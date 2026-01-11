# -*- coding: utf-8 -*-
"""Peppol BIS Billing 3.0 UBL XML generator."""

from datetime import date
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET


# UBL 2.1 / Peppol BIS 3.0 namespaces
NAMESPACES = {
    "": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cec": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}

CREDIT_NOTE_NS = {
    "": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cec": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}

# Country code to currency mapping (common)
COUNTRY_CURRENCY = {
    "BE": "EUR",
    "NL": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "ES": "EUR",
    "IT": "EUR",
    "AT": "EUR",
    "PT": "EUR",
    "FI": "EUR",
    "IE": "EUR",
    "LU": "EUR",
    "GB": "GBP",
    "US": "USD",
    "CH": "CHF",
}


class UBLGenerator:
    """Generator for Peppol BIS Billing 3.0 UBL XML documents."""

    def __init__(self, company: dict):
        """Initialize generator with company info.

        Args:
            company: Company dictionary from Odoo
        """
        self.company = company

    def generate_invoice(
        self,
        invoice: dict,
        partner: dict,
        lines: list[dict],
        taxes: dict[int, dict],
        products: dict[int, dict],
    ) -> bytes:
        """Generate UBL XML for an invoice.

        Args:
            invoice: Invoice dictionary from Odoo
            partner: Partner dictionary
            lines: List of invoice line dictionaries
            taxes: Dict mapping tax ID to tax info
            products: Dict mapping product ID to product info

        Returns:
            UTF-8 encoded XML bytes
        """
        is_credit_note = invoice["move_type"] in ("out_refund", "in_refund")
        ns = CREDIT_NOTE_NS if is_credit_note else NAMESPACES

        # Register namespaces
        for prefix, uri in ns.items():
            if prefix:
                ET.register_namespace(prefix, uri)
            else:
                ET.register_namespace("", uri)

        # Create root element
        if is_credit_note:
            root = ET.Element(
                "CreditNote",
                xmlns=ns[""],
            )
        else:
            root = ET.Element(
                "Invoice",
                xmlns=ns[""],
            )

        # Add namespace declarations as attributes
        root.set("xmlns:cac", ns["cac"])
        root.set("xmlns:cbc", ns["cbc"])

        # Customization and Profile ID (required for Peppol)
        self._add_element(
            root, "cbc:CustomizationID",
            "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
        )
        self._add_element(
            root, "cbc:ProfileID",
            "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
        )

        # Invoice number and dates
        self._add_element(root, "cbc:ID", invoice["name"])

        invoice_date = invoice.get("invoice_date")
        if isinstance(invoice_date, str):
            self._add_element(root, "cbc:IssueDate", invoice_date)
        elif invoice_date:
            self._add_element(root, "cbc:IssueDate", invoice_date.isoformat())

        due_date = invoice.get("invoice_date_due")
        if due_date:
            if isinstance(due_date, str):
                self._add_element(root, "cbc:DueDate", due_date)
            else:
                self._add_element(root, "cbc:DueDate", due_date.isoformat())

        # Invoice type code
        if is_credit_note:
            self._add_element(root, "cbc:CreditNoteTypeCode", "381")
        else:
            self._add_element(root, "cbc:InvoiceTypeCode", "380")

        # Notes
        if invoice.get("narration"):
            # Strip HTML tags if present
            note = invoice["narration"]
            if "<" in note:
                import re
                note = re.sub(r"<[^>]+>", "", note)
            self._add_element(root, "cbc:Note", note)

        # Document currency
        currency = "EUR"
        if invoice.get("currency_id"):
            currency_data = invoice["currency_id"]
            if isinstance(currency_data, (list, tuple)) and len(currency_data) > 1:
                currency = currency_data[1]  # [id, name]
            elif isinstance(currency_data, str):
                currency = currency_data
        self._add_element(root, "cbc:DocumentCurrencyCode", currency)

        # Buyer reference (payment reference)
        if invoice.get("payment_reference"):
            self._add_element(root, "cbc:BuyerReference", invoice["payment_reference"])
        elif invoice.get("ref"):
            self._add_element(root, "cbc:BuyerReference", invoice["ref"])

        # Supplier (AccountingSupplierParty)
        self._add_supplier_party(root, ns)

        # Customer (AccountingCustomerParty)
        self._add_customer_party(root, partner, ns)

        # Payment means
        self._add_payment_means(root, invoice, ns)

        # Tax totals
        self._add_tax_total(root, invoice, lines, taxes, currency, ns)

        # Legal monetary total
        self._add_monetary_total(root, invoice, currency, is_credit_note, ns)

        # Invoice lines
        for idx, line in enumerate(lines, start=1):
            # Skip lines without price (section headers, notes, etc.)
            if line.get("price_subtotal", 0) == 0 and line.get("quantity", 0) == 0:
                continue
            self._add_invoice_line(
                root, line, idx, taxes, products, currency, is_credit_note, ns
            )

        # Generate XML with declaration
        xml_str = ET.tostring(root, encoding="unicode")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'.encode("utf-8")

    def _add_element(
        self, parent: ET.Element, tag: str, text: str | None = None
    ) -> ET.Element:
        """Add a child element with optional text."""
        elem = ET.SubElement(parent, tag)
        if text is not None:
            elem.text = str(text)
        return elem

    def _add_supplier_party(self, root: ET.Element, ns: dict) -> None:
        """Add AccountingSupplierParty element."""
        supplier = ET.SubElement(root, "cac:AccountingSupplierParty")
        party = ET.SubElement(supplier, "cac:Party")

        # Endpoint ID (VAT or company registry)
        if self.company.get("vat"):
            endpoint = self._add_element(party, "cbc:EndpointID", self.company["vat"])
            endpoint.set("schemeID", "0208")  # Belgian VAT

        # Party identification
        if self.company.get("vat"):
            party_id = ET.SubElement(party, "cac:PartyIdentification")
            self._add_element(party_id, "cbc:ID", self.company["vat"])

        # Party name
        party_name = ET.SubElement(party, "cac:PartyName")
        self._add_element(party_name, "cbc:Name", self.company.get("name", ""))

        # Postal address
        address = ET.SubElement(party, "cac:PostalAddress")
        if self.company.get("street"):
            self._add_element(address, "cbc:StreetName", self.company["street"])
        if self.company.get("city"):
            self._add_element(address, "cbc:CityName", self.company["city"])
        if self.company.get("zip"):
            self._add_element(address, "cbc:PostalZone", self.company["zip"])

        country = ET.SubElement(address, "cac:Country")
        country_code = "BE"  # Default
        if self.company.get("country_id"):
            country_data = self.company["country_id"]
            if isinstance(country_data, (list, tuple)) and len(country_data) > 1:
                # Try to extract country code from name
                country_name = country_data[1]
                if "Belgium" in country_name or "België" in country_name:
                    country_code = "BE"
                elif "Netherlands" in country_name:
                    country_code = "NL"
                # Add more as needed
        self._add_element(country, "cbc:IdentificationCode", country_code)

        # Tax scheme (VAT)
        if self.company.get("vat"):
            tax_scheme = ET.SubElement(party, "cac:PartyTaxScheme")
            self._add_element(tax_scheme, "cbc:CompanyID", self.company["vat"])
            scheme = ET.SubElement(tax_scheme, "cac:TaxScheme")
            self._add_element(scheme, "cbc:ID", "VAT")

        # Legal entity
        legal = ET.SubElement(party, "cac:PartyLegalEntity")
        self._add_element(legal, "cbc:RegistrationName", self.company.get("name", ""))
        if self.company.get("company_registry"):
            self._add_element(
                legal, "cbc:CompanyID", self.company["company_registry"]
            )

    def _add_customer_party(
        self, root: ET.Element, partner: dict, ns: dict
    ) -> None:
        """Add AccountingCustomerParty element."""
        customer = ET.SubElement(root, "cac:AccountingCustomerParty")
        party = ET.SubElement(customer, "cac:Party")

        # Endpoint ID
        if partner.get("vat"):
            endpoint = self._add_element(party, "cbc:EndpointID", partner["vat"])
            endpoint.set("schemeID", "0208")

        # Party identification
        if partner.get("vat"):
            party_id = ET.SubElement(party, "cac:PartyIdentification")
            self._add_element(party_id, "cbc:ID", partner["vat"])

        # Party name
        party_name = ET.SubElement(party, "cac:PartyName")
        self._add_element(party_name, "cbc:Name", partner.get("name", ""))

        # Postal address
        address = ET.SubElement(party, "cac:PostalAddress")
        if partner.get("street"):
            self._add_element(address, "cbc:StreetName", partner["street"])
        if partner.get("city"):
            self._add_element(address, "cbc:CityName", partner["city"])
        if partner.get("zip"):
            self._add_element(address, "cbc:PostalZone", partner["zip"])

        country = ET.SubElement(address, "cac:Country")
        country_code = "BE"
        if partner.get("country_id"):
            country_data = partner["country_id"]
            if isinstance(country_data, (list, tuple)) and len(country_data) > 1:
                country_name = country_data[1]
                if "Belgium" in country_name or "België" in country_name:
                    country_code = "BE"
                elif "Netherlands" in country_name:
                    country_code = "NL"
        self._add_element(country, "cbc:IdentificationCode", country_code)

        # Tax scheme
        if partner.get("vat"):
            tax_scheme = ET.SubElement(party, "cac:PartyTaxScheme")
            self._add_element(tax_scheme, "cbc:CompanyID", partner["vat"])
            scheme = ET.SubElement(tax_scheme, "cac:TaxScheme")
            self._add_element(scheme, "cbc:ID", "VAT")

        # Legal entity
        legal = ET.SubElement(party, "cac:PartyLegalEntity")
        self._add_element(legal, "cbc:RegistrationName", partner.get("name", ""))

    def _add_payment_means(
        self, root: ET.Element, invoice: dict, ns: dict
    ) -> None:
        """Add PaymentMeans element."""
        payment = ET.SubElement(root, "cac:PaymentMeans")
        # 30 = Credit transfer
        self._add_element(payment, "cbc:PaymentMeansCode", "30")

        if invoice.get("payment_reference"):
            self._add_element(
                payment, "cbc:PaymentID", invoice["payment_reference"]
            )

    def _add_tax_total(
        self,
        root: ET.Element,
        invoice: dict,
        lines: list[dict],
        taxes: dict[int, dict],
        currency: str,
        ns: dict,
    ) -> None:
        """Add TaxTotal element."""
        tax_total = ET.SubElement(root, "cac:TaxTotal")

        tax_amount = self._add_element(
            tax_total, "cbc:TaxAmount",
            f"{invoice.get('amount_tax', 0):.2f}"
        )
        tax_amount.set("currencyID", currency)

        # Group taxes by rate
        tax_groups: dict[float, dict] = {}
        for line in lines:
            line_tax_ids = line.get("tax_ids", [])
            if isinstance(line_tax_ids, (list, tuple)):
                for tax_id in line_tax_ids:
                    if tax_id in taxes:
                        tax_info = taxes[tax_id]
                        rate = tax_info.get("amount", 0)
                        if rate not in tax_groups:
                            tax_groups[rate] = {
                                "taxable": 0,
                                "tax": 0,
                                "name": tax_info.get("name", f"{rate}%"),
                            }
                        tax_groups[rate]["taxable"] += line.get("price_subtotal", 0)

        # Calculate tax amounts
        for rate, group in tax_groups.items():
            group["tax"] = group["taxable"] * rate / 100

        # If no tax groups found, add default
        if not tax_groups:
            tax_groups[0] = {
                "taxable": invoice.get("amount_untaxed", 0),
                "tax": invoice.get("amount_tax", 0),
                "name": "VAT",
            }

        # Add subtotals
        for rate, group in tax_groups.items():
            subtotal = ET.SubElement(tax_total, "cac:TaxSubtotal")

            taxable = self._add_element(
                subtotal, "cbc:TaxableAmount", f"{group['taxable']:.2f}"
            )
            taxable.set("currencyID", currency)

            tax_amt = self._add_element(
                subtotal, "cbc:TaxAmount", f"{group['tax']:.2f}"
            )
            tax_amt.set("currencyID", currency)

            category = ET.SubElement(subtotal, "cac:TaxCategory")
            self._add_element(category, "cbc:ID", "S")  # Standard rate
            self._add_element(category, "cbc:Percent", f"{rate:.2f}")

            scheme = ET.SubElement(category, "cac:TaxScheme")
            self._add_element(scheme, "cbc:ID", "VAT")

    def _add_monetary_total(
        self,
        root: ET.Element,
        invoice: dict,
        currency: str,
        is_credit_note: bool,
        ns: dict,
    ) -> None:
        """Add LegalMonetaryTotal element."""
        monetary = ET.SubElement(root, "cac:LegalMonetaryTotal")

        # Line extension amount (sum of line totals without tax)
        line_ext = self._add_element(
            monetary, "cbc:LineExtensionAmount",
            f"{invoice.get('amount_untaxed', 0):.2f}"
        )
        line_ext.set("currencyID", currency)

        # Tax exclusive amount
        tax_excl = self._add_element(
            monetary, "cbc:TaxExclusiveAmount",
            f"{invoice.get('amount_untaxed', 0):.2f}"
        )
        tax_excl.set("currencyID", currency)

        # Tax inclusive amount
        tax_incl = self._add_element(
            monetary, "cbc:TaxInclusiveAmount",
            f"{invoice.get('amount_total', 0):.2f}"
        )
        tax_incl.set("currencyID", currency)

        # Payable amount
        payable = self._add_element(
            monetary, "cbc:PayableAmount",
            f"{invoice.get('amount_total', 0):.2f}"
        )
        payable.set("currencyID", currency)

    def _add_invoice_line(
        self,
        root: ET.Element,
        line: dict,
        line_number: int,
        taxes: dict[int, dict],
        products: dict[int, dict],
        currency: str,
        is_credit_note: bool,
        ns: dict,
    ) -> None:
        """Add InvoiceLine or CreditNoteLine element."""
        if is_credit_note:
            inv_line = ET.SubElement(root, "cac:CreditNoteLine")
        else:
            inv_line = ET.SubElement(root, "cac:InvoiceLine")

        self._add_element(inv_line, "cbc:ID", str(line_number))

        # Quantity
        quantity = line.get("quantity", 1)
        if is_credit_note:
            qty_elem = self._add_element(
                inv_line, "cbc:CreditedQuantity", f"{quantity:.4f}"
            )
        else:
            qty_elem = self._add_element(
                inv_line, "cbc:InvoicedQuantity", f"{quantity:.4f}"
            )
        qty_elem.set("unitCode", "C62")  # Unit (piece)

        # Line extension amount
        line_amt = self._add_element(
            inv_line, "cbc:LineExtensionAmount",
            f"{line.get('price_subtotal', 0):.2f}"
        )
        line_amt.set("currencyID", currency)

        # Item
        item = ET.SubElement(inv_line, "cac:Item")

        # Description
        description = line.get("name", "")
        if description:
            self._add_element(item, "cbc:Description", description)

        # Product name
        product_name = description
        product_id = line.get("product_id")
        if product_id:
            if isinstance(product_id, (list, tuple)):
                product_id = product_id[0]
            if product_id in products:
                product_name = products[product_id].get("name", description)
        self._add_element(item, "cbc:Name", product_name or "Item")

        # Seller's item identification
        if product_id and product_id in products:
            product = products[product_id]
            if product.get("default_code"):
                seller_id = ET.SubElement(item, "cac:SellersItemIdentification")
                self._add_element(seller_id, "cbc:ID", product["default_code"])

        # Tax category for item
        line_tax_ids = line.get("tax_ids", [])
        tax_rate = 0
        if isinstance(line_tax_ids, (list, tuple)) and line_tax_ids:
            first_tax_id = line_tax_ids[0]
            if first_tax_id in taxes:
                tax_rate = taxes[first_tax_id].get("amount", 0)

        tax_cat = ET.SubElement(item, "cac:ClassifiedTaxCategory")
        self._add_element(tax_cat, "cbc:ID", "S")
        self._add_element(tax_cat, "cbc:Percent", f"{tax_rate:.2f}")
        scheme = ET.SubElement(tax_cat, "cac:TaxScheme")
        self._add_element(scheme, "cbc:ID", "VAT")

        # Price
        price = ET.SubElement(inv_line, "cac:Price")
        price_amt = self._add_element(
            price, "cbc:PriceAmount",
            f"{line.get('price_unit', 0):.4f}"
        )
        price_amt.set("currencyID", currency)

