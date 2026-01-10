# -*- coding: utf-8 -*-
# Copyright 2025 HungryDev
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Add quarterly export settings to Accounting configuration."""

    _inherit = "res.config.settings"

    # Quarterly export settings
    quarterly_export_enabled = fields.Boolean(
        string="Enable Quarterly Auto-Send",
        config_parameter="account_invoice_ubl_export.quarterly_enabled",
        help="Automatically send invoices and bank statements quarterly",
    )
    quarterly_ubl_email = fields.Char(
        string="BilltoBox Email",
        config_parameter="account_invoice_ubl_export.ubl_email",
        help="Email address for UBL files (e.g., your BilltoBox import address)",
    )
    quarterly_pdf_email = fields.Char(
        string="Bank Statements Email",
        config_parameter="account_invoice_ubl_export.pdf_email",
        help="Email address for bank statement PDFs (e.g., your accountant)",
    )
    quarterly_send_day = fields.Integer(
        string="Send Day of Month",
        config_parameter="account_invoice_ubl_export.send_day",
        default=5,
        help="Day of the month to send quarterly reports (1-28). "
             "Reports are sent in January, April, July, and October.",
    )
    quarterly_journal_ids = fields.Many2many(
        comodel_name="account.journal",
        relation="quarterly_export_journal_rel",
        column1="config_id",
        column2="journal_id",
        string="Bank Accounts for Auto-Send",
        domain="[('type', 'in', ('bank', 'cash'))]",
        help="Select which bank accounts to include in quarterly exports",
    )

    # Invoice filter settings for quarterly export
    quarterly_state_filter = fields.Selection(
        selection=[
            ("posted", "Posted Only"),
            ("posted_draft_bills", "Posted + Draft Bills"),
            ("posted_draft_invoices", "Posted + Draft Invoices"),
            ("posted_draft", "Posted + All Drafts"),
            ("all", "All States"),
        ],
        string="Document State Filter",
        config_parameter="account_invoice_ubl_export.state_filter",
        default="posted",
        help="Filter invoices and bills by state for quarterly exports",
    )
    quarterly_custom_domain = fields.Char(
        string="Custom Filter",
        config_parameter="account_invoice_ubl_export.custom_domain",
        help="Optional domain filter for invoices in Odoo format. "
             "Examples:\n"
             "- [('partner_id.country_id.code', '=', 'BE')]\n"
             "- [('amount_total', '>', 1000)]",
    )

    @api.model
    def get_values(self):
        """Load journal IDs from config parameter."""
        res = super().get_values()
        journal_ids_str = self.env["ir.config_parameter"].sudo().get_param(
            "account_invoice_ubl_export.quarterly_journal_ids", default=""
        )
        if journal_ids_str:
            journal_ids = [int(x) for x in journal_ids_str.split(",") if x.isdigit()]
            res["quarterly_journal_ids"] = [(6, 0, journal_ids)]
        return res

    def set_values(self):
        """Save journal IDs to config parameter."""
        super().set_values()
        journal_ids_str = ",".join(str(j) for j in self.quarterly_journal_ids.ids)
        self.env["ir.config_parameter"].sudo().set_param(
            "account_invoice_ubl_export.quarterly_journal_ids", journal_ids_str
        )

    def action_test_quarterly_export(self):
        """Test button to trigger quarterly export manually."""
        return self.env[
            "account.invoice.ubl.export.wizard"
        ].action_test_quarterly_export()
