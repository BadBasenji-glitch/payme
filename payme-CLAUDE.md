# CLAUDE.md

## Overview

payme is a Home Assistant integration that automates bill payments. Photos of bills are added to a Google Photos album, parsed via Gemini, and paid via Wise with manual approval.

## Architecture

```
Google Photos → poll.py → gemini.py → wise.py → HA entities → Dashboard
                  ↓
              girocode.py (QR detection, tried first)
                  ↓
              iban.py (validation + bank lookup)
                  ↓
              dedup.py (duplicate check)
```

All HTTP logic runs in `/config/scripts/payme/` via shell_command (not pyscript) to avoid async issues.

pyscript handles only: HA entity updates, triggers, service registration.

## Module Structure

Keep code modular. Each file has a single responsibility:

| Module | Responsibility | Depends on |
|--------|----------------|------------|
| `poll.py` | Orchestration, entry point | all others |
| `google_photos.py` | Photos API auth and requests | `storage.py` |
| `gemini.py` | OCR and bill parsing | — |
| `girocode.py` | QR code detection | — |
| `iban.py` | IBAN validation, bank lookup | `storage.py` |
| `wise.py` | Wise API operations | — |
| `dedup.py` | Duplicate detection | `storage.py` |
| `storage.py` | All JSON file read/write | — |
| `notify.py` | HA notification calls | — |
| `config.py` | Load secrets, constants | — |

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

- Google Photos API has no "new items since" filter—we fetch all and compare locally
- Wise may require 2FA in app for some transfers—this is expected, not a bug
- Album matching requires listing all albums (no search by name API)
- openiban.com has no SLA—bank lookup may fail silently
