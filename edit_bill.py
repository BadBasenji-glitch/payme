#!/usr/bin/env python3
"""Edit bill details interactively."""

import sys
from config import PAYMENT_HISTORY_FILE
from storage import load_json, save_json
from iban import validate_iban, get_iban_info


def find_bill(bill_id):
    """Find a bill by ID in pending or history."""
    data = load_json(PAYMENT_HISTORY_FILE, {})

    for collection in ['pending', 'history']:
        for i, bill in enumerate(data.get(collection, [])):
            if bill.get('id') == bill_id:
                return data, collection, i, bill

    return None, None, None, None


def list_pending():
    """List pending bills with numbers for selection."""
    data = load_json(PAYMENT_HISTORY_FILE, {})
    pending = data.get('pending', [])

    if not pending:
        print('No pending bills.')
        return []

    print()
    print('PENDING BILLS:')
    print('-' * 70)
    print(f"{'#':<4} {'Amount':>10}  {'Recipient':<40}")
    print('-' * 70)
    for i, b in enumerate(pending, 1):
        amount = f"{b.get('amount', 0):.2f} {b.get('currency', 'EUR')}"
        print(f"{i:<4} {amount:>10}  {b.get('recipient', '')[:40]}")
    print()
    return pending


def show_bill(bill):
    """Display bill details."""
    print()
    print('=' * 60)
    print(f"Bill ID: {bill.get('id')}")
    print('=' * 60)
    print(f"  [1] Recipient:  {bill.get('recipient', '')}")
    print(f"  [2] IBAN:       {bill.get('iban', '') or '(empty)'}")
    print(f"  [3] BIC:        {bill.get('bic', '') or '(empty)'}")
    print(f"  [4] Amount:     {bill.get('amount', 0)}")
    print(f"  [5] Currency:   {bill.get('currency', 'EUR')}")
    print(f"  [6] Reference:  {bill.get('reference', '') or '(empty)'}")
    print(f"  [7] Bank Name:  {bill.get('bank_name', '') or '(empty)'}")
    print(f"  [8] Due Date:   {bill.get('due_date', '') or '(empty)'}")
    print(f"  [9] Invoice #:  {bill.get('invoice_number', '') or '(empty)'}")
    print()
    print(f"  Status:      {bill.get('status', 'unknown')}")
    print(f"  Confidence:  {bill.get('confidence', 0) * 100:.1f}%")
    print(f"  Source:      {bill.get('source', 'unknown')}")
    print('=' * 60)
    print()


def edit_field(bill, field_num):
    """Edit a specific field."""
    field_map = {
        '1': ('recipient', 'Recipient'),
        '2': ('iban', 'IBAN'),
        '3': ('bic', 'BIC'),
        '4': ('amount', 'Amount'),
        '5': ('currency', 'Currency'),
        '6': ('reference', 'Reference'),
        '7': ('bank_name', 'Bank Name'),
        '8': ('due_date', 'Due Date'),
        '9': ('invoice_number', 'Invoice Number'),
    }

    if field_num not in field_map:
        print('Invalid field number.')
        return False

    field_key, field_name = field_map[field_num]
    current = bill.get(field_key, '')

    print(f"\nCurrent {field_name}: {current or '(empty)'}")
    new_value = input(f"New {field_name} (Enter to keep current): ").strip()

    if not new_value:
        print('No change.')
        return False

    # Special handling for certain fields
    if field_key == 'amount':
        try:
            new_value = float(new_value.replace(',', '.'))
        except ValueError:
            print('Invalid amount.')
            return False

    if field_key == 'iban':
        # Remove spaces and validate
        new_value = new_value.replace(' ', '').upper()
        if new_value:
            if not validate_iban(new_value):
                print(f'Warning: IBAN checksum invalid, but saving anyway.')
            else:
                # Try to get bank info
                info = get_iban_info(new_value)
                if info['valid'] and info['bank']['name']:
                    print(f"Bank: {info['bank']['name']}")
                    update_bank = input('Update bank name and BIC from IBAN? [Y/n]: ').strip().lower()
                    if update_bank != 'n':
                        bill['bank_name'] = info['bank']['name']
                        bill['bic'] = info['bank']['bic']
                        print(f"Updated bank_name: {info['bank']['name']}")
                        print(f"Updated BIC: {info['bank']['bic']}")

    if field_key == 'currency':
        new_value = new_value.upper()
        if new_value not in ('EUR', 'USD', 'GBP', 'CHF'):
            print(f'Warning: Unusual currency code: {new_value}')

    bill[field_key] = new_value
    print(f"Updated {field_name}: {new_value}")

    # If we fixed the IBAN, remove the "NO IBAN" from recipient
    if field_key == 'iban' and new_value and ' - NO IBAN' in bill.get('recipient', ''):
        bill['recipient'] = bill['recipient'].replace(' - NO IBAN', '')
        print(f"Removed 'NO IBAN' from recipient: {bill['recipient']}")

    return True


def main():
    if len(sys.argv) < 2:
        # No bill ID provided - show numbered list and prompt
        pending = list_pending()
        if not pending:
            return

        choice = input('Enter bill number to edit (or q to quit): ').strip()
        if choice.lower() == 'q':
            return

        try:
            num = int(choice)
            if 1 <= num <= len(pending):
                bill_id = pending[num - 1].get('id')
            else:
                print('Invalid number.')
                return
        except ValueError:
            print('Invalid input.')
            return
    else:
        bill_id = sys.argv[1]

    data, collection, index, bill = find_bill(bill_id)

    if not bill:
        print(f'Bill not found: {bill_id}')
        return

    print(f'\nEditing bill from {collection}.')

    modified = False
    while True:
        show_bill(bill)

        choice = input('Enter field number to edit (1-9), s to save, q to quit: ').strip().lower()

        if choice == 'q':
            if modified:
                confirm = input('Discard changes? [y/N]: ').strip().lower()
                if confirm != 'y':
                    continue
            print('Cancelled.')
            return

        if choice == 's':
            if modified:
                data[collection][index] = bill
                save_json(PAYMENT_HISTORY_FILE, data)
                print('Saved!')
            else:
                print('No changes to save.')
            return

        if choice in '123456789':
            if edit_field(bill, choice):
                modified = True
        else:
            print('Invalid choice. Enter 1-9, s, or q.')


if __name__ == '__main__':
    main()
