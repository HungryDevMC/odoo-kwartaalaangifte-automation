# Odoo UBL Export - AWS Lambda

Export invoices from **Odoo Online** to **Peppol BIS 3.0 UBL XML** using AWS Lambda.

**Same configuration options as the Odoo module** - direction filter, document types, state filter, custom domains, email sending, and quarterly auto-send.

## 💰 Cost: ~€0.01/month

Lambda pricing is per-millisecond. Quarterly exports cost virtually nothing:
- Lambda: ~$0.0001 per execution
- S3: ~$0.023/GB (exports are ~KB)
- API Gateway: Free tier covers 1M requests

## 🚀 Quick Start

### Option 1: Test Locally First

```bash
cd lambda-export

# Copy and configure
cp env.example .env
nano .env  # Fill in your Odoo credentials

# Test export
python handler.py Q4 2025

# Test with filters
python handler.py Q4 2025 outgoing posted  # Only customer invoices
```

### Option 2: Deploy to AWS

```bash
# Install SAM CLI (if not installed)
brew install aws-sam-cli

# Build & deploy
sam build
sam deploy --guided
```

The guided deploy will ask for all configuration parameters.

## ⚙️ Configuration Options

All options from the Odoo module are supported:

### Direction Filter

| Value | Description |
|-------|-------------|
| `both` | All invoices & bills (default) |
| `outgoing` | Customer invoices only |
| `incoming` | Vendor bills only |

### Document Type Filter

| Value | Description |
|-------|-------------|
| `all` | Invoices & credit notes (default) |
| `invoice` | Invoices only |
| `refund` | Credit notes only |

### State Filter

| Value | Description |
|-------|-------------|
| `posted` | Only posted/validated invoices (default) |
| `posted_draft_bills` | Posted + draft vendor bills |
| `posted_draft_invoices` | Posted + draft customer invoices |
| `posted_draft` | Posted + all drafts |
| `all` | All states |

### Custom Domain Filter

Odoo domain format in JSON:

```json
[["partner_id.country_id.code", "=", "BE"]]
[["amount_total", ">", 1000]]
[["partner_id.name", "ilike", "ACME"]]
```

### Email Settings

Emails are sent through **Odoo's mail system** (not AWS SES), so no separate email setup needed!

| Variable | Description |
|----------|-------------|
| `UBL_EMAIL` | BilltoBox import address (receives XML files) |
| `PDF_EMAIL` | Accountant email (receives statement PDFs) |

### Quarterly Auto-Send

| Variable | Description |
|----------|-------------|
| `SEND_DAY` | Day of month to send (1-28, default: 5) |
| `BANK_JOURNAL_IDS` | Comma-separated journal IDs for statements |

## 📖 API Usage

### Export by Quarter

```bash
curl -X POST https://your-api.execute-api.eu-west-1.amazonaws.com/export \
  -H "Content-Type: application/json" \
  -d '{
    "quarter": "Q4",
    "year": 2025
  }'
```

### Export by Date Range

```bash
curl -X POST https://your-api.execute-api.eu-west-1.amazonaws.com/export \
  -d '{
    "date_from": "2025-10-01",
    "date_to": "2025-12-31"
  }'
```

### Export with Filter Overrides

```bash
curl -X POST https://your-api.execute-api.eu-west-1.amazonaws.com/export \
  -d '{
    "quarter": "Q4",
    "year": 2025,
    "direction": "outgoing",
    "document_type": "invoice",
    "state_filter": "posted_draft_invoices"
  }'
```

### Export and Send Email

```bash
curl -X POST https://your-api.execute-api.eu-west-1.amazonaws.com/export \
  -d '{
    "quarter": "Q4",
    "year": 2025,
    "send_email": true
  }'
```

### List Available Exports

```bash
curl https://your-api.execute-api.eu-west-1.amazonaws.com/exports
```

### Download Export

```bash
curl -L https://your-api.execute-api.eu-west-1.amazonaws.com/download/UBL_Export_2025_Q4.zip \
  -o export.zip
```

## 🔑 Getting Your Odoo API Key

1. Log into Odoo Online
2. Go to **Settings → Users & Companies → Users**
3. Click your user → **Account Security** tab
4. Click **New API Key**
5. Copy immediately (shown only once!)

## 🗓 Quarterly Auto-Send

The Lambda automatically runs on the configured `SEND_DAY` in January, April, July, and October.

It exports the **previous quarter**:
- January 5th → Q4 of previous year
- April 5th → Q1
- July 5th → Q2
- October 5th → Q3

## 📁 Output Format

```
UBL_Export_2025_Q4.zip
└── UBL/
    ├── INV-2025-0001.xml
    ├── INV-2025-0002.xml
    ├── RINV-2025-0001.xml
    └── ...
```

Each XML is **Peppol BIS Billing 3.0** compliant for:
- BilltoBox
- ClearFacts
- Exact Online
- Yuki
- Octopus
- Any Peppol-compatible software

## 🇧🇪 Belgian E-Invoicing 2026

From January 1, 2026, e-invoicing is mandatory for B2B in Belgium. This generates the required Peppol UBL format.

## 🛠 Project Structure

```
lambda-export/
├── handler.py          # Main Lambda handler
├── config.py           # Configuration management
├── odoo_client.py      # Odoo XML-RPC client
├── ubl_generator.py    # Peppol BIS 3.0 UBL generator
├── email_sender.py     # AWS SES email sender
├── download_handler.py # S3 download endpoint
├── list_handler.py     # List exports endpoint
├── template.yaml       # AWS SAM template
├── env.example         # Example configuration
└── README.md
```

## 🎉 No External Dependencies!

Uses only Python standard library + boto3 (included in Lambda):
- `xmlrpc.client` - Odoo API
- `xml.etree.ElementTree` - UBL generation
- `zipfile`, `io`, `base64` - ZIP handling
- `boto3` - AWS services (S3, SES)

## 📄 License

LGPL-3.0 - Same as the Odoo module.
