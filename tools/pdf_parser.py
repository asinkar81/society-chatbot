import re
import pdfplumber
from typing import List, Optional, Dict, Any


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


def _ngram_match(a, b, n=5):
    a_u, b_u = a.upper(), b.upper()
    if a_u == b_u:
        return True
    if len(a_u) < n or len(b_u) < n:
        return False
    for i in range(len(a_u) - n + 1):
        if a_u[i:i+n] in b_u:
            return True
    for i in range(len(b_u) - n + 1):
        if b_u[i:i+n] in a_u:
            return True
    return False


def extract_text_from_pdf(pdf_path: str, password: str = "") -> str:
    with pdfplumber.open(pdf_path, password=password) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def detect_format(lines: List[str]) -> str:
    for fmt_name, profile in FORMAT_PROFILES.items():
        try:
            if profile["detect"](lines):
                return fmt_name
        except Exception:
            continue
    return "unknown"


def _strip_non_transaction(line: str) -> bool:
    cumulative_patterns = [
        r"(?:OPENING\s+)?BALANCE(?:\s+(?:B/F|C/F|BROUGHT|CARRIED))?",
        r"TOTAL\s+(?:DEBITS|CREDITS|DEPOSITS|WITHDRAWALS)",
        r"SUB\s*TOTAL",
        r"GRAND\s+TOTAL",
        r"CUMULATIVE\s+TOTAL",
        r"\b(?:C/F|B/F)\b",
        r"^Total\b",
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
    if re.search(r"Page\s+\d+(?:\s+of\s+\d+)?", line, re.IGNORECASE):
        return False
    if re.search(r"BROUGHT\s+FORWARD|CARRIED\s+FORWARD", line, re.IGNORECASE):
        return False
    if re.match(r"^REP\d+", line, re.IGNORECASE):
        return False
    if re.search(r"REPORT\s+FOR\s+THE\s+PERIOD", line, re.IGNORECASE):
        return False
    if re.search(r"CO\s+OPERATIVE\s+SOCIETY", line, re.IGNORECASE):
        return False
    if re.match(r"^\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\s+", line):
        return False
    if re.match(r"^\d{2}:\d{2}:\d{2}\s+", line):
        return False
    return True


def clean_entries(lines: List[str]) -> List[str]:
    filtered = [l for l in lines if _strip_non_transaction(l)]
    normalized = [re.sub(r'^\d+\s+(?=\d{2}-\d{2}-\d{4})', '', l) for l in filtered]
    while normalized and not re.match(r"^\d{2}-\d{2}-\d{4}", normalized[0]):
        normalized.pop(0)
    if not normalized:
        return []
    # Truncate at "Summary" — anything after is appendix (non-transaction)
    for i, line in enumerate(normalized):
        if re.match(r"^Summary\b", line, re.IGNORECASE):
            normalized = normalized[:i]
            break
    merged = []
    for line in normalized:
        if re.match(r"^\d{2}-\d{2}-\d{4}", line):
            merged.append(line)
        elif merged:
            merged[-1] = merged[-1] + " " + line.strip()
    return merged


def parse_bank_pdf(pdf_path: str, password: str = "") -> dict:
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


def _get_txn_type(text: str) -> str:
    text_u = text.upper()
    if "MOBFT" in text_u:
        return "MOBFT"
    if "NEFT" in text_u:
        return "NEFT"
    if "UPI" in text_u:
        return "UPI"
    if "IMPS" in text_u:
        return "IMPS"
    if "RTGS" in text_u:
        return "RTGS"
    if "CHQ" in text_u or "CHEQUE" in text_u or "CTS" in text_u:
        return "CHQ"
    if "CASH" in text_u:
        return "CASH"
    return ""


def _extract_txn_id(text: str, txn_type: str, all_lines: Optional[List[str]] = None) -> str:
    if txn_type == "NEFT":
        after_prefix = re.sub(r'^NEFT:?\s*', '', text, flags=re.IGNORECASE)
        after_amounts = re.sub(r'\s+[\d,]+\.\d{2}\s*(?:Cr|Dr)?(?:\s+[\d,]+\.\d{2}\s*(?:Cr|Dr)?)?\s*$', '', after_prefix, count=1)
        parts = after_amounts.split()
        if parts:
            txn_id = parts[-1].strip()
            if len(txn_id) >= 6:
                return txn_id
        if all_lines:
            for cl in all_lines[1:]:
                utr_match = re.search(r'UTR\s*(?:Number|#|:)?\s*:?\s*([A-Za-z0-9]{8,})', cl, re.IGNORECASE)
                if utr_match:
                    return utr_match.group(1)
    if txn_type == "UPI":
        ref_match = re.search(r'UPI[A-Za-z]*/(\d{6,})', text)
        if ref_match:
            return ref_match.group(1)
    gen_match = re.search(r'([A-Z0-9]{8,})', text)
    if gen_match:
        return gen_match.group(1)
    return ""


def _extract_search_tokens(particulars: str, txn_type: str, txn_id: str = None) -> tuple:
    tokens = set()
    identifiers = []

    TITLE_WORDS = {"MR", "MRS", "MS", "SHRI", "SMT", "DR", "SRI", "M/S", "CMN",
                   "PAY", "AND", "THE", "FROM", "B"}
    STOP_WORDS = TITLE_WORDS | {"PAYMENT", "RECEIVED", "TRANSFER", "NEFT", "RTGS",
                                "IMPS", "CHQ", "CHEQUE", "BANK", "REFERENCE",
                                "CREDIT", "DEBIT", "BY", "TO", "VIA", "THROUGH"}

    def should_record_name(token: str) -> bool:
        t = token.upper()
        if len(t) <= 2:
            return False
        if t in STOP_WORDS:
            return False
        if t.isalpha() and t.isupper() and len(t) <= 4:
            return False
        if bool(re.match(r'^[\d,]+\.\d{2}$', t)):
            return False
        return True

    cr_match = re.search(r'/CR/([^/]+)', particulars)
    if cr_match:
        name_raw = cr_match.group(1).strip()
        name_raw = re.sub(r'^(Mr|Mrs|Ms|Shri|Smt|Dr|Sri)\s+', '', name_raw, flags=re.IGNORECASE)
        for t in re.split(r'[\s.]+', name_raw):
            if len(t) > 1:
                token = t.upper()
                tokens.add(token)
                if should_record_name(token):
                    identifiers.append((token, "PAYEE_NAME"))

    if txn_type == "UPI":
        segments = particulars.split("/")
        if segments:
            last_seg = segments[-1].strip().split()[0]
            last_seg = re.sub(r'[\s.,]', '', last_seg)
            if len(last_seg) > 3 and not last_seg.isdigit():
                token = last_seg.upper()
                tokens.add(token)
                identifiers.append((token, "UPI_ID"))

    if txn_type == "NEFT":
        after_prefix = re.sub(r'^NEFT:?\s*', '', particulars)
        after_amounts = re.sub(r'(?:\s+[\d,]+\.\d{2}\s*(?:Cr)?){1,2}\s*$', '', after_prefix, count=1)
        if after_amounts == after_prefix and re.match(r'^[\d,]+\.\d{2}\s*[/\\]?\s*', after_amounts):
            after_amounts = re.sub(r'^[\d,]+\.\d{2}\s*[/\\]?\s*', '', after_amounts, count=1)
        parts = after_amounts.split()
        if len(parts) >= 2:
            name_tokens_list = parts[:-1]
            for t in name_tokens_list:
                t_clean = re.sub(r'^(Mr|Mrs|Ms|Shri|Smt|Dr|Sri|MRS?)\s+', '', t, flags=re.IGNORECASE)
                if len(t_clean) > 1:
                    token = t_clean.upper()
                    tokens.add(token)
                    if should_record_name(token):
                        identifiers.append((token, "PAYEE_NAME"))

    mobft_match = re.search(r'from:\s*([A-Za-z\s.]+?)(?:/|\s+\d)', particulars)
    if mobft_match:
        name_raw = mobft_match.group(1).strip()
        for t in re.split(r'[\s.]+', name_raw):
            if len(t) > 1:
                token = t.upper()
                tokens.add(token)
                if should_record_name(token):
                    identifiers.append((token, "PAYEE_NAME"))

    email_match = re.search(r'([\w.]+)@', particulars)
    if email_match:
        for p in email_match.group(1).split("."):
            if len(p) > 2:
                token = p.upper()
                tokens.add(token)
                identifiers.append((token, "UPI_ID"))

    for phone in re.findall(r'([6-9]\d{9})', particulars):
        if txn_id and phone in txn_id:
            continue
        tokens.add(phone)
        identifiers.append((phone, "MOBILE"))

    return tokens, identifiers


def _parse_entry_amounts(particulars: str, fmt: str, prev_balance: Optional[float] = None) -> Optional[Dict[str, Any]]:
    amounts = list(re.finditer(r'([\d,]+\.\d{2})\s*(Cr|Dr)?', particulars, re.IGNORECASE))
    if not amounts:
        return None
    n = len(amounts)
    balance = float(amounts[-1].group(1).replace(",", ""))
    if n == 1:
        return {"withdrawal": None, "deposit": None, "balance": balance, "entry_type": None}
    if n >= 3:
        w_raw = float(amounts[-3].group(1).replace(",", ""))
        d_raw = float(amounts[-2].group(1).replace(",", ""))
        return {
            "withdrawal": w_raw if w_raw > 0 else None,
            "deposit": d_raw if d_raw > 0 else None,
            "balance": balance,
            "entry_type": "credit" if d_raw > 0 else "debit",
        }
    def _guess_direction(text: str, amount: float, bal: float) -> Dict[str, Any]:
        text_u = text.upper()
        if any(kw in text_u for kw in ["NEFT", "UPI", "MOBFT", "IMPS", "RTGS"]):
            return {"withdrawal": None, "deposit": amount, "balance": bal, "entry_type": "credit"}
        if any(kw in text_u for kw in ["CHQ", "CHEQUE", "CTS", "CASH"]):
            return {"withdrawal": amount, "deposit": None, "balance": bal, "entry_type": "debit"}
        return {"withdrawal": None, "deposit": None, "balance": bal, "entry_type": None}

    if fmt in ("email_attachment", "printed_printout", "serial_number_prefix"):
        txn = float(amounts[-2].group(1).replace(",", ""))
        suffix = (amounts[-2].group(2) or "").upper()
        if suffix == "DR":
            return {"withdrawal": txn, "deposit": None, "balance": balance, "entry_type": "debit"}
        elif suffix == "CR":
            return {"withdrawal": None, "deposit": txn, "balance": balance, "entry_type": "credit"}
        if prev_balance is not None:
            diff_w = abs(balance - (prev_balance - txn))
            diff_d = abs(balance - (prev_balance + txn))
            if diff_w < diff_d:
                return {"withdrawal": txn, "deposit": None, "balance": balance, "entry_type": "debit"}
            elif diff_d < diff_w:
                return {"withdrawal": None, "deposit": txn, "balance": balance, "entry_type": "credit"}
        return _guess_direction(particulars, txn, balance)
    elif fmt == "netbanking":
        txn = float(amounts[-2].group(1).replace(",", ""))
        suffix = (amounts[-2].group(2) or "").upper()
        if suffix == "DR":
            return {"withdrawal": txn, "deposit": None, "balance": balance, "entry_type": "debit"}
        elif suffix == "CR":
            return {"withdrawal": None, "deposit": txn, "balance": balance, "entry_type": "credit"}
        text_before = particulars[:amounts[-2].start()].rstrip()
        if re.search(r'\b(\d{6,9})\s*$', text_before) and re.search(r'(?:CHQ|CHEQUE|CTS|INST)', text_before, re.IGNORECASE):
            return {"withdrawal": txn, "deposit": None, "balance": balance, "entry_type": "debit"}
        if prev_balance is not None:
            diff_w = abs(balance - (prev_balance - txn))
            diff_d = abs(balance - (prev_balance + txn))
            if diff_w < diff_d:
                return {"withdrawal": txn, "deposit": None, "balance": balance, "entry_type": "debit"}
            elif diff_d < diff_w:
                return {"withdrawal": None, "deposit": txn, "balance": balance, "entry_type": "credit"}
        return _guess_direction(particulars, txn, balance)
    else:
        if n >= 2:
            txn = float(amounts[-2].group(1).replace(",", ""))
            suffix = (amounts[-2].group(2) or "").upper()
            if suffix == "DR":
                return {"withdrawal": txn, "deposit": None, "balance": balance, "entry_type": "debit"}
            elif suffix == "CR":
                return {"withdrawal": None, "deposit": txn, "balance": balance, "entry_type": "credit"}
            if prev_balance is not None:
                diff_w = abs(balance - (prev_balance - txn))
                diff_d = abs(balance - (prev_balance + txn))
                if diff_w < diff_d:
                    return {"withdrawal": txn, "deposit": None, "balance": balance, "entry_type": "debit"}
                elif diff_d < diff_w:
                    return {"withdrawal": None, "deposit": txn, "balance": balance, "entry_type": "credit"}
            return _guess_direction(particulars, txn, balance)
    return None


_FOOTER_ARTIFACT_PATTERNS = [
    re.compile(r'\bPage\s+\d+\b', re.IGNORECASE),
    re.compile(r'\bREP\d+\b', re.IGNORECASE),
    re.compile(r'REPORT\s+FOR\s+THE\s+PERIOD', re.IGNORECASE),
    re.compile(r'BROUGHT\s+FORWARD|CARRIED\s+FORWARD', re.IGNORECASE),
    re.compile(r'\d{2}:\d{2}:\d{2}\s+UNION\s+BANK', re.IGNORECASE),
    re.compile(r'CO\s+OPERATIVE\s+SOCIETY', re.IGNORECASE),
    re.compile(r'UNION\s+BANK\s+OF\s+INDIA,\s*MUTHA', re.IGNORECASE),
    re.compile(r'\bSummary\b', re.IGNORECASE),
]


def _is_footer_artifact(text: str) -> bool:
    for pat in _FOOTER_ARTIFACT_PATTERNS:
        if pat.search(text):
            return True
    return False


def parse_entries_to_accounts(entries: List[str], fmt: str) -> Dict[str, Any]:
    parsed = []
    prev_balance = None
    seq = 0
    for entry_text in entries:
        seq += 1
        date_match = re.match(r'^(\d{2}-\d{2}-\d{4})\s*(.*)', entry_text)
        if not date_match:
            continue
        date = date_match.group(1)
        first_line = date_match.group(2)
        all_text = entry_text
        particulars = first_line

        amt = _parse_entry_amounts(all_text, fmt, prev_balance)
        if amt is None:
            continue

        if _is_footer_artifact(all_text):
            if amt.get("balance") is not None:
                prev_balance = amt["balance"]
            continue

        txn_type = _get_txn_type(first_line)
        txn_id = _extract_txn_id(first_line, txn_type)

        withdrawal = amt["withdrawal"]
        deposit = amt["deposit"]
        balance = amt["balance"]

        if withdrawal is None and deposit is None:
            prev_balance = balance
            continue

        if prev_balance is None:
            calc_balance = balance
        else:
            calc_balance = round(prev_balance - (withdrawal or 0) + (deposit or 0), 2)

        if balance is not None:
            if abs(calc_balance - balance) < 0.01:
                balance_check = "✓"
            else:
                balance_check = f"✗ off by ₹{abs(calc_balance - balance):.2f}"
        else:
            balance_check = ""

        parsed.append({
            "Date": date,
            "Particulars": particulars,
            "Withdrawal": withdrawal,
            "Deposit": deposit,
            "Balance": balance,
            "Calculated_Balance": calc_balance,
            "Balance_Check": balance_check,
            "Transaction_Type": txn_type,
            "Transaction_ID": txn_id,
            "Status": "Pending",
            "Statement_Seq": seq,
        })

        prev_balance = balance

    return {
        "entries": parsed,
        "entry_count": len(parsed),
        "closing_balance": prev_balance,
    }
