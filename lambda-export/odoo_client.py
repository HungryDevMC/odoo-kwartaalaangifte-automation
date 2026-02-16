# -*- coding: utf-8 -*-
"""Odoo XML-RPC client for connecting to Odoo Online.

Supports Odoo versions 12.0 through 18.0 with automatic version detection
and compatibility handling for model/field differences.
"""

import base64
import logging
import re
import xmlrpc.client
from datetime import date, timedelta
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class OdooVersion:
    """Odoo version information with comparison helpers."""

    def __init__(self, version_string: str):
        self.raw = version_string
        # Parse version like "17.0" or "saas~17.4" or "18.0.20241215"
        match = re.search(r'(\d+)\.(\d+)', version_string)
        if match:
            self.major = int(match.group(1))
            self.minor = int(match.group(2))
        else:
            # Default to latest if parsing fails
            logger.warning(f"Could not parse Odoo version: {version_string}, assuming 17.0")
            self.major = 17
            self.minor = 0

    def __ge__(self, other: tuple) -> bool:
        return (self.major, self.minor) >= other

    def __le__(self, other: tuple) -> bool:
        return (self.major, self.minor) <= other

    def __gt__(self, other: tuple) -> bool:
        return (self.major, self.minor) > other

    def __lt__(self, other: tuple) -> bool:
        return (self.major, self.minor) < other

    def __eq__(self, other: tuple) -> bool:
        return (self.major, self.minor) == other

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"

    def __repr__(self) -> str:
        return f"OdooVersion({self.raw!r})"


class OdooClient:
    """Client for connecting to Odoo via XML-RPC External API.

    Supports Odoo versions 12.0 through 18.0+ with automatic compatibility
    handling for model and field differences between versions.
    """

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
        self._http_session = None
        self._http_authenticated = False
        self._version: OdooVersion | None = None
        self._available_fields_cache: dict[str, set[str]] = {}

    def _get_common(self) -> xmlrpc.client.ServerProxy:
        """Get common endpoint for authentication."""
        return xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")

    def _get_models(self) -> xmlrpc.client.ServerProxy:
        """Get models endpoint for CRUD operations."""
        if self._models is None:
            self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        return self._models

    def _detect_version(self) -> OdooVersion:
        """Detect the Odoo server version.

        Returns:
            OdooVersion object with parsed version info
        """
        if self._version is not None:
            return self._version

        try:
            common = self._get_common()
            version_info = common.version()
            server_version = version_info.get("server_version", "17.0")
            self._version = OdooVersion(server_version)
            logger.info(f"Detected Odoo version: {self._version} (raw: {server_version})")
        except Exception as e:
            logger.warning(f"Could not detect Odoo version: {e}, assuming 17.0")
            self._version = OdooVersion("17.0")

        return self._version

    @property
    def version(self) -> OdooVersion:
        """Get the Odoo server version, detecting if needed."""
        if self._version is None:
            self._detect_version()
        return self._version

    def _get_model_fields(self, model: str) -> set[str]:
        """Get available fields for a model (cached).

        Args:
            model: Model name

        Returns:
            Set of field names available on the model
        """
        if model in self._available_fields_cache:
            return self._available_fields_cache[model]

        try:
            fields_info = self.execute(model, "fields_get", [], {"attributes": ["name"]})
            field_names = set(fields_info.keys()) if isinstance(fields_info, dict) else set()
            self._available_fields_cache[model] = field_names
            return field_names
        except Exception as e:
            logger.warning(f"Could not get fields for {model}: {e}")
            return set()

    def _filter_fields(self, model: str, requested_fields: list[str]) -> list[str]:
        """Filter requested fields to only those available on the model.

        Args:
            model: Model name
            requested_fields: List of fields to request

        Returns:
            List of fields that exist on the model
        """
        available = self._get_model_fields(model)
        if not available:
            # If we can't determine available fields, return all requested
            return requested_fields

        filtered = [f for f in requested_fields if f in available]
        removed = set(requested_fields) - set(filtered)
        if removed:
            logger.debug(f"Fields not available on {model}: {removed}")

        return filtered

    def model_exists(self, model: str) -> bool:
        """Check if a model exists in the Odoo instance.

        Args:
            model: Model name to check

        Returns:
            True if the model exists
        """
        try:
            # Try to get fields for the model
            fields = self._get_model_fields(model)
            return bool(fields)
        except Exception:
            return False

    def safe_search_read(
        self,
        model: str,
        domain: list,
        fields: list | None = None,
        limit: int | None = None,
        order: str | None = None,
        default: list | None = None,
    ) -> list[dict]:
        """Search and read with graceful error handling.

        Args:
            model: Model name
            domain: Search domain
            fields: Fields to fetch
            limit: Maximum records
            order: Sort order
            default: Default value to return on error

        Returns:
            List of records, or default on error
        """
        if default is None:
            default = []
        try:
            return self.search_read(model, domain, fields, limit, order)
        except Exception as e:
            logger.warning(f"safe_search_read failed for {model}: {e}")
            return default

    def safe_read(
        self,
        model: str,
        ids: list[int],
        fields: list | None = None,
        default: list | None = None,
    ) -> list[dict]:
        """Read records with graceful error handling.

        Args:
            model: Model name
            ids: Record IDs
            fields: Fields to fetch
            default: Default value to return on error

        Returns:
            List of records, or default on error
        """
        if default is None:
            default = []
        try:
            return self.read(model, ids, fields)
        except Exception as e:
            logger.warning(f"safe_read failed for {model}: {e}")
            return default

    def authenticate(self) -> int:
        """Authenticate and return user ID.

        Also detects the Odoo version for compatibility handling.

        Returns:
            User ID if successful

        Raises:
            Exception: If authentication fails
        """
        # Detect version before authentication
        self._detect_version()

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
        filter_fields: bool = True,
    ) -> list[dict]:
        """Search and read records from a model.

        Args:
            model: Model name
            domain: Search domain
            fields: Fields to fetch (None = all)
            limit: Maximum records to return
            order: Sort order
            filter_fields: If True, filter out fields that don't exist on the model

        Returns:
            List of record dictionaries
        """
        kwargs = {}
        if fields:
            if filter_fields:
                fields = self._filter_fields(model, fields)
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order

        return self.execute(model, "search_read", domain, **kwargs)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list | None = None,
        filter_fields: bool = True,
    ) -> list[dict]:
        """Read specific records by ID.

        Args:
            model: Model name
            ids: List of record IDs
            fields: Fields to fetch
            filter_fields: If True, filter out fields that don't exist on the model

        Returns:
            List of record dictionaries
        """
        kwargs = {}
        if fields:
            if filter_fields:
                fields = self._filter_fields(model, fields)
            kwargs["fields"] = fields
        return self.execute(model, "read", ids, **kwargs)

    def get_company(self) -> dict:
        """Get the current user's company with bank account info.

        Returns:
            Company dictionary with bank_account field added if available
        """
        try:
            user = self.search_read(
                "res.users",
                [("id", "=", self.uid)],
                ["company_id"],
                limit=1,
                filter_fields=False,
            )
            if not user or not user[0].get("company_id"):
                logger.warning("Could not determine user's company")
                return {}

            company_id = user[0]["company_id"]
            if isinstance(company_id, (list, tuple)):
                company_id = company_id[0]

            # Fetch company with common fields
            company_fields = [
                "id", "name", "vat", "street", "street2", "city", "zip",
                "country_id", "email", "phone", "partner_id", "currency_id",
                "company_registry",
            ]
            companies = self.read("res.company", [company_id], fields=company_fields)
            if not companies:
                return {}

            company = companies[0]

            # Fetch primary bank account
            partner_id = company.get("partner_id")
            if isinstance(partner_id, (list, tuple)):
                partner_id = partner_id[0]
            if partner_id:
                try:
                    bank_accounts = self.search_read(
                        "res.partner.bank",
                        [("partner_id", "=", partner_id)],
                        ["acc_number", "bank_id", "acc_holder_name"],
                        limit=1,
                    )
                    if bank_accounts:
                        company["bank_account"] = bank_accounts[0].get("acc_number", "")
                        company["bank_id"] = bank_accounts[0].get("bank_id", False)
                except Exception as e:
                    logger.debug(f"Could not fetch bank accounts: {e}")

            return company

        except Exception as e:
            logger.error(f"Failed to get company info: {e}")
            return {}

    def get_invoices(
        self,
        date_from: date,
        date_to: date,
        move_types: list[str] | None = None,
        state: str = "posted",
    ) -> list[dict]:
        """Fetch invoices for a date range.

        Handles version differences:
        - Odoo 12 and earlier: account.invoice model
        - Odoo 13+: account.move model with move_type field

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

        # Odoo 12 and earlier use account.invoice model
        if self.version < (13, 0):
            return self._get_invoices_v12(date_from, date_to, move_types, state)

        # Odoo 13+ use account.move model
        domain = [
            ("move_type", "in", move_types),
            ("invoice_date", ">=", date_from.isoformat()),
            ("invoice_date", "<=", date_to.isoformat()),
        ]

        if state != "all":
            domain.append(("state", "=", state))

        # Common fields across Odoo 13+
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

        invoices = self.search_read(
            "account.move",
            domain,
            fields=fields,
            order="invoice_date, name",
        )

        # Normalize for cross-version compatibility
        for inv in invoices:
            # Ensure invoice_date_due exists (may be False in some cases)
            if not inv.get("invoice_date_due"):
                inv["invoice_date_due"] = inv.get("invoice_date")

        return invoices

    def _get_invoices_v12(
        self,
        date_from: date,
        date_to: date,
        move_types: list[str],
        state: str,
    ) -> list[dict]:
        """Fetch invoices from Odoo 12 and earlier (account.invoice model).

        Args:
            date_from: Start date
            date_to: End date
            move_types: Invoice types to include
            state: Invoice state filter

        Returns:
            List of invoice dictionaries normalized to match Odoo 13+ format
        """
        # Map Odoo 13+ move_types to Odoo 12 type field
        type_map = {
            "out_invoice": "out_invoice",
            "out_refund": "out_refund",
            "in_invoice": "in_invoice",
            "in_refund": "in_refund",
        }
        invoice_types = [type_map.get(t, t) for t in move_types]

        domain = [
            ("type", "in", invoice_types),
            ("date_invoice", ">=", date_from.isoformat()),
            ("date_invoice", "<=", date_to.isoformat()),
        ]

        # State mapping: Odoo 12 uses 'open' instead of 'posted'
        state_map = {"posted": "open", "draft": "draft"}
        if state != "all":
            domain.append(("state", "=", state_map.get(state, state)))

        fields = [
            "id",
            "number",
            "name",
            "type",
            "state",
            "date_invoice",
            "date_due",
            "partner_id",
            "currency_id",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
            "reference",
            "comment",
            "invoice_line_ids",
            "company_id",
        ]

        invoices = self.search_read(
            "account.invoice",
            domain,
            fields=fields,
            order="date_invoice, number",
        )

        # Normalize to Odoo 13+ format
        for inv in invoices:
            # Save original values before popping
            number = inv.pop("number", "")
            name = inv.pop("name", False)
            reference = inv.pop("reference", "")
            comment = inv.pop("comment", "")
            invoice_type = inv.pop("type", "out_invoice")
            date_invoice = inv.pop("date_invoice", None)
            date_due = inv.pop("date_due", None)

            # Map to Odoo 13+ field names
            inv["move_type"] = invoice_type
            inv["invoice_date"] = date_invoice
            inv["invoice_date_due"] = date_due or date_invoice
            inv["payment_reference"] = reference or ""
            inv["narration"] = comment or ""

            # In Odoo 12, 'number' is the invoice number (e.g., INV/2024/0001)
            # 'name' is often False or same as number
            # For ref field: use name if it's a valid string, otherwise empty
            inv["ref"] = name if (name and name is not False and name != "/") else ""

            # For name field: prefer number, fall back to name
            if number and number != "/":
                inv["name"] = number
            elif name and name is not False and name != "/":
                inv["name"] = name
            else:
                inv["name"] = ""

            # Normalize state: 'open' -> 'posted'
            if inv.get("state") == "open":
                inv["state"] = "posted"

        return invoices

    def get_invoice_lines(self, line_ids: list[int]) -> list[dict]:
        """Fetch invoice line details.

        Handles version differences:
        - Odoo 12 and earlier: account.invoice.line model
        - Odoo 13+: account.move.line model

        Args:
            line_ids: List of invoice line IDs

        Returns:
            List of line dictionaries with normalized field names
        """
        if not line_ids:
            return []

        # Odoo 12 and earlier use account.invoice.line
        if self.version < (13, 0):
            return self._get_invoice_lines_v12(line_ids)

        # Odoo 13+ fields
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

        lines = self.read("account.move.line", line_ids, fields=fields)

        # Filter out non-product lines (section headers, notes, tax lines)
        # In Odoo 13+, move_id contains invoice lines AND accounting lines
        product_lines = []
        for line in lines:
            # Lines with quantity are typically product/service lines
            # Skip lines that are just section headers or notes (quantity 0 or None)
            if line.get("quantity") is not None and line.get("quantity") != 0:
                product_lines.append(line)
            elif line.get("product_id"):
                # Has a product, likely a valid line
                product_lines.append(line)
            elif line.get("price_unit") and line.get("name"):
                # Has price and description, likely a service line
                product_lines.append(line)

        return product_lines

    def _get_invoice_lines_v12(self, line_ids: list[int]) -> list[dict]:
        """Fetch invoice lines from Odoo 12 and earlier.

        Args:
            line_ids: List of invoice line IDs

        Returns:
            List of line dictionaries normalized to Odoo 13+ format
        """
        fields = [
            "id",
            "name",
            "quantity",
            "price_unit",
            "price_subtotal",
            "discount",
            "product_id",
            "uom_id",
            "invoice_line_tax_ids",
            "invoice_id",
        ]

        lines = self.read("account.invoice.line", line_ids, fields=fields)

        # Normalize to Odoo 13+ format
        for line in lines:
            line["product_uom_id"] = line.pop("uom_id", False)
            line["tax_ids"] = line.pop("invoice_line_tax_ids", [])
            line["move_id"] = line.pop("invoice_id", False)
            # price_total doesn't exist in v12, calculate it
            if "price_total" not in line:
                subtotal = line.get("price_subtotal", 0) or 0
                # Approximate price_total (without proper tax calculation)
                line["price_total"] = subtotal

        return lines

    def get_partner(self, partner_id: int) -> dict:
        """Fetch partner details.

        Args:
            partner_id: Partner record ID

        Returns:
            Partner dictionary with normalized fields
        """
        # Common fields across all versions
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
            # Additional fields that may exist
            "state_id",
            "is_company",
            "parent_id",
        ]

        partners = self.read("res.partner", [partner_id], fields=fields)
        if not partners:
            return {}

        partner = partners[0]

        # Normalize False/None values to empty strings for string fields
        # Odoo returns False instead of None for empty fields
        string_fields = ["company_registry", "email", "phone", "vat",
                         "street", "street2", "city", "zip"]
        for field in string_fields:
            if field not in partner or partner[field] is False or partner[field] is None:
                partner[field] = ""

        return partner

    def get_taxes(self, tax_ids: list[int]) -> list[dict]:
        """Fetch tax details.

        Args:
            tax_ids: List of tax record IDs

        Returns:
            List of tax dictionaries with normalized fields
        """
        if not tax_ids:
            return []

        # Common fields across versions
        fields = [
            "id",
            "name",
            "amount",
            "amount_type",
            "type_tax_use",
            "description",
        ]

        # Additional fields that may exist in some versions
        optional_fields = [
            "tax_group_id",      # Odoo 13+
            "invoice_repartition_line_ids",  # Odoo 13+
            "refund_repartition_line_ids",   # Odoo 13+
        ]

        # Add optional fields if available
        available = self._get_model_fields("account.tax")
        for field in optional_fields:
            if field in available:
                fields.append(field)

        taxes = self.read("account.tax", tax_ids, fields=fields)

        # Normalize tax data
        for tax in taxes:
            # Ensure amount is a float
            if "amount" in tax and tax["amount"] is None:
                tax["amount"] = 0.0
            # Ensure description exists
            if "description" not in tax or not tax["description"]:
                tax["description"] = tax.get("name", "")

        return taxes

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

        Note: In Odoo 17+, bank statements are deprecated. Use
        get_bank_statement_lines() instead for transaction data.

        Args:
            date_from: Start date
            date_to: End date
            journal_ids: Optional list of journal IDs to filter by

        Returns:
            List of bank statement dictionaries
        """
        # In Odoo 17+, bank statements model is deprecated
        if self.version >= (17, 0):
            logger.info("Odoo 17+: Bank statements deprecated, returning empty list")
            return []

        domain = [
            ("date", ">=", date_from.isoformat()),
            ("date", "<=", date_to.isoformat()),
        ]

        if journal_ids:
            domain.append(("journal_id", "in", journal_ids))

        # Fields differ between versions
        # balance_end_real was renamed to balance_end in some versions
        fields = [
            "id",
            "name",
            "date",
            "journal_id",
            "balance_start",
            "balance_end_real",  # Odoo 12-16
            "balance_end",       # Some versions use this
            "line_ids",
        ]

        try:
            return self.search_read(
                "account.bank.statement",
                domain,
                fields=fields,
                order="date, name",
            )
        except Exception as e:
            logger.warning(f"Could not fetch bank statements: {e}")
            return []

    def get_bank_statement_lines(
        self,
        date_from: date,
        date_to: date,
        journal_ids: list[int] | None = None,
    ) -> list[dict]:
        """Fetch bank statement lines (transactions) for a date range.

        Handles version differences:
        - Odoo 12-13: Uses 'ref' for payment reference
        - Odoo 14-16: Uses 'payment_ref' and has 'statement_id'
        - Odoo 17+: Uses 'payment_ref', no 'statement_id' (statements deprecated)

        Args:
            date_from: Start date
            date_to: End date
            journal_ids: Optional list of journal IDs to filter by

        Returns:
            List of bank statement line dictionaries with normalized field names
        """
        domain = [
            ("date", ">=", date_from.isoformat()),
            ("date", "<=", date_to.isoformat()),
        ]

        if journal_ids:
            domain.append(("journal_id", "in", journal_ids))

        # Build version-appropriate field list
        # Common fields across all versions
        fields = [
            "id",
            "name",
            "date",
            "journal_id",
            "amount",
            "partner_id",
        ]

        # Add version-specific fields
        if self.version >= (14, 0):
            fields.append("payment_ref")
        else:
            # Odoo 12-13 uses 'ref'
            fields.append("ref")

        # statement_id removed in Odoo 17+
        if self.version < (17, 0):
            fields.append("statement_id")

        lines = self.search_read(
            "account.bank.statement.line",
            domain,
            fields=fields,
            order="date, id",
        )

        # Normalize payment reference field name
        for line in lines:
            # Ensure payment_ref exists (normalize from 'ref' in older versions)
            if "payment_ref" not in line:
                line["payment_ref"] = line.get("ref", line.get("name", ""))
            # Ensure statement_id exists (even if None for Odoo 17+)
            if "statement_id" not in line:
                line["statement_id"] = False

        return lines

    def get_bank_journals(self) -> list[dict]:
        """Get all bank/cash journals.

        Returns:
            List of journal dictionaries with normalized fields
        """
        domain = [("type", "in", ["bank", "cash"])]

        # Fields vary slightly between versions
        fields = ["id", "name", "type", "bank_account_id"]

        # Additional fields in some versions
        optional_fields = ["code", "currency_id", "company_id"]
        available = self._get_model_fields("account.journal")
        for field in optional_fields:
            if field in available:
                fields.append(field)

        try:
            return self.search_read("account.journal", domain, fields=fields)
        except Exception as e:
            logger.warning(f"Could not fetch bank journals: {e}")
            return []

    def _ensure_http_session(self) -> bool:
        """Ensure we have an authenticated HTTP session.

        Returns:
            True if session is authenticated
        """
        if self._http_authenticated and self._http_session:
            return True

        self._http_session = requests.Session()

        # Authenticate via web login
        login_url = f"{self.url}/web/session/authenticate"
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "db": self.database,
                "login": self.username,
                "password": self.api_key,
            },
            "id": 1,
        }

        try:
            response = self._http_session.post(
                login_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("result") and result["result"].get("uid"):
                self._http_authenticated = True
                logger.info("HTTP session authenticated as user %d", result["result"]["uid"])
                return True
            else:
                error = result.get("error", {}).get("message", "Unknown error")
                logger.warning("HTTP authentication failed: %s", error)
                return False

        except Exception as e:
            logger.warning("HTTP session authentication failed: %s", e)
            return False

    def get_invoice_pdf(self, invoice_id: int) -> bytes | None:
        """Fetch invoice PDF from Odoo via HTTP.

        Supports multiple Odoo versions by trying different report names.

        Args:
            invoice_id: Invoice record ID

        Returns:
            PDF content as bytes, or None if rendering failed
        """
        # Try multiple report names for compatibility across versions
        # Order matters: most common/recent first
        report_names = [
            # Odoo 14+ (account.move based)
            "account.report_invoice_with_payments",
            "account.report_invoice",
            # Odoo 13+
            "account.account_invoices",
            "account.account_invoices_without_payment",
            # Odoo 12 and earlier (account.invoice based)
            "account.report_invoice_document",
            "account.report_invoice_document_with_payments",
            # Enterprise versions
            "account_followup.report_followup_with_invoice",
        ]

        for report_name in report_names:
            pdf_data = self._fetch_report_pdf_http(report_name, [invoice_id])
            if pdf_data:
                logger.info(
                    "Generated invoice PDF using %s: %d bytes",
                    report_name, len(pdf_data)
                )
                return pdf_data

        # Fallback: check for existing PDF attachment on the invoice
        # Try both account.move and account.invoice models for older versions
        pdf_data = self._get_invoice_attachment(invoice_id)
        if pdf_data:
            logger.info("Found existing PDF attachment for invoice %d: %d bytes", invoice_id, len(pdf_data))
            return pdf_data

        logger.warning("Could not render invoice PDF for ID %d", invoice_id)
        return None

    def _fetch_report_pdf_http(
        self, report_name: str, record_ids: list[int]
    ) -> bytes | None:
        """Fetch a report PDF via HTTP.

        Args:
            report_name: Report technical name
            record_ids: List of record IDs

        Returns:
            PDF content as bytes, or None if failed
        """
        if not self._ensure_http_session():
            return None

        ids_str = ",".join(str(i) for i in record_ids)
        report_url = f"{self.url}/report/pdf/{report_name}/{ids_str}"

        try:
            response = self._http_session.get(report_url, timeout=60)

            if response.status_code == 200:
                content_type = response.headers.get("Content-Type", "")
                if "pdf" in content_type.lower() or response.content[:4] == b"%PDF":
                    return response.content

            logger.debug(
                "Report %s returned status %d for IDs %s",
                report_name, response.status_code, ids_str
            )
            return None

        except Exception as e:
            logger.debug("HTTP report fetch failed for %s: %s", report_name, e)
            return None

    def _get_invoice_attachment(self, invoice_id: int) -> bytes | None:
        """Get existing PDF attachment from invoice.

        Tries both account.move (Odoo 13+) and account.invoice (Odoo 12-)
        models for backward compatibility.

        Args:
            invoice_id: Invoice record ID

        Returns:
            PDF content as bytes, or None if not found
        """
        # Try models in version-appropriate order
        if self.version >= (13, 0):
            models_to_try = ["account.move", "account.invoice"]
        else:
            models_to_try = ["account.invoice", "account.move"]

        for model in models_to_try:
            try:
                attachments = self.search_read(
                    "ir.attachment",
                    [
                        ("res_model", "=", model),
                        ("res_id", "=", invoice_id),
                        ("mimetype", "=", "application/pdf"),
                    ],
                    fields=["id", "name", "datas"],
                    limit=1,
                    filter_fields=False,
                )

                if attachments and attachments[0].get("datas"):
                    logger.debug(f"Found PDF attachment on {model} for invoice {invoice_id}")
                    return base64.b64decode(attachments[0]["datas"])

            except Exception as e:
                logger.debug("Failed to fetch attachment from %s for invoice %d: %s", model, invoice_id, e)

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
        return self._fetch_report_pdf_http(report_name, record_ids)


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
