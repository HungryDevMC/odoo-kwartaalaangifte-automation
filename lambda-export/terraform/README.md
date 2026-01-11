# Terraform Deployment

Deploy the Odoo UBL Export Lambda to AWS using Terraform.

## Prerequisites

- AWS Account with access key and secret
- Terraform >= 1.5.0 (for local deployment)
- GitHub repository (for pipeline deployment)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        AWS Account                          │
│                        eu-west-1                            │
│                                                             │
│  ┌──────────────────────┐    ┌──────────────────────┐      │
│  │       GESP           │    │       EVOLF          │      │
│  │                      │    │                      │      │
│  │  ┌────────────────┐  │    │  ┌────────────────┐  │      │
│  │  │ API Gateway    │  │    │  │ API Gateway    │  │      │
│  │  │ /export        │  │    │  │ /export        │  │      │
│  │  │ /download/{f}  │  │    │  │ /download/{f}  │  │      │
│  │  │ /exports       │  │    │  │ /exports       │  │      │
│  │  └───────┬────────┘  │    │  └───────┬────────┘  │      │
│  │          │           │    │          │           │      │
│  │  ┌───────▼────────┐  │    │  ┌───────▼────────┐  │      │
│  │  │ Lambda         │  │    │  │ Lambda         │  │      │
│  │  │ - export       │  │    │  │ - export       │  │      │
│  │  │ - download     │  │    │  │ - download     │  │      │
│  │  │ - list         │  │    │  │ - list         │  │      │
│  │  └───────┬────────┘  │    │  └───────┬────────┘  │      │
│  │          │           │    │          │           │      │
│  │  ┌───────▼────────┐  │    │  ┌───────▼────────┐  │      │
│  │  │ S3 Bucket      │  │    │  │ S3 Bucket      │  │      │
│  │  │ (exports)      │  │    │  │ (exports)      │  │      │
│  │  └────────────────┘  │    │  └────────────────┘  │      │
│  │                      │    │                      │      │
│  │  ┌────────────────┐  │    │  ┌────────────────┐  │      │
│  │  │ EventBridge    │  │    │  │ EventBridge    │  │      │
│  │  │ (quarterly)    │  │    │  │ (quarterly)    │  │      │
│  │  └────────────────┘  │    │  └────────────────┘  │      │
│  └──────────────────────┘    └──────────────────────┘      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Terraform State (S3)                    │   │
│  │  odoo-ubl-export-terraform-state/                    │   │
│  │    ├── gesp/terraform.tfstate                        │   │
│  │    └── evolf/terraform.tfstate                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Setup GitHub Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions

### Repository Secrets (shared)

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |

### Environment: `gesp`

Create environment "gesp" and add these secrets:

| Secret | Description | Example |
|--------|-------------|---------|
| `GESP_ODOO_URL` | Odoo URL | `https://gesp.odoo.com` |
| `GESP_ODOO_DATABASE` | Database name | `gesp` |
| `GESP_ODOO_USERNAME` | User email | `admin@gesp.be` |
| `GESP_ODOO_API_KEY` | API key | `abc123...` |
| `GESP_UBL_EMAIL` | BilltoBox email | `upload@billtobox.be` |
| `GESP_PDF_EMAIL` | Accountant email | `accountant@example.com` |

### Environment: `evolf`

Create environment "evolf" and add these secrets:

| Secret | Description | Example |
|--------|-------------|---------|
| `EVOLF_ODOO_URL` | Odoo URL | `https://evolf.odoo.com` |
| `EVOLF_ODOO_DATABASE` | Database name | `evolf` |
| `EVOLF_ODOO_USERNAME` | User email | `admin@evolf.be` |
| `EVOLF_ODOO_API_KEY` | API key | `xyz789...` |
| `EVOLF_UBL_EMAIL` | BilltoBox email | `upload@billtobox.be` |
| `EVOLF_PDF_EMAIL` | Accountant email | `accountant@example.com` |

> **Note:** Emails are sent through Odoo's mail system (not AWS SES), so no separate email verification is needed.

## Deploy

### Via GitHub Actions (Recommended)

1. Push to `main` branch → Auto-deploys both environments
2. Or: Actions → "Deploy to AWS" → Run workflow → Select environment

### Manual Deployment

```bash
cd lambda-export/terraform

# Initialize with backend
terraform init \
  -backend-config="bucket=odoo-ubl-export-terraform-state" \
  -backend-config="key=gesp/terraform.tfstate" \
  -backend-config="region=eu-west-1"

# Set sensitive variables
export TF_VAR_odoo_url="https://gesp.odoo.com"
export TF_VAR_odoo_database="gesp"
export TF_VAR_odoo_username="admin@gesp.be"
export TF_VAR_odoo_api_key="your-api-key"

# Plan
terraform plan -var-file="environments/gesp.tfvars"

# Apply
terraform apply -var-file="environments/gesp.tfvars"
```

## Destroy

### Via GitHub Actions

Actions → "Destroy Infrastructure" → Select environment → Type "destroy" → Run

### Manual

```bash
terraform destroy -var-file="environments/gesp.tfvars"
```

## Customizing Filters

Edit the `.tfvars` files to change export behavior:

```hcl
# environments/gesp.tfvars

# Only customer invoices (no vendor bills)
direction = "outgoing"

# Only invoices (no credit notes)
document_type = "invoice"

# Include draft invoices
state_filter = "posted_draft_invoices"

# Only Belgian partners
custom_domain = "[[\"partner_id.country_id.code\", \"=\", \"BE\"]]"
```

## Outputs

After deployment, you'll get:

| Output | Description |
|--------|-------------|
| `api_endpoint` | Base API URL |
| `export_endpoint` | POST to trigger export |
| `list_endpoint` | GET to list exports |
| `download_endpoint` | GET to download |
| `s3_bucket` | S3 bucket name |

## Cost Estimate

| Resource | Monthly Cost |
|----------|--------------|
| Lambda | ~$0.01 (per quarterly run) |
| API Gateway | Free tier |
| S3 | ~$0.01 |
| CloudWatch | ~$0.01 |
| **Total** | **~$0.03/month per environment** |

