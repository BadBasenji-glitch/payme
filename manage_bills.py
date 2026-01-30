#!/usr/bin/env python3
"""Interactive script to manage processed bills."""

import json
from pathlib import Path
from datetime import datetime, timedelta

STORAGE_PATH = Path('/config/.storage/payme')
HISTORY_FILE = STORAGE_PATH / 'payment_history.json'
PROCESSED_PHOTOS_FILE = STORAGE_PATH / 'processed_photos.json'
PROCESSED_EMAILS_FILE = STORAGE_PATH / 'processed_emails.json'


def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def get_bills_in_range(days):
    """Get all bills created within the last N days."""
    data = load_json(HISTORY_FILE)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    bills = []
    for b in data.get('pending', []):
        if b.get('created_at', '') >= cutoff:
            b['_location'] = 'pending'
            bills.append(b)

    for b in data.get('history', []):
        if b.get('created_at', '') >= cutoff:
            b['_location'] = 'history'
            bills.append(b)

    bills.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return bills


def display_bills(bills):
    """Display bills in numbered list."""
    print()
    print('=' * 70)
    print(f'{"#":<4} {"Status":<12} {"Amount":>10} {"Due Date":<12} {"Vendor":<30}')
    print('=' * 70)

    for i, b in enumerate(bills, 1):
        status = b.get('status', 'unknown')
        amount = f"{b.get('amount', 0):.2f}"
        due = b.get('due_date', '')[:10] or 'N/A'
        vendor = b.get('recipient', 'Unknown')[:30]
        print(f'{i:<4} {status:<12} {amount:>10} {due:<12} {vendor:<30}')

    print('=' * 70)
    print()


def delete_bills(bills, indices):
    """Delete bills by their indices."""
    data = load_json(HISTORY_FILE)

    to_delete = [bills[i] for i in indices]
    deleted_ids = {b.get('id') for b in to_delete}

    data['pending'] = [b for b in data.get('pending', []) if b.get('id') not in deleted_ids]
    data['history'] = [b for b in data.get('history', []) if b.get('id') not in deleted_ids]

    save_json(HISTORY_FILE, data)

    print(f'Deleted {len(to_delete)} bill(s).')
    return to_delete


def reprocess_bills(bills, indices):
    """Remove photo/email IDs from processed lists so they get picked up again."""
    to_reprocess = [bills[i] for i in indices]

    # Collect photo IDs to remove
    photo_ids_to_remove = set()
    for b in to_reprocess:
        for pid in b.get('photo_ids', []):
            photo_ids_to_remove.add(pid)

    # Remove from processed_photos.json
    if photo_ids_to_remove:
        photos_data = load_json(PROCESSED_PHOTOS_FILE)
        processed = photos_data.get('processed', [])
        original_count = len(processed)
        processed = [p for p in processed if p not in photo_ids_to_remove]
        photos_data['processed'] = processed
        save_json(PROCESSED_PHOTOS_FILE, photos_data)
        removed = original_count - len(processed)
        if removed > 0:
            print(f'Removed {removed} photo ID(s) from processed list.')

    # Also delete the bills from history so they don't show as duplicates
    data = load_json(HISTORY_FILE)
    bill_ids_to_remove = {b.get('id') for b in to_reprocess}
    data['pending'] = [b for b in data.get('pending', []) if b.get('id') not in bill_ids_to_remove]
    data['history'] = [b for b in data.get('history', []) if b.get('id') not in bill_ids_to_remove]
    save_json(HISTORY_FILE, data)

    print(f'Marked {len(to_reprocess)} bill(s) for reprocessing.')
    print('Run a poll to pick them up again.')


def parse_selection(input_str, max_num):
    """Parse user input like '1,3,5' or '1-3' or '1,3-5' into list of indices."""
    indices = set()
    parts = input_str.replace(' ', '').split(',')

    for part in parts:
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-')
                for i in range(int(start), int(end) + 1):
                    if 1 <= i <= max_num:
                        indices.add(i - 1)
            except ValueError:
                pass
        else:
            try:
                i = int(part)
                if 1 <= i <= max_num:
                    indices.add(i - 1)
            except ValueError:
                pass

    return sorted(indices)


def main():
    print()
    print('PAYME BILL MANAGER')
    print('=' * 40)

    # Ask for number of days
    while True:
        try:
            days_input = input('How many days back to look? [7]: ').strip()
            days = int(days_input) if days_input else 7
            if days > 0:
                break
            print('Please enter a positive number.')
        except ValueError:
            print('Please enter a valid number.')

    # Get and display bills
    bills = get_bills_in_range(days)

    if not bills:
        print(f'\nNo bills found in the last {days} days.')
        return

    print(f'\nFound {len(bills)} bill(s) in the last {days} days:')
    display_bills(bills)

    # Ask about deletion
    delete_input = input('Enter bill numbers to DELETE (e.g., 1,3,5 or 1-3), or press Enter to skip: ').strip()

    if delete_input:
        indices = parse_selection(delete_input, len(bills))
        if indices:
            print(f'\nYou selected to delete:')
            for i in indices:
                b = bills[i]
                print(f'  - {b.get("recipient", "Unknown")[:40]} ({b.get("amount", 0):.2f})')

            confirm = input('\nConfirm deletion? (y/n): ').strip().lower()
            if confirm == 'y':
                delete_bills(bills, indices)
                # Refresh bills list after deletion
                bills = get_bills_in_range(days)
            else:
                print('Deletion cancelled.')
        else:
            print('No valid selection.')

    # Ask about reprocessing
    if bills:
        print(f'\nRemaining bills:')
        display_bills(bills)

        reprocess_input = input('Enter bill numbers to REPROCESS (e.g., 1,3,5 or 1-3), or press Enter to skip: ').strip()

        if reprocess_input:
            indices = parse_selection(reprocess_input, len(bills))
            if indices:
                print(f'\nYou selected to reprocess:')
                for i in indices:
                    b = bills[i]
                    print(f'  - {b.get("recipient", "Unknown")[:40]} ({b.get("amount", 0):.2f})')

                confirm = input('\nConfirm reprocessing? This will remove these bills and their photos will be picked up on next poll. (y/n): ').strip().lower()
                if confirm == 'y':
                    reprocess_bills(bills, indices)
                else:
                    print('Reprocessing cancelled.')
            else:
                print('No valid selection.')

    print('\nDone.')


if __name__ == '__main__':
    main()
