# -*- coding: utf-8 -*-
"""Email sender using Odoo's mail system."""

import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OdooEmailSender:
    """Send emails through Odoo's mail system via XML-RPC API."""

    def __init__(self, odoo_client):
        """Initialize with Odoo client.

        Args:
            odoo_client: Connected OdooClient instance
        """
        self.client = odoo_client

    def send_ubl_export(
        self,
        recipient: str,
        company_name: str,
        quarter: str,
        year: str,
        attachments: list[tuple[str, bytes, str]],
        subject_prefix: str = "",
    ) -> bool:
        """Send UBL XML files via Odoo email.

        Args:
            recipient: Recipient email address
            company_name: Company name for email subject
            quarter: Quarter (Q1, Q2, Q3, Q4)
            year: Year
            attachments: List of (filename, data, mimetype) tuples
            subject_prefix: Optional prefix for subject

        Returns:
            True if sent successfully
        """
        subject = f"{subject_prefix}{company_name} - UBL Export {quarter} {year}".strip()
        body = f"""
<p>Quarterly UBL export for <strong>{quarter} {year}</strong></p>
<p><strong>Company:</strong> {company_name}</p>
<p><strong>Documents:</strong> {len(attachments)} invoice(s)</p>
<hr/>
<p><em>This email was sent automatically via Odoo.</em></p>
"""
        return self._send_mail(recipient, subject, body, attachments)

    def send_statement_export(
        self,
        recipient: str,
        company_name: str,
        quarter: str,
        year: str,
        zip_data: bytes,
        zip_filename: str,
        statement_count: int,
        bank_accounts: list[str],
    ) -> bool:
        """Send bank statement PDFs via Odoo email.

        Args:
            recipient: Recipient email address
            company_name: Company name for email subject
            quarter: Quarter (Q1, Q2, Q3, Q4)
            year: Year
            zip_data: ZIP file content
            zip_filename: ZIP filename
            statement_count: Number of statements
            bank_accounts: List of bank account names

        Returns:
            True if sent successfully
        """
        subject = f"{company_name} - Bank Statements {quarter} {year}"
        body = f"""
<p>Quarterly bank statements for <strong>{quarter} {year}</strong></p>
<p><strong>Company:</strong> {company_name}</p>
<p><strong>Statements:</strong> {statement_count}</p>
<p><strong>Bank Accounts:</strong> {', '.join(bank_accounts)}</p>
<hr/>
<p><em>This email was sent automatically via Odoo.</em></p>
"""
        attachments = [(zip_filename, zip_data, "application/zip")]
        return self._send_mail(recipient, subject, body, attachments)

    def send_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        download_url: Optional[str] = None,
    ) -> bool:
        """Send a simple notification email.

        Args:
            recipient: Recipient email address
            subject: Email subject
            body: Plain text body
            download_url: Optional download URL

        Returns:
            True if sent successfully
        """
        body_html = f"<p>{body.replace(chr(10), '<br/>')}</p>"
        if download_url:
            body_html += f'<p><a href="{download_url}">Download Export</a></p>'

        return self._send_mail(recipient, subject, body_html, [])

    def _send_mail(
        self,
        recipient: str,
        subject: str,
        body_html: str,
        attachments: list[tuple[str, bytes, str]],
    ) -> bool:
        """Send email via Odoo mail.mail model.

        Args:
            recipient: Recipient email address
            subject: Email subject
            body_html: HTML email body
            attachments: List of (filename, data, mimetype) tuples

        Returns:
            True if sent successfully
        """
        try:
            # Create mail.mail record
            mail_values = {
                "email_to": recipient,
                "subject": subject,
                "body_html": body_html,
                "auto_delete": True,
            }

            mail_id = self.client.execute(
                "mail.mail", "create", mail_values
            )
            logger.info(f"Created mail.mail record {mail_id}")

            # Add attachments if any
            if attachments:
                attachment_ids = []
                for filename, data, mimetype in attachments:
                    # Encode data to base64
                    if isinstance(data, bytes):
                        data_b64 = base64.b64encode(data).decode("utf-8")
                    else:
                        data_b64 = base64.b64encode(data.encode()).decode("utf-8")

                    att_values = {
                        "name": filename,
                        "datas": data_b64,
                        "mimetype": mimetype,
                        "res_model": "mail.mail",
                        "res_id": mail_id,
                    }
                    att_id = self.client.execute(
                        "ir.attachment", "create", att_values
                    )
                    attachment_ids.append(att_id)
                    logger.info(f"Created attachment {att_id}: {filename}")

                # Link attachments to mail
                self.client.execute(
                    "mail.mail", "write", [mail_id],
                    {"attachment_ids": [(6, 0, attachment_ids)]}
                )

            # Send the email
            self.client.execute("mail.mail", "send", [mail_id])
            logger.info(f"Email sent to {recipient}: {subject}")

            return True

        except Exception as e:
            logger.error(f"Failed to send email via Odoo: {e}")
            return False


def send_export_via_odoo(
    odoo_client,
    recipient: str,
    company_name: str,
    quarter: str,
    year: str,
    attachments: list[tuple[str, bytes, str]],
) -> bool:
    """Convenience function to send UBL export via Odoo.

    Args:
        odoo_client: Connected OdooClient instance
        recipient: Recipient email address
        company_name: Company name
        quarter: Quarter string
        year: Year string
        attachments: List of (filename, data, mimetype) tuples

    Returns:
        True if sent successfully
    """
    sender = OdooEmailSender(odoo_client)
    return sender.send_ubl_export(
        recipient=recipient,
        company_name=company_name,
        quarter=quarter,
        year=year,
        attachments=attachments,
    )
