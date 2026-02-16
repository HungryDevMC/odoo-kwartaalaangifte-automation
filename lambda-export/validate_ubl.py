#!/usr/bin/env python3
"""
End-to-End UBL Validation Script

Validates UBL Invoice/CreditNote files against Peppol BIS 3.0 using:
1. Local validator (basic Peppol BIS 3.0 rules)
2. Ecosio online validator (free, comprehensive)
3. Sample invoice generation for testing

Usage:
    python validate_ubl.py <file.xml>           # Validate single file
    python validate_ubl.py *.xml                # Validate multiple files
    python validate_ubl.py export.zip           # Validate all XMLs in ZIP
    python validate_ubl.py --json <file.xml>    # JSON output
    python validate_ubl.py --online <file.xml>  # Include online validators
    python validate_ubl.py --generate-sample    # Generate test invoice

Free Online Validators:
- Ecosio: https://ecosio.com/en/peppol-and-xml-document-validator/
- ITPLC: https://www.itplc.com/peppol-validator
"""

import argparse
import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path

from ubl_validator import UBLValidator, ValidationResult


def get_online_validators_info() -> str:
    """Return info about free online validators for manual testing."""
    return """
Free Online Peppol/UBL Validators (Manual):

1. Ecosio Validator (Recommended)
   https://ecosio.com/en/peppol-and-xml-document-validator/
   - Supports Peppol BIS 3.0, EN16931, XRechnung
   - Drag and drop XML file to validate

2. ITPLC Peppol Validator
   https://www.itplc.com/peppol-validator
   - Comprehensive Peppol BIS validation

3. SimplerInvoicing Validator (Netherlands)
   https://validation.simplerinvoicing.org/
   - Peppol BIS 3.0 validation

4. Belgian e-Invoicing Test Portal
   https://einvoicing.belgium.be/en
   - Hermes platform testing

5. KoSIT Validator (German)
   https://github.com/itplr-kosit/validator
   - Download and run locally with Java
   - Most comprehensive validation

6. Validate in Odoo
   - Import the UBL file via Vendor Bills > Import
   - Tests real-world compatibility
"""


def generate_sample_invoice() -> bytes:
    """Generate a sample Peppol BIS 3.0 compliant invoice."""
    from ubl_generator import UBLGenerator

    company = {
        "id": 1,
        "name": "Test Seller Company BV",
        "vat": "BE0123456789",
        "street": "Seller Street 123",
        "city": "Brussels",
        "zip": "1000",
        "country_id": [21, "Belgium"],
        "email": "seller@testcompany.be",
        "phone": "+32 2 123 4567",
        "bank_account": "BE68539007547034",
    }

    invoice = {
        "id": 1,
        "name": "INV/2024/SAMPLE",
        "_ubl_number": "INV/2024/SAMPLE",
        "move_type": "out_invoice",
        "state": "posted",
        "invoice_date": "2024-01-15",
        "invoice_date_due": "2024-02-15",
        "partner_id": [10, "Buyer Company"],
        "currency_id": [1, "EUR"],
        "amount_untaxed": 1000.00,
        "amount_tax": 210.00,
        "amount_total": 1210.00,
        "payment_reference": "INV-2024-SAMPLE",
        "narration": "",
        "invoice_line_ids": [100],
        "company_id": [1, "Test Company"],
        "ref": "",
    }

    partner = {
        "id": 10,
        "name": "Test Buyer Company NV",
        "vat": "BE9876543210",
        "street": "Buyer Street 456",
        "city": "Antwerp",
        "zip": "2000",
        "country_id": [21, "Belgium"],
        "email": "buyer@customercompany.be",
    }

    lines = [{
        "id": 100,
        "name": "Professional consulting services",
        "quantity": 10.0,
        "price_unit": 100.00,
        "price_subtotal": 1000.00,
        "price_total": 1210.00,
        "discount": 0,
        "product_id": [1, "Consulting"],
        "product_uom_id": [1, "Hours"],
        "tax_ids": [1],
        "move_id": [1, "INV/2024/SAMPLE"],
    }]

    taxes = {
        1: {
            "id": 1,
            "name": "BTW 21%",
            "amount": 21.0,
            "amount_type": "percent",
        }
    }

    generator = UBLGenerator(company)
    return generator.generate_invoice(invoice, partner, lines, taxes, {})


def validate_file(filepath: Path, validator: UBLValidator) -> tuple[str, ValidationResult]:
    """Validate a single UBL file."""
    with open(filepath, "rb") as f:
        content = f.read()
    return filepath.name, validator.validate(content)


def validate_zip(filepath: Path, validator: UBLValidator) -> list[tuple[str, ValidationResult]]:
    """Validate all XML files in a ZIP archive."""
    results = []
    with zipfile.ZipFile(filepath) as zf:
        for name in zf.namelist():
            if name.endswith((".xml", ".ubl")):
                content = zf.read(name)
                result = validator.validate(content)
                # Use the filename without UBL/ prefix
                display_name = name.split("/")[-1] if "/" in name else name
                results.append((display_name, result))
    return results


def print_result(filename: str, result: ValidationResult, verbose: bool = False):
    """Print validation result for a file."""
    if result.is_valid:
        status = "✓ VALID"
        color = "\033[92m"  # Green
    else:
        status = "✗ INVALID"
        color = "\033[91m"  # Red
    reset = "\033[0m"

    print(f"{color}{status}{reset} {filename}", end="")
    if result.errors:
        print(f" ({len(result.errors)} errors)", end="")
    if result.warnings:
        print(f" ({len(result.warnings)} warnings)", end="")
    print()

    if verbose or not result.is_valid:
        for err in result.errors:
            print(f"  {color}ERROR{reset} [{err.rule_id}] {err.message}")
        if verbose:
            for warn in result.warnings:
                print(f"  \033[93mWARN{reset} [{warn.rule_id}] {warn.message}")


def show_online_validators():
    """Show info about online validators."""
    print(get_online_validators_info())


def main():
    parser = argparse.ArgumentParser(
        description="Validate UBL Invoice/CreditNote files against Peppol BIS 3.0 rules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="XML/UBL files or ZIP archives to validate",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show warnings even for valid files",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error if any warnings are found",
    )
    parser.add_argument(
        "--show-validators",
        action="store_true",
        help="Show list of free online validators for manual testing",
    )
    parser.add_argument(
        "--generate-sample",
        action="store_true",
        help="Generate a sample invoice and validate it",
    )
    parser.add_argument(
        "--save-sample",
        metavar="FILE",
        help="Save generated sample to file",
    )

    args = parser.parse_args()

    # Show online validators info
    if args.show_validators:
        show_online_validators()
        return 0

    # Handle sample generation
    if args.generate_sample:
        print("Generating sample Peppol BIS 3.0 invoice...")
        try:
            xml_content = generate_sample_invoice()
            print(f"Generated {len(xml_content)} bytes of UBL XML\n")

            if args.save_sample:
                with open(args.save_sample, "wb") as f:
                    f.write(xml_content)
                print(f"Saved to: {args.save_sample}\n")

            # Validate the sample
            print("-" * 60)
            print("Local Peppol BIS 3.0 validation:")
            validator = UBLValidator()
            result = validator.validate(xml_content)
            print_result("sample_invoice.xml", result, args.verbose)

            print("-" * 60)
            if result.is_valid:
                print("\n✓ Sample invoice is valid")
                print("\nFor comprehensive validation, test with online validators:")
                print("  Run: python validate_ubl.py --show-validators")
                return 0
            else:
                print("\n✗ Sample invoice has errors")
                return 1

        except ImportError as e:
            print(f"Error: {e}")
            print("Make sure ubl_generator.py is in the same directory")
            return 1

    if not args.files:
        parser.print_help()
        return 1

    validator = UBLValidator()
    all_results = []
    exit_code = 0

    for filepath_str in args.files:
        filepath = Path(filepath_str)

        if not filepath.exists():
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            exit_code = 1
            continue

        if filepath.suffix.lower() == ".zip":
            results = validate_zip(filepath, validator)
            all_results.extend(results)
        else:
            filename, result = validate_file(filepath, validator)
            all_results.append((filename, result))

    if args.json:
        output = {
            "total": len(all_results),
            "valid": sum(1 for _, r in all_results if r.is_valid),
            "invalid": sum(1 for _, r in all_results if not r.is_valid),
            "files": [
                {
                    "filename": filename,
                    "valid": result.is_valid,
                    "document_type": result.document_type,
                    "errors": [
                        {"rule": e.rule_id, "message": e.message}
                        for e in result.errors
                    ],
                    "warnings": [
                        {"rule": w.rule_id, "message": w.message}
                        for w in result.warnings
                    ],
                }
                for filename, result in all_results
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\nValidating {len(all_results)} file(s)...\n")
        print("-" * 60)

        for filename, result in all_results:
            print_result(filename, result, args.verbose)

            if not result.is_valid:
                exit_code = 1
            elif args.strict and result.warnings:
                exit_code = 1

        print("-" * 60)
        valid_count = sum(1 for _, r in all_results if r.is_valid)
        invalid_count = len(all_results) - valid_count

        if invalid_count == 0:
            print(f"\n✓ All {valid_count} file(s) are valid")
            print("\nFor comprehensive testing, also validate with online tools:")
            print("  Run: python validate_ubl.py --show-validators")
        else:
            print(f"\n✗ {invalid_count} of {len(all_results)} file(s) failed validation")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
