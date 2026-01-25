#!/usr/bin/env python3
"""
Fetch bills from Gmail and upload to Google Drive for payme processing.

This script:
1. Searches Gmail for emails with the configured label (default: 'save-to-drive')
2. Extracts PDF attachments and uploads them to the payme Drive folder
3. Converts email body to PDF and uploads (for emails without PDF attachments)
4. Marks processed emails as read

Usage:
    python3 fetch_email_bills.py           # Process all matching emails
    python3 fetch_email_bills.py --dry-run # Show what would be processed
    python3 fetch_email_bills.py --status  # Show processing status

Requires:
    pip install xhtml2pdf
"""

import argparse
import base64
import html
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import (
    PROCESSED_EMAILS_FILE,
    GMAIL_LABEL,
    get_env,
    ensure_directories,
)
from storage import load_json, save_json
from google_drive import get_valid_access_token, get_album_id
from http_client import get_json, post_json, HttpError

# Gmail API base
GMAIL_API_BASE = 'https://gmail.googleapis.com/gmail/v1'

# Google Drive API base
DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3'
DRIVE_UPLOAD_BASE = 'https://www.googleapis.com/upload/drive/v3'


def get_processed_emails() -> set:
    """Load set of processed email IDs."""
    data = load_json(PROCESSED_EMAILS_FILE, {'processed': []})
    return set(data.get('processed', []))


def mark_email_processed(email_id: str) -> None:
    """Add email ID to processed set."""
    data = load_json(PROCESSED_EMAILS_FILE, {'processed': []})
    processed = set(data.get('processed', []))
    processed.add(email_id)
    data['processed'] = list(processed)
    save_json(PROCESSED_EMAILS_FILE, data)


def gmail_get(endpoint: str, access_token: str, params: dict = None) -> dict:
    """Make GET request to Gmail API."""
    url = f'{GMAIL_API_BASE}{endpoint}'
    if params:
        from urllib.parse import urlencode
        url = f'{url}?{urlencode(params)}'

    return get_json(
        url,
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=30,
    )


def gmail_post(endpoint: str, access_token: str, json_data: dict) -> dict:
    """Make POST request to Gmail API."""
    url = f'{GMAIL_API_BASE}{endpoint}'

    return post_json(
        url,
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        },
        json=json_data,
        timeout=30,
    )


def list_matching_emails(access_token: str) -> list[dict]:
    """
    List emails matching the configured label.

    Returns list of {'id': ..., 'threadId': ...} dicts.
    """
    query = f'is:unread label:{GMAIL_LABEL}'

    result = gmail_get(
        '/users/me/messages',
        access_token,
        params={'q': query, 'maxResults': 50},
    )

    return result.get('messages', [])


def get_message(access_token: str, message_id: str) -> dict:
    """Get full message details."""
    return gmail_get(
        f'/users/me/messages/{message_id}',
        access_token,
        params={'format': 'full'},
    )


def get_attachment(access_token: str, message_id: str, attachment_id: str) -> bytes:
    """Download attachment data."""
    result = gmail_get(
        f'/users/me/messages/{message_id}/attachments/{attachment_id}',
        access_token,
    )

    data = result.get('data', '')
    return base64.urlsafe_b64decode(data)


def mark_as_read(access_token: str, message_id: str) -> None:
    """Remove UNREAD label from message."""
    gmail_post(
        f'/users/me/messages/{message_id}/modify',
        access_token,
        json_data={'removeLabelIds': ['UNREAD']},
    )


def extract_headers(message: dict) -> dict:
    """Extract common headers from message."""
    headers = {}
    for header in message.get('payload', {}).get('headers', []):
        name = header.get('name', '').lower()
        if name in ('from', 'to', 'subject', 'date'):
            headers[name] = header.get('value', '')
    return headers


def extract_body(payload: dict) -> str:
    """Recursively extract HTML body from message payload."""
    # Direct body
    body = payload.get('body', {})
    if body.get('data'):
        data = base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')
        return data

    # Check parts
    parts = payload.get('parts', [])
    for part in parts:
        mime_type = part.get('mimeType', '')

        # Prefer HTML
        if mime_type == 'text/html':
            body = part.get('body', {})
            if body.get('data'):
                return base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')

        # Recurse into multipart
        if mime_type.startswith('multipart'):
            result = extract_body(part)
            if result:
                return result

    # Fall back to plain text
    for part in parts:
        if part.get('mimeType') == 'text/plain':
            body = part.get('body', {})
            if body.get('data'):
                text = base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')
                # Convert plain text to basic HTML
                return f'<pre>{html.escape(text)}</pre>'

    return ''


def find_pdf_attachments(payload: dict) -> list[dict]:
    """Find all PDF attachments in message."""
    attachments = []

    parts = payload.get('parts', [])
    for part in parts:
        filename = part.get('filename', '')
        if filename.lower().endswith('.pdf'):
            attachment_id = part.get('body', {}).get('attachmentId')
            if attachment_id:
                attachments.append({
                    'filename': filename,
                    'attachment_id': attachment_id,
                })

        # Recurse into nested parts
        if part.get('parts'):
            attachments.extend(find_pdf_attachments(part))

    return attachments


def upload_to_drive(access_token: str, folder_id: str, filename: str, file_data: bytes) -> str:
    """
    Upload file to Google Drive.

    Returns the file ID.
    """
    import requests

    # Create metadata
    metadata = {
        'name': filename,
        'parents': [folder_id],
    }

    # Multipart upload
    url = f'{DRIVE_UPLOAD_BASE}/files?uploadType=multipart'

    # Build multipart body
    boundary = '----payme_upload_boundary'

    body = (
        f'--{boundary}\r\n'
        f'Content-Type: application/json; charset=UTF-8\r\n\r\n'
        f'{json.dumps(metadata)}\r\n'
        f'--{boundary}\r\n'
        f'Content-Type: application/pdf\r\n\r\n'
    ).encode('utf-8') + file_data + f'\r\n--{boundary}--'.encode('utf-8')

    response = requests.post(
        url,
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': f'multipart/related; boundary={boundary}',
        },
        data=body,
        timeout=60,
    )

    if response.status_code not in (200, 201):
        raise HttpError(f'Drive upload failed: {response.status_code} {response.text}')

    return response.json().get('id', '')


def email_to_pdf(headers: dict, body_html: str) -> bytes:
    """
    Convert email to PDF.

    Uses xhtml2pdf for pure Python PDF generation.
    """
    from xhtml2pdf import pisa
    from io import BytesIO

    subject = html.escape(headers.get('subject', 'No Subject'))
    sender = html.escape(headers.get('from', 'Unknown'))
    date = html.escape(headers.get('date', ''))

    # Wrap body in a complete HTML document
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #f5f5f5; padding: 15px; margin-bottom: 20px; }}
        .header h2 {{ margin: 0 0 10px 0; }}
        .meta {{ color: #666; font-size: 0.9em; }}
        .body {{ line-height: 1.5; }}
        hr {{ border: none; border-top: 1px solid #ddd; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>{subject}</h2>
        <div class="meta">
            <strong>From:</strong> {sender}<br>
            <strong>Date:</strong> {date}
        </div>
    </div>
    <hr>
    <div class="body">
        {body_html}
    </div>
</body>
</html>"""

    # Convert to PDF
    output = BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=output)

    if pisa_status.err:
        raise ValueError(f'PDF generation failed: {pisa_status.err}')

    return output.getvalue()


def sanitize_filename(name: str) -> str:
    """Create a safe filename from string."""
    # Remove/replace problematic characters
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(char, '-')
    # Limit length
    return name[:100].strip()


def process_email(access_token: str, folder_id: str, message_id: str, dry_run: bool = False) -> dict:
    """
    Process a single email.

    Returns dict with processing results.
    """
    result = {
        'id': message_id,
        'subject': '',
        'pdf_attachments': 0,
        'body_pdf': False,
        'uploaded': [],
        'error': None,
    }

    try:
        # Get full message
        message = get_message(access_token, message_id)
        headers = extract_headers(message)
        result['subject'] = headers.get('subject', 'No Subject')

        payload = message.get('payload', {})

        # Find PDF attachments
        attachments = find_pdf_attachments(payload)
        result['pdf_attachments'] = len(attachments)

        if dry_run:
            if attachments:
                result['uploaded'] = [a['filename'] for a in attachments]
            else:
                result['body_pdf'] = True
                result['uploaded'] = [f"{sanitize_filename(result['subject'])}.pdf"]
            return result

        # Process attachments or body
        if attachments:
            # Upload PDF attachments
            for att in attachments:
                pdf_data = get_attachment(access_token, message_id, att['attachment_id'])
                file_id = upload_to_drive(access_token, folder_id, att['filename'], pdf_data)
                result['uploaded'].append(att['filename'])
                print(f"  Uploaded attachment: {att['filename']}")
        else:
            # Convert email body to PDF
            body_html = extract_body(payload)
            if body_html:
                pdf_data = email_to_pdf(headers, body_html)
                filename = f"{sanitize_filename(result['subject'])}.pdf"
                file_id = upload_to_drive(access_token, folder_id, filename, pdf_data)
                result['body_pdf'] = True
                result['uploaded'].append(filename)
                print(f"  Uploaded email as PDF: {filename}")

        # Mark as read
        mark_as_read(access_token, message_id)

        # Mark as processed locally
        mark_email_processed(message_id)

    except Exception as e:
        result['error'] = str(e)
        print(f"  Error: {e}")

    return result


def fetch_email_bills(dry_run: bool = False) -> dict:
    """
    Main function to fetch and process email bills.

    Returns dict with processing summary.
    """
    ensure_directories()

    summary = {
        'emails_found': 0,
        'emails_processed': 0,
        'emails_skipped': 0,
        'files_uploaded': 0,
        'errors': [],
    }

    # Get access token
    print('Getting access token...')
    try:
        access_token = get_valid_access_token()
    except HttpError as e:
        summary['errors'].append(f'Auth failed: {e}')
        return summary

    # Get Drive folder ID
    print('Getting Drive folder ID...')
    try:
        folder_id = get_album_id()
    except Exception as e:
        summary['errors'].append(f'Failed to get folder ID: {e}')
        return summary

    print(f'Using Drive folder: {folder_id}')

    # Get already processed emails
    processed = get_processed_emails()

    # List matching emails
    print(f'Searching for emails with label: {GMAIL_LABEL}')
    try:
        emails = list_matching_emails(access_token)
    except HttpError as e:
        summary['errors'].append(f'Gmail search failed: {e}')
        return summary

    summary['emails_found'] = len(emails)
    print(f'Found {len(emails)} matching emails')

    if dry_run:
        print('\n--- DRY RUN MODE ---\n')

    # Process each email
    for email in emails:
        email_id = email['id']

        # Skip already processed
        if email_id in processed:
            print(f'Skipping already processed: {email_id}')
            summary['emails_skipped'] += 1
            continue

        print(f'\nProcessing email: {email_id}')
        result = process_email(access_token, folder_id, email_id, dry_run=dry_run)

        if result['error']:
            summary['errors'].append(f"{result['subject']}: {result['error']}")
        else:
            summary['emails_processed'] += 1
            summary['files_uploaded'] += len(result['uploaded'])

            if dry_run:
                print(f"  Subject: {result['subject']}")
                print(f"  Would upload: {', '.join(result['uploaded'])}")

    return summary


def show_status():
    """Show current processing status."""
    processed = get_processed_emails()
    print(f'Processed emails: {len(processed)}')

    if processed:
        print('\nRecent processed IDs:')
        for email_id in list(processed)[-10:]:
            print(f'  {email_id}')


def main():
    parser = argparse.ArgumentParser(
        description='Fetch bills from Gmail and upload to Drive',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f'''
Setup:
  1. Create a Gmail label called '{GMAIL_LABEL}'
  2. Apply this label to emails containing bills
  3. Re-run authorize_google.py to add Gmail permissions
  4. Run this script to process labeled emails

The script will:
  - Extract PDF attachments from labeled emails
  - Convert email body to PDF if no attachments
  - Upload PDFs to the payme Drive folder
  - Mark emails as read after processing
        '''
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without making changes',
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show processing status',
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    print('='*50)
    print('payme Email Bill Fetcher')
    print('='*50)

    summary = fetch_email_bills(dry_run=args.dry_run)

    print('\n' + '='*50)
    print('Summary')
    print('='*50)
    print(f"Emails found:     {summary['emails_found']}")
    print(f"Emails processed: {summary['emails_processed']}")
    print(f"Emails skipped:   {summary['emails_skipped']}")
    print(f"Files uploaded:   {summary['files_uploaded']}")

    if summary['errors']:
        print(f"\nErrors ({len(summary['errors'])}):")
        for error in summary['errors']:
            print(f"  - {error}")
        sys.exit(1)

    print('\nDone!')


if __name__ == '__main__':
    main()
