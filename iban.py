#!/usr/bin/env python3
"""IBAN validation and bank lookup for payme."""

import re
import requests
from typing import Optional

from config import BIC_DB_FILE, BIC_CACHE_FILE, OPENIBAN_API_BASE
from storage import load_json, update_dict

# IBAN length by country (common European countries)
IBAN_LENGTHS = {
    'DE': 22, 'AT': 20, 'CH': 21, 'FR': 27, 'IT': 27, 'ES': 24,
    'NL': 18, 'BE': 16, 'LU': 20, 'PT': 25, 'PL': 28, 'CZ': 24,
    'GB': 22, 'IE': 22, 'DK': 18, 'SE': 24, 'NO': 15, 'FI': 18,
}


def normalize_iban(iban: str) -> str:
    """Remove spaces and convert to uppercase."""
    return re.sub(r'\s+', '', iban).upper()


def validate_iban(iban: str) -> tuple[bool, str]:
    """
    Validate IBAN using ISO 7064 Mod 97-10 checksum.
    Returns (is_valid, error_message).
    """
    iban = normalize_iban(iban)

    # Basic format check
    if not iban:
        return False, 'IBAN is empty'

    if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]+$', iban):
        return False, 'Invalid IBAN format'

    country_code = iban[:2]

    # Check length for known countries
    if country_code in IBAN_LENGTHS:
        expected_length = IBAN_LENGTHS[country_code]
        if len(iban) != expected_length:
            return False, f'Invalid length for {country_code}: expected {expected_length}, got {len(iban)}'
    elif len(iban) < 15 or len(iban) > 34:
        return False, f'Invalid IBAN length: {len(iban)}'

    # Move first 4 characters to end
    rearranged = iban[4:] + iban[:4]

    # Convert letters to numbers (A=10, B=11, ..., Z=35)
    numeric = ''
    for char in rearranged:
        if char.isalpha():
            numeric += str(ord(char) - ord('A') + 10)
        else:
            numeric += char

    # Check mod 97
    if int(numeric) % 97 != 1:
        return False, 'Invalid IBAN checksum'

    return True, ''


def extract_country_code(iban: str) -> str:
    """Extract country code from IBAN."""
    return normalize_iban(iban)[:2]


def extract_blz(iban: str) -> Optional[str]:
    """Extract German Bankleitzahl (BLZ) from IBAN. Returns None for non-DE IBANs."""
    iban = normalize_iban(iban)
    if not iban.startswith('DE') or len(iban) != 22:
        return None
    # German IBAN: DExx BBBB BBBB CCCC CCCC CC
    # BLZ is positions 4-12 (8 digits)
    return iban[4:12]


def lookup_bank_from_db(blz: str) -> Optional[dict]:
    """Look up bank info from local BIC database."""
    bic_db = load_json(BIC_DB_FILE, {})
    return bic_db.get(blz)


def lookup_bank_from_cache(iban: str) -> Optional[dict]:
    """Look up bank info from cache."""
    cache = load_json(BIC_CACHE_FILE, {})
    return cache.get(normalize_iban(iban))


def cache_bank_lookup(iban: str, info: dict) -> None:
    """Cache bank lookup result."""
    update_dict(BIC_CACHE_FILE, normalize_iban(iban), info)


def lookup_bank_from_api(iban: str) -> Optional[dict]:
    """Query openiban.com for bank info. Returns None on failure."""
    iban = normalize_iban(iban)

    try:
        response = requests.get(
            OPENIBAN_API_BASE,
            params={'iban': iban, 'getBIC': 'true'},
            timeout=3
        )
        response.raise_for_status()
        data = response.json()

        if not data.get('valid'):
            return None

        bank_data = data.get('bankData', {})
        if not bank_data:
            return None

        return {
            'name': bank_data.get('name', ''),
            'bic': bank_data.get('bic', ''),
            'city': bank_data.get('city', ''),
        }
    except (requests.RequestException, ValueError, KeyError):
        return None


def lookup_bank(iban: str) -> dict:
    """
    Look up bank info for IBAN.

    Lookup order:
    1. Local BIC database (for German IBANs via BLZ)
    2. Cache (for previously looked up IBANs)
    3. openiban.com API (3s timeout)
    4. Returns unknown bank info if all fail

    Returns dict with keys: name, bic, city, source
    """
    iban = normalize_iban(iban)

    # For German IBANs, try local BLZ database first
    blz = extract_blz(iban)
    if blz:
        db_result = lookup_bank_from_db(blz)
        if db_result:
            return {
                'name': db_result.get('name', ''),
                'bic': db_result.get('bic', ''),
                'city': db_result.get('city', ''),
                'source': 'bic_db',
            }

    # Check cache
    cached = lookup_bank_from_cache(iban)
    if cached:
        cached['source'] = 'cache'
        return cached

    # Try openiban.com API
    api_result = lookup_bank_from_api(iban)
    if api_result:
        cache_bank_lookup(iban, api_result)
        api_result['source'] = 'openiban'
        return api_result

    # All lookups failed
    return {
        'name': 'Unknown bank',
        'bic': blz or '',
        'city': '',
        'source': 'none',
    }


def get_iban_info(iban: str) -> dict:
    """
    Get complete IBAN information including validation and bank lookup.

    Returns dict with keys:
    - iban: normalized IBAN
    - valid: bool
    - error: error message if invalid
    - country: country code
    - bank: dict with name, bic, city, source
    """
    iban = normalize_iban(iban)
    is_valid, error = validate_iban(iban)

    result = {
        'iban': iban,
        'valid': is_valid,
        'error': error,
        'country': extract_country_code(iban) if iban else '',
    }

    if is_valid:
        result['bank'] = lookup_bank(iban)
    else:
        result['bank'] = {'name': '', 'bic': '', 'city': '', 'source': 'none'}

    return result


if __name__ == '__main__':
    import sys

    print('Testing iban.py')
    print('=' * 40)

    # Test validation
    test_ibans = [
        ('DE89370400440532013000', True, 'Valid German IBAN'),
        ('DE89 3704 0044 0532 0130 00', True, 'Valid with spaces'),
        ('de89370400440532013000', True, 'Valid lowercase'),
        ('DE89370400440532013001', False, 'Invalid checksum'),
        ('DE8937040044053201300', False, 'Too short'),
        ('XX89370400440532013000', False, 'Unknown country'),
        ('', False, 'Empty'),
        ('INVALID', False, 'Invalid format'),
    ]

    for iban, expected_valid, description in test_ibans:
        is_valid, error = validate_iban(iban)
        status = '[OK]' if is_valid == expected_valid else '[FAIL]'
        print(f'{status} {description}: valid={is_valid}', end='')
        if error:
            print(f' ({error})')
        else:
            print()

    print()
    print('BLZ extraction:')
    blz = extract_blz('DE89370400440532013000')
    print(f'  DE89370400440532013000 -> BLZ: {blz}')
    assert blz == '37040044', f'Expected 37040044, got {blz}'
    print('  [OK]')

    print()

    # Command line usage
    if len(sys.argv) > 1:
        iban_arg = sys.argv[1]
        print(f'Looking up: {iban_arg}')
        print('=' * 40)

        info = get_iban_info(iban_arg)
        print(f"IBAN:    {info['iban']}")
        print(f"Valid:   {info['valid']}")
        if info['error']:
            print(f"Error:   {info['error']}")
        print(f"Country: {info['country']}")
        print(f"Bank:    {info['bank']['name']}")
        print(f"BIC:     {info['bank']['bic']}")
        if info['bank']['city']:
            print(f"City:    {info['bank']['city']}")
        print(f"Source:  {info['bank']['source']}")
    else:
        print('Usage: python3 iban.py <IBAN>')
        print('Example: python3 iban.py DE89370400440532013000')

    print()
    print('=' * 40)
    print('Tests complete')
