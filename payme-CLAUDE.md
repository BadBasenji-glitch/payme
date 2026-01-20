# CLAUDE.md

Development guide for Claude (and humans) working on payme.

## Overview

payme is a Home Assistant integration that automates bill payments. Photos of bills are added to a Google Drive folder, parsed via GiroCode QR or Gemini OCR, and paid via Wise with manual approval.

**Key Design Decisions:**
- All HTTP/API logic runs as subprocess via `poll.py` (not in pyscript) to avoid async issues
- pyscript only handles: HA entity updates, triggers, service registration, event handling
- GiroCode QR is tried first (100% accurate), Gemini OCR is fallback
- Personal Wise accounts cannot auto-fund transfers (PSD2) - user must approve in Wise app

## Quick Architecture

```
Google Drive → poll.py → gemini.py → wise.py → HA entities → Dashboard
                  ↓
              girocode.py (QR detection, tried first)
                  ↓
              iban.py (validation + bank lookup)
                  ↓
              dedup.py (duplicate check)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed technical reference.

## Module Structure

Keep code modular. Each file has a single responsibility:

| Module | Responsibility | Depends on |
|--------|----------------|------------|
| `poll.py` | Orchestration, entry point | all others |
| `google_drive.py` | Drive API auth and requests | `storage.py` |
| `gemini.py` | OCR and bill parsing | — |
| `girocode.py` | QR code detection | — |
| `iban.py` | IBAN validation, bank lookup | `storage.py` |
| `wise.py` | Wise API operations | — |
| `dedup.py` | Duplicate detection | `storage.py` |
| `storage.py` | All JSON file read/write | — |
| `notify.py` | HA notification calls | — |
| `config.py` | Load secrets, constants, status mappings | — |

**Rules:**

- One module per concern
- Shared utilities go in a dedicated module, not duplicated
- `poll.py` is the only entry point; other modules are libraries
- No circular imports

## No Code Duplication

Before writing a function, check if it exists:

| Need | Location |
|------|----------|
| Read/write JSON files | `storage.py` |
| HTTP requests with retry | `http_client.py` |
| Load secrets/config | `config.py` |
| Format currency | `formatting.py` |
| Parse dates | `formatting.py` |
| Log with context | `logging_utils.py` |

If a function is used by more than one module, it belongs in a shared module.

**Bad:**
```python
# In gemini.py
def load_json(path):
    with open(path) as f:
        return json.load(f)

# In dedup.py (duplicated!)
def load_json(path):
    with open(path) as f:
        return json.load(f)
```

**Good:**
```python
# In storage.py
def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)

# In gemini.py
from storage import load_json

# In dedup.py
from storage import load_json
```

## File Locations

| Path | Purpose | Editable at runtime |
|------|---------|---------------------|
| `/config/scripts/payme/` | Core Python logic | Yes |
| `/config/pyscript/modules/payme/` | HA integration | Requires reload |
| `/config/www/payme/` | Dashboard JS/CSS | Requires browser refresh |
| `/config/.storage/payme/` | Runtime data, tokens, caches | Yes (careful) |
| `/config/secrets.yaml` | API keys | Requires HA restart |

## Key Constraints

- Never log or print API tokens, even partially
- Never auto-execute payments without user approval
- IBAN validation must pass before creating Wise transfer
- All Wise API calls must have 2s delay between them
- Google Photos baseUrls expire in 60 minutes—never cache them

## Testing

No test suite. Verify manually:

1. `python3 scripts/payme/iban.py DE89370400440532013000` — should validate and return bank name
2. `python3 scripts/payme/girocode.py test_image.jpg` — should extract payment data or return None
3. Check HA logs after poll: Developer Tools → Logs → filter "payme"

## Dependencies

Python (in HA environment):
- google-auth, google-auth-oauthlib
- google-api-python-client
- pyzbar
- opencv-python-headless
- requests

System:
- libzbar0 (for QR decoding)

## Common Tasks

**Add a new parsed field from bills:**
1. Update prompt in `gemini.py`
2. Add field to bill schema in `entities.py`
3. Update dashboard card in `payme-panel.js`

**Change polling interval:**
Edit `payme_triggers.py`, modify `@time_trigger` decorator.

**Add support for new currency:**
Modify currency detection in `gemini.py`, add handling in `wise.py` for quote creation.

**Add a new shared utility:**
1. Identify which module it belongs to (or create new if none fit)
2. Add function with type hints
3. Import where needed—never copy

## Code Style

- No classes unless necessary; prefer functions
- Type hints on function signatures
- f-strings for formatting
- Single quotes for strings
- 4-space indentation
- Max line length: 100
- Imports: stdlib, then third-party, then local (blank line between groups)
- One function per task; small functions over long ones

## Secrets Handling

These values come from `secrets.yaml` via HA, passed as environment variables to scripts:

- `PAYME_GEMINI_API_KEY`
- `PAYME_WISE_API_TOKEN`
- `PAYME_WISE_PROFILE_ID`

Never hardcode. Never log.

## Known Limitations

- Google Drive API has no "new items since" filter—we fetch all and compare locally
- Personal Wise accounts cannot fund transfers via API (PSD2 restriction)—user must fund in Wise app
- Wise 2FA is always required for transfers—this is expected, not a bug
- Folder matching requires listing all folders (no search by name API)
- openiban.com has no SLA—bank lookup may fail silently

## Debugging Guide

**Check if scripts work:**
```bash
cd /config/scripts/payme
python3 poll.py status        # System status
python3 poll.py list          # List pending bills
python3 poll.py poll          # Run poll manually
```

**Check pyscript logs:**
```bash
grep "payme" /config/home-assistant.log | tail -50
```

**Test individual modules:**
```bash
python3 iban.py DE89370400440532013000       # IBAN validation
python3 girocode.py /path/to/bill.jpg        # QR extraction
python3 gemini.py /path/to/bill.jpg          # OCR test
python3 wise.py                              # Wise dataclass tests
```

**Common Issues:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| "No tokens found" | Missing Google auth | Run `authorize_google.py` |
| "Folder not found" | Wrong folder name | Check `PAYME_ALBUM_NAME` matches exactly |
| "Invalid IBAN" | OCR error | Check image quality, try GiroCode |
| "Insufficient balance" | Low Wise funds | Top up EUR balance |
| Bill stuck in `awaiting_funding` | Normal for personal accounts | Fund in Wise app |

## Adding New Features

**New parsed field from bills:**
1. Update prompt in `gemini.py` (BILL_PARSE_PROMPT)
2. Add field to `ParsedBill` dataclass in `gemini.py`
3. Add field to `Bill` dataclass in `poll.py`
4. Update `process_photo_group()` to map the field
5. Update dashboard card in `payme-card.js` if needed

**New notification type:**
1. Add function in `notify.py` following existing pattern
2. Call from appropriate place in `poll.py`
3. Update event handler in `payme_triggers.py` if actionable

**New bill status:**
1. Add to `valid_statuses` list in `poll.py:set_bill_status()`
2. Add to `WISE_STATUS_MAP` in `config.py` if from Wise (centralized status mapping)
3. Update dashboard card to handle new status
4. Update `Transfer` dataclass properties if needed

**New HA service:**
1. Add `@service` function in `payme_triggers.py`
2. If it needs script execution, use `run_script(command, *args)`
3. Call `update_entities_from_status()` if state changed

## File Organization Rules

| If you need... | Put it in... |
|----------------|--------------|
| New API integration | New module (e.g., `newapi.py`) |
| Shared utility | `storage.py`, `http_client.py`, or `formatting.py` |
| New CLI command | `poll.py` (add to argparse) |
| New HA service | `payme_triggers.py` |
| New entity | `entities.py` + update in `payme_triggers.py` |
| New dashboard feature | `payme-card.js` |

## Important Patterns

**Environment variables in pyscript:**
```python
# payme_triggers.py reads secrets.yaml using PyYAML (with fallback)
def get_script_env():
    env = dict(os.environ)
    secrets = _parse_secrets_yaml(secrets_content)  # Uses PyYAML if available
    for yaml_key, env_key in _SECRETS_TO_ENV.items():
        if yaml_key in secrets:
            env[env_key] = str(secrets[yaml_key])
    return env
```

**Entity updates from scripts:**
```python
# run_script() returns parsed JSON
result = run_script('status')
if result['success']:
    state.set('sensor.payme_xyz', value, new_attributes={...})
```

**Error propagation:**
```python
# In modules, raise HttpError for API failures
raise HttpError(f'API call failed: {response.status_code}')

# In poll.py, catch and log/notify
try:
    result = some_api_call()
except HttpError as e:
    notify_error(str(e))
```
