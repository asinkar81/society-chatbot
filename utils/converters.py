"""
Utility converters: number to words, date formatting, etc.
"""
from num2words import num2words
from datetime import datetime, timedelta
from typing import Optional


def number_to_words_inr(amount: float) -> str:
    """
    Convert number to INR words
    Example: 53000 -> "Rupees Fifty Three Thousand"
    """
    try:
        amount = int(amount)
        words = num2words(amount, lang="en_IN")
        # Clean up and format
        words = words.replace("crore", "Crore").replace("lakh", "Lakh").replace("thousand", "Thousand")
        return f"Rupees {words.capitalize()}"
    except Exception as e:
        return f"Rupees {amount:.2f}"


def format_amount(amount: float) -> str:
    """Format amount with currency symbol and commas"""
    return f"₹ {amount:,.2f}"


def format_date(date_obj: datetime, format_str: str = "%d-%m-%Y") -> str:
    """Format datetime object"""
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.strptime(date_obj, "%d-%m-%Y")
        except:
            return date_obj
    return date_obj.strftime(format_str)


def parse_date(date_str: str, format_str: str = "%d-%m-%Y") -> Optional[datetime]:
    """Parse date string"""
    try:
        return datetime.strptime(date_str, format_str)
    except:
        return None


def get_due_date(days: int = 60) -> str:
    """Get due date N days from now in DD-MM-YYYY format"""
    due = datetime.now() + timedelta(days=days)
    return due.strftime("%d-%m-%Y")


def get_current_date() -> str:
    """Get current date in DD-MM-YYYY format"""
    return datetime.now().strftime("%d-%m-%Y")


def get_fy_string(from_month: int = 4) -> str:
    """
    Get financial year string (e.g., "2026-27")
    from_month: Start month of FY (4 for April)
    """
    today = datetime.now()
    if today.month >= from_month:
        fy_start = today.year
    else:
        fy_start = today.year - 1
    fy_end = fy_start + 1
    return f"{fy_start % 100}-{fy_end % 100}"


def get_fy_from_date(date_str: str) -> str:
    """Get FY string (e.g., '26-27') from a DD-MM-YYYY date string."""
    try:
        parts = date_str.split("-")
        if len(parts) != 3:
            return get_fy_string()
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        if month >= 4:
            fy_start = year
        else:
            fy_start = year - 1
        fy_end = fy_start + 1
        return f"{fy_start % 100}-{fy_end % 100}"
    except (ValueError, IndexError):
        return get_fy_string()


def get_bill_period(from_month: int = 4) -> str:
    """
    Get bill period (e.g., "Apr26 to Mar27")
    """
    today = datetime.now()
    if today.month >= from_month:
        fy_start = today.year
    else:
        fy_start = today.year - 1
    fy_end = fy_start + 1

    month_names = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    from_month_name = month_names[from_month - 1]
    end_month_name = month_names[from_month - 2]  # Month before from_month

    return f"{from_month_name}{fy_start % 100} to {end_month_name}{fy_end % 100}"


def parse_dmy(date_str: str) -> datetime:
    """Parse DD-MM-YYYY string to datetime, returning datetime.min on failure."""
    try:
        return datetime.strptime(str(date_str).strip(), "%d-%m-%Y")
    except (ValueError, AttributeError):
        return datetime.min


def compute_outstanding_as_of(ledger: list, as_of_date: str) -> float:
    """Sum credits - debits from ledger entries up to and including as_of_date."""
    as_of = parse_dmy(as_of_date)
    total_credit = 0.0
    total_debit = 0.0
    for entry in ledger:
        entry_date = parse_dmy(str(entry.get("Date", "") or "").strip())
        if entry_date <= as_of:
            total_credit += float(entry.get("Credit", 0) or 0)
            total_debit += float(entry.get("Debit", 0) or 0)
    return total_credit - total_debit


def get_payment_history(ledger: list, up_to_date: str) -> list:
    """Return sorted list of all credit (payment) entries up to up_to_date."""
    up_to = parse_dmy(up_to_date)
    payments = []
    for entry in ledger:
        entry_date = parse_dmy(str(entry.get("Date", "") or "").strip())
        if entry_date <= up_to:
            credit = float(entry.get("Credit", 0) or 0)
            if credit > 0:
                payments.append({
                    "date": entry.get("Date", ""),
                    "particulars": str(entry.get("Particulars", "") or "")[:40],
                    "amount": credit,
                })
    payments.sort(key=lambda x: parse_dmy(str(x["date"])))
    return payments


def get_previous_invoices(ledger: list, up_to_date: str) -> list:
    """Return sorted list of all INVOICE debit entries up to up_to_date."""
    up_to = parse_dmy(up_to_date)
    invoices = []
    for entry in ledger:
        entry_date = parse_dmy(str(entry.get("Date", "") or "").strip())
        if entry_date <= up_to:
            debit = float(entry.get("Debit", 0) or 0)
            txn_type = str(entry.get("Transaction_Type", "") or "").strip().upper()
            if debit > 0 and txn_type == "INVOICE":
                invoices.append({
                    "date": entry.get("Date", ""),
                    "description": str(entry.get("Description", "") or "")[:50],
                    "amount": debit,
                })
    invoices.sort(key=lambda x: parse_dmy(str(x["date"])))
    return invoices
