# -*- coding: utf-8 -*-
"""Peppol BIS Billing 3.0 UBL XML generator."""

import base64
import re
from datetime import date
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET


# UBL 2.1 / Peppol BIS 3.0 namespaces
NS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CREDIT_NOTE = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

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


def _cac(tag: str) -> str:
    """Return tag with CAC namespace in Clark notation."""
    return f"{{{NS_CAC}}}{tag}"


def _cbc(tag: str) -> str:
    """Return tag with CBC namespace in Clark notation."""
    return f"{{{NS_CBC}}}{tag}"


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
        pdf_content: bytes | None = None,
    ) -> bytes:
        """Generate UBL XML for an invoice.

        Args:
            invoice: Invoice dictionary from Odoo
            partner: Partner dictionary
            lines: List of invoice line dictionaries
            taxes: Dict mapping tax ID to tax info
            products: Dict mapping product ID to product info
            pdf_content: Optional PDF bytes to embed in the UBL

        Returns:
            UTF-8 encoded XML bytes
        """
        is_credit_note = invoice["move_type"] in ("out_refund", "in_refund")

        # Register namespaces for clean output
        ET.register_namespace("", NS_CREDIT_NOTE if is_credit_note else NS_INVOICE)
        ET.register_namespace("cac", NS_CAC)
        ET.register_namespace("cbc", NS_CBC)

        # Create root element
        if is_credit_note:
            root = ET.Element(f"{{{NS_CREDIT_NOTE}}}CreditNote")
        else:
            root = ET.Element(f"{{{NS_INVOICE}}}Invoice")

        # Customization and Profile ID (required for Peppol)
        self._add_cbc(
            root, "CustomizationID",
            "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
        )
        self._add_cbc(
            root, "ProfileID",
            "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
        )

        # Invoice number and dates
        invoice_number = invoice.get("_ubl_number") or invoice.get("name") or "UNKNOWN"
        self._add_cbc(root, "ID", invoice_number)

        invoice_date = invoice.get("invoice_date")
        if isinstance(invoice_date, str):
            self._add_cbc(root, "IssueDate", invoice_date)
        elif invoice_date:
            self._add_cbc(root, "IssueDate", invoice_date.isoformat())

        due_date = invoice.get("invoice_date_due")
        if due_date:
            if isinstance(due_date, str):
                self._add_cbc(root, "DueDate", due_date)
            else:
                self._add_cbc(root, "DueDate", due_date.isoformat())

        # Invoice type code
        if is_credit_note:
            self._add_cbc(root, "CreditNoteTypeCode", "381")
        else:
            self._add_cbc(root, "InvoiceTypeCode", "380")

        # Notes
        if invoice.get("narration"):
            note = invoice["narration"]
            if "<" in note:
                note = re.sub(r"<[^>]+>", "", note)
            self._add_cbc(root, "Note", note)

        # Document currency
        currency = self._get_currency(invoice)
        self._add_cbc(root, "DocumentCurrencyCode", currency)

        # Buyer reference (MANDATORY in Peppol - use invoice number as fallback)
        buyer_ref = invoice.get("payment_reference") or invoice.get("ref") or invoice_number
        self._add_cbc(root, "BuyerReference", buyer_ref)

        # Embed PDF as AdditionalDocumentReference (if provided)
        if pdf_content:
            self._add_pdf_attachment(root, invoice_number, pdf_content)

        # Supplier (AccountingSupplierParty)
        self._add_supplier_party(root)

        # Customer (AccountingCustomerParty)
        self._add_customer_party(root, partner)

        # Payment means
        self._add_payment_means(root, invoice)

        # Tax totals
        self._add_tax_total(root, invoice, lines, taxes, currency)

        # Legal monetary total
        self._add_monetary_total(root, invoice, currency)

        # Invoice lines
        line_count = 0
        for idx, line in enumerate(lines, start=1):
            # Skip lines without price (section headers, notes, etc.)
            if line.get("price_subtotal", 0) == 0 and line.get("quantity", 0) == 0:
                continue
            self._add_invoice_line(
                root, line, idx, taxes, products, currency, is_credit_note
            )
            line_count += 1

        # Ensure at least one line (Peppol requirement)
        if line_count == 0:
            self._add_dummy_line(root, currency, is_credit_note)

        # Generate XML with declaration
        xml_str = ET.tostring(root, encoding="unicode")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'.encode("utf-8")

    def _add_cbc(self, parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
        """Add a CBC namespace element."""
        elem = ET.SubElement(parent, _cbc(tag))
        if text is not None:
            elem.text = str(text)
        return elem

    def _add_cac(self, parent: ET.Element, tag: str) -> ET.Element:
        """Add a CAC namespace element."""
        return ET.SubElement(parent, _cac(tag))

    def _get_currency(self, invoice: dict) -> str:
        """Extract currency code from invoice."""
        currency = "EUR"
        if invoice.get("currency_id"):
            currency_data = invoice["currency_id"]
            if isinstance(currency_data, (list, tuple)) and len(currency_data) > 1:
                currency = currency_data[1]
            elif isinstance(currency_data, str):
                currency = currency_data
        return currency

    def _get_country_code(self, data: dict) -> str:
        """Extract country code from partner/company data."""
        country_code = "BE"  # Default for Belgian companies
        if data.get("country_id"):
            country_data = data["country_id"]
            if isinstance(country_data, (list, tuple)) and len(country_data) > 1:
                country_name = country_data[1]
                # Map common country names to codes
                country_map = {
                    "Belgium": "BE", "België": "BE", "Belgique": "BE",
                    "Netherlands": "NL", "Nederland": "NL",
                    "Germany": "DE", "Deutschland": "DE",
                    "France": "FR",
                    "Luxembourg": "LU",
                    "United Kingdom": "GB",
                    "United States": "US",
                }
                for name, code in country_map.items():
                    if name in country_name:
                        country_code = code
                        break
        return country_code

    def _get_vat_scheme_id(self, vat: str, country_code: str) -> str:
        """Get the correct schemeID for a VAT number.

        Belgian VAT: 9925
        Belgian enterprise (KBO): 0208
        Dutch VAT: 9944
        German VAT: 9930
        French VAT: 9957
        """
        scheme_map = {
            "BE": "9925",  # Belgian VAT
            "NL": "9944",  # Dutch VAT
            "DE": "9930",  # German VAT
            "FR": "9957",  # French VAT
            "LU": "9945",  # Luxembourg VAT
        }
        return scheme_map.get(country_code, "9925")

    def _get_tax_category(self, rate: float) -> str:
        """Get Peppol tax category code based on rate.

        S = Standard rate (> 0%)
        Z = Zero rated (0% but taxable)
        E = Exempt
        """
        if rate > 0:
            return "S"
        # 0% could be zero-rated or exempt - default to zero-rated
        return "Z"

    def _add_pdf_attachment(
        self, root: ET.Element, invoice_number: str, pdf_content: bytes
    ) -> None:
        """Add PDF as AdditionalDocumentReference per Peppol BIS 3.0."""
        add_doc_ref = self._add_cac(root, "AdditionalDocumentReference")
        self._add_cbc(add_doc_ref, "ID", invoice_number)
        self._add_cbc(add_doc_ref, "DocumentDescription", "Invoice PDF")

        attachment = self._add_cac(add_doc_ref, "Attachment")
        pdf_filename = f"{invoice_number.replace('/', '-')}.pdf"
        embedded_doc = self._add_cbc(attachment, "EmbeddedDocumentBinaryObject")
        embedded_doc.set("mimeCode", "application/pdf")
        embedded_doc.set("filename", pdf_filename)
        embedded_doc.text = base64.b64encode(pdf_content).decode("ascii")

    def _add_supplier_party(self, root: ET.Element) -> None:
        """Add AccountingSupplierParty element."""
        supplier = self._add_cac(root, "AccountingSupplierParty")
        party = self._add_cac(supplier, "Party")

        country_code = self._get_country_code(self.company)
        vat = self.company.get("vat", "")

        # Endpoint ID (VAT number with correct scheme)
        if vat:
            endpoint = self._add_cbc(party, "EndpointID", vat)
            endpoint.set("schemeID", self._get_vat_scheme_id(vat, country_code))

        # Party identification
        if vat:
            party_id = self._add_cac(party, "PartyIdentification")
            self._add_cbc(party_id, "ID", vat)

        # Party name
        party_name = self._add_cac(party, "PartyName")
        self._add_cbc(party_name, "Name", self.company.get("name", ""))

        # Postal address
        address = self._add_cac(party, "PostalAddress")
        if self.company.get("street"):
            self._add_cbc(address, "StreetName", self.company["street"])
        if self.company.get("city"):
            self._add_cbc(address, "CityName", self.company["city"])
        if self.company.get("zip"):
            self._add_cbc(address, "PostalZone", self.company["zip"])

        country = self._add_cac(address, "Country")
        self._add_cbc(country, "IdentificationCode", country_code)

        # Tax scheme (VAT)
        if vat:
            tax_scheme = self._add_cac(party, "PartyTaxScheme")
            self._add_cbc(tax_scheme, "CompanyID", vat)
            scheme = self._add_cac(tax_scheme, "TaxScheme")
            self._add_cbc(scheme, "ID", "VAT")

        # Legal entity
        legal = self._add_cac(party, "PartyLegalEntity")
        self._add_cbc(legal, "RegistrationName", self.company.get("name", ""))
        if self.company.get("company_registry"):
            self._add_cbc(legal, "CompanyID", self.company["company_registry"])

    def _add_customer_party(self, root: ET.Element, partner: dict) -> None:
        """Add AccountingCustomerParty element."""
        customer = self._add_cac(root, "AccountingCustomerParty")
        party = self._add_cac(customer, "Party")

        country_code = self._get_country_code(partner)
        vat = partner.get("vat", "")

        # Endpoint ID
        if vat:
            endpoint = self._add_cbc(party, "EndpointID", vat)
            endpoint.set("schemeID", self._get_vat_scheme_id(vat, country_code))

        # Party identification
        if vat:
            party_id = self._add_cac(party, "PartyIdentification")
            self._add_cbc(party_id, "ID", vat)

        # Party name
        party_name = self._add_cac(party, "PartyName")
        self._add_cbc(party_name, "Name", partner.get("name", ""))

        # Postal address
        address = self._add_cac(party, "PostalAddress")
        if partner.get("street"):
            self._add_cbc(address, "StreetName", partner["street"])
        if partner.get("city"):
            self._add_cbc(address, "CityName", partner["city"])
        if partner.get("zip"):
            self._add_cbc(address, "PostalZone", partner["zip"])

        country = self._add_cac(address, "Country")
        self._add_cbc(country, "IdentificationCode", country_code)

        # Tax scheme
        if vat:
            tax_scheme = self._add_cac(party, "PartyTaxScheme")
            self._add_cbc(tax_scheme, "CompanyID", vat)
            scheme = self._add_cac(tax_scheme, "TaxScheme")
            self._add_cbc(scheme, "ID", "VAT")

        # Legal entity
        legal = self._add_cac(party, "PartyLegalEntity")
        self._add_cbc(legal, "RegistrationName", partner.get("name", ""))

    def _add_payment_means(self, root: ET.Element, invoice: dict) -> None:
        """Add PaymentMeans element."""
        payment = self._add_cac(root, "PaymentMeans")

        # Get company bank account (IBAN)
        iban = self.company.get("bank_account", "")

        if iban:
            # Credit transfer with bank account (BR-61 compliant)
            self._add_cbc(payment, "PaymentMeansCode", "30")
        else:
            # No bank account - use "not defined" code which doesn't require IBAN
            self._add_cbc(payment, "PaymentMeansCode", "1")

        if invoice.get("payment_reference"):
            self._add_cbc(payment, "PaymentID", invoice["payment_reference"])

        # PayeeFinancialAccount required for credit transfer (code 30)
        if iban:
            financial_account = self._add_cac(payment, "PayeeFinancialAccount")
            self._add_cbc(financial_account, "ID", iban)

    def _add_tax_total(
        self,
        root: ET.Element,
        invoice: dict,
        lines: list[dict],
        taxes: dict[int, dict],
        currency: str,
    ) -> None:
        """Add TaxTotal element."""
        tax_total = self._add_cac(root, "TaxTotal")

        tax_amount = self._add_cbc(
            tax_total, "TaxAmount", f"{invoice.get('amount_tax', 0):.2f}"
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
            subtotal = self._add_cac(tax_total, "TaxSubtotal")

            taxable = self._add_cbc(subtotal, "TaxableAmount", f"{group['taxable']:.2f}")
            taxable.set("currencyID", currency)

            tax_amt = self._add_cbc(subtotal, "TaxAmount", f"{group['tax']:.2f}")
            tax_amt.set("currencyID", currency)

            category = self._add_cac(subtotal, "TaxCategory")
            self._add_cbc(category, "ID", self._get_tax_category(rate))
            self._add_cbc(category, "Percent", f"{rate:.2f}")

            scheme = self._add_cac(category, "TaxScheme")
            self._add_cbc(scheme, "ID", "VAT")

    def _add_monetary_total(
        self, root: ET.Element, invoice: dict, currency: str
    ) -> None:
        """Add LegalMonetaryTotal element."""
        monetary = self._add_cac(root, "LegalMonetaryTotal")

        line_ext = self._add_cbc(
            monetary, "LineExtensionAmount", f"{invoice.get('amount_untaxed', 0):.2f}"
        )
        line_ext.set("currencyID", currency)

        tax_excl = self._add_cbc(
            monetary, "TaxExclusiveAmount", f"{invoice.get('amount_untaxed', 0):.2f}"
        )
        tax_excl.set("currencyID", currency)

        tax_incl = self._add_cbc(
            monetary, "TaxInclusiveAmount", f"{invoice.get('amount_total', 0):.2f}"
        )
        tax_incl.set("currencyID", currency)

        payable = self._add_cbc(
            monetary, "PayableAmount", f"{invoice.get('amount_total', 0):.2f}"
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
    ) -> None:
        """Add InvoiceLine or CreditNoteLine element."""
        if is_credit_note:
            inv_line = self._add_cac(root, "CreditNoteLine")
        else:
            inv_line = self._add_cac(root, "InvoiceLine")

        self._add_cbc(inv_line, "ID", str(line_number))

        # Quantity
        quantity = line.get("quantity", 1)
        if is_credit_note:
            qty_elem = self._add_cbc(inv_line, "CreditedQuantity", f"{quantity:.4f}")
        else:
            qty_elem = self._add_cbc(inv_line, "InvoicedQuantity", f"{quantity:.4f}")
        qty_elem.set("unitCode", "C62")  # Unit (piece)

        # Line extension amount
        line_amt = self._add_cbc(
            inv_line, "LineExtensionAmount", f"{line.get('price_subtotal', 0):.2f}"
        )
        line_amt.set("currencyID", currency)

        # Item
        item = self._add_cac(inv_line, "Item")

        # Description
        description = line.get("name", "")
        if description:
            self._add_cbc(item, "Description", description)

        # Product name
        product_name = description
        product_id = line.get("product_id")
        if product_id:
            if isinstance(product_id, (list, tuple)):
                product_id = product_id[0]
            if product_id in products:
                product_name = products[product_id].get("name", description)
        self._add_cbc(item, "Name", product_name or "Item")

        # Seller's item identification
        if product_id and product_id in products:
            product = products[product_id]
            if product.get("default_code"):
                seller_id = self._add_cac(item, "SellersItemIdentification")
                self._add_cbc(seller_id, "ID", product["default_code"])

        # Tax category for item
        line_tax_ids = line.get("tax_ids", [])
        tax_rate = 0
        if isinstance(line_tax_ids, (list, tuple)) and line_tax_ids:
            first_tax_id = line_tax_ids[0]
            if first_tax_id in taxes:
                tax_rate = taxes[first_tax_id].get("amount", 0)

        tax_cat = self._add_cac(item, "ClassifiedTaxCategory")
        self._add_cbc(tax_cat, "ID", self._get_tax_category(tax_rate))
        self._add_cbc(tax_cat, "Percent", f"{tax_rate:.2f}")
        scheme = self._add_cac(tax_cat, "TaxScheme")
        self._add_cbc(scheme, "ID", "VAT")

        # Price
        price = self._add_cac(inv_line, "Price")
        price_amt = self._add_cbc(price, "PriceAmount", f"{line.get('price_unit', 0):.4f}")
        price_amt.set("currencyID", currency)

    def _add_dummy_line(self, root: ET.Element, currency: str, is_credit_note: bool) -> None:
        """Add a dummy line when no real lines exist (Peppol requires at least one)."""
        if is_credit_note:
            inv_line = self._add_cac(root, "CreditNoteLine")
            qty_elem = self._add_cbc(inv_line, "CreditedQuantity", "0")
        else:
            inv_line = self._add_cac(root, "InvoiceLine")
            qty_elem = self._add_cbc(inv_line, "InvoicedQuantity", "0")

        self._add_cbc(inv_line, "ID", "1")
        qty_elem.set("unitCode", "C62")

        line_amt = self._add_cbc(inv_line, "LineExtensionAmount", "0.00")
        line_amt.set("currencyID", currency)

        item = self._add_cac(inv_line, "Item")
        self._add_cbc(item, "Name", "No items")

        tax_cat = self._add_cac(item, "ClassifiedTaxCategory")
        self._add_cbc(tax_cat, "ID", "Z")
        self._add_cbc(tax_cat, "Percent", "0.00")
        scheme = self._add_cac(tax_cat, "TaxScheme")
        self._add_cbc(scheme, "ID", "VAT")

        price = self._add_cac(inv_line, "Price")
        price_amt = self._add_cbc(price, "PriceAmount", "0.00")
        price_amt.set("currencyID", currency)
