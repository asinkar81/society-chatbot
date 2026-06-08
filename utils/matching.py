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
