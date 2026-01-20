# -*- coding: utf-8 -*-
"""AWS Lambda handler for Odoo UBL export.

Supports all configuration options from the Odoo module:
- Direction filter (customer invoices / vendor bills / both)
- Document type filter (invoices / credit notes / all)
- State filter (posted / drafts / all combinations)
- Custom domain filter
- Email sending to BilltoBox and accountant
- Quarterly auto-send scheduling
"""

import base64
import io
import json
import logging
import os
import zipfile
from datetime import date

from config import ExportConfig
from email_sender import OdooEmailSender
from odoo_client import OdooClient, get_quarter_dates
from ubl_generator import UBLGenerator

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    """Main Lambda handler for UBL export.

    Supports two modes:
    1. Manual trigger via API with parameters
    2. Scheduled quarterly export (auto_quarter=true)

    Event Parameters:
        quarter: Q1, Q2, Q3, Q4 (optional if date_from/date_to provided)
        year: Year as integer (optional if date_from/date_to provided)
        date_from: Start date as YYYY-MM-DD (optional)
        date_to: End date as YYYY-MM-DD (optional)

        # Filter options (override environment defaults)
        direction: "both" | "outgoing" | "incoming"
        document_type: "all" | "invoice" | "refund"
        state_filter: "posted" | "posted_draft_bills" | "posted_draft_invoices" |
                      "posted_draft" | "all"
        custom_domain: Odoo domain string

        # Email options
        send_email: send results via email (default: true if ubl_email configured)
        ubl_email: Override UBL recipient
        pdf_email: Override PDF recipient

        # Auto mode
        auto_quarter: true for scheduled quarterly export

    Returns:
        Response with export results, S3 location, or download URL
    """
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        # Load config from environment and event overrides
        config = ExportConfig.from_event(event)

        # Validate Odoo credentials
        if not all([config.odoo_url, config.odoo_database,
                    config.odoo_username, config.odoo_api_key]):
            return _error_response(400, "Missing Odoo credentials")

        # Handle auto quarterly export
        if event.get("auto_quarter"):
            return _handle_auto_quarterly_export(config)

        # Parse date range for manual export
        date_from, date_to, quarter, year = _parse_date_range(event)
        if not date_from or not date_to:
            return _error_response(
                400, "Missing date range (provide quarter+year or date_from+date_to)"
            )

        logger.info(f"Exporting invoices from {date_from} to {date_to}")
        logger.info(f"Filters: direction={config.direction}, "
                    f"document_type={config.document_type}, "
                    f"state_filter={config.state_filter}")

        # Connect to Odoo
        client = OdooClient(
            config.odoo_url, config.odoo_database,
            config.odoo_username, config.odoo_api_key
        )
        client.authenticate()
        logger.info(f"Authenticated as user {client.uid}")

        # Run export
        result = _run_export(config, client, date_from, date_to, quarter, year)

        # Send email via Odoo's mail system (enabled by default if ubl_email is set)
        send_email = event.get("send_email", True)  # Default to True
        if send_email:
            if config.ubl_email:
                _send_ubl_email(config, result, quarter, year, client)
            if config.pdf_email:
                _send_bank_statements_email(config, result, quarter, year, client)

        # Clean response - remove binary data that can't be serialized
        return _clean_response(result)

    except Exception as e:
        logger.exception("Export failed")
        return _error_response(500, str(e))


def _handle_auto_quarterly_export(config: ExportConfig) -> dict:
    """Handle scheduled quarterly export.

    Determines the previous quarter and runs export with email sending.
    """
    today = date.today()

    # Check if today is the configured send day
    if today.day != config.send_day:
        return _success_response({
            "message": f"Not send day (today={today.day}, configured={config.send_day})",
            "skipped": True,
        })

    # Check if we're in a "send month" (Jan, Apr, Jul, Oct)
    send_months = [1, 4, 7, 10]
    if today.month not in send_months:
        return _success_response({
            "message": f"Not a send month (today={today.month})",
            "skipped": True,
        })

    # Determine previous quarter
    quarter_map = {1: ("Q4", -1), 4: ("Q1", 0), 7: ("Q2", 0), 10: ("Q3", 0)}
    quarter, year_offset = quarter_map[today.month]
    year = today.year + year_offset

    logger.info(f"Auto quarterly export for {quarter} {year}")

    # Get date range
    date_from, date_to = get_quarter_dates(quarter, year)

    # Connect to Odoo
    client = OdooClient(
        config.odoo_url, config.odoo_database,
        config.odoo_username, config.odoo_api_key
    )
    client.authenticate()
    logger.info(f"Authenticated as user {client.uid}")

    # Run export
    result = _run_export(config, client, date_from, date_to, quarter, str(year))

    # Send emails via Odoo's mail system
    if config.ubl_email:
        _send_ubl_email(config, result, quarter, str(year), client)
    if config.pdf_email:
        _send_bank_statements_email(config, result, quarter, str(year), client)

    return _clean_response(result)


def _run_export(
    config: ExportConfig,
    client: OdooClient,
    date_from: date,
    date_to: date,
    quarter: str | None,
    year: str | None,
) -> dict:
    """Run the actual export process.

    Args:
        config: Export configuration
        client: Authenticated Odoo client
        date_from: Start date
        date_to: End date
        quarter: Quarter string (for filename)
        year: Year string (for filename)

    Returns:
        Response dict with export results
    """
    # Get company info
    company = client.get_company()
    logger.info(f"Company: {company.get('name')}")

    # Build domain for invoice search
    move_types = config.get_move_types()
    if not move_types:
        return _success_response({
            "message": "No move types selected (check direction/document_type filters)",
            "count": 0,
        })

    # Fetch invoices with filters
    invoices = _fetch_invoices(client, config, date_from, date_to, move_types)
    logger.info(f"Found {len(invoices)} invoices")

    if not invoices:
        return _success_response({
            "message": "No invoices found for the specified criteria",
            "count": 0,
            "filters": {
                "direction": config.direction,
                "document_type": config.document_type,
                "state_filter": config.state_filter,
            },
        })

    # Fetch related data (lines, partners, taxes, products)
    lines_by_invoice, partners, taxes, products = _fetch_related_data(
        client, invoices
    )

    # Generate UBL files
    generator = UBLGenerator(company)
    ubl_files = []  # List of (filename, xml_bytes)

    if config.embed_pdf:
        logger.info("PDF embedding enabled - will fetch invoice PDFs from Odoo")

    for invoice in invoices:
        try:
            # Determine invoice number for UBL and filename
            # For vendor bills (in_invoice, in_refund): prefer vendor's reference (ref)
            # For customer invoices (out_invoice, out_refund): use Odoo's name
            move_type = invoice.get("move_type", "")
            invoice_name = invoice.get("name")
            vendor_ref = invoice.get("ref")

            if move_type in ("in_invoice", "in_refund"):
                # Vendor bill - use vendor's invoice reference
                if vendor_ref and vendor_ref is not False:
                    ubl_number = vendor_ref
                elif invoice_name and invoice_name is not False and invoice_name != "/":
                    ubl_number = invoice_name
                else:
                    # Generate from ID if nothing else available
                    ubl_number = f"BILL-{invoice.get('id')}"
                    logger.warning(f"Using generated number {ubl_number} for vendor bill (no ref or name)")
            else:
                # Customer invoice - use Odoo's name
                if invoice_name and invoice_name is not False and invoice_name != "/":
                    ubl_number = invoice_name
                else:
                    logger.warning(f"Skipping customer invoice {invoice.get('id')} - no invoice number")
                    continue

            partner_id = invoice.get("partner_id")
            if isinstance(partner_id, (list, tuple)):
                partner_id = partner_id[0]
            partner = partners.get(partner_id, {})

            lines = lines_by_invoice.get(invoice["id"], [])

            # Override invoice name with our determined UBL number
            invoice_copy = dict(invoice)
            invoice_copy["_ubl_number"] = ubl_number

            # Fetch invoice PDF if embedding is enabled
            pdf_content = None
            if config.embed_pdf:
                pdf_content = client.get_invoice_pdf(invoice["id"])
                if pdf_content:
                    logger.info(f"Fetched PDF for {ubl_number}: {len(pdf_content)} bytes")
                else:
                    logger.warning(f"Could not fetch PDF for {ubl_number}")

            xml_content = generator.generate_invoice(
                invoice_copy, partner, lines, taxes, products, pdf_content=pdf_content
            )

            filename = f"{ubl_number.replace('/', '-').replace(' ', '_')}.{config.ubl_file_extension}"
            ubl_files.append((filename, xml_content))
            logger.info(f"Generated UBL for {ubl_number} (type: {move_type}, pdf_embedded={pdf_content is not None})")

        except Exception as e:
            logger.error(f"Failed to generate UBL for invoice {invoice.get('id')}: {e}")

    # Fetch and render bank statements if enabled
    statement_pdfs = []  # List of (filename, pdf_bytes)
    logger.info(f"Bank statements enabled: {config.include_bank_statements}")
    if config.include_bank_statements:
        statement_pdfs = _export_bank_statements(
            client, config, date_from, date_to
        )
        logger.info(f"Exported {len(statement_pdfs)} bank statement PDFs")

    # Create ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add UBL files
        for filename, xml_content in ubl_files:
            zf.writestr(f"UBL/{filename}", xml_content)

        # Add bank statement PDFs
        for filename, pdf_content in statement_pdfs:
            zf.writestr(f"BankStatements/{filename}", pdf_content)

    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()

    # Generate filename
    if quarter and year:
        zip_filename = f"Export_{year}_{quarter}.zip"
    else:
        zip_filename = f"Export_{date_from}_{date_to}.zip"

    # Store result
    result_data = {
        "message": f"Exported {len(ubl_files)} invoices, {len(statement_pdfs)} bank statements",
        "invoice_count": len(ubl_files),
        "statement_count": len(statement_pdfs),
        "total_invoices_found": len(invoices),
        "filename": zip_filename,
        "company": company.get("name"),
        "period": {
            "from": str(date_from),
            "to": str(date_to),
            "quarter": quarter,
            "year": year,
        },
        "filters": {
            "direction": config.direction,
            "document_type": config.document_type,
            "state_filter": config.state_filter,
            "include_bank_statements": config.include_bank_statements,
        },
    }

    # Upload to S3 if configured
    if config.s3_bucket:
        import boto3
        s3 = boto3.client("s3")
        s3_key = f"exports/{zip_filename}"
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=s3_key,
            Body=zip_data,
            ContentType="application/zip",
        )
        logger.info(f"Uploaded to s3://{config.s3_bucket}/{s3_key}")

        # Generate presigned URL
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": config.s3_bucket, "Key": s3_key},
            ExpiresIn=3600,
        )

        result_data["s3_bucket"] = config.s3_bucket
        result_data["s3_key"] = s3_key
        result_data["download_url"] = presigned_url
        result_data["_zip_data"] = zip_data  # For email sending
        result_data["_ubl_files"] = ubl_files  # For email sending (individual XMLs)
        result_data["_statement_files"] = statement_pdfs  # For bank statement email

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({k: v for k, v in result_data.items() if not k.startswith("_")}),
            "_zip_data": zip_data,
            "_ubl_files": ubl_files,
            "_result_data": result_data,
        }

    else:
        # Return base64 encoded ZIP directly
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/zip",
                "Content-Disposition": f"attachment; filename={zip_filename}",
            },
            "body": base64.b64encode(zip_data).decode("utf-8"),
            "isBase64Encoded": True,
            "_result_data": result_data,  # Metadata
        }


def _fetch_invoices(
    client: OdooClient,
    config: ExportConfig,
    date_from: date,
    date_to: date,
    move_types: list[str],
) -> list[dict]:
    """Fetch invoices with all configured filters.

    Args:
        client: Odoo client
        config: Export configuration
        date_from: Start date
        date_to: End date
        move_types: List of move types to include

    Returns:
        List of invoice dictionaries
    """
    # Build domain
    domain = [
        ("move_type", "in", move_types),
        ("invoice_date", ">=", date_from.isoformat()),
        ("invoice_date", "<=", date_to.isoformat()),
    ]

    # Add state filter
    state_domain = config.get_state_domain()
    domain.extend(state_domain)

    # Add custom domain if specified
    custom_domain = config.parse_custom_domain()
    if custom_domain:
        # For simple domains, we can apply them
        # Complex OR domains may not work perfectly via XML-RPC
        for clause in custom_domain:
            if isinstance(clause, (list, tuple)) and len(clause) == 3:
                domain.append(tuple(clause))

    logger.info(f"Invoice search domain: {domain}")

    fields = [
        "id", "name", "move_type", "state", "invoice_date", "invoice_date_due",
        "partner_id", "currency_id", "amount_untaxed", "amount_tax",
        "amount_total", "payment_reference", "narration", "invoice_line_ids",
        "company_id", "ref",
    ]

    return client.search_read(
        "account.move", domain, fields=fields, order="invoice_date, name"
    )


def _fetch_related_data(
    client: OdooClient, invoices: list[dict]
) -> tuple[dict, dict, dict, dict]:
    """Fetch all related data for invoices.

    Args:
        client: Odoo client
        invoices: List of invoice dicts

    Returns:
        Tuple of (lines_by_invoice, partners, taxes, products)
    """
    all_line_ids = []
    all_partner_ids = set()
    all_tax_ids = set()
    all_product_ids = set()

    for invoice in invoices:
        all_line_ids.extend(invoice.get("invoice_line_ids", []))
        if invoice.get("partner_id"):
            partner_id = invoice["partner_id"]
            if isinstance(partner_id, (list, tuple)):
                partner_id = partner_id[0]
            all_partner_ids.add(partner_id)

    # Fetch lines
    lines_by_invoice = {}
    if all_line_ids:
        all_lines = client.get_invoice_lines(all_line_ids)
        for line in all_lines:
            move_id = line.get("move_id")
            if isinstance(move_id, (list, tuple)):
                move_id = move_id[0]
            if move_id not in lines_by_invoice:
                lines_by_invoice[move_id] = []
            lines_by_invoice[move_id].append(line)

            # Collect tax and product IDs
            for tax_id in line.get("tax_ids", []):
                all_tax_ids.add(tax_id)
            product_id = line.get("product_id")
            if product_id:
                if isinstance(product_id, (list, tuple)):
                    product_id = product_id[0]
                all_product_ids.add(product_id)

    # Fetch partners
    partners = {}
    if all_partner_ids:
        partner_list = client.read("res.partner", list(all_partner_ids), [
            "id", "name", "vat", "street", "street2", "city", "zip",
            "country_id", "email", "phone"
        ])
        partners = {p["id"]: p for p in partner_list}

    # Fetch taxes
    taxes = {}
    if all_tax_ids:
        tax_list = client.get_taxes(list(all_tax_ids))
        taxes = {t["id"]: t for t in tax_list}

    # Fetch products
    products = {}
    if all_product_ids:
        product_list = client.get_products(list(all_product_ids))
        products = {p["id"]: p for p in product_list}

    return lines_by_invoice, partners, taxes, products


def _generate_bank_transactions_pdf(statement_lines: list[dict], date_from: date, date_to: date) -> bytes:
    """Generate a PDF report of bank transaction lines.

    Args:
        statement_lines: List of bank statement line dicts from Odoo
        date_from: Start date of the period
        date_to: End date of the period

    Returns:
        PDF content as bytes
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    import io

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=20,
        textColor=colors.gray,
    )

    elements = []

    # Title
    elements.append(Paragraph("Bank Transactions Report", title_style))
    elements.append(Paragraph(
        f"Period: {date_from.strftime('%d-%m-%Y')} to {date_to.strftime('%d-%m-%Y')} | "
        f"Total transactions: {len(statement_lines)}",
        subtitle_style
    ))

    # Calculate totals
    total_credit = sum(line.get("amount", 0) for line in statement_lines if line.get("amount", 0) > 0)
    total_debit = sum(line.get("amount", 0) for line in statement_lines if line.get("amount", 0) < 0)

    # Table header
    table_data = [[
        "Date",
        "Journal",
        "Reference",
        "Partner",
        "Debit",
        "Credit",
    ]]

    # Data rows
    for line in statement_lines:
        journal_name = ""
        if line.get("journal_id"):
            journal_data = line["journal_id"]
            if isinstance(journal_data, (list, tuple)) and len(journal_data) > 1:
                journal_name = journal_data[1]

        partner_name = ""
        if line.get("partner_id"):
            partner_data = line["partner_id"]
            if isinstance(partner_data, (list, tuple)) and len(partner_data) > 1:
                partner_name = partner_data[1]

        amount = line.get("amount", 0)
        debit = f"€ {abs(amount):,.2f}" if amount < 0 else ""
        credit = f"€ {amount:,.2f}" if amount > 0 else ""

        # Truncate long strings
        ref = line.get("payment_ref") or line.get("name", "")
        if len(ref) > 40:
            ref = ref[:37] + "..."
        if len(partner_name) > 30:
            partner_name = partner_name[:27] + "..."

        table_data.append([
            line.get("date", ""),
            journal_name,
            ref,
            partner_name,
            debit,
            credit,
        ])

    # Add totals row
    table_data.append([
        "", "", "", "TOTALS:",
        f"€ {abs(total_debit):,.2f}",
        f"€ {total_credit:,.2f}",
    ])

    # Create table
    col_widths = [22*mm, 35*mm, 80*mm, 60*mm, 30*mm, 30*mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        # Header style
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),

        # Data rows style
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -2), 4),
        ('TOPPADDING', (0, 1), (-1, -2), 4),

        # Totals row style
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ecf0f1')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
        ('TOPPADDING', (0, -1), (-1, -1), 8),

        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8f9fa')]),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),

        # Alignment
        ('ALIGN', (4, 0), (5, -1), 'RIGHT'),  # Amount columns right-aligned
    ]))

    elements.append(table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


def _export_bank_statements(
    client: OdooClient,
    config: ExportConfig,
    date_from: date,
    date_to: date,
) -> list[tuple[str, bytes]]:
    """Export bank statements as PDFs.

    Args:
        client: Odoo client
        config: Export configuration
        date_from: Start date
        date_to: End date

    Returns:
        List of (filename, pdf_bytes) tuples
    """
    statement_pdfs = []

    try:
        # Get journal IDs to filter by (if specified)
        journal_ids = config.bank_journal_ids if config.bank_journal_ids else None

        # Fetch bank statements (the document model)
        statements = client.get_bank_statements(date_from, date_to, journal_ids)
        logger.info(f"Found {len(statements)} bank statements (account.bank.statement)")

        # Also check for statement lines (transactions) - in Odoo 14+ these may exist without statements
        statement_lines = []
        try:
            statement_lines = client.get_bank_statement_lines(date_from, date_to, journal_ids)
            logger.info(f"Found {len(statement_lines)} bank transaction lines (account.bank.statement.line)")
        except Exception as e:
            logger.warning(f"Could not fetch statement lines: {e}")

        # If no formal statements but we have transaction lines, generate PDF report
        if not statements and statement_lines:
            logger.info("No formal statements, generating PDF report from transaction lines")
            pdf_content = _generate_bank_transactions_pdf(statement_lines, date_from, date_to)
            if pdf_content:
                statement_pdfs.append(("Bank_Transactions.pdf", pdf_content))
                logger.info(f"Generated bank transactions PDF with {len(statement_lines)} transactions")
            # Return the PDF - no formal statements to process
            return statement_pdfs

        if not statements:
            return statement_pdfs  # Return whatever we have (might be empty)

        # Try to render each statement as PDF
        for statement in statements:
            try:
                statement_id = statement["id"]
                statement_name = statement.get("name") or f"Statement_{statement_id}"
                journal_name = "Bank"
                
                if statement.get("journal_id"):
                    journal_data = statement["journal_id"]
                    if isinstance(journal_data, (list, tuple)) and len(journal_data) > 1:
                        journal_name = journal_data[1]

                # Try to render PDF via Odoo's report engine
                pdf_data = client.render_report_pdf(
                    "account.report_bank_statement",
                    [statement_id]
                )

                if pdf_data:
                    # Clean filename
                    safe_name = statement_name.replace("/", "-").replace("\\", "-")
                    safe_journal = journal_name.replace("/", "-").replace("\\", "-")
                    filename = f"{safe_journal}/{safe_name}.pdf"
                    statement_pdfs.append((filename, pdf_data))
                    logger.info(f"Generated PDF for statement {statement_name}")
                else:
                    logger.warning(f"Could not render PDF for statement {statement_name}")

            except Exception as e:
                logger.error(f"Failed to export statement {statement.get('name')}: {e}")

    except Exception as e:
        logger.error(f"Failed to fetch bank statements: {e}")

    return statement_pdfs


def _send_ubl_email(
    config: ExportConfig,
    result: dict,
    quarter: str,
    year: str,
    odoo_client: OdooClient,
) -> bool:
    """Send UBL export via Odoo's email system.

    Args:
        config: Export configuration
        result: Export result dict
        quarter: Quarter string
        year: Year string
        odoo_client: Connected Odoo client for sending email

    Returns:
        True if sent successfully
    """
    if not config.ubl_email:
        logger.warning("UBL email not configured, skipping")
        return False

    try:
        # Get UBL files directly (preferred) or extract from ZIP
        ubl_files = result.get("_ubl_files")
        
        if ubl_files:
            # Use pre-generated UBL files directly
            attachments = [
                (filename, xml_data, "application/xml")
                for filename, xml_data in ubl_files
            ]
        else:
            # Fallback: try to get ZIP data and extract
            zip_data = result.get("_zip_data")
            if not zip_data:
                # Try to get from nested _result_data
                result_data = result.get("_result_data", {})
                zip_data = result_data.get("_zip_data")
            
            if not zip_data and config.s3_bucket:
                # Download from S3
                import boto3
                s3 = boto3.client("s3")
                s3_key = result.get("s3_key") or result.get("_result_data", {}).get("s3_key")
                if s3_key:
                    logger.info(f"Downloading ZIP from S3: {s3_key}")
                    response = s3.get_object(Bucket=config.s3_bucket, Key=s3_key)
                    zip_data = response["Body"].read()

            if not zip_data:
                logger.error("No ZIP data available for email")
                return False

            # Extract individual UBL files for BilltoBox
            attachments = []
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                for name in zf.namelist():
                    if name.endswith((".xml", ".ubl")):
                        xml_data = zf.read(name)
                        filename = name.split("/")[-1]  # Remove UBL/ prefix
                        attachments.append((filename, xml_data, "application/xml"))

        if not attachments:
            logger.warning("No UBL files to send")
            return False

        # Get company name from result
        company_name = result.get("company") or result.get("_result_data", {}).get("company", "Unknown Company")
        body = result.get("body", {})
        if isinstance(body, str):
            try:
                body = json.loads(body)
                company_name = body.get("company", company_name)
            except json.JSONDecodeError:
                pass

        logger.info(f"Sending {len(attachments)} UBL files to {config.ubl_email} (as_zip={config.send_ubl_as_zip})")

        # Send email via Odoo
        sender = OdooEmailSender(odoo_client)
        return sender.send_ubl_export(
            recipient=config.ubl_email,
            company_name=company_name,
            quarter=quarter or "Export",
            year=year or str(date.today().year),
            attachments=attachments,
            as_zip=config.send_ubl_as_zip,
        )

    except Exception as e:
        logger.exception(f"Failed to send email via Odoo: {e}")
        return False


def _send_bank_statements_email(
    config: ExportConfig,
    result: dict,
    quarter: str,
    year: str,
    odoo_client: OdooClient,
) -> bool:
    """Send bank statements/transactions via Odoo's email system.

    Args:
        config: Export configuration
        result: Export result dict
        quarter: Quarter string
        year: Year string
        odoo_client: Connected Odoo client for sending email

    Returns:
        True if sent successfully
    """
    if not config.pdf_email:
        logger.warning("PDF email not configured, skipping bank statements email")
        return False

    try:
        # Get statement files from result
        statement_files = result.get("_statement_files") or result.get("_result_data", {}).get("_statement_files", [])
        
        if not statement_files:
            logger.info("No bank statement files to send")
            return False

        # Convert to attachment format
        attachments = []
        for filename, data in statement_files:
            mimetype = "application/pdf" if filename.endswith(".pdf") else "text/csv"
            attachments.append((filename, data, mimetype))

        if not attachments:
            logger.warning("No attachments for bank statements email")
            return False

        # Get company name from result
        company_name = result.get("company") or result.get("_result_data", {}).get("company", "Unknown Company")

        logger.info(f"Sending {len(attachments)} bank statement files to {config.pdf_email}")

        # Send email via Odoo
        sender = OdooEmailSender(odoo_client)
        return sender.send_statement_export(
            recipient=config.pdf_email,
            company_name=company_name,
            quarter=quarter or "Export",
            year=year or str(date.today().year),
            zip_data=attachments[0][1] if len(attachments) == 1 else None,
            zip_filename=attachments[0][0] if len(attachments) == 1 else "BankStatements.zip",
            statement_count=len(attachments),
            bank_accounts=["Bank"],  # Could be enhanced to list actual accounts
        ) if len(attachments) == 1 else _send_multiple_statement_files(
            sender, config.pdf_email, company_name, quarter, year, attachments
        )

    except Exception as e:
        logger.exception(f"Failed to send bank statements email via Odoo: {e}")
        return False


def _send_multiple_statement_files(
    sender: OdooEmailSender,
    recipient: str,
    company_name: str,
    quarter: str,
    year: str,
    attachments: list[tuple[str, bytes, str]],
) -> bool:
    """Send multiple statement files bundled in a ZIP."""
    import io
    import zipfile
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, data, mimetype in attachments:
            zf.writestr(filename, data)
    
    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()
    
    return sender.send_statement_export(
        recipient=recipient,
        company_name=company_name,
        quarter=quarter,
        year=year,
        zip_data=zip_data,
        zip_filename=f"BankStatements_{quarter}_{year}.zip",
        statement_count=len(attachments),
        bank_accounts=["Bank"],
    )


def _parse_date_range(event: dict) -> tuple[date | None, date | None, str | None, str | None]:
    """Parse date range from event.

    Args:
        event: Lambda event

    Returns:
        Tuple of (date_from, date_to, quarter, year)
    """
    # Try quarter + year first
    quarter = event.get("quarter")
    year = event.get("year")
    if quarter and year:
        date_from, date_to = get_quarter_dates(quarter, int(year))
        return date_from, date_to, quarter, str(year)

    # Try explicit date range
    date_from_str = event.get("date_from")
    date_to_str = event.get("date_to")
    if date_from_str and date_to_str:
        return (
            date.fromisoformat(date_from_str),
            date.fromisoformat(date_to_str),
            None,
            None,
        )

    return None, None, None, None


def _clean_response(result: dict) -> dict:
    """Clean response by removing binary data that can't be serialized.

    Args:
        result: Response dict that may contain binary data

    Returns:
        Clean response dict safe for JSON serialization
    """
    # If it's already a proper API response with statusCode
    if "statusCode" in result:
        # Remove internal binary fields
        clean_result = {
            "statusCode": result["statusCode"],
            "headers": result.get("headers", {"Content-Type": "application/json"}),
        }
        
        # If body is already a JSON string, keep it
        if "body" in result and isinstance(result["body"], str):
            clean_result["body"] = result["body"]
        else:
            # Create body from result_data if available
            result_data = result.get("_result_data", {})
            clean_data = {k: v for k, v in result_data.items() if not k.startswith("_")}
            clean_result["body"] = json.dumps(clean_data) if clean_data else result.get("body", "{}")
        
        return clean_result
    
    # Otherwise just return as-is (shouldn't happen)
    return result


def _success_response(data: dict) -> dict:
    """Create success response."""
    # Remove internal keys
    clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(clean_data),
    }


def _error_response(status_code: int, message: str) -> dict:
    """Create error response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


# For local testing
if __name__ == "__main__":
    import sys

    # Load from .env file if present
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    # Default to previous quarter
    today = date.today()
    current_quarter = (today.month - 1) // 3 + 1
    if current_quarter == 1:
        quarter = "Q4"
        year = today.year - 1
    else:
        quarter = f"Q{current_quarter - 1}"
        year = today.year

    # Parse command line args
    if len(sys.argv) >= 3:
        quarter = sys.argv[1]
        year = int(sys.argv[2])

    event = {
        "quarter": quarter,
        "year": year,
    }

    # Optional: override filters via args
    if len(sys.argv) >= 4:
        event["direction"] = sys.argv[3]  # e.g., "outgoing"
    if len(sys.argv) >= 5:
        event["state_filter"] = sys.argv[4]  # e.g., "posted_draft"

    print(f"Testing export for {quarter} {year}...")
    print(f"Filters: direction={event.get('direction', 'both')}, "
          f"state={event.get('state_filter', 'posted')}")

    result = lambda_handler(event, None)
    print(f"Status: {result['statusCode']}")

    if result.get("isBase64Encoded"):
        # Save ZIP file
        zip_data = base64.b64decode(result["body"])
        filename = result["headers"].get("Content-Disposition", "").split("filename=")[-1]
        if not filename:
            filename = f"export_{quarter}_{year}.zip"
        with open(filename, "wb") as f:
            f.write(zip_data)
        print(f"Saved to {filename}")
    else:
        print(result["body"])
