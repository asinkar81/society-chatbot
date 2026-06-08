"""
WhatsApp sharing utilities — message builder, wa.me links, clipboard.
"""
import subprocess
import shutil
import urllib.parse
from typing import Optional, List, Dict


def _fmt_amt(amount) -> str:
    try:
        return f"₹{float(amount):,.2f}"
    except (ValueError, TypeError):
        return f"₹{amount}"


def _summary_text(summary: Optional[Dict]) -> str:
    if not summary:
        return ""
    lines = [
        "Summary:",
        f"  Balance carried forward: {_fmt_amt(summary.get('previous_outstanding', 0))}",
        f"  New Invoice Demand: {_fmt_amt(summary.get('total_demand', 0))}",
        f"  Payments Received: {_fmt_amt(summary.get('total_payments', 0))}",
        f"  Total Outstanding as of {summary.get('as_of_date', '')}: {_fmt_amt(summary.get('total_due', 0))}",
    ]
    return "\n".join(lines)


def build_wa_message(
    template_type: str,
    member: dict,
    summary: Optional[dict] = None,
    entries: Optional[List[dict]] = None,
    pdf_names: Optional[List[str]] = None,
) -> str:
    plot = member.get("Plot_No", "")
    name = member.get("Plot_Owner_Name", "")

    lines = [
        f"Weekend Ville Society",
        f"Plot {plot} — {name}",
    ]

    if template_type == "receipt":
        if entries:
            e = entries[0]
            lines.append(f"\nDear {name}, a payment of {_fmt_amt(e.get('amount', 0))} has been received for your plot at Weekend Ville Society.")
            lines.append(f"Receipt: {e.get('ref_id', '')}, Date: {e.get('date', '')}")
    elif template_type == "invoice":
        lines.append(f"\nDear {name}, your invoice for Plot {plot} at Weekend Ville Society is ready.")
    elif template_type == "statement":
        lines.append(f"\nDear {name}, your statement for Plot {plot} at Weekend Ville Society.")
    elif template_type == "reminder":
        lines.append(f"\nDear {name}, a gentle reminder for outstanding dues for Plot {plot} at Weekend Ville Society.")

    s = _summary_text(summary)
    if s:
        lines.append("")
        lines.append(s)

    pdf_names = pdf_names or []
    if pdf_names:
        lines.append("")
        lines.append("Attached Documents:")
        for i, pn in enumerate(pdf_names, 1):
            lines.append(f"  {i}. {pn}")

    return "\n".join(lines)


def build_wa_link(phone: str, text: str, country_code: str = "91") -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith(country_code):
        full = digits
    else:
        full = country_code + digits.lstrip("0")
    encoded = urllib.parse.quote(text)
    return f"https://wa.me/{full}?text={encoded}"


def copy_to_clipboard(text: str) -> bool:
    if shutil.which("pbcopy"):
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    return False
