#!/usr/bin/env python3
"""
End-to-End UBL Import Testing

Validates that generated UBL invoices can be imported into Odoo.
Designed to run in CI/CD pipelines on each commit.

Supported Odoo versions for E2E import testing:
  - Odoo 16, 17, 18: Full support via create_document_from_attachment API
  - Odoo 15: No public import API (use web UI manually)
  - Odoo 12-14: No native UBL import module

Usage:
    python test_e2e_import.py --ci                       # Full CI run with Odoo 17
    python test_e2e_import.py --ci --odoo-version 18     # Test with specific Odoo version
    python test_e2e_import.py --ci --keep                # CI run, keep containers for debugging
    python test_e2e_import.py --local-only               # Just validate locally, no Docker

Exit codes:
    0 - All tests passed
    1 - One or more tests failed
    2 - Infrastructure error (Docker, network, etc.)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import xmlrpc.client
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import requests

# Configuration
COMPOSE_FILE = Path(__file__).parent / "docker-compose.test.yml"

ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.getenv("ODOO_DB", "ubl_test")
ODOO_USER = os.getenv("ODOO_USER", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "admin")

# Timeouts
CONTAINER_STARTUP_TIMEOUT = 180  # 3 minutes
SERVICE_READY_TIMEOUT = 120      # 2 minutes


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    message: str
    details: Optional[dict] = None


class OdooE2ETest:
    """End-to-end testing with Odoo."""

    def __init__(self, url: str = ODOO_URL, db: str = ODOO_DB):
        self.url = url
        self.db = db
        self.uid = None
        self.password = ODOO_PASSWORD

    def wait_for_ready(self, timeout: int = SERVICE_READY_TIMEOUT) -> bool:
        """Wait for Odoo to be ready."""
        print(f"  Waiting for Odoo at {self.url}...")
        start = time.time()
        while time.time() - start < timeout:
            try:
                response = requests.get(
                    f"{self.url}/web/database/selector",
                    timeout=5
                )
                if response.status_code == 200:
                    print("  Odoo is ready!")
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(3)
        print("  Timeout waiting for Odoo")
        return False

    def setup(self) -> bool:
        """Setup database and modules."""
        if not self._create_database():
            return False
        if not self._authenticate():
            return False
        if not self._install_modules():
            return False
        return True

    def _create_database(self) -> bool:
        """Create test database."""
        print(f"  Creating database '{self.db}'...")
        try:
            db_proxy = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/db",
                allow_none=True
            )

            if self.db in db_proxy.list():
                print(f"  Database '{self.db}' already exists")
                return True

            db_proxy.create_database(
                "admin",
                self.db,
                True,
                "en_US",
                self.password,
                "admin",
                "BE",
            )
            print(f"  Database '{self.db}' created!")
            time.sleep(5)
            return True

        except xmlrpc.client.Fault as e:
            if "already exists" in str(e):
                return True
            print(f"  Database creation failed: {e.faultString[:200]}")
        except Exception as e:
            print(f"  Database creation failed: {e}")

        # Fallback: web-based creation
        try:
            response = requests.post(
                f"{self.url}/web/database/create",
                data={
                    "master_pwd": "admin",
                    "name": self.db,
                    "login": "admin",
                    "password": self.password,
                    "lang": "en_US",
                    "country_code": "BE",
                },
                allow_redirects=False,
            )
            if response.status_code in (200, 303):
                print(f"  Database created via web!")
                time.sleep(5)
                return True
        except Exception:
            pass

        return False

    def _authenticate(self) -> bool:
        """Authenticate with Odoo."""
        try:
            common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
            self.uid = common.authenticate(self.db, ODOO_USER, self.password, {})
            if self.uid:
                print(f"  Authenticated as user {self.uid}")
                return True
        except Exception as e:
            print(f"  Authentication failed: {e}")
        return False

    def _execute(self, model: str, method: str, *args, **kwargs):
        """Execute Odoo method."""
        models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        return models.execute_kw(
            self.db, self.uid, self.password,
            model, method, args, kwargs
        )

    def _install_modules(self) -> bool:
        """Install required modules."""
        modules = ["account", "account_edi", "account_edi_ubl_cii"]
        print(f"  Installing modules: {modules}")
        try:
            module_ids = self._execute(
                "ir.module.module", "search",
                [("name", "in", modules), ("state", "!=", "installed")]
            )
            if not module_ids:
                print("  All modules already installed")
                return True

            self._execute(
                "ir.module.module", "button_immediate_install",
                module_ids
            )
            print(f"  Installed {len(module_ids)} module(s)")
            return True
        except Exception as e:
            print(f"  Module installation failed: {e}")
            return False

    def import_invoice(self, xml_content: bytes, filename: str) -> TestResult:
        """Import UBL invoice and return test result."""
        try:
            # Create attachment
            attachment_data = {
                "name": filename,
                "datas": base64.b64encode(xml_content).decode(),
                "mimetype": "application/xml",
            }
            attachment_id = self._execute("ir.attachment", "create", attachment_data)

            # Import via purchase journal
            journal_id = self._execute(
                "account.journal", "search",
                [("type", "=", "purchase")], limit=1
            )
            if not journal_id:
                return TestResult(filename, False, "No purchase journal found")

            result = self._execute(
                "account.journal", "create_document_from_attachment",
                journal_id, [attachment_id]
            )

            if result and result.get("res_id"):
                invoice_id = result["res_id"]
                invoice = self._execute(
                    "account.move", "read", [invoice_id],
                    ["name", "partner_id", "amount_total", "state", "move_type"]
                )[0]
                return TestResult(
                    filename, True,
                    f"Imported as {invoice['move_type']} (ID: {invoice_id})",
                    details=invoice
                )

            return TestResult(filename, False, "Import returned no result")

        except xmlrpc.client.Fault as e:
            return TestResult(filename, False, e.faultString[:500])
        except Exception as e:
            return TestResult(filename, False, str(e)[:500])


def generate_test_invoices() -> list[tuple[str, bytes]]:
    """Generate test UBL invoices."""
    from ubl_generator import UBLGenerator

    invoices = []

    company = {
        "id": 1,
        "name": "Test Seller BV",
        "vat": "BE0123456789",
        "street": "Test Street 1",
        "city": "Brussels",
        "zip": "1000",
        "country_id": [21, "Belgium"],
        "email": "seller@test.be",
        "bank_account": "BE68539007547034",
    }

    partner = {
        "id": 10,
        "name": "Test Buyer NV",
        "vat": "BE9876543210",
        "street": "Buyer Street 1",
        "city": "Antwerp",
        "zip": "2000",
        "country_id": [21, "Belgium"],
        "email": "buyer@test.be",
    }

    generator = UBLGenerator(company)
    taxes = {1: {"id": 1, "name": "VAT 21%", "amount": 21.0, "amount_type": "percent"}}

    # Test case 1: Standard invoice with 21% VAT
    invoice1 = {
        "id": 1,
        "name": "E2E-INV-001",
        "_ubl_number": "E2E-INV-001",
        "move_type": "out_invoice",
        "state": "posted",
        "invoice_date": str(date.today()),
        "invoice_date_due": str(date.today()),
        "partner_id": [10, "Test Buyer"],
        "currency_id": [1, "EUR"],
        "amount_untaxed": 1000.00,
        "amount_tax": 210.00,
        "amount_total": 1210.00,
        "payment_reference": "E2E-001",
        "narration": "",
        "invoice_line_ids": [1],
        "company_id": [1, "Test"],
        "ref": "",
    }
    lines1 = [{
        "id": 1,
        "name": "Consulting Services",
        "quantity": 10.0,
        "price_unit": 100.00,
        "price_subtotal": 1000.00,
        "price_total": 1210.00,
        "discount": 0,
        "product_id": False,
        "product_uom_id": [1, "Units"],
        "tax_ids": [1],
        "move_id": [1, "E2E-INV-001"],
    }]

    xml1 = generator.generate_invoice(invoice1, partner, lines1, taxes, {})
    invoices.append(("E2E-INV-001.xml", xml1))

    # Test case 2: Credit note
    invoice2 = {**invoice1, "id": 2, "name": "E2E-CN-001", "_ubl_number": "E2E-CN-001", "move_type": "out_refund"}
    xml2 = generator.generate_invoice(invoice2, partner, lines1, taxes, {})
    invoices.append(("E2E-CN-001.xml", xml2))

    # Test case 3: 0% VAT (exempt)
    invoice3 = {
        **invoice1,
        "id": 3,
        "name": "E2E-INV-002",
        "_ubl_number": "E2E-INV-002",
        "amount_tax": 0.0,
        "amount_total": 1000.0,
    }
    lines3 = [{**lines1[0], "price_total": 1000.0, "tax_ids": [2]}]
    taxes3 = {2: {"id": 2, "name": "VAT 0%", "amount": 0.0, "amount_type": "percent"}}
    xml3 = generator.generate_invoice(invoice3, partner, lines3, taxes3, {})
    invoices.append(("E2E-INV-002.xml", xml3))

    # Test case 4: Multiple line items
    invoice4 = {
        **invoice1,
        "id": 4,
        "name": "E2E-INV-003",
        "_ubl_number": "E2E-INV-003",
        "amount_untaxed": 500.00,
        "amount_tax": 105.00,
        "amount_total": 605.00,
        "invoice_line_ids": [1, 2],
    }
    lines4 = [
        {
            "id": 1,
            "name": "Product A",
            "quantity": 2.0,
            "price_unit": 150.00,
            "price_subtotal": 300.00,
            "price_total": 363.00,
            "discount": 0,
            "product_id": [1, "Product A"],
            "product_uom_id": [1, "Units"],
            "tax_ids": [1],
            "move_id": [4, "E2E-INV-003"],
        },
        {
            "id": 2,
            "name": "Product B",
            "quantity": 4.0,
            "price_unit": 50.00,
            "price_subtotal": 200.00,
            "price_total": 242.00,
            "discount": 0,
            "product_id": [2, "Product B"],
            "product_uom_id": [1, "Units"],
            "tax_ids": [1],
            "move_id": [4, "E2E-INV-003"],
        },
    ]
    xml4 = generator.generate_invoice(invoice4, partner, lines4, taxes, {})
    invoices.append(("E2E-INV-003.xml", xml4))

    # Test case 5: Invoice with discount
    invoice5 = {
        **invoice1,
        "id": 5,
        "name": "E2E-INV-004",
        "_ubl_number": "E2E-INV-004",
        "amount_untaxed": 900.00,  # 1000 - 10% discount
        "amount_tax": 189.00,
        "amount_total": 1089.00,
    }
    lines5 = [{
        "id": 5,
        "name": "Discounted Service",
        "quantity": 10.0,
        "price_unit": 100.00,
        "price_subtotal": 900.00,  # After 10% discount
        "price_total": 1089.00,
        "discount": 10.0,
        "product_id": False,
        "product_uom_id": [1, "Units"],
        "tax_ids": [1],
        "move_id": [5, "E2E-INV-004"],
    }]
    xml5 = generator.generate_invoice(invoice5, partner, lines5, taxes, {})
    invoices.append(("E2E-INV-004.xml", xml5))

    return invoices


def run_docker_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run docker compose command."""
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE)] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def start_containers() -> bool:
    """Start Docker containers."""
    print("\n[1/4] Starting Docker containers...")
    try:
        result = run_docker_command(["up", "-d", "--wait"], check=False)
        if result.returncode != 0:
            result = run_docker_command(["up", "-d"], check=False)

        if result.returncode != 0:
            print(f"  Failed to start containers: {result.stderr}")
            return False

        print("  Containers started")
        return True
    except Exception as e:
        print(f"  Docker error: {e}")
        return False


def wait_for_healthy() -> bool:
    """Wait for containers to be healthy."""
    print("\n[2/4] Waiting for containers to be healthy...")
    start = time.time()

    while time.time() - start < CONTAINER_STARTUP_TIMEOUT:
        try:
            result = run_docker_command(["ps", "--format", "json"], check=False)
            if result.returncode == 0:
                containers = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            containers.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

                all_healthy = True
                for c in containers:
                    health = c.get("Health", c.get("Status", ""))
                    if "healthy" not in health.lower() and "running" not in health.lower():
                        all_healthy = False
                        break

                if all_healthy and containers:
                    print("  All containers healthy!")
                    return True
        except Exception:
            pass

        time.sleep(5)
        print(f"  Still waiting... ({int(time.time() - start)}s)")

    print("  Timeout waiting for containers")
    return False


def stop_containers(remove_volumes: bool = True) -> None:
    """Stop and remove Docker containers."""
    print("\n[4/4] Cleaning up containers...")
    args = ["down"]
    if remove_volumes:
        args.append("-v")
    run_docker_command(args, check=False)
    print("  Cleanup complete")


def run_tests() -> list[TestResult]:
    """Run the E2E tests."""
    results = []

    # Generate test invoices
    print("\n[3/4] Running tests...")
    test_invoices = generate_test_invoices()
    print(f"  Generated {len(test_invoices)} test invoice(s)")

    # Local validation
    from ubl_validator import UBLValidator
    validator = UBLValidator()

    print("\n  --- Local Validation ---")
    for filename, xml_content in test_invoices:
        local_result = validator.validate(xml_content)
        if local_result.is_valid:
            results.append(TestResult(f"LOCAL:{filename}", True, "Valid UBL"))
            print(f"  ✓ {filename}: Valid")
        else:
            error_msg = local_result.errors[0].message if local_result.errors else "Unknown"
            results.append(TestResult(f"LOCAL:{filename}", False, error_msg))
            print(f"  ✗ {filename}: {error_msg}")

    # Odoo import tests
    print("\n  --- Odoo Import Tests ---")
    odoo = OdooE2ETest()
    if odoo.wait_for_ready():
        if odoo.setup():
            for filename, xml_content in test_invoices:
                result = odoo.import_invoice(xml_content, filename)
                result.name = f"ODOO:{result.name}"
                results.append(result)
                status = "✓" if result.passed else "✗"
                print(f"  {status} {filename}: {result.message}")
        else:
            results.append(TestResult("ODOO:setup", False, "Setup failed"))
    else:
        results.append(TestResult("ODOO:connection", False, "Connection failed"))

    return results


def print_summary(results: list[TestResult]) -> bool:
    """Print test summary and return success status."""
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    for r in results:
        status = "✓ PASS" if r.passed else "✗ FAIL"
        print(f"  {status}  {r.name}")
        if not r.passed:
            print(f"         {r.message}")

    print("-" * 60)
    print(f"Total: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end UBL import testing with Odoo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ci", action="store_true",
        help="Full CI run: start containers, test, cleanup"
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep containers running after CI tests (for debugging)"
    )
    parser.add_argument(
        "--local-only", action="store_true",
        help="Just validate locally, no Docker required"
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="Stop and remove containers"
    )
    parser.add_argument(
        "--odoo-version", type=str, default="17",
        help="Odoo version to test (15, 16, 17, 18). Default: 17"
    )

    args = parser.parse_args()

    # Set ODOO_VERSION environment variable for docker-compose
    os.environ["ODOO_VERSION"] = args.odoo_version

    # Cleanup only
    if args.cleanup:
        stop_containers()
        return 0

    # Local validation only
    if args.local_only:
        print("Running local validation only...\n")
        from ubl_validator import UBLValidator
        validator = UBLValidator()
        test_invoices = generate_test_invoices()

        all_valid = True
        for filename, xml_content in test_invoices:
            result = validator.validate(xml_content)
            status = "✓ VALID" if result.is_valid else "✗ INVALID"
            print(f"{status} {filename}")
            if not result.is_valid:
                for err in result.errors:
                    print(f"  [{err.rule_id}] {err.message}")
                all_valid = False

        return 0 if all_valid else 1

    # Full CI run
    if args.ci:
        print("=" * 60)
        print(f"E2E UBL IMPORT TEST (Odoo {args.odoo_version})")
        print("=" * 60)

        if not start_containers():
            return 2

        if not wait_for_healthy():
            if not args.keep:
                stop_containers()
            return 2

        try:
            results = run_tests()
            success = print_summary(results)
        finally:
            if not args.keep:
                stop_containers()

        return 0 if success else 1

    # Default: show help
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
