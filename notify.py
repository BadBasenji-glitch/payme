#!/usr/bin/env python3
"""Home Assistant notification calls for payme."""

from typing import Optional

from config import get_env
from http_client import post_json, HttpError
from formatting import format_currency, format_iban

# HA API endpoints
HA_API_BASE = 'http://supervisor/core/api'  # Inside HA container
HA_API_FALLBACK = 'http://localhost:8123/api'  # External access


def get_ha_token() -> str:
    """Get Home Assistant long-lived access token."""
    # Inside HA, SUPERVISOR_TOKEN is available
    token = get_env('SUPERVISOR_TOKEN', '')
    if token:
        return token

    # Fallback to configured token
    return get_env('PAYME_HA_TOKEN', required=True)


def get_ha_api_base() -> str:
    """Get HA API base URL."""
    # Check if running inside HA
    if get_env('SUPERVISOR_TOKEN', ''):
        return HA_API_BASE
    return get_env('PAYME_HA_API_URL', HA_API_FALLBACK)


def get_notify_service() -> str:
    """Get notification service name."""
    return get_env('PAYME_NOTIFY_SERVICE', 'mobile_app_phone')


def call_ha_service(domain: str, service: str, data: dict) -> dict:
    """
    Call a Home Assistant service.

    Args:
        domain: Service domain (e.g., 'notify', 'persistent_notification')
        service: Service name (e.g., 'mobile_app_phone')
        data: Service data

    Returns:
        Response dict
    """
    url = f'{get_ha_api_base()}/services/{domain}/{service}'
    headers = {
        'Authorization': f'Bearer {get_ha_token()}',
        'Content-Type': 'application/json',
    }

    return post_json(url, headers=headers, json=data, timeout=10)


def send_notification(
    title: str,
    message: str,
    data: dict = None,
    service: str = None,
) -> bool:
    """
    Send notification via Home Assistant.

    Args:
        title: Notification title
        message: Notification body
        data: Additional notification data (actions, etc.)
        service: Override notification service name

    Returns:
        True if sent successfully
    """
    if service is None:
        service = get_notify_service()

    payload = {
        'title': title,
        'message': message,
    }
    if data:
        payload['data'] = data

    try:
        call_ha_service('notify', service, payload)
        return True
    except HttpError:
        return False


def send_persistent_notification(
    title: str,
    message: str,
    notification_id: str = None,
) -> bool:
    """
    Create a persistent notification in HA dashboard.

    Args:
        title: Notification title
        message: Notification body
        notification_id: Optional ID for updating/dismissing

    Returns:
        True if created successfully
    """
    payload = {
        'title': title,
        'message': message,
    }
    if notification_id:
        payload['notification_id'] = notification_id

    try:
        call_ha_service('persistent_notification', 'create', payload)
        return True
    except HttpError:
        return False


def dismiss_persistent_notification(notification_id: str) -> bool:
    """Dismiss a persistent notification by ID."""
    try:
        call_ha_service('persistent_notification', 'dismiss', {
            'notification_id': notification_id,
        })
        return True
    except HttpError:
        return False


def mask_iban(iban: str) -> str:
    """Mask IBAN for display, showing only first 4 and last 4 chars."""
    iban = iban.replace(' ', '').upper()
    if len(iban) <= 8:
        return iban
    return f'{iban[:4]}...{iban[-4:]}'


def notify_pending_bill(
    bill_id: str,
    recipient: str,
    bank_name: str,
    iban: str,
    amount: float,
    currency: str,
    reference: str,
    confidence: float,
) -> bool:
    """
    Send notification for pending bill approval.

    Includes actionable buttons for approve/reject.
    """
    title = f'💶 Bill: {format_currency(amount, currency)}'

    message = (
        f'Recipient: {recipient}\n'
        f'Bank: {bank_name}\n'
        f'IBAN: {mask_iban(iban)}\n'
        f'Reference: {reference[:50]}'
    )

    if confidence < 0.9:
        message += f'\n⚠️ Low confidence: {confidence:.0%}'

    data = {
        'actions': [
            {
                'action': f'PAYME_APPROVE_{bill_id}',
                'title': '✓ Approve',
            },
            {
                'action': f'PAYME_REJECT_{bill_id}',
                'title': '✗ Reject',
            },
            {
                'action': f'PAYME_VIEW_{bill_id}',
                'title': 'View Details',
            },
        ],
        'tag': f'payme_bill_{bill_id}',
        'group': 'payme_bills',
        # iOS specific
        'push': {
            'category': 'payme_bill',
        },
        # Android specific
        'channel': 'payme_bills',
        'importance': 'high',
        'sticky': True,
    }

    return send_notification(title, message, data)


def notify_payment_sent(
    recipient: str,
    amount: float,
    currency: str,
    reference: str,
) -> bool:
    """Send notification that payment was sent."""
    title = '✓ Payment Sent'
    message = (
        f'{format_currency(amount, currency)} to {recipient}\n'
        f'Ref: {reference[:50]}'
    )

    data = {
        'tag': 'payme_payment_sent',
        'group': 'payme_status',
    }

    return send_notification(title, message, data)


def notify_payment_rejected(
    recipient: str,
    amount: float,
    currency: str,
) -> bool:
    """Send notification that payment was rejected."""
    title = '✗ Payment Rejected'
    message = f'{format_currency(amount, currency)} to {recipient}'

    data = {
        'tag': 'payme_payment_rejected',
        'group': 'payme_status',
    }

    return send_notification(title, message, data)


def notify_insufficient_balance(
    amount_needed: float,
    balance_available: float,
    currency: str = 'EUR',
) -> bool:
    """Send notification about insufficient balance."""
    title = '⚠️ Insufficient Balance'
    message = (
        f'Need: {format_currency(amount_needed, currency)}\n'
        f'Available: {format_currency(balance_available, currency)}\n'
        f'Please top up your Wise account.'
    )

    data = {
        'tag': 'payme_balance',
        'group': 'payme_status',
        'importance': 'high',
    }

    # Also create persistent notification
    send_persistent_notification(
        title,
        message,
        notification_id='payme_insufficient_balance',
    )

    return send_notification(title, message, data)


def notify_2fa_required(
    transfer_id: int,
    recipient: str,
    amount: float,
    currency: str = 'EUR',
) -> bool:
    """Send notification that Wise 2FA is required."""
    title = '🔐 Wise Approval Needed'
    message = (
        f'{format_currency(amount, currency)} to {recipient}\n'
        f'Open Wise app to approve transfer #{transfer_id}'
    )

    data = {
        'tag': f'payme_2fa_{transfer_id}',
        'group': 'payme_2fa',
        'importance': 'high',
        'actions': [
            {
                'action': 'URI',
                'title': 'Open Wise',
                'uri': 'wise://',
            },
        ],
    }

    return send_notification(title, message, data)


def notify_awaiting_funding(
    transfer_id: int,
    recipient: str,
    amount: float,
    currency: str = 'EUR',
    reference: str = '',
) -> bool:
    """Send notification that transfer needs funding in Wise app."""
    title = '💳 Fund Transfer in Wise'
    message = (
        f'{format_currency(amount, currency)} to {recipient}\n'
        f'Ref: {reference[:50]}\n'
        f'Transfer created - tap to fund in Wise app'
    )

    data = {
        'tag': f'payme_fund_{transfer_id}',
        'group': 'payme_funding',
        'importance': 'high',
        'actions': [
            {
                'action': 'URI',
                'title': 'Open Wise',
                'uri': 'wise://',
            },
        ],
    }

    # Also create persistent notification
    send_persistent_notification(
        title,
        f'{format_currency(amount, currency)} to {recipient}\n'
        f'Reference: {reference}\n'
        f'Open Wise app to fund transfer #{transfer_id}',
        notification_id=f'payme_fund_{transfer_id}',
    )

    return send_notification(title, message, data)


def notify_parse_error(
    filename: str,
    error: str,
) -> bool:
    """Send notification about bill parsing error."""
    title = '⚠️ Bill Parse Error'
    message = f'{filename}\n{error[:100]}'

    data = {
        'tag': 'payme_parse_error',
        'group': 'payme_errors',
    }

    return send_notification(title, message, data)


def notify_google_auth_expiring() -> bool:
    """Send notification that Google auth is expiring."""
    title = '⚠️ Google Auth Expiring'
    message = 'Google Photos authorization will expire soon. Please re-authenticate.'

    data = {
        'tag': 'payme_google_auth',
        'group': 'payme_status',
        'importance': 'high',
    }

    send_persistent_notification(
        title,
        message,
        notification_id='payme_google_auth_expiring',
    )

    return send_notification(title, message, data)


def notify_poll_complete(
    new_bills: int,
    processed: int,
    errors: int,
) -> bool:
    """Send quiet notification about poll completion (for debugging)."""
    if new_bills == 0 and errors == 0:
        return True  # Don't notify if nothing happened

    title = 'payme Poll Complete'
    parts = []
    if new_bills > 0:
        parts.append(f'{new_bills} new bill(s)')
    if processed > 0:
        parts.append(f'{processed} processed')
    if errors > 0:
        parts.append(f'{errors} error(s)')

    message = ', '.join(parts)

    data = {
        'tag': 'payme_poll',
        'group': 'payme_status',
        'importance': 'low',
    }

    return send_notification(title, message, data)


def clear_bill_notification(bill_id: str) -> bool:
    """Clear notification for a specific bill."""
    # Send empty notification with same tag to clear
    data = {
        'tag': f'payme_bill_{bill_id}',
        'message': 'clear_notification',
    }

    try:
        service = get_notify_service()
        call_ha_service('notify', service, data)
        return True
    except HttpError:
        return False


if __name__ == '__main__':
    print('Testing notify.py')
    print('=' * 40)

    # Test IBAN masking
    assert mask_iban('DE89370400440532013000') == 'DE89...3000', 'IBAN mask failed'
    assert mask_iban('DE89 3704 0044 0532 0130 00') == 'DE89...3000', 'IBAN mask with spaces failed'
    assert mask_iban('DE123456') == 'DE123456', 'Short IBAN should not mask'
    print('[OK] IBAN masking')

    # Test notification data structure
    # We can't actually send notifications without HA, but we can test the data building
    print('[OK] Notification functions defined')

    # Test formatting in notifications
    from formatting import format_currency
    assert '€' in format_currency(123.45, 'EUR'), 'Currency formatting failed'
    print('[OK] Currency formatting in notifications')

    print()
    print('Notification tests require Home Assistant.')
    print('Set PAYME_HA_TOKEN and optionally PAYME_NOTIFY_SERVICE.')
    print('Default service: mobile_app_phone')

    print('=' * 40)
    print('All tests passed')
