#!/usr/bin/env python3
"""Wise API client for payme."""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from config import WISE_API_BASE, WISE_API_DELAY_SECONDS, get_env
from http_client import get_json, post_json, HttpError

# Track last API call for rate limiting
_last_api_call: Optional[datetime] = None


def _rate_limit() -> None:
    """Enforce delay between API calls."""
    global _last_api_call

    if _last_api_call is not None:
        elapsed = (datetime.now() - _last_api_call).total_seconds()
        if elapsed < WISE_API_DELAY_SECONDS:
            time.sleep(WISE_API_DELAY_SECONDS - elapsed)

    _last_api_call = datetime.now()


def get_api_token() -> str:
    """Get Wise API token from environment."""
    return get_env('PAYME_WISE_API_TOKEN', required=True)


def get_profile_id() -> str:
    """Get Wise profile ID from environment."""
    return get_env('PAYME_WISE_PROFILE_ID', required=True)


def get_auth_headers() -> dict:
    """Get authorization headers for API requests."""
    token = get_api_token()
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }


def api_get(endpoint: str) -> dict:
    """Make rate-limited GET request to Wise API."""
    _rate_limit()
    url = f'{WISE_API_BASE}{endpoint}'
    return get_json(url, headers=get_auth_headers())


def api_post(endpoint: str, data: dict) -> dict:
    """Make rate-limited POST request to Wise API."""
    _rate_limit()
    url = f'{WISE_API_BASE}{endpoint}'
    return post_json(url, headers=get_auth_headers(), json=data)


@dataclass
class Balance:
    """Wise account balance."""
    currency: str
    amount: float
    reserved: float
    available: float

    @property
    def has_funds(self) -> bool:
        return self.available > 0


@dataclass
class Transfer:
    """Wise transfer details."""
    id: int
    reference: str
    status: str
    source_currency: str
    source_amount: float
    target_currency: str
    target_amount: float
    recipient_name: str
    created: str
    rate: float

    @property
    def is_complete(self) -> bool:
        return self.status in ('outgoing_payment_sent', 'funds_converted')

    @property
    def is_pending(self) -> bool:
        return self.status in ('incoming_payment_waiting', 'processing', 'waiting_for_authorization')

    @property
    def needs_2fa(self) -> bool:
        return self.status == 'waiting_for_authorization'

    @property
    def is_failed(self) -> bool:
        return self.status in ('cancelled', 'funds_refunded', 'bounced_back')


def get_profiles() -> list[dict]:
    """Get all profiles for the authenticated user."""
    return api_get('/v1/profiles')


def get_profile(profile_id: str = None) -> dict:
    """Get profile details."""
    if profile_id is None:
        profile_id = get_profile_id()
    return api_get(f'/v1/profiles/{profile_id}')


def get_balances(profile_id: str = None) -> list[Balance]:
    """Get all currency balances for profile."""
    if profile_id is None:
        profile_id = get_profile_id()

    response = api_get(f'/v4/profiles/{profile_id}/balances?types=STANDARD')

    balances = []
    for b in response:
        amount_data = b.get('amount', {})
        balances.append(Balance(
            currency=amount_data.get('currency', ''),
            amount=float(amount_data.get('value', 0)),
            reserved=float(b.get('reservedAmount', {}).get('value', 0)),
            available=float(amount_data.get('value', 0)) - float(b.get('reservedAmount', {}).get('value', 0)),
        ))

    return balances


def get_balance(currency: str = 'EUR', profile_id: str = None) -> Optional[Balance]:
    """Get balance for specific currency."""
    balances = get_balances(profile_id)
    for b in balances:
        if b.currency == currency:
            return b
    return None


def get_eur_balance(profile_id: str = None) -> float:
    """Get available EUR balance. Returns 0 if no EUR balance."""
    balance = get_balance('EUR', profile_id)
    return balance.available if balance else 0.0


def check_sufficient_balance(amount: float, currency: str = 'EUR', profile_id: str = None) -> bool:
    """Check if sufficient balance exists for transfer."""
    balance = get_balance(currency, profile_id)
    if not balance:
        return False
    return balance.available >= amount


def create_quote(
    source_currency: str,
    target_currency: str,
    target_amount: float,
    profile_id: str = None,
) -> dict:
    """
    Create a quote for a transfer.

    Returns quote dict with id, rate, fee, etc.
    """
    if profile_id is None:
        profile_id = get_profile_id()

    data = {
        'sourceCurrency': source_currency,
        'targetCurrency': target_currency,
        'targetAmount': target_amount,
        'profile': int(profile_id),
    }

    return api_post('/v3/quotes', data)


def create_recipient(
    iban: str,
    name: str,
    currency: str = 'EUR',
    profile_id: str = None,
) -> dict:
    """
    Create a recipient account.

    Returns recipient dict with id.
    """
    if profile_id is None:
        profile_id = get_profile_id()

    # Remove spaces from IBAN
    iban = iban.replace(' ', '').upper()

    data = {
        'currency': currency,
        'type': 'iban',
        'profile': int(profile_id),
        'accountHolderName': name,
        'details': {
            'iban': iban,
        },
    }

    return api_post('/v1/accounts', data)


def find_recipient(iban: str, profile_id: str = None) -> Optional[dict]:
    """
    Find existing recipient by IBAN.

    Returns recipient dict or None if not found.
    """
    if profile_id is None:
        profile_id = get_profile_id()

    iban = iban.replace(' ', '').upper()

    # List all recipients
    recipients = api_get(f'/v1/accounts?profile={profile_id}')

    for r in recipients:
        details = r.get('details', {})
        if details.get('iban', '').replace(' ', '').upper() == iban:
            return r

    return None


def get_or_create_recipient(
    iban: str,
    name: str,
    currency: str = 'EUR',
    profile_id: str = None,
) -> dict:
    """
    Get existing recipient or create new one.

    Returns recipient dict with id.
    """
    existing = find_recipient(iban, profile_id)
    if existing:
        return existing

    return create_recipient(iban, name, currency, profile_id)


def create_transfer(
    quote_id: str,
    recipient_id: int,
    reference: str,
) -> dict:
    """
    Create a transfer.

    Returns transfer dict with id, status.
    Note: Transfer is not funded yet - call fund_transfer() to execute.
    """
    data = {
        'targetAccount': recipient_id,
        'quoteUuid': quote_id,
        'customerTransactionId': None,  # Will be auto-generated
        'details': {
            'reference': reference[:140] if reference else '',  # Max 140 chars
        },
    }

    return api_post('/v1/transfers', data)


def fund_transfer(transfer_id: int, profile_id: str = None) -> dict:
    """
    Fund a transfer (execute payment).

    This actually sends the money.
    Returns funding response with status.
    """
    if profile_id is None:
        profile_id = get_profile_id()

    data = {
        'type': 'BALANCE',
    }

    return api_post(f'/v3/profiles/{profile_id}/transfers/{transfer_id}/payments', data)


def get_transfer(transfer_id: int) -> Transfer:
    """Get transfer details by ID."""
    data = api_get(f'/v1/transfers/{transfer_id}')
    return _parse_transfer(data)


def get_transfer_status(transfer_id: int) -> str:
    """Get current status of a transfer."""
    transfer = get_transfer(transfer_id)
    return transfer.status


def _parse_transfer(data: dict) -> Transfer:
    """Parse API response into Transfer object."""
    return Transfer(
        id=data.get('id', 0),
        reference=data.get('details', {}).get('reference', ''),
        status=data.get('status', ''),
        source_currency=data.get('sourceCurrency', ''),
        source_amount=float(data.get('sourceValue', 0)),
        target_currency=data.get('targetCurrency', ''),
        target_amount=float(data.get('targetValue', 0)),
        recipient_name=data.get('targetRecipientName', ''),
        created=data.get('created', ''),
        rate=float(data.get('rate', 0)),
    )


def list_transfers(
    profile_id: str = None,
    limit: int = 100,
    status: str = None,
) -> list[Transfer]:
    """
    List recent transfers.

    Args:
        profile_id: Profile ID
        limit: Max number of transfers to return
        status: Filter by status (optional)

    Returns list of Transfer objects.
    """
    if profile_id is None:
        profile_id = get_profile_id()

    params = f'?profile={profile_id}&limit={limit}'
    if status:
        params += f'&status={status}'

    data = api_get(f'/v1/transfers{params}')

    return [_parse_transfer(t) for t in data]


def list_pending_transfers(profile_id: str = None) -> list[Transfer]:
    """List transfers that are pending or need action."""
    transfers = list_transfers(profile_id, limit=50)
    return [t for t in transfers if t.is_pending]


def list_transfers_needing_2fa(profile_id: str = None) -> list[Transfer]:
    """List transfers waiting for 2FA approval in Wise app."""
    transfers = list_transfers(profile_id, limit=50)
    return [t for t in transfers if t.needs_2fa]


def execute_payment(
    iban: str,
    name: str,
    amount: float,
    reference: str,
    currency: str = 'EUR',
    profile_id: str = None,
) -> dict:
    """
    Execute complete payment flow.

    1. Check balance
    2. Create quote
    3. Create/find recipient
    4. Create transfer
    5. Fund transfer

    Returns dict with transfer_id, status, and any errors.
    """
    if profile_id is None:
        profile_id = get_profile_id()

    result = {
        'success': False,
        'transfer_id': None,
        'status': None,
        'error': None,
    }

    try:
        # Check balance
        if not check_sufficient_balance(amount, currency, profile_id):
            balance = get_eur_balance(profile_id)
            result['error'] = f'Insufficient balance: {balance:.2f} EUR available, {amount:.2f} EUR needed'
            result['status'] = 'insufficient_balance'
            return result

        # Create quote
        quote = create_quote(currency, currency, amount, profile_id)
        quote_id = quote.get('id')
        if not quote_id:
            result['error'] = 'Failed to create quote'
            return result

        # Get or create recipient
        recipient = get_or_create_recipient(iban, name, currency, profile_id)
        recipient_id = recipient.get('id')
        if not recipient_id:
            result['error'] = 'Failed to create recipient'
            return result

        # Create transfer
        transfer = create_transfer(quote_id, recipient_id, reference)
        transfer_id = transfer.get('id')
        if not transfer_id:
            result['error'] = 'Failed to create transfer'
            return result

        result['transfer_id'] = transfer_id

        # Fund transfer
        funding = fund_transfer(transfer_id, profile_id)
        result['status'] = funding.get('status', 'unknown')
        result['success'] = result['status'] not in ('REJECTED', 'FAILED')

        # Check if needs 2FA
        if result['status'] == 'PENDING' or 'waiting' in result['status'].lower():
            current = get_transfer_status(transfer_id)
            result['status'] = current
            if current == 'waiting_for_authorization':
                result['needs_2fa'] = True

        return result

    except HttpError as e:
        result['error'] = str(e)
        return result


if __name__ == '__main__':
    print('Testing wise.py')
    print('=' * 40)

    # Test rate limiting
    import wise
    wise._last_api_call = None

    start = datetime.now()
    _rate_limit()
    elapsed1 = (datetime.now() - start).total_seconds()
    assert elapsed1 < 0.1, 'First call should not delay'

    start = datetime.now()
    _rate_limit()
    elapsed2 = (datetime.now() - start).total_seconds()
    assert elapsed2 >= WISE_API_DELAY_SECONDS - 0.1, f'Second call should delay ~{WISE_API_DELAY_SECONDS}s'
    print(f'[OK] Rate limiting ({elapsed2:.1f}s delay)')

    # Test Transfer dataclass
    test_transfer = Transfer(
        id=12345,
        reference='Invoice 001',
        status='outgoing_payment_sent',
        source_currency='EUR',
        source_amount=100.0,
        target_currency='EUR',
        target_amount=100.0,
        recipient_name='Test User',
        created='2024-01-15T10:00:00Z',
        rate=1.0,
    )
    assert test_transfer.is_complete, 'Should be complete'
    assert not test_transfer.is_pending, 'Should not be pending'
    assert not test_transfer.needs_2fa, 'Should not need 2FA'
    print('[OK] Transfer status: complete')

    test_pending = Transfer(
        id=12346,
        reference='Invoice 002',
        status='waiting_for_authorization',
        source_currency='EUR',
        source_amount=500.0,
        target_currency='EUR',
        target_amount=500.0,
        recipient_name='Test User',
        created='2024-01-15T10:00:00Z',
        rate=1.0,
    )
    assert not test_pending.is_complete, 'Should not be complete'
    assert test_pending.is_pending, 'Should be pending'
    assert test_pending.needs_2fa, 'Should need 2FA'
    print('[OK] Transfer status: pending 2FA')

    test_failed = Transfer(
        id=12347,
        reference='Invoice 003',
        status='cancelled',
        source_currency='EUR',
        source_amount=50.0,
        target_currency='EUR',
        target_amount=50.0,
        recipient_name='Test User',
        created='2024-01-15T10:00:00Z',
        rate=1.0,
    )
    assert test_failed.is_failed, 'Should be failed'
    print('[OK] Transfer status: failed')

    # Test Balance dataclass
    test_balance = Balance(
        currency='EUR',
        amount=1000.0,
        reserved=50.0,
        available=950.0,
    )
    assert test_balance.has_funds, 'Should have funds'
    assert test_balance.available == 950.0, 'Wrong available amount'
    print('[OK] Balance dataclass')

    print()
    print('API tests require Wise credentials.')
    print('Set PAYME_WISE_API_TOKEN and PAYME_WISE_PROFILE_ID.')

    print('=' * 40)
    print('All tests passed')
