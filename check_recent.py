#!/usr/bin/env python3
"""Check recent payme activity."""

from datetime import datetime, timedelta

from config import PAYMENT_HISTORY_FILE, PROCESSED_PHOTOS_FILE, PROCESSED_EMAILS_FILE
from storage import load_json

LOG_FILE = PAYMENT_HISTORY_FILE.parent / 'payme.log'


def main():
    print('=' * 60)
    print('PAYME RECENT ACTIVITY CHECK')
    print('=' * 60)

    print('\n=== PROCESSED PHOTOS ===')
    data = load_json(PROCESSED_PHOTOS_FILE, {})
    processed = data.get('processed', [])
    print('Total processed:', len(processed))
    print('Last 10:')
    for pid in processed[-10:]:
        print(' ', pid)

    print('\n=== PROCESSED EMAILS ===')
    data = load_json(PROCESSED_EMAILS_FILE, {})
    processed = data.get('processed', [])
    print('Total processed:', len(processed))
    print('Last 10:')
    for eid in processed[-10:]:
        print(' ', eid)

    print('\n=== PAYMENT HISTORY ===')
    data = load_json(PAYMENT_HISTORY_FILE, {})
    pending = data.get('pending', [])
    history = data.get('history', [])

    print('\nPENDING BILLS:', len(pending))
    print('-' * 60)
    for b in pending:
        print('ID:', b.get('id'))
        print('Created:', b.get('created_at', '')[:19])
        print('Status:', b.get('status'))
        print('Amount:', b.get('amount'), b.get('currency', 'EUR'))
        print('Recipient:', b.get('recipient', '')[:40])
        print('IBAN:', b.get('iban', 'N/A'))
        if b.get('error'):
            print('ERROR:', b.get('error'))
        print()

    print('\nHISTORY (last 10 of', len(history), 'total):')
    print('-' * 60)
    for b in history[-10:]:
        print(b.get('id'), '|', b.get('created_at', '')[:10], '|', b.get('status'), '|', b.get('amount'), '|', b.get('recipient', '')[:25])
        if b.get('error'):
            print('  ERROR:', b.get('error'))

    print('\n=== BILLS FROM LAST 2 DAYS ===')
    cutoff = (datetime.now() - timedelta(days=2)).isoformat()
    recent = [b for b in pending + history if b.get('created_at', '') >= cutoff]
    recent.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    if recent:
        for b in recent:
            print(b.get('id'), '|', b.get('created_at', '')[:16], '|', b.get('status'), '|', b.get('amount'), '|', b.get('recipient', '')[:25])
    else:
        print('No bills in last 2 days')

    print('\n=== RECENT LOG ===')
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text().splitlines()
        print('Last 20 of', len(lines), 'lines:')
        for line in lines[-20:]:
            print(' ', line)
    else:
        print('No log file yet')

    print('\n' + '=' * 60)


if __name__ == '__main__':
    main()
