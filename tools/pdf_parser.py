import re
import pdfplumber
from typing import List

FORMAT_PROFILES = {
    "email_attachment": {
        "detect": lambda lines: any(
            kw in l for l in lines[:10] for kw in ["e-Statement", "eStatement", "Monthly Statement"]
        ),
    },
    "printed_printout": {
        "detect": lambda lines: any(
            re.search(r"Page\s+\d+\s+(of|/)", l, re.IGNORECASE)
            for l in lines[:15]
        ),
    },
    "netbanking": {
        "detect": lambda lines: any(
            re.match(r"^\d{2}-\d{2}-\d{4}\s+(NEFT|MOBFT|UPI|RTGS|CHQ|IMPS)", l, re.IGNORECASE)
            for l in lines[:20]
        ),
    },
    "serial_number_prefix": {
        "detect": lambda lines: any(
            re.match(r"^\d+\s+\d{2}-\d{2}-\d{4}\s+", l)
            for l in lines[:30]
        ),
    },
}


def extract_text_from_pdf(pdf_path: str, password: str = "") -> str:
    """Extract all text from a PDF file, handling encrypted PDFs."""
    with pdfplumber.open(pdf_path, password=password) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def detect_format(lines: List[str]) -> str:
    """Detect the bank statement format from text lines. Returns profile name or 'unknown'."""
    for fmt_name, profile in FORMAT_PROFILES.items():
        try:
            if profile["detect"](lines):
                return fmt_name
        except Exception:
            continue
    return "unknown"


def _strip_non_transaction(line: str) -> bool:
    """Return True if line should be kept (is a transaction line)."""
    cumulative_patterns = [
        r"(?:OPENING\s+)?BALANCE(?:\s+(?:B/F|C/F|BROUGHT|CARRIED))?",
        r"TOTAL\s+(?:DEBITS|CREDITS|DEPOSITS|WITHDRAWALS)",
        r"SUB\s*TOTAL",
        r"GRAND\s+TOTAL",
        r"CUMULATIVE\s+TOTAL",
    ]
    for pat in cumulative_patterns:
        if re.search(pat, line, re.IGNORECASE):
            return False
    if re.match(r"^[\s\-]+$", line):
        return False
    if re.match(r"^(Date|Id|SI|Particulars|Transaction)\s", line, re.IGNORECASE):
        return False
    if re.match(r"^STATEMENT\s+OF\s+ACCOUNT", line, re.IGNORECASE):
        return False
    if re.match(r"^\w+\s+BANK\s+(LTD|LIMITED)?$", line, re.IGNORECASE):
        return False
    if re.search(r"Page\s+\d+\s+of\s+\d+", line, re.IGNORECASE):
        return False
    return True


def clean_entries(lines: List[str]) -> List[str]:
    """Filter cumulative lines and merge continuation lines into entries."""
    filtered = [l for l in lines if _strip_non_transaction(l)]
    # Strip leading serial numbers before dates (e.g. "1 02-03-2026 ..." → "02-03-2026 ...")
    normalized = [re.sub(r'^\d+\s+(?=\d{2}-\d{2}-\d{4})', '', l) for l in filtered]
    while normalized and not re.match(r"^\d{2}-\d{2}-\d{4}", normalized[0]):
        normalized.pop(0)
    if not normalized:
        return []
    merged = []
    for line in normalized:
        if re.match(r"^\d{2}-\d{2}-\d{4}", line):
            merged.append(line)
        elif merged:
            merged[-1] = merged[-1] + " " + line.strip()
    return merged


def parse_bank_pdf(pdf_path: str, password: str = "") -> dict:
    """Extract text from a PDF bank statement, detect format, clean entries.

    Returns:
        dict with keys:
            - entries: List[str] — cleaned transaction lines
            - format: str — detected format profile name
            - entry_count: int
            - raw_lines: int (pre-cleaning count)
    """
    raw_text = extract_text_from_pdf(pdf_path, password=password)
    lines = [l.rstrip("\r").strip() for l in raw_text.split("\n") if l.strip()]
    fmt = detect_format(lines)
    entries = clean_entries(lines)
    return {
        "entries": entries,
        "format": fmt,
        "entry_count": len(entries),
        "raw_lines": len(lines),
    }
