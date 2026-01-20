# -*- coding: utf-8 -*-
# Copyright 2025 HungryDev
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import io
import logging
import zipfile
from datetime import date, timedelta

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# UBL namespaces
UBL_NAMESPACES = {
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
}


class AccountInvoiceUblExportWizard(models.TransientModel):
    """Wizard for exporting invoices to UBL XML and bank statements to PDF.

    Provides three selection modes:
    - By Quarter: Export all documents from a specific quarter
    - By Date Range: Export documents within a custom date range
    - Manual Selection: Pick specific invoices from a list

    Also supports automated quarterly exports via cron job.
    """

    _name = "account.invoice.ubl.export.wizard"
    _description = "Export Invoices and Bank Statements"

    @api.model
    def _get_year_selection(self):
        """Generate year selection for the last 5 years and next year."""
        current_year = date.today().year
        return [(str(y), str(y)) for y in range(current_year - 4, current_year + 2)]

    # Selection mode
    selection_mode = fields.Selection(
        selection=[
            ("quarter", "By Quarter"),
            ("date_range", "By Date Range"),
            ("manual", "Manual Selection"),
        ],
        string="Selection Mode",
        default="quarter",
        required=True,
    )

    # Quarter selection
    year = fields.Selection(
        selection="_get_year_selection",
        string="Year",
        default=lambda self: str(date.today().year),
    )
    quarter = fields.Selection(
        selection=[
            ("Q1", "Q1 (January - March)"),
            ("Q2", "Q2 (April - June)"),
            ("Q3", "Q3 (July - September)"),
            ("Q4", "Q4 (October - December)"),
        ],
        string="Quarter",
        default=lambda self: "Q%s" % str((date.today().month - 1) // 3 + 1),
    )

    # Date range selection
    date_from = fields.Date(string="From Date")
    date_to = fields.Date(string="To Date")

    # Manual selection
    invoice_ids = fields.Many2many(
        comodel_name="account.move",
        string="Documents",
        domain="[('move_type', 'in', ['out_invoice', 'out_refund', "
               "'in_invoice', 'in_refund']), ('state', '=', 'posted')]",
    )

    # Direction filter
    direction = fields.Selection(
        selection=[
            ("both", "All (Invoices & Bills)"),
            ("outgoing", "Customer Invoices"),
            ("incoming", "Vendor Bills"),
        ],
        string="Direction",
        default="both",
        required=True,
    )

    # Document type filter
    document_type = fields.Selection(
        selection=[
            ("all", "Invoices & Credit Notes"),
            ("invoice", "Invoices Only"),
            ("refund", "Credit Notes Only"),
        ],
        string="Document Type",
        default="all",
        required=True,
    )

    # State filter
    state_filter = fields.Selection(
        selection=[
            ("posted", "Posted Only"),
            ("posted_draft_bills", "Posted + Draft Bills"),
            ("posted_draft_invoices", "Posted + Draft Invoices"),
            ("posted_draft", "Posted + All Drafts"),
            ("all", "All States"),
        ],
        string="Document State",
        default="posted",
        required=True,
        help="Filter documents by state",
    )

    # Custom domain filter
    custom_domain = fields.Char(
        string="Additional Filter",
        help="Optional domain filter in Odoo format. "
             "Examples:\n"
             "- [('partner_id.name', 'ilike', 'test')]\n"
             "- [('amount_total', '>', 1000)]\n"
             "- [('invoice_user_id', '=', uid)]",
    )

    # Bank statement export
    include_bank_statements = fields.Boolean(
        string="Include Bank Statements",
        default=False,
        help="Include bank statement PDFs in the export",
    )
    journal_ids = fields.Many2many(
        comodel_name="account.journal",
        string="Bank Accounts",
        domain="[('type', 'in', ('bank', 'cash'))]",
        help="Select bank accounts to export statements for",
    )

    # PDF embedding option
    embed_pdf = fields.Boolean(
        string="Embed PDF in UBL",
        default=True,
        help="Embed a PDF representation of the invoice in the UBL XML file. "
             "Required by most Belgian accounting software (BilltoBox, ClearFacts, etc.)",
    )

    # Output
    export_file = fields.Binary(string="Export File", readonly=True)
    export_filename = fields.Char(string="Filename", readonly=True)
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("done", "Done"),
        ],
        string="State",
        default="draft",
    )

    # Statistics
    invoice_count = fields.Integer(
        string="Documents Found",
        compute="_compute_counts",
    )
    total_amount = fields.Monetary(
        string="Total Amount",
        compute="_compute_counts",
        currency_field="currency_id",
    )
    statement_count = fields.Integer(
        string="Statements Found",
        compute="_compute_counts",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    @api.depends(
        "selection_mode",
        "quarter",
        "year",
        "date_from",
        "date_to",
        "invoice_ids",
        "direction",
        "document_type",
        "state_filter",
        "custom_domain",
        "include_bank_statements",
        "journal_ids",
    )
    def _compute_counts(self):
        """Compute document and statement counts for display."""
        for wizard in self:
            invoices = wizard._get_invoices()
            wizard.invoice_count = len(invoices)
            wizard.total_amount = sum(invoices.mapped("amount_total_signed"))
            if wizard.include_bank_statements and wizard.journal_ids:
                statements = wizard._get_bank_statements()
                wizard.statement_count = len(statements)
            else:
                wizard.statement_count = 0

    def _get_quarter_dates(self, quarter=None, year=None):
        """Return start and end date for selected quarter.

        :param quarter: Optional quarter override (Q1, Q2, Q3, Q4)
        :param year: Optional year override
        :return: tuple (start_date, end_date) or (None, None) if not set
        """
        quarters = {
            "Q1": (1, 3),
            "Q2": (4, 6),
            "Q3": (7, 9),
            "Q4": (10, 12),
        }
        quarter = quarter or self.quarter
        year = year or self.year

        if not quarter or not year:
            return None, None

        year_int = int(year)
        start_month, end_month = quarters[quarter]
        start_date = date(year_int, start_month, 1)

        # Get last day of end month
        if end_month == 12:
            end_date = date(year_int, 12, 31)
        else:
            end_date = date(year_int, end_month + 1, 1) - timedelta(days=1)

        return start_date, end_date

    def _get_move_types(self):
        """Get list of move types based on direction and document_type filters.

        :return: List of move_type values to filter on
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

    def _get_state_domain(self, state_filter=None):
        """Build state domain based on state filter setting.

        :param state_filter: Optional override for state_filter field
        :return: Domain list for state filtering
        """
        state_filter = state_filter or self.state_filter or "posted"
        outgoing_types = ["out_invoice", "out_refund"]
        incoming_types = ["in_invoice", "in_refund"]

        if state_filter == "posted":
            return [("state", "=", "posted")]
        elif state_filter == "posted_draft":
            return [("state", "in", ("posted", "draft"))]
        elif state_filter == "all":
            return []  # No state filter
        elif state_filter == "posted_draft_invoices":
            # Posted + draft for outgoing only
            return [
                "|",
                ("state", "=", "posted"),
                "&",
                ("state", "=", "draft"),
                ("move_type", "in", outgoing_types),
            ]
        elif state_filter == "posted_draft_bills":
            # Posted + draft for incoming only
            return [
                "|",
                ("state", "=", "posted"),
                "&",
                ("state", "=", "draft"),
                ("move_type", "in", incoming_types),
            ]
        return [("state", "=", "posted")]

    def _parse_custom_domain(self, domain_str=None):
        """Parse custom domain string into domain list.

        :param domain_str: Optional domain string override
        :return: Domain list or empty list if invalid
        """
        domain_str = domain_str or self.custom_domain
        if not domain_str:
            return []
        try:
            # Safely evaluate the domain string
            domain = eval(domain_str, {"uid": self.env.uid, "__builtins__": {}})
            if isinstance(domain, list):
                return domain
        except Exception as e:
            _logger.warning("Invalid custom domain '%s': %s", domain_str, e)
        return []

    def _get_invoices(self, state_filter=None, custom_domain=None):
        """Get invoices based on selection mode and filters.

        :param state_filter: Optional override for state filter
        :param custom_domain: Optional override for custom domain
        :return: account.move recordset matching the criteria
        """
        move_types = self._get_move_types()
        if not move_types:
            return self.env["account.move"]

        # Build base domain
        domain = self._get_state_domain(state_filter) + [
            ("company_id", "=", self.env.company.id),
            ("move_type", "in", move_types),
        ]

        # Add custom domain if specified
        domain.extend(self._parse_custom_domain(custom_domain))

        if self.selection_mode == "quarter":
            start_date, end_date = self._get_quarter_dates()
            if not start_date or not end_date:
                return self.env["account.move"]
            domain.extend([
                ("invoice_date", ">=", start_date),
                ("invoice_date", "<=", end_date),
            ])
        elif self.selection_mode == "date_range":
            if self.date_from:
                domain.append(("invoice_date", ">=", self.date_from))
            if self.date_to:
                domain.append(("invoice_date", "<=", self.date_to))
        elif self.selection_mode == "manual":
            if self.invoice_ids:
                domain.append(("id", "in", self.invoice_ids.ids))
            else:
                return self.env["account.move"]

        return self.env["account.move"].search(domain, order="invoice_date, name")

    def _get_bank_statements(self, journal_ids=None):
        """Get bank statements based on selection mode and journals.

        :param journal_ids: Optional recordset of journals to filter by
        :return: account.bank.statement recordset matching the criteria
        """
        journals = journal_ids or self.journal_ids
        if not journals:
            return self.env["account.bank.statement"]

        domain = [
            ("journal_id", "in", journals.ids),
            ("company_id", "=", self.env.company.id),
        ]

        if self.selection_mode == "quarter":
            start_date, end_date = self._get_quarter_dates()
            if start_date and end_date:
                domain.extend([
                    ("date", ">=", start_date),
                    ("date", "<=", end_date),
                ])
        elif self.selection_mode == "date_range":
            if self.date_from:
                domain.append(("date", ">=", self.date_from))
            if self.date_to:
                domain.append(("date", "<=", self.date_to))

        return self.env["account.bank.statement"].search(domain, order="date, name")

    def _generate_invoice_pdf(self, invoice):
        """Generate PDF for an invoice using Odoo's report engine.

        :param invoice: account.move record
        :return: bytes PDF content or None if generation failed
        """
        try:
            report = self.env.ref("account.account_invoices")
            pdf_content, _ = report._render_qweb_pdf(report, [invoice.id])
            return pdf_content
        except Exception as e:
            _logger.warning("PDF generation failed for %s: %s", invoice.name, str(e))
            return None

    def _embed_pdf_in_ubl(self, xml_content, pdf_content, invoice):
        """Embed PDF as AdditionalDocumentReference in UBL XML.

        Adds the PDF as a base64-encoded EmbeddedDocumentBinaryObject
        per Peppol BIS 3.0 specification.

        :param xml_content: bytes UBL XML content
        :param pdf_content: bytes PDF content
        :param invoice: account.move record for filename
        :return: bytes modified XML content
        """
        if not pdf_content:
            return xml_content

        try:
            # Parse the XML
            root = etree.fromstring(xml_content)

            # Get the namespace from the root element
            nsmap = root.nsmap.copy()
            # Handle default namespace
            if None in nsmap:
                nsmap['inv'] = nsmap.pop(None)

            # Create namespace-aware element names
            cac_ns = UBL_NAMESPACES['cac']
            cbc_ns = UBL_NAMESPACES['cbc']

            # Create AdditionalDocumentReference element
            add_doc_ref = etree.Element(
                "{%s}AdditionalDocumentReference" % cac_ns,
                nsmap={'cac': cac_ns, 'cbc': cbc_ns}
            )

            # Add ID element
            doc_id = etree.SubElement(add_doc_ref, "{%s}ID" % cbc_ns)
            doc_id.text = invoice.name

            # Add DocumentDescription
            doc_desc = etree.SubElement(add_doc_ref, "{%s}DocumentDescription" % cbc_ns)
            doc_desc.text = "Invoice PDF"

            # Add Attachment element
            attachment = etree.SubElement(add_doc_ref, "{%s}Attachment" % cac_ns)

            # Add EmbeddedDocumentBinaryObject
            pdf_filename = "%s.pdf" % invoice.name.replace("/", "-")
            embedded_doc = etree.SubElement(
                attachment,
                "{%s}EmbeddedDocumentBinaryObject" % cbc_ns,
                mimeCode="application/pdf",
                filename=pdf_filename
            )
            embedded_doc.text = base64.b64encode(pdf_content).decode('ascii')

            # Find insertion point - after AccountingSupplierParty or before PaymentMeans
            # Per UBL 2.1 schema, AdditionalDocumentReference comes after ContractDocumentReference
            # and before Signature. We'll insert it after any existing DocumentReference elements
            # or after AccountingCustomerParty if none exist.

            insert_after_tags = [
                "{%s}ContractDocumentReference" % cac_ns,
                "{%s}OriginatorDocumentReference" % cac_ns,
                "{%s}AdditionalDocumentReference" % cac_ns,
                "{%s}ProjectReference" % cac_ns,
                "{%s}AccountingCustomerParty" % cac_ns,
                "{%s}AccountingSupplierParty" % cac_ns,
            ]

            insert_position = None
            for tag in insert_after_tags:
                elements = root.findall(tag)
                if elements:
                    insert_position = list(root).index(elements[-1]) + 1
                    break

            if insert_position is not None:
                root.insert(insert_position, add_doc_ref)
            else:
                # Fallback: append to end (not ideal but safe)
                root.append(add_doc_ref)

            # Return modified XML
            return etree.tostring(
                root,
                pretty_print=True,
                xml_declaration=True,
                encoding='UTF-8'
            )

        except Exception as e:
            _logger.warning(
                "Failed to embed PDF in UBL for %s: %s", invoice.name, str(e)
            )
            # Return original XML if embedding fails
            return xml_content

    def _generate_ubl_xml(self, invoice, embed_pdf=True):
        """Generate UBL BIS 3.0 XML for a single invoice.

        Uses Odoo's built-in UBL BIS3 generator from account_edi_ubl_cii,
        then optionally embeds the invoice PDF.

        :param invoice: account.move record
        :param embed_pdf: Whether to embed PDF in the XML (default True)
        :return: bytes XML content or None if generation failed
        """
        builder = self.env["account.edi.xml.ubl_bis3"]
        xml_content, errors = builder._export_invoice(invoice)

        if errors:
            invoice.message_post(
                body=_("UBL Export warnings: %s") % ", ".join(errors),
                message_type="notification",
            )

        if not xml_content:
            return None

        # Embed PDF if requested
        if embed_pdf:
            pdf_content = self._generate_invoice_pdf(invoice)
            if pdf_content:
                xml_content = self._embed_pdf_in_ubl(xml_content, pdf_content, invoice)
                _logger.debug(
                    "Embedded PDF (%d bytes) in UBL for %s",
                    len(pdf_content), invoice.name
                )

        return xml_content

    def _generate_statement_pdf(self, statement):
        """Generate PDF for a bank statement.

        :param statement: account.bank.statement record
        :return: bytes PDF content
        """
        report = self.env.ref("account.action_report_account_statement")
        pdf_content, _ = report._render_qweb_pdf(report, [statement.id])
        return pdf_content

    def action_preview(self):
        """Preview the invoices that will be exported."""
        self.ensure_one()
        invoices = self._get_invoices()

        if not invoices and not (self.include_bank_statements and self.statement_count):
            raise UserError(_("No documents found for the selected criteria."))

        return {
            "name": _("Documents to Export (%s)") % len(invoices),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", invoices.ids)],
            "context": {"create": False},
        }

    def action_export(self):
        """Export invoices to UBL XML and bank statements to PDF."""
        self.ensure_one()
        invoices = self._get_invoices()
        statements = (
            self._get_bank_statements()
            if self.include_bank_statements
            else self.env["account.bank.statement"]
        )

        if not invoices and not statements:
            raise UserError(_("No documents found for the selected criteria."))

        # Create ZIP file in memory
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Export UBL files
            for invoice in invoices:
                try:
                    xml_content = self._generate_ubl_xml(invoice, embed_pdf=self.embed_pdf)
                    if xml_content:
                        filename = "UBL/%s.xml" % invoice.name.replace("/", "-")
                        zip_file.writestr(filename, xml_content)
                except Exception as e:
                    _logger.warning(
                        "UBL Export failed for %s: %s", invoice.name, str(e)
                    )
                    invoice.message_post(
                        body=_("UBL Export failed: %s") % str(e),
                        message_type="notification",
                    )

            # Export bank statement PDFs
            for statement in statements:
                try:
                    pdf_content = self._generate_statement_pdf(statement)
                    if pdf_content:
                        journal_name = statement.journal_id.name.replace("/", "-")
                        stmt_name = (
                            statement.name or statement.date.strftime("%Y-%m-%d")
                        )
                        filename = "BankStatements/%s/%s.pdf" % (
                            journal_name,
                            stmt_name.replace("/", "-"),
                        )
                        zip_file.writestr(filename, pdf_content)
                except Exception as e:
                    _logger.warning(
                        "Statement PDF failed for %s: %s", statement.name, str(e)
                    )

        # Generate ZIP filename
        zip_filename = self._get_export_filename()

        # Save to wizard
        zip_buffer.seek(0)
        self.write({
            "export_file": base64.b64encode(zip_buffer.getvalue()),
            "export_filename": zip_filename,
            "state": "done",
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _get_export_filename(self):
        """Generate filename for the export ZIP file.

        :return: Filename for the ZIP archive
        """
        if self.selection_mode == "quarter":
            return "Export_%s_%s.zip" % (self.year, self.quarter)
        elif self.selection_mode == "date_range":
            date_from_str = (
                self.date_from.strftime("%Y%m%d") if self.date_from else "start"
            )
            date_to_str = self.date_to.strftime("%Y%m%d") if self.date_to else "end"
            return "Export_%s_%s.zip" % (date_from_str, date_to_str)
        else:
            return "Export_%s.zip" % date.today().strftime("%Y%m%d")

    def action_download(self):
        """Download the generated ZIP file."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s/%s/export_file/%s?download=true" % (
                self._name,
                self.id,
                self.export_filename,
            ),
            "target": "self",
        }

    def action_reset(self):
        """Reset wizard to draft state for a new export."""
        self.ensure_one()
        self.write({
            "export_file": False,
            "export_filename": False,
            "state": "draft",
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # -------------------------------------------------------------------------
    # Cron Methods for Quarterly Auto-Send
    # -------------------------------------------------------------------------

    @api.model
    def _cron_quarterly_export(self):
        """Cron job to send quarterly exports via email.

        Runs daily, checks if today is the configured send day and if we're
        in the first month after a quarter end (Jan, Apr, Jul, Oct).
        """
        ICP = self.env["ir.config_parameter"].sudo()

        # Check if enabled
        if ICP.get_param("account_invoice_ubl_export.quarterly_enabled") != "True":
            return

        # Check if today is the configured send day
        send_day = int(ICP.get_param("account_invoice_ubl_export.send_day", "5"))
        today = date.today()
        if today.day != send_day:
            return

        # Check if we're in a "send month" (Jan, Apr, Jul, Oct)
        send_months = [1, 4, 7, 10]
        if today.month not in send_months:
            return

        # Determine previous quarter
        quarter_map = {1: ("Q4", -1), 4: ("Q1", 0), 7: ("Q2", 0), 10: ("Q3", 0)}
        quarter, year_offset = quarter_map[today.month]
        year = str(today.year + year_offset)

        # Check if already sent for this quarter (prevent duplicates)
        last_sent = ICP.get_param(
            "account_invoice_ubl_export.last_sent_quarter", ""
        )
        current_period = "%s_%s" % (year, quarter)
        if last_sent == current_period:
            _logger.info(
                "Quarterly export for %s %s already sent, skipping", quarter, year
            )
            return

        _logger.info("Running quarterly export for %s %s", quarter, year)

        # Run the actual export
        self._run_quarterly_export(quarter, year)

        # Mark as sent
        ICP.set_param("account_invoice_ubl_export.last_sent_quarter", current_period)

    @api.model
    def _run_quarterly_export(self, quarter, year):
        """Execute the quarterly export for a given quarter.

        :param quarter: Quarter string (Q1, Q2, Q3, Q4)
        :param year: Year string
        """
        ICP = self.env["ir.config_parameter"].sudo()

        # Get email addresses
        ubl_email = ICP.get_param("account_invoice_ubl_export.ubl_email")
        pdf_email = ICP.get_param("account_invoice_ubl_export.pdf_email")

        # Get journal IDs for bank statements
        journal_ids_str = ICP.get_param(
            "account_invoice_ubl_export.quarterly_journal_ids", ""
        )
        journal_ids = []
        if journal_ids_str:
            journal_ids = [int(x) for x in journal_ids_str.split(",") if x.isdigit()]

        # Get filter settings
        state_filter = ICP.get_param(
            "account_invoice_ubl_export.state_filter", "posted"
        )
        custom_domain = ICP.get_param(
            "account_invoice_ubl_export.custom_domain", ""
        )

        # Get PDF embedding setting (default True for compatibility)
        embed_pdf = ICP.get_param(
            "account_invoice_ubl_export.embed_pdf", "True"
        ) == "True"

        # Process each company
        for company in self.env["res.company"].search([]):
            self._send_quarterly_export_for_company(
                company, quarter, year, ubl_email, pdf_email, journal_ids,
                state_filter, custom_domain, embed_pdf
            )

    @api.model
    def action_test_quarterly_export(self, quarter=None, year=None):
        """Manually trigger quarterly export for testing.

        Can be called from settings or shell. If quarter/year not specified,
        uses the previous quarter.

        :param quarter: Optional quarter (Q1, Q2, Q3, Q4)
        :param year: Optional year string
        :return: Action to display notification
        """
        if not quarter or not year:
            # Default to previous quarter
            today = date.today()
            current_quarter = (today.month - 1) // 3 + 1
            if current_quarter == 1:
                quarter = "Q4"
                year = str(today.year - 1)
            else:
                quarter = "Q%s" % (current_quarter - 1)
                year = str(today.year)

        _logger.info("Manual send: Running quarterly export for %s %s", quarter, year)

        try:
            self._run_quarterly_export(quarter, year)
            message = _(
                "Export for %(quarter)s %(year)s sent. "
                "Scheduled cron will still run on configured date."
            ) % {"quarter": quarter, "year": year}
            msg_type = "success"
        except Exception as e:
            message = _("Export failed: %s") % str(e)
            msg_type = "danger"
            _logger.exception("Manual quarterly export failed")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Quarterly Export"),
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }

    def _send_quarterly_export_for_company(
        self, company, quarter, year, ubl_email, pdf_email, journal_ids,
        state_filter="posted", custom_domain="", embed_pdf=True
    ):
        """Send quarterly export for a specific company.

        :param company: res.company record
        :param quarter: Quarter string (Q1, Q2, Q3, Q4)
        :param year: Year string
        :param ubl_email: Email for UBL files
        :param pdf_email: Email for bank statement PDFs
        :param journal_ids: List of journal IDs for bank statements
        :param state_filter: State filter setting (posted, posted_draft, etc.)
        :param custom_domain: Custom domain string for additional filtering
        :param embed_pdf: Whether to embed PDF in UBL files
        """
        self = self.with_company(company)
        start_date, end_date = self._get_quarter_dates(quarter, year)

        if not start_date:
            return

        # Send UBL export to BilltoBox
        if ubl_email:
            self._send_ubl_quarterly_email(
                company, quarter, year, start_date, end_date, ubl_email,
                state_filter, custom_domain, embed_pdf
            )

        # Send bank statements to accountant
        if pdf_email and journal_ids:
            journals = self.env["account.journal"].browse(journal_ids).filtered(
                lambda j: j.company_id == company
            )
            if journals:
                self._send_statements_quarterly_email(
                    company, quarter, year, start_date, end_date, pdf_email, journals
                )

    def _send_ubl_quarterly_email(
        self, company, quarter, year, start_date, end_date, email_to,
        state_filter="posted", custom_domain="", embed_pdf=True
    ):
        """Generate and send UBL export email.

        :param company: res.company record
        :param quarter: Quarter string
        :param year: Year string
        :param start_date: Period start date
        :param end_date: Period end date
        :param email_to: Recipient email address
        :param state_filter: State filter setting
        :param custom_domain: Custom domain string for additional filtering
        :param embed_pdf: Whether to embed PDF in UBL files
        """
        # Build state domain based on filter
        state_domain = self._get_state_domain(state_filter)

        # Build base domain
        domain = state_domain + [
            ("company_id", "=", company.id),
            ("move_type", "in", [
                "out_invoice", "out_refund", "in_invoice", "in_refund"
            ]),
            ("invoice_date", ">=", start_date),
            ("invoice_date", "<=", end_date),
        ]

        # Add custom domain if specified
        domain.extend(self._parse_custom_domain(custom_domain))

        # Get all invoices for the quarter
        invoices = self.env["account.move"].search(domain)

        if not invoices:
            _logger.info("No invoices for %s %s %s", company.name, quarter, year)
            return

        # Generate individual UBL XML files
        attachments = []
        for invoice in invoices:
            try:
                xml_content = self._generate_ubl_xml(invoice, embed_pdf=embed_pdf)
                if xml_content:
                    filename = "%s.xml" % invoice.name.replace("/", "-")
                    attachments.append((filename, xml_content, "application/xml"))
            except Exception as e:
                _logger.warning(
                    "UBL export failed for %s: %s", invoice.name, str(e)
                )

        if not attachments:
            return

        # Create and send email with individual attachments
        subject = "%s - UBL Export %s %s" % (company.name, quarter, year)
        body = _(
            "<p>Quarterly UBL export for %(quarter)s %(year)s</p>"
            "<p>Company: %(company)s</p>"
            "<p>Period: %(start)s to %(end)s</p>"
            "<p>Documents: %(count)s</p>"
            "<p>PDF embedded: %(embed)s</p>"
        ) % {
            "quarter": quarter,
            "year": year,
            "company": company.name,
            "start": start_date,
            "end": end_date,
            "count": len(attachments),
            "embed": _("Yes") if embed_pdf else _("No"),
        }

        self._send_email_with_attachments(email_to, subject, body, attachments)
        _logger.info("Sent %d UBL files to %s for %s", len(attachments), email_to, company.name)

    def _send_statements_quarterly_email(
        self, company, quarter, year, start_date, end_date, email_to, journals
    ):
        """Generate and send bank statements export email.

        :param company: res.company record
        :param quarter: Quarter string
        :param year: Year string
        :param start_date: Period start date
        :param end_date: Period end date
        :param email_to: Recipient email address
        :param journals: account.journal recordset
        """
        statements = self.env["account.bank.statement"].search([
            ("journal_id", "in", journals.ids),
            ("company_id", "=", company.id),
            ("date", ">=", start_date),
            ("date", "<=", end_date),
        ])

        if not statements:
            _logger.info(
                "No bank statements for %s %s %s", company.name, quarter, year
            )
            return

        # Generate ZIP with PDFs
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for statement in statements:
                try:
                    pdf_content = self._generate_statement_pdf(statement)
                    if pdf_content:
                        journal_name = statement.journal_id.name.replace("/", "-")
                        stmt_name = (
                            statement.name or statement.date.strftime("%Y-%m-%d")
                        )
                        filename = "%s/%s.pdf" % (
                            journal_name, stmt_name.replace("/", "-")
                        )
                        zip_file.writestr(filename, pdf_content)
                except Exception as e:
                    _logger.warning(
                        "Statement PDF failed for %s: %s", statement.name, str(e)
                    )

        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()

        if not zip_data:
            return

        # Create and send email
        zip_filename = "BankStatements_%s_%s.zip" % (year, quarter)
        subject = "%s - Bank Statements %s %s" % (company.name, quarter, year)
        body = _(
            "<p>Quarterly bank statements for %(quarter)s %(year)s</p>"
            "<p>Company: %(company)s</p>"
            "<p>Period: %(start)s to %(end)s</p>"
            "<p>Statements: %(count)s</p>"
            "<p>Accounts: %(accounts)s</p>"
        ) % {
            "quarter": quarter,
            "year": year,
            "company": company.name,
            "start": start_date,
            "end": end_date,
            "count": len(statements),
            "accounts": ", ".join(journals.mapped("name")),
        }

        self._send_export_email(email_to, subject, body, zip_data, zip_filename)
        _logger.info("Sent bank statements to %s for %s", email_to, company.name)

    def _send_export_email(self, email_to, subject, body, attachment_data, filename):
        """Send email with ZIP attachment.

        :param email_to: Recipient email address
        :param subject: Email subject
        :param body: HTML email body
        :param attachment_data: ZIP file content (bytes)
        :param filename: Attachment filename
        """
        mail = self.env["mail.mail"].sudo().create({
            "email_to": email_to,
            "subject": subject,
            "body_html": body,
            "auto_delete": True,
        })

        # Add attachment
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(attachment_data),
            "mimetype": "application/zip",
            "res_model": "mail.mail",
            "res_id": mail.id,
        })
        mail.attachment_ids = [(4, attachment.id)]

        # Send email
        mail.send(auto_commit=True)

    def _send_email_with_attachments(self, email_to, subject, body, attachments):
        """Send email with multiple individual attachments.

        :param email_to: Recipient email address
        :param subject: Email subject
        :param body: HTML email body
        :param attachments: List of tuples (filename, data, mimetype)
        """
        mail = self.env["mail.mail"].sudo().create({
            "email_to": email_to,
            "subject": subject,
            "body_html": body,
            "auto_delete": True,
        })

        # Add all attachments
        attachment_ids = []
        for filename, data, mimetype in attachments:
            attachment = self.env["ir.attachment"].sudo().create({
                "name": filename,
                "datas": base64.b64encode(data) if isinstance(data, bytes) else base64.b64encode(data.encode()),
                "mimetype": mimetype,
                "res_model": "mail.mail",
                "res_id": mail.id,
            })
            attachment_ids.append(attachment.id)

        mail.attachment_ids = [(6, 0, attachment_ids)]

        # Send email
        mail.send(auto_commit=True)
