# -*- coding: utf-8 -*-
"""Odoo XML-RPC client for connecting to Odoo Online."""

import base64
import logging
import xmlrpc.client
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class OdooClient:
    """Client for connecting to Odoo via XML-RPC External API."""

    def __init__(self, url: str, database: str, username: str, api_key: str):
        """Initialize Odoo client.

        Args:
            url: Odoo instance URL (e.g., https://mycompany.odoo.com)
            database: Database name (usually same as subdomain)
            username: User email/login
            api_key: API key (generate in Odoo: Settings → Users → API Keys)
        """
        self.url = url.rstrip("/")
        self.database = database
        self.username = username
        self.api_key = api_key
        self._uid = None
        self._models = None

    def _get_common(self) -> xmlrpc.client.ServerProxy:
        """Get common endpoint for authentication."""
        return xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")

    def _get_models(self) -> xmlrpc.client.ServerProxy:
        """Get models endpoint for CRUD operations."""
        if self._models is None:
            self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        return self._models

    def authenticate(self) -> int:
        """Authenticate and return user ID.

        Returns:
            User ID if successful

        Raises:
            Exception: If authentication fails
        """
        common = self._get_common()
        self._uid = common.authenticate(
            self.database, self.username, self.api_key, {}
        )
        if not self._uid:
            raise Exception(
                f"Authentication failed for {self.username} on {self.database}"
            )
        return self._uid

    @property
    def uid(self) -> int:
        """Get authenticated user ID, authenticating if needed."""
        if self._uid is None:
            self.authenticate()
        return self._uid

    def execute(
        self, model: str, method: str, *args, **kwargs
    ) -> Any:
        """Execute a method on an Odoo model.

        Args:
            model: Model name (e.g., 'account.move')
            method: Method name (e.g., 'search_read')
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            Method result
        """
        models = self._get_models()
        return models.execute_kw(
            self.database,
            self.uid,
            self.api_key,
            model,
            method,
            args,
            kwargs,
        )

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list | None = None,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict]:
        """Search and read records from a model.

        Args:
            model: Model name
            domain: Search domain
            fields: Fields to fetch (None = all)
            limit: Maximum records to return
            order: Sort order

        Returns:
            List of record dictionaries
        """
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order

        return self.execute(model, "search_read", domain, **kwargs)

    def read(self, model: str, ids: list[int], fields: list | None = None) -> list[dict]:
        """Read specific records by ID.

        Args:
            model: Model name
            ids: List of record IDs
            fields: Fields to fetch

        Returns:
            List of record dictionaries
        """
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute(model, "read", ids, **kwargs)

    def get_company(self) -> dict:
        """Get the current user's company."""
        user = self.search_read(
            "res.users",
            [("id", "=", self.uid)],
            ["company_id"],
            limit=1,
        )
        if user and user[0].get("company_id"):
            company_id = user[0]["company_id"][0]
            companies = self.read("res.company", [company_id])
            return companies[0] if companies else {}
        return {}

    def get_invoices(
        self,
        date_from: date,
        date_to: date,
        move_types: list[str] | None = None,
        state: str = "posted",
    ) -> list[dict]:
        """Fetch invoices for a date range.

        Args:
            date_from: Start date
            date_to: End date
            move_types: Invoice types to include (default: all invoice types)
            state: Invoice state filter ('posted', 'draft', or 'all')

        Returns:
            List of invoice dictionaries with all relevant fields
        """
        if move_types is None:
            move_types = ["out_invoice", "out_refund", "in_invoice", "in_refund"]

        domain = [
            ("move_type", "in", move_types),
            ("invoice_date", ">=", date_from.isoformat()),
            ("invoice_date", "<=", date_to.isoformat()),
        ]

        if state != "all":
            domain.append(("state", "=", state))

        fields = [
            "id",
            "name",
            "move_type",
            "state",
            "invoice_date",
            "invoice_date_due",
            "partner_id",
            "currency_id",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
            "payment_reference",
            "narration",
            "invoice_line_ids",
            "company_id",
            "ref",
        ]

        return self.search_read(
            "account.move",
            domain,
            fields=fields,
            order="invoice_date, name",
        )

    def get_invoice_lines(self, line_ids: list[int]) -> list[dict]:
        """Fetch invoice line details.

        Args:
            line_ids: List of invoice line IDs

        Returns:
            List of line dictionaries
        """
        if not line_ids:
            return []

        fields = [
            "id",
            "name",
            "quantity",
            "price_unit",
            "price_subtotal",
            "price_total",
            "discount",
            "product_id",
            "product_uom_id",
            "tax_ids",
            "move_id",
        ]

        return self.read("account.move.line", line_ids, fields=fields)

    def get_partner(self, partner_id: int) -> dict:
        """Fetch partner details.

        Args:
            partner_id: Partner record ID

        Returns:
            Partner dictionary
        """
        fields = [
            "id",
            "name",
            "vat",
            "street",
            "street2",
            "city",
            "zip",
            "country_id",
            "email",
            "phone",
            "commercial_partner_id",
            "company_registry",
        ]

        partners = self.read("res.partner", [partner_id], fields=fields)
        return partners[0] if partners else {}

    def get_taxes(self, tax_ids: list[int]) -> list[dict]:
        """Fetch tax details.

        Args:
            tax_ids: List of tax record IDs

        Returns:
            List of tax dictionaries
        """
        if not tax_ids:
            return []

        fields = [
            "id",
            "name",
            "amount",
            "amount_type",
            "type_tax_use",
            "description",
        ]

        return self.read("account.tax", tax_ids, fields=fields)

    def get_products(self, product_ids: list[int]) -> list[dict]:
        """Fetch product details.

        Args:
            product_ids: List of product record IDs

        Returns:
            List of product dictionaries
        """
        if not product_ids:
            return []

        fields = [
            "id",
            "name",
            "default_code",
            "barcode",
            "description_sale",
        ]

        return self.read("product.product", product_ids, fields=fields)

    def get_bank_statements(
        self,
        date_from: date,
        date_to: date,
        journal_ids: list[int] | None = None,
    ) -> list[dict]:
        """Fetch bank statements for a date range.

        Args:
            date_from: Start date
            date_to: End date
            journal_ids: Optional list of journal IDs to filter by

        Returns:
            List of bank statement dictionaries
        """
        domain = [
            ("date", ">=", date_from.isoformat()),
            ("date", "<=", date_to.isoformat()),
        ]

        if journal_ids:
            domain.append(("journal_id", "in", journal_ids))

        fields = [
            "id",
            "name",
            "date",
            "journal_id",
            "balance_start",
            "balance_end_real",
            "line_ids",
        ]

        return self.search_read(
            "account.bank.statement",
            domain,
            fields=fields,
            order="date, name",
        )

    def get_bank_statement_lines(
        self,
        date_from: date,
        date_to: date,
        journal_ids: list[int] | None = None,
    ) -> list[dict]:
        """Fetch bank statement lines (transactions) for a date range.

        In Odoo 14+, bank transactions may not be grouped into statements.
        This fetches individual transaction lines.

        Args:
            date_from: Start date
            date_to: End date
            journal_ids: Optional list of journal IDs to filter by

        Returns:
            List of bank statement line dictionaries
        """
        domain = [
            ("date", ">=", date_from.isoformat()),
            ("date", "<=", date_to.isoformat()),
        ]

        if journal_ids:
            domain.append(("journal_id", "in", journal_ids))

        fields = [
            "id",
            "name",
            "date",
            "journal_id",
            "amount",
            "payment_ref",
            "partner_id",
            "statement_id",
        ]

        return self.search_read(
            "account.bank.statement.line",
            domain,
            fields=fields,
            order="date, id",
        )

    def get_bank_journals(self) -> list[dict]:
        """Get all bank/cash journals.

        Returns:
            List of journal dictionaries
        """
        domain = [("type", "in", ["bank", "cash"])]
        fields = ["id", "name", "type", "bank_account_id"]

        return self.search_read("account.journal", domain, fields=fields)

    def get_invoice_pdf(self, invoice_id: int) -> bytes | None:
        """Fetch invoice PDF from Odoo.

        Args:
            invoice_id: Invoice record ID

        Returns:
            PDF content as bytes, or None if rendering failed
        """
        # Try multiple report names for compatibility
        report_names = [
            "account.report_invoice_with_payments",
            "account.report_invoice",
            "account.account_invoices",
        ]

        for report_name in report_names:
            pdf_data = self.render_report_pdf(report_name, [invoice_id])
            if pdf_data:
                logger.info(
                    "Generated invoice PDF using %s: %d bytes",
                    report_name, len(pdf_data)
                )
                return pdf_data

        logger.warning("Could not render invoice PDF for ID %d", invoice_id)
        return None

    def render_report_pdf(
        self, report_name: str, record_ids: list[int]
    ) -> bytes | None:
        """Render a report as PDF.

        Args:
            report_name: Report XML ID or name (e.g., 'account.report_bank_statement')
            record_ids: List of record IDs to include in the report

        Returns:
            PDF content as bytes, or None if rendering failed
        """
        try:
            # Try using report service
            # Method 1: ir.actions.report render_qweb_pdf
            result = self.execute(
                "ir.actions.report",
                "_render_qweb_pdf",
                report_name,
                record_ids,
            )

            if result and isinstance(result, (list, tuple)) and len(result) >= 1:
                pdf_data = result[0]
                if isinstance(pdf_data, bytes):
                    return pdf_data
                elif isinstance(pdf_data, str):
                    # Base64 encoded
                    return base64.b64decode(pdf_data)

            return None

        except Exception as e:
            logger.debug("Method 1 failed for %s: %s", report_name, e)
            # Method 2: Try alternative approach via report action
            try:
                # Find the report action
                report_action = self.search_read(
                    "ir.actions.report",
                    [("report_name", "=", report_name)],
                    ["id"],
                    limit=1,
                )

                if report_action:
                    result = self.execute(
                        "ir.actions.report",
                        "_render_qweb_pdf",
                        [report_action[0]["id"]],
                        record_ids,
                    )

                    if result and isinstance(result, (list, tuple)) and len(result) >= 1:
                        pdf_data = result[0]
                        if isinstance(pdf_data, bytes):
                            return pdf_data
                        elif isinstance(pdf_data, str):
                            return base64.b64decode(pdf_data)

            except Exception as e2:
                logger.debug("Method 2 failed for %s: %s", report_name, e2)

            return None


def get_quarter_dates(quarter: str, year: int) -> tuple[date, date]:
    """Get start and end dates for a quarter.

    Args:
        quarter: Quarter string (Q1, Q2, Q3, Q4)
        year: Year

    Returns:
        Tuple of (start_date, end_date)
    """
    quarters = {
        "Q1": (1, 3),
        "Q2": (4, 6),
        "Q3": (7, 9),
        "Q4": (10, 12),
    }

    start_month, end_month = quarters[quarter.upper()]
    start_date = date(year, start_month, 1)

    # Get last day of end month
    if end_month == 12:
        end_date = date(year, 12, 31)
    else:
        end_date = date(year, end_month + 1, 1) - timedelta(days=1)

    return start_date, end_date
