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
