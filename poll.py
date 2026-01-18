#!/usr/bin/env python3
"""
Main entry point and orchestration for payme.

This is the only entry point - all other modules are libraries.
Called by Home Assistant shell_command or pyscript.
"""

import json
import sys
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import (
    PAYMENT_HISTORY_FILE,
    CONFIDENCE_THRESHOLD,
    ensure_directories,
)
from storage import load_json, save_json, append_to_list, backup_file
from formatting import format_currency, format_iban
from iban import validate_iban, get_iban_info
from dedup import is_duplicate, record_payment, check_similar
from girocode import extract_girocode, extract_girocode_from_bytes, check_dependencies as girocode_available
from gemini import parse_bill_image, parse_bill_images, parse_bill_bytes, ParsedBill
from google_photos import (
    get_new_photos,
    group_photos_by_time,
    download_photo,
    mark_photo_processed,
    check_token_health,
)
from wise import (
    get_eur_balance,
    check_sufficient_balance,
    execute_payment,
    get_transfer,
    list_transfers_needing_2fa,
)
from notify import (
    notify_pending_bill,
    notify_payment_sent,
    notify_payment_rejected,
    notify_insufficient_balance,
    notify_2fa_required,
    notify_parse_error,
    notify_google_auth_expiring,
    notify_poll_complete,
    clear_bill_notification,
)
from http_client import HttpError


@dataclass
class Bill:
    """Pending bill awaiting approval."""
    id: str
    recipient: str
    iban: str
    bic: str
    amount: float
    currency: str
    reference: str
    bank_name: str
    confidence: float
    source: str  # 'girocode' or 'gemini'
    photo_ids: list[str] = field(default_factory=list)
    created_at: str = ''
    due_date: str = ''
    invoice_number: str = ''
    description: str = ''
    original_text: str = ''
    english_translation: str = ''
    status: str = 'pending'  # pending, approved, rejected, paid, failed
    paid_at: str = ''
    duplicate_warning: bool = False
    low_confidence: bool = False
    error: str = ''

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Bill':
        return cls(**data)


class PollResult:
    """Results from a poll operation."""

    def __init__(self):
        self.new_photos = 0
        self.bills_created = 0
        self.bills_processed = 0
        self.errors = []
        self.bills = []

    def add_error(self, error: str):
        self.errors.append(error)

    def to_dict(self) -> dict:
        return {
            'new_photos': self.new_photos,
            'bills_created': self.bills_created,
            'bills_processed': self.bills_processed,
            'errors': self.errors,
            'bills': [b.to_dict() for b in self.bills],
        }


def generate_bill_id() -> str:
    """Generate unique bill ID."""
    return str(uuid.uuid4())[:8]


def load_pending_bills() -> list[Bill]:
    """Load pending bills from storage."""
    data = load_json(PAYMENT_HISTORY_FILE, {'pending': [], 'history': []})
    return [Bill.from_dict(b) for b in data.get('pending', [])]


def save_pending_bills(bills: list[Bill]) -> None:
    """Save pending bills to storage."""
    data = load_json(PAYMENT_HISTORY_FILE, {'pending': [], 'history': []})
    data['pending'] = [b.to_dict() for b in bills]
    save_json(PAYMENT_HISTORY_FILE, data)


def add_to_history(bill: Bill) -> None:
    """Add bill to payment history."""
    data = load_json(PAYMENT_HISTORY_FILE, {'pending': [], 'history': []})
    data['history'].append(bill.to_dict())
    save_json(PAYMENT_HISTORY_FILE, data)


def move_to_history(bill: Bill) -> None:
    """Remove from pending and add to history in one atomic operation."""
    data = load_json(PAYMENT_HISTORY_FILE, {'pending': [], 'history': []})
    # Remove from pending
    data['pending'] = [b for b in data['pending'] if b.get('id') != bill.id]
    # Add to history
    data['history'].append(bill.to_dict())
    save_json(PAYMENT_HISTORY_FILE, data)


def get_pending_bill(bill_id: str) -> Optional[Bill]:
    """Get pending bill by ID."""
    bills = load_pending_bills()
    for bill in bills:
        if bill.id == bill_id:
            return bill
    return None


def remove_pending_bill(bill_id: str) -> Optional[Bill]:
    """Remove bill from pending list. Returns removed bill or None."""
    bills = load_pending_bills()
    for i, bill in enumerate(bills):
        if bill.id == bill_id:
            removed = bills.pop(i)
            save_pending_bills(bills)
            return removed
    return None


def process_photo_group(photos: list[dict]) -> Optional[Bill]:
    """
    Process a group of photos (potentially multi-page bill).

    1. Download photos
    2. Try GiroCode detection
    3. Fall back to Gemini OCR
    4. Validate and enrich data
    5. Create Bill object

    Returns Bill or None on failure.
    """
    if not photos:
        return None

    bill_id = generate_bill_id()
    photo_ids = [p['id'] for p in photos]

    # Download photos
    downloaded_images = []
    temp_files = []

    try:
        for photo in photos:
            image_data = download_photo(photo, size='large')
            downloaded_images.append((image_data, photo.get('mimeType', 'image/jpeg')))

            # Save to temp file for girocode/gemini
            temp_file = tempfile.NamedTemporaryFile(
                suffix='.jpg',
                delete=False,
            )
            temp_file.write(image_data)
            temp_file.close()
            temp_files.append(Path(temp_file.name))

        # Try GiroCode detection first (more reliable)
        girocode_data = None
        if girocode_available():
            for i, (image_data, mime_type) in enumerate(downloaded_images):
                try:
                    girocode_data = extract_girocode_from_bytes(image_data)
                    if girocode_data:
                        break
                except Exception:
                    continue

        # Initialize optional fields
        due_date = ''
        invoice_number = ''
        description = ''
        original_text = ''
        english_translation = ''

        if girocode_data:
            # Use GiroCode data
            iban = girocode_data.iban
            recipient = girocode_data.recipient
            bic = girocode_data.bic
            amount = girocode_data.amount
            currency = girocode_data.currency
            reference = girocode_data.reference or girocode_data.text
            confidence = 1.0  # GiroCode is deterministic
            source = 'girocode'
        else:
            # Fall back to Gemini OCR
            if len(temp_files) == 1:
                parsed = parse_bill_image(temp_files[0])
            else:
                parsed = parse_bill_images(temp_files)

            iban = parsed.iban
            recipient = parsed.recipient
            bic = parsed.bic
            amount = parsed.amount
            currency = parsed.currency
            reference = parsed.reference
            confidence = parsed.overall_confidence
            source = 'gemini'
            due_date = parsed.due_date
            invoice_number = parsed.invoice_number
            description = parsed.description
            original_text = parsed.original_text
            english_translation = parsed.english_translation

        # Validate IBAN
        iban_info = get_iban_info(iban)
        if not iban_info['valid']:
            raise ValueError(f"Invalid IBAN: {iban_info['error']}")

        # Get bank name
        bank_name = iban_info['bank']['name']
        if not bic:
            bic = iban_info['bank']['bic']

        # Check for duplicates
        is_dup, dup_info = is_duplicate(iban, amount, reference)
        duplicate_warning = is_dup

        # Check for similar payments
        if not duplicate_warning:
            similar = check_similar(iban, amount)
            if similar:
                duplicate_warning = True

        # Create bill
        bill = Bill(
            id=bill_id,
            recipient=recipient,
            iban=iban,
            bic=bic,
            amount=amount,
            currency=currency,
            reference=reference,
            bank_name=bank_name,
            confidence=confidence,
            source=source,
            photo_ids=photo_ids,
            created_at=datetime.now().isoformat(),
            due_date=due_date,
            invoice_number=invoice_number,
            description=description,
            original_text=original_text,
            english_translation=english_translation,
            status='pending',
            duplicate_warning=duplicate_warning,
            low_confidence=confidence < CONFIDENCE_THRESHOLD,
        )

        return bill

    finally:
        # Cleanup temp files
        for temp_file in temp_files:
            try:
                temp_file.unlink()
            except Exception:
                pass


def poll_for_new_bills() -> PollResult:
    """
    Main poll function - check for new photos and create pending bills.

    Returns PollResult with stats and any new bills.
    """
    result = PollResult()
    ensure_directories()

    # Check Google auth health
    auth_health = check_token_health()
    if auth_health['status'] == 'missing':
        result.add_error('Google auth not configured')
        return result
    if auth_health['status'] == 'expiring':
        notify_google_auth_expiring()
    if auth_health['status'] == 'expired':
        result.add_error('Google auth expired')
        notify_google_auth_expiring()
        return result

    # Get new photos
    try:
        new_photos = get_new_photos()
    except HttpError as e:
        result.add_error(f'Failed to fetch photos: {e}')
        return result

    result.new_photos = len(new_photos)

    if not new_photos:
        return result

    # Group photos by time (multi-page bills)
    photo_groups = group_photos_by_time(new_photos)

    # Process each group
    pending_bills = load_pending_bills()

    for group in photo_groups:
        try:
            bill = process_photo_group(group)

            if bill:
                # Add to pending
                pending_bills.append(bill)
                result.bills.append(bill)
                result.bills_created += 1

                # Send notification
                notify_pending_bill(
                    bill_id=bill.id,
                    recipient=bill.recipient,
                    bank_name=bill.bank_name,
                    iban=bill.iban,
                    amount=bill.amount,
                    currency=bill.currency,
                    reference=bill.reference,
                    confidence=bill.confidence,
                )

            # Mark photos as processed
            for photo in group:
                mark_photo_processed(photo['id'])

            result.bills_processed += 1

        except Exception as e:
            error_msg = str(e)
            result.add_error(f'Failed to process bill: {error_msg}')

            # Still mark as processed to avoid infinite retries
            for photo in group:
                mark_photo_processed(photo['id'])

            # Notify about parse error
            filename = group[0].get('filename', 'unknown') if group else 'unknown'
            notify_parse_error(filename, error_msg)

    # Save pending bills
    save_pending_bills(pending_bills)

    # Backup history file
    backup_file(PAYMENT_HISTORY_FILE)

    # Send poll summary notification
    notify_poll_complete(
        new_bills=result.bills_created,
        processed=result.bills_processed,
        errors=len(result.errors),
    )

    return result


def approve_bill(bill_id: str) -> dict:
    """
    Approve a pending bill and execute payment.

    Returns dict with success status and any error.
    """
    result = {
        'success': False,
        'error': None,
        'transfer_id': None,
        'status': None,
    }

    bill = get_pending_bill(bill_id)
    if not bill:
        result['error'] = f'Bill not found: {bill_id}'
        return result

    # Check balance
    if not check_sufficient_balance(bill.amount, bill.currency):
        balance = get_eur_balance()
        notify_insufficient_balance(bill.amount, balance, bill.currency)
        result['error'] = f'Insufficient balance'
        result['status'] = 'insufficient_balance'
        return result

    # Execute payment
    payment_result = execute_payment(
        iban=bill.iban,
        name=bill.recipient,
        amount=bill.amount,
        reference=bill.reference,
        currency=bill.currency,
    )

    if payment_result['success']:
        # Record for deduplication
        record_payment(bill.iban, bill.amount, bill.reference)

        # Update bill status
        bill.status = 'paid'
        bill.paid_at = datetime.now().isoformat()
        result['success'] = True
        result['transfer_id'] = payment_result.get('transfer_id')
        result['status'] = payment_result.get('status')

        # Check if needs 2FA
        if payment_result.get('needs_2fa'):
            bill.status = 'awaiting_2fa'
            notify_2fa_required(
                transfer_id=payment_result['transfer_id'],
                recipient=bill.recipient,
                amount=bill.amount,
                currency=bill.currency,
            )
        else:
            notify_payment_sent(
                recipient=bill.recipient,
                amount=bill.amount,
                currency=bill.currency,
                reference=bill.reference,
            )

        # Move to history
        remove_pending_bill(bill_id)
        add_to_history(bill)
        clear_bill_notification(bill_id)

    else:
        bill.status = 'failed'
        bill.error = payment_result.get('error', 'Unknown error')
        result['error'] = bill.error

        # Keep in pending with error status
        bills = load_pending_bills()
        for i, b in enumerate(bills):
            if b.id == bill_id:
                bills[i] = bill
                break
        save_pending_bills(bills)

    return result


def reject_bill(bill_id: str) -> dict:
    """
    Reject a pending bill.

    Returns dict with success status.
    """
    result = {
        'success': False,
        'error': None,
    }

    bill = remove_pending_bill(bill_id)
    if not bill:
        result['error'] = f'Bill not found: {bill_id}'
        return result

    bill.status = 'rejected'
    add_to_history(bill)
    clear_bill_notification(bill_id)

    notify_payment_rejected(
        recipient=bill.recipient,
        amount=bill.amount,
        currency=bill.currency,
    )

    result['success'] = True
    return result


def override_duplicate(bill_id: str) -> dict:
    """
    Override duplicate warning for a bill.

    Returns dict with success status.
    """
    result = {
        'success': False,
        'error': None,
    }

    bills = load_pending_bills()
    for i, bill in enumerate(bills):
        if bill.id == bill_id:
            bills[i].duplicate_warning = False
            save_pending_bills(bills)
            result['success'] = True
            return result

    result['error'] = f'Bill not found: {bill_id}'
    return result


def set_bill_status(bill_id: str, status: str) -> dict:
    """
    Manually set a bill's status.

    Args:
        bill_id: The bill ID to update
        status: New status value

    Returns dict with success status.
    """
    valid_statuses = [
        'pending', 'paid', 'rejected', 'failed',
        'processing', 'awaiting_2fa', 'insufficient_balance'
    ]

    result = {
        'success': False,
        'error': None,
        'bill_id': bill_id,
        'new_status': status,
    }

    if status not in valid_statuses:
        result['error'] = f'Invalid status: {status}. Valid: {", ".join(valid_statuses)}'
        return result

    # Check pending bills first
    bills = load_pending_bills()
    for i, bill in enumerate(bills):
        if bill.id == bill_id:
            old_status = bills[i].status
            bills[i].status = status

            # If marking as paid, set paid_at timestamp
            if status == 'paid' and not bills[i].paid_at:
                bills[i].paid_at = datetime.now().isoformat()

            save_pending_bills(bills)

            # If marked as paid/rejected/failed, move to history
            if status in ('paid', 'rejected', 'failed'):
                move_to_history(bills[i])

            result['success'] = True
            result['old_status'] = old_status
            return result

    # Check history if not found in pending
    history = load_json(PAYMENT_HISTORY_FILE, {'history': []})
    for i, entry in enumerate(history.get('history', [])):
        if entry.get('id') == bill_id:
            old_status = entry.get('status')
            history['history'][i]['status'] = status

            if status == 'paid' and not entry.get('paid_at'):
                history['history'][i]['paid_at'] = datetime.now().isoformat()

            save_json(PAYMENT_HISTORY_FILE, history)

            result['success'] = True
            result['old_status'] = old_status
            return result

    result['error'] = f'Bill not found: {bill_id}'
    return result


def check_2fa_transfers() -> list[dict]:
    """
    Check for transfers waiting for 2FA.

    Returns list of transfers needing approval.
    """
    try:
        transfers = list_transfers_needing_2fa()
        return [
            {
                'id': t.id,
                'recipient': t.recipient_name,
                'amount': t.target_amount,
                'currency': t.target_currency,
                'reference': t.reference,
            }
            for t in transfers
        ]
    except HttpError:
        return []


def get_status() -> dict:
    """
    Get current payme status.

    Returns dict with pending bills, balance, auth status, etc.
    """
    status = {
        'pending_bills': [],
        'balance': None,
        'auth_status': None,
        'awaiting_2fa': [],
    }

    # Pending bills
    try:
        bills = load_pending_bills()
        status['pending_bills'] = [b.to_dict() for b in bills]
    except Exception as e:
        status['pending_bills_error'] = str(e)

    # Balance
    try:
        status['balance'] = get_eur_balance()
    except Exception as e:
        status['balance_error'] = str(e)

    # Auth status
    try:
        status['auth_status'] = check_token_health()
    except Exception as e:
        status['auth_error'] = str(e)

    # 2FA transfers
    try:
        status['awaiting_2fa'] = check_2fa_transfers()
    except Exception as e:
        status['2fa_error'] = str(e)

    return status


def main():
    """Command-line interface."""
    import argparse

    parser = argparse.ArgumentParser(description='payme bill payment automation')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Poll command
    subparsers.add_parser('poll', help='Poll for new bills')

    # Status command
    subparsers.add_parser('status', help='Get current status')

    # Approve command
    approve_parser = subparsers.add_parser('approve', help='Approve a pending bill')
    approve_parser.add_argument('bill_id', help='Bill ID to approve')

    # Reject command
    reject_parser = subparsers.add_parser('reject', help='Reject a pending bill')
    reject_parser.add_argument('bill_id', help='Bill ID to reject')

    # Override duplicate command
    override_parser = subparsers.add_parser('override-duplicate', help='Override duplicate warning')
    override_parser.add_argument('bill_id', help='Bill ID')

    # Set status command
    set_status_parser = subparsers.add_parser('set-status', help='Manually set bill status')
    set_status_parser.add_argument('bill_id', help='Bill ID')
    set_status_parser.add_argument('status', help='New status (pending, paid, rejected, failed, processing, awaiting_2fa, insufficient_balance)')

    # List pending command
    subparsers.add_parser('list', help='List pending bills')

    args = parser.parse_args()

    if args.command == 'poll':
        print('Polling for new bills...')
        result = poll_for_new_bills()
        print(json.dumps(result.to_dict(), indent=2))

    elif args.command == 'status':
        status = get_status()
        print(json.dumps(status, indent=2))

    elif args.command == 'approve':
        result = approve_bill(args.bill_id)
        print(json.dumps(result, indent=2))

    elif args.command == 'reject':
        result = reject_bill(args.bill_id)
        print(json.dumps(result, indent=2))

    elif args.command == 'override-duplicate':
        result = override_duplicate(args.bill_id)
        print(json.dumps(result, indent=2))

    elif args.command == 'set-status':
        result = set_bill_status(args.bill_id, args.status)
        print(json.dumps(result, indent=2))

    elif args.command == 'list':
        bills = load_pending_bills()
        for bill in bills:
            status_icon = '⚠️' if bill.duplicate_warning or bill.low_confidence else '📄'
            print(f'{status_icon} [{bill.id}] {bill.recipient}: {format_currency(bill.amount, bill.currency)}')
            print(f'   IBAN: {format_iban(bill.iban)}')
            print(f'   Ref: {bill.reference[:50]}')
            print()
        if not bills:
            print('No pending bills')

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
