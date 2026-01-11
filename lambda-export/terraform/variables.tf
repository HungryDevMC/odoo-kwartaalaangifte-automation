# ============================================================
# Odoo UBL Export Lambda - Variables
# ============================================================

# === General ===

variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment name (e.g., gesp, evolf)"
  type        = string
}

# === Odoo Connection ===

variable "odoo_url" {
  description = "Odoo Online URL (e.g., https://mycompany.odoo.com)"
  type        = string
}

variable "odoo_database" {
  description = "Odoo database name"
  type        = string
}

variable "odoo_username" {
  description = "Odoo username (email)"
  type        = string
}

variable "odoo_api_key" {
  description = "Odoo API key"
  type        = string
  sensitive   = true
}

# === Filter Settings ===

variable "direction" {
  description = "Direction filter: both, outgoing, incoming"
  type        = string
  default     = "both"

  validation {
    condition     = contains(["both", "outgoing", "incoming"], var.direction)
    error_message = "Direction must be 'both', 'outgoing', or 'incoming'."
  }
}

variable "document_type" {
  description = "Document type filter: all, invoice, refund"
  type        = string
  default     = "all"

  validation {
    condition     = contains(["all", "invoice", "refund"], var.document_type)
    error_message = "Document type must be 'all', 'invoice', or 'refund'."
  }
}

variable "state_filter" {
  description = "State filter: posted, posted_draft_bills, posted_draft_invoices, posted_draft, all"
  type        = string
  default     = "posted_draft_bills"

  validation {
    condition     = contains(["posted", "posted_draft_bills", "posted_draft_invoices", "posted_draft", "all"], var.state_filter)
    error_message = "Invalid state filter value."
  }
}

variable "custom_domain" {
  description = "Custom Odoo domain filter (JSON format)"
  type        = string
  default     = ""
}

# === Email Settings ===
# Note: Emails are sent through Odoo's mail system, not AWS SES

variable "ubl_email" {
  description = "Email for UBL files (e.g., BilltoBox)"
  type        = string
  default     = ""
}

variable "pdf_email" {
  description = "Email for bank statement PDFs"
  type        = string
  default     = ""
}

# === Quarterly Settings ===

variable "send_day" {
  description = "Day of month to send quarterly exports (1-28)"
  type        = number
  default     = 5

  validation {
    condition     = var.send_day >= 1 && var.send_day <= 28
    error_message = "Send day must be between 1 and 28."
  }
}

variable "bank_journal_ids" {
  description = "Comma-separated bank journal IDs for statement exports"
  type        = string
  default     = ""
}

variable "enable_quarterly_schedule" {
  description = "Enable the quarterly auto-send schedule"
  type        = bool
  default     = true
}

variable "include_bank_statements" {
  description = "Include bank statement PDFs in exports"
  type        = bool
  default     = true
}

