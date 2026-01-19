# ============================================================
# GESP Environment Configuration
# ============================================================

environment = "gesp"
aws_region  = "eu-west-1"

# === Odoo Connection ===
# These are set via environment variables in the pipeline:
# - TF_VAR_odoo_url
# - TF_VAR_odoo_database
# - TF_VAR_odoo_username
# - TF_VAR_odoo_api_key

# === Filter Settings ===
direction     = "both"               # both, outgoing, incoming
document_type = "all"                # all, invoice, refund
state_filter  = "posted_draft_bills" # posted, posted_draft_bills, posted_draft_invoices, posted_draft, all
custom_domain = ""                   # Optional: [["partner_id.country_id.code", "=", "BE"]]

# === Email Settings ===
# Set via environment variables for security:
# - TF_VAR_sender_email
# - TF_VAR_ubl_email
# - TF_VAR_pdf_email

# === Quarterly Settings ===
send_day                  = 5
bank_journal_ids          = "" # Comma-separated IDs
enable_quarterly_schedule = true

# === Output Settings ===
ubl_file_extension = "ubl" # Use .ubl extension for Axito compatibility

