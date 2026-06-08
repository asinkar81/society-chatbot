# WhatsApp Web Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WhatsApp Web sharing via wa.me links alongside existing email sharing — per-row 💬 buttons in Receipts/Invoices tabs, and a 💬 button in Settings > Email > Share Documents for consolidated sharing.

**Architecture:** New `utils/whatsapp.py` module with message builder, wa.me link generator, and clipboard support. No automated sending — wa.me links open pre-filled messages in WhatsApp Web, user clicks Send. Staging folder (`data/staging/whatsapp/`) collects PDFs for drag-drop.

**Tech Stack:** Python stdlib (`urllib.parse`, `subprocess` for macOS pbcopy), Streamlit (`st.markdown` with `unsafe_allow_html` for wa.me links, `st.text_area`, `st.checkbox`, `st.expander`)

---

### Task 1: Add STAGING_DIR to config.py

**Files:**
- Modify: `config.py`

- [ ] **Add STAGING_DIR constant after BACKUPS_DIR (line 69)**

```python
STAGING_DIR = DATA_DIR / "staging"
```

- [ ] **Add mkdir after BACKUPS_DIR mkdir (line 86)**

```python
STAGING_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Commit**

```bash
git add config.py
git commit -m "feat: add STAGING_DIR for WhatsApp staging folder"
```

---

### Task 2: Create utils/whatsapp.py — Core Module

**Files:**
- Create: `utils/whatsapp.py`
- Test: `tests/test_whatsapp.py`

- [ ] **Write the failing tests**

```python
"""tests/test_whatsapp.py"""
import pytest
from utils.whatsapp import build_wa_message, build_wa_link, copy_to_clipboard


def test_build_wa_message_receipt():
    member = {"Plot_No": "25", "Plot_Owner_Name": "Anil Sharma"}
    summary = None
    entries = [{"date": "01-06-2026", "amount": 5000, "ref_id": "26-27-005",
                "particulars": "By NEFT", "type": "CR"}]
    pdf_names = ["Receipt_Plot_No_25_26-27-005.pdf"]
    msg = build_wa_message("receipt", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "Plot 25" in msg
    assert "Anil Sharma" in msg
    assert "₹5,000" in msg or "₹ 5,000" in msg
    assert "Receipt_Plot_No_25_26-27-005.pdf" in msg


def test_build_wa_message_invoice_with_summary():
    member = {"Plot_No": "12", "Plot_Owner_Name": "Amit Patel"}
    summary = {
        "previous_outstanding": 2500, "total_demand": 12000,
        "total_payments": 3000, "total_due": 11500,
        "as_of_date": "15-06-2026",
    }
    entries = [{"date": "01-06-2026", "amount": 12000, "ref_id": "26-27-001",
                "particulars": "Invoice for FY 26-27", "type": "DR"}]
    pdf_names = ["Invoice_Plot_No_12_26-27-001.pdf"]
    msg = build_wa_message("invoice", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "Plot 12" in msg
    assert "Amit Patel" in msg
    assert "Invoice" in msg
    assert "Balance carried forward" in msg
    assert "₹2,500" in msg or "₹ 2,500" in msg
    assert "New Demand" in msg
    assert "₹12,000" in msg or "₹ 12,000" in msg
    assert "Outstanding" in msg
    assert "₹11,500" in msg or "₹ 11,500" in msg


def test_build_wa_message_statement():
    member = {"Plot_No": "5", "Plot_Owner_Name": "Priya Singh"}
    summary = {
        "previous_outstanding": 0, "total_demand": 12000,
        "total_payments": 8000, "total_due": 4000,
        "as_of_date": "15-06-2026",
    }
    entries = [
        {"date": "01-04-2026", "amount": 12000, "ref_id": "26-27-001",
         "particulars": "Invoice", "type": "DR"},
        {"date": "10-05-2026", "amount": 5000, "ref_id": "26-27-003",
         "particulars": "By NEFT", "type": "CR"},
        {"date": "01-06-2026", "amount": 3000, "ref_id": "26-27-005",
         "particulars": "By UPI", "type": "CR"},
    ]
    pdf_names = ["Invoice_Plot_No_5_26-27-001.pdf", "Receipt_Plot_No_5_26-27-003.pdf"]
    msg = build_wa_message("statement", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "Statement" in msg
    assert "Summary" in msg
    assert "Attached Documents" in msg
    assert len(pdf_names[0]) > 0 and pdf_names[0] in msg


def test_build_wa_message_reminder():
    member = {"Plot_No": "8", "Plot_Owner_Name": "Rajesh Kumar"}
    summary = {
        "previous_outstanding": 1000, "total_demand": 12000,
        "total_payments": 2000, "total_due": 11000,
        "as_of_date": "15-06-2026",
    }
    entries = []
    pdf_names = []
    msg = build_wa_message("reminder", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "Reminder" in msg
    assert "Outstanding" in msg


def test_build_wa_link():
    phone = "9876543210"
    text = "Hello World"
    link = build_wa_link(phone, text)
    assert link.startswith("https://wa.me/919876543210?text=")
    assert "Hello%20World" in link


def test_build_wa_link_with_country_code():
    phone = "+1-555-1234"
    text = "Test"
    link = build_wa_link(phone, text, country_code="1")
    assert "15551234" in link


def test_copy_to_clipboard_returns_bool():
    result = copy_to_clipboard("test")
    assert isinstance(result, bool)
```

- [ ] **Run tests to verify they fail**

Run: `python3 -m pytest tests/test_whatsapp.py -v 2>&1 | head -30`
Expected: FAIL with ModuleNotFoundError for each test

- [ ] **Write utils/whatsapp.py implementation**

```python
"""
WhatsApp sharing utilities — message builder, wa.me links, clipboard.
"""
import subprocess
import shutil
import urllib.parse
from pathlib import Path
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
            p = subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    return False
```

- [ ] **Run tests to verify they pass**

Run: `python3 -m pytest tests/test_whatsapp.py -v`
Expected: 7 passed

- [ ] **Commit**

```bash
git add utils/whatsapp.py tests/test_whatsapp.py
git commit -m "feat: add whatsapp message builder, wa.me link, clipboard"
```

---

### Task 3: Add 💬 Buttons in Receipts Tab (main.py)

**Files:**
- Modify: `main.py` (around lines 1149-1194)

- [ ] **Add 💬 button column alongside 📧 in Receipts tab**

After the `st.button("📧", ...)` block (ends ~line 1194), add a new column for 💬. Currently the row has `cols[8]` for the email button. Change to 10 columns and add `cols[9]` for WhatsApp.

Find the column creation in the Receipts tab (around line 1065-1070) and add an extra column. Then add the 💬 button:

```python
                        with cols[9]:
                            mr = data_provider.get_member(e["_mid"])
                            _raw_wa = mr.get("WhatsApp_No") if mr else None
                            wa_phone = "" if (_raw_wa is None or (isinstance(_raw_wa, float) and pd.isna(_raw_wa))) else str(_raw_wa).strip()
                            if cr > 0 and wa_phone and st.button("💬", key=f"rec_wa_{idx}", help="Share via WhatsApp"):
                                from utils.whatsapp import build_wa_message, build_wa_link, copy_to_clipboard
                                fy = get_fy_from_date(str(e.get("Date", "")))
                                ref_id = (_extract_ref_id(str(e.get("Description", "")))
                                          or _extract_ref_id(str(e.get("Particulars", "")))
                                          or "")
                                pdf_path = _get_pdf_path(config.RECEIPTS_DIR, ref_id) if ref_id else None
                                pdf_names = [pdf_path.name] if pdf_path and pdf_path.exists() else []
                                msg = build_wa_message(
                                    "receipt", mr, summary=None,
                                    entries=[{"date": str(e.get("Date", "")),
                                              "amount": cr, "ref_id": ref_id or "",
                                              "particulars": str(e.get("Particulars", "")),
                                              "type": "CR"}],
                                    pdf_names=pdf_names,
                                )
                                wa_link = build_wa_link(wa_phone, msg)
                                copied = copy_to_clipboard(msg)
                                st.info("📋 Message copied!" if copied else "")
                                st.markdown(f'<a href="{wa_link}" target="_blank">🔗 Open WhatsApp</a>',
                                            unsafe_allow_html=True)
                                refs = ";".join(pdf_names)
                                data_provider.log_communication(
                                    member_id=e["_mid"], template_type="whatsapp",
                                    subject="Receipt shared via WhatsApp",
                                    recipients=wa_phone, cc="",
                                    status="sent",
                                    document_refs=refs, error="",
                                )
```

Also update the columns count on the Receipts tab header (where `cols = st.columns(...)` is defined).

- [ ] **Verify the Receipts tab columns are updated**

Find the `st.columns(...)` call in the receipts loop and ensure the column count is incremented by 1 (from 9 → 10 or whatever it currently is).

- [ ] **Commit**

```bash
git add main.py
git commit -m "feat: add WhatsApp 💬 button in Receipts tab"
```

---

### Task 4: Add 💬 Buttons in Invoices Tab (main.py)

**Files:**
- Modify: `main.py` (around lines 1402-1463)

- [ ] **Add 💬 button in Invoices tab alongside 📧**

Same pattern as receipts. Find the columns in the invoices loop, add an extra column, and add the 💬 button:

```python
                        with cols[9]:  # or whichever is the new column index
                            mr = data_provider.get_member(e["_mid"])
                            _raw_wa = mr.get("WhatsApp_No") if mr else None
                            wa_phone = "" if (_raw_wa is None or (isinstance(_raw_wa, float) and pd.isna(_raw_wa))) else str(_raw_wa).strip()
                            if wa_phone and st.button("💬", key=f"inv_wa_{e_key}", help="Share invoice via WhatsApp"):
                                from utils.whatsapp import build_wa_message, build_wa_link, copy_to_clipboard
                                fy = get_fy_from_date(str(e.get("Date", "")))
                                ref_id = (_extract_ref_id(str(e.get("Description", "")))
                                          or _extract_ref_id(str(e.get("Particulars", "")))
                                          or "")
                                pdf_path = _get_pdf_path(config.INVOICES_DIR, ref_id) if ref_id else None
                                pdf_names = [pdf_path.name] if pdf_path and pdf_path.exists() else []
                                inv_member_id = e["_mid"]
                                inv_ledger = data_provider.get_member_ledger(inv_member_id)
                                fy_start = f"01-04-20{fy[:2]}"
                                inv_prev_outstanding = max(0, -compute_outstanding_as_of(inv_ledger, fy_start))
                                inv_entries_fy = [x for x in inv_ledger if get_fy_from_date(str(x.get("Date", ""))) == fy]
                                inv_total_demand = sum(float(x.get("Debit", 0)) for x in inv_entries_fy
                                                       if str(x.get("Transaction_Type", "")).upper() == "INVOICE")
                                inv_total_payments = sum(float(x.get("Credit", 0)) for x in inv_entries_fy)
                                inv_today = datetime.now().strftime("%d-%m-%Y")
                                inv_summary = {
                                    "previous_outstanding": inv_prev_outstanding,
                                    "total_demand": inv_total_demand,
                                    "total_payments": inv_total_payments,
                                    "total_due": max(0, inv_prev_outstanding + inv_total_demand - inv_total_payments),
                                    "as_of_date": inv_today,
                                }
                                msg = build_wa_message(
                                    "invoice", mr, summary=inv_summary,
                                    entries=[{"date": str(e.get("Date", "")),
                                              "amount": _s(e.get("Debit")), "ref_id": ref_id or "",
                                              "particulars": str(e.get("Particulars", "")),
                                              "type": "DR"}],
                                    pdf_names=pdf_names,
                                )
                                wa_link = build_wa_link(wa_phone, msg)
                                copied = copy_to_clipboard(msg)
                                st.info("📋 Message copied!" if copied else "💬 Opening WhatsApp...")
                                st.markdown(f'<a href="{wa_link}" target="_blank">🔗 Open WhatsApp</a>',
                                            unsafe_allow_html=True)
                                refs = ";".join(pdf_names)
                                data_provider.log_communication(
                                    member_id=e["_mid"], template_type="whatsapp",
                                    subject="Invoice shared via WhatsApp",
                                    recipients=wa_phone, cc="",
                                    status="sent",
                                    document_refs=refs, error="",
                                )
```

- [ ] **Update columns count in invoices loop**

Find the `st.columns(...)` call in the invoices loop and increment column count.

- [ ] **Commit**

```bash
git add main.py
git commit -m "feat: add WhatsApp 💬 button in Invoices tab"
```

---

### Task 5: Add WhatsApp Sharing in Settings > Email > Share Documents

**Files:**
- Modify: `main.py` (around lines 3317-3368, after the email "Send" button)

- [ ] **Add WhatsApp number to share_data and update recipient filtering**

In the `share_data.append(...)` block (line 3289), add:
```python
                    raw_wa = m.get("WhatsApp_No")
                    wa_phone = "" if (raw_wa is None or (isinstance(raw_wa, float) and pd.isna(raw_wa))) else str(raw_wa).strip()
```

And add `"wa_phone": wa_phone` to the share_data dict.

Update the recipient filter (around line 3300-3308) to show both email and WhatsApp availability:
```python
            with_wa = [sd for sd in share_data if sd["wa_phone"]]
            with_email = [sd for sd in share_data if sd["email"]]
            has_both = with_wa and with_email
            label = f"{len(with_email)} member(s) with email"
            if with_wa:
                label += f", {len(with_wa)} with WhatsApp"
            if no_email_count:
                label += f" ({no_email_count} without email, not listed)"
            st.caption(label)
```

- [ ] **Add document filtering per member**

After the "Last sent" caption (line 3315) and before the "Send" button (line 3317), add a checkbox row for filtering documents:

```python
                wa_include_receipts = st.checkbox("Include Receipts", value=True, key="wa_inc_rec")
                wa_include_invoices = st.checkbox("Include Invoices", value=True, key="wa_inc_inv")
```

- [ ] **Add "💬 Send via WhatsApp" button with bulk UI**

After the email "Send" button block (which ends around line 3368), add:

```python
                if st.button("💬 Send via WhatsApp", use_container_width=True,
                             disabled=not sel_items or not with_wa):
                    from utils.whatsapp import build_wa_message, build_wa_link, copy_to_clipboard
                    from pathlib import Path
                    import shutil
                    staging_folder = config.STAGING_DIR / "whatsapp" / datetime.now().strftime("%Y%m%d_%H%M%S")
                    staging_folder.mkdir(parents=True, exist_ok=True)
                    wa_processed = 0
                    for sd in sel_items:
                        if not sd["wa_phone"]:
                            continue
                        wa_processed += 1
                        pdfs = []
                        for e in sd["entries"]:
                            is_credit = e.get("Credit", 0)
                            if is_credit and _receipt_exists(e) == "no":
                                _generate_receipt_for_entry(data_provider, e, sd["mid"])
                            tmpl = sd.get("summary") if wa_include_invoices else None
                            ref_id = (_extract_ref_id(str(e.get("Description", "")))
                                      or _extract_ref_id(str(e.get("Particulars", "")))
                                      or "")
                            etype = str(e.get("Transaction_Type", "") or "").upper()
                            is_inv = etype == "INVOICE"
                            if is_inv and not wa_include_invoices:
                                continue
                            if is_credit and not is_inv and not wa_include_receipts:
                                continue
                            sdir = config.RECEIPTS_DIR if is_credit and not is_inv else config.INVOICES_DIR
                            p = _get_pdf_path(sdir, ref_id) if ref_id else None
                            if p and p.exists():
                                pdfs.append(p)
                                shutil.copy2(p, staging_folder)
                        pdf_names = [p.name for p in pdfs]
                        entries_for_body = []
                        for e in sd["entries"]:
                            is_credit = e.get("Credit", 0)
                            etype = str(e.get("Transaction_Type", "") or "").upper()
                            is_inv = etype == "INVOICE"
                            if is_inv and not wa_include_invoices:
                                continue
                            if is_credit and not is_inv and not wa_include_receipts:
                                continue
                            amt = _s(e.get("Credit")) or _s(e.get("Debit"))
                            entries_for_body.append({
                                "date": str(e.get("Date", "")),
                                "amount": amt, "ref_id": ref_id,
                                "particulars": str(e.get("Particulars", "")),
                                "type": "CR" if is_credit else "DR",
                            })
                        msg = build_wa_message(
                            template_key, sd, summary=sd.get("summary"),
                            entries=entries_for_body, pdf_names=pdf_names,
                        )
                        wa_link = build_wa_link(sd["wa_phone"], msg)
                        with st.expander(f"💬 Plot {sd['plot']} — {sd['name']} ({sd['wa_phone']})"):
                            st.text_area("Message", msg, height=200,
                                         key=f"wa_msg_{sd['mid']}")
                            col_a, col_b, col_c = st.columns(3)
                            with col_a:
                                if st.button("📋 Copy", key=f"wa_copy_{sd['mid']}"):
                                    copy_to_clipboard(msg)
                                    st.success("Copied!")
                            with col_b:
                                st.markdown(f'<a href="{wa_link}" target="_blank">🔗 Open WhatsApp</a>',
                                            unsafe_allow_html=True)
                            with col_c:
                                st.markdown(f"[📂 Open Staging Folder]({staging_folder.as_uri()})")
                            if pdfs:
                                st.caption(f"{len(pdfs)} PDF(s) staged at:\n{staging_folder}")
                                for pn in pdf_names:
                                    st.text(pn)
                    if wa_processed == 0:
                        st.warning("No selected members have a WhatsApp number")
                    elif wa_processed > 0:
                        st.info(f"✅ {wa_processed} message(s) ready. Open WhatsApp Web, copy the message, and drag PDFs from the staging folder.")
                        if st.button("📂 Open Staging Folder", key="wa_open_staging"):
                            import subprocess
                            subprocess.run(["open", str(staging_folder)])
```

- [ ] **Commit**

```bash
git add main.py
git commit -m "feat: add WhatsApp bulk sharing in Share Documents"
```

---

### Task 6: Verify and Run Tests

**Files:**
- Run: all tests

- [ ] **Run full test suite**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -20`
Expected: All 138 + 7 new WhatsApp tests = 145 passed

- [ ] **Run a syntax check on main.py**

Run: `python3 -c "import py_compile; py_compile.compile('main.py', doraise=True)"`
Expected: No errors

- [ ] **Commit final changes if any fixes needed**

```bash
git add -A
git commit -m "fix: post-implementation adjustments"
```
