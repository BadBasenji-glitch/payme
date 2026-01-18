"""
Entity management for payme.

Creates and updates Home Assistant entities for the payme dashboard.
"""

import json
from datetime import datetime
from typing import Any


# Entity IDs
ENTITY_PENDING_BILLS = 'sensor.payme_pending_bills'
ENTITY_PENDING_FUNDING = 'sensor.payme_pending_funding'
ENTITY_AWAITING_2FA = 'sensor.payme_awaiting_wise_2fa'
ENTITY_WISE_BALANCE = 'sensor.payme_wise_balance'
ENTITY_PAYMENT_HISTORY = 'sensor.payme_payment_history'
ENTITY_FAILED_QUEUE = 'sensor.payme_failed_queue'
ENTITY_STATISTICS = 'sensor.payme_statistics'
ENTITY_GOOGLE_AUTH_STATUS = 'sensor.payme_google_auth_status'
ENTITY_GOOGLE_AUTH_HEALTHY = 'binary_sensor.payme_google_auth_healthy'
ENTITY_LAST_POLL = 'sensor.payme_last_poll'


def set_state(entity_id: str, state: Any, attributes: dict = None) -> None:
    """
    Set entity state in Home Assistant.

    Uses pyscript's state.set() function.
    """
    if attributes is None:
        attributes = {}

    # pyscript provides state.set globally
    state.set(entity_id, state, attributes)


def update_pending_bills(bills: list[dict]) -> None:
    """
    Update pending bills entity.

    Args:
        bills: List of pending bill dicts
    """
    # Separate by status
    pending = [b for b in bills if b.get('status') == 'pending']
    pending_funding = [b for b in bills if b.get('status') == 'insufficient_balance']
    failed = [b for b in bills if b.get('status') == 'failed']

    # Count warnings
    duplicates = sum(1 for b in pending if b.get('duplicate_warning'))
    low_confidence = sum(1 for b in pending if b.get('low_confidence'))

    # Pending bills
    set_state(
        ENTITY_PENDING_BILLS,
        len(pending),
        {
            'bills': json.dumps(pending),
            'count': len(pending),
            'total_amount': sum(b.get('amount', 0) for b in pending),
            'duplicate_warnings': duplicates,
            'low_confidence_warnings': low_confidence,
            'friendly_name': 'Pending Bills',
            'icon': 'mdi:file-document-multiple',
            'unit_of_measurement': 'bills',
        }
    )

    # Pending funding
    set_state(
        ENTITY_PENDING_FUNDING,
        len(pending_funding),
        {
            'bills': json.dumps(pending_funding),
            'count': len(pending_funding),
            'total_amount': sum(b.get('amount', 0) for b in pending_funding),
            'friendly_name': 'Pending Funding',
            'icon': 'mdi:cash-clock',
            'unit_of_measurement': 'bills',
        }
    )

    # Failed queue
    set_state(
        ENTITY_FAILED_QUEUE,
        len(failed),
        {
            'bills': json.dumps(failed),
            'count': len(failed),
            'friendly_name': 'Failed Bills',
            'icon': 'mdi:alert-circle',
            'unit_of_measurement': 'bills',
        }
    )


def update_awaiting_2fa(transfers: list[dict]) -> None:
    """
    Update transfers awaiting Wise 2FA.

    Args:
        transfers: List of transfer dicts needing 2FA
    """
    set_state(
        ENTITY_AWAITING_2FA,
        len(transfers),
        {
            'transfers': json.dumps(transfers),
            'count': len(transfers),
            'friendly_name': 'Awaiting Wise 2FA',
            'icon': 'mdi:two-factor-authentication',
            'unit_of_measurement': 'transfers',
        }
    )


def update_wise_balance(balance: float, currency: str = 'EUR') -> None:
    """
    Update Wise balance entity.

    Args:
        balance: Available balance
        currency: Currency code
    """
    # Determine icon based on balance
    if balance < 50:
        icon = 'mdi:cash-remove'
    elif balance < 200:
        icon = 'mdi:cash'
    else:
        icon = 'mdi:cash-plus'

    set_state(
        ENTITY_WISE_BALANCE,
        round(balance, 2),
        {
            'currency': currency,
            'friendly_name': 'Wise Balance',
            'icon': icon,
            'unit_of_measurement': currency,
            'device_class': 'monetary',
        }
    )


def update_payment_history(history: list[dict], limit: int = 50) -> None:
    """
    Update payment history entity.

    Args:
        history: List of payment history dicts
        limit: Max entries to store in attributes
    """
    # Sort by date descending
    sorted_history = sorted(
        history,
        key=lambda x: x.get('created_at', ''),
        reverse=True
    )[:limit]

    # Calculate totals
    paid = [h for h in history if h.get('status') == 'paid']
    rejected = [h for h in history if h.get('status') == 'rejected']

    set_state(
        ENTITY_PAYMENT_HISTORY,
        len(history),
        {
            'history': json.dumps(sorted_history),
            'total_count': len(history),
            'paid_count': len(paid),
            'rejected_count': len(rejected),
            'total_paid': sum(h.get('amount', 0) for h in paid),
            'friendly_name': 'Payment History',
            'icon': 'mdi:history',
            'unit_of_measurement': 'payments',
        }
    )


def update_google_auth_status(status: str, expires_at: str = None, message: str = None) -> None:
    """
    Update Google auth status entities.

    Args:
        status: 'ok', 'expiring', 'expired', or 'missing'
        expires_at: Token expiration datetime
        message: Status message
    """
    # Map status to icon
    icons = {
        'ok': 'mdi:check-circle',
        'expiring': 'mdi:alert',
        'expired': 'mdi:alert-circle',
        'missing': 'mdi:close-circle',
    }

    set_state(
        ENTITY_GOOGLE_AUTH_STATUS,
        status,
        {
            'expires_at': expires_at or '',
            'message': message or '',
            'friendly_name': 'Google Auth Status',
            'icon': icons.get(status, 'mdi:help-circle'),
        }
    )

    # Binary sensor for healthy auth
    is_healthy = status == 'ok'
    set_state(
        ENTITY_GOOGLE_AUTH_HEALTHY,
        'on' if is_healthy else 'off',
        {
            'friendly_name': 'Google Auth Healthy',
            'device_class': 'connectivity',
        }
    )


def update_statistics(history: list[dict]) -> None:
    """
    Update statistics entity based on payment history.

    Args:
        history: Full payment history
    """
    now = datetime.now()
    current_month = now.strftime('%Y-%m')
    current_year = now.strftime('%Y')

    # Filter paid bills only
    paid = [h for h in history if h.get('status') == 'paid']

    # Monthly stats
    this_month = [
        h for h in paid
        if h.get('created_at', '').startswith(current_month)
    ]

    # Yearly stats
    this_year = [
        h for h in paid
        if h.get('created_at', '').startswith(current_year)
    ]

    # Calculate averages
    monthly_total = sum(h.get('amount', 0) for h in this_month)
    yearly_total = sum(h.get('amount', 0) for h in this_year)

    avg_payment = 0
    if paid:
        avg_payment = sum(h.get('amount', 0) for h in paid) / len(paid)

    stats = {
        'monthly_total': round(monthly_total, 2),
        'monthly_count': len(this_month),
        'yearly_total': round(yearly_total, 2),
        'yearly_count': len(this_year),
        'all_time_total': round(sum(h.get('amount', 0) for h in paid), 2),
        'all_time_count': len(paid),
        'average_payment': round(avg_payment, 2),
        'current_month': current_month,
    }

    set_state(
        ENTITY_STATISTICS,
        round(monthly_total, 2),
        {
            **stats,
            'stats_json': json.dumps(stats),
            'friendly_name': 'Monthly Spending',
            'icon': 'mdi:chart-line',
            'unit_of_measurement': 'EUR',
            'device_class': 'monetary',
        }
    )


def update_last_poll(success: bool, bills_found: int, errors: list[str] = None) -> None:
    """
    Update last poll status entity.

    Args:
        success: Whether poll completed successfully
        bills_found: Number of new bills found
        errors: List of error messages
    """
    now = datetime.now().isoformat()

    set_state(
        ENTITY_LAST_POLL,
        now,
        {
            'success': success,
            'bills_found': bills_found,
            'errors': json.dumps(errors or []),
            'error_count': len(errors or []),
            'friendly_name': 'Last Poll',
            'icon': 'mdi:update',
            'device_class': 'timestamp',
        }
    )


def update_all_entities(
    pending_bills: list[dict] = None,
    payment_history: list[dict] = None,
    wise_balance: float = None,
    awaiting_2fa: list[dict] = None,
    google_auth: dict = None,
) -> None:
    """
    Update all payme entities at once.

    Args:
        pending_bills: List of pending bill dicts
        payment_history: List of payment history dicts
        wise_balance: Available EUR balance
        awaiting_2fa: List of transfers needing 2FA
        google_auth: Dict with status, expires_at, message
    """
    if pending_bills is not None:
        update_pending_bills(pending_bills)

    if payment_history is not None:
        update_payment_history(payment_history)
        update_statistics(payment_history)

    if wise_balance is not None:
        update_wise_balance(wise_balance)

    if awaiting_2fa is not None:
        update_awaiting_2fa(awaiting_2fa)

    if google_auth is not None:
        update_google_auth_status(
            status=google_auth.get('status', 'unknown'),
            expires_at=google_auth.get('expires_at'),
            message=google_auth.get('message'),
        )


def get_entity_states() -> dict:
    """
    Get current state of all payme entities.

    Returns dict of entity_id -> state.
    """
    entities = [
        ENTITY_PENDING_BILLS,
        ENTITY_PENDING_FUNDING,
        ENTITY_AWAITING_2FA,
        ENTITY_WISE_BALANCE,
        ENTITY_PAYMENT_HISTORY,
        ENTITY_FAILED_QUEUE,
        ENTITY_STATISTICS,
        ENTITY_GOOGLE_AUTH_STATUS,
        ENTITY_GOOGLE_AUTH_HEALTHY,
        ENTITY_LAST_POLL,
    ]

    states = {}
    for entity_id in entities:
        try:
            states[entity_id] = state.get(entity_id)
        except Exception:
            states[entity_id] = None

    return states
