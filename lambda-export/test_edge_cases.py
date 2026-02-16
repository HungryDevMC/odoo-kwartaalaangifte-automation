# -*- coding: utf-8 -*-
"""Edge case tests to break the Odoo export implementation.

Tests common Odoo quirks, edge cases, and potential failure modes.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch
from decimal import Decimal

# Import test utilities from version compatibility tests
from test_version_compatibility import MockOdooClient


class TestOdooFalseVsNone(unittest.TestCase):
    """Test handling of Odoo's False vs None vs empty string quirks.

    Odoo often returns False instead of None for empty fields,
    which can cause issues with truthiness checks.
    """

    def test_partner_with_false_values(self):
        """Test partner with False values for optional fields."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("res.partner", [
            "id", "name", "vat", "street", "street2", "city", "zip",
            "country_id", "email", "phone", "commercial_partner_id",
            "company_registry", "state_id", "is_company", "parent_id"
        ])
        # Odoo returns False, not None, for empty fields
        client.set_mock_data("res.partner", [{
            "id": 10,
            "name": "Test Partner",
            "vat": False,  # No VAT
            "street": False,
            "street2": False,
            "city": False,
            "zip": False,
            "country_id": False,  # No country
            "email": False,
            "phone": False,
            "commercial_partner_id": False,
            "company_registry": False,
            "state_id": False,
            "is_company": False,
            "parent_id": False,
        }])

        partner = client.get_partner(10)

        # Should not crash and should have default values
        self.assertEqual(partner["name"], "Test Partner")
        self.assertEqual(partner.get("company_registry", ""), "")
        self.assertEqual(partner.get("email", ""), "")

    def test_invoice_with_false_date_due(self):
        """Test invoice where date_due is False."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": False,  # No due date set
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": False,
            "narration": False,
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": False,
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        inv = invoices[0]
        # invoice_date_due should fall back to invoice_date
        self.assertEqual(inv["invoice_date_due"], "2024-01-15")

    def test_invoice_line_with_false_product(self):
        """Test invoice line without a product (service line)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Consulting services",
            "quantity": 10.0,
            "price_unit": 100.0,
            "price_subtotal": 1000.0,
            "price_total": 1210.0,
            "discount": 0.0,
            "product_id": False,  # No product
            "product_uom_id": False,  # No UOM
            "tax_ids": [1],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        # Should not crash
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["product_id"], False)


class TestMany2OneFieldFormats(unittest.TestCase):
    """Test different Many2one field return formats.

    Many2one fields can return:
    - [id, name] tuple/list
    - id (integer only, when using specific field options)
    - False (when empty)
    """

    def test_partner_id_as_tuple(self):
        """Test partner_id returned as [id, name] tuple."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer A"],  # Tuple format
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))
        self.assertEqual(invoices[0]["partner_id"], [10, "Customer A"])

    def test_partner_id_as_list(self):
        """Test partner_id returned as list (JSON deserialized)."""
        # When coming from JSON, tuples become lists
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer A"],  # List format (from JSON)
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        # Code should handle both tuple and list
        partner_id = invoices[0]["partner_id"]
        if isinstance(partner_id, (list, tuple)):
            self.assertEqual(partner_id[0], 10)


class TestDraftInvoicesWithoutNumbers(unittest.TestCase):
    """Test handling of draft invoices that don't have numbers yet.

    In Odoo, draft invoices often have name="/" until posted.
    """

    def test_draft_invoice_with_slash_name(self):
        """Test draft invoice with name='/'."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "/",  # Draft - no number yet
            "move_type": "out_invoice",
            "state": "draft",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [100],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(
            date(2024, 1, 1), date(2024, 3, 31), state="all"
        )

        # Invoice should be returned but name is "/"
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["name"], "/")

    def test_odoo12_draft_without_number(self):
        """Test Odoo 12 draft invoice without number."""
        client = MockOdooClient("12.0")
        client.set_mock_fields("account.invoice", [
            "id", "number", "name", "type", "state", "date_invoice",
            "date_due", "partner_id", "currency_id", "amount_untaxed",
            "amount_tax", "amount_total", "reference", "comment",
            "invoice_line_ids", "company_id"
        ])
        client.set_mock_data("account.invoice", [{
            "id": 1,
            "number": False,  # No number yet (draft)
            "name": False,
            "type": "out_invoice",
            "state": "draft",
            "date_invoice": "2024-01-15",
            "date_due": "2024-02-15",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "reference": "",
            "comment": "",
            "invoice_line_ids": [100],
            "company_id": [1, "Company"],
        }])

        invoices = client.get_invoices(
            date(2024, 1, 1), date(2024, 3, 31), state="all"
        )

        # Should have empty name, not crash
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["name"], "")


class TestSpecialCharactersAndUnicode(unittest.TestCase):
    """Test handling of special characters and unicode in field values."""

    def test_unicode_partner_name(self):
        """Test partner with unicode characters in name."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("res.partner", [
            "id", "name", "vat", "street", "street2", "city", "zip",
            "country_id", "email", "phone", "commercial_partner_id",
            "company_registry", "state_id", "is_company", "parent_id"
        ])
        client.set_mock_data("res.partner", [{
            "id": 10,
            "name": "Société Générale — François & Müller GmbH",
            "vat": "DE123456789",
            "street": "Königstraße 42",
            "street2": "Büro №5",
            "city": "Düsseldorf",
            "zip": "40212",
            "country_id": [54, "Germany"],
            "email": "contact@société.de",
            "phone": "+49 211 123456",
            "commercial_partner_id": [10, "Société"],
            "company_registry": "",
            "state_id": False,
            "is_company": True,
            "parent_id": False,
        }])

        partner = client.get_partner(10)

        self.assertEqual(partner["name"], "Société Générale — François & Müller GmbH")
        self.assertEqual(partner["street"], "Königstraße 42")
        self.assertEqual(partner["city"], "Düsseldorf")

    def test_html_in_narration(self):
        """Test invoice with HTML content in narration field."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "<p>Terms &amp; Conditions:</p><ul><li>Payment within 30 days</li></ul>",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        # Should preserve HTML content
        self.assertIn("<p>", invoices[0]["narration"])
        self.assertIn("&amp;", invoices[0]["narration"])

    def test_special_chars_in_invoice_number(self):
        """Test invoice number with special characters."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        # Vendor bills often have weird reference numbers
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "BILL/2024/0001",
            "move_type": "in_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Vendor"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "VND/2024/001-A (rev.2)",  # Vendor's weird reference
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(invoices[0]["ref"], "VND/2024/001-A (rev.2)")


class TestNegativeAmountsAndCredits(unittest.TestCase):
    """Test handling of negative amounts and credit notes."""

    def test_credit_note_amounts(self):
        """Test credit note with negative/positive amounts."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        # Credit notes may have positive or negative amounts depending on Odoo config
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "RINV/2024/0001",
            "move_type": "out_refund",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,  # Positive in Odoo
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [100],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(invoices[0]["move_type"], "out_refund")
        # Amounts are positive in Odoo, UBL generator handles sign

    def test_line_with_discount(self):
        """Test invoice line with discount."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Product with discount",
            "quantity": 10.0,
            "price_unit": 100.0,
            "price_subtotal": 800.0,  # After 20% discount
            "price_total": 968.0,
            "discount": 20.0,  # 20% discount
            "product_id": [1, "Product"],
            "product_uom_id": [1, "Units"],
            "tax_ids": [1],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        self.assertEqual(lines[0]["discount"], 20.0)
        self.assertEqual(lines[0]["price_subtotal"], 800.0)

    def test_negative_line_quantity(self):
        """Test invoice line with negative quantity (return)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Returned items",
            "quantity": -5.0,  # Negative quantity
            "price_unit": 100.0,
            "price_subtotal": -500.0,
            "price_total": -605.0,
            "discount": 0.0,
            "product_id": [1, "Product"],
            "product_uom_id": [1, "Units"],
            "tax_ids": [1],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        self.assertEqual(lines[0]["quantity"], -5.0)


class TestZeroAndEmptyLines(unittest.TestCase):
    """Test handling of zero-amount and display-only lines."""

    def test_section_header_line(self):
        """Test that section header lines (quantity=0) are handled."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [
            {
                "id": 100,
                "name": "--- Services ---",  # Section header
                "quantity": 0,  # Display only
                "price_unit": 0,
                "price_subtotal": 0,
                "price_total": 0,
                "discount": 0,
                "product_id": False,
                "product_uom_id": False,
                "tax_ids": [],
                "move_id": [1, "INV/2024/0001"],
            },
            {
                "id": 101,
                "name": "Consulting",
                "quantity": 10.0,
                "price_unit": 100.0,
                "price_subtotal": 1000.0,
                "price_total": 1210.0,
                "discount": 0,
                "product_id": [1, "Consulting"],
                "product_uom_id": [1, "Hours"],
                "tax_ids": [1],
                "move_id": [1, "INV/2024/0001"],
            },
        ])

        lines = client.get_invoice_lines([100, 101])

        # Section headers should be filtered out (quantity=0, no product)
        # Only actual product lines should remain
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["name"], "Consulting")

    def test_note_line(self):
        """Test that note lines are filtered out."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [
            {
                "id": 100,
                "name": "Note: Please pay within 30 days",
                "quantity": 0,
                "price_unit": 0,
                "price_subtotal": 0,
                "price_total": 0,
                "discount": 0,
                "product_id": False,
                "product_uom_id": False,
                "tax_ids": [],
                "move_id": [1, "INV/2024/0001"],
            },
        ])

        lines = client.get_invoice_lines([100])

        # Note lines should be filtered out
        self.assertEqual(len(lines), 0)


class TestTaxEdgeCases(unittest.TestCase):
    """Test tax-related edge cases."""

    def test_tax_with_none_amount(self):
        """Test tax where amount is None (happens with fixed taxes)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.tax", [
            "id", "name", "amount", "amount_type", "type_tax_use", "description"
        ])
        client.set_mock_data("account.tax", [{
            "id": 1,
            "name": "Eco Tax",
            "amount": None,  # Fixed amount tax without percentage
            "amount_type": "fixed",
            "type_tax_use": "sale",
            "description": False,
        }])

        taxes = client.get_taxes([1])

        # Amount should be normalized to 0.0
        self.assertEqual(taxes[0]["amount"], 0.0)
        # Description should be normalized to name
        self.assertEqual(taxes[0]["description"], "Eco Tax")

    def test_tax_with_zero_amount(self):
        """Test zero-rate tax (exempt)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.tax", [
            "id", "name", "amount", "amount_type", "type_tax_use", "description"
        ])
        client.set_mock_data("account.tax", [{
            "id": 1,
            "name": "VAT 0% (Exempt)",
            "amount": 0.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "description": "0%",
        }])

        taxes = client.get_taxes([1])

        self.assertEqual(taxes[0]["amount"], 0.0)

    def test_multiple_taxes_on_line(self):
        """Test line with multiple taxes."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Product with multiple taxes",
            "quantity": 1.0,
            "price_unit": 100.0,
            "price_subtotal": 100.0,
            "price_total": 126.0,  # VAT 21% + Eco 5%
            "discount": 0,
            "product_id": [1, "Product"],
            "product_uom_id": [1, "Units"],
            "tax_ids": [1, 2, 3],  # Multiple taxes
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        self.assertEqual(len(lines[0]["tax_ids"]), 3)


class TestBankStatementEdgeCases(unittest.TestCase):
    """Test bank statement edge cases."""

    def test_statement_line_with_no_partner(self):
        """Test bank transaction without identified partner."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.bank.statement.line", [
            "id", "name", "date", "journal_id", "amount",
            "payment_ref", "partner_id"
        ])
        client.set_mock_data("account.bank.statement.line", [{
            "id": 1,
            "name": "Unknown payment",
            "date": "2024-01-15",
            "journal_id": [1, "Bank"],
            "amount": 500.0,
            "payment_ref": "TXN-001",
            "partner_id": False,  # No partner identified
        }])

        lines = client.get_bank_statement_lines(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(lines[0]["partner_id"], False)

    def test_statement_line_negative_amount(self):
        """Test bank transaction with negative amount (outgoing)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.bank.statement.line", [
            "id", "name", "date", "journal_id", "amount",
            "payment_ref", "partner_id"
        ])
        client.set_mock_data("account.bank.statement.line", [{
            "id": 1,
            "name": "Supplier payment",
            "date": "2024-01-15",
            "journal_id": [1, "Bank"],
            "amount": -1500.0,  # Outgoing payment
            "payment_ref": "PAY-001",
            "partner_id": [20, "Supplier"],
        }])

        lines = client.get_bank_statement_lines(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(lines[0]["amount"], -1500.0)


class TestEmptyResults(unittest.TestCase):
    """Test handling of empty result sets."""

    def test_no_invoices_found(self):
        """Test when no invoices match the criteria."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date"
        ])
        client.set_mock_data("account.move", [])  # No invoices

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(invoices, [])

    def test_empty_line_ids(self):
        """Test fetching lines with empty ID list."""
        client = MockOdooClient("17.0")

        lines = client.get_invoice_lines([])

        self.assertEqual(lines, [])

    def test_empty_tax_ids(self):
        """Test fetching taxes with empty ID list."""
        client = MockOdooClient("17.0")

        taxes = client.get_taxes([])

        self.assertEqual(taxes, [])

    def test_empty_product_ids(self):
        """Test fetching products with empty ID list."""
        client = MockOdooClient("17.0")

        products = client.get_products([])

        self.assertEqual(products, [])


class TestLargeDatasets(unittest.TestCase):
    """Test handling of large result sets."""

    def test_many_invoices(self):
        """Test fetching many invoices."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])

        # Generate 1000 invoices
        invoices = []
        for i in range(1000):
            invoices.append({
                "id": i + 1,
                "name": f"INV/2024/{i+1:04d}",
                "move_type": "out_invoice",
                "state": "posted",
                "invoice_date": "2024-01-15",
                "invoice_date_due": "2024-02-15",
                "partner_id": [10, "Customer"],
                "currency_id": [1, "EUR"],
                "amount_untaxed": 1000.0,
                "amount_tax": 210.0,
                "amount_total": 1210.0,
                "payment_reference": "",
                "narration": "",
                "invoice_line_ids": [100 + i],
                "company_id": [1, "Company"],
                "ref": "",
            })
        client.set_mock_data("account.move", invoices)

        result = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(len(result), 1000)

    def test_many_line_ids(self):
        """Test fetching many invoice lines at once."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])

        # Generate 500 lines
        lines = []
        for i in range(500):
            lines.append({
                "id": i + 1,
                "name": f"Line {i+1}",
                "quantity": 1.0,
                "price_unit": 100.0,
                "price_subtotal": 100.0,
                "price_total": 121.0,
                "discount": 0,
                "product_id": [1, "Product"],
                "product_uom_id": [1, "Units"],
                "tax_ids": [1],
                "move_id": [1, "INV/2024/0001"],
            })
        client.set_mock_data("account.move.line", lines)

        line_ids = list(range(1, 501))
        result = client.get_invoice_lines(line_ids)

        self.assertEqual(len(result), 500)


class TestCompanyRetrieval(unittest.TestCase):
    """Test company data retrieval edge cases."""

    def test_company_without_bank_account(self):
        """Test company without configured bank account."""
        client = MockOdooClient("17.0")

        # Mock the execute method for this specific test
        def mock_execute(model, method, *args, **kwargs):
            if model == "res.users" and method == "search_read":
                return [{"id": 1, "company_id": [1, "My Company"]}]
            if model == "res.company" and method == "read":
                return [{
                    "id": 1,
                    "name": "My Company",
                    "vat": "BE0123456789",
                    "street": "Main Street 1",
                    "city": "Brussels",
                    "zip": "1000",
                    "country_id": [21, "Belgium"],
                    "partner_id": [1, "My Company"],
                    "currency_id": [1, "EUR"],
                }]
            if model == "res.partner.bank" and method == "search_read":
                return []  # No bank accounts
            if method == "fields_get":
                return {}
            return []

        client.execute = mock_execute
        client._available_fields_cache = {}

        company = client.get_company()

        self.assertEqual(company["name"], "My Company")
        self.assertNotIn("bank_account", company)


class TestVATFormatting(unittest.TestCase):
    """Test VAT number handling edge cases."""

    def test_vat_without_country_prefix(self):
        """Test VAT number without country prefix."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("res.partner", [
            "id", "name", "vat", "street", "city", "zip", "country_id",
            "email", "phone", "commercial_partner_id", "company_registry"
        ])
        client.set_mock_data("res.partner", [{
            "id": 10,
            "name": "Test Partner",
            "vat": "0123456789",  # No country prefix
            "street": "Main Street",
            "city": "Brussels",
            "zip": "1000",
            "country_id": [21, "Belgium"],
            "email": "",
            "phone": "",
            "commercial_partner_id": [10, "Test"],
            "company_registry": "",
        }])

        partner = client.get_partner(10)

        # VAT should be returned as-is, UBL generator handles normalization
        self.assertEqual(partner["vat"], "0123456789")

    def test_vat_with_spaces(self):
        """Test VAT number with spaces."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("res.partner", [
            "id", "name", "vat", "country_id"
        ])
        client.set_mock_data("res.partner", [{
            "id": 10,
            "name": "Test Partner",
            "vat": "BE 0123 456 789",  # With spaces
            "country_id": [21, "Belgium"],
        }])

        partner = client.get_partner(10)

        self.assertEqual(partner["vat"], "BE 0123 456 789")


class TestDateHandling(unittest.TestCase):
    """Test date handling edge cases."""

    def test_invoice_date_as_string(self):
        """Test that invoice dates are handled as strings."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",  # String format
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        # Date should remain as string
        self.assertIsInstance(invoices[0]["invoice_date"], str)
        self.assertEqual(invoices[0]["invoice_date"], "2024-01-15")


class TestUBLGeneratorEdgeCases(unittest.TestCase):
    """Test UBL generator with edge cases."""

    def setUp(self):
        try:
            from ubl_generator import UBLGenerator
            self.UBLGenerator = UBLGenerator
        except ImportError:
            self.skipTest("UBLGenerator not available")

    def _get_minimal_company(self):
        """Company with minimal data."""
        return {
            "id": 1,
            "name": "Test Company",
            "vat": "",  # No VAT
            "street": "",
            "city": "",
            "zip": "",
            "country_id": False,  # No country
            "bank_account": "",  # No bank
        }

    def _get_minimal_invoice(self):
        """Invoice with minimal data."""
        return {
            "id": 1,
            "name": "INV/2024/0001",
            "_ubl_number": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": False,  # No due date
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 0.0,  # No tax
            "amount_total": 1000.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }

    def _get_minimal_partner(self):
        """Partner with minimal data."""
        return {
            "id": 10,
            "name": "Test Customer",
            "vat": "",  # No VAT
            "street": "",
            "city": "",
            "zip": "",
            "country_id": False,  # No country
            "email": "",  # No email
        }

    def _get_minimal_line(self):
        """Line with minimal data."""
        return {
            "id": 100,
            "name": "Service",
            "quantity": 1.0,
            "price_unit": 1000.0,
            "price_subtotal": 1000.0,
            "price_total": 1000.0,
            "discount": 0,
            "product_id": False,  # No product
            "product_uom_id": False,
            "tax_ids": [],  # No taxes
            "move_id": [1, "INV/2024/0001"],
        }

    def test_generate_with_minimal_data(self):
        """Test UBL generation with absolute minimal data."""
        company = self._get_minimal_company()
        invoice = self._get_minimal_invoice()
        partner = self._get_minimal_partner()
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        # Should generate valid XML without crashing
        self.assertIsInstance(xml_content, bytes)
        self.assertIn(b"Invoice", xml_content)

    def test_partner_without_vat_or_email(self):
        """Test customer party without VAT or email (uses name fallback)."""
        company = {
            "id": 1,
            "name": "Seller Co",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
        }
        invoice = self._get_minimal_invoice()
        partner = {
            "id": 10,
            "name": "Anonymous Customer",
            "vat": "",
            "email": "",
            "country_id": [21, "Belgium"],
        }
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Should have EndpointID with scheme 0190 (unregistered)
        self.assertIn('schemeID="0190"', xml_str)
        # Should use sanitized name
        self.assertIn("ANONYMOUSCUSTOMER", xml_str)

    def test_partner_with_email_no_vat(self):
        """Test customer with email but no VAT (uses email scheme)."""
        company = {
            "id": 1,
            "name": "Seller Co",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
        }
        invoice = self._get_minimal_invoice()
        partner = {
            "id": 10,
            "name": "Email Customer",
            "vat": "",
            "email": "customer@example.com",
            "country_id": [21, "Belgium"],
        }
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Should have EndpointID with scheme 0195 (email)
        self.assertIn('schemeID="0195"', xml_str)
        self.assertIn("customer@example.com", xml_str)

    def test_vat_normalization(self):
        """Test VAT number normalization with country prefix."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "0123456789",  # No country prefix
            "country_id": [21, "Belgium"],
        }
        invoice = self._get_minimal_invoice()
        partner = {
            "id": 10,
            "name": "Buyer",
            "vat": "123456789",  # No country prefix
            "country_id": [54, "Germany"],
        }
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Belgian VAT should have BE prefix
        self.assertIn("BE0123456789", xml_str)
        # German VAT should have DE prefix
        self.assertIn("DE123456789", xml_str)

    def test_zero_amount_invoice(self):
        """Test invoice with zero amounts (free sample)."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
        }
        invoice = {
            **self._get_minimal_invoice(),
            "amount_untaxed": 0.0,
            "amount_tax": 0.0,
            "amount_total": 0.0,
        }
        partner = self._get_minimal_partner()
        lines = [{
            "id": 100,
            "name": "Free sample",
            "quantity": 1.0,
            "price_unit": 0.0,
            "price_subtotal": 0.0,
            "price_total": 0.0,
            "discount": 100.0,  # 100% discount
            "product_id": False,
            "product_uom_id": False,
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        # Should generate valid XML
        self.assertIsInstance(xml_content, bytes)

    def test_html_in_narration_stripped(self):
        """Test that HTML is stripped from narration."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
        }
        invoice = {
            **self._get_minimal_invoice(),
            "narration": "<p>Payment <strong>terms</strong>:</p><ul><li>30 days</li></ul>",
        }
        partner = self._get_minimal_partner()
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # HTML tags should be stripped
        self.assertNotIn("<p>", xml_str)
        self.assertNotIn("<strong>", xml_str)
        # But text content should remain
        self.assertIn("Payment", xml_str)
        self.assertIn("terms", xml_str)

    def test_invoice_with_no_lines(self):
        """Test invoice with empty lines array."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
        }
        invoice = self._get_minimal_invoice()
        partner = self._get_minimal_partner()
        lines = []  # No lines

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Should have a dummy line (Peppol requires at least one)
        self.assertIn("InvoiceLine", xml_str)
        self.assertIn("No items", xml_str)

    def test_invoice_with_only_zero_quantity_lines(self):
        """Test invoice where all lines have zero quantity."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
        }
        invoice = self._get_minimal_invoice()
        partner = self._get_minimal_partner()
        lines = [{
            "id": 100,
            "name": "Section header",
            "quantity": 0,
            "price_unit": 0,
            "price_subtotal": 0,
            "price_total": 0,
            "discount": 0,
            "product_id": False,
            "product_uom_id": False,
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Should have a dummy line since all real lines are skipped
        self.assertIn("No items", xml_str)

    def test_country_code_detection_non_english(self):
        """Test country code detection with non-English names."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "België"],  # Dutch name for Belgium
        }
        invoice = self._get_minimal_invoice()
        partner = {
            "id": 10,
            "name": "Dutch Customer",
            "vat": "",
            "country_id": [165, "Nederland"],  # Dutch name for Netherlands
        }
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Should detect BE from België and NL from Nederland
        self.assertIn("<cbc:IdentificationCode>BE</cbc:IdentificationCode>", xml_str)
        self.assertIn("<cbc:IdentificationCode>NL</cbc:IdentificationCode>", xml_str)

    def test_very_long_description_truncation(self):
        """Test that very long names are handled."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
        }
        invoice = self._get_minimal_invoice()
        # Partner with very long name (potential endpoint ID issue)
        partner = {
            "id": 10,
            "name": "A" * 100,  # 100 character name
            "vat": "",
            "email": "",
            "country_id": [21, "Belgium"],
        }
        lines = [{
            "id": 100,
            "name": "X" * 5000,  # Very long description
            "quantity": 1.0,
            "price_unit": 100.0,
            "price_subtotal": 100.0,
            "price_total": 121.0,
            "discount": 0,
            "product_id": False,
            "product_uom_id": False,
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        # Should generate valid XML without crashing
        self.assertIsInstance(xml_content, bytes)
        # Endpoint ID should be truncated to 35 chars
        xml_str = xml_content.decode('utf-8')
        self.assertIn("A" * 35, xml_str)  # Truncated name

    def test_payment_means_without_iban(self):
        """Test that PaymentMeans uses code 1 when no IBAN."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
            "bank_account": "",  # No IBAN
        }
        invoice = self._get_minimal_invoice()
        partner = self._get_minimal_partner()
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Should use code 1 (not defined) instead of 30 (credit transfer)
        self.assertIn("<cbc:PaymentMeansCode>1</cbc:PaymentMeansCode>", xml_str)
        # Should NOT have PayeeFinancialAccount
        self.assertNotIn("PayeeFinancialAccount", xml_str)

    def test_payment_means_with_iban(self):
        """Test that PaymentMeans uses code 30 with IBAN."""
        company = {
            "id": 1,
            "name": "Seller",
            "vat": "BE0123456789",
            "country_id": [21, "Belgium"],
            "bank_account": "BE12345678901234",  # Has IBAN
        }
        invoice = self._get_minimal_invoice()
        partner = self._get_minimal_partner()
        lines = [self._get_minimal_line()]

        generator = self.UBLGenerator(company)
        xml_content = generator.generate_invoice(
            invoice, partner, lines, {}, {}
        )

        xml_str = xml_content.decode('utf-8')
        # Should use code 30 (credit transfer)
        self.assertIn("<cbc:PaymentMeansCode>30</cbc:PaymentMeansCode>", xml_str)
        # Should have PayeeFinancialAccount with IBAN
        self.assertIn("PayeeFinancialAccount", xml_str)
        self.assertIn("BE12345678901234", xml_str)


class TestXMLRPCQuirks(unittest.TestCase):
    """Test handling of XML-RPC specific quirks."""

    def test_execute_with_empty_kwargs(self):
        """Test that empty kwargs don't cause issues."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("test.model", ["id", "name"])
        client.set_mock_data("test.model", [{"id": 1, "name": "Test"}])

        # Should not crash with empty domain
        result = client.search_read("test.model", [], ["id", "name"])
        self.assertEqual(len(result), 1)


class TestRealWorldScenarios(unittest.TestCase):
    """Test complete real-world scenarios."""

    def test_vendor_bill_with_duplicate_ref(self):
        """Test handling vendor bills where ref might duplicate name."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        # Vendor bill where Odoo name and vendor ref are different
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "BILL/2024/0001",  # Odoo's internal ref
            "move_type": "in_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Vendor"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "VND-INV-2024-001",  # Vendor's invoice number
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        # For vendor bills, ref (vendor's number) should be preserved
        self.assertEqual(invoices[0]["ref"], "VND-INV-2024-001")

    def test_multi_currency_invoice(self):
        """Test invoice in non-EUR currency."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "US Customer"],
            "currency_id": [2, "USD"],  # USD currency
            "amount_untaxed": 1000.0,
            "amount_tax": 0.0,
            "amount_total": 1000.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        # Currency should be USD
        self.assertEqual(invoices[0]["currency_id"], [2, "USD"])


class TestDecimalPrecisionIssues(unittest.TestCase):
    """Test handling of decimal precision issues common in Odoo."""

    def test_floating_point_rounding(self):
        """Test that floating point amounts don't cause precision issues."""
        # Classic floating point issue: 0.1 + 0.2 != 0.3
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Product",
            "quantity": 3.0,
            "price_unit": 0.1,  # Classic float issue
            "price_subtotal": 0.30000000000000004,  # Floating point artifact
            "price_total": 0.30000000000000004,
            "discount": 0,
            "product_id": False,
            "product_uom_id": False,
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        # Should not crash - data passes through
        self.assertIsNotNone(lines[0]["price_subtotal"])

    def test_very_large_amounts(self):
        """Test handling of very large monetary amounts."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Big Corp"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 999999999.99,  # 1 billion almost
            "amount_tax": 209999999.9979,
            "amount_total": 1209999999.9879,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(invoices[0]["amount_total"], 1209999999.9879)

    def test_four_decimal_precision(self):
        """Test handling of 4-decimal precision (common in some countries)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Bulk item",
            "quantity": 10000.0,
            "price_unit": 0.0125,  # 4 decimal places
            "price_subtotal": 125.0,
            "price_total": 151.25,
            "discount": 0,
            "product_id": False,
            "product_uom_id": False,
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        self.assertEqual(lines[0]["price_unit"], 0.0125)


class TestXMLSpecialCharacters(unittest.TestCase):
    """Test handling of characters that need XML escaping."""

    def test_ampersand_in_partner_name(self):
        """Test partner name with ampersand (needs XML escaping)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("res.partner", [
            "id", "name", "vat", "street", "street2", "city", "zip",
            "country_id", "email", "phone", "commercial_partner_id",
            "company_registry", "state_id", "is_company", "parent_id"
        ])
        client.set_mock_data("res.partner", [{
            "id": 10,
            "name": "Johnson & Johnson Ltd",  # Ampersand
            "vat": "BE0123456789",
            "street": "123 Main St",
            "street2": False,
            "city": "Brussels",
            "zip": "1000",
            "country_id": [21, "Belgium"],
            "email": "info@jj.com",
            "phone": "+32 2 123 4567",
            "commercial_partner_id": [10, "Johnson & Johnson Ltd"],
            "company_registry": False,
            "state_id": False,
            "is_company": True,
            "parent_id": False,
        }])

        partner = client.get_partner(10)

        self.assertEqual(partner["name"], "Johnson & Johnson Ltd")

    def test_quotes_in_product_name(self):
        """Test product with quotes in name."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": '10" Monitor Stand',  # Quotes in name
            "quantity": 1.0,
            "price_unit": 50.0,
            "price_subtotal": 50.0,
            "price_total": 60.5,
            "discount": 0,
            "product_id": [1, '10" Monitor Stand'],
            "product_uom_id": [1, "Units"],
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        self.assertEqual(lines[0]["name"], '10" Monitor Stand')

    def test_less_than_greater_than_in_description(self):
        """Test description with < and > characters."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Size: <Large>",  # < and > characters
            "quantity": 1.0,
            "price_unit": 50.0,
            "price_subtotal": 50.0,
            "price_total": 60.5,
            "discount": 0,
            "product_id": False,
            "product_uom_id": False,
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        self.assertEqual(lines[0]["name"], "Size: <Large>")


class TestMalformedOdooData(unittest.TestCase):
    """Test handling of malformed or unexpected data from Odoo."""

    def test_currency_id_as_false(self):
        """Test invoice with False currency_id."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": [10, "Customer"],
            "currency_id": False,  # Missing currency
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        # Should not crash, currency is False
        self.assertEqual(invoices[0]["currency_id"], False)

    def test_partner_id_as_integer(self):
        """Test partner_id returned as plain integer (some versions)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-15",
            "invoice_date_due": "2024-02-15",
            "partner_id": 10,  # Integer, not list
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        # Should handle integer partner_id
        self.assertEqual(invoices[0]["partner_id"], 10)

    def test_empty_string_amounts(self):
        """Test invoice with empty string amounts (shouldn't happen, but...)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move.line", [
            "id", "name", "quantity", "price_unit", "price_subtotal",
            "price_total", "discount", "product_id", "product_uom_id",
            "tax_ids", "move_id"
        ])
        client.set_mock_data("account.move.line", [{
            "id": 100,
            "name": "Weird line",
            "quantity": 1.0,
            "price_unit": 0,  # Zero instead of empty
            "price_subtotal": 0,
            "price_total": 0,
            "discount": 0,
            "product_id": False,
            "product_uom_id": False,
            "tax_ids": [],
            "move_id": [1, "INV/2024/0001"],
        }])

        lines = client.get_invoice_lines([100])

        # Line might be filtered out due to quantity filtering
        # but should not crash
        self.assertIsInstance(lines, list)


class TestDateEdgeCases(unittest.TestCase):
    """Test date handling edge cases."""

    def test_invoice_date_at_boundary(self):
        """Test invoices at date range boundaries."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-01-01",  # First day of range
            "invoice_date_due": "2024-01-31",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }, {
            "id": 2,
            "name": "INV/2024/0002",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-03-31",  # Last day of range
            "invoice_date_due": "2024-04-30",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 500.0,
            "amount_tax": 105.0,
            "amount_total": 605.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 1, 1), date(2024, 3, 31))

        self.assertEqual(len(invoices), 2)

    def test_leap_year_date(self):
        """Test invoice on February 29 (leap year)."""
        client = MockOdooClient("17.0")
        client.set_mock_fields("account.move", [
            "id", "name", "move_type", "state", "invoice_date",
            "invoice_date_due", "partner_id", "currency_id",
            "amount_untaxed", "amount_tax", "amount_total",
            "payment_reference", "narration", "invoice_line_ids",
            "company_id", "ref"
        ])
        client.set_mock_data("account.move", [{
            "id": 1,
            "name": "INV/2024/0229",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2024-02-29",  # Leap year date
            "invoice_date_due": "2024-03-29",
            "partner_id": [10, "Customer"],
            "currency_id": [1, "EUR"],
            "amount_untaxed": 1000.0,
            "amount_tax": 210.0,
            "amount_total": 1210.0,
            "payment_reference": "",
            "narration": "",
            "invoice_line_ids": [],
            "company_id": [1, "Company"],
            "ref": "",
        }])

        invoices = client.get_invoices(date(2024, 2, 1), date(2024, 2, 29))

        self.assertEqual(invoices[0]["invoice_date"], "2024-02-29")


class TestVersionEdgeCases(unittest.TestCase):
    """Test version detection edge cases."""

    def test_saas_version_with_tilde(self):
        """Test parsing SaaS version with tilde."""
        from odoo_client import OdooVersion

        version = OdooVersion("saas~17.4")

        self.assertEqual(version.major, 17)
        self.assertEqual(version.minor, 4)

    def test_version_with_build_number(self):
        """Test parsing version with build number."""
        from odoo_client import OdooVersion

        version = OdooVersion("17.0.20240115")

        self.assertEqual(version.major, 17)
        self.assertEqual(version.minor, 0)

    def test_enterprise_version_string(self):
        """Test parsing Enterprise version string."""
        from odoo_client import OdooVersion

        version = OdooVersion("17.0e")  # Enterprise suffix

        self.assertEqual(version.major, 17)
        self.assertEqual(version.minor, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
