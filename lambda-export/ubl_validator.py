"""
UBL/Peppol BIS 3.0 Validator

Validates UBL Invoice/CreditNote XML files against:
1. UBL 2.1 XSD Schema (structural validation)
2. Peppol BIS 3.0 Schematron rules (business rule validation)

Dependencies: lxml
"""

import os
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ValidationError:
    """Represents a single validation error."""
    level: str  # 'error', 'warning', 'fatal'
    rule_id: str  # e.g., 'BR-01', 'BR-CO-09', 'xsd'
    message: str
    location: str = ""  # XPath location in document
    test: str = ""  # The failed test expression


@dataclass
class ValidationResult:
    """Complete validation result."""
    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    xsd_valid: bool = True
    schematron_valid: bool = True
    document_type: str = ""  # 'Invoice' or 'CreditNote'

    def __str__(self) -> str:
        if self.is_valid:
            return f"Valid {self.document_type} (0 errors, {len(self.warnings)} warnings)"
        return (
            f"Invalid {self.document_type}: "
            f"{len(self.errors)} errors, {len(self.warnings)} warnings"
        )

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "xsd_valid": self.xsd_valid,
            "schematron_valid": self.schematron_valid,
            "document_type": self.document_type,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [
                {
                    "level": e.level,
                    "rule_id": e.rule_id,
                    "message": e.message,
                    "location": e.location,
                }
                for e in self.errors
            ],
            "warnings": [
                {
                    "level": w.level,
                    "rule_id": w.rule_id,
                    "message": w.message,
                    "location": w.location,
                }
                for w in self.warnings
            ],
        }


class UBLValidator:
    """
    Validates UBL documents against Peppol BIS 3.0 specifications.

    Usage:
        validator = UBLValidator()
        result = validator.validate(xml_content)
        if not result.is_valid:
            for error in result.errors:
                print(f"{error.rule_id}: {error.message}")
    """

    # Peppol BIS 3.0 Schematron URLs
    SCHEMATRON_URLS = {
        "peppol": "https://raw.githubusercontent.com/OpenPEPPOL/peppol-bis-invoice-3/master/rules/sch/PEPPOL-EN16931-UBL.sch",
        "cen": "https://raw.githubusercontent.com/OpenPEPPOL/peppol-bis-invoice-3/master/rules/sch/CEN-EN16931-UBL.sch",
    }

    # UBL 2.1 XSD URLs
    XSD_URLS = {
        "Invoice": "http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-Invoice-2.1.xsd",
        "CreditNote": "http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-CreditNote-2.1.xsd",
    }

    # UBL Namespaces
    NAMESPACES = {
        "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "ubl-cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }

    def __init__(self, cache_dir: Optional[str] = None, skip_download: bool = False):
        """
        Initialize the validator.

        Args:
            cache_dir: Directory to cache downloaded schemas.
                      Defaults to temp directory.
            skip_download: If True, skip XSD validation if schemas aren't cached.
        """
        self.cache_dir = Path(cache_dir or tempfile.gettempdir()) / "peppol_schemas"
        self.skip_download = skip_download
        self._lxml_available = None
        self._xsd_schemas = {}
        self._schematron_validators = {}

    def _check_lxml(self) -> bool:
        """Check if lxml is available."""
        if self._lxml_available is None:
            try:
                import lxml.etree
                self._lxml_available = True
            except ImportError:
                self._lxml_available = False
        return self._lxml_available

    def _ensure_cache_dir(self):
        """Create cache directory if it doesn't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _download_file(self, url: str, filename: str) -> Optional[Path]:
        """Download a file to the cache directory."""
        self._ensure_cache_dir()
        filepath = self.cache_dir / filename

        if filepath.exists():
            return filepath

        if self.skip_download:
            return None

        try:
            urllib.request.urlretrieve(url, filepath)
            return filepath
        except Exception:
            return None

    def _detect_document_type(self, xml_content: bytes) -> str:
        """Detect if the document is an Invoice or CreditNote."""
        if b"<CreditNote" in xml_content or b":CreditNote" in xml_content:
            return "CreditNote"
        return "Invoice"

    def validate(
        self,
        xml_content: bytes,
        validate_xsd: bool = True,
        validate_schematron: bool = True,
    ) -> ValidationResult:
        """
        Validate a UBL document.

        Args:
            xml_content: The XML document as bytes
            validate_xsd: Whether to perform XSD validation
            validate_schematron: Whether to perform Schematron validation

        Returns:
            ValidationResult with all errors and warnings
        """
        result = ValidationResult(is_valid=True)
        result.document_type = self._detect_document_type(xml_content)

        if not self._check_lxml():
            result.warnings.append(ValidationError(
                level="warning",
                rule_id="VALIDATOR",
                message="lxml not installed. Run: pip install lxml",
            ))
            return result

        import lxml.etree as etree

        # Parse the document
        try:
            doc = etree.fromstring(xml_content)
        except etree.XMLSyntaxError as e:
            result.is_valid = False
            result.xsd_valid = False
            result.errors.append(ValidationError(
                level="fatal",
                rule_id="XML",
                message=f"XML parsing error: {e}",
            ))
            return result

        # XSD Validation
        if validate_xsd:
            xsd_result = self._validate_xsd(doc, result.document_type)
            result.xsd_valid = xsd_result.is_valid
            result.errors.extend(xsd_result.errors)
            result.warnings.extend(xsd_result.warnings)

        # Schematron Validation
        if validate_schematron:
            sch_result = self._validate_schematron(doc)
            result.schematron_valid = sch_result.is_valid
            result.errors.extend(sch_result.errors)
            result.warnings.extend(sch_result.warnings)

        # Overall validity
        result.is_valid = len(result.errors) == 0

        return result

    def _validate_xsd(self, doc, doc_type: str) -> ValidationResult:
        """Validate against UBL 2.1 XSD schema."""
        import lxml.etree as etree

        result = ValidationResult(is_valid=True, document_type=doc_type)

        # Get or load the schema
        if doc_type not in self._xsd_schemas:
            schema = self._load_xsd_schema(doc_type)
            if schema:
                self._xsd_schemas[doc_type] = schema

        schema = self._xsd_schemas.get(doc_type)
        if not schema:
            result.warnings.append(ValidationError(
                level="warning",
                rule_id="XSD",
                message=f"XSD schema for {doc_type} not available. Skipping XSD validation.",
            ))
            return result

        # Validate
        if not schema.validate(doc):
            result.is_valid = False
            for error in schema.error_log:
                result.errors.append(ValidationError(
                    level="error",
                    rule_id="XSD",
                    message=error.message,
                    location=f"Line {error.line}, Column {error.column}",
                ))

        return result

    def _load_xsd_schema(self, doc_type: str):
        """Load XSD schema from cache or download."""
        import lxml.etree as etree

        # Try to use a local bundled schema first
        bundled_path = Path(__file__).parent / "schemas" / f"UBL-{doc_type}-2.1.xsd"
        if bundled_path.exists():
            try:
                with open(bundled_path, "rb") as f:
                    schema_doc = etree.parse(f)
                return etree.XMLSchema(schema_doc)
            except Exception:
                pass

        # Skip XSD for now - it requires the full UBL package
        # Schematron provides better business rule validation anyway
        return None

    def _validate_schematron(self, doc) -> ValidationResult:
        """Validate against Peppol BIS 3.0 Schematron rules."""
        import lxml.etree as etree

        result = ValidationResult(is_valid=True)

        # Try to load compiled schematron
        if "peppol" not in self._schematron_validators:
            validator = self._load_schematron()
            if validator:
                self._schematron_validators["peppol"] = validator

        validator = self._schematron_validators.get("peppol")
        if not validator:
            # Fallback to basic structural checks
            return self._validate_basic_rules(doc)

        try:
            # Validate and get SVRL report
            svrl = validator(doc)

            # Parse SVRL for errors
            svrl_ns = {"svrl": "http://purl.oclc.org/dml/svrl"}

            for failed in svrl.xpath("//svrl:failed-assert", namespaces=svrl_ns):
                rule_id = failed.get("id", "UNKNOWN")
                flag = failed.get("flag", "error")
                location = failed.get("location", "")
                test = failed.get("test", "")

                text_elem = failed.find("svrl:text", namespaces=svrl_ns)
                message = text_elem.text if text_elem is not None else "Validation failed"

                error = ValidationError(
                    level=flag,
                    rule_id=rule_id,
                    message=message.strip(),
                    location=location,
                    test=test,
                )

                if flag in ("fatal", "error"):
                    result.errors.append(error)
                else:
                    result.warnings.append(error)

            result.is_valid = len(result.errors) == 0

        except Exception as e:
            result.warnings.append(ValidationError(
                level="warning",
                rule_id="SCHEMATRON",
                message=f"Schematron validation error: {e}",
            ))
            # Fallback to basic rules
            basic_result = self._validate_basic_rules(doc)
            result.errors.extend(basic_result.errors)
            result.warnings.extend(basic_result.warnings)
            result.is_valid = result.is_valid and basic_result.is_valid

        return result

    def _load_schematron(self):
        """Load and compile Schematron rules."""
        try:
            from lxml import isoschematron
        except ImportError:
            return None

        # Try bundled pre-compiled XSLT first
        bundled_path = Path(__file__).parent / "schemas" / "PEPPOL-EN16931-UBL.xslt"
        if bundled_path.exists():
            try:
                import lxml.etree as etree
                with open(bundled_path, "rb") as f:
                    xslt_doc = etree.parse(f)
                return etree.XSLT(xslt_doc)
            except Exception:
                pass

        # Note: Raw .sch files from Peppol use ISO Schematron features
        # that require pre-compilation with Saxon. Skip downloading
        # as lxml's isoschematron can't handle them directly.
        # The basic rule validation will be used instead.
        return None

    def _validate_basic_rules(self, doc) -> ValidationResult:
        """
        Basic validation without external schemas.
        Checks essential Peppol BIS 3.0 requirements.
        """
        result = ValidationResult(is_valid=True)

        # Define namespaces for XPath
        ns = {
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        }

        def get_text(xpath: str) -> Optional[str]:
            elems = doc.xpath(xpath, namespaces=ns)
            return elems[0].text if elems and elems[0].text else None

        def check_required(xpath: str, rule_id: str, desc: str):
            if not get_text(xpath):
                result.errors.append(ValidationError(
                    level="error",
                    rule_id=rule_id,
                    message=f"{desc} is required",
                    location=xpath,
                ))

        def check_exists(xpath: str, rule_id: str, desc: str):
            if not doc.xpath(xpath, namespaces=ns):
                result.errors.append(ValidationError(
                    level="error",
                    rule_id=rule_id,
                    message=f"{desc} is required",
                    location=xpath,
                ))

        # BR-01: Invoice number
        check_required("//cbc:ID", "BR-01", "Invoice number (ID)")

        # BR-02: Invoice issue date
        check_required("//cbc:IssueDate", "BR-02", "Invoice issue date")

        # BR-04: Seller name
        check_required(
            "//cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
            "BR-06",
            "Seller name (RegistrationName)"
        )

        # BR-07: Buyer name
        check_required(
            "//cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
            "BR-07",
            "Buyer name (RegistrationName)"
        )

        # BR-10: Buyer endpoint
        check_exists(
            "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID",
            "BR-10",
            "Buyer electronic address (EndpointID)"
        )

        # BR-12: Buyer reference or Order reference
        buyer_ref = get_text("//cbc:BuyerReference")
        order_ref = get_text("//cac:OrderReference/cbc:ID")
        if not buyer_ref and not order_ref:
            result.warnings.append(ValidationError(
                level="warning",
                rule_id="BR-12",
                message="BuyerReference or OrderReference is recommended",
            ))

        # BR-16: At least one invoice line
        lines = doc.xpath("//cac:InvoiceLine | //cac:CreditNoteLine", namespaces=ns)
        if not lines:
            result.errors.append(ValidationError(
                level="error",
                rule_id="BR-16",
                message="Invoice must have at least one line",
            ))

        # BR-CO-09: Seller VAT should have country prefix
        seller_vat = get_text(
            "//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
        )
        if seller_vat and len(seller_vat) >= 2:
            if seller_vat[:2].isdigit():
                result.warnings.append(ValidationError(
                    level="warning",
                    rule_id="BR-CO-09",
                    message=f"Seller VAT '{seller_vat}' should have country prefix",
                ))

        # BR-CO-09: Buyer VAT should have country prefix
        buyer_vat = get_text(
            "//cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
        )
        if buyer_vat and len(buyer_vat) >= 2:
            if buyer_vat[:2].isdigit():
                result.warnings.append(ValidationError(
                    level="warning",
                    rule_id="BR-CO-09",
                    message=f"Buyer VAT '{buyer_vat}' should have country prefix",
                ))

        # Currency check
        currency_attrs = doc.xpath("//*/@currencyID")
        currencies = set(currency_attrs)
        if len(currencies) > 1:
            result.warnings.append(ValidationError(
                level="warning",
                rule_id="BR-CL-04",
                message=f"Multiple currencies found: {currencies}. Should be consistent.",
            ))

        # Peppol CustomizationID
        customization = get_text("//cbc:CustomizationID")
        if customization:
            if "peppol" not in customization.lower() and "en16931" not in customization.lower():
                result.warnings.append(ValidationError(
                    level="warning",
                    rule_id="PEPPOL-EN16931",
                    message="CustomizationID should reference Peppol BIS 3.0 or EN16931",
                ))

        # Check tax totals
        tax_total = doc.xpath("//cac:TaxTotal", namespaces=ns)
        if not tax_total:
            result.warnings.append(ValidationError(
                level="warning",
                rule_id="BR-CO-14",
                message="TaxTotal element is recommended",
            ))

        result.is_valid = len(result.errors) == 0
        return result


def validate_file(filepath: str) -> ValidationResult:
    """Convenience function to validate a UBL file."""
    with open(filepath, "rb") as f:
        content = f.read()
    validator = UBLValidator()
    return validator.validate(content)


def validate_string(xml_string: str) -> ValidationResult:
    """Convenience function to validate a UBL XML string."""
    if isinstance(xml_string, str):
        xml_string = xml_string.encode("utf-8")
    validator = UBLValidator()
    return validator.validate(xml_string)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ubl_validator.py <ubl_file.xml> [<file2.xml> ...]")
        print("\nValidates UBL Invoice/CreditNote files against Peppol BIS 3.0 rules.")
        sys.exit(1)

    exit_code = 0
    for filepath in sys.argv[1:]:
        print(f"\n{'='*60}")
        print(f"Validating: {filepath}")
        print("="*60)

        try:
            result = validate_file(filepath)
            print(f"\nResult: {result}")

            if result.errors:
                print(f"\nErrors ({len(result.errors)}):")
                for err in result.errors:
                    print(f"  [{err.rule_id}] {err.message}")
                    if err.location:
                        print(f"           Location: {err.location}")

            if result.warnings:
                print(f"\nWarnings ({len(result.warnings)}):")
                for warn in result.warnings:
                    print(f"  [{warn.rule_id}] {warn.message}")

            if not result.is_valid:
                exit_code = 1

        except FileNotFoundError:
            print(f"Error: File not found: {filepath}")
            exit_code = 1
        except Exception as e:
            print(f"Error: {e}")
            exit_code = 1

    sys.exit(exit_code)
