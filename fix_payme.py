#!/usr/bin/env python3
"""
Payme diagnostic and fix script.
Run this when bills aren't showing up or the system isn't working.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

STORAGE_PATH = Path('/config/.storage/payme')
HISTORY_FILE = STORAGE_PATH / 'payment_history.json'
SECRETS_FILE = Path('/config/secrets.yaml')
SCRIPTS_PATH = Path('/config/scripts/payme')

VALID_CURRENCIES = ('EUR', 'USD', 'GBP', 'CHF', '')


def print_header(text):
    print()
    print('=' * 60)
    print(f'  {text}')
    print('=' * 60)


def print_ok(text):
    print(f'[OK] {text}')


def print_warn(text):
    print(f'[WARN] {text}')


def print_fail(text):
    print(f'[FAIL] {text}')


def print_fix(text):
    print(f'[FIX] {text}')


def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def check_dependencies():
    """Check and install missing Python packages."""
    print_header('1. CHECKING DEPENDENCIES')

    packages = {
        'requests': 'requests',
        'PIL': 'Pillow',
        'fpdf': 'fpdf2',
    }

    missing = []
    for module, package in packages.items():
        try:
            __import__(module)
            print_ok(f'{package} installed')
        except ImportError:
            print_fail(f'{package} missing')
            missing.append(package)

    if missing:
        print()
        response = input(f'Install missing packages ({", ".join(missing)})? [Y/n]: ').strip().lower()
        if response != 'n':
            for pkg in missing:
                print(f'Installing {pkg}...')
                subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', pkg])
            print_fix('Packages installed')

    return len(missing) == 0


def check_env_vars():
    """Check and set environment variables from secrets.yaml."""
    print_header('2. CHECKING ENVIRONMENT VARIABLES')

    required = {
        'PAYME_GEMINI_API_KEY': 'payme_gemini_api_key',
        'PAYME_WISE_API_TOKEN': 'payme_wise_api_token',
        'PAYME_WISE_PROFILE_ID': 'payme_wise_profile_id',
    }

    # Load secrets
    secrets = {}
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            if ':' in line and not line.strip().startswith('#'):
                key, _, value = line.partition(':')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                secrets[key] = value
        print_ok(f'Loaded {len(secrets)} secrets from {SECRETS_FILE}')
    else:
        print_fail(f'Secrets file not found: {SECRETS_FILE}')
        return False

    # Set environment variables
    all_set = True
    for env_var, secret_key in required.items():
        if secret_key in secrets:
            os.environ[env_var] = secrets[secret_key]
            masked = secrets[secret_key][:4] + '***'
            print_ok(f'{env_var} = {masked}')
        else:
            print_fail(f'{env_var} not found in secrets (looking for {secret_key})')
            all_set = False

    return all_set


def check_invalid_currencies():
    """Find and fix bills with invalid currency codes."""
    print_header('3. CHECKING FOR INVALID CURRENCIES')

    data = load_json(HISTORY_FILE)
    fixed = 0

    for collection in ['pending', 'history']:
        for bill in data.get(collection, []):
            currency = bill.get('currency', '')
            if currency and currency not in VALID_CURRENCIES:
                print_fail(f"Invalid currency '{currency}' in bill {bill.get('id')}")
                print(f"    Recipient: {bill.get('recipient', '')[:40]}")
                print(f"    Amount: {bill.get('amount')}")

                response = input(f"    Fix to EUR? [Y/n]: ").strip().lower()
                if response != 'n':
                    bill['currency'] = 'EUR'
                    fixed += 1
                    print_fix('Changed to EUR')

    if fixed > 0:
        save_json(HISTORY_FILE, data)
        print_fix(f'Saved {fixed} fix(es) to {HISTORY_FILE}')
    else:
        print_ok('No invalid currencies found')

    return fixed


def check_bill_counts():
    """Show bill counts by status."""
    print_header('4. BILL COUNTS')

    data = load_json(HISTORY_FILE)
    pending = data.get('pending', [])
    history = data.get('history', [])

    # Count by status
    status_counts = {}
    for bill in pending + history:
        status = bill.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f'Pending array: {len(pending)} bills')
    print(f'History array: {len(history)} bills')
    print()
    print('By status:')
    for status, count in sorted(status_counts.items()):
        print(f'  {status}: {count}')


def run_status():
    """Run poll.py status and check output."""
    print_header('5. RUNNING STATUS CHECK')

    os.chdir(SCRIPTS_PATH)

    try:
        result = subprocess.run(
            [sys.executable, 'poll.py', 'status'],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                pending = data.get('pending_bills', [])
                balance = data.get('balance')
                auth = data.get('auth_status', {})

                print_ok(f'Status command succeeded')
                print(f'  Pending bills: {len(pending)}')
                print(f'  Balance: {balance}')
                print(f'  Auth status: {auth.get("status", "unknown")}')

                if auth.get('status') in ('expiring', 'expired'):
                    print_warn(f'  Auth message: {auth.get("message")}')

                return True
            except json.JSONDecodeError:
                print_fail('Status returned invalid JSON')
                print(f'  Output: {result.stdout[:200]}')
        else:
            print_fail('Status command failed')
            print(f'  Error: {result.stderr[:200]}')

    except subprocess.TimeoutExpired:
        print_fail('Status command timed out')
    except Exception as e:
        print_fail(f'Error running status: {e}')

    return False


def refresh_entities():
    """Refresh HA entities via pyscript."""
    print_header('6. REFRESHING ENTITIES')

    token = os.environ.get('SUPERVISOR_TOKEN', '')
    if not token:
        print_warn('SUPERVISOR_TOKEN not available - cannot refresh entities')
        print('  Run this manually in HA: Developer Tools → Services → pyscript.payme_refresh')
        return False

    try:
        import requests
        response = requests.post(
            'http://supervisor/core/api/services/pyscript/payme_refresh',
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )

        if response.status_code == 200:
            print_ok('Entity refresh triggered')

            # Check entity state
            import time
            time.sleep(2)

            response = requests.get(
                'http://supervisor/core/api/states/sensor.payme_pending_bills',
                headers={'Authorization': f'Bearer {token}'},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                state = data.get('state')
                count = data.get('attributes', {}).get('count')
                print_ok(f'Entity updated: state={state}, count={count}')
                return True
        else:
            print_fail(f'Refresh failed: {response.status_code}')

    except Exception as e:
        print_fail(f'Error refreshing: {e}')

    return False


def main():
    print()
    print('PAYME DIAGNOSTIC AND FIX SCRIPT')
    print('=' * 60)

    # Run checks
    check_dependencies()
    env_ok = check_env_vars()

    if not env_ok:
        print()
        print_fail('Cannot continue without environment variables')
        return

    check_invalid_currencies()
    check_bill_counts()
    run_status()
    refresh_entities()

    print()
    print_header('DONE')
    print('If bills still not showing, try:')
    print('  1. Hard refresh browser (Ctrl+Shift+R)')
    print('  2. Check HA logs for pyscript errors')
    print('  3. Run: python3 manage_bills.py')


if __name__ == '__main__':
    main()
