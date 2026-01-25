import os
import base64
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from email import message_from_bytes
from weasyprint import HTML
import pickle

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive.file'
]

DRIVE_FOLDER_ID = 'your-drive-folder-id'
GMAIL_QUERY = 'is:unread label:save-to-drive'  # Customize this filter

def get_credentials():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

def get_message_content(service, msg_id):
    message = service.users().messages().get(
        userId='me', id=msg_id, format='full'
    ).execute()
    return message

def extract_pdf_attachments(service, message, drive_service):
    """Extract and upload PDF attachments."""
    parts = message.get('payload', {}).get('parts', [])
    
    for part in parts:
        filename = part.get('filename', '')
        if filename.lower().endswith('.pdf'):
            attachment_id = part['body'].get('attachmentId')
            if attachment_id:
                attachment = service.users().messages().attachments().get(
                    userId='me', messageId=message['id'], id=attachment_id
                ).execute()
                file_data = base64.urlsafe_b64decode(attachment['data'])
                
                # Save temporarily and upload
                temp_path = f'/tmp/{filename}'
                with open(temp_path, 'wb') as f:
                    f.write(file_data)
                upload_to_drive(drive_service, temp_path, filename)
                os.remove(temp_path)

def email_to_pdf(service, message, drive_service):
    """Convert email body to PDF and upload."""
    headers = {h['name']: h['value'] for h in message['payload']['headers']}
    subject = headers.get('Subject', 'No Subject')
    sender = headers.get('From', 'Unknown')
    date = headers.get('Date', '')
    
    # Get body
    body_html = get_body(message['payload'])
    
    # Create HTML document
    html_content = f"""
    <html>
    <head><meta charset="utf-8"></head>
    <body>
        <h2>{subject}</h2>
        <p><strong>From:</strong> {sender}<br>
        <strong>Date:</strong> {date}</p>
        <hr>
        {body_html}
    </body>
    </html>
    """
    
    # Convert to PDF
    filename = f"{subject[:50].replace('/', '-')}.pdf"
    temp_path = f'/tmp/{filename}'
    HTML(string=html_content).write_pdf(temp_path)
    upload_to_drive(drive_service, temp_path, filename)
    os.remove(temp_path)

def get_body(payload):
    """Recursively extract email body."""
    if 'body' in payload and payload['body'].get('data'):
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/html':
                if part['body'].get('data'):
                    return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
            elif part['mimeType'].startswith('multipart'):
                return get_body(part)
    return ''

def upload_to_drive(drive_service, file_path, filename):
    file_metadata = {
        'name': filename,
        'parents': [DRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(file_path, mimetype='application/pdf')
    drive_service.files().create(
        body=file_metadata, media_body=media, fields='id'
    ).execute()
    print(f"Uploaded: {filename}")

def mark_as_read(service, msg_id):
    service.users().messages().modify(
        userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}
    ).execute()

def main():
    creds = get_credentials()
    gmail = build('gmail', 'v1', credentials=creds)
    drive = build('drive', 'v3', credentials=creds)
    
    results = gmail.users().messages().list(userId='me', q=GMAIL_QUERY).execute()
    messages = results.get('messages', [])
    
    for msg in messages:
        message = get_message_content(gmail, msg['id'])
        extract_pdf_attachments(gmail, message, drive)
        email_to_pdf(gmail, message, drive)
        mark_as_read(gmail, msg['id'])

if __name__ == '__main__':
    main()
