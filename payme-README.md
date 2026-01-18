# payme

Automated bill payment for Home Assistant. Photograph a bill, add it to a Google Photos album, and receive a mobile notification to approve payment via Wise.

## How It Works

1. You photograph a bill with your phone
2. You add the photo to the "bill-pay" album in Google Photos
3. Every 30 minutes, Home Assistant polls the album for new images
4. New images are downloaded and sent to Gemini for OCR parsing
5. Extracted payment details (IBAN, amount, recipient, reference) create a Wise transfer draft
6. You receive a mobile notification with payment details
7. You approve or reject
8. On approval, the Wise transfer executes

## Requirements

- Home Assistant (with HACS)
- pyscript (installed via HACS)
- Google Cloud project with Photos Library API enabled
- Gemini API key
- Wise API token (full access)
- Home Assistant Companion app on your phone (for notifications)

## File Structure

```
config/
├── pyscript/
│   ├── modules/
│   │   └── payme/
│   │       ├── __init__.py
│   │       └── entities.py
│   └── payme_triggers.py
├── scripts/
│   └── payme/
│       ├── poll.py                 # Entry point, orchestration
│       ├── google_photos.py        # Photos API client
│       ├── gemini.py               # OCR and parsing
│       ├── wise.py                 # Wise API client
│       ├── girocode.py             # QR code detection
│       ├── iban.py                 # IBAN validation and bank lookup
│       ├── dedup.py                # Duplicate detection
│       ├── storage.py              # JSON file read/write
│       ├── http_client.py          # HTTP requests with retry/timeout
│       ├── config.py               # Load secrets and constants
│       ├── formatting.py           # Currency, date formatting
│       ├── notify.py               # HA notification calls
│       ├── authorize_google.py     # One-time OAuth setup
│       └── update_bic_db.py        # Fetch latest BIC database from Bundesbank
├── www/
│   └── payme/
│       ├── payme-panel.js
│       └── payme-styles.css
├── backups/
│   └── payme/                      # Daily history backups (auto-created)
├── .storage/
│   └── payme/
│       ├── google_tokens.json      # OAuth tokens (auto-created)
│       ├── album_cache.json        # Cached album metadata
│       ├── processed_photos.json   # Tracks processed photo IDs
│       ├── payment_hashes.json     # Deduplication hashes
│       ├── payment_history.json    # Payment log
│       ├── bic_db.json             # BIC-to-bank-name mapping
│       └── bic_cache.json          # Cached lookups from openiban
├── secrets.yaml                    # API keys and credentials
└── CLAUDE.md                       # Instructions for Claude Code
```

## Installation

### 1. Install pyscript

In HACS: search for "pyscript" and install. Add to `configuration.yaml`:

```yaml
pyscript:
  allow_all_imports: true
  hass_is_global: true
```

Restart Home Assistant.

### 2. Copy payme files

Copy the `pyscript/modules/payme/` directory and `pyscript/payme_poll.py` to your Home Assistant config.

### 3. Create storage directory

```bash
mkdir -p /config/.storage/payme
```

## Configuration

### Google Photos API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable "Photos Library API"
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Application type: "Desktop app"
6. Download the JSON file

#### One-time authorization

Run the authorization script from your Home Assistant machine:

```bash
cd /config/pyscript/modules/payme
python3 authorize_google.py /path/to/downloaded/credentials.json
```

This opens a browser for Google sign-in. After authorization, tokens are saved to `/config/.storage/payme/google_tokens.json`.

The script requests read-only access to Google Photos. Tokens refresh automatically.

### Gemini API

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create an API key

### Wise API

1. Go to [Wise Settings → API tokens](https://wise.com/settings/api-tokens)
2. Create a new token with "Full access"
3. Note your Profile ID (visible in the URL when viewing your account, or via API)

### secrets.yaml

Add to your `secrets.yaml`:

```yaml
payme_gemini_api_key: "your-gemini-api-key"
payme_wise_api_token: "your-wise-api-token"
payme_wise_profile_id: "your-profile-id"
payme_google_credentials_path: "/config/.storage/payme/google_tokens.json"
payme_album_name: "bill-pay"              # Optional: album name (fuzzy matched)
payme_album_id: ""                        # Optional: album ID (exact match, overrides name)
payme_webhook_fallback: true              # Enable webhook upload when Google auth fails
```

### Bank Name Lookup (BIC Database)

payme displays the bank name for each IBAN to help you verify recipients. This uses a local database of German BIC codes.

#### Initial setup

A BIC database ships with payme. To update it or if missing:

```bash
cd /config/scripts/payme
python3 update_bic_db.py
```

This downloads the current Bankleitzahlen file from Deutsche Bundesbank and extracts BIC-to-bank-name mappings.

#### Manual download (alternative)

1. Go to [Bundesbank BLZ download](https://www.bundesbank.de/de/aufgaben/unbarer-zahlungsverkehr/serviceangebot/bankleitzahlen)
2. Download "BLZ-Datei" (text format)
3. Place in `/config/.storage/payme/blz_raw.txt`
4. Run: `python3 update_bic_db.py --from-file /config/.storage/payme/blz_raw.txt`

#### Lookup behavior

1. Extract BIC from IBAN (or use BIC if provided on bill)
2. Check `bic_db.json` (static Bundesbank data)
3. If miss, query openiban.com (3s timeout)
4. Cache successful lookups in `bic_cache.json`
5. If all fail, display "Unknown bank" with raw BIC

Bundesbank updates quarterly. Running `update_bic_db.py` annually is sufficient for most cases.

### Google Photos Album

Create an album named exactly `bill-pay` in Google Photos. The album must exist before payme can poll it.

## Credential Storage

| Credential | Location | Access |
|------------|----------|--------|
| Google OAuth tokens | `/config/.storage/payme/google_tokens.json` | Read/write by pyscript |
| Gemini API key | `secrets.yaml` | Read by pyscript |
| Wise API token | `secrets.yaml` | Read by pyscript |
| Processed photo IDs | `/config/.storage/payme/processed_photos.json` | Read/write by pyscript |

All credentials remain local to your Home Assistant instance. The `.storage` directory is excluded from backups by default—consider backing up `google_tokens.json` separately.

## Where It Runs

All code runs inside Home Assistant via pyscript:

- **Polling**: time-triggered pyscript service (every 30 minutes)
- **API calls**: outbound HTTPS to Google Photos, Gemini, and Wise
- **Notifications**: via Home Assistant's mobile_app integration

No external servers. No cloud functions. Everything stays on your HA instance.

## Dashboard

payme includes a dedicated Home Assistant view at `/payme` in your sidebar.

### Features

| Section | Description |
|---------|-------------|
| Pending Bills | Cards showing parsed bill details with Approve/Reject buttons |
| Wise Balance | Current EUR balance in your Wise account |
| Payment History | Table of past payments with status (sent, failed, rejected) |
| Failed Queue | Bills that failed parsing or payment, with retry option |
| Statistics | Monthly spend, bill count, average payment amount |
| Recent Photos | Thumbnails from bill-pay album |
| Manual Poll | Button to check for new bills immediately |

### Installation

Add to `configuration.yaml`:

```yaml
panel_custom:
  - name: payme-panel
    sidebar_title: payme
    sidebar_icon: mdi:bank-transfer
    url_path: payme
    module_url: /local/payme/payme-panel.js
```

Copy `www/payme/` to your Home Assistant `www` directory:

```
config/
└── www/
    └── payme/
        ├── payme-panel.js
        └── payme-styles.css
```

Restart Home Assistant. "payme" appears in your sidebar.

### Dashboard Entities

The dashboard reads from these entities (created automatically by pyscript):

| Entity | Type | Purpose |
|--------|------|---------|
| `sensor.payme_pending_bills` | sensor | JSON list of pending bills awaiting your approval |
| `sensor.payme_pending_funding` | sensor | JSON list of bills awaiting Wise top-up |
| `sensor.payme_awaiting_wise_2fa` | sensor | JSON list of transfers requiring Wise app confirmation |
| `sensor.payme_wise_balance` | sensor | Current EUR balance |
| `sensor.payme_payment_history` | sensor | JSON list of past payments |
| `sensor.payme_failed_queue` | sensor | JSON list of failed items |
| `sensor.payme_statistics` | sensor | Monthly stats as JSON |
| `sensor.payme_google_auth_status` | sensor | OAuth token health (ok/expiring/failed) |
| `binary_sensor.payme_google_auth_healthy` | binary_sensor | True if Google auth working |

### Approving from Dashboard

Each pending bill card shows:

- Recipient name
- Bank name (looked up from IBAN)
- IBAN (partially masked)
- Amount and currency
- Reference
- Confidence score (with warning if below 90%)
- Thumbnail of original bill

Buttons:

- **Approve** — executes the Wise transfer immediately
- **Reject** — dismisses the bill, logs as rejected
- **Edit** — modify extracted fields before approving
- **View Original** — opens full bill image
- **Override Duplicate** — appears if duplicate detected, allows payment anyway

### Mobile Access

The dashboard works in the Home Assistant Companion app. You can approve payments from your phone via the dashboard instead of (or in addition to) notifications.

## Usage

Once installed:

1. Take a photo of a bill
2. In Google Photos, add it to the "bill-pay" album
3. Wait up to 30 minutes (or trigger manually via HA Developer Tools → Services → `pyscript.payme_poll`)
4. Receive notification on your phone
5. Tap "Approve" to execute payment, or "Reject" to dismiss

## Manual Trigger

To poll immediately without waiting:

**Developer Tools → Services:**

```yaml
service: pyscript.payme_poll
```

Or create a dashboard button:

```yaml
type: button
name: Check Bills
tap_action:
  action: call-service
  service: pyscript.payme_poll
```

## Troubleshooting

### "Album not found"

Album matching is case-insensitive and trims whitespace. If still not found, get the album ID from Google Photos (share album → copy link → ID is in URL) and set `payme_album_id` in secrets.yaml.

### "Token expired"

payme checks token health daily. If you receive an alert, re-run the authorization script. As a temporary workaround, upload bills via webhook: POST image to `/api/webhook/payme_upload`.

### "Low confidence" bills

Bills below 90% parsing confidence appear in the dashboard with a warning. Review extracted fields and correct manually before approving. Common causes: unusual layout, poor photo quality, handwritten amounts.

### "Duplicate detected"

payme blocks bills matching (IBAN + amount + reference) seen in the last 90 days, or matching recent Wise transactions. If legitimate (e.g., recurring bill), use "Override duplicate" in dashboard.

### "Insufficient balance"

Bill moves to "pending funding" queue. Top up your Wise EUR balance, then approve from dashboard. payme re-checks balance before executing.

### "IBAN invalid"

Checksum validation failed. Usually indicates OCR misread. Compare displayed IBAN against original bill, correct in dashboard before approving.

### "Gemini parsing failed"

Check HA logs for raw response. If bill has no QR code and unusual layout, try re-photographing with better lighting and straight angle. Persistent failures may require prompt tuning in `gemini.py`.

### "Awaiting Wise 2FA"

Wise requires app confirmation for some transfers (new recipients, large amounts, unusual patterns). Open Wise app, approve the pending transfer. payme detects completion on next poll and updates history.

### "Wise transfer failed"

Verify API token has full access. Check Wise dashboard for account restrictions. Review HA logs for specific error code from Wise API.

### "Multi-page bill split incorrectly"

Photos must be added to album within 5 minutes to be grouped. If photographing slowly, add all photos before processing triggers, or manually link in dashboard.

## Reliability and Error Handling

payme implements multiple safeguards to prevent payment errors and handle failures gracefully.

### Bill Parsing

| Safeguard | Description |
|-----------|-------------|
| GiroCode detection | Scans for EPC QR codes first (deterministic). Falls back to OCR only if no code found. |
| Confidence scoring | Gemini returns confidence per field. Bills below 90% confidence require manual review in dashboard. |
| IBAN checksum | Validates IBAN structure using ISO 7064 Mod 97-10 before creating transfer. |
| Bank name lookup | Displays bank name for extracted IBAN so you can visually verify recipient. |

### Duplicate Prevention

| Safeguard | Description |
|-----------|-------------|
| Local hash check | SHA256 of (IBAN + amount + reference). Rejects exact duplicates seen within 90 days. |
| Wise transaction comparison | Pulls recent Wise transactions before creating transfer. Warns if similar payment exists. |

### Multi-page Bills

Photos added to the album within 5 minutes of each other are grouped as a single bill. All images are sent to Gemini together for parsing.

### Currency Handling

Currency is detected from the bill. Non-EUR bills are rejected with a clear error message suggesting manual payment. EUR-only by design.

### Payment Execution

| Safeguard | Description |
|-----------|-------------|
| Balance check | Verifies sufficient EUR balance before creating transfer. Blocks if insufficient. |
| Payment queue | If balance is insufficient, bill moves to "pending funding" queue. You receive a notification to top up Wise. |
| Rate limiting | Bills processed sequentially with 2-second delays between Wise API calls. |
| Wise 2FA handling | Some transfers require approval in Wise app (new recipients, large amounts). payme detects `waiting_for_authorization` status and notifies you to complete in Wise. Transfer tracked until confirmed. |

### Google Photos Integration

| Safeguard | Description |
|-----------|-------------|
| Metadata caching | Album contents cached locally. Only new items fetched on each poll. |
| Fuzzy album matching | Album name matched case-insensitively with whitespace trimmed. |
| Album ID fallback | Optionally configure album ID directly for exact matching. |
| Token health check | Daily validation of OAuth token. Alert if refresh fails. |
| Webhook fallback | If Google auth breaks, upload bills directly via HA webhook at `/api/webhook/payme_upload`. |

### Audit Trail

| Safeguard | Description |
|-----------|-------------|
| Wise reconciliation | Local payment history reconciled against Wise API transaction list on each poll. |
| Daily backup | Payment history backed up to `/config/backups/payme/` with daily rotation (7 days retained). |

### Execution Environment

pyscript async limitations are avoided by running HTTP calls via shell_command to an external Python script. All external calls implement timeouts (30s) and retry logic (3 attempts with exponential backoff).

## Security Notes

- Wise API tokens grant full account access. Treat them like passwords.
- Google OAuth tokens allow read-only Photos access for the authorized account only.
- All API calls use HTTPS.
- Consider restricting Home Assistant external access if running payme.
