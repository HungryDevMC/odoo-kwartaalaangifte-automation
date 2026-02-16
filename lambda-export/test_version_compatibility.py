# -*- coding: utf-8 -*-
"""Tests for Odoo version compatibility.

Validates that the OdooClient produces consistent, normalized output
regardless of the Odoo version being connected to.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch, PropertyMock
from odoo_client import OdooClient, OdooVersion, get_quarter_dates


class TestOdooVersion(unittest.TestCase):
    """Test OdooVersion parsing and comparison."""

    def test_parse_standard_version(self):
        """Test parsing standard version strings."""
        v = OdooVersion("17.0")
        self.assertEqual(v.major, 17)
        self.assertEqual(v.minor, 0)
        self.assertEqual(str(v), "17.0")

    def test_parse_saas_version(self):
        """Test parsing SaaS version strings."""
        v = OdooVersion("saas~17.4")
        self.assertEqual(v.major, 17)
        self.assertEqual(v.minor, 4)

    def test_parse_full_version(self):
        """Test parsing full version with date."""
        v = OdooVersion("18.0.20241215")
        self.assertEqual(v.major, 18)
        self.assertEqual(v.minor, 0)

    def test_parse_invalid_defaults_to_17(self):
        """Test that invalid versions default to 17.0."""
        v = OdooVersion("invalid")
        self.assertEqual(v.major, 17)
        self.assertEqual(v.minor, 0)

    def test_version_comparison_ge(self):
        """Test >= comparison."""
        v = OdooVersion("17.0")
        self.assertTrue(v >= (17, 0))
        self.assertTrue(v >= (16, 0))
        self.assertTrue(v >= (14, 0))
        self.assertFalse(v >= (18, 0))

    def test_version_comparison_lt(self):
        """Test < comparison."""
        v = OdooVersion("13.0")
        self.assertTrue(v < (14, 0))
        self.assertTrue(v < (17, 0))
        self.assertFalse(v < (12, 0))
        self.assertFalse(v < (13, 0))

    def test_version_comparison_eq(self):
        """Test == comparison."""
        v = OdooVersion("14.0")
        self.assertTrue(v == (14, 0))
        self.assertFalse(v == (13, 0))


class MockOdooClient(OdooClient):
    """Mock OdooClient for testing without actual Odoo connection."""

    def __init__(self, version: str = "17.0"):
        # Don't call super().__init__ to avoid connection setup
        self.url = "https://test.odoo.com"
        self.database = "test"
        self.username = "test@test.com"
        self.api_key = "test_key"
        self._uid = 1
        self._models = MagicMock()
        self._http_session = None
        self._http_authenticated = False
        self._version = OdooVersion(version)
        self._available_fields_cache = {}
        self._mock_data = {}

    def set_mock_fields(self, model: str, fields: list[str]):
        """Set available fields for a model."""
        self._available_fields_cache[model] = set(fields)

    def set_mock_data(self, model: str, data: list[dict]):
        """Set mock data to return for a model."""
        self._mock_data[model] = data

    def execute(self, model: str, method: str, *args, **kwargs):
        """Mock execute that returns test data."""
        if method == "fields_get":
            fields = self._available_fields_cache.get(model, set())
            return {f: {"name": f} for f in fields}
        if method == "search_read":
            return self._mock_data.get(model, [])
        if method == "read":
            ids = args[0] if args else []
            all_data = self._mock_data.get(model, [])
            return [d for d in all_data if d.get("id") in ids]
        return []


class TestInvoiceCompatibility(unittest.TestCase):
    """Test invoice fetching across versions."""

    def setUp(self):
        self.date_from = date(2024, 1, 1)
        self.date_to = date(2024, 3, 31)

    def _get_odoo13_invoice_data(self):
        """Sample invoice data as returned by Odoo 13+."""
        return [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer A"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "PAY-001",
            "narration": "Test invoice",
            "invoice_line_ids": [100, 101],
            "company_id": [1, "My Company"],
            "ref": False,
        }]

    def _get_odoo12_invoice_data(self):
        """Sample invoice data as returned by Odoo 12."""
        return [{
            "id": 1,
            "number": "INV/2024/0001",
            "name": False,
            "type": "out_invoice",
            "state": "open",  # Odoo 12 uses 'open' instead of 'posted'
            "date_invoice": "2024-01-15",
            "date_due": "2024-02-15",
            "partner_id": [10, "Customer A"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "reference": "PAY-001",
            "comment": "Test invoice",
            "invoice_line_ids": [100, 101],
            "company_id": [1, "My Company"],
        }]

    def test_odoo17_invoice_fields(self):
        """Test invoice fetching in Odoo 17."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", self._get_odoo13_invoice_data())

        invoices = client.get_invoices(self.date_from, self.date_to)

        self.assertEqual(len(invoices), 1)
        inv = invoices[0]
        self.assertEqual(inv["name"], "INV/2024/0001")
        self.assertEqual(inv["move_type"], "out_invoice")
        self.assertEqual(inv["state"], "posted")
        self.assertEqual(inv["invoice_date"], "2024-01-15")
        self.assertEqual(inv["invoice_date_due"], "2024-02-15")

    def test_odoo13_invoice_fields(self):
        """Test invoice fetching in Odoo 13."""
        client = MockOdooClient("13.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", self._get_odoo13_invoice_data())

        invoices = client.get_invoices(self.date_from, self.date_to)

        self.assertEqual(len(invoices), 1)
        inv = invoices[0]
        # Should have same normalized structure as Odoo 17
        self.assertEqual(inv["name"], "INV/2024/0001")
        self.assertEqual(inv["move_type"], "out_invoice")
        self.assertEqual(inv["state"], "posted")

    def test_odoo12_invoice_normalization(self):
        """Test that Odoo 12 invoices are normalized to Odoo 13+ format."""
        client = MockOdooClient("12.0")
        client.set_mock_fields("account.invoice", [
            "id", "number", "name", "type", "state", "date_invoice",
            "date_due", "partner_id", "currency_id", "amount_untaxed",
            "amount_tax", "amount_total", "reference", "comment",
            "invoice_line_ids", "company_id"
        ])
        client.set_mock_data("account.invoice", self._get_odoo12_invoice_data())

        invoices = client.get_invoices(self.date_from, self.date_to)

        self.assertEqual(len(invoices), 1)
        inv = invoices[0]

        # Verify normalization to Odoo 13+ field names
        self.assertEqual(inv["name"], "INV/2024/0001")  # From 'number'
        self.assertEqual(inv["move_type"], "out_invoice")  # From 'type'
        self.assertEqual(inv["state"], "posted")  # From 'open'
        self.assertEqual(inv["invoice_date"], "2024-01-15")  # From 'date_invoice'
        self.assertEqual(inv["invoice_date_due"], "2024-02-15")  # From 'date_due'
        self.assertEqual(inv["payment_reference"], "PAY-001")  # From 'reference'
        self.assertEqual(inv["narration"], "Test invoice")  # From 'comment'

    def test_cross_version_output_consistency(self):
        """Test that Odoo 12 and 17 produce the same normalized output."""
        # Odoo 17 client
        client17 = MockOdooClient("17.0")
        client17.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client17.set_mock_data("account.move", self._get_odoo13_invoice_data())

        # Odoo 12 client
        client12 = MockOdooClient("12.0")
        client12.set_mock_fields("account.invoice", [
            "id", "number", "name", "type", "state", "date_invoice",
            "date_due", "partner_id", "currency_id", "amount_untaxed",
            "amount_tax", "amount_total", "reference", "comment",
            "invoice_line_ids", "company_id"
        ])
        client12.set_mock_data("account.invoice", self._get_odoo12_invoice_data())

        invoices17 = client17.get_invoices(self.date_from, self.date_to)
        invoices12 = client12.get_invoices(self.date_from, self.date_to)

        # Both should have same essential fields with same values
        inv17 = invoices17[0]
        inv12 = invoices12[0]

        # Core fields that must match
        self.assertEqual(inv17["name"], inv12["name"])
        self.assertEqual(inv17["move_type"], inv12["move_type"])
        self.assertEqual(inv17["state"], inv12["state"])
        self.assertEqual(inv17["invoice_date"], inv12["invoice_date"])
        self.assertEqual(inv17["invoice_date_due"], inv12["invoice_date_due"])
        self.assertEqual(inv17["amount_untaxed"], inv12["amount_untaxed"])
        self.assertEqual(inv17["amount_tax"], inv12["amount_tax"])
        self.assertEqual(inv17["amount_total"], inv12["amount_total"])
        self.assertEqual(inv17["payment_reference"], inv12["payment_reference"])
        self.assertEqual(inv17["narration"], inv12["narration"])


class TestInvoiceLinesCompatibility(unittest.TestCase):
    """Test invoice line fetching across versions."""

    def _get_odoo13_line_data(self):
        """Sample line data as returned by Odoo 13+."""
        return [{
            "id": 100,
            "name": "Product A",
            "quantity": 2.0,
            "price_unit": 500.0,
            "price_subtotal": 1000.0,
            "price_total": 1210.0,
            "discount": 0.0,
            "product_id": [1, "Product A"],
            "product_uom_id": [1, "Units"],
            "tax_ids": [1, 2],
            "move_id": [1, "INV/2024/0001"],
        }]

    def _get_odoo12_line_data(self):
        """Sample line data as returned by Odoo 12."""
        return [{
            "id": 100,
            "name": "Product A",
            "quantity": 2.0,
            "price_unit": 500.0,
            "price_subtotal": 1000.0,
            "discount": 0.0,
            "product_id": [1, "Product A"],
            "uom_id": [1, "Units"],
            "invoice_line_tax_ids": [1, 2],
            "invoice_id": [1, "INV/2024/0001"],
        }]

    def test_odoo17_line_fields(self):
        """Test line fetching in Odoo 17."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", self._get_odoo13_line_data())

        lines = client.get_invoice_lines([100])

        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["name"], "Product A")
        self.assertEqual(line["quantity"], 2.0)
        self.assertEqual(line["product_uom_id"], [1, "Units"])
        self.assertEqual(line["tax_ids"], [1, 2])
        self.assertEqual(line["move_id"], [1, "INV/2024/0001"])

    def test_odoo12_line_normalization(self):
        """Test that Odoo 12 lines are normalized to Odoo 13+ format."""
        client = MockOdooClient("12.0")
        client.set_mock_fields("account.invoice.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "discount", "product_id", "uom_id", "invoice_line_tax_ids",
            "invoice_id"
        ])
        client.set_mock_data("account.invoice.line", self._get_odoo12_line_data())

        lines = client.get_invoice_lines([100])

        self.assertEqual(len(lines), 1)
        line = lines[0]

        # Verify normalization
        self.assertEqual(line["name"], "Product A")
        self.assertEqual(line["product_uom_id"], [1, "Units"])  # From 'uom_id'
        self.assertEqual(line["tax_ids"], [1, 2])  # From 'invoice_line_tax_ids'
        self.assertEqual(line["move_id"], [1, "INV/2024/0001"])  # From 'invoice_id'
        self.assertIn("price_total", line)  # Should be added

    def test_cross_version_line_consistency(self):
        """Test that line output is consistent across versions."""
        # Odoo 17 client
        client17 = MockOdooClient("17.0")
        client17.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client17.set_mock_data("account.move.line", self._get_odoo13_line_data())

        # Odoo 12 client
        client12 = MockOdooClient("12.0")
        client12.set_mock_fields("account.invoice.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "discount", "product_id", "uom_id", "invoice_line_tax_ids",
            "invoice_id"
        ])
        client12.set_mock_data("account.invoice.line", self._get_odoo12_line_data())

        lines17 = client17.get_invoice_lines([100])
        lines12 = client12.get_invoice_lines([100])

        line17 = lines17[0]
        line12 = lines12[0]

        # Core fields must match
        self.assertEqual(line17["name"], line12["name"])
        self.assertEqual(line17["quantity"], line12["quantity"])
        self.assertEqual(line17["price_unit"], line12["price_unit"])
        self.assertEqual(line17["price_subtotal"], line12["price_subtotal"])
        self.assertEqual(line17["product_uom_id"], line12["product_uom_id"])
        self.assertEqual(line17["tax_ids"], line12["tax_ids"])
        self.assertEqual(line17["move_id"], line12["move_id"])


class TestBankStatementCompatibility(unittest.TestCase):
    """Test bank statement fetching across versions."""

    def setUp(self):
        self.date_from = date(2024, 1, 1)
        self.date_to = date(2024, 3, 31)

    def _get_statement_line_data_v14(self):
        """Sample statement line data for Odoo 14-16."""
        return [{
            "id": 1,
            "name": "Bank Transaction 1",
            "date": "2024-01-15",
            "journal_id": [1, "Bank"],
            "amount": 1000.0,
            "payment_ref": "TXN-001",
            "partner_id": [10, "Customer A"],
            "statement_id": [1, "BNK/2024/01"],
        }]

    def _get_statement_line_data_v13(self):
        """Sample statement line data for Odoo 13."""
        return [{
            "id": 1,
            "name": "Bank Transaction 1",
            "date": "2024-01-15",
            "journal_id": [1, "Bank"],
            "amount": 1000.0,
            "ref": "TXN-001",  # Odoo 13 uses 'ref' instead of 'payment_ref'
            "partner_id": [10, "Customer A"],
            "statement_id": [1, "BNK/2024/01"],
        }]

    def _get_statement_line_data_v17(self):
        """Sample statement line data for Odoo 17+."""
        return [{
            "id": 1,
            "name": "Bank Transaction 1",
            "date": "2024-01-15",
            "journal_id": [1, "Bank"],
            "amount": 1000.0,
            "payment_ref": "TXN-001",
            "partner_id": [10, "Customer A"],
            # No statement_id in Odoo 17+
        }]

    def test_odoo17_statement_lines(self):
        """Test statement line fetching in Odoo 17 (no statement_id)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.bank.statement.line", [
            "id", "name", "date", "journal_id", "amount",
            "payment_ref", "partner_id"  # No statement_id
        ])
        client.set_mock_data("account.bank.statement.line", self._get_statement_line_data_v17())

        lines = client.get_bank_statement_lines(self.date_from, self.date_to)

        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["payment_ref"], "TXN-001")
        self.assertEqual(line["statement_id"], False)  # Normalized to False

    def test_odoo14_statement_lines(self):
        """Test statement line fetching in Odoo 14-16."""
        client = MockOdooClient("14.0")
        client.set_mock_fields("account.bank.statement.line", [
            "id", "name", "date", "journal_id", "amount",
            "payment_ref", "partner_id", "statement_id"
        ])
        client.set_mock_data("account.bank.statement.line", self._get_statement_line_data_v14())

        lines = client.get_bank_statement_lines(self.date_from, self.date_to)

        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["payment_ref"], "TXN-001")
        self.assertEqual(line["statement_id"], [1, "BNK/2024/01"])

    def test_odoo13_statement_line_normalization(self):
        """Test that Odoo 13 ref field is normalized to payment_ref."""
        client = MockOdooClient("13.0")
        client.set_mock_fields("account.bank.statement.line", [
            "id", "name", "date", "journal_id", "amount",
            "ref", "partner_id", "statement_id"  # Uses 'ref' not 'payment_ref'
        ])
        client.set_mock_data("account.bank.statement.line", self._get_statement_line_data_v13())

        lines = client.get_bank_statement_lines(self.date_from, self.date_to)

        self.assertEqual(len(lines), 1)
        line = lines[0]
        # Should have payment_ref normalized from ref
        self.assertEqual(line["payment_ref"], "TXN-001")

    def test_odoo17_statements_deprecated(self):
        """Test that Odoo 17 returns empty for bank statements (deprecated)."""
        client = MockOdooClient("17.0")

        statements = client.get_bank_statements(self.date_from, self.date_to)

        # Should return empty list for Odoo 17+ (statements deprecated)
        self.assertEqual(statements, [])

    def test_cross_version_statement_line_consistency(self):
        """Test that statement line output is consistent across versions."""
        # Odoo 17 client
        client17 = MockOdooClient("17.0")
        client17.set_mock_fields("account.bank.statement.line", [
            "id", "name", "date", "journal_id", "amount",
            "payment_ref", "partner_id"
        ])
        client17.set_mock_data("account.bank.statement.line", self._get_statement_line_data_v17())

        # Odoo 13 client
        client13 = MockOdooClient("13.0")
        client13.set_mock_fields("account.bank.statement.line", [
            "id", "name", "date", "journal_id", "amount",
            "ref", "partner_id", "statement_id"
        ])
        client13.set_mock_data("account.bank.statement.line", self._get_statement_line_data_v13())

        lines17 = client17.get_bank_statement_lines(self.date_from, self.date_to)
        lines13 = client13.get_bank_statement_lines(self.date_from, self.date_to)

        line17 = lines17[0]
        line13 = lines13[0]

        # Core fields must match
        self.assertEqual(line17["name"], line13["name"])
        self.assertEqual(line17["date"], line13["date"])
        self.assertEqual(line17["amount"], line13["amount"])
        self.assertEqual(line17["payment_ref"], line13["payment_ref"])  # Both normalized
        # Both should have statement_id (False for v17, actual value for v13)
        self.assertIn("statement_id", line17)
        self.assertIn("statement_id", line13)


class TestFieldFiltering(unittest.TestCase):
    """Test automatic field filtering for version compatibility."""

    def test_filter_removes_unavailable_fields(self):
        """Test that unavailable fields are filtered out."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("test.model", ["id", "name", "field_a"])

        filtered = client._filter_fields("test.model", [
            "id", "name", "field_a", "field_b", "field_c"
        ])

        self.assertEqual(set(filtered), {"id", "name", "field_a"})
        self.assertNotIn("field_b", filtered)
        self.assertNotIn("field_c", filtered)

    def test_filter_returns_all_if_no_cache(self):
        """Test that all fields are returned if model fields can't be determined."""
        client = MockOdooClient("17.0")
        # Don't set any mock fields - simulates inability to fetch fields

        requested = ["id", "name", "field_a"]
        filtered = client._filter_fields("unknown.model", requested)

        # Should return all requested fields
        self.assertEqual(filtered, requested)


class TestQuarterDates(unittest.TestCase):
    """Test quarter date calculation."""

    def test_q1_dates(self):
        """Test Q1 date range."""
        start, end = get_quarter_dates("Q1", 2024)
        self.assertEqual(start, date(2024, 1, 1))
        self.assertEqual(end, date(2024, 3, 31))

    def test_q2_dates(self):
        """Test Q2 date range."""
        start, end = get_quarter_dates("Q2", 2024)
        self.assertEqual(start, date(2024, 4, 1))
        self.assertEqual(end, date(2024, 6, 30))

    def test_q3_dates(self):
        """Test Q3 date range."""
        start, end = get_quarter_dates("Q3", 2024)
        self.assertEqual(start, date(2024, 7, 1))
        self.assertEqual(end, date(2024, 9, 30))

    def test_q4_dates(self):
        """Test Q4 date range."""
        start, end = get_quarter_dates("Q4", 2024)
        self.assertEqual(start, date(2024, 10, 1))
        self.assertEqual(end, date(2024, 12, 31))

    def test_lowercase_quarter(self):
        """Test that lowercase quarter works."""
        start, end = get_quarter_dates("q1", 2024)
        self.assertEqual(start, date(2024, 1, 1))


class TestPartnerCompatibility(unittest.TestCase):
    """Test partner fetching across versions."""

    def _get_partner_data(self):
        """Sample partner data."""
        return [{
            "id": 10,
            "name": "Customer A",
            "vat": "BE0123456789",
            "street": "Main Street 1",
            "street2": False,
            "city": "Brussels",
            "zip": "1000",
            "country_id": [21, "Belgium"],
            "email": "customer@example.com",
            "phone": "+32123456789",
            "commercial_partner_id": [10, "Customer A"],
            "company_registry": "0123.456.789",
            "state_id": False,
            "is_company": True,
            "parent_id": False,
        }]

    def test_partner_normalization(self):
        """Test partner data normalization."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("res.partner", [
            "id", "name", "vat", "street", "street2", "city", "zip",
            "country_id", "email", "phone", "commercial_partner_id",
            "company_registry", "state_id", "is_company", "parent_id"
        ])
        client.set_mock_data("res.partner", self._get_partner_data())

        partner = client.get_partner(10)

        self.assertEqual(partner["name"], "Customer A")
        self.assertEqual(partner["vat"], "BE0123456789")
        self.assertEqual(partner["company_registry"], "0123.456.789")
        self.assertEqual(partner["email"], "customer@example.com")

    def test_partner_missing_optional_fields(self):
        """Test partner with missing optional fields."""
        client = MockOdooClient("12.0")
        # Odoo 12 might not have all fields
        client.set_mock_fields("res.partner", [
            "id", "name", "vat", "street", "city", "zip", "country_id"
        ])
        client.set_mock_data("res.partner", [{
            "id": 10,
            "name": "Customer A",
            "vat": "BE0123456789",
            "street": "Main Street 1",
            "city": "Brussels",
            "zip": "1000",
            "country_id": [21, "Belgium"],
        }])

        partner = client.get_partner(10)

        self.assertEqual(partner["name"], "Customer A")
        # Optional fields should have defaults
        self.assertEqual(partner.get("company_registry", ""), "")
        self.assertEqual(partner.get("email", ""), "")


class TestTaxCompatibility(unittest.TestCase):
    """Test tax fetching across versions."""

    def _get_tax_data_v13(self):
        """Sample tax data for Odoo 13+."""
        return [{
            "id": 1,
            "name": "VAT 21%",
            "amount": 21.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "description": "21% VAT",
            "tax_group_id": [1, "VAT"],
        }]

    def _get_tax_data_v12(self):
        """Sample tax data for Odoo 12."""
        return [{
            "id": 1,
            "name": "VAT 21%",
            "amount": 21.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "description": False,  # Often missing in Odoo 12
        }]

    def test_tax_v17(self):
        """Test tax fetching in Odoo 17."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.tax", [
            "id", "name", "amount", "amount_type", "type_tax_use",
            "description", "tax_group_id"
        ])
        client.set_mock_data("account.tax", self._get_tax_data_v13())

        taxes = client.get_taxes([1])

        self.assertEqual(len(taxes), 1)
        tax = taxes[0]
        self.assertEqual(tax["name"], "VAT 21%")
        self.assertEqual(tax["amount"], 21.0)

    def test_tax_description_normalization(self):
        """Test that missing description is normalized."""
        client = MockOdooClient("12.0")
        client.set_mock_fields("account.tax", [
            "id", "name", "amount", "amount_type", "type_tax_use", "description"
        ])
        client.set_mock_data("account.tax", self._get_tax_data_v12())

        taxes = client.get_taxes([1])

        tax = taxes[0]
        # Description should be set to name if False/missing
        self.assertEqual(tax["description"], "VAT 21%")


class TestUBLGenerationConsistency(unittest.TestCase):
    """Test that UBL generation produces consistent output across versions."""

    def _get_normalized_invoice(self):
        """Get a normalized invoice dict (as produced by our code)."""
        return {
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer A"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "PAY-001",
            "narration": "Test invoice",
            "invoice_line_ids": [100],
            "company_id": [1, "My Company"],
            "ref": "",
            "_ubl_number": "INV/2024/0001",
        }

    def _get_normalized_partner(self):
        """Get a normalized partner dict."""
        return {
            "id": 10,
            "name": "Customer A",
            "vat": "BE0123456789",
            "street": "Main Street 1",
            "street2": False,
            "city": "Brussels",
            "zip": "1000",
            "country_id": [21, "Belgium"],
            "email": "customer@example.com",
            "phone": "+32123456789",
            "commercial_partner_id": [10, "Customer A"],
            "company_registry": "",
        }

    def _get_normalized_line(self):
        """Get a normalized invoice line dict."""
        return {
            "id": 100,
            "name": "Product A - Description",
            "quantity": 2.0,
            "price_unit": 500.0,
            "price_subtotal": 1000.0,
            "price_total": 1210.0,
            "discount": 0.0,
            "product_id": [1, "Product A"],
            "product_uom_id": [1, "Units"],
            "tax_ids": [1],
            "move_id": [1, "INV/2024/0001"],
        }

    def _get_normalized_tax(self):
        """Get a normalized tax dict."""
        return {
            "id": 1,
            "name": "VAT 21%",
            "amount": 21.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "description": "21% VAT",
        }

    def _get_company(self):
        """Get company info."""
        return {
            "id": 1,
            "name": "My Company",
            "vat": "BE0987654321",
            "street": "Company Street 10",
            "street2": False,
            "city": "Antwerp",
            "zip": "2000",
            "country_id": [21, "Belgium"],
            "email": "info@mycompany.com",
            "phone": "+32987654321",
            "bank_account": "BE12345678901234",
        }

    def test_ubl_generation_with_normalized_data(self):
        """Test that UBL can be generated from normalized data."""
        try:
            from ubl_generator import UBLGenerator
        except ImportError:
            self.skipTest("UBLGenerator not available")

        company = self._get_company()
        invoice = self._get_normalized_invoice()
        partner = self._get_normalized_partner()
        lines = [self._get_normalized_line()]
        taxes = {1: self._get_normalized_tax()}
        products = {1: {"id": 1, "name": "Product A", "default_code": "PROD-A"}}

        generator = UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, taxes, products
        )

        # Verify XML was generated
        self.assertIsInstance(xml_content, bytes)
        self.assertGreater(len(xml_content), 100)

        # Verify it's valid XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_content)

        # Check it's a UBL Invoice
        self.assertIn("Invoice", root.tag)

    def test_ubl_contains_required_fields(self):
        """Test that generated UBL contains required Peppol fields."""
        try:
            from ubl_generator import UBLGenerator
        except ImportError:
            self.skipTest("UBLGenerator not available")

        company = self._get_company()
        invoice = self._get_normalized_invoice()
        partner = self._get_normalized_partner()
        lines = [self._get_normalized_line()]
        taxes = {1: self._get_normalized_tax()}
        products = {1: {"id": 1, "name": "Product A", "default_code": "PROD-A"}}

        generator = UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, taxes, products
        )

        xml_str = xml_content.decode('utf-8')

        # Check for required Peppol elements
        self.assertIn("CustomizationID", xml_str)
        self.assertIn("ProfileID", xml_str)
        self.assertIn("ID", xml_str)  # Invoice number
        self.assertIn("IssueDate", xml_str)
        self.assertIn("AccountingSupplierParty", xml_str)
        self.assertIn("AccountingCustomerParty", xml_str)
        self.assertIn("InvoiceLine", xml_str)
        self.assertIn("LegalMonetaryTotal", xml_str)

    def test_credit_note_generation(self):
        """Test that credit notes are generated correctly."""
        try:
            from ubl_generator import UBLGenerator
        except ImportError:
            self.skipTest("UBLGenerator not available")

        company = self._get_company()
        invoice = self._get_normalized_invoice()
        invoice["move_type"] = "out_refund"  # Credit note
        invoice["name"] = "CN/2024/0001"
        invoice["_ubl_number"] = "CN/2024/0001"

        partner = self._get_normalized_partner()
        lines = [self._get_normalized_line()]
        taxes = {1: self._get_normalized_tax()}
        products = {1: {"id": 1, "name": "Product A", "default_code": "PROD-A"}}

        generator = UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, taxes, products
        )

        xml_str = xml_content.decode('utf-8')

        # Credit notes should use CreditNote element
        self.assertIn("CreditNote", xml_str)


class TestVersionCompatibilitySummary(unittest.TestCase):
    """Summary test to verify all version-specific behavior."""

    def test_version_specific_model_selection(self):
        """Test that correct models are selected based on version."""
        # Odoo 12 should use account.invoice
        client12 = MockOdooClient("12.0")
        self.assertTrue(client12.version < (13, 0))

        # Odoo 13+ should use account.move
        client13 = MockOdooClient("13.0")
        self.assertTrue(client13.version >= (13, 0))

        # Odoo 17+ should skip bank statements
        client17 = MockOdooClient("17.0")
        self.assertTrue(client17.version >= (17, 0))

    def test_all_versions_produce_same_schema(self):
        """Test that all versions produce invoices with the same field schema."""
        date_from = date(2024, 1, 1)
        date_to = date(2024, 3, 31)

        # Required fields in normalized output
        required_fields = {
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        }

        # Test Odoo 17
        client17 = MockOdooClient("17.0")
        client17.set_mock_fields("account.move", list(required_fields))
        client17.set_mock_data("account.move", [{
            "id": 1, "name": "INV-001", "move_type": "out_invoice",
            "state": "posted", "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15", "partner_id": [1, "Test"],
            "currency_id": [1, "EUR"], "amount_untaxed": 100,
            "amount_tax": 21, "amount_total": 121,
            "payment_reference": "", "narration": "",
            "invoice_line_ids": [], "company_id": [1, "Co"], "ref": ""
        }])
        inv17 = client17.get_invoices(date_from, date_to)[0]

        # Test Odoo 12
        client12 = MockOdooClient("12.0")
        v12_fields = ["id", "number", "name", "type", "state", "date_invoice",
                      "date_due", "partner_id", "currency_id", "amount_untaxed",
                      "amount_tax", "amount_total", "reference", "comment",
                      "invoice_line_ids", "company_id"]
        client12.set_mock_fields("account.invoice", v12_fields)
        client12.set_mock_data("account.invoice", [{
            "id": 1, "number": "INV-001", "name": False,
            "type": "out_invoice", "state": "open",
            "date_invoice": "2024-01-15", "date_due": "2024-02-15",
            "partner_id": [1, "Test"], "currency_id": [1, "EUR"],
            "amount_untaxed": 100, "amount_tax": 21, "amount_total": 121,
            "reference": "", "comment": "",
            "invoice_line_ids": [], "company_id": [1, "Co"]
        }])
        inv12 = client12.get_invoices(date_from, date_to)[0]

        # Both should have all required fields
        for field in required_fields:
            self.assertIn(field, inv17, f"Odoo 17 missing field: {field}")
            self.assertIn(field, inv12, f"Odoo 12 missing field: {field}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
