# -*- coding: utf-8 -*-
"""Configuration management for UBL Export Lambda."""

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExportConfig:
    """Configuration for UBL/Statement export.

    Mirrors the Odoo module configuration options.
    """

    # === Odoo Connection ===
    odoo_url: str = ""
    odoo_database: str = ""
    odoo_username: str = ""
    odoo_api_key: str = ""

    # === Direction Filter ===
    # "both" = all invoices & bills
    # "outgoing" = customer invoices only
    # "incoming" = vendor bills only
    direction: str = "both"

    # === Document Type Filter ===
    # "all" = invoices & credit notes
    # "invoice" = invoices only
    # "refund" = credit notes only
    document_type: str = "all"

    # === State Filter ===
    # "posted" = only posted/validated
    # "posted_draft_bills" = posted + draft vendor bills (DEFAULT)
    # "posted_draft_invoices" = posted + draft customer invoices
    # "posted_draft" = posted + all drafts
    # "all" = all states
    state_filter: str = "posted_draft_bills"

    # === Custom Domain Filter ===
    # Odoo domain format, e.g.: [("partner_id.country_id.code", "=", "BE")]
    # Limited support via API - basic field filters work
    custom_domain: Optional[str] = None

    # === Email Settings ===
    # Email for UBL files (e.g., BilltoBox import address)
    # Emails are sent through Odoo's mail system, not AWS SES
    ubl_email: Optional[str] = None
    # Email for bank statement PDFs (e.g., accountant)
    pdf_email: Optional[str] = None

    # === Quarterly Auto-Send ===
    # Day of month to send (1-28)
    send_day: int = 5
    # Bank account/journal IDs to include in statement exports (empty = all)
    bank_journal_ids: list[int] = field(default_factory=list)

    # === Bank Statement Export ===
    # Include bank statements in export
    include_bank_statements: bool = True

    # === Email Options ===
    # Send UBL files as ZIP attachment (vs individual XML files)
    send_ubl_as_zip: bool = True

    # === Output Settings ===
    # S3 bucket for storing exports
    s3_bucket: Optional[str] = None
    # File extension for UBL files ("xml" or "ubl")
    # Use "ubl" for Axito compatibility
    ubl_file_extension: str = "xml"

    def get_move_types(self) -> list[str]:
        """Get list of move types based on direction and document_type filters.

        Returns:
            List of Odoo move_type values
        """
        move_types = []

        if self.direction in ("outgoing", "both"):
            if self.document_type in ("all", "invoice"):
                move_types.append("out_invoice")
            if self.document_type in ("all", "refund"):
                move_types.append("out_refund")

        if self.direction in ("incoming", "both"):
            if self.document_type in ("all", "invoice"):
                move_types.append("in_invoice")
            if self.document_type in ("all", "refund"):
                move_types.append("in_refund")

        return move_types

    def get_state_domain(self) -> list:
        """Build domain filter for state.

        Returns:
            Odoo domain list for state filtering
        """
        if self.state_filter == "posted":
            return [("state", "=", "posted")]
        elif self.state_filter == "posted_draft":
            return [("state", "in", ["posted", "draft"])]
        elif self.state_filter == "all":
            return []
        elif self.state_filter == "posted_draft_invoices":
            # Posted + draft for outgoing only
            return [
                "|",
                ("state", "=", "posted"),
                "&",
                ("state", "=", "draft"),
                ("move_type", "in", ["out_invoice", "out_refund"]),
            ]
        elif self.state_filter == "posted_draft_bills":
            # Posted + draft for incoming only
            return [
                "|",
                ("state", "=", "posted"),
                "&",
                ("state", "=", "draft"),
                ("move_type", "in", ["in_invoice", "in_refund"]),
            ]
        return [("state", "=", "posted")]

    def parse_custom_domain(self) -> list:
        """Parse custom domain string into domain list.

        Returns:
            Odoo domain list or empty list if invalid/empty
        """
        if not self.custom_domain:
            return []
        try:
            domain = json.loads(self.custom_domain.replace("'", '"'))
            if isinstance(domain, list):
                return domain
        except (json.JSONDecodeError, ValueError):
            pass
        return []

    @classmethod
    def from_env(cls) -> "ExportConfig":
        """Create config from environment variables.

        Returns:
            ExportConfig instance
        """
        bank_journal_ids = []
        journal_ids_str = os.environ.get("BANK_JOURNAL_IDS", "")
        if journal_ids_str:
            bank_journal_ids = [
                int(x) for x in journal_ids_str.split(",") if x.strip().isdigit()
            ]

        return cls(
            odoo_url=os.environ.get("ODOO_URL", ""),
            odoo_database=os.environ.get("ODOO_DATABASE", ""),
            odoo_username=os.environ.get("ODOO_USERNAME", ""),
            odoo_api_key=os.environ.get("ODOO_API_KEY", ""),
            direction=os.environ.get("DIRECTION", "both"),
            document_type=os.environ.get("DOCUMENT_TYPE", "all"),
            state_filter=os.environ.get("STATE_FILTER", "posted"),
            custom_domain=os.environ.get("CUSTOM_DOMAIN"),
            ubl_email=os.environ.get("UBL_EMAIL"),
            pdf_email=os.environ.get("PDF_EMAIL"),
            send_day=int(os.environ.get("SEND_DAY", "5")),
            bank_journal_ids=bank_journal_ids,
            include_bank_statements=os.environ.get("INCLUDE_BANK_STATEMENTS", "true").lower() == "true",
            send_ubl_as_zip=os.environ.get("SEND_UBL_AS_ZIP", "true").lower() == "true",
            s3_bucket=os.environ.get("S3_BUCKET"),
            ubl_file_extension=os.environ.get("UBL_FILE_EXTENSION", "xml"),
        )

    @classmethod
    def from_event(cls, event: dict, base_config: Optional["ExportConfig"] = None) -> "ExportConfig":
        """Create config from Lambda event, optionally merging with base config.

        Event parameters override environment/base config.

        Args:
            event: Lambda event dict
            base_config: Optional base config (e.g., from environment)

        Returns:
            ExportConfig instance
        """
        if base_config is None:
            base_config = cls.from_env()

        # Event parameters override base config
        return cls(
            odoo_url=event.get("odoo_url", base_config.odoo_url),
            odoo_database=event.get("odoo_database", base_config.odoo_database),
            odoo_username=event.get("odoo_username", base_config.odoo_username),
            odoo_api_key=event.get("odoo_api_key", base_config.odoo_api_key),
            direction=event.get("direction", base_config.direction),
            document_type=event.get("document_type", base_config.document_type),
            state_filter=event.get("state_filter", base_config.state_filter),
            custom_domain=event.get("custom_domain", base_config.custom_domain),
            ubl_email=event.get("ubl_email", base_config.ubl_email),
            pdf_email=event.get("pdf_email", base_config.pdf_email),
            send_day=event.get("send_day", base_config.send_day),
            bank_journal_ids=event.get("bank_journal_ids", base_config.bank_journal_ids),
            include_bank_statements=event.get("include_bank_statements", base_config.include_bank_statements),
            send_ubl_as_zip=event.get("send_ubl_as_zip", base_config.send_ubl_as_zip),
            s3_bucket=event.get("s3_bucket", base_config.s3_bucket),
            ubl_file_extension=event.get("ubl_file_extension", base_config.ubl_file_extension),
        )


# Direction options (for reference/validation)
DIRECTION_OPTIONS = {
    "both": "All (Invoices & Bills)",
    "outgoing": "Customer Invoices Only",
    "incoming": "Vendor Bills Only",
}

# Document type options
DOCUMENT_TYPE_OPTIONS = {
    "all": "Invoices & Credit Notes",
    "invoice": "Invoices Only",
    "refund": "Credit Notes Only",
}

# State filter options
STATE_FILTER_OPTIONS = {
    "posted": "Posted Only",
    "posted_draft_bills": "Posted + Draft Bills",
    "posted_draft_invoices": "Posted + Draft Invoices",
    "posted_draft": "Posted + All Drafts",
    "all": "All States",
}

