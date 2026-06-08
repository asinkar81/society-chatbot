import smtplib
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


def _sortable_date(dd: str) -> str:
    try:
        p = dd.split("-")
        return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else dd
    except Exception:
        return dd


def _attachments_html(pdf_names: Optional[List[str]]) -> str:
    if not pdf_names:
        return ""
    items = "".join(
        f'<li style="font-size:12px;color:#555;">{n}</li>'
        for n in pdf_names
    )
    return f'<p style="font-size:12px;color:#666;margin:8px 0;">Attachments:</p><ul style="margin:4px 0 12px 0;padding-left:20px;">{items}</ul>'


def _summary_html(summary: Optional[Dict]) -> str:
    if not summary:
        return ""
    prev = summary.get("previous_outstanding", 0)
    demand = summary.get("total_demand", 0)
    payments = summary.get("total_payments", 0)
    due = summary.get("total_due", 0)
    date = summary.get("as_of_date", "")
    return f"""<div style="background:#f8f9fa;border:1px solid #ddd;border-radius:6px;padding:12px;margin:12px 0;">
<table style="width:100%;border-collapse:collapse;">
<tr><td style="padding:4px 8px;border-bottom:1px solid #ddd;">Balance carried forward from previous FY</td>
    <td style="padding:4px 8px;border-bottom:1px solid #ddd;text-align:right;">₹{prev:,.2f}</td></tr>
<tr><td style="padding:4px 8px;border-bottom:1px solid #ddd;">New Invoice Demand for this FY</td>
    <td style="padding:4px 8px;border-bottom:1px solid #ddd;text-align:right;">₹{demand:,.2f}</td></tr>
<tr><td style="padding:4px 8px;border-bottom:1px solid #ddd;">Payments Received in this FY till date</td>
    <td style="padding:4px 8px;border-bottom:1px solid #ddd;text-align:right;">₹{payments:,.2f}</td></tr>
<tr style="font-weight:bold;"><td style="padding:4px 8px;">Total Outstanding as of {date}</td>
    <td style="padding:4px 8px;text-align:right;">₹{due:,.2f}</td></tr>
</table>
</div>"""


def _build_html_body(template_type: str, member_name: str, plot_no: str,
                     fy: str, entries: List[Dict], society: str,
                     pdf_names: Optional[List[str]] = None,
                     summary: Optional[Dict] = None) -> str:
    if template_type == "invoice":
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:0;">
<div style="max-width:600px;margin:20px auto;border:1px solid #ccc;border-radius:8px;overflow:hidden;">
<div style="background:#1a5276;color:#fff;padding:16px 24px;">
<h2 style="margin:0;">{society}</h2>
</div>
<div style="padding:24px;">
<p>Dear <strong>{member_name}</strong> (Plot {plot_no}),</p>
<p>Please find below the invoice summary for FY {fy}:</p>
{_summary_html(summary)}
{_attachments_html(pdf_names)}
<hr style="border:none;border-top:1px solid #eee;margin:16px 0;">
<p style="font-size:12px;color:#888;">This is an auto-generated email. Please do not reply.</p>
</div>
</div>
</body>
</html>"""

    rows_html = ""
    total = 0.0
    sorted_entries = sorted(
        entries,
        key=lambda x: _sortable_date(x.get("date", "")),
    )
    for e in sorted_entries:
        amt = float(e.get("amount", 0))
        typ = e.get("type", "CR")
        if template_type == "statement":
            total += amt if typ == "CR" else -amt
        else:
            total += amt
        date = e.get("date", "")
        ref = e.get("ref_id", "")
        part = e.get("particulars", "")[:40]
        if template_type == "statement":
            type_label = "Receipt" if typ == "CR" else "Invoice"
            rows_html += f"""
        <tr>
            <td style="padding:6px 8px;border:1px solid #ddd;">{date}</td>
            <td style="padding:6px 8px;border:1px solid #ddd;">{ref}</td>
            <td style="padding:6px 8px;border:1px solid #ddd;">{part}</td>
            <td style="padding:6px 8px;border:1px solid #ddd;">{type_label}</td>
            <td style="padding:6px 8px;border:1px solid #ddd;text-align:right;">₹{amt:,.2f}</td>
        </tr>"""
        else:
            rows_html += f"""
        <tr>
            <td style="padding:6px 8px;border:1px solid #ddd;">{date}</td>
            <td style="padding:6px 8px;border:1px solid #ddd;">{ref}</td>
            <td style="padding:6px 8px;border:1px solid #ddd;">{part}</td>
            <td style="padding:6px 8px;border:1px solid #ddd;text-align:right;">{'CR' if typ == 'CR' else 'DR'} ₹{amt:,.2f}</td>
        </tr>"""

    if template_type == "receipt":
        title = "Payment Receipt"
        label = "receipt(s)"
    elif template_type == "statement":
        title = "Statement of Account"
        label = "entries"
    else:
        title = "Payment Reminder"
        label = "outstanding entries"

    summary_section = _summary_html(summary) if template_type == "statement" else ""

    if template_type == "statement":
        header_cols = """<th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Date</th>
<th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Ref</th>
<th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Particulars</th>
<th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Type</th>
<th style="padding:6px 8px;border:1px solid #ddd;text-align:right;">Amount</th>"""
    else:
        header_cols = """<th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Date</th>
<th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Ref</th>
<th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Particulars</th>
<th style="padding:6px 8px;border:1px solid #ddd;text-align:right;">Amount</th>"""

    entries_section = ""
    total_line = ""
    if rows_html:
        if template_type == "statement":
            total_line = f'<p style="font-size:16px;font-weight:bold;text-align:right;">Net Total: ₹{total:,.2f}</p>'
        else:
            total_line = f'<p style="font-size:16px;font-weight:bold;text-align:right;">Total: ₹{total:,.2f}</p>'
        entries_section = f"""<table style="width:100%;border-collapse:collapse;margin:12px 0;">
<tr style="background:#f5f5f5;">
{header_cols}
</tr>
{rows_html}
</table>
{total_line}"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:0;">
<div style="max-width:600px;margin:20px auto;border:1px solid #ccc;border-radius:8px;overflow:hidden;">
<div style="background:#1a5276;color:#fff;padding:16px 24px;">
<h2 style="margin:0;">{society}</h2>
</div>
<div style="padding:24px;">
<p>Dear <strong>{member_name}</strong> (Plot {plot_no}),</p>
<p>Please find below the {label} for FY {fy}:</p>
{summary_section}
{entries_section}
{_attachments_html(pdf_names)}
<hr style="border:none;border-top:1px solid #eee;margin:16px 0;">
<p style="font-size:12px;color:#888;">This is an auto-generated email. Please do not reply.</p>
</div>
</div>
</body>
</html>"""


def _build_subject(template_type: str, member_name: str, plot_no: str,
                   fy: str, amount: Optional[float] = None) -> str:
    if template_type == "receipt":
        base = f"Payment Receipt - {member_name} (Plot {plot_no})"
        if amount:
            base += f" - ₹{amount:,.2f}"
    elif template_type == "invoice":
        base = f"Invoice - {member_name} (Plot {plot_no}) - FY {fy}"
    elif template_type == "statement":
        base = f"Statement of Account - {member_name} (Plot {plot_no}) - FY {fy}"
    else:
        base = f"Reminder: Payment Due - {member_name} (Plot {plot_no}) - FY {fy}"
    return f"Weekend Ville {base}"


def send_template_email(
    smtp_server: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_email: str,
    to_emails: str,
    member_name: str,
    plot_no: str,
    template_type: str = "receipt",
    entries: Optional[List[Dict]] = None,
    pdf_paths: Optional[List[Path]] = None,
    cc_email: Optional[str] = None,
    fy: str = "",
    subject_override: Optional[str] = None,
    body_override: Optional[str] = None,
    summary: Optional[Dict] = None,
) -> Dict:
    """Send a template-based email with optional PDF attachments.
    Returns dict with keys: success (bool), subject (str), error (str).
    """
    def _split_emails(raw: str) -> List[str]:
        if not isinstance(raw, str):
            return []
        return [e.strip() for e in re.split(r'[,;]', raw) if e.strip() and '@' in e.strip()]

    recipients = _split_emails(to_emails)
    if not recipients:
        return {"success": False, "subject": "", "error": "No valid recipient emails", "recipients": ""}

    entries = entries or []
    pdf_paths = pdf_paths or []

    subject = subject_override or _build_subject(template_type, member_name, plot_no, fy)

    soc = "Weekend Ville Maintenance Co-Op. Society Ltd"

    pdf_names = [p.name for p in pdf_paths if p and p.exists()]
    body_html = body_override or _build_html_body(template_type, member_name, plot_no, fy, entries, soc, pdf_names, summary=summary)

    msg = MIMEMultipart("mixed")
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(
        f"Dear {member_name},\n\nPlease see attached {template_type} documents for Plot {plot_no}.\n\nThank you,\n{soc}",
        "plain",
    ))
    alt.attach(MIMEText(body_html, "html"))
    msg.attach(alt)

    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(recipients)
    if cc_email:
        msg["Cc"] = cc_email
        recipients += _split_emails(cc_email)

    for pdf_path in pdf_paths:
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
        logger.info(f"Email sent: {subject} to {recipients}")
        return {"success": True, "subject": subject, "error": "", "recipients": ", ".join(recipients)}
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return {"success": False, "subject": subject, "error": str(e), "recipients": ", ".join(recipients)}


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
    """Backward-compatible wrapper for send_template_email."""
    r = send_template_email(
        smtp_server=smtp_server, smtp_port=smtp_port,
        smtp_user=smtp_user, smtp_pass=smtp_pass,
        from_email=from_email, to_emails=to_emails,
        cc_email=cc_email, member_name=member_name, plot_no=plot_no,
        template_type="receipt",
        pdf_paths=[pdf_path] if pdf_path else [],
    )
    return r["success"]
