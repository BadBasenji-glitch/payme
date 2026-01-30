#!/usr/bin/env python3
"""Check recent payme activity."""

import json
from pathlib import Path
from datetime import datetime, timedelta

STORAGE_PATH = Path('/config/.storage/payme')


def main():
    print('=' * 60)
    print('PAYME RECENT ACTIVITY CHECK')
    print('=' * 60)

    photos_file = STORAGE_PATH / 'processed_photos.json'
    print('\n=== PROCESSED PHOTOS ===')
    if photos_file.exists():
        data = json.loads(photos_file.read_text())
        processed = data.get('processed', [])
        print('Total processed:', len(processed))
        print('Last 10:')
        for pid in processed[-10:]:
            print(' ', pid)
    else:
        print('No file found')

    emails_file = STORAGE_PATH / 'processed_emails.json'
    print('\n=== PROCESSED EMAILS ===')
    if emails_file.exists():
        data = json.loads(emails_file.read_text())
        processed = data.get('processed', [])
        print('Total processed:', len(processed))
        print('Last 10:')
        for eid in processed[-10:]:
            print(' ', eid)
    else:
        print('No file found')

    history_file = STORAGE_PATH / 'payment_history.json'
    print('\n=== PAYMENT HISTORY ===')
    if history_file.exists():
        data = json.loads(history_file.read_text())
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
    else:
        print('No payment_history.json found')

    log_file = STORAGE_PATH / 'payme.log'
    print('\n=== RECENT LOG ===')
    if log_file.exists():
        lines = log_file.read_text().splitlines()
        print('Last 20 of', len(lines), 'lines:')
        for line in lines[-20:]:
            print(' ', line)
    else:
        print('No log file yet')

    print('\n' + '=' * 60)


if __name__ == '__main__':
    main()
