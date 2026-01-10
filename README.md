# Invoice UBL & Bank Statement Export

Odoo 18 module for bulk exporting invoices to Peppol BIS 3.0 UBL XML and bank statements to PDF, with quarterly auto-send functionality.

## Features

- **UBL XML Export**: Export customer invoices, vendor bills, and credit notes to Peppol BIS 3.0 compliant UBL XML files
- **Bank Statement PDF Export**: Export bank statements from multiple accounts to PDF format
- **Flexible Selection**: Export by quarter, date range, or manual selection
- **Document Filtering**: Filter by state (posted, draft) and custom domain filters
- **Quarterly Auto-Send**: Automatically email exports at the start of each quarter
  - UBL files to BilltoBox or similar service
  - Bank statement PDFs to your accountant

## Installation

1. Copy the `account_invoice_ubl_export` folder to your Odoo addons directory
2. Update the apps list in Odoo
3. Install the module "Invoice UBL & Bank Statement Export"

## Configuration

### Quarterly Auto-Send

1. Go to **Settings → Invoicing → Quarterly Export**
2. Enable "Quarterly Auto-Send"
3. Configure:
   - **Send Day**: Day of the month to send (1-28)
   - **BilltoBox Email**: Email address for UBL files
   - **Bank Statements Email**: Email address for PDF statements
   - **Bank Accounts**: Select which accounts to include
   - **Document State Filter**: Choose which document states to include
   - **Custom Filter**: Optional Odoo domain for additional filtering

### Manual Export

1. Go to **Invoicing → Reporting → Export to UBL**
2. Select your export criteria
3. Click Export and download the ZIP file

## Quick Start (Docker)

```bash
# Start Odoo 18 with PostgreSQL
docker-compose up -d

# Open browser at http://localhost:8069
```

## Module Features

- Export by quarter (Q1, Q2, Q3, Q4)
- Export by date range
- Manual invoice selection
- Filter by document state (Posted, Draft Bills, Draft Invoices, etc.)
- Custom domain filters
- Bank statement PDF export
- Preview before export
- ZIP download with all files
- Quarterly auto-send via email
- Peppol BIS Billing 3.0 compliant

## Belgian E-invoicing 2026

From January 1, 2026, e-invoicing becomes mandatory for all B2B transactions in Belgium. This module generates Peppol-compliant UBL files that can be imported into accounting software like BilltoBox, ClearFacts, Exact, Yuki, and Octopus.

## Requirements

- Odoo 18.0
- Dependencies: `account`, `account_edi_ubl_cii`, `mail`

## License

LGPL-3.0 or later

## Support

For support, please open an issue on [GitHub](https://github.com/HungryDevMC/odoo-kwartaalaangifte-automation).
