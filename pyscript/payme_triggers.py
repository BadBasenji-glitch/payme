"""
payme pyscript triggers and services for Home Assistant.

This file registers:
- Time triggers for polling
- Services for approve/reject/poll
- Event handlers for notification actions

All heavy lifting is done by shell_command calling the Python scripts.
"""

import json
import subprocess
import os
from datetime import datetime

# Path to payme scripts
SCRIPTS_PATH = '/config/scripts/payme'


def get_script_env():
    """Get environment variables for scripts. Must be called inside functions."""
    return {
        **os.environ,
        'PAYME_GEMINI_API_KEY': pyscript.app_config.get('gemini_api_key', ''),
        'PAYME_WISE_API_TOKEN': pyscript.app_config.get('wise_api_token', ''),
        'PAYME_WISE_PROFILE_ID': str(pyscript.app_config.get('wise_profile_id', '')),
        'PAYME_ALBUM_NAME': pyscript.app_config.get('album_name', 'bill-pay'),
        'PAYME_ALBUM_ID': pyscript.app_config.get('album_id', ''),
        'PAYME_NOTIFY_SERVICE': pyscript.app_config.get('notify_service', 'mobile_app_phone'),
    }


def run_script(command: str, *args) -> dict:
    """
    Run a payme script command.

    Returns dict with success, output, and error.
    """
    cmd = ['python3', f'{SCRIPTS_PATH}/poll.py', command] + list(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=get_script_env(),
            cwd=SCRIPTS_PATH,
        )

        output = result.stdout.strip()

        # Try to parse as JSON
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            data = {'raw_output': output}

        return {
            'success': result.returncode == 0,
            'data': data,
            'error': result.stderr.strip() if result.returncode != 0 else None,
        }

    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'data': None,
            'error': 'Script timeout',
        }
    except Exception as e:
        return {
            'success': False,
            'data': None,
            'error': str(e),
        }


def update_entities_from_status():
    """Fetch status and update all entities directly using state.set."""
    log.info('payme: update_entities_from_status called')

    result = run_script('status')
    log.info(f'payme: run_script result - success: {result.get("success")}, has_data: {result.get("data") is not None}')

    if not result['success']:
        log.error(f'payme: run_script failed - {result.get("error")}')
        return

    if not result['data']:
        log.error('payme: run_script returned no data')
        return

    data = result['data']

    # Update pending bills entity directly
    pending_bills = data.get('pending_bills', [])
    log.info(f'payme: got {len(pending_bills)} pending bills')
    if pending_bills:
        log.info(f'payme: first bill: {pending_bills[0].get("recipient", "unknown")}')

    # Filter by status
    pending = [b for b in pending_bills if b.get('status') == 'pending']
    state.set(
        'sensor.payme_pending_bills',
        len(pending),
        new_attributes={
            'bills': json.dumps(pending),
            'count': len(pending),
            'total_amount': sum(b.get('amount', 0) for b in pending),
            'friendly_name': 'Pending Bills',
            'icon': 'mdi:file-document-multiple',
            'unit_of_measurement': 'bills',
        }
    )
    log.info(f'payme: set pending_bills entity to {len(pending)} bills')

    # Update Wise balance
    balance = data.get('balance', 0)
    if balance is not None:
        state.set(
            'sensor.payme_wise_balance',
            round(balance, 2),
            new_attributes={
                'currency': 'EUR',
                'friendly_name': 'Wise Balance',
                'icon': 'mdi:cash',
                'unit_of_measurement': 'EUR',
                'device_class': 'monetary',
            }
        )
        log.info(f'payme: set balance to {balance}')

    # Update awaiting 2FA
    awaiting_2fa = data.get('awaiting_2fa', [])
    state.set(
        'sensor.payme_awaiting_wise_2fa',
        len(awaiting_2fa),
        new_attributes={
            'transfers': json.dumps(awaiting_2fa),
            'count': len(awaiting_2fa),
            'friendly_name': 'Awaiting Wise 2FA',
            'icon': 'mdi:two-factor-authentication',
        }
    )

    # Update Google auth status
    auth = data.get('auth_status', {})
    if auth:
        state.set(
            'sensor.payme_google_auth_status',
            auth.get('status', 'unknown'),
            new_attributes={
                'expires_at': auth.get('expires_at', ''),
                'message': auth.get('message', ''),
                'friendly_name': 'Google Auth Status',
                'icon': 'mdi:google',
            }
        )

    # Load and update payment history from file
    try:
        history_file = '/config/.storage/payme/payment_history.json'
        with open(history_file, 'r') as f:
            history_data = json.load(f)
        history = history_data.get('history', [])
        state.set(
            'sensor.payme_payment_history',
            len(history),
            new_attributes={
                'history': json.dumps(history),
                'total_count': len(history),
                'friendly_name': 'Payment History',
                'icon': 'mdi:history',
            }
        )
        log.info(f'payme: set payment history to {len(history)} items')
    except Exception as e:
        log.error(f'payme: failed to load payment history: {e}')

    log.info('payme: entity update complete')


# =============================================================================
# Time Triggers
# =============================================================================

@time_trigger('cron(*/30 * * * *)')
def payme_scheduled_poll():
    """Poll for new bills every 30 minutes."""
    log.info('payme: Starting scheduled poll')

    from payme import update_last_poll

    result = run_script('poll')

    if result['success']:
        data = result.get('data', {})
        update_last_poll(
            success=True,
            bills_found=data.get('bills_created', 0),
            errors=data.get('errors', []),
        )
        log.info(f"payme: Poll complete - {data.get('bills_created', 0)} new bills")
    else:
        update_last_poll(
            success=False,
            bills_found=0,
            errors=[result.get('error', 'Unknown error')],
        )
        log.error(f"payme: Poll failed - {result.get('error')}")

    # Update all entities
    update_entities_from_status()


@time_trigger('cron(0 6 * * *)')
def payme_daily_maintenance():
    """Daily maintenance: check auth, cleanup old data."""
    log.info('payme: Running daily maintenance')

    # Update entities
    update_entities_from_status()

    # Check Google auth
    from payme import update_google_auth_status

    result = run_script('status')
    if result['success'] and result['data']:
        auth = result['data'].get('auth_status', {})
        if auth.get('status') in ('expiring', 'expired'):
            log.warning(f"payme: Google auth issue - {auth.get('message')}")


# =============================================================================
# Services
# =============================================================================

@service
def payme_poll():
    """
    Manually trigger a poll for new bills.

    Call via: service: pyscript.payme_poll
    """
    log.info('payme: Manual poll triggered')
    payme_scheduled_poll()


@service
def payme_approve(bill_id: str):
    """
    Approve a pending bill.

    Call via:
        service: pyscript.payme_approve
        data:
            bill_id: "abc123"
    """
    log.info(f'payme: Approving bill {bill_id}')

    result = run_script('approve', bill_id)

    if result['success']:
        log.info(f'payme: Bill {bill_id} approved')
    else:
        log.error(f"payme: Approve failed - {result.get('error')}")

    update_entities_from_status()


@service
def payme_reject(bill_id: str):
    """
    Reject a pending bill.

    Call via:
        service: pyscript.payme_reject
        data:
            bill_id: "abc123"
    """
    log.info(f'payme: Rejecting bill {bill_id}')

    result = run_script('reject', bill_id)

    if result['success']:
        log.info(f'payme: Bill {bill_id} rejected')
    else:
        log.error(f"payme: Reject failed - {result.get('error')}")

    update_entities_from_status()


@service
def payme_override_duplicate(bill_id: str):
    """
    Override duplicate warning for a bill.

    Call via:
        service: pyscript.payme_override_duplicate
        data:
            bill_id: "abc123"
    """
    log.info(f'payme: Overriding duplicate for bill {bill_id}')

    result = run_script('override-duplicate', bill_id)
    update_entities_from_status()


@service
def payme_refresh():
    """
    Refresh all entity states without polling for new bills.

    Call via: service: pyscript.payme_refresh
    """
    log.info('payme: Refreshing entities')
    update_entities_from_status()


@service
def payme_get_status():
    """
    Get current payme status as JSON.

    Call via: service: pyscript.payme_get_status

    Logs status to pyscript log.
    """
    result = run_script('status')
    log.info(f"payme status: {result.get('data', {})}")


@service
def payme_set_status(bill_id: str, status: str):
    """
    Manually set a bill's status.

    Call via:
        service: pyscript.payme_set_status
        data:
            bill_id: "abc123"
            status: "paid"

    Valid statuses:
        - pending: Awaiting approval
        - paid: Payment completed
        - rejected: User rejected
        - failed: Payment failed
        - processing: Payment in progress
        - awaiting_2fa: Needs Wise 2FA
        - insufficient_balance: Needs more funds
    """
    valid_statuses = [
        'pending', 'paid', 'rejected', 'failed',
        'processing', 'awaiting_2fa', 'insufficient_balance'
    ]

    if status not in valid_statuses:
        log.error(f'payme: Invalid status "{status}". Valid: {valid_statuses}')
        return

    log.info(f'payme: Setting bill {bill_id} status to {status}')

    result = run_script('set-status', bill_id, status)

    if result['success']:
        log.info(f'payme: Bill {bill_id} status updated to {status}')
    else:
        log.error(f"payme: Set status failed - {result.get('error')}")

    update_entities_from_status()


# =============================================================================
# Event Handlers
# =============================================================================

@event_trigger('mobile_app_notification_action')
def handle_notification_action(**kwargs):
    """
    Handle notification action buttons.

    Actions are formatted as:
    - PAYME_APPROVE_<bill_id>
    - PAYME_REJECT_<bill_id>
    - PAYME_VIEW_<bill_id>
    """
    action = kwargs.get('action', '')

    if not action.startswith('PAYME_'):
        return

    log.info(f'payme: Notification action received: {action}')

    parts = action.split('_', 2)
    if len(parts) < 3:
        return

    action_type = parts[1]
    bill_id = parts[2]

    if action_type == 'APPROVE':
        payme_approve(bill_id=bill_id)

    elif action_type == 'REJECT':
        payme_reject(bill_id=bill_id)

    elif action_type == 'VIEW':
        # Trigger a refresh so dashboard shows latest
        update_entities_from_status()


@event_trigger('ios.notification_action_fired')
def handle_ios_notification_action(**kwargs):
    """Handle iOS notification actions (different event name)."""
    # iOS uses 'actionName' instead of 'action'
    action = kwargs.get('actionName', kwargs.get('action', ''))
    handle_notification_action(action=action)


# =============================================================================
# Startup
# =============================================================================

@time_trigger('startup')
def payme_startup():
    """Initialize payme on Home Assistant startup."""
    log.info('payme: Initializing on startup')

    # Create initial entity states
    from payme import (
        update_pending_bills,
        update_wise_balance,
        update_google_auth_status,
        update_awaiting_2fa,
        update_last_poll,
    )

    # Set initial states
    update_pending_bills([])
    update_wise_balance(0.0)
    update_google_auth_status('unknown', message='Not yet checked')
    update_awaiting_2fa([])

    # Fetch actual status
    task.sleep(5)  # Wait for HA to be fully ready
    update_entities_from_status()

    log.info('payme: Startup complete')
