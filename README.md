# payme

Automated bill payment for Home Assistant. Photograph a bill, add it to a Google Drive folder, and receive a mobile notification to approve payment via Wise.

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  1. Photo   │────►│  2. Folder  │────►│  3. Parse   │────►│  4. Notify  │
│  Take bill  │     │  Add to     │     │  OCR or QR  │     │  Approve?   │
│  photo      │     │  "bill-pay" │     │  extract    │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                   │
                    ┌─────────────┐     ┌─────────────┐            │
                    │  6. Done    │◄────│  5. Pay     │◄───────────┘
                    │  History    │     │  Wise draft │
                    │  updated    │     │  + fund     │
                    └─────────────┘     └─────────────┘
```

1. Take a photo of your bill with your phone
2. Add the photo to the "bill-pay" folder in Google Drive
3. Home Assistant polls the folder every 30 minutes
4. Bills are parsed via GiroCode QR or Gemini OCR
5. You receive a notification with payment details and Approve/Reject buttons
6. On approval, a Wise transfer is created (fund in Wise app)

## Features

- **GiroCode QR Detection**: Instant, 100% accurate parsing from EPC QR codes
- **Gemini OCR Fallback**: AI-powered parsing with confidence scores
- **English Translation**: German bills translated for verification
- **Duplicate Detection**: Blocks repeat payments within 90 days
- **IBAN Validation**: Full checksum verification (ISO 7064)
- **Bank Name Lookup**: Deutsche Bundesbank database integration
- **Multi-page Bills**: Photos taken within 5 minutes auto-grouped
- **Balance Awareness**: Dashboard shows if you can pay pending bills
- **Mobile Notifications**: Actionable approve/reject from your phone

## Dashboard

Clean, table-based interface with status-aware balance bar:

```
┌────────────────────────────────────────────────────────────────┐
│  Bills                                                    [↻]  │
├────────────────────────────────────────────────────────────────┤
│                         €1,234.56                              │  ← Green/Orange/Red
├────────────────────────────────────────────────────────────────┤
│  [Pending]  [Processing]  [Complete]  [All]                    │
├────────────────────────────────────────────────────────────────┤
│  Due      │ Vendor        │ Amount    │ Status  │ Paid         │
│  Jan 22   │ Netflix       │ €15.99    │ Pending │ -            │
│  Jan 18   │ Stadtwerke    │ €89.50    │         │ Jan 15       │
│  Jan 10   │ Telekom       │ €45.00    │         │ Jan 8        │
└────────────────────────────────────────────────────────────────┘
```

Click any row for full details, translations, and action buttons.

## Requirements

- **Home Assistant** with pyscript (via HACS)
- **Google Cloud Project** with Drive API enabled
- **Gemini API Key** from Google AI Studio
- **Wise Account** with API token and EUR balance

## Quick Start

```bash
# Copy payme to your Home Assistant, then:
cd /config/payme
./install.sh
```

The install script handles directories, file copying, dependencies, and configuration. You'll still need to:

1. Add your API keys to `secrets.yaml`
2. Run Google OAuth setup (one-time)
3. Create "bill-pay" folder in Google Drive
4. Add the Lovelace card to your dashboard

**See [INSTALL.md](INSTALL.md) for complete installation guide.**

**See [ARCHITECTURE.md](ARCHITECTURE.md) for technical reference.**

## File Structure

```
/config/
├── scripts/payme/           # Python modules
│   ├── poll.py              # Main orchestrator
│   ├── gemini.py            # OCR integration
│   ├── girocode.py          # QR code parsing
│   ├── wise.py              # Payment API
│   ├── google_drive.py      # Drive API client
│   ├── iban.py              # IBAN validation
│   ├── dedup.py             # Duplicate detection
│   ├── notify.py            # HA notifications
│   └── ...
├── pyscript/
│   ├── modules/payme/       # HA entity management
│   └── payme_triggers.py    # Triggers and services
├── www/payme/
│   └── payme-card.js        # Dashboard card
└── .storage/payme/          # Tokens, cache, history
```

## Services

```yaml
# Poll for new bills now
service: pyscript.payme_poll

# Approve a bill
service: pyscript.payme_approve
data:
  bill_id: "abc123"

# Reject a bill
service: pyscript.payme_reject
data:
  bill_id: "abc123"

# Manually set bill status
service: pyscript.payme_set_status
data:
  bill_id: "abc123"
  status: "paid"
```

## Entities

| Entity | Description |
|--------|-------------|
| `sensor.payme_pending_bills` | Bills awaiting approval |
| `sensor.payme_wise_balance` | EUR balance |
| `sensor.payme_awaiting_wise_2fa` | Transfers needing 2FA |
| `sensor.payme_payment_history` | Payment history |
| `sensor.payme_statistics` | Monthly spending |

## Security

- All credentials stored in Home Assistant secrets
- OAuth tokens auto-refresh, stored locally
- No external servers - everything runs on your HA instance
- Wise API requires your explicit approval for each payment

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No photos found | Check folder name, verify OAuth tokens |
| Low confidence | Re-photograph with better lighting |
| Duplicate warning | Override if intentional (recurring bill) |
| Insufficient balance | Top up Wise, bill auto-retries |
| Awaiting 2FA | Complete in Wise mobile app |

See [INSTALL.md](INSTALL.md) for detailed troubleshooting.

## License

MIT License
