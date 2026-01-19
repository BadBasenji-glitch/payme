#!/usr/bin/env python3
"""
Payme Diagnostic Script
Checks 25 most likely problems and outputs results to a file.

Run: python3 diagnose.py
Output: /tmp/payme_diagnostic.txt
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_FILE = '/tmp/payme_diagnostic.txt'
results = []

def log(msg):
    """Log to both console and results."""
    print(msg)
    results.append(msg)

def section(title):
    """Start a new section."""
    log('')
    log('=' * 60)
    log(f'  {title}')
    log('=' * 60)

def check(name, condition, details=''):
    """Log a check result."""
    status = '[OK]' if condition else '[FAIL]'
    log(f'{status} {name}')
    if details:
        for line in details.split('\n')[:10]:
            log(f'      {line}')
    return condition

def run_cmd(cmd, timeout=30):
    """Run a command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, '', 'TIMEOUT'
    except Exception as e:
        return -1, '', str(e)

def main():
    log(f'Payme Diagnostic Report')
    log(f'Generated: {datetime.now().isoformat()}')
    log(f'Python: {sys.version}')

    # =========================================================================
    section('1. DIRECTORY STRUCTURE')
    # =========================================================================

    paths = [
        '/config/pyscript',
        '/config/pyscript/apps',
        '/config/pyscript/apps/payme',
        '/config/pyscript/modules',
        '/config/pyscript/modules/payme',
        '/config/scripts/payme',
        '/config/.storage/payme',
        '/config/www/payme',
    ]

    for p in paths:
        exists = Path(p).exists()
        is_dir = Path(p).is_dir() if exists else False
        check(f'Directory: {p}', exists and is_dir)

    # =========================================================================
    section('2. REQUIRED FILES')
    # =========================================================================

    files = [
        ('/config/pyscript/apps/payme/__init__.py', 'Pyscript app'),
        ('/config/pyscript/modules/payme/__init__.py', 'Pyscript module init'),
        ('/config/pyscript/modules/payme/entities.py', 'Pyscript entities'),
        ('/config/scripts/payme/poll.py', 'Poll script'),
        ('/config/scripts/payme/wise.py', 'Wise API'),
        ('/config/scripts/payme/config.py', 'Config'),
        ('/config/scripts/payme/notify.py', 'Notifications'),
        ('/config/.storage/payme/payment_history.json', 'Payment history'),
        ('/config/www/payme/payme-card.js', 'Dashboard card'),
    ]

    for path, desc in files:
        p = Path(path)
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        check(f'{desc}: {path}', exists and size > 0, f'Size: {size} bytes')

    # =========================================================================
    section('3. PYSCRIPT CONFIGURATION')
    # =========================================================================

    config_file = Path('/config/configuration.yaml')
    if config_file.exists():
        content = config_file.read_text()
        check('pyscript in configuration.yaml', 'pyscript:' in content)
        check('allow_all_imports enabled', 'allow_all_imports: true' in content)
        check('hass_is_global enabled', 'hass_is_global: true' in content)

        # Extract pyscript config section
        lines = content.split('\n')
        in_pyscript = False
        pyscript_config = []
        for line in lines:
            if line.strip().startswith('pyscript:'):
                in_pyscript = True
            elif in_pyscript:
                if line and not line.startswith(' ') and not line.startswith('\t'):
                    break
                pyscript_config.append(line)

        if pyscript_config:
            log('  Pyscript config:')
            for line in pyscript_config[:15]:
                log(f'    {line}')
    else:
        check('configuration.yaml exists', False)

    # =========================================================================
    section('4. PYSCRIPT APP CONFIG (apps.yaml)')
    # =========================================================================

    apps_yaml = Path('/config/pyscript/apps.yaml')
    if apps_yaml.exists():
        content = apps_yaml.read_text()
        check('apps.yaml exists', True, content[:500])
        check('payme app configured', 'payme' in content.lower())
    else:
        check('apps.yaml exists', False, 'File not found - app config may be inline')

    # Check for inline config in __init__.py or config
    init_file = Path('/config/pyscript/apps/payme/__init__.py')
    if init_file.exists():
        content = init_file.read_text()
        check('App __init__.py has content', len(content) > 100, f'Size: {len(content)} chars')
        check('Has @service decorator', '@service' in content)
        check('Has @time_trigger decorator', '@time_trigger' in content)
        check('Uses pyscript.app_config', 'pyscript.app_config' in content or 'app_config' in content)

    # =========================================================================
    section('5. PYSCRIPT MODULE IMPORTS')
    # =========================================================================

    module_init = Path('/config/pyscript/modules/payme/__init__.py')
    if module_init.exists():
        content = module_init.read_text()
        log(f'  Module __init__.py content:')
        for line in content.split('\n')[:20]:
            log(f'    {line}')

        check('Exports update_all_entities', 'update_all_entities' in content)
        check('Exports update_pending_bills', 'update_pending_bills' in content)

    # =========================================================================
    section('6. ENVIRONMENT VARIABLES')
    # =========================================================================

    env_vars = [
        'SUPERVISOR_TOKEN',
        'PAYME_GEMINI_API_KEY',
        'PAYME_WISE_API_TOKEN',
        'PAYME_WISE_PROFILE_ID',
    ]

    for var in env_vars:
        val = os.environ.get(var, '')
        has_value = len(val) > 0
        masked = f'{val[:8]}...' if len(val) > 8 else ('SET' if val else 'NOT SET')
        check(f'Env var: {var}', has_value, f'Value: {masked}')

    # =========================================================================
    section('7. POLL.PY STATUS COMMAND')
    # =========================================================================

    code, stdout, stderr = run_cmd('cd /config/scripts/payme && python3 poll.py status')
    check('poll.py status runs', code == 0, f'Return code: {code}')

    if stdout:
        try:
            data = json.loads(stdout)
            pending = data.get('pending_bills', [])
            balance = data.get('balance', 0)
            check(f'Returns valid JSON', True)
            check(f'Pending bills count: {len(pending)}', True)
            check(f'Balance: {balance}', balance > 0)
            if pending:
                log(f'  First pending bill: {pending[0].get("recipient", "unknown")}')
        except json.JSONDecodeError as e:
            check('Returns valid JSON', False, f'Error: {e}')
            log(f'  Raw output: {stdout[:300]}')

    if stderr:
        log(f'  Stderr: {stderr[:300]}')

    # =========================================================================
    section('8. DATA FILES CONTENT')
    # =========================================================================

    history_file = Path('/config/.storage/payme/payment_history.json')
    if history_file.exists():
        try:
            data = json.loads(history_file.read_text())
            pending = data.get('pending', [])
            history = data.get('history', [])
            check(f'payment_history.json valid', True)
            check(f'Pending array: {len(pending)} bills', True)
            check(f'History array: {len(history)} bills', True)

            if pending:
                log(f'  Pending bills:')
                for b in pending[:3]:
                    log(f'    - {b.get("id")}: {b.get("recipient")} - {b.get("status")}')

            if history:
                log(f'  History bills:')
                for b in history[:3]:
                    log(f'    - {b.get("id")}: {b.get("recipient")} - {b.get("status")}')
        except Exception as e:
            check('payment_history.json valid', False, str(e))

    # =========================================================================
    section('9. HOME ASSISTANT API ACCESS')
    # =========================================================================

    token = os.environ.get('SUPERVISOR_TOKEN', '')
    if token:
        # Test API access
        code, stdout, stderr = run_cmd(
            f'curl -s -H "Authorization: Bearer {token}" http://supervisor/core/api/'
        )
        check('HA API accessible', code == 0 and 'message' in stdout.lower())

        # Get entity state
        code, stdout, stderr = run_cmd(
            f'curl -s -H "Authorization: Bearer {token}" http://supervisor/core/api/states/sensor.payme_pending_bills'
        )
        if code == 0 and stdout:
            try:
                entity = json.loads(stdout)
                state = entity.get('state', 'unknown')
                attrs = entity.get('attributes', {})
                bills_json = attrs.get('bills', '[]')
                check(f'Entity state: {state}', True)

                try:
                    bills = json.loads(bills_json)
                    if bills:
                        log(f'  Entity shows: {bills[0].get("recipient", "unknown")}')
                except:
                    log(f'  Bills attr: {bills_json[:100]}')
            except:
                check('Entity readable', False)
    else:
        check('SUPERVISOR_TOKEN available', False)

    # =========================================================================
    section('10. PYSCRIPT SERVICE CHECK')
    # =========================================================================

    if token:
        code, stdout, stderr = run_cmd(
            f'curl -s -H "Authorization: Bearer {token}" http://supervisor/core/api/services'
        )
        if code == 0:
            try:
                services = json.loads(stdout)
                pyscript_services = [s for s in services if s.get('domain') == 'pyscript']
                if pyscript_services:
                    svc_list = list(pyscript_services[0].get('services', {}).keys())
                    payme_services = [s for s in svc_list if 'payme' in s]
                    check(f'Pyscript domain registered', True)
                    check(f'Payme services: {len(payme_services)}', len(payme_services) > 0)
                    log(f'  Services: {", ".join(payme_services[:10])}')
                else:
                    check('Pyscript domain registered', False)
            except:
                check('Services API readable', False)

    # =========================================================================
    section('11. SUBPROCESS FROM PYSCRIPT CONTEXT')
    # =========================================================================

    # Simulate what pyscript does
    test_script = '''
import subprocess
import os
import json

env = {
    **os.environ,
    'PAYME_GEMINI_API_KEY': os.environ.get('PAYME_GEMINI_API_KEY', ''),
    'PAYME_WISE_API_TOKEN': os.environ.get('PAYME_WISE_API_TOKEN', ''),
    'PAYME_WISE_PROFILE_ID': os.environ.get('PAYME_WISE_PROFILE_ID', ''),
}

result = subprocess.run(
    ['python3', '/config/scripts/payme/poll.py', 'status'],
    capture_output=True,
    text=True,
    timeout=30,
    env=env,
    cwd='/config/scripts/payme',
)

print(f'RETURN_CODE:{result.returncode}')
print(f'STDOUT_LEN:{len(result.stdout)}')
print(f'STDERR:{result.stderr[:200] if result.stderr else "none"}')
try:
    data = json.loads(result.stdout)
    print(f'PENDING_COUNT:{len(data.get("pending_bills", []))}')
except:
    print('JSON_PARSE:FAILED')
'''

    code, stdout, stderr = run_cmd(f'python3 -c "{test_script}"')
    check('Subprocess execution works', code == 0)
    if stdout:
        for line in stdout.split('\n'):
            if line.strip():
                log(f'  {line}')
    if stderr:
        log(f'  Subprocess stderr: {stderr[:200]}')

    # =========================================================================
    section('12. FILE PERMISSIONS')
    # =========================================================================

    code, stdout, stderr = run_cmd('ls -la /config/pyscript/apps/payme/')
    log(f'  Pyscript app permissions:')
    for line in stdout.split('\n')[:5]:
        log(f'    {line}')

    code, stdout, stderr = run_cmd('ls -la /config/scripts/payme/*.py | head -5')
    log(f'  Script permissions:')
    for line in stdout.split('\n')[:5]:
        log(f'    {line}')

    # =========================================================================
    section('13. PYTHON PATH AND IMPORTS')
    # =========================================================================

    code, stdout, stderr = run_cmd('cd /config/scripts/payme && python3 -c "import poll; print(\"poll OK\")"')
    check('Can import poll.py', code == 0 and 'OK' in stdout, stderr[:100] if stderr else '')

    code, stdout, stderr = run_cmd('cd /config/scripts/payme && python3 -c "import config; print(\"config OK\")"')
    check('Can import config.py', code == 0 and 'OK' in stdout, stderr[:100] if stderr else '')

    code, stdout, stderr = run_cmd('cd /config/scripts/payme && python3 -c "import wise; print(\"wise OK\")"')
    check('Can import wise.py', code == 0 and 'OK' in stdout, stderr[:100] if stderr else '')

    # =========================================================================
    section('14. HOME ASSISTANT LOGS')
    # =========================================================================

    log_locations = [
        '/config/home-assistant.log',
        '/config/home-assistant.log.1',
        '/homeassistant/home-assistant.log',
    ]

    for log_path in log_locations:
        if Path(log_path).exists():
            code, stdout, stderr = run_cmd(f'grep -i "pyscript\\|payme" {log_path} | tail -20')
            if stdout.strip():
                log(f'  Found in {log_path}:')
                for line in stdout.split('\n')[:10]:
                    log(f'    {line[:120]}')
            break
    else:
        log('  No HA log files found')

    # Check journalctl
    code, stdout, stderr = run_cmd('journalctl -u homeassistant 2>/dev/null | grep -i "pyscript\\|payme" | tail -10')
    if stdout.strip():
        log('  From journalctl:')
        for line in stdout.split('\n')[:5]:
            log(f'    {line[:120]}')

    # =========================================================================
    section('15. PYSCRIPT STATE OBJECT TEST')
    # =========================================================================

    # This tests if the state.set works by checking what happens when we try to update
    log('  Note: state.set() only works inside pyscript context')
    log('  Checking if entity exists and is writable via API...')

    if token:
        test_data = json.dumps({
            'state': '999',
            'attributes': {
                'test': 'diagnostic',
                'friendly_name': 'Pending Bills'
            }
        })
        code, stdout, stderr = run_cmd(
            f"curl -s -X POST -H 'Authorization: Bearer {token}' -H 'Content-Type: application/json' -d '{test_data}' http://supervisor/core/api/states/sensor.payme_test_entity"
        )
        check('Can create entity via API', code == 0 and 'entity_id' in stdout.lower())

        # Clean up test entity
        run_cmd(f"curl -s -X DELETE -H 'Authorization: Bearer {token}' http://supervisor/core/api/states/sensor.payme_test_entity")

    # =========================================================================
    section('16. CARD DATA FLOW')
    # =========================================================================

    log('  Data flow: payment_history.json -> poll.py status -> pyscript -> entity -> card')

    # Step 1: Check file
    file_pending = []
    if history_file.exists():
        data = json.loads(history_file.read_text())
        file_pending = data.get('pending', [])
        log(f'  1. File has {len(file_pending)} pending bills')
        if file_pending:
            log(f'     First: {file_pending[0].get("recipient")}')

    # Step 2: Check poll.py output
    code, stdout, stderr = run_cmd('cd /config/scripts/payme && python3 poll.py status')
    if code == 0:
        data = json.loads(stdout)
        poll_pending = data.get('pending_bills', [])
        log(f'  2. poll.py returns {len(poll_pending)} pending bills')
        if poll_pending:
            log(f'     First: {poll_pending[0].get("recipient")}')

    # Step 3: Check entity
    if token:
        code, stdout, stderr = run_cmd(
            f'curl -s -H "Authorization: Bearer {token}" http://supervisor/core/api/states/sensor.payme_pending_bills'
        )
        if code == 0:
            entity = json.loads(stdout)
            bills_json = entity.get('attributes', {}).get('bills', '[]')
            entity_bills = json.loads(bills_json)
            log(f'  3. Entity has {len(entity_bills)} pending bills')
            if entity_bills:
                log(f'     First: {entity_bills[0].get("recipient")}')

    # Check for mismatch
    if file_pending and poll_pending:
        file_ids = {b.get('id') for b in file_pending}
        poll_ids = {b.get('id') for b in poll_pending}
        if file_ids != poll_ids:
            log(f'  MISMATCH: File and poll.py return different bills!')
            log(f'  File IDs: {file_ids}')
            log(f'  Poll IDs: {poll_ids}')

    # =========================================================================
    section('17. PYSCRIPT RELOAD TEST')
    # =========================================================================

    if token:
        code, stdout, stderr = run_cmd(
            f"curl -s -X POST -H 'Authorization: Bearer {token}' http://supervisor/core/api/services/pyscript/reload"
        )
        check('Pyscript reload succeeds', code == 0)

        import time
        time.sleep(2)

        # Check if services still exist
        code, stdout, stderr = run_cmd(
            f'curl -s -H "Authorization: Bearer {token}" http://supervisor/core/api/services'
        )
        if code == 0:
            services = json.loads(stdout)
            pyscript_services = [s for s in services if s.get('domain') == 'pyscript']
            if pyscript_services:
                svc_list = list(pyscript_services[0].get('services', {}).keys())
                payme_services = [s for s in svc_list if 'payme' in s]
                check(f'Payme services after reload: {len(payme_services)}', len(payme_services) > 0)

    # =========================================================================
    section('18. PYSCRIPT APP_CONFIG')
    # =========================================================================

    # Check if app_config is set in configuration.yaml
    config_file = Path('/config/configuration.yaml')
    if config_file.exists():
        content = config_file.read_text()
        check('apps: section in pyscript config', 'apps:' in content)

        # Look for payme app config
        if 'payme:' in content:
            log('  Found payme config in configuration.yaml')
            lines = content.split('\n')
            in_payme = False
            for i, line in enumerate(lines):
                if 'payme:' in line and in_payme == False:
                    in_payme = True
                    for j in range(i, min(i+15, len(lines))):
                        log(f'    {lines[j]}')
                    break

    # =========================================================================
    section('19. SYNTAX CHECK ON PYSCRIPT FILES')
    # =========================================================================

    pyscript_files = [
        '/config/pyscript/apps/payme/__init__.py',
        '/config/pyscript/modules/payme/__init__.py',
        '/config/pyscript/modules/payme/entities.py',
    ]

    for f in pyscript_files:
        if Path(f).exists():
            code, stdout, stderr = run_cmd(f'python3 -m py_compile {f}')
            check(f'Syntax OK: {Path(f).name}', code == 0, stderr[:100] if stderr else '')

    # =========================================================================
    section('20. PYSCRIPT SPECIFIC SYNTAX')
    # =========================================================================

    init_file = Path('/config/pyscript/apps/payme/__init__.py')
    if init_file.exists():
        content = init_file.read_text()

        # Check for common pyscript issues
        check('No bare pyscript.app_config at module level',
              'SCRIPT_ENV = ' not in content or 'pyscript.app_config' not in content.split('def ')[0])
        check('Uses get_script_env() function', 'def get_script_env' in content)
        check('run_script uses get_script_env()', 'env=get_script_env()' in content)

        # Check imports
        check('Imports subprocess', 'import subprocess' in content)
        check('Imports json', 'import json' in content)

    # =========================================================================
    section('21. POLL.PY PENDING BILLS FUNCTION')
    # =========================================================================

    code, stdout, stderr = run_cmd('''
cd /config/scripts/payme && python3 -c "
from poll import load_pending_bills
bills = load_pending_bills()
print(f'Loaded {len(bills)} pending bills')
for b in bills[:3]:
    print(f'  - {b.id}: {b.recipient} ({b.status})')
"
''')
    check('load_pending_bills() works', code == 0)
    if stdout:
        for line in stdout.split('\n')[:5]:
            log(f'  {line}')
    if stderr:
        log(f'  Error: {stderr[:200]}')

    # =========================================================================
    section('22. STORAGE FILE STRUCTURE')
    # =========================================================================

    storage_path = Path('/config/.storage/payme')
    if storage_path.exists():
        code, stdout, stderr = run_cmd('ls -la /config/.storage/payme/')
        log('  Storage files:')
        for line in stdout.split('\n'):
            if line.strip():
                log(f'    {line}')

    # =========================================================================
    section('23. RECENT MODIFICATIONS')
    # =========================================================================

    code, stdout, stderr = run_cmd('find /config/pyscript -name "*.py" -mmin -60 -ls 2>/dev/null')
    if stdout.strip():
        log('  Recently modified pyscript files (last hour):')
        for line in stdout.split('\n')[:5]:
            log(f'    {line}')
    else:
        log('  No pyscript files modified in last hour')

    code, stdout, stderr = run_cmd('find /config/scripts/payme -name "*.py" -mmin -60 -ls 2>/dev/null')
    if stdout.strip():
        log('  Recently modified script files (last hour):')
        for line in stdout.split('\n')[:5]:
            log(f'    {line}')

    # =========================================================================
    section('24. MEMORY AND PROCESS CHECK')
    # =========================================================================

    code, stdout, stderr = run_cmd('ps aux | grep -i pyscript | grep -v grep')
    if stdout.strip():
        log('  Pyscript processes:')
        for line in stdout.split('\n')[:3]:
            log(f'    {line[:100]}')
    else:
        log('  No dedicated pyscript processes (normal - runs in HA)')

    code, stdout, stderr = run_cmd('free -h 2>/dev/null || cat /proc/meminfo | head -5')
    log('  Memory:')
    for line in stdout.split('\n')[:3]:
        log(f'    {line}')

    # =========================================================================
    section('25. ENTITY DIRECT UPDATE TEST')
    # =========================================================================

    if token:
        log('  Testing direct entity update via API...')

        # Get current value
        code, stdout, stderr = run_cmd(
            f'curl -s -H "Authorization: Bearer {token}" http://supervisor/core/api/states/sensor.payme_pending_bills'
        )
        old_state = 'unknown'
        if code == 0:
            try:
                old_state = json.loads(stdout).get('state', 'unknown')
            except:
                pass

        # Set new value
        test_bills = json.dumps([{'id': 'test123', 'recipient': 'DIAGNOSTIC TEST', 'status': 'pending', 'amount': 0}])
        payload = json.dumps({
            'state': '1',
            'attributes': {
                'bills': test_bills,
                'count': 1,
                'friendly_name': 'Pending Bills',
                'icon': 'mdi:file-document-multiple'
            }
        })

        code, stdout, stderr = run_cmd(
            f"curl -s -X POST -H 'Authorization: Bearer {token}' -H 'Content-Type: application/json' -d '{payload}' http://supervisor/core/api/states/sensor.payme_pending_bills"
        )
        check('Entity update API call succeeds', code == 0)

        # Verify
        code, stdout, stderr = run_cmd(
            f'curl -s -H "Authorization: Bearer {token}" http://supervisor/core/api/states/sensor.payme_pending_bills'
        )
        if code == 0:
            try:
                entity = json.loads(stdout)
                bills_attr = entity.get('attributes', {}).get('bills', '')
                if 'DIAGNOSTIC TEST' in bills_attr:
                    check('Entity was updated successfully', True)
                    log('  Entity CAN be updated via API - pyscript state.set should work')
                else:
                    check('Entity was updated successfully', False, f'Bills: {bills_attr[:100]}')
            except Exception as e:
                check('Entity readable after update', False, str(e))

        log(f'  Note: Entity was modified for testing. Run pyscript.payme_refresh to restore.')

    # =========================================================================
    section('SUMMARY')
    # =========================================================================

    failures = [r for r in results if r.startswith('[FAIL]')]
    log(f'')
    log(f'Total checks with failures: {len(failures)}')
    if failures:
        log(f'Failed checks:')
        for f in failures:
            log(f'  {f}')

    # Write to file
    with open(OUTPUT_FILE, 'w') as f:
        f.write('\n'.join(results))

    log(f'')
    log(f'Report saved to: {OUTPUT_FILE}')
    log(f'Share this file for debugging assistance.')


if __name__ == '__main__':
    main()
