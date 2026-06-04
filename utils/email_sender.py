import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def send_receipt_email(
    smtp_server: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_email: str,
    to_emails: str,
    member_name: str,
    plot_no: str,
    pdf_path: Optional[Path] = None,
    cc_email: Optional[str] = None,
) -> bool:
    recipients = [e.strip() for e in to_emails.split(",") if e.strip()]
    if not recipients:
        logger.warning("No recipient emails")
        return False

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Payment Receipt - {member_name} (Plot {plot_no})"
    msg["From"] = from_email
    msg["To"] = ", ".join(recipients)
    if cc_email:
        msg["Cc"] = cc_email
        recipients += [e.strip() for e in cc_email.split(",") if e.strip()]

    body = MIMEText(
        f"Dear {member_name},\n\n"
        f"Please find attached the receipt for your payment (Plot {plot_no}).\n\n"
        f"Thank you,\nWeekend Ville Maintenance Co-Op. Society Ltd"
    )
    msg.attach(body)

    if pdf_path and pdf_path.exists():
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{pdf_path.name}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, recipients, msg.as_string())
        logger.info(f"Receipt email sent to {recipients}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False