# payme Installation Guide

Automated bill payment system for Home Assistant. Photograph bills, add to a Google Drive folder, and payme handles OCR, validation, and Wise payment drafts.

**See also:** [ARCHITECTURE.md](ARCHITECTURE.md) for detailed technical reference.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER WORKFLOW                                   │
│                                                                             │
│   1. Take photo of bill    2. Add to Google Drive      3. Approve via       │
│      with phone               "bill-pay" folder           notification      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HOME ASSISTANT                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         pyscript                                     │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │   │
│  │  │ payme_triggers  │  │ entities.py     │  │ __init__.py         │  │   │
│  │  │ - Time triggers │  │ - HA entities   │  │ - Module exports    │  │   │
│  │  │ - Services      │  │ - State mgmt    │  │                     │  │   │
│  │  │ - Events        │  │                 │  │                     │  │   │
│  │  └────────┬────────┘  └─────────────────┘  └─────────────────────┘  │   │
│  └───────────┼──────────────────────────────────────────────────────────┘   │
│              │ subprocess                                                    │
│              ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Python Scripts                                 │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │                         poll.py                               │   │   │
│  │  │                    Main Orchestrator                          │   │   │
│  │  │  Commands: poll, status, approve, reject, override-duplicate  │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │         ┌────────────────────┼────────────────────┐                 │   │
│  │         ▼                    ▼                    ▼                 │   │
│  │  ┌─────────────┐     ┌─────────────┐      ┌─────────────┐          │   │
│  │  │google_drive │     │  girocode   │      │   gemini    │          │   │
│  │  │   .py       │     │    .py      │      │    .py      │          │   │
│  │  │Folder fetch │     │ QR parsing  │      │ OCR parsing │          │   │
│  │  └─────────────┘     └─────────────┘      └─────────────┘          │   │
│  │         │                                        │                  │   │
│  │         ▼                                        ▼                  │   │
│  │  ┌─────────────┐     ┌─────────────┐      ┌─────────────┐          │   │
│  │  │    iban     │     │   dedup     │      │    wise     │          │   │
│  │  │    .py      │     │    .py      │      │    .py      │          │   │
│  │  │ Validation  │     │ Duplicate   │      │ Payments    │          │   │
│  │  │ BIC lookup  │     │ detection   │      │ API client  │          │   │
│  │  └─────────────┘     └─────────────┘      └─────────────┘          │   │
│  │         │                    │                   │                  │   │
│  │         ▼                    ▼                   ▼                  │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  config.py │ storage.py │ formatting.py │ http_client.py     │   │   │
│  │  │  notify.py │                                                  │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Lovelace Dashboard                               │   │
│  │  ┌───────────────────────────────────────────────────────────────┐  │   │
│  │  │                     payme-card.js                              │  │   │
│  │  │  ┌─────────────────────────────────────────────────────────┐  │  │   │
│  │  │  │  Balance Bar (green/orange/red based on pending bills)  │  │  │   │
│  │  │  ├─────────────────────────────────────────────────────────┤  │  │   │
│  │  │  │  Tabs: Pending | Processing | Complete | All            │  │  │   │
│  │  │  ├─────────────────────────────────────────────────────────┤  │  │   │
│  │  │  │  Due    │ Vendor      │ Amount  │ Status  │ Paid        │  │  │   │
│  │  │  │  Jan 22 │ Netflix     │ 15.99 € │ Pending │ -           │  │  │   │
│  │  │  │  Jan 25 │ Stadtwerke  │ 89.50 € │         │ Jan 20      │  │  │   │
│  │  │  └─────────────────────────────────────────────────────────┘  │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
            │Google Drive │   │   Gemini    │   │    Wise     │
            │    API      │   │    API      │   │    API      │
            │             │   │   (OCR)     │   │ (Payments)  │
            └─────────────┘   └─────────────┘   └─────────────┘
```

## Data Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           POLL WORKFLOW                                   │
└──────────────────────────────────────────────────────────────────────────┘

1. FETCH PHOTOS
   Google Drive API → Get images from "bill-pay" folder
                    → Filter out already-processed photos
                    → Group photos taken within 5 minutes (multi-page bills)

2. PARSE BILLS (for each photo group)
   ┌─────────────────┐     ┌─────────────────┐
   │  Try GiroCode   │────►│  Found QR?      │
   │  (EPC QR scan)  │     │                 │
   └─────────────────┘     └────────┬────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
               Yes: Use QR data              No: Use Gemini OCR
               (100% confidence)             (variable confidence)
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  Extracted: recipient, IBAN, BIC, amount, reference, due_date  │
   │             description, original_text, english_translation     │
   └─────────────────────────────────────────────────────────────────┘

3. VALIDATE & ENRICH
   IBAN Validation → Check format and checksum (ISO 7064 Mod 97-10)
   BIC Lookup      → Deutsche Bundesbank database → OpenIBAN fallback
   Duplicate Check → SHA256(IBAN + amount + reference) against 90-day history

4. CREATE BILL
   ┌─────────────────────────────────────────────────────────────────┐
   │  Bill record with:                                              │
   │  - Unique ID, payment details, confidence score                 │
   │  - Status: pending (or insufficient_balance if low funds)       │
   │  - Flags: duplicate_warning, low_confidence                     │
   └─────────────────────────────────────────────────────────────────┘

5. NOTIFY
   Home Assistant → Mobile notification with:
                   - Bill summary (recipient, amount, due date)
                   - Action buttons: Approve / Reject / View


┌──────────────────────────────────────────────────────────────────────────┐
│                          APPROVE WORKFLOW                                 │
└──────────────────────────────────────────────────────────────────────────┘

1. User taps "Approve" (notification or dashboard)

2. CREATE WISE TRANSFER
   ┌─────────────────────────────────────────────────────────────────┐
   │  a) Check balance (must cover amount)                          │
   │  b) Create/find recipient (IBAN + BIC + name)                  │
   │  c) Create quote (amount + currency)                           │
   │  d) Create transfer draft (quote + recipient + reference)      │
   └─────────────────────────────────────────────────────────────────┘

3. STATUS UPDATE
   Bill status → awaiting_2fa (Wise requires mobile app confirmation)

4. COMPLETION
   After Wise 2FA → Status changes to "paid"
                 → Payment added to history
```

## File Structure

```
/config/
├── scripts/
│   └── payme/
│       ├── config.py              # Configuration and paths
│       ├── storage.py             # JSON file operations
│       ├── formatting.py          # Currency/date formatting
│       ├── http_client.py         # HTTP with retry logic
│       ├── iban.py                # IBAN validation and BIC lookup
│       ├── dedup.py               # Duplicate detection
│       ├── girocode.py            # EPC QR code parsing
│       ├── gemini.py              # Gemini OCR integration
│       ├── google_drive.py        # Google Drive API client
│       ├── wise.py                # Wise API client
│       ├── notify.py              # HA notifications
│       ├── poll.py                # Main orchestrator (CLI entry point)
│       ├── authorize_google.py    # One-time OAuth setup
│       └── update_bic_db.py       # BIC database updater
│
├── pyscript/
│   ├── modules/
│   │   └── payme/
│   │       ├── __init__.py        # Module exports
│   │       └── entities.py        # HA entity management
│   └── payme_triggers.py          # Triggers, services, events
│
├── www/
│   └── payme/
│       └── payme-card.js          # Lovelace dashboard card
│
└── .storage/
    └── payme/
        ├── google_tokens.json     # OAuth tokens (auto-refreshed)
        ├── album_cache.json       # Album ID cache
        ├── processed_photos.json  # Processed photo IDs
        ├── payment_hashes.json    # Duplicate detection hashes
        ├── payment_history.json   # Payment history
        ├── bic_db.json            # Bundesbank BIC database
        └── bic_cache.json         # BIC lookup cache
```

## Prerequisites

### Home Assistant Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Home Assistant | 2021.9.0 | 2024.1.0+ |
| Python | 3.9 | 3.11+ |
| pyscript | 1.4.0 | Latest |

**Tested Platforms:**
- Home Assistant Green (fully supported)
- Home Assistant Yellow
- Home Assistant OS (any hardware)
- Home Assistant Supervised
- Home Assistant Container

### Required Services

1. **Home Assistant** with:
   - [pyscript](https://hacs.xyz/default_addons/pyscript/) integration installed via HACS
   - Mobile app configured for notifications

2. **Google Cloud Project** with:
   - Google Drive API enabled
   - OAuth 2.0 credentials (Desktop application type)

3. **Gemini API Key** from:
   - [Google AI Studio](https://makersuite.google.com/app/apikey)

4. **Wise Account** with:
   - API token from [Wise Settings](https://wise.com/settings/api-tokens)
   - Profile ID (visible in Wise dashboard URL)
   - EUR balance for SEPA payments

### System Dependencies (for QR Code Detection)

GiroCode QR detection requires `pyzbar` and `opencv`. These are **optional** - without them, payme uses Gemini OCR for all bills (which works well, just slightly less accurate than QR codes).

#### Home Assistant OS (Green, Yellow, generic)

Use the "Advanced SSH & Web Terminal" add-on:

```bash
# Install system library
apk add zbar

# Install Python packages
pip install pyzbar opencv-python-headless
```

Note: On Home Assistant OS, installed packages may not persist across updates. If QR detection stops working after an update, re-run the above commands.

#### Home Assistant Supervised / Container

```bash
# Debian/Ubuntu
apt-get install libzbar0
pip install pyzbar opencv-python-headless

# Alpine
apk add zbar
pip install pyzbar opencv-python-headless
```

#### Home Assistant Core (venv)

```bash
# Install system library first
sudo apt-get install libzbar0  # Debian/Ubuntu
# or
brew install zbar  # macOS

# Then Python packages in your venv
pip install pyzbar opencv-python-headless
```

## Installation

### Quick Install (Recommended)

Copy the payme folder to your Home Assistant and run the install script:

```bash
# SSH into Home Assistant or use Terminal add-on
cd /config/payme  # wherever you copied the files
chmod +x install.sh
./install.sh
```

The script will:
1. Create all required directories
2. Copy Python scripts, pyscript modules, and dashboard card
3. Check dependencies (Python, pyzbar, opencv)
4. Initialize the BIC database
5. Add pyscript configuration to configuration.yaml
6. Create a secrets template
7. Print remaining manual steps

### Manual Installation

If you prefer manual installation, follow these steps:

#### Step 1: Create Directory Structure

```bash
mkdir -p /config/scripts/payme
mkdir -p /config/pyscript/modules/payme
mkdir -p /config/www/payme
mkdir -p /config/.storage/payme
```

#### Step 2: Copy Python Scripts

Copy all `.py` files to `/config/scripts/payme/`:

```
config.py
storage.py
formatting.py
http_client.py
iban.py
dedup.py
girocode.py
gemini.py
google_drive.py
wise.py
notify.py
poll.py
authorize_google.py
update_bic_db.py
```

#### Step 3: Copy Pyscript Files

```bash
# Module files
cp pyscript/modules/payme/__init__.py /config/pyscript/modules/payme/
cp pyscript/modules/payme/entities.py /config/pyscript/modules/payme/

# Trigger file
cp pyscript/payme_triggers.py /config/pyscript/
```

#### Step 4: Copy Dashboard Card

```bash
cp www/payme/payme-card.js /config/www/payme/
```

### Step 5: Configure Pyscript

Add to `/config/configuration.yaml`:

```yaml
pyscript:
  allow_all_imports: true
  hass_is_global: true
  apps:
    payme:
      gemini_api_key: !secret payme_gemini_api_key
      wise_api_token: !secret payme_wise_api_token
      wise_profile_id: !secret payme_wise_profile_id
      album_name: "bill-pay"
      notify_service: "mobile_app_your_phone"
```

Add to `/config/secrets.yaml`:

```yaml
payme_gemini_api_key: "your-gemini-api-key"
payme_wise_api_token: "your-wise-api-token"
payme_wise_profile_id: "your-profile-id"
```

### Step 6: Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable "Google Drive API"
4. Create OAuth 2.0 credentials:
   - Application type: Desktop application
   - Download the JSON file

5. Run the authorization script:

```bash
cd /config/scripts/payme

# Set your credentials
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your-client-secret"

# Run authorization
python3 authorize_google.py
```

6. Follow the prompts to authorize in your browser
7. Tokens are saved to `/config/.storage/payme/google_tokens.json`

### Step 7: Initialize BIC Database

```bash
cd /config/scripts/payme
python3 update_bic_db.py
```

This downloads the Deutsche Bundesbank BLZ database for German bank lookups.

### Step 8: Create Google Drive Folder

1. Open Google Drive on your phone or computer
2. Create a new folder named exactly: `bill-pay`
3. This is where you'll add bill photos

### Step 9: Add Dashboard Card

Add to your Lovelace dashboard:

```yaml
resources:
  - url: /local/payme/payme-card.js
    type: module

views:
  - title: Bills
    cards:
      - type: custom:payme-card
```

Or via UI:
1. Edit Dashboard → Add Card → Manual
2. Enter:
```yaml
type: custom:payme-card
```

### Step 10: Restart Home Assistant

```bash
ha core restart
```

## Configuration Reference

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PAYME_GEMINI_API_KEY` | Yes | Gemini API key for OCR |
| `PAYME_WISE_API_TOKEN` | Yes | Wise API token |
| `PAYME_WISE_PROFILE_ID` | Yes | Wise profile ID |
| `PAYME_ALBUM_NAME` | No | Google Drive folder (default: "bill-pay") |
| `PAYME_ALBUM_ID` | No | Folder ID (auto-detected if not set) |
| `PAYME_NOTIFY_SERVICE` | No | HA notify service (default: "mobile_app_phone") |

### Constants (in config.py)

| Constant | Default | Description |
|----------|---------|-------------|
| `POLLING_INTERVAL_MINUTES` | 30 | How often to check for new photos |
| `DUPLICATE_WINDOW_DAYS` | 90 | Days to check for duplicate payments |
| `PHOTO_GROUPING_MINUTES` | 5 | Window to group multi-page bills |
| `CONFIDENCE_THRESHOLD` | 0.9 | Minimum OCR confidence (0-1) |
| `WISE_API_DELAY_SECONDS` | 2 | Rate limit delay between Wise calls |

## Usage

### Adding Bills

1. Take a photo of the bill with your phone
2. Add the photo to the "bill-pay" folder in Google Drive
3. Wait for the next poll (every 30 minutes) or trigger manually
4. Receive notification with bill details
5. Tap "Approve" to create Wise transfer draft
6. Complete 2FA in the Wise app

### Multi-Page Bills

For bills spanning multiple pages:
1. Take photos of all pages within 5 minutes
2. Add all photos to the folder
3. payme will automatically group and analyze them together

### Dashboard Features

- **Balance Bar**: Shows Wise EUR balance
  - Green: Can pay all pending bills
  - Orange: Can pay some bills
  - Red: Cannot pay any pending bills

- **Tabs**:
  - Pending: Bills awaiting approval
  - Processing: Bills being paid (awaiting 2FA)
  - Complete: Paid/rejected/failed bills
  - All: Full history

- **Bill Detail**: Tap any bill to see:
  - Full payment details (IBAN, BIC, reference)
  - English translation (for German bills)
  - Original text
  - Approve/Reject buttons (for pending bills)

### Services

Call from automations or Developer Tools:

```yaml
# Trigger manual poll
service: pyscript.payme_poll

# Approve a bill
service: pyscript.payme_approve
data:
  bill_id: "abc123"

# Reject a bill
service: pyscript.payme_reject
data:
  bill_id: "abc123"

# Override duplicate warning
service: pyscript.payme_override_duplicate
data:
  bill_id: "abc123"

# Manually set bill status
service: pyscript.payme_set_status
data:
  bill_id: "abc123"
  status: "paid"  # pending, paid, rejected, failed, processing, awaiting_2fa, insufficient_balance

# Refresh entity states
service: pyscript.payme_refresh

# Get current status
service: pyscript.payme_get_status
```

### Entities

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.payme_pending_bills` | sensor | Count of pending bills |
| `sensor.payme_pending_funding` | sensor | Bills needing more funds |
| `sensor.payme_awaiting_wise_2fa` | sensor | Transfers awaiting 2FA |
| `sensor.payme_wise_balance` | sensor | EUR balance |
| `sensor.payme_payment_history` | sensor | Payment history |
| `sensor.payme_failed_queue` | sensor | Failed bills |
| `sensor.payme_statistics` | sensor | Monthly spending stats |
| `sensor.payme_google_auth_status` | sensor | OAuth token status |
| `binary_sensor.payme_google_auth_healthy` | binary_sensor | Auth health |
| `sensor.payme_last_poll` | sensor | Last poll timestamp |

## Troubleshooting

### Check Logs

```bash
# Pyscript logs
grep "payme" /config/home-assistant.log

# Run poll manually with debug output
cd /config/scripts/payme
python3 poll.py status
python3 poll.py poll
```

### Common Issues

**"No photos found"**
- Verify folder name matches exactly (case-sensitive)
- Check Google OAuth tokens are valid
- Run `python3 poll.py status` to see auth status

**"IBAN validation failed"**
- Ensure IBAN is correctly extracted
- Check for OCR errors in the bill image
- Try a clearer photo

**"Insufficient balance"**
- Add funds to Wise EUR balance
- Bill will auto-retry when balance is sufficient

**"Duplicate warning"**
- Same IBAN + amount + reference was paid in last 90 days
- Use "Override duplicate" if this is intentional

**"Low confidence"**
- OCR confidence below 90%
- Verify extracted details before approving
- Consider re-photographing the bill

### Re-authorize Google

If tokens expire:

```bash
cd /config/scripts/payme
rm /config/.storage/payme/google_tokens.json
python3 authorize_google.py
```

### Update BIC Database

Run monthly to get latest bank codes:

```bash
cd /config/scripts/payme
python3 update_bic_db.py
```

## Security Notes

1. **Secrets**: All API keys are stored in Home Assistant secrets, never in code
2. **OAuth Tokens**: Stored locally, auto-refreshed, never exposed
3. **Wise API**: Uses read/write token - keep secure, rotate if compromised
4. **Dashboard**: Requires HA authentication, no public access
5. **Photos**: Only accessed from your own Google account

## License

MIT License - See LICENSE file for details.
