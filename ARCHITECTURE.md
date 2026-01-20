# payme Architecture

Technical reference for the payme bill payment automation system.

## System Overview

payme automates bill payments through a pipeline:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                               DATA FLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Google Drive          Home Assistant           External APIs               │
│  ─────────────         ──────────────           ─────────────               │
│                                                                             │
│  ┌─────────────┐       ┌─────────────┐         ┌─────────────┐             │
│  │ "bill-pay"  │──────►│ pyscript    │────────►│ Gemini API  │             │
│  │   folder    │       │ triggers    │         │ (OCR)       │             │
│  └─────────────┘       └──────┬──────┘         └─────────────┘             │
│        │                      │                                             │
│        │               ┌──────▼──────┐         ┌─────────────┐             │
│        │               │  poll.py    │────────►│ Wise API    │             │
│        │               │ orchestrator│         │ (payments)  │             │
│        │               └──────┬──────┘         └─────────────┘             │
│        │                      │                                             │
│        │               ┌──────▼──────┐         ┌─────────────┐             │
│        └──────────────►│   notify    │────────►│ HA Mobile   │             │
│         (Drive API)    │   .py       │         │ App         │             │
│                        └─────────────┘         └─────────────┘             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Reference

### Core Modules

#### `poll.py` - Main Orchestrator
**Location:** `/config/scripts/payme/poll.py`
**Purpose:** Entry point for all operations. CLI interface.

**Commands:**
| Command | Description |
|---------|-------------|
| `poll` | Check for new bills in Google Drive |
| `status` | Get current system status |
| `approve <bill_id>` | Approve a pending bill |
| `reject <bill_id>` | Reject a pending bill |
| `override-duplicate <bill_id>` | Clear duplicate warning |
| `set-status <bill_id> <status>` | Manually set bill status |
| `set-transfer-id <bill_id> <id>` | Link bill to Wise transfer |
| `check-transfers` | Update bill statuses from Wise |
| `list` | List pending bills |

**Key Classes:**
```python
@dataclass
class Bill:
    id: str                    # UUID (8 chars)
    recipient: str             # Payee name
    iban: str                  # Normalized IBAN (no spaces)
    bic: str                   # BIC/SWIFT code
    amount: float              # Payment amount
    currency: str              # Currency code (EUR)
    reference: str             # Payment reference
    bank_name: str             # Bank name from BIC lookup
    confidence: float          # OCR confidence (0.0-1.0)
    source: str                # 'girocode' or 'gemini'
    photo_ids: list[str]       # Source photo IDs
    created_at: str            # ISO timestamp
    due_date: str              # Payment due date
    invoice_number: str        # Extracted invoice number
    description: str           # Bill description
    original_text: str         # Original OCR text
    english_translation: str   # Translated text
    status: str                # Bill status (see below)
    paid_at: str               # Payment timestamp
    duplicate_warning: bool    # Duplicate detected
    low_confidence: bool       # Below threshold
    error: str                 # Error message
    transfer_id: int           # Wise transfer ID
```

**Bill Statuses:**
| Status | Description |
|--------|-------------|
| `pending` | Awaiting user approval |
| `awaiting_funding` | Transfer created, needs funding in Wise app |
| `awaiting_2fa` | Needs 2FA approval in Wise app |
| `processing` | Payment in progress |
| `paid` | Payment completed |
| `rejected` | User rejected |
| `failed` | Payment failed |
| `insufficient_balance` | Not enough funds |

---

#### `google_drive.py` - Google Drive API Client
**Location:** `/config/scripts/payme/google_drive.py`
**Purpose:** Fetch images from Google Drive folder.

**Key Functions:**
```python
def get_valid_access_token() -> str
    """Get/refresh OAuth token. Raises HttpError if expired."""

def check_token_health() -> dict
    """Check token status. Returns {status, expires_at, message}."""

def list_folders() -> list[dict]
    """List all folders. Returns [{id, title}, ...]."""

def find_folder(name: str = None, folder_id: str = None) -> dict
    """Find folder by name (fuzzy) or ID (exact)."""

def get_folder_id() -> str
    """Get configured folder ID, caching result."""

def list_folder_photos(folder_id: str = None) -> list[dict]
    """List images in folder. Returns [{id, filename, mimeType, creationTime}, ...]."""

def get_new_photos(folder_id: str = None) -> list[dict]
    """Get unprocessed photos."""

def group_photos_by_time(photos: list) -> list[list]
    """Group photos within PHOTO_GROUPING_MINUTES (default: 5)."""

def download_photo(photo: dict, size: str = 'full') -> bytes
    """Download image bytes from Drive."""

def mark_photo_processed(photo_id: str) -> None
    """Add photo ID to processed set."""
```

**Token Storage:** `/config/.storage/payme/google_tokens.json`
```json
{
  "access_token": "ya29.xxx",
  "refresh_token": "1//xxx",
  "expires_at": "2024-01-15T12:00:00",
  "client_id": "xxx.apps.googleusercontent.com",
  "client_secret": "xxx"
}
```

---

#### `gemini.py` - OCR and Bill Parsing
**Location:** `/config/scripts/payme/gemini.py`
**Purpose:** Extract payment data from bill images using Gemini 2.0 Flash.

**Key Functions:**
```python
def parse_bill_image(image_path: Path, api_key: str = None) -> ParsedBill
    """Parse single image."""

def parse_bill_images(image_paths: list[Path], api_key: str = None) -> ParsedBill
    """Parse multiple images (multi-page bill)."""

def parse_bill_bytes(image_data: bytes, mime_type: str, api_key: str = None) -> ParsedBill
    """Parse from raw bytes."""
```

**ParsedBill Dataclass:**
```python
@dataclass
class ParsedBill:
    recipient: str
    iban: str              # Normalized, no spaces
    bic: str
    amount: float
    currency: str          # Default: 'EUR'
    description: str
    original_text: str     # Original language text
    english_translation: str
    reference: str
    due_date: str          # YYYY-MM-DD
    invoice_number: str
    confidence: dict       # Per-field confidence scores
    overall_confidence: float  # Average of key fields
    raw_response: str      # Raw Gemini output
```

**API Details:**
- Model: `gemini-2.0-flash`
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent`
- Temperature: 0.1 (deterministic)
- Max tokens: 1024

---

#### `girocode.py` - QR Code Extraction
**Location:** `/config/scripts/payme/girocode.py`
**Purpose:** Extract payment data from EPC QR codes (GiroCode standard).

**Key Functions:**
```python
def check_dependencies() -> bool
    """Check if pyzbar/opencv are available."""

def extract_girocode(image_path: Path) -> GiroCodeData | None
    """Extract from file path."""

def extract_girocode_from_bytes(image_data: bytes) -> GiroCodeData | None
    """Extract from raw bytes."""
```

**GiroCodeData:**
```python
@dataclass
class GiroCodeData:
    service_tag: str       # "BCD"
    version: str           # "001" or "002"
    encoding: str          # Character encoding
    transfer_type: str     # "SCT" (SEPA Credit Transfer)
    bic: str
    recipient: str
    iban: str
    amount: float
    currency: str
    purpose: str           # Purpose code
    reference: str         # Structured reference
    text: str              # Unstructured text
```

**EPC QR Code Format:**
```
BCD                     # Service tag
002                     # Version
1                       # Encoding (UTF-8)
SCT                     # Transfer type
COBADEFFXXX             # BIC
Recipient Name          # Beneficiary
DE89370400440532013000  # IBAN
EUR123.45               # Amount
                        # Purpose (optional)
Reference               # Reference
Payment description     # Text
```

**Dependencies:**
- `pyzbar` - QR code decoding
- `opencv-python-headless` - Image processing
- System: `libzbar0` or `zbar`

---

#### `wise.py` - Wise Payment API
**Location:** `/config/scripts/payme/wise.py`
**Purpose:** Create and manage Wise transfers.

**Key Functions:**
```python
def get_eur_balance(profile_id: str = None) -> float
    """Get available EUR balance."""

def check_sufficient_balance(amount: float, currency: str = 'EUR') -> bool
    """Check if balance covers amount."""

def execute_payment(iban, name, amount, reference, currency='EUR') -> dict
    """Full payment flow. Returns {success, transfer_id, status, error}."""

def get_transfer(transfer_id: int) -> Transfer
    """Get transfer details by ID."""

def list_transfers_needing_2fa(profile_id: str = None) -> list[Transfer]
    """Get transfers awaiting authorization."""
```

**Payment Flow:**
```
1. check_sufficient_balance()
2. create_quote() → quote_id
3. get_or_create_recipient() → recipient_id
4. create_transfer() → transfer_id
5. Return with status='awaiting_funding'
```

**Note:** Personal Wise accounts cannot fund transfers via API (PSD2 restriction). Transfers are created as drafts - user must fund in Wise app/website.

**Transfer Dataclass:**
```python
@dataclass
class Transfer:
    id: int
    reference: str
    status: str            # See Wise statuses below
    source_currency: str
    source_amount: float
    target_currency: str
    target_amount: float
    recipient_name: str
    created: str
    rate: float

    @property
    def is_complete(self) -> bool
    @property
    def is_pending(self) -> bool
    @property
    def needs_2fa(self) -> bool
    @property
    def is_failed(self) -> bool
```

**Wise Transfer Statuses:**

Status mapping is centralized in `config.py` as `WISE_STATUS_MAP`:

| Wise Status | payme Status |
|-------------|--------------|
| `incoming_payment_waiting` | `awaiting_funding` |
| `processing` | `processing` |
| `waiting_for_authorization` | `awaiting_2fa` |
| `outgoing_payment_sent` | `paid` |
| `funds_converted` | `paid` |
| `cancelled` | `failed` |
| `funds_refunded` | `failed` |
| `bounced_back` | `failed` |

**Rate Limiting:** 2-second delay between API calls (configurable via `WISE_API_DELAY_SECONDS`).

---

#### `iban.py` - IBAN Validation and Bank Lookup
**Location:** `/config/scripts/payme/iban.py`
**Purpose:** Validate IBANs and lookup bank information.

**Key Functions:**
```python
def validate_iban(iban: str) -> bool
    """Validate IBAN checksum (ISO 7064 Mod 97-10)."""

def get_iban_info(iban: str) -> dict
    """Full validation + bank lookup."""
    # Returns: {valid, error, country, bank: {name, bic}}

def lookup_bic(iban: str) -> dict | None
    """Lookup bank by IBAN. Uses Bundesbank DB then OpenIBAN."""
```

**Validation Algorithm:**
1. Remove spaces, convert to uppercase
2. Check length (country-specific, DE=22)
3. Move first 4 chars to end
4. Convert letters to numbers (A=10, B=11, ...)
5. Calculate mod 97, must equal 1

**Bank Lookup Sources:**
1. **Bundesbank BLZ Database** - German banks (primary)
   - File: `/config/.storage/payme/bic_db.json`
   - Updated via `update_bic_db.py`
2. **OpenIBAN API** - Fallback for other countries
   - Endpoint: `https://openiban.com/validate/{iban}`

---

#### `dedup.py` - Duplicate Detection
**Location:** `/config/scripts/payme/dedup.py`
**Purpose:** Prevent duplicate payments.

**Key Functions:**
```python
def is_duplicate(iban: str, amount: float, reference: str) -> tuple[bool, dict]
    """Check if payment was made in last 90 days."""
    # Returns: (is_duplicate, {paid_at, bill_id} or None)

def check_similar(iban: str, amount: float) -> bool
    """Check for similar payments (same IBAN + amount, different reference)."""

def record_payment(iban: str, amount: float, reference: str) -> None
    """Record payment hash for future dedup checks."""
```

**Hash Algorithm:**
```python
hash = SHA256(iban + str(amount) + reference)[:16]
```

**Storage:** `/config/.storage/payme/payment_hashes.json`
```json
{
  "hashes": {
    "abc123def456": {
      "paid_at": "2024-01-15T10:00:00",
      "bill_id": "12345678"
    }
  }
}
```

**Window:** 90 days (configurable via `DUPLICATE_WINDOW_DAYS`).

---

#### `notify.py` - Home Assistant Notifications
**Location:** `/config/scripts/payme/notify.py`
**Purpose:** Send mobile and persistent notifications.

**Key Functions:**
```python
def send_notification(title, message, data=None, service=None) -> bool
    """Send mobile notification."""

def send_persistent_notification(title, message, notification_id=None) -> bool
    """Create dashboard notification."""

def notify_pending_bill(bill_id, recipient, bank_name, iban, amount, ...) -> bool
    """Actionable notification with Approve/Reject buttons."""

def notify_awaiting_funding(transfer_id, recipient, amount, ...) -> bool
    """Notify user to fund transfer in Wise app."""

def notify_2fa_required(transfer_id, recipient, amount, ...) -> bool
    """Notify user to approve in Wise app."""
```

**Notification Actions:**
| Action Pattern | Trigger |
|----------------|---------|
| `PAYME_APPROVE_{bill_id}` | Approve button |
| `PAYME_REJECT_{bill_id}` | Reject button |
| `PAYME_VIEW_{bill_id}` | View button |

**HA API Detection:**
- Inside HA: Uses `SUPERVISOR_TOKEN` + `http://supervisor/core/api`
- External: Uses `PAYME_HA_TOKEN` + `PAYME_HA_API_URL`

---

### Support Modules

#### `config.py` - Configuration
**Constants:**
| Constant | Default | Description |
|----------|---------|-------------|
| `POLLING_INTERVAL_MINUTES` | 30 | Poll frequency |
| `BACKUP_RETENTION_DAYS` | 7 | Backup file retention |
| `DUPLICATE_WINDOW_DAYS` | 90 | Dedup lookback |
| `PHOTO_GROUPING_MINUTES` | 5 | Multi-page grouping window |
| `WISE_API_DELAY_SECONDS` | 2 | Rate limit delay |
| `HTTP_TIMEOUT_SECONDS` | 30 | HTTP request timeout |
| `HTTP_RETRY_ATTEMPTS` | 3 | Retry count |
| `CONFIDENCE_THRESHOLD` | 0.9 | Minimum OCR confidence |

**Wise Status Mapping (centralized):**
| Constant | Description |
|----------|-------------|
| `WISE_STATUS_MAP` | Dict mapping Wise statuses to payme statuses |
| `WISE_COMPLETE_STATUSES` | Set of statuses indicating payment complete |
| `WISE_PENDING_STATUSES` | Set of statuses indicating payment in progress |
| `WISE_FAILED_STATUSES` | Set of statuses indicating payment failed |

**Environment Variables:**
| Variable | Required | Description |
|----------|----------|-------------|
| `PAYME_GEMINI_API_KEY` | Yes | Gemini API key |
| `PAYME_WISE_API_TOKEN` | Yes | Wise API token |
| `PAYME_WISE_PROFILE_ID` | Yes | Wise profile ID |
| `PAYME_ALBUM_NAME` | No | Drive folder name (default: "bill-pay") |
| `PAYME_ALBUM_ID` | No | Pre-configured folder ID |
| `PAYME_HA_TOKEN` | No* | HA long-lived token (*required outside HA) |
| `PAYME_HA_API_URL` | No | HA API URL |
| `PAYME_NOTIFY_SERVICE` | No | Notify service (default: "mobile_app_phone") |

---

#### `storage.py` - JSON File Operations
```python
def load_json(path: Path, default: any = None) -> dict
def save_json(path: Path, data: dict) -> None
def backup_file(path: Path) -> Path
def append_to_list(path: Path, key: str, item: any) -> None
```

---

#### `http_client.py` - HTTP with Retry
```python
def get_json(url, headers=None, params=None, timeout=30) -> dict
def post_json(url, headers=None, json=None, timeout=30) -> dict
class HttpError(Exception): pass
```

---

#### `formatting.py` - Display Formatting
```python
def format_currency(amount: float, currency: str = 'EUR') -> str
    # "€123.45" or "123.45 EUR"

def format_iban(iban: str) -> str
    # "DE89 3704 0044 0532 0130 00"

def format_date(date_str: str) -> str
    # "Jan 15, 2024"
```

---

## pyscript Integration

### `payme_triggers.py`
**Location:** `/config/pyscript/payme_triggers.py`

**Time Triggers:**
| Schedule | Function | Description |
|----------|----------|-------------|
| `*/30 * * * *` | `payme_scheduled_poll` | Poll for new bills |
| `0 6 * * *` | `payme_daily_maintenance` | Auth check, cleanup |
| `*/10 * * * *` | `payme_scheduled_transfer_check` | Update transfer statuses |
| `startup` | `payme_startup` | Initialize entities |

**Services:**
| Service | Parameters | Description |
|---------|------------|-------------|
| `pyscript.payme_poll` | - | Manual poll trigger |
| `pyscript.payme_approve` | `bill_id` | Approve bill |
| `pyscript.payme_reject` | `bill_id` | Reject bill |
| `pyscript.payme_override_duplicate` | `bill_id` | Clear duplicate warning |
| `pyscript.payme_set_status` | `bill_id`, `status` | Set bill status |
| `pyscript.payme_set_transfer_id` | `bill_id`, `transfer_id` | Link to Wise transfer |
| `pyscript.payme_check_transfers` | - | Update from Wise |
| `pyscript.payme_refresh` | - | Refresh entities |
| `pyscript.payme_get_status` | - | Log current status |

**Event Handlers:**
| Event | Handler |
|-------|---------|
| `mobile_app_notification_action` | `handle_notification_action` |
| `ios.notification_action_fired` | `handle_ios_notification_action` |

**Subprocess Execution:**
```python
def run_script(command: str, *args) -> dict:
    """Run poll.py with environment from secrets.yaml."""
    cmd = ['python3', f'{SCRIPTS_PATH}/poll.py', command] + list(args)
    result = subprocess.run(cmd, capture_output=True, timeout=120, env=get_script_env())
    return {'success': result.returncode == 0, 'data': json.loads(result.stdout), ...}
```

---

### `entities.py`
**Location:** `/config/pyscript/modules/payme/entities.py`

**Sensors:**
| Entity | Type | Description |
|--------|------|-------------|
| `sensor.payme_pending_bills` | sensor | Count + JSON of pending bills |
| `sensor.payme_pending_funding` | sensor | Bills needing funding |
| `sensor.payme_awaiting_wise_2fa` | sensor | Transfers needing 2FA |
| `sensor.payme_wise_balance` | sensor | EUR balance (monetary) |
| `sensor.payme_payment_history` | sensor | Full history |
| `sensor.payme_failed_queue` | sensor | Failed bills |
| `sensor.payme_statistics` | sensor | Spending stats |
| `sensor.payme_google_auth_status` | sensor | Auth status |
| `binary_sensor.payme_google_auth_healthy` | binary_sensor | Auth health |
| `sensor.payme_last_poll` | sensor | Last poll info |

**Entity Update Pattern:**
```python
state.set(
    'sensor.payme_pending_bills',
    len(pending),  # State value
    new_attributes={
        'bills': json.dumps(pending),  # JSON for dashboard
        'count': len(pending),
        'total_amount': sum([b.get('amount', 0) for b in pending]),
        'friendly_name': 'Pending Bills',
        'icon': 'mdi:file-document-multiple',
        'unit_of_measurement': 'bills',
    }
)
```

---

## Storage Files

**Location:** `/config/.storage/payme/`

| File | Purpose | Format |
|------|---------|--------|
| `google_tokens.json` | OAuth credentials | `{access_token, refresh_token, expires_at, client_id, client_secret}` |
| `album_cache.json` | Cached folder ID | `{album_id, album_title, cached_at}` |
| `processed_photos.json` | Processed photo IDs | `{processed: [id1, id2, ...]}` |
| `payment_history.json` | Bills (pending + history) | `{pending: [...], history: [...]}` |
| `payment_hashes.json` | Dedup hashes | `{hashes: {hash: {paid_at, bill_id}}}` |
| `bic_db.json` | Bundesbank BIC database | `{blz: {bic, name}}` |
| `bic_cache.json` | BIC lookup cache | `{iban: {bic, name}}` |

---

## Dashboard Card

**Location:** `/config/www/payme/payme-card.js`

**Features:**
- Balance bar (green/orange/red based on coverage)
- Tabs: Pending | Processing | Complete | All
- Bill table with Due, Vendor, Amount, Status, Paid columns
- Detail view with full payment info
- Action buttons (Approve/Reject/Override)
- English translation display for German bills

**Lovelace Configuration:**
```yaml
resources:
  - url: /local/payme/payme-card.js
    type: module

cards:
  - type: custom:payme-card
```

---

## Security Model

1. **Credentials Storage:**
   - API keys in `secrets.yaml` (HA managed)
   - OAuth tokens in `.storage/payme/` (local, auto-refresh)
   - Never logged or displayed

2. **API Scopes:**
   - Google Drive: `drive.readonly` (read-only)
   - Wise: Read/write (required for transfers)

3. **Payment Authorization:**
   - All payments require explicit user approval
   - Wise 2FA required for execution (app approval)
   - Duplicate detection prevents accidental repeats

4. **Data Privacy:**
   - IBAN masked in notifications (shows `DE89...3000`)
   - All data stored locally on HA instance
   - No external servers except APIs

---

## Error Handling

**Poll Errors:**
1. Auth expired → `notify_google_auth_expiring()` + skip poll
2. No photos → Normal, no notification
3. Parse error → `notify_parse_error()` + mark photos processed
4. API error → Log error + continue to next photo

**Payment Errors:**
1. Insufficient balance → `notify_insufficient_balance()` + status change
2. Wise API error → Status = `failed` + error stored
3. 2FA required → `notify_2fa_required()` + status = `awaiting_2fa`

**Recovery:**
- Failed bills remain in history, can be manually retried
- `check-transfers` command updates statuses from Wise
- `set-status` allows manual status override
