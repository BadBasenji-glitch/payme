#!/usr/bin/env python3
"""Duplicate payment detection for payme."""

import hashlib
from datetime import datetime, timedelta
from typing import Optional

from config import PAYMENT_HASHES_FILE, DUPLICATE_WINDOW_DAYS
from storage import load_json, save_json


def generate_hash(iban: str, amount: float, reference: str) -> str:
    """
    Generate SHA256 hash from payment details.

    Normalizes inputs before hashing:
    - IBAN: uppercase, no spaces
    - Amount: 2 decimal places
    - Reference: lowercase, stripped
    """
    # Normalize inputs
    iban_normalized = iban.replace(' ', '').upper()
    amount_normalized = f'{amount:.2f}'
    reference_normalized = reference.strip().lower()

    # Combine and hash
    combined = f'{iban_normalized}|{amount_normalized}|{reference_normalized}'
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


def load_hashes() -> dict:
    """Load payment hashes from storage."""
    return load_json(PAYMENT_HASHES_FILE, {})


def save_hashes(hashes: dict) -> None:
    """Save payment hashes to storage."""
    save_json(PAYMENT_HASHES_FILE, hashes)


def is_duplicate(iban: str, amount: float, reference: str) -> tuple[bool, Optional[dict]]:
    """
    Check if payment is a duplicate.

    Returns (is_duplicate, duplicate_info).
    duplicate_info contains original payment details if duplicate found.
    """
    payment_hash = generate_hash(iban, amount, reference)
    hashes = load_hashes()

    if payment_hash not in hashes:
        return False, None

    record = hashes[payment_hash]
    recorded_date = datetime.fromisoformat(record['date'])
    cutoff_date = datetime.now() - timedelta(days=DUPLICATE_WINDOW_DAYS)

    # Check if within duplicate window
    if recorded_date < cutoff_date:
        return False, None

    return True, {
        'hash': payment_hash,
        'date': record['date'],
        'iban': record.get('iban', ''),
        'amount': record.get('amount', 0),
        'reference': record.get('reference', ''),
        'days_ago': (datetime.now() - recorded_date).days,
    }


def record_payment(iban: str, amount: float, reference: str) -> str:
    """
    Record a payment hash to prevent future duplicates.

    Returns the generated hash.
    """
    payment_hash = generate_hash(iban, amount, reference)
    hashes = load_hashes()

    hashes[payment_hash] = {
        'date': datetime.now().isoformat(),
        'iban': iban.replace(' ', '').upper(),
        'amount': amount,
        'reference': reference.strip(),
    }

    save_hashes(hashes)
    return payment_hash


def remove_hash(payment_hash: str) -> bool:
    """
    Remove a payment hash (for override/undo).

    Returns True if hash was found and removed.
    """
    hashes = load_hashes()

    if payment_hash not in hashes:
        return False

    del hashes[payment_hash]
    save_hashes(hashes)
    return True


def cleanup_old_hashes() -> int:
    """
    Remove hashes older than the duplicate window.

    Returns count of removed hashes.
    """
    hashes = load_hashes()
    cutoff_date = datetime.now() - timedelta(days=DUPLICATE_WINDOW_DAYS)

    old_count = len(hashes)
    hashes = {
        h: record for h, record in hashes.items()
        if datetime.fromisoformat(record['date']) >= cutoff_date
    }

    removed = old_count - len(hashes)
    if removed > 0:
        save_hashes(hashes)

    return removed


def get_stats() -> dict:
    """Get statistics about stored hashes."""
    hashes = load_hashes()

    if not hashes:
        return {
            'total': 0,
            'oldest': None,
            'newest': None,
        }

    dates = [datetime.fromisoformat(r['date']) for r in hashes.values()]

    return {
        'total': len(hashes),
        'oldest': min(dates).isoformat(),
        'newest': max(dates).isoformat(),
    }


def check_similar(
    iban: str,
    amount: float,
    tolerance: float = 0.01,
) -> list[dict]:
    """
    Find similar payments (same IBAN, similar amount) within duplicate window.

    Used for fuzzy duplicate detection when reference might differ.
    Returns list of similar payment records.
    """
    iban_normalized = iban.replace(' ', '').upper()
    hashes = load_hashes()
    cutoff_date = datetime.now() - timedelta(days=DUPLICATE_WINDOW_DAYS)

    similar = []
    for payment_hash, record in hashes.items():
        recorded_date = datetime.fromisoformat(record['date'])
        if recorded_date < cutoff_date:
            continue

        if record.get('iban') != iban_normalized:
            continue

        recorded_amount = record.get('amount', 0)
        if abs(recorded_amount - amount) <= tolerance:
            similar.append({
                'hash': payment_hash,
                'date': record['date'],
                'amount': recorded_amount,
                'reference': record.get('reference', ''),
                'days_ago': (datetime.now() - recorded_date).days,
            })

    return similar


if __name__ == '__main__':
    print('Testing dedup.py')
    print('=' * 40)

    # Test hash generation
    hash1 = generate_hash('DE89370400440532013000', 123.45, 'Invoice 001')
    hash2 = generate_hash('DE89 3704 0044 0532 0130 00', 123.45, 'INVOICE 001')
    hash3 = generate_hash('DE89370400440532013000', 123.46, 'Invoice 001')

    assert hash1 == hash2, 'Normalized hashes should match'
    assert hash1 != hash3, 'Different amounts should have different hashes'
    print('[OK] Hash generation and normalization')

    # Test duplicate detection (clean state)
    is_dup, info = is_duplicate('DE11111111111111111111', 99.99, 'Test ref')
    assert not is_dup, 'Should not be duplicate initially'
    print('[OK] Non-duplicate detection')

    # Record a payment
    test_hash = record_payment('DE11111111111111111111', 99.99, 'Test ref')
    assert len(test_hash) == 64, 'Hash should be SHA256'
    print('[OK] Record payment')

    # Check duplicate
    is_dup, info = is_duplicate('DE11111111111111111111', 99.99, 'Test ref')
    assert is_dup, 'Should be duplicate now'
    assert info['hash'] == test_hash, 'Hash should match'
    assert info['days_ago'] == 0, 'Should be from today'
    print('[OK] Duplicate detection')

    # Test similar payment detection
    record_payment('DE22222222222222222222', 50.00, 'Ref A')
    record_payment('DE22222222222222222222', 50.01, 'Ref B')
    similar = check_similar('DE22222222222222222222', 50.00, tolerance=0.05)
    assert len(similar) == 2, 'Should find 2 similar payments'
    print('[OK] Similar payment detection')

    # Test hash removal
    removed = remove_hash(test_hash)
    assert removed, 'Should remove hash'
    is_dup, _ = is_duplicate('DE11111111111111111111', 99.99, 'Test ref')
    assert not is_dup, 'Should not be duplicate after removal'
    print('[OK] Hash removal')

    # Test stats
    stats = get_stats()
    assert stats['total'] >= 2, 'Should have at least 2 hashes'
    print(f'[OK] Stats: {stats["total"]} hashes stored')

    # Cleanup test hashes
    hashes = load_hashes()
    hashes = {h: r for h, r in hashes.items()
              if r.get('iban') not in ['DE11111111111111111111', 'DE22222222222222222222']}
    save_hashes(hashes)
    print('[OK] Test cleanup')

    print('=' * 40)
    print('All tests passed')
