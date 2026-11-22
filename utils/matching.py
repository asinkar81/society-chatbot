"""
Shared matching utilities for member lookup across PDF parsing and ledger creation.
"""
import re


def ngram_match(a, b, n=5):
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


def score_member_match(search_tokens, member):
    name = str(member.get("Plot_Owner_Name") or "").upper()
    email = str(member.get("Email") or "").upper()

    phone_raw = member.get("Phone")
    phone = ""
    if phone_raw is not None:
        try:
            phone = str(int(float(str(phone_raw))))
        except (ValueError, TypeError, OverflowError):
            s = str(phone_raw).strip()
            if s.lower() not in ("", "nan", "inf", "-inf", "infinity", "-infinity", "none"):
                phone = s

    wa_raw = member.get("WhatsApp_No")
    wa_phone = ""
    if wa_raw is not None:
        try:
            wa_phone = str(int(float(str(wa_raw))))
        except (ValueError, TypeError, OverflowError):
            s = str(wa_raw).strip()
            if s.lower() not in ("", "nan", "inf", "-inf", "infinity", "-infinity", "none"):
                wa_phone = s

    name_tokens = set(re.split(r'[\s.]+', name))

    score = 0
    reason_parts = []

    name_parts_list = re.split(r'[\s.]+', name)
    surname = name_parts_list[-1] if name_parts_list else ""
    if surname and len(surname) > 2:
        if surname in search_tokens:
            score += 20
            reason_parts.append("surname")
        else:
            matched = False
            for token in search_tokens:
                if surname in token and len(token) > len(surname):
                    score += 15
                    reason_parts.append(f"surname_in_{token}")
                    matched = True
                    break
            if not matched:
                for token in search_tokens:
                    if len(token) > 2 and ngram_match(token, surname):
                        score += 15
                        reason_parts.append(f"surname_fuzzy:{token}")
                        break

    common = search_tokens & name_tokens
    if common:
        score += 5 * len(common)
        reason_parts.append(f"name:{','.join(common)}")

    fuzzy_common = set()
    for t in search_tokens:
        if len(t) <= 2:
            continue
        for nt in name_tokens:
            if len(nt) > 2 and t != nt and ngram_match(t, nt):
                fuzzy_common.add(t)
                break
    deduped = fuzzy_common - common
    if deduped:
        score += 3 * len(deduped)
        reason_parts.append(f"name_fuzzy:{','.join(deduped)}")

    sub_common = set()
    for t in search_tokens:
        if len(t) < 3:
            continue
        for nt in name_tokens:
            if len(nt) < 3:
                continue
            if (t in nt or nt in t) and t != nt:
                sub_common.add(t)
                break
    sub_deduped = sub_common - common - fuzzy_common
    if sub_deduped:
        score += 5 * len(sub_deduped)
        reason_parts.append(f"name_sub:{','.join(sub_deduped)}")

    if email and "@" in email:
        email_local = email.split("@")[0]
        email_parts = set(re.split(r'[.\s]+', email_local))
        common_email = search_tokens & email_parts
        if common_email:
            score += 3 * len(common_email)
            reason_parts.append(f"email:{','.join(common_email)}")

    if phone and phone in search_tokens:
        score += 8
        reason_parts.append("phone")

    if wa_phone and wa_phone in search_tokens:
        score += 8
        reason_parts.append("whatsapp")

    return score, ", ".join(reason_parts)


def extract_txn_ref(e: dict) -> str:
    """Extract a unique bank transaction reference/UTR if present."""
    tid = str(e.get("Transaction_ID") or "").strip()
    if tid and len(tid) >= 8 and not tid.startswith("SPLIT") and re.search(r'\d{3,}', tid):
        if not any(stop in tid.upper() for stop in ["MAHARASHTRA", "ELECTRICITY", "CHARGES"]):
            return tid.upper()
    text = f"{e.get('Particulars', '')} {e.get('Description', '')}"
    m_paren = re.search(r'\(([A-Z0-9]{6,22})', text)
    if m_paren and re.search(r'\d{2,}', m_paren.group(1)):
        return m_paren.group(1).upper()
    m = re.search(r'\b([A-Z0-9]{8,22})\b', text)
    if m:
        val = m.group(1).upper()
        if re.search(r'\d{3,}', val):
            return val
    return ""


def scan_ledger_duplicates(ledger: list) -> list:
    """Scan ledger for potential duplicates across members, plots, and financial years.
    Returns list of (reason_str, items_list) tuples.
    """
    from utils.converters import get_fy_from_date
    dup_groups = []
    seen_ids = set()

    def get_amt_dir(e):
        cr = float(e.get("Credit") or 0)
        dr = float(e.get("Debit") or 0)
        return (cr, "CR") if cr > 0 else (dr, "DR")

    def is_split_entry(e):
        tt = str(e.get("Transaction_Type") or "").upper()
        desc = str(e.get("Description") or "")
        part = str(e.get("Particulars") or "")
        tid = str(e.get("Transaction_ID") or "")
        return (tt == "SPLIT" or "SPLIT FROM" in desc.upper() 
                or "SPLIT FROM" in part.upper() or tid.startswith("SPLIT"))

    # ── Check 1: Same Plot + Same Date + Same Amount + Same Direction ──
    same_plot_map = {}
    for e in ledger:
        tt = str(e.get("Transaction_Type") or "").upper()
        if tt == "INVOICE":
            continue
        amt, direction = get_amt_dir(e)
        if amt <= 0:
            continue
        plot = str(e.get("Plot_No") or e.get("Member_ID") or "")
        dt = str(e.get("Date") or "").strip()
        mid = int(float(e.get("Member_ID") or e.get("Plot_No") or 0))
        key = (plot, dt, amt, direction)
        same_plot_map.setdefault(key, []).append({**e, "_dup_mid": mid})

    for (plot, dt, amt, direction), items in same_plot_map.items():
        if len(items) >= 2:
            refs = [extract_txn_ref(item) for item in items]
            has_distinct_refs = len(set(refs)) == len(items) and all(bool(r) for r in refs)
            if not has_distinct_refs:
                vch_key = tuple(sorted(int(e.get("Vch_No", 0)) for e in items))
                if vch_key not in seen_ids:
                    seen_ids.add(vch_key)
                    dup_groups.append((
                        f"Plot {plot}: {len(items)} entries on {dt} for {direction} ₹{amt:,.2f}",
                        items
                    ))

    # ── Check 2: Cross-Plot Duplicate Real Transaction ID (Excluding Splits) ──
    cross_plot_map = {}
    for e in ledger:
        if is_split_entry(e):
            continue
        tt = str(e.get("Transaction_Type") or "").upper()
        if tt == "INVOICE":
            continue
        ref = extract_txn_ref(e)
        if ref:
            mid = int(float(e.get("Member_ID") or e.get("Plot_No") or 0))
            cross_plot_map.setdefault(ref, []).append({**e, "_dup_mid": mid})

    for ref, items in cross_plot_map.items():
        if len(items) >= 2:
            plots = set(str(e.get("Plot_No") or e.get("Member_ID") or "") for e in items)
            if len(plots) >= 2:
                vch_key = tuple(sorted(int(e.get("Vch_No", 0)) for e in items))
                if vch_key not in seen_ids:
                    seen_ids.add(vch_key)
                    dup_groups.append((
                        f"Cross-Plot: Txn ID '{ref}' assigned to multiple plots ({', '.join(sorted(plots))})",
                        items
                    ))

    # ── Check 3: Duplicate Invoices (Same Plot + Same FY) ──
    inv_map = {}
    for e in ledger:
        tt = str(e.get("Transaction_Type") or "").upper()
        if tt != "INVOICE":
            continue
        plot = str(e.get("Plot_No") or e.get("Member_ID") or "")
        fy = get_fy_from_date(str(e.get("Date") or ""))
        mid = int(float(e.get("Member_ID") or e.get("Plot_No") or 0))
        inv_map.setdefault((plot, fy), []).append({**e, "_dup_mid": mid})

    for (plot, fy), items in inv_map.items():
        if len(items) >= 2:
            vch_key = tuple(sorted(int(e.get("Vch_No", 0)) for e in items))
            if vch_key not in seen_ids:
                seen_ids.add(vch_key)
                dup_groups.append((
                    f"Duplicate Invoices: Plot {plot} has {len(items)} invoices for FY {fy}",
                    items
                ))

    return dup_groups

