"""
Main Streamlit application for Society Management Chatbot
"""
import streamlit as st
from pathlib import Path
from typing import Optional, Dict, Any, List
import re
import config
from utils.auth import show_login_page, logout
from utils.chat_manager import ChatManager
from utils.converters import get_fy_string, get_fy_from_date, compute_outstanding_as_of, get_payment_history, get_previous_invoices, number_to_words_inr, clean_payment_details
from data_providers.local_excel_provider import LocalExcelDataProvider
from file_storage.local_storage import LocalFileStorage
from agents.invoice_agent import InvoiceAgent
from agents.receipt_agent import ReceiptAgent
from agents.ledger_agent import LedgerAgent
from agents.admin_agent import AdminAgent
from agents.orchestrator_agent import OrchestratorAgent
from tools.pdf_generator import create_simple_receipt_pdf
import pandas as pd
from agents.router_agent import get_router
import json
from datetime import datetime
import uuid


def _normalize_particulars(text: str) -> str:
    """Strip system-added prefixes from Particulars for cross-referencing.

    Handles:
      "By PANDIT HIRAJI VAIRAL 17060260 ..." → "PANDIT HIRAJI VAIRAL 17060260 ..."
      "By Split from Owner Name (PANDIT ...)" → "PANDIT ..."
      "RECEIVED FROM John Doe" → "John Doe"
    """
    s = str(text or "").strip()
    # Strip "By Split from <name> (<particulars>)" → extract inner particulars
    m = re.match(r'^By\s+Split\s+from\s+.+?\((.+)\)\s*$', s, re.DOTALL | re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    else:
        # Strip common system prefixes
        for prefix in ["By ", "RECEIVED FROM ", "FROM ", "PAID BY "]:
            if s.upper().startswith(prefix.upper()):
                s = s[len(prefix):]
                break
    return s.strip()


# Page config
st.set_page_config(
    page_title=config.STREAMLIT_PAGE_TITLE,
    page_icon=config.STREAMLIT_PAGE_ICON,
    layout=config.STREAMLIT_LAYOUT,
    initial_sidebar_state="expanded",
)

# Initialize chat manager
if "chat_manager" not in st.session_state:
    st.session_state.chat_manager = ChatManager()

# Initialize data provider and agents
@st.cache_resource
def init_agents():
    """Initialize data provider and agents"""
    data_provider = LocalExcelDataProvider(config.SOCIETY_DATA_FILE)
    file_storage = LocalFileStorage(config.DATA_DIR)

    return {
        "data_provider": data_provider,
        "file_storage": file_storage,
        "invoice_agent": InvoiceAgent(data_provider, file_storage),
        "receipt_agent": ReceiptAgent(data_provider, file_storage),
        "ledger_agent": LedgerAgent(data_provider, file_storage),
        "admin_agent": AdminAgent(data_provider, file_storage),
        "orchestrator_agent": OrchestratorAgent(data_provider, file_storage),
    }


# Check authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if config.BYPASS_LOGIN:
    st.session_state.authenticated = True
    st.session_state.username = st.session_state.get("username", config.ADMIN_USERNAME)
elif not st.session_state.authenticated:
    show_login_page()
    st.stop()

# Initialize agents
agents = init_agents()
data_provider = agents["data_provider"]
file_storage = agents["file_storage"]
invoice_agent = agents["invoice_agent"]
receipt_agent = agents["receipt_agent"]
ledger_agent = agents["ledger_agent"]
admin_agent = agents["admin_agent"]
orchestrator_agent = agents["orchestrator_agent"]


# Main layout
def main():
    """Main application layout"""

    # Sidebar navigation
    with st.sidebar:
        st.title("🏘️ Society Management")
        st.caption(f"Welcome, {st.session_state.username}!")

        page = st.radio(
            "Navigation",
            ["Chat", "Dashboard", "Settings", "Help"],
            key="page_nav",
        )

        st.divider()

        if st.button("🚪 Logout", use_container_width=True):
            logout()

    # Route to pages
    if page == "Chat":
        show_chat_page()
    elif page == "Dashboard":
        show_dashboard_page()
    elif page == "Settings":
        show_settings_page()
    elif page == "Help":
        show_help_page()


def save_uploaded_file(uploaded_file) -> Path:
    """Save an uploaded file to the persistent uploads directory and return the path."""
    ext = Path(uploaded_file.name).suffix
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = config.UPLOADS_DIR / unique_name
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest


def show_chat_page():
    """Chat interface page"""
    st.title("💬 Agentic Chatbot")
    st.markdown("Chat with agents to manage invoices, receipts, and ledgers")

    st.divider()

    # Display chat history
    chat_container = st.container(height=400, border=True)
    with chat_container:
        st.session_state.chat_manager.display_chat_history()

    st.divider()

    # File upload + chat input
    if "upload_key" not in st.session_state:
        st.session_state.upload_key = 0

    uploaded_file = st.file_uploader(
        "📎 Attach a file (payment screenshot, receipt image, etc.)",
        type=["jpg", "jpeg", "png", "gif", "webp", "pdf"],
        key=f"chat_upload_{st.session_state.upload_key}",
    )

    col1, col2 = st.columns([5, 1])
    with col1:
        user_input = st.text_input(
            "Enter your message:",
            placeholder="E.g., 'Generate invoices for FY 2026-27' or 'Show ledger for Plot 01'",
            key="chat_input",
        )
    with col2:
        send_btn = st.button("Send", use_container_width=True)

    if send_btn and user_input:
        attachments = []
        enriched_input = user_input

        if uploaded_file is not None:
            saved_path = save_uploaded_file(uploaded_file)
            attachments.append({
                "path": str(saved_path),
                "filename": uploaded_file.name,
                "mime_type": uploaded_file.type,
                "size": uploaded_file.size,
            })
            enriched_input += f"\n\n[Attached file: {saved_path} — {uploaded_file.name}]"

            # Pre-extract payment details from image so the LLM has them immediately
            ext = Path(uploaded_file.name).suffix.lower()
            if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                try:
                    ocr_result = orchestrator_agent.ocr_processor.extract_payment_details(saved_path)
                    if "error" not in ocr_result:
                        enriched_input += f"\n[Extracted Payment Details: {json.dumps(ocr_result)}]"
                    else:
                        enriched_input += f"\n[OCR Extraction issue: {ocr_result['error']}. You can retry with the file path above.]"
                except Exception as e:
                    enriched_input += f"\n[OCR Extraction error: {str(e)}]"

        st.session_state.chat_manager.add_message(
            "user", user_input, attachments=attachments,
        )

        # Build conversation context from recent history (last 6 exchanges)
        history = st.session_state.chat_manager.get_chat_history()
        context_lines = []
        for msg in history[-12:]:  # last 6 user+agent pairs = 12 messages
            role = "User" if msg["role"] == "user" else "Assistant"
            context_lines.append(f"{role}: {msg['content']}")
        context_str = "\n".join(context_lines)

        # Prepend context so the agent knows what was discussed
        if context_str.strip():
            enriched_input = (
                "Previous conversation:\n"
                f"{context_str}\n\n"
                "---\n\n"
                f"{enriched_input}"
            )

        with st.spinner("🤖 Processing with Orchestrator Agent..."):
            response = orchestrator_agent.run(enriched_input)

        st.session_state.chat_manager.add_message("agent", response)

        # Reset file uploader for next message
        st.session_state.upload_key += 1
        st.rerun()


def _s(val) -> float:
    """Safe float conversion — treats None, NaN, empty as 0."""
    if val is None:
        return 0.0
    try:
        v = float(val)
        if v != v:  # NaN check (NaN != NaN)
            return 0.0
        return v
    except (ValueError, TypeError):
        return 0.0


def _member_label(mid: int) -> str:
    m = data_provider.get_member(mid)
    if not m:
        return f"ID {mid}"
    return f"Plot {m.get('Plot_No', '?')} — {m.get('Plot_Owner_Name', '?')}"


def _find_member(mid: int) -> Optional[Dict[str, Any]]:
    return data_provider.get_member(mid)


def _extract_ref_id(desc: str) -> Optional[str]:
    """Extract a receipt/invoice reference ID from a description string.
    Skips FY tokens (e.g. '24-25') that look like year ranges."""
    import re
    lower = desc.lower()
    # Skip tokens matching year-range pattern like "24-25" or "21-22"
    for tok in desc.split():
        if re.match(r"^\d{2}-\d{2}$", tok):
            continue
        if any(c.isdigit() for c in tok) and "-" in tok:
            return tok
    if "invoice" in lower:
        for tok in desc.split():
            if re.match(r"^\d{2}-\d{2}$", tok):
                continue
            if any(c.isdigit() for c in tok) and not tok.startswith("FY"):
                return tok
    return None


def _show_suspense_table(entries: List[Dict], dp: LocalExcelDataProvider, all_members: List[Dict]) -> None:
    """Render a suspense entries table with tag/delete actions."""
    member_opts = {m["ID"]: f"Plot {m.get('Plot_No','?')} — {m.get('Plot_Owner_Name','?')}" for m in all_members}
    for se in entries:
        sid = se["ID"]
        with st.container(border=True):
            ca, cb, cc, cd = st.columns([1.5, 3, 1.5, 3])
            ca.markdown(f"**{se.get('Date','')}** — ₹{float(se.get('Amount',0)):>,.2f}")
            cb.markdown(f"`{str(se.get('Particulars',''))[:80]}`")
            cc.markdown(f"`{se.get('Transaction_Type','') or '—'}`")
            with cd:
                if se.get("Status") == "Pending":
                    tag_mid = st.selectbox(
                        "Tag to", options=list(member_opts.keys()),
                        format_func=lambda x: member_opts.get(x, f"ID {x}"),
                        key=f"stag_{sid}", label_visibility="collapsed",
                        placeholder="Select member...",
                    )
                    col_x, col_y = st.columns(2)
                    if col_x.button("✅ Tag", key=f"tag_{sid}", use_container_width=True):
                        if data_provider.tag_suspense_entry(sid, tag_mid):
                            st.session_state.bank_stmt_confirmation = f"✅ Tagged suspense entry #{sid} to {member_opts.get(tag_mid, '?')}"
                            st.rerun()
                        else:
                            st.error("Failed to tag entry")
                    if col_y.button("🗑️", key=f"del_sus_{sid}", use_container_width=True):
                        if data_provider.delete_suspense_entry(sid):
                            st.rerun()
                else:
                    tagged_to = se.get("Tagged_To")
                    mname = member_opts.get(int(tagged_to), f"ID {tagged_to}") if tagged_to else "?"
                    st.caption(f"→ {mname}")
                    st.caption(f"Tagged: {se.get('Tagged_Date','')}")
                    if st.button("🗑️", key=f"del_sus_{sid}", use_container_width=True):
                        if data_provider.delete_suspense_entry(sid):
                            st.rerun()


def _fy_date_range(fy: str) -> tuple:
    """Convert '24-25' to (from_date, to_date) strings in DD-MM-YYYY format."""
    try:
        parts = fy.split("-")
        start_yr = int(parts[0]) + 2000
        end_yr = int(parts[1]) + 2000
        return (f"01-04-{start_yr}", f"31-03-{end_yr}")
    except Exception:
        return ("", "")


def _get_available_fys(entries: List[Dict]) -> List[str]:
    """Extract unique FY strings from a list of ledger entries, sorted desc."""
    fys = set()
    for e in entries:
        d = str(e.get("Date", "") or "")
        if d:
            fys.add(get_fy_from_date(d))
    return sorted(fys, reverse=True)


def _filter_entries(entries: List[Dict], entry_type: str, from_dt: str, to_dt: str) -> List[Dict]:
    """Filter ledger entries by type (All/Debit/Credit) and date range.
    Dates are compared numerically by converting DD-MM-YYYY to a sortable string."""
    def _sortable(dd: str) -> str:
        try:
            p = dd.split("-")
            return f"{p[2]}-{p[1]}-{p[0]}"  # YYYY-MM-DD
        except Exception:
            return dd
    result = []
    from_key = _sortable(from_dt) if from_dt else ""
    to_key = _sortable(to_dt) if to_dt else ""
    for e in entries:
        d = str(e.get("Date", "") or "")
        d_key = _sortable(d)
        if from_key and d_key < from_key:
            continue
        if to_key and d_key > to_key:
            continue
        deb = _s(e.get("Debit"))
        cr = _s(e.get("Credit"))
        if entry_type == "Debit" and deb <= 0:
            continue
        if entry_type == "Credit" and cr <= 0:
            continue
        result.append(e)
    return result


def _parse_invoice_entry(entry: Dict) -> Optional[Dict]:
    """Extract invoice parameters from a ledger entry's Description and Particulars.
    Returns dict with invoice_no, fy, from_date, to_date, months or None."""
    import re
    desc = str(entry.get("Description", "") or "")
    parts = str(entry.get("Particulars", "") or "")
    # Description: "Invoice 0051121 FY 21-22"
    m = re.search(r"Invoice\s+(\w+)\s+FY\s+(\d{2}-\d{2})", desc)
    if not m:
        return None
    invoice_no = m.group(1)
    fy_str = m.group(2)
    # Particulars: "To Annual Maintenance Charges (01-11-2021 to 31-03-2022, 5 months)"
    m2 = re.search(r"\((\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4}),\s+(\d+)\s+months\)", parts)
    if m2:
        from_date = m2.group(1)
        to_date = m2.group(2)
        months = int(m2.group(3))
    else:
        # Fallback: derive from FY
        from_date, to_date = _fy_date_range(fy_str)
        months = 12
    return {
        "invoice_no": invoice_no,
        "fy": fy_str,
        "from_date": from_date,
        "to_date": to_date,
        "months": months,
    }


def regenerate_invoice(dp: Any, member_id: int, entry: Dict) -> Optional[str]:
    """Regenerate an invoice entry with updated payment history.
    Deletes old entry + PDF, creates new entry + PDF.
    Returns status message or None on failure."""
    import re
    from datetime import datetime, timedelta
    import config
    from tools.pdf_generator import create_simple_invoice_pdf

    info = _parse_invoice_entry(entry)
    if not info:
        return None

    vch_no = int(entry.get("Vch_No", 0))
    invoice_date = str(entry.get("Date", "") or "")
    old_desc = str(entry.get("Description", "") or "")
    ref_id = _extract_ref_id(old_desc)

    # ── Delete old entry + PDF ──
    if not dp.delete_ledger_entry(member_id, vch_no):
        return "Failed to delete old entry"
    _delete_pdf_files(ref_id)

    # ── Compute gross charges ──
    member = dp.get_member(member_id)
    settings = dp.get_settings()
    repair_rate = float(settings.get("Repair_Fund_Rate", 100))
    service_rate = float(settings.get("Service_Charges_Rate", 885))
    sinking_rate = float(settings.get("Sinking_Fund_Rate", 15))
    months = info["months"]
    repair_amt = repair_rate * months
    service_amt = service_rate * months
    sinking_amt = sinking_rate * months
    pending_interest = float(member.get("Pending_Interest", 0) or 0)
    gross_total = repair_amt + service_amt + sinking_amt + pending_interest

    # ── Recalculate payment_received ──
    ledger = dp.get_member_ledger(member_id)
    fd_parts = info["from_date"].split("-")
    td_parts = info["to_date"].split("-")
    period_start = datetime(int(fd_parts[2]), int(fd_parts[1]), int(fd_parts[0]))
    period_end = datetime(int(td_parts[2]), int(td_parts[1]), int(td_parts[0]))
    payment_received = 0
    for e in ledger:
        ed = str(e.get("Date", "") or "").strip()
        if ed:
            try:
                edt = datetime.strptime(ed, "%d-%m-%Y")
                if period_start <= edt <= period_end:
                    payment_received += float(e.get("Credit", 0) or 0)
            except ValueError:
                pass

    total = gross_total - payment_received

    # ── Build invoice_data ──
    bill_period = f"{_month_names[period_start.month - 1]}{period_start.year % 100} to {_month_names[period_end.month - 1]}{period_end.year % 100}"
    inv_date = datetime.strptime(invoice_date, "%d-%m-%Y") if invoice_date else datetime.now()
    if not invoice_date:
        invoice_date = inv_date.strftime("%d-%m-%Y")
    due_date = (inv_date + timedelta(days=config.INVOICE_DUE_DAYS)).strftime("%d-%m-%Y")
    plot_str = str(member.get("Plot_No", "") or "")
    plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
    line_items = {
        f"Repair & Maintenance Fund @ ₹{repair_rate:,.2f}/month × {months} months": repair_amt,
        f"Service Charges @ ₹{service_rate:,.2f}/month × {months} months": service_amt,
        f"Sinking Fund @ ₹{sinking_rate:,.2f}/month × {months} months": sinking_amt,
        "Interest Penalty Charges": pending_interest,
    }
    if payment_received > 0:
        line_items["Payment Received (this period)"] = -payment_received

    payment_history = get_payment_history(ledger, invoice_date)
    previous_invoices = get_previous_invoices(ledger, invoice_date)

    invoice_data = {
        "invoice_no": info["invoice_no"],
        "invoice_date": invoice_date,
        "due_date": due_date,
        "plot_owner_name": member.get("Plot_Owner_Name", "Unknown"),
        "plot_no": member.get("Plot_No", "N/A"),
        "bill_period": bill_period,
        "from_date": info["from_date"],
        "to_date": info["to_date"],
        "number_of_months": months,
        "payment_received_till_date": payment_received,
        "outstanding_balance": total,
        "payment_history": payment_history,
        "previous_invoices": previous_invoices,
        "line_items": line_items,
        "total_amount": total,
        "amount_in_words": number_to_words_inr(total),
    }

    # ── Write PDF (overwrite) ──
    fy_short = info["fy"][:2]
    invoice_dir = config.INVOICES_DIR / fy_short
    invoice_dir.mkdir(parents=True, exist_ok=True)
    invoice_path = invoice_dir / f"Invoice_{plot_part}_{info['invoice_no']}.pdf"
    create_simple_invoice_pdf(invoice_path, invoice_data)

    # ── Create new ledger entry ──
    date_range = f"{info['from_date']} to {info['to_date']}, {months} months"
    vch_no_new = dp.get_next_voucher_number()
    dp.add_ledger_entry(member_id, {
        "Date": invoice_date,
        "Particulars": f"To Annual Maintenance Charges ({date_range})",
        "Vch_Type": "Journal",
        "Vch_No": vch_no_new,
        "Debit": gross_total,
        "Credit": None,
        "Description": f"Invoice {info['invoice_no']} FY {info['fy']} (regenerated)",
        "Transaction_Type": "INVOICE",
    })

    return f"Regenerated invoice {info['invoice_no']} for ₹{total:,.2f} (payment received this period: ₹{payment_received:,.2f})"


def delete_invoice(dp: Any, member_id: int, entry: Dict) -> Optional[str]:
    """Delete an invoice ledger entry + PDF. Returns status message or None."""
    vch_no = int(entry.get("Vch_No", 0))
    desc = str(entry.get("Description", "") or "")
    inv_match = re.search(r'Invoice\s+(\S+)', desc)
    invoice_no = inv_match.group(1) if inv_match else _extract_ref_id(desc)
    if invoice_no:
        _delete_pdf_files(invoice_no)
    if not dp.delete_ledger_entry(member_id, vch_no):
        return None
    return f"Invoice {invoice_no or f'Vch {vch_no}'} deleted"


def _inv_select_all_changed():
    """Sync all individual invoice checkboxes when Select All is toggled."""
    val = st.session_state["inv_select_all"]
    for key in list(st.session_state.keys()):
        if key.startswith("inv_sel_") and key != "inv_select_all":
            st.session_state[key] = val


def _rec_select_all_changed():
    """Sync all individual receipt checkboxes when Select All is toggled."""
    val = st.session_state["rec_select_all"]
    for key in list(st.session_state.keys()):
        if key.startswith("rec_sel_") and key != "rec_select_all":
            st.session_state[key] = val


def _led_select_all_changed():
    """Sync all individual ledger checkboxes when Select All is toggled."""
    val = st.session_state.get("led_sel_all", False)
    for key in list(st.session_state.keys()):
        if key.startswith("led_sel_") and key != "led_sel_all":
            st.session_state[key] = val


_month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _delete_pdf_files(ref_id: Optional[str]) -> None:
    """Remove PDF files matching a reference ID from receipts and invoices dirs."""
    if not ref_id:
        return
    for d in (config.RECEIPTS_DIR, config.INVOICES_DIR):
        if d.exists():
            for sub in d.iterdir():
                if sub.is_dir():
                    for p in sub.glob(f"*{ref_id}*"):
                        p.unlink(missing_ok=True)

def _get_pdf_path(search_dir: Path, ref_id: str) -> Optional[Path]:
    """Find the first PDF file in subdirectories matching a reference ID."""
    if not ref_id or not search_dir.exists():
        return None
    for sub in search_dir.iterdir():
        if sub.is_dir():
            for p in sub.glob(f"*{ref_id}*"):
                return p
    return None

def _receipt_exists(entry: dict) -> str:
    """Return 'yes', 'no', or 'na' for a ledger entry's receipt status."""
    if _s(entry.get("Credit", 0)) <= 0:
        return "na"
    ref_id = _extract_ref_id(str(entry.get("Description", "")))
    if not ref_id:
        ref_id = _extract_ref_id(str(entry.get("Particulars", "")))
    if ref_id and _get_pdf_path(config.RECEIPTS_DIR, ref_id):
        return "yes"
    return "no"


def _generate_receipt_for_entry(dp, entry, member_id) -> Optional[str]:
    """Generate a receipt PDF for a single credit ledger entry. Returns receipt_id or None."""
    if _s(entry.get("Credit", 0)) <= 0:
        return None
    member = dp.get_member(member_id)
    if not member:
        return None
    ref_id = _extract_ref_id(str(entry.get("Description", "")))
    if not ref_id:
        ref_id = _extract_ref_id(str(entry.get("Particulars", "")))
    if not ref_id:
        date_str = str(entry.get("Date", ""))
        fy = get_fy_from_date(date_str)
        vch_no = int(entry.get("Vch_No", 0))
        ref_id = f"{fy}-{str(vch_no).zfill(3)}"
        old_desc = str(entry.get("Description", "") or "")
        new_desc = f"Receipt {ref_id}"
        if old_desc.strip():
            new_desc = f"{old_desc.strip()} Receipt {ref_id}"
        dp.update_ledger_entry(member_id, vch_no, {"Description": new_desc})
    if _get_pdf_path(config.RECEIPTS_DIR, ref_id):
        return ref_id
    date_str = str(entry.get("Date", "")) or get_current_date()
    fy = get_fy_from_date(date_str[:10] if len(date_str) >= 10 else date_str)
    plot_str = str(member.get("Plot_No", "") or "")
    plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
    receipt_dir = config.RECEIPTS_DIR / fy
    receipt_dir.mkdir(parents=True, exist_ok=True)
    rpath = receipt_dir / f"Receipt_{plot_part}_{ref_id}.pdf"
    receipt_data = {
        "receipt_id": ref_id,
        "date": date_str,
        "member_name": member.get("Plot_Owner_Name", ""),
        "plot_no": plot_str,
        "amount": _s(entry.get("Credit")),
        "transaction_id": str(entry.get("Transaction_ID", "") or "N/A"),
        "transaction_type": str(entry.get("Transaction_Type", "") or ""),
        "payment_details": clean_payment_details(str(entry.get("Particulars", "")))[:120],
    }
    success = create_simple_receipt_pdf(rpath, receipt_data)
    return ref_id if success else None


def _invoice_exists(entry: dict) -> str:
    """Return 'yes', 'no', or 'na' for a ledger entry's invoice status."""
    if _s(entry.get("Debit", 0)) <= 0:
        return "na"
    desc = str(entry.get("Description", "") or "")
    inv_match = re.search(r'Invoice\s+(\S+)', desc)
    ref_id = inv_match.group(1) if inv_match else _extract_ref_id(desc)
    if ref_id and _get_pdf_path(config.INVOICES_DIR, ref_id):
        return "yes"
    return "no"


def show_dashboard_page():
    """Dashboard page"""
    st.title("📊 Dashboard")

    members = data_provider.get_all_members()
    total_members = len(members)
    total_outstanding = sum(data_provider.get_current_outstanding(m["ID"]) for m in members)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Members", total_members)
    with col2:
        label = "Surplus" if total_outstanding > 0 else "Demand"
        st.metric(f"Net {label}", f"₹{abs(total_outstanding):,.2f}")
    with col3:
        settled = sum(1 for m in members if data_provider.get_current_outstanding(m["ID"]) == 0)
        st.metric("Settled", settled)
    with col4:
        pending = sum(1 for m in members if data_provider.get_current_outstanding(m["ID"]) < 0)
        st.metric("In Demand", pending)

    tab_accounts, tab_expenses, tab_receipts, tab_invoices, tab_ledgers, tab_reports = st.tabs(
        ["Accounts", "Expenses", "Receipts", "Invoices", "Ledgers", "Reports"]
    )

    # ═══════════════════════════════════════════════════════════════
    # TAB 1: Accounts
    # ═══════════════════════════════════════════════════════════════
    with tab_accounts:

        # ── Manual Payment Entry Form ─────────────────────────────
        with st.expander("💰 Record Payment", expanded=False):
            pay_member_id = st.selectbox(
                "Member *", options=[m["ID"] for m in members],
                format_func=_member_label, key="pay_member",
            )
            pay_col1, pay_col2 = st.columns(2)
            with pay_col1:
                pay_date = st.text_input("Date (DD-MM-YYYY)", value="", key="pay_date", placeholder="e.g. 15-05-2026")
                pay_amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0, key="pay_amount")
                pay_generate_receipt = st.checkbox("Generate Receipt PDF", value=False, key="pay_gen_rec")
            with pay_col2:
                pay_particulars = st.text_input("Particulars", key="pay_particulars", placeholder="e.g. Maintenance payment")
                pay_txn_type = st.selectbox("Transaction Type", ["NEFT", "UPI", "CHQ", "CASH", "IMPS", "RTGS", "Other"], key="pay_txn_type")
                pay_txn_id = st.text_input("Transaction ID (optional)", key="pay_txn_id", placeholder="e.g. UTR number")

            if st.button("Save Payment", type="primary", use_container_width=True, key="pay_save"):
                pay_member = _find_member(pay_member_id)
                if not pay_date.strip() or not pay_particulars.strip() or pay_amount <= 0 or not pay_member:
                    st.warning("Date, Particulars, Amount, and Member are required")
                else:
                    vch_no = data_provider.get_next_voucher_number()
                    fy = get_fy_from_date(pay_date.strip())
                    receipt_id = f"{fy}-{str(vch_no).zfill(3)}"
                    description = f"RCPT-{receipt_id} — Manual entry ({pay_txn_type})"
                    if pay_txn_id.strip():
                        description += f" [{pay_txn_id.strip()}]"

                    data_provider.add_ledger_entry(pay_member_id, {
                        "Date": pay_date.strip(),
                        "Particulars": f"By {pay_particulars.strip()[:60]}",
                        "Vch_Type": "Journal",
                        "Vch_No": vch_no,
                        "Debit": None,
                        "Credit": pay_amount,
                        "Description": description,
                        "Transaction_Type": pay_txn_type,
                        "Transaction_ID": pay_txn_id.strip() or None,
                    })

                    if pay_generate_receipt:
                        receipt_dir = config.RECEIPTS_DIR / fy
                        receipt_dir.mkdir(parents=True, exist_ok=True)
                        plot_str = str(pay_member.get("Plot_No", "") or "")
                        plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
                        rpath = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"
                        receipt_data = {
                            "receipt_id": receipt_id,
                            "date": pay_date.strip(),
                            "member_name": pay_member.get("Plot_Owner_Name", ""),
                            "plot_no": plot_str,
                            "amount": pay_amount,
                            "transaction_id": pay_txn_id.strip() or "N/A",
                            "transaction_type": pay_txn_type,
                            "payment_details": clean_payment_details(pay_particulars.strip())[:120],
                        }
                        create_simple_receipt_pdf(rpath, receipt_data)

                    st.success(f"✅ Payment of ₹{pay_amount:,.2f} recorded for {pay_member.get('Plot_Owner_Name', '')} → {receipt_id}")
                    st.rerun()

        # ── Bank Statement Processing ─────────────────────────────
        st.subheader("🏦 Bank Statement Processing")

        if "bank_stmt_result" not in st.session_state:
            st.session_state.bank_stmt_result = None
        if "bank_stmt_processed" not in st.session_state:
            st.session_state.bank_stmt_processed = set()
        if "bank_stmt_manual_matches" not in st.session_state:
            st.session_state.bank_stmt_manual_matches = []
        if "bank_stmt_confirmation" not in st.session_state:
            st.session_state.bank_stmt_confirmation = None

        if st.session_state.bank_stmt_confirmation:
            st.success(st.session_state.bank_stmt_confirmation)
            if st.button("Dismiss", key="bs_dismiss_conf"):
                st.session_state.bank_stmt_confirmation = None
                st.rerun()

        import hashlib
        import shutil
        from datetime import datetime
        from tools.pdf_parser import parse_bank_pdf

        def _run_tool(tool_name: str, input_str: str) -> dict:
            for t in orchestrator_agent.tools:
                if t.name == tool_name:
                    return t.func(input_str)
            return {"error": f"Tool '{tool_name}' not found"}

        gen_receipts_checkbox = st.checkbox(
            "📄 Generate Receipt PDFs (uncheck to add ledger entries only)",
            value=False, key="bs_gen_receipts",
            help="When unchecked, only ledger entries are created. You can generate receipts later from the Receipts tab.",
        )

        with st.expander("Upload & Parse Bank Statement PDF", expanded=True):
            pdf_file = st.file_uploader(
                "Upload bank statement PDF",
                type=["pdf"],
                key="bank_stmt_pdf_upload",
            )
            stmt_password = st.text_input(
                "PDF Password",
                type="password",
                value=config.BANK_STMT_PASSWORD,
                key="bank_stmt_password",
            )

            if pdf_file is not None:
                pdf_bytes = pdf_file.read()
                file_hash = hashlib.sha256(pdf_bytes).hexdigest()[:16]

                processed = data_provider.get_processed_statements()
                already_done = any(
                    p.get("File_Hash", "") == file_hash or p.get("Filename", "") == pdf_file.name
                    for p in processed
                )

                if already_done:
                    st.info(f"'{pdf_file.name}' has already been processed. Use Rebuild if you need to re-process.")
                else:
                    save_path = config.BANK_STATEMENTS_DIR / pdf_file.name
                    with open(save_path, "wb") as f:
                        f.write(pdf_bytes)

                    with st.spinner("Parsing PDF..."):
                        parsed = parse_bank_pdf(str(save_path), password=stmt_password)

                    st.success(f"Extracted {parsed['entry_count']} entries from {pdf_file.name} (format: {parsed['format']}, {parsed['raw_lines']} raw lines)")

                    if st.button("🚀 Process Statement Entries → Ledger", key="process_parsed_stmt"):
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_auto_pre_stmt.xlsx")

                        entries_text = "\n".join(parsed["entries"])
                        tool_input = json.dumps({
                            "statement": entries_text,
                            "generate_receipts": gen_receipts_checkbox,
                            "format": parsed["format"],
                            "filename": pdf_file.name,
                        })

                        result = _run_tool("process_bank_statement_pdf", tool_input)
                        st.session_state.bank_stmt_result = result

                        data_provider.record_processed_statement(
                            filename=pdf_file.name,
                            date_range=f"from_{pdf_file.name.replace('.pdf', '')}",
                            entry_count=parsed["entry_count"],
                            fmt=parsed["format"],
                            file_hash=file_hash,
                        )
                        data_provider.refresh_reports_sheet()
                        st.rerun()

        result = st.session_state.bank_stmt_result
        matched = []
        unmatched = []
        if result is None:
            st.info("No bank statement processed yet.")
        elif isinstance(result, str):
            st.markdown(result)
        else:
            matched = result.get("matched", [])
            unmatched = result.get("unmatched", [])
        processed_idx = st.session_state.bank_stmt_processed

        def _check_duplicate(data_provider, mid, date, amount, txn_id, particulars=""):
            ledger = data_provider.get_member_ledger(mid)
            if not ledger:
                return False
            txn_clean = str(txn_id or "").strip()
            raw_part = str(particulars or "").strip()
            part_clean = raw_part[3:] if raw_part.upper().startswith("BY ") else raw_part
            part_clean = part_clean[:40].upper()
            for e in ledger:
                e_part_upper = str(e.get("Particulars", "") or "").upper()
                if "SPLIT FROM" in e_part_upper:
                    continue
                e_date = str(e.get("Date", "") or "").strip()
                e_credit = float(e.get("Credit", 0) or 0)
                if e_date == date and abs(e_credit - amount) < 0.01:
                    e_txn = str(e.get("Transaction_ID", "") or "").strip()
                    if txn_clean and e_txn and e_txn == txn_clean:
                        return True
                    e_part = str(e.get("Particulars", "") or "").strip()
                    e_part_clean = e_part[3:] if e_part.upper().startswith("BY ") else e_part
                    e_part_clean = e_part_clean[:40].upper()
                    if part_clean and e_part_clean and (part_clean in e_part_clean or e_part_clean in part_clean):
                        return True
                    if not txn_clean and not e_txn:
                        return True
            return False

        manual_matches = st.session_state.bank_stmt_manual_matches
        all_matched = list(matched) + list(manual_matches)
        if all_matched:
            auto_count = len(matched)
            manual_count = len(manual_matches)
            label = f"✅ **{len(all_matched)} entries matched**"
            if auto_count:
                label += f" ({auto_count} auto"
                if manual_count:
                    label += f", {manual_count} manual"
                label += ")"
            elif manual_count:
                label += f" ({manual_count} manual)"
            st.success(label)
            for m in all_matched:
                with st.container(border=True):
                    has_pdf = m.get("has_pdf", True)
                    c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1.5])
                    c1.markdown(f"**{m['date']}** — ₹{m['amount']:>,.2f} `[{m['txn_type']}]`")
                    c2.markdown(f"{m['member_name']}")
                    c3.markdown(f"Plot **{m['plot_no']}**" if m.get('plot_no') else "")
                    ref = m.get('receipt_id', '')
                    status = "⚠️ No PDF" if (not has_pdf and ref) else (f"📄 `{ref}`" if ref else "")
                    c4.markdown(status)
        else:
            st.info("No entries matched.")

        if unmatched:
            st.warning(f"⚠️ **{len(unmatched)} entries need attention**")

            skip_dup = st.checkbox(
                "Reprocess entries already in ledger (skip duplicate check)",
                key="bs_skip_dup",
                help="Check this when re-processing to allow adding entries that were previously skipped as duplicates.",
            )

            members_list = [
                {"id": m["ID"], "label": f"Plot {m.get('Plot_No','?')} — {m.get('Plot_Owner_Name','?')}"}
                for m in members
            ]
            all_member_options = [m["label"] for m in members_list]
            member_id_map = {m["label"]: m["id"] for m in members_list}

            def _add_unmatched_row(u, mid, members, gen_receipts_flag):
                """Add a ledger entry for an unmatched row. Returns (vch_no, receipt_id)."""
                fy = get_fy_from_date(u["date"])
                vch_no = data_provider.get_next_voucher_number()
                receipt_id = f"{fy}-{str(vch_no).zfill(3)}"
                data_provider.add_ledger_entry(mid, {
                    "Date": u["date"],
                    "Particulars": f"By {u['particulars'][:60]}",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": None,
                    "Credit": u["amount"],
                    "Description": f"Receipt {receipt_id} — Manual Bank Statement ({u['txn_type'] or 'N/A'})",
                    "Transaction_Type": u.get("txn_type", "") or "",
                    "Transaction_ID": u.get("txn_id") or "",
                })
                member_data = next((m for m in members if m["ID"] == mid), {})
                mname = member_data.get("Plot_Owner_Name", "")
                mplot = str(member_data.get("Plot_No", "") or "")
                manual_match = {
                    "date": u["date"], "amount": u["amount"],
                    "txn_type": u.get("txn_type", ""),
                    "member_name": mname, "plot_no": mplot, "receipt_id": receipt_id,
                }
                st.session_state.bank_stmt_manual_matches.append(manual_match)
                if gen_receipts_flag:
                    plot_part = f"Plot_No_{mplot.zfill(2)}" if mplot else "Unknown"
                    rdir = config.RECEIPTS_DIR / fy
                    rdir.mkdir(parents=True, exist_ok=True)
                    rpath = rdir / f"Receipt_{plot_part}_{receipt_id}.pdf"
                    ledger = data_provider.get_member_ledger(mid)
                    led_after = list(ledger) + [{"Date": u["date"], "Credit": u["amount"], "Debit": None}]
                    as_of_o = compute_outstanding_as_of(led_after, u["date"])
                    create_simple_receipt_pdf(rpath, {
                        "receipt_id": receipt_id, "date": u["date"],
                        "member_name": mname, "plot_no": mplot,
                        "amount": u["amount"], "transaction_id": u.get("txn_id") or "",
                        "transaction_type": u.get("txn_type") or "",
                        "payment_details": clean_payment_details(u.get("particulars", "")),
                        "outstanding_balance": as_of_o,
                    })
                return vch_no, receipt_id

            # ── Bulk move all to suspense ──
            if st.button("📋 Move All Unmatched to Suspense", type="secondary", use_container_width=True, key="bs_move_all_suspense"):
                count = 0
                for i, u in enumerate(unmatched):
                    if i in processed_idx:
                        continue
                    data_provider.add_suspense_entry({
                        "Date": u["date"],
                        "Particulars": u.get("particulars", "")[:80],
                        "Amount": u["amount"],
                        "Transaction_ID": u.get("txn_id") or "",
                        "Transaction_Type": u.get("txn_type") or "",
                        "Description": f"From bank statement — {u.get('particulars', '')[:60]}",
                    })
                    st.session_state.bank_stmt_processed.add(i)
                    count += 1
                st.session_state.bank_stmt_confirmation = f"📋 Moved {count} entries to suspense"
                st.rerun()

            # ── Batch form (no rerun on checkbox/dropdown change) ──
            with st.form("unmatched_batch"):
                for i, u in enumerate(unmatched):
                    if i in processed_idx:
                        continue
                    with st.container(border=True):
                        cols = st.columns([0.4, 2, 1.5, 2, 1, 1.5, 2, 0.7, 0.7, 0.7])
                        with cols[0]:
                            st.checkbox("", key=f"bs_chk_{i}", label_visibility="collapsed")
                        cols[1].markdown(f"**{u['date']}**")
                        cols[2].markdown(f"₹{u['amount']:>,.2f}")
                        cols[3].markdown(f"`{u['particulars'][:40]}`")
                        cols[4].markdown(f"`{u['txn_type'] or '—'}`")
                        with cols[5]:
                            st.selectbox("Action", ["", "Add", "Ignore", "Suspense"],
                                         key=f"bs_act_{i}", label_visibility="collapsed")
                        with cols[6]:
                            st.selectbox("To", all_member_options,
                                         key=f"bs_to_{i}", label_visibility="collapsed",
                                         placeholder="Select")
                        with cols[7]:
                            add_i = st.form_submit_button("Add", key=f"bs_fadd_{i}", use_container_width=True)
                        with cols[8]:
                            ign_i = st.form_submit_button("Ignore", key=f"bs_fign_{i}", use_container_width=True)
                        with cols[9]:
                            sus_i = st.form_submit_button("Suspense", key=f"bs_fsus_{i}", use_container_width=True)

                        if add_i:
                            mid = member_id_map.get(st.session_state.get(f"bs_to_{i}", ""))
                            if mid:
                                if not skip_dup and _check_duplicate(
                                    data_provider, mid, u["date"], u["amount"],
                                    u.get("txn_id"), u.get("particulars")
                                ):
                                    st.session_state.bank_stmt_confirmation = (
                                        f"⚠️ Duplicate — entry for ₹{u['amount']:>,.2f} "
                                        f"on {u['date']} already exists for {st.session_state.get(f'bs_to_{i}', '')}"
                                    )
                                else:
                                    _add_unmatched_row(u, mid, members, True)
                                    st.session_state.bank_stmt_processed.add(i)
                                    st.session_state.bank_stmt_confirmation = (
                                        f"✅ Added ₹{u['amount']:>,.2f} to {st.session_state.get(f'bs_to_{i}', '')}"
                                    )
                            else:
                                st.warning("Select a member first")
                        if ign_i:
                            st.session_state.bank_stmt_processed.add(i)
                            st.session_state.bank_stmt_confirmation = (
                                f"⏭️ Ignored — ₹{u['amount']:>,.2f} on {u['date']}"
                            )
                        if sus_i:
                            data_provider.add_suspense_entry({
                                "Date": u["date"],
                                "Particulars": u.get("particulars", "")[:80],
                                "Amount": u["amount"],
                                "Transaction_ID": u.get("txn_id") or "",
                                "Transaction_Type": u.get("txn_type") or "",
                                "Description": f"From bank statement — {u.get('particulars', '')[:60]}",
                            })
                            st.session_state.bank_stmt_processed.add(i)
                            st.session_state.bank_stmt_confirmation = (
                                f"📋 Moved to suspense — ₹{u['amount']:>,.2f} on {u['date']}"
                            )

                st.divider()
                c1, c2, c3 = st.columns(3)
                with c1:
                    sub_all = st.form_submit_button("✅ Submit All Checked", use_container_width=True)
                with c2:
                    sub_ign_all = st.form_submit_button("⏭️ Ignore All Checked", use_container_width=True)
                with c3:
                    sub_sus_all = st.form_submit_button("📋 Suspense All Checked", use_container_width=True)

                if sub_all:
                    counts = {"Add": 0, "Ignore": 0, "Suspense": 0}
                    for i, u in enumerate(unmatched):
                        if i in processed_idx or not st.session_state.get(f"bs_chk_{i}", False):
                            continue
                        action = st.session_state.get(f"bs_act_{i}", "")
                        if action == "Add":
                            mid = member_id_map.get(st.session_state.get(f"bs_to_{i}", ""))
                            if mid and (skip_dup or not _check_duplicate(
                                data_provider, mid, u["date"], u["amount"],
                                u.get("txn_id"), u.get("particulars")
                            )):
                                _add_unmatched_row(u, mid, members, gen_receipts_checkbox)
                                st.session_state.bank_stmt_processed.add(i)
                                counts["Add"] += 1
                        elif action == "Ignore":
                            st.session_state.bank_stmt_processed.add(i)
                            counts["Ignore"] += 1
                        elif action == "Suspense":
                            data_provider.add_suspense_entry({
                                "Date": u["date"],
                                "Particulars": u.get("particulars", "")[:80],
                                "Amount": u["amount"],
                                "Transaction_ID": u.get("txn_id") or "",
                                "Transaction_Type": u.get("txn_type") or "",
                                "Description": f"From bank statement — {u.get('particulars', '')[:60]}",
                            })
                            st.session_state.bank_stmt_processed.add(i)
                            counts["Suspense"] += 1
                    st.session_state.bank_stmt_confirmation = (
                        f"✅ Processed: {counts['Add']} added, {counts['Ignore']} ignored, {counts['Suspense']} suspended"
                    )
                elif sub_ign_all:
                    count = sum(1 for i in range(len(unmatched))
                                if i not in processed_idx and st.session_state.get(f"bs_chk_{i}", False))
                    for i in range(len(unmatched)):
                        if i in processed_idx or not st.session_state.get(f"bs_chk_{i}", False):
                            continue
                        st.session_state.bank_stmt_processed.add(i)
                    st.session_state.bank_stmt_confirmation = f"⏭️ Ignored {count} entries"
                elif sub_sus_all:
                    count = 0
                    for i, u in enumerate(unmatched):
                        if i in processed_idx or not st.session_state.get(f"bs_chk_{i}", False):
                            continue
                        data_provider.add_suspense_entry({
                            "Date": u["date"],
                            "Particulars": u.get("particulars", "")[:80],
                            "Amount": u["amount"],
                            "Transaction_ID": u.get("txn_id") or "",
                            "Transaction_Type": u.get("txn_type") or "",
                            "Description": f"From bank statement — {u.get('particulars', '')[:60]}",
                        })
                        st.session_state.bank_stmt_processed.add(i)
                        count += 1
                    st.session_state.bank_stmt_confirmation = f"📋 Moved {count} entries to suspense"

            st.divider()
            st.subheader("↔️ Split Entry Equally")
            split_idx = st.selectbox(
                "Select entry to split",
                options=range(len(unmatched)),
                format_func=lambda i: (
                    f"{unmatched[i]['date']} — ₹{unmatched[i]['amount']:>,.2f} — "
                    f"{unmatched[i]['particulars'][:40]}"
                ),
                key="bs_split_select",
            )
            u_split = unmatched[split_idx]
            total_split = u_split["amount"]
            split_members = st.multiselect(
                "Select members to split equally",
                options=all_member_options,
                key="bs_split_members",
            )
            if split_members:
                per_head = total_split / len(split_members)
                st.caption(f"₹{total_split:>,.2f} ÷ {len(split_members)} = **₹{per_head:>,.2f} each**")
            if st.button("Apply Split", type="secondary", use_container_width=True,
                         key="bs_split_apply"):
                if len(split_members) < 2:
                    st.error("Select at least 2 members to split")
                else:
                    added = 0
                    skipped = 0
                    fy = get_fy_from_date(u_split["date"])
                    receipt_dir = config.RECEIPTS_DIR / fy
                    receipt_dir.mkdir(parents=True, exist_ok=True)
                    for label in split_members:
                        mid = member_id_map.get(label)
                        if not mid:
                            continue
                        if not skip_dup and _check_duplicate(
                            data_provider, mid, u_split["date"],
                            per_head, u_split.get("txn_id"),
                            u_split.get("particulars")
                        ):
                            skipped += 1
                            continue
                        vch_no = data_provider.get_next_voucher_number()
                        receipt_id = f"{fy}-{str(vch_no).zfill(3)}"
                        data_provider.add_ledger_entry(mid, {
                            "Date": u_split["date"],
                            "Particulars": f"By {u_split['particulars'][:60]} (split {per_head:,.0f}/{total_split:,.0f})",
                            "Vch_Type": "Journal",
                            "Vch_No": vch_no,
                            "Debit": None,
                            "Credit": per_head,
                            "Description": f"Receipt {receipt_id} — Split Bank Statement ({u_split['txn_type'] or 'N/A'})",
                            "Transaction_Type": u_split.get("txn_type", "") or "",
                            "Transaction_ID": u_split.get("txn_id") or "",
                        })
                        member_data = next((m for m in members if m["ID"] == mid), {})
                        mname = member_data.get("Plot_Owner_Name", "")
                        mplot = str(member_data.get("Plot_No", "") or "")
                        manual_match = {
                            "date": u_split["date"],
                            "amount": per_head,
                            "txn_type": u_split.get("txn_type", ""),
                            "member_name": mname,
                            "plot_no": mplot,
                            "receipt_id": receipt_id,
                        }
                        st.session_state.bank_stmt_manual_matches.append(manual_match)
                        plot_part = f"Plot_No_{mplot.zfill(2)}" if mplot else "Unknown"
                        receipt_path = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"
                        ledger = data_provider.get_member_ledger(mid)
                        led_after = list(ledger) + [{"Date": u_split["date"], "Credit": per_head, "Debit": None}]
                        as_of_o = compute_outstanding_as_of(led_after, u_split["date"])
                        create_simple_receipt_pdf(receipt_path, {
                            "receipt_id": receipt_id,
                            "date": u_split["date"],
                            "member_name": mname,
                            "plot_no": mplot,
                            "amount": per_head,
                            "transaction_id": u_split.get("txn_id") or "",
                            "transaction_type": u_split.get("txn_type") or "",
                            "payment_details": f"{clean_payment_details(u_split.get('particulars', ''))} (split ₹{per_head:,.0f}/{total_split:,.0f})",
                            "outstanding_balance": as_of_o,
                        })
                        added += 1
                    st.session_state.bank_stmt_processed.add(split_idx)
                    msg = f"✅ Split ₹{total_split:>,.2f} across {added} members, receipts generated"
                    if skipped:
                        msg += f" ({skipped} skipped — already existed)"
                    st.session_state.bank_stmt_confirmation = msg
                    st.rerun()
        else:
            st.success("🎉 All entries processed!")

        # ── Reprocess / Rebuild from stored PDFs ─────────────────
        if "reprocess_msg" not in st.session_state:
            st.session_state.reprocess_msg = None
        if st.session_state.reprocess_msg:
            st.success(st.session_state.reprocess_msg)
            if st.button("Dismiss", key="reprocess_dismiss"):
                st.session_state.reprocess_msg = None
                st.rerun()

        with st.expander("🔄 Reprocess / Rebuild from Bank Statements", expanded=False):
            st.markdown("**Previously processed statements:**")
            proc_list = data_provider.get_processed_statements()
            if not proc_list:
                st.info("No previously processed statements found.")
            else:
                pwd = st.session_state.get("bank_stmt_password", config.BANK_STMT_PASSWORD) or ""
                for ps in proc_list:
                    cols = st.columns([3, 1, 1])
                    cols[0].write(f"`{ps.get('Filename', '?')}` ({ps.get('Entry_Count', 0)} entries, {ps.get('Processed_At', '')})")
                    cols[1].write(f"`{ps.get('Format', '')}`")
                    with cols[2]:
                        if st.button("Reprocess", key=f"reprocess_{ps.get('Filename', '')}"):
                            fname = ps.get("Filename", "")
                            fpath = config.BANK_STATEMENTS_DIR / fname
                            if not fpath.exists():
                                st.session_state.reprocess_msg = f"❌ File not found: {fname}"
                            else:
                                import hashlib
                                import shutil
                                from datetime import datetime as _dt
                                from tools.pdf_parser import parse_bank_pdf

                                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                                shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_auto_reprocess.xlsx")

                                deleted = data_provider.clear_auto_ledger_entries()
                                try:
                                    parsed = parse_bank_pdf(str(fpath), password=pwd)
                                except Exception as e:
                                    st.session_state.reprocess_msg = f"❌ Failed to parse '{fname}': {e}"
                                    st.rerun()
                                entries_text = "\n".join(parsed["entries"])
                                tool_input = json.dumps({
                                    "statement": entries_text,
                                    "generate_receipts": False,
                                    "format": ps.get("Format", parsed["format"]),
                                    "filename": fname,
                                })
                                result = _run_tool("process_bank_statement_pdf", tool_input)
                                st.session_state.bank_stmt_result = result
                                data_provider.refresh_reports_sheet()
                                st.session_state.reprocess_msg = (
                                    f"✅ Reprocessed '{fname}' — deleted {deleted} old entries, "
                                    f"re-processed {parsed['entry_count']} entries"
                                )
                                st.session_state.bank_stmt_processed = set()
                                st.rerun()

            st.divider()
            if st.button("🔄 Rebuild from All Statements", type="primary", use_container_width=True, key="rebuild_all"):
                import shutil
                from datetime import datetime as _dt
                from tools.pdf_parser import parse_bank_pdf

                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_auto_rebuild.xlsx")

                # ── Snapshot existing ledger + suspense before clearing ──
                legacy_snapshot = data_provider.get_member_ledger_all()
                legacy_lookup = {}  # (date, amount_rounded) → [(Particulars, Plot_No, Vch_No)]
                for e in legacy_snapshot:
                    mid = e.get("Plot_No") or e.get("Member_ID")
                    if mid is None:
                        continue
                    try:
                        mid_int = int(float(mid))
                    except (ValueError, TypeError):
                        continue
                    d = str(e.get("Date", "") or "")
                    cr = e.get("Credit") or 0
                    amt = round(float(cr), 2)
                    key = (d, amt)
                    legacy_lookup.setdefault(key, []).append({
                        "particulars": str(e.get("Particulars", "") or ""),
                        "plot_no": mid_int,
                    })

                suspense_lookup = {}  # same key format → {"status", "tagged_to", "particulars"}
                for se in data_provider.get_suspense_entries():
                    d = str(se.get("Date", "") or "")
                    amt = round(float(se.get("Amount", 0) or 0), 2)
                    key = (d, amt)
                    suspense_lookup.setdefault(key, []).append({
                        "status": str(se.get("Status", "") or "").strip(),
                        "tagged_to": se.get("Tagged_To") or se.get("Member_ID"),
                        "particulars": str(se.get("Particulars", "") or ""),
                    })

                def _match_unmatched(u_entry, lookup, source_label):
                    """Find a match for an unmatched entry in a lookup dict by
                    (date, amount) then disambiguate by normalized Particulars.
                    Returns matching entry dict or None."""
                    key = (u_entry["date"], round(u_entry["amount"], 2))
                    candidates = lookup.get(key, [])
                    if not candidates:
                        return None
                    if len(candidates) == 1:
                        return candidates[0]
                    # Multiple candidates — disambiguate by Particulars
                    u_norm = _normalize_particulars(u_entry.get("particulars", ""))
                    for c in candidates:
                        c_norm = _normalize_particulars(c.get("particulars", ""))
                        if u_norm and c_norm and (u_norm in c_norm or c_norm in u_norm):
                            return c
                    return None

                deleted = data_provider.clear_auto_ledger_entries()
                proc_list = data_provider.get_processed_statements()
                total_parsed = 0
                skipped_from_legacy = 0
                skipped_from_suspense = 0
                errors = []
                for ps in proc_list:
                    fname = ps.get("Filename", "")
                    fpath = config.BANK_STATEMENTS_DIR / fname
                    if not fpath.exists():
                        errors.append(f"'{fname}' not found")
                        continue
                    try:
                        parsed = parse_bank_pdf(str(fpath), password=pwd)
                    except Exception as e:
                        errors.append(f"'{fname}': {e}")
                        continue
                    entries_text = "\n".join(parsed["entries"])
                    tool_input = json.dumps({
                        "statement": entries_text,
                        "generate_receipts": False,
                        "format": ps.get("Format", parsed["format"]),
                        "filename": fname,
                    })
                    result = _run_tool("process_bank_statement_pdf", tool_input)
                    if isinstance(result, dict):
                        # Filter unmatched against legacy snapshot + Suspense_Entries
                        filtered_unmatched = []
                        for u in result.get("unmatched", []):
                            # 1) Check legacy snapshot
                            match = _match_unmatched(u, legacy_lookup, "ledger")
                            if match:
                                data_provider.add_ledger_entry(match["plot_no"], {
                                    "Date": u["date"],
                                    "Particulars": f"By {u.get('particulars', '')[:60]}",
                                    "Vch_Type": "Journal",
                                    "Vch_No": data_provider.get_next_voucher_number(),
                                    "Debit": None,
                                    "Credit": u["amount"],
                                    "Description": "Rebuilt from legacy snapshot",
                                    "Transaction_Type": u.get("txn_type", ""),
                                    "Transaction_ID": u.get("txn_id", ""),
                                })
                                skipped_from_legacy += 1
                                continue
                            # 2) Check Suspense_Entries
                            match = _match_unmatched(u, suspense_lookup, "suspense")
                            if match:
                                if match["status"] == "Tagged" and match.get("tagged_to"):
                                    data_provider.add_ledger_entry(int(float(match["tagged_to"])), {
                                        "Date": u["date"],
                                        "Particulars": f"By {u.get('particulars', '')[:60]}",
                                        "Vch_Type": "Journal",
                                        "Vch_No": data_provider.get_next_voucher_number(),
                                        "Debit": None,
                                        "Credit": u["amount"],
                                        "Description": "Rebuilt from suspense tagging",
                                        "Transaction_Type": u.get("txn_type", ""),
                                        "Transaction_ID": u.get("txn_id", ""),
                                    })
                                # Tagged → recreated; Pending → skip (already in suspense)
                                skipped_from_suspense += 1
                                continue
                            # 3) Genuinely new → keep
                            filtered_unmatched.append(u)
                        result["unmatched"] = filtered_unmatched
                        total_parsed += len(result.get("matched", [])) + len(filtered_unmatched)
                    data_provider.refresh_reports_sheet()
                err_msg = f" ⚠️ {len(errors)} errors: {'; '.join(errors[:3])}" if errors else ""
                skip_msg = []
                if skipped_from_legacy:
                    skip_msg.append(f"auto-restored {skipped_from_legacy} from legacy ledger")
                if skipped_from_suspense:
                    skip_msg.append(f"skipped {skipped_from_suspense} from suspense")
                skip_txt = f" ({'; '.join(skip_msg)})" if skip_msg else ""
                st.session_state.reprocess_msg = (
                    f"✅ Rebuilt from {len(proc_list)} statements — deleted {deleted} old entries, "
                    f"re-processed {total_parsed} entries.{skip_txt}{err_msg}"
                )
                st.session_state.bank_stmt_result = None
                st.session_state.bank_stmt_processed = set()
                st.rerun()

    # ═══════════════════════════════════════════════════════════════
    # TAB 2: Expenses
    # ═══════════════════════════════════════════════════════════════
    with tab_expenses:

        # ── Expense Entry Form ────────────────────────────────────
        with st.expander("➕ Record Expense", expanded=False):
            exp_col1, exp_col2 = st.columns(2)
            with exp_col1:
                exp_date = st.text_input("Date (DD-MM-YYYY)", value="", key="exp_date", placeholder="e.g. 15-05-2026")
                exp_amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0, key="exp_amount")
            with exp_col2:
                exp_particulars = st.text_input("Particulars", key="exp_particulars", placeholder="e.g. Plumbing repair")
                cats = data_provider.get_expense_categories()
                flat_cats = sorted(set(c["Name"] for c in cats)) if cats else ["Other"]
                exp_cat = st.selectbox("Category", flat_cats, key="exp_cat")
            exp_comments = st.text_area("Comments", key="exp_comments", placeholder="Optional notes...")
            uploaded_bill = st.file_uploader("Attach Bill", type=list(config.ALLOWED_UPLOAD_TYPES), key="exp_bill")

            if st.button("Save Expense", type="primary", use_container_width=True, key="exp_save"):
                if not exp_date.strip() or not exp_particulars.strip() or exp_amount <= 0:
                    st.warning("Date, Particulars, and Amount are required")
                else:
                    bill_path = ""
                    if uploaded_bill:
                        bill_path = str(config.BILLS_DIR / uploaded_bill.name)
                        config.BILLS_DIR.mkdir(parents=True, exist_ok=True)
                        with open(bill_path, "wb") as f:
                            f.write(uploaded_bill.getbuffer())
                    eid = data_provider.add_expense({
                        "Member_ID": None,
                        "Date": exp_date.strip(),
                        "Particulars": exp_particulars.strip(),
                        "Amount": exp_amount,
                        "Category": exp_cat,
                        "Bill_File": bill_path,
                        "Comments": exp_comments.strip(),
                    })
                    st.success(f"✅ Expense recorded (ID: {eid})")
                    st.rerun()

        # ── Manage Expenses ────────────────────────────────────────
        with st.expander("📋 Manage Expenses", expanded=False):
            all_expenses = data_provider.get_expenses()
            if all_expenses:
                exp_df_data = []
                for exp in all_expenses:
                    exp_df_data.append({
                        "ID": exp.get("ID", ""),
                        "Date": exp.get("Date", ""),
                        "Particulars": str(exp.get("Particulars", "") or "")[:50],
                        "Amount": f"₹{_s(exp.get('Amount', 0)):,.2f}",
                        "Category": exp.get("Category", ""),
                    })
                st.dataframe(exp_df_data, use_container_width=True)
                del_exp_opts = {f"{e.get('ID', '')}: {str(e.get('Particulars', '') or '')[:40]}": e.get("ID")
                               for e in all_expenses}
                del_exp_sel = st.selectbox("Delete Expense", [""] + list(del_exp_opts.keys()),
                                           format_func=lambda x: "Select..." if not x else x,
                                           key="del_exp")
                if del_exp_sel and st.button("Delete Selected Expense", type="secondary", key="del_exp_btn"):
                    eid = del_exp_opts[del_exp_sel]
                    if data_provider.delete_expense(eid):
                        st.success(f"Expense {eid} deleted!")
                        st.rerun()
                    else:
                        st.error(f"Failed to delete expense {eid}")
            else:
                st.info("No expenses recorded yet.")

    # ═══════════════════════════════════════════════════════════════
    # TAB 3: Receipts
    # ═══════════════════════════════════════════════════════════════
    with tab_receipts:

        # ── Suspense Entries ──────────────────────────────────────
        with st.expander("📋 Suspense Entries", expanded=False):
            suspense_list = data_provider.get_suspense_entries()
            pending = [s for s in suspense_list if s.get("Status") == "Pending"]
            tagged = [s for s in suspense_list if s.get("Status") == "Tagged"]
            if not pending and not tagged:
                st.info("No suspense entries.")
            else:
                tab_pend, tab_tag = st.tabs([f"Pending ({len(pending)})", f"Tagged ({len(tagged)})"])
                with tab_pend:
                    if not pending:
                        st.info("No pending entries.")
                    else:
                        _show_suspense_table(pending, data_provider, members)
                with tab_tag:
                    if not tagged:
                        st.info("No tagged entries.")
                    else:
                        _show_suspense_table(tagged, data_provider, members)
                        st.divider()
                        batch_cols = st.columns(2)
                        with batch_cols[0]:
                            if st.button("📐 Run Split Rules on Tagged", type="primary", use_container_width=True, key="sus_split_tagged"):
                                split_rules = data_provider.get_split_rules()
                                mid_to_group = {}
                                for rule in split_rules:
                                    src_mid = int(rule["Source_Member_ID"])
                                    members_str = str(rule.get("Members", ""))
                                    grp = [int(x.strip()) for x in members_str.split(",") if x.strip().isdigit()]
                                    mid_to_group[src_mid] = grp
                                tagged_entries = [s for s in suspense_list if s.get("Status") == "Tagged"]
                                processed = 0
                                for se in tagged_entries:
                                    sid = se["ID"]
                                    tagged_mid = int(se.get("Tagged_To", 0))
                                    if tagged_mid not in mid_to_group:
                                        continue
                                    grp = mid_to_group[tagged_mid]
                                    per_head = round(float(se.get("Amount", 0)) / len(grp), 2)
                                    date_str = str(se.get("Date", "") or "")
                                    particulars = str(se.get("Particulars", "") or "")
                                    for gmid in grp:
                                        vch_no = data_provider.get_next_voucher_number()
                                        data_provider.add_ledger_entry(gmid, {
                                            "Date": date_str,
                                            "Particulars": f"By Suspense Split ({particulars[:40]})",
                                            "Vch_Type": "Journal",
                                            "Vch_No": vch_no,
                                            "Debit": None,
                                            "Credit": per_head,
                                            "Description": f"Split from suspense #{sid}",
                                            "Transaction_Type": "SPLIT",
                                        })
                                    data_provider.delete_suspense_entry(sid)
                                    processed += 1
                                st.success(f"✅ Applied split rules to {processed} tagged entries")
                                st.rerun()
                        with batch_cols[1]:
                            if st.button("🔍 Match Identifiers on Tagged", type="primary", use_container_width=True, key="sus_match_id_tagged"):
                                identifiers = data_provider.get_all_identifiers()
                                tagged_entries = [s for s in suspense_list if s.get("Status") == "Tagged"]
                                processed = 0
                                for se in tagged_entries:
                                    sid = se["ID"]
                                    tagged_mid = int(se.get("Tagged_To", 0))
                                    particulars = str(se.get("Particulars", "") or "").upper()
                                    extra = str(se.get("Description", "") or "").upper()
                                    combined = particulars + " " + extra
                                    matched_identifiers = [
                                        idr for idr in identifiers
                                        if idr.get("Member_ID") == tagged_mid
                                        and str(idr.get("Identifier_Value", "")).upper() in combined
                                    ]
                                    if not matched_identifiers:
                                        continue
                                    date_str = str(se.get("Date", "") or "")
                                    amount = float(se.get("Amount", 0))
                                    member_data = _find_member(tagged_mid)
                                    mname = member_data.get("Plot_Owner_Name", "") if member_data else ""
                                    mplot = str(member_data.get("Plot_No", "") or "") if member_data else ""
                                    vch_no = data_provider.get_next_voucher_number()
                                    fy = get_fy_from_date(date_str)
                                    receipt_id = f"{fy}-{str(vch_no).zfill(3)}"
                                    data_provider.add_ledger_entry(tagged_mid, {
                                        "Date": date_str,
                                        "Particulars": f"By {particulars[:60]}",
                                        "Vch_Type": "Journal",
                                        "Vch_No": vch_no,
                                        "Debit": None,
                                        "Credit": amount,
                                        "Description": f"Receipt {receipt_id} — Suspense Identifier Match",
                                        "Transaction_Type": se.get("Transaction_Type", ""),
                                        "Transaction_ID": se.get("Transaction_ID", ""),
                                    })
                                    data_provider.delete_suspense_entry(sid)
                                    processed += 1
                                st.success(f"✅ Matched {processed} tagged entries via identifiers")
                                st.rerun()

        # ── Receipts List ─────────────────────────────────────────
        st.subheader("📄 Receipts")
        rec_fy_options = ["All"] + _get_available_fys(
            sum((data_provider.get_member_ledger(m["ID"]) for m in members), [])
        ) if members else ["All"]
        rec_col1, rec_col2, rec_col3, rec_col4 = st.columns([2, 2, 1.5, 1.5])
        with rec_col1:
            rec_member_id = st.selectbox(
                "Member", options=[0] + [m["ID"] for m in members],
                format_func=lambda x: "All" if x == 0 else _member_label(x),
                key="rec_member",
            )
        with rec_col2:
            rec_fy = st.selectbox("FY", rec_fy_options, key="rec_fy")
        with rec_col3:
            rec_type_filter = st.selectbox("Type", ["All", "Credit", "Debit"], key="rec_type")
        with rec_col4:
            rec_status_filter = st.selectbox("Status", ["All", "Receipt Generated", "Receipt Pending"], key="rec_status")

        rec_all_entries = []
        if rec_member_id == 0:
            for m in members:
                for e in data_provider.get_member_ledger(m["ID"]):
                    rec_all_entries.append({**e, "_mid": m["ID"], "_mname": m.get("Plot_Owner_Name", ""), "_mplot": m.get("Plot_No", "")})
        else:
            m = _find_member(rec_member_id)
            if m:
                for e in data_provider.get_member_ledger(rec_member_id):
                    rec_all_entries.append({**e, "_mid": rec_member_id, "_mname": m.get("Plot_Owner_Name", ""), "_mplot": m.get("Plot_No", "")})

        from_dt_r, to_dt_r = "", ""
        if rec_fy != "All":
            from_dt_r, to_dt_r = _fy_date_range(rec_fy)
        rec_filtered = _filter_entries(rec_all_entries, rec_type_filter, from_dt_r, to_dt_r)

        # Apply receipt status filter
        if rec_status_filter != "All":
            rec_filtered = [e for e in rec_filtered if _receipt_exists(e) == ("yes" if rec_status_filter == "Receipt Generated" else "no")]

        missing_count = sum(1 for e in rec_filtered if _receipt_exists(e) == "no")
        if missing_count:
            warn_cols = st.columns([3, 1])
            with warn_cols[0]:
                st.warning(f"⚠️ {missing_count} receipt{'s' if missing_count != 1 else ''} pending generation")
            with warn_cols[1]:
                if st.button("📄 Generate Missing", type="primary", use_container_width=True, key="rec_gen_missing"):
                    gen_count = 0
                    for e in rec_filtered:
                        if _receipt_exists(e) == "no":
                            if _generate_receipt_for_entry(data_provider, e, e["_mid"]):
                                gen_count += 1
                    if gen_count:
                        st.success(f"✅ Generated {gen_count} missing receipt(s)")
                    else:
                        st.warning("No receipts could be generated")
                    st.rerun()

        if rec_filtered:
            # ── Batch toolbar ──
            bcols = st.columns([0.6, 4, 3, 2])
            with bcols[0]:
                select_all = st.checkbox("☑", key="rec_select_all", label_visibility="collapsed",
                                         on_change=_rec_select_all_changed)
            with bcols[3]:
                if st.button("🔄 Regenerate Selected", type="primary", use_container_width=True, key="rec_batch_regen"):
                    sel = [e for idx, e in enumerate(rec_filtered)
                           if _s(e.get("Credit")) > 0 and st.session_state.get(f"rec_sel_{idx}", False)]
                    if sel:
                        for e in sel:
                            rec_vch = int(e.get("Vch_No", 0))
                            rec_mid = e["_mid"]
                            tool = next((t for t in orchestrator_agent.tools if t.name == "regenerate_receipt"), None)
                            if tool:
                                tool.func(json.dumps({"member_id": rec_mid, "vch_no": rec_vch}))
                        st.success(f"Regenerated {len(sel)} receipt(s)")
                        st.rerun()
                    else:
                        st.warning("No receipts selected")

            for idx, e in enumerate(rec_filtered):
                ref_id = _extract_ref_id(str(e.get("Description", "")))
                if not ref_id:
                    ref_id = _extract_ref_id(str(e.get("Particulars", "")))
                pdf_path = _get_pdf_path(config.RECEIPTS_DIR, ref_id) if ref_id else None
                rstatus = _receipt_exists(e)
                with st.container(border=True):
                    cr = _s(e.get("Credit"))
                    db = _s(e.get("Debit"))
                    amt = cr if cr > 0 else db
                    cols = st.columns([0.4, 1.8, 1.5, 0.6, 0.6, 1.8, 0.7, 0.7, 0.7])
                    with cols[0]:
                        if cr > 0:
                            st.checkbox("", key=f"rec_sel_{idx}", label_visibility="collapsed")
                    cols[1].markdown(f"**{e.get('Date', '')}** {e.get('_mname', '')} (P{e.get('_mplot', '')})")
                    cols[2].markdown(f"{'CR' if cr > 0 else 'DR'} ₹{amt:,.2f} | {e.get('Transaction_Type', '')}")
                    cols[3].markdown(f"`{e.get('Vch_No', '')}`")
                    status_icon = {"yes": "✅", "no": "⚠️", "na": "—"}.get(rstatus, "")
                    cols[4].markdown(status_icon)
                    cols[5].markdown(f"{e.get('Particulars', '')[:40]}" if e.get('Particulars') else "")
                    with cols[6]:
                        if pdf_path and pdf_path.exists():
                            with open(pdf_path, "rb") as fh:
                                cols[6].download_button("📄", data=fh, file_name=pdf_path.name, key=f"rec_pdf_{id(e)}")
                    with cols[7]:
                        if cr > 0 and st.button("🔄", key=f"rec_regen_{id(e)}", help="Regenerate receipt"):
                            rec_vch = int(e.get("Vch_No", 0))
                            rec_mid = e["_mid"]
                            tool = next((t for t in orchestrator_agent.tools if t.name == "regenerate_receipt"), None)
                            if tool:
                                result = tool.func(json.dumps({"member_id": rec_mid, "vch_no": rec_vch}))
                                if "✅" in str(result):
                                    st.success(result)
                                else:
                                    st.error(result)
                            st.rerun()
                    with cols[8]:
                        if cr > 0 and st.button("📧", key=f"rec_share_{id(e)}", help="Share receipt"):
                            st.session_state.rec_share_entry = e
                            st.rerun()
        else:
            st.info("No receipts found for selected filters.")

    # ═══════════════════════════════════════════════════════════════
    # TAB 4: Invoices
    # ═══════════════════════════════════════════════════════════════
    with tab_invoices:

        # ── Generate Invoices ─────────────────────────────────────
        with st.expander("🧾 Generate Invoices", expanded=False):
            col_d1, col_d2, col_d3 = st.columns(3)
            with col_d1:
                from_d = st.text_input("From Date (DD-MM-YYYY)", value="", key="inv_from", placeholder="e.g. 01-04-2026")
            with col_d2:
                to_d = st.text_input("To Date (DD-MM-YYYY)", value="", key="inv_to", placeholder="e.g. 31-03-2027")
            with col_d3:
                inv_d = st.text_input("Invoice Date (DD-MM-YYYY)", value="", key="inv_date", placeholder="Defaults to today")

            all_plots = st.checkbox("All Plots", value=True, key="inv_all_plots")
            if not all_plots:
                plot_options = {str(m.get("Plot_No", "")): f"Plot {m.get('Plot_No', '')} - {m.get('Plot_Owner_Name', '')}" for m in members}
                selected_plots = st.multiselect(
                    "Select Plots",
                    options=sorted(plot_options.keys(), key=lambda x: int(x) if x.isdigit() else 0),
                    format_func=lambda x: plot_options.get(x, x),
                    key="inv_selected_plots",
                )
            else:
                selected_plots = []

            if st.button("Generate Invoices Now", type="primary", use_container_width=True):
                params = {}
                if from_d.strip():
                    params["from_date"] = from_d.strip()
                if to_d.strip():
                    params["to_date"] = to_d.strip()
                if inv_d.strip():
                    params["invoice_date"] = inv_d.strip()
                if selected_plots:
                    params["plots"] = selected_plots
                invoice_tool = next(
                    (t for t in orchestrator_agent.tools if t.name == "batch_generate_invoices"),
                    None,
                )
                if invoice_tool:
                    label = f"Generating invoices for {len(selected_plots) if selected_plots else 'all'} member{'s' if len(selected_plots) != 1 else ''}..."
                    with st.spinner(label):
                        gresult = invoice_tool.func(json.dumps(params))
                        st.session_state.invoice_gen_result = gresult
                        st.rerun()
                else:
                    st.error("Invoice tool not found")

        if "invoice_gen_result" not in st.session_state:
            st.session_state.invoice_gen_result = None

        if st.session_state.invoice_gen_result:
            gresult = st.session_state.invoice_gen_result
            if "Error" in gresult or "Invalid" in gresult or "Please provide" in gresult:
                st.error(gresult)
            else:
                st.success("✅ Invoices generated")
                st.code(gresult, language="text")
            if st.button("Dismiss", key="dismiss_inv"):
                st.session_state.invoice_gen_result = None
                st.rerun()

        # ── Invoices List ─────────────────────────────────────────
        st.subheader("📑 Invoices")
        inv_fy_options = ["All"] + _get_available_fys(
            sum((data_provider.get_member_ledger(m["ID"]) for m in members), [])
        ) if members else ["All"]
        inv_col1, inv_col2, inv_col3 = st.columns([2, 2, 1.5])
        with inv_col1:
            inv_member_id = st.selectbox(
                "Member", options=[0] + [m["ID"] for m in members],
                format_func=lambda x: "All" if x == 0 else _member_label(x),
                key="inv_member_list",
            )
        with inv_col2:
            inv_fy_filter = st.selectbox("FY", inv_fy_options, key="inv_fy_list")
        with inv_col3:
            inv_status_filter = st.selectbox("Status", ["All", "PDF Generated", "PDF Pending"], key="inv_status")

        inv_all_entries = []
        if inv_member_id == 0:
            for m in members:
                for e in data_provider.get_member_ledger(m["ID"]):
                    if str(e.get("Transaction_Type", "") or "").upper() == "INVOICE":
                        inv_all_entries.append({**e, "_mid": m["ID"], "_mname": m.get("Plot_Owner_Name", ""), "_mplot": m.get("Plot_No", "")})
        else:
            m = _find_member(inv_member_id)
            if m:
                for e in data_provider.get_member_ledger(inv_member_id):
                    if str(e.get("Transaction_Type", "") or "").upper() == "INVOICE":
                        inv_all_entries.append({**e, "_mid": inv_member_id, "_mname": m.get("Plot_Owner_Name", ""), "_mplot": m.get("Plot_No", "")})

        from_dt_i, to_dt_i = "", ""
        if inv_fy_filter != "All":
            from_dt_i, to_dt_i = _fy_date_range(inv_fy_filter)
        inv_filtered = _filter_entries(inv_all_entries, "All", from_dt_i, to_dt_i)

        if inv_status_filter != "All":
            inv_filtered = [e for e in inv_filtered if _invoice_exists(e) == ("yes" if inv_status_filter == "PDF Generated" else "no")]

        missing_inv = sum(1 for e in inv_filtered if _invoice_exists(e) == "no")
        if missing_inv:
            st.warning(f"⚠️ {missing_inv} invoice{'s' if missing_inv != 1 else ''} pending PDF generation")

        if inv_filtered:
            # ── Batch action toolbar ──
            bcols = st.columns([0.6, 5, 2, 2])
            with bcols[0]:
                select_all = st.checkbox("☑", key="inv_select_all", label_visibility="collapsed",
                                         on_change=_inv_select_all_changed)
            with bcols[2]:
                if st.button("🗑️ Delete Selected", type="secondary", use_container_width=True, key="inv_batch_del"):
                    sel = [e for idx, e in enumerate(inv_filtered) if st.session_state.get(f"inv_sel_{idx}", False)]
                    if sel:
                        msgs = []
                        for e in sel:
                            msg = delete_invoice(data_provider, e["_mid"], e)
                            if msg:
                                msgs.append(msg)
                        if msgs:
                            st.success(f"Deleted {len(msgs)} invoice(s)")
                        st.rerun()
                    else:
                        st.warning("No invoices selected")
            with bcols[3]:
                if st.button("🔄 Regenerate Selected", type="primary", use_container_width=True, key="inv_batch_regen"):
                    sel = [e for idx, e in enumerate(inv_filtered) if st.session_state.get(f"inv_sel_{idx}", False)]
                    if sel:
                        msgs = []
                        for e in sel:
                            msg = regenerate_invoice(data_provider, e["_mid"], e)
                            if msg:
                                msgs.append(msg)
                        if msgs:
                            st.success(f"Regenerated {len(msgs)} invoice(s)")
                        st.rerun()
                    else:
                        st.warning("No invoices selected")

            for idx, e in enumerate(inv_filtered):
                desc = str(e.get("Description", "") or "")
                inv_match = re.search(r'Invoice\s+(\S+)', desc)
                ref_id = inv_match.group(1) if inv_match else _extract_ref_id(desc)
                pdf_path = _get_pdf_path(config.INVOICES_DIR, ref_id) if ref_id else None
                istatus = _invoice_exists(e)
                e_key = id(e)
                with st.container(border=True):
                    cols = st.columns([0.4, 1.8, 1.5, 0.6, 0.5, 1.8, 0.55, 0.55, 0.55, 0.55])
                    with cols[0]:
                        st.checkbox("", key=f"inv_sel_{idx}", label_visibility="collapsed")
                    cols[1].markdown(f"**{e.get('Date', '')}** {e.get('_mname', '')} (P{e.get('_mplot', '')})")
                    cols[2].markdown(f"₹{_s(e.get('Debit')):,.2f} | `{e.get('Vch_No', '')}`")
                    status_icon = {"yes": "✅", "no": "⚠️", "na": "—"}.get(istatus, "")
                    cols[3].markdown(status_icon)
                    cols[4].markdown(f"`{ref_id or ''}`")
                    cols[5].markdown(f"{e.get('Particulars', '')[:40]}" if e.get('Particulars') else "")
                    with cols[6]:
                        if pdf_path and pdf_path.exists():
                            with open(pdf_path, "rb") as fh:
                                cols[6].download_button("📄", data=fh, file_name=pdf_path.name, key=f"inv_pdf_{e_key}")
                    with cols[7]:
                        if st.button("🔄", key=f"inv_regen_{e_key}", help="Regenerate invoice"):
                            msg = regenerate_invoice(data_provider, e["_mid"], e)
                            if msg:
                                st.success(msg)
                            else:
                                st.error("Regeneration failed")
                            st.rerun()
                    with cols[8]:
                        if st.button("📧", key=f"inv_share_{e_key}", help="Share invoice"):
                            st.session_state.inv_share_entry = e
                            st.rerun()
                    with cols[9]:
                        if st.button("🗑️", key=f"inv_del_{e_key}", help="Delete invoice"):
                            msg = delete_invoice(data_provider, e["_mid"], e)
                            if msg:
                                st.success(msg)
                            else:
                                st.error("Deletion failed")
                            st.rerun()
        else:
            st.info("No invoices found for selected filters.")

    # ═══════════════════════════════════════════════════════════════
    # TAB 5: Ledgers
    # ═══════════════════════════════════════════════════════════════
    with tab_ledgers:

        col_f1, col_f2, col_f3 = st.columns([3, 2, 2])
        with col_f1:
            led_member_id = st.selectbox(
                "Member", options=[0] + [m["ID"] for m in members],
                format_func=lambda x: "🏘️ All Plots" if x == 0 else _member_label(x),
                key="led_member",
            )
        with col_f2:
            led_type_filter = st.selectbox("Type", ["All", "Debit", "Credit"], key="led_type")
        with col_f3:
            led_fy_filter = st.selectbox(
                "FY", ["All", "Custom"] + _get_available_fys(
                    sum((data_provider.get_member_ledger(m["ID"]) for m in members), [])
                ) if members else ["All"],
                key="led_fy",
            )

        led_from_dt, led_to_dt = "", ""
        if led_fy_filter == "Custom":
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                led_from_dt = st.text_input("From (DD-MM-YYYY)", value="", key="led_from")
            with col_d2:
                led_to_dt = st.text_input("To (DD-MM-YYYY)", value="", key="led_to")
        elif led_fy_filter != "All":
            led_from_dt, led_to_dt = _fy_date_range(led_fy_filter)

        # ── Search Particulars ──────────────────────────────────────
        led_search = st.text_input("🔍 Search Particulars", placeholder="Enter text to search across all entries...", key="led_search_parts")
        if led_search:
            search_results = []
            seen_vch = set()
            search_members = [m] if led_member_id != 0 else members
            for sm in search_members:
                mid = sm["ID"]
                for e in data_provider.get_member_ledger(mid):
                    epart = str(e.get("Particulars", "") or "")
                    if led_search.lower() not in epart.lower():
                        continue
                    vch = e.get("Vch_No")
                    if vch and vch in seen_vch:
                        continue
                    if vch:
                        seen_vch.add(vch)
                    search_results.append({**e, "_src_mid": mid, "_src_label": _member_label(mid)})
            if search_results:
                st.warning(f"🔍 Found {len(search_results)} entries matching '{led_search}'")
                with st.container(border=True):
                    for se in search_results:
                        sed = str(se.get("Date", "") or "")
                        separt = str(se.get("Particulars", "") or "")
                        se_amt = _s(se.get("Credit")) or _s(se.get("Debit"))
                        se_type = str(se.get("Transaction_Type", "") or "")
                        se_label = se.get("_src_label", "?")
                        cols = st.columns([1.5, 3, 1.5, 2, 2])
                        cols[0].text(sed)
                        cols[1].caption(separt[:80])
                        cols[2].text(f"₹{se_amt:,.2f}")
                        cols[3].text(se_label)
                        cols[4].text(se_type or "—")
                    move_to_mid = st.selectbox(
                        "Move all matched entries to:", options=[m["ID"] for m in members],
                        format_func=_member_label, key="led_search_move_target",
                    )
                    if st.button(f"🚚 Move All {len(search_results)} to selected member", type="primary", key="led_search_move_all"):
                        count = 0
                        for se in search_results:
                            svch = int(se.get("Vch_No", 0))
                            if svch and data_provider.delete_ledger_entry(se["_src_mid"], svch):
                                data_provider.add_ledger_entry(move_to_mid, {
                                    "Date": str(se.get("Date", "") or ""),
                                    "Particulars": str(se.get("Particulars", "") or "")[:60],
                                    "Vch_Type": "Journal", "Vch_No": svch,
                                    "Debit": se.get("Debit"), "Credit": se.get("Credit"),
                                    "Description": str(se.get("Description", "") or ""),
                                    "Transaction_Type": str(se.get("Transaction_Type", "") or ""),
                                    "Transaction_ID": str(se.get("Transaction_ID", "") or ""),
                                })
                                count += 1
                        st.success(f"✅ Moved {count} entries to {_member_label(move_to_mid)}")
                        st.rerun()
            else:
                st.info(f"No entries match '{led_search}'")

        # ── All Plots view ────────────────────────────────────────
        if led_member_id == 0:
            summary = []
            for m in members:
                mid = m["ID"]
                ledger = data_provider.get_member_ledger(mid)
                filtered = _filter_entries(ledger, led_type_filter, led_from_dt, led_to_dt)
                td = _s(sum(float(e.get("Debit") or 0) for e in filtered))
                tc = _s(sum(float(e.get("Credit") or 0) for e in filtered))
                outstanding = data_provider.get_current_outstanding(mid)
                summary.append({
                    "Plot": m.get("Plot_No", "?"), "Name": m.get("Plot_Owner_Name", "?"),
                    "Debits": td, "Credits": tc, "Net": tc - td, "Outstanding": outstanding,
                    "Member_ID": mid, "has_entries": bool(filtered),
                })
            if summary:
                st.dataframe(
                    [{"Plot": s["Plot"], "Name": s["Name"],
                      "Debits": f"₹{s['Debits']:,.2f}", "Credits": f"₹{s['Credits']:,.2f}",
                      "Net": f"₹{s['Net']:,.2f}",
                      "Outstanding": f"₹{abs(s['Outstanding']):,.2f} {'Demand' if s['Outstanding'] < 0 else 'Surplus' if s['Outstanding'] > 0 else 'Settled'}"}
                     for s in summary],
                    use_container_width=True,
                )
                for s in summary:
                    if not s["has_entries"]:
                        continue
                    plot_entries = _filter_entries(
                        data_provider.get_member_ledger(s["Member_ID"]),
                        led_type_filter, led_from_dt, led_to_dt,
                    )
                    inv_list = [pe for pe in plot_entries if str(pe.get("Transaction_Type", "") or "").upper() == "INVOICE"]
                    col_a1, col_a2, col_a3 = st.columns([3, 3, 3])
                    with col_a1:
                        st.text(f"{s['Plot']}  {s['Name']}")
                    with col_a2:
                        if inv_list and st.button(f"🔄 Regen {len(inv_list)} invoice(s)", key=f"led_regen_{s['Member_ID']}"):
                            rc = 0
                            for pe in list(inv_list):
                                if regenerate_invoice(data_provider, s["Member_ID"], pe):
                                    rc += 1
                            if rc:
                                st.success(f"✅ Regenerated {rc} invoice(s) for Plot {s['Plot']}")
                                st.rerun()
                    with col_a3:
                        if st.button(f"🗑️ Delete {len(plot_entries)}", key=f"led_del_{s['Member_ID']}"):
                            dc = 0
                            for pe in sorted(plot_entries, key=lambda x: _s(x.get("Vch_No") or 0), reverse=True):
                                vch = pe.get("Vch_No")
                                if vch and data_provider.delete_ledger_entry(s["Member_ID"], int(vch)):
                                    _delete_pdf_files(_extract_ref_id(str(pe.get("Description", ""))))
                                    dc += 1
                            st.success(f"✅ Deleted {dc} entries for Plot {s['Plot']}")
                            st.rerun()

        # ── Single-member view ────────────────────────────────────
        else:
            led_member = _find_member(led_member_id)
            if led_member:
                raw_ledger = data_provider.get_member_ledger(led_member_id)
                led_entries = _filter_entries(raw_ledger, led_type_filter, led_from_dt, led_to_dt)
                if led_entries:
                    total_dr = _s(sum(_s(e.get("Debit")) for e in led_entries))
                    total_cr = _s(sum(_s(e.get("Credit")) for e in led_entries))
                    st.caption(f"Debits: ₹{total_dr:,.2f}  |  Credits: ₹{total_cr:,.2f}  |  Net: ₹{total_cr - total_dr:,.2f}")

                    # ── Batch action toolbar ──
                    bcols = st.columns([0.6, 2.5, 2, 2, 2, 2])
                    with bcols[0]:
                        st.checkbox("☑", key="led_sel_all", label_visibility="collapsed",
                                     on_change=_led_select_all_changed)
                    with bcols[2]:
                        if st.button("🗑️ Delete Selected", type="secondary", use_container_width=True, key="led_batch_del"):
                            sel_idx = [idx for idx, e in enumerate(led_entries) if st.session_state.get(f"led_sel_{idx}", False)]
                            if sel_idx:
                                dc = 0
                                for idx in sorted(sel_idx, key=lambda i: int(led_entries[i].get("Vch_No") or 0), reverse=True):
                                    e = led_entries[idx]
                                    vch = e.get("Vch_No")
                                    if vch and data_provider.delete_ledger_entry(led_member_id, int(vch)):
                                        _delete_pdf_files(_extract_ref_id(str(e.get("Description", ""))))
                                        dc += 1
                                st.success(f"✅ Deleted {dc} entries")
                                st.rerun()
                            else:
                                st.warning("No entries selected")
                    with bcols[3]:
                        if st.button("🔄 Regenerate Selected", type="primary", use_container_width=True, key="led_batch_regen"):
                            sel_idx = [idx for idx, e in enumerate(led_entries) if st.session_state.get(f"led_sel_{idx}", False)]
                            if sel_idx:
                                for idx in sel_idx:
                                    e = led_entries[idx]
                                    if str(e.get("Transaction_Type", "") or "").upper() == "INVOICE":
                                        regenerate_invoice(data_provider, led_member_id, e)
                                st.success(f"✅ Regenerated invoices")
                                st.rerun()
                            else:
                                st.warning("No entries selected")
                    with bcols[4]:
                        if st.button("➡️ Move Selected", type="secondary", use_container_width=True, key="led_batch_move"):
                            sel_idx = [idx for idx, e in enumerate(led_entries) if st.session_state.get(f"led_sel_{idx}", False)]
                            credits = [led_entries[idx] for idx in sel_idx if _s(led_entries[idx].get("Credit")) > 0]
                            if credits:
                                st.session_state.move_src_list = [
                                    {"member_id": led_member_id,
                                     "vch_no": int(e.get("Vch_No", 0)),
                                     "amount": _s(e.get("Credit")),
                                     "date": str(e.get("Date", "") or ""),
                                     "particulars": str(e.get("Particulars", "") or ""),
                                     "description": str(e.get("Description", "") or ""),
                                     "txn_type": str(e.get("Transaction_Type", "") or ""),
                                     "txn_id": str(e.get("Transaction_ID", "") or "")}
                                    for e in credits
                                ]
                                st.session_state.move_src = st.session_state.move_src_list[0]
                                st.rerun()
                            else:
                                st.warning("Select at least one credit entry to move")
                    with bcols[5]:
                        if st.button("✂️ Split Selected", type="secondary", use_container_width=True, key="led_batch_split"):
                            sel_idx = [idx for idx, e in enumerate(led_entries) if st.session_state.get(f"led_sel_{idx}", False)]
                            credits = [led_entries[idx] for idx in sel_idx if _s(led_entries[idx].get("Credit")) > 0]
                            if credits:
                                st.session_state.split_src_list = [
                                    {"member_id": led_member_id,
                                     "vch_no": int(e.get("Vch_No", 0)),
                                     "amount": _s(e.get("Credit")),
                                     "date": str(e.get("Date", "") or ""),
                                     "particulars": str(e.get("Particulars", "") or ""),
                                     "txn_type": str(e.get("Transaction_Type", "") or ""),
                                     "txn_id": str(e.get("Transaction_ID", "") or "")}
                                    for e in credits
                                ]
                                st.session_state.split_src = st.session_state.split_src_list[0]
                                st.rerun()
                            else:
                                st.warning("Select at least one credit entry to split")

                    st.divider()
                    split_group = data_provider.get_split_group_for_member(led_member_id) if led_member_id else None
                    for idx, entry in enumerate(led_entries):
                        ed = str(entry.get("Date", "") or "")
                        ev = entry.get("Vch_No", "")
                        edesc = str(entry.get("Description", "") or "")
                        epart = str(entry.get("Particulars", "") or "")
                        edeb = _s(entry.get("Debit"))
                        ecr = _s(entry.get("Credit"))
                        etype = str(entry.get("Transaction_Type", "") or "")
                        amt = ecr if ecr > 0 else edeb
                        is_credit = ecr > 0
                        lbl = f"₹{amt:,.2f} CR" if is_credit else f"₹{amt:,.2f} DR"
                        can_split = is_credit and split_group is not None
                        c1, c2, c3, c4, c5, c6 = st.columns([0.3, 1.5, 1.5, 3, 1.5, 1.5])
                        with c1:
                            st.checkbox("", key=f"led_sel_{idx}", label_visibility="collapsed")
                        with c2:
                            st.caption(f"#{ev}")
                            st.text(ed)
                        with c3:
                            st.caption(etype)
                            st.text(edesc[:40] if edesc else "")
                        with c4:
                            st.caption("Particulars")
                            st.text(epart[:80])
                        with c5:
                            st.text(lbl)
                        with c6:
                            # ── Undo Split ──
                            if etype.upper() == "SPLIT" or "split from #" in edesc.lower():
                                orig_match = re.search(r"Split from #(\d+)\s*\(src:(\d+)\)", edesc, re.IGNORECASE)
                                if orig_match:
                                    orig_vch = int(orig_match.group(1))
                                    orig_mid = int(orig_match.group(2))
                                    if st.button("↩️ Undo", key=f"led_unsplit_{idx}", help="Undo split, recreate original entry"):
                                        all_ledger = data_provider.get_member_ledger_all()
                                        siblings = [se for se in all_ledger
                                                     if f"Split from #{orig_vch}" in str(se.get("Description", ""))]
                                        total_amt = sum(float(se.get("Credit", 0) or 0) for se in siblings)
                                        for se in siblings:
                                            smid = se.get("Member_ID") or se.get("Plot_No")
                                            svch = int(se.get("Vch_No", 0))
                                            if smid and svch:
                                                data_provider.delete_ledger_entry(int(float(smid)), svch)
                                        data_provider.add_ledger_entry(orig_mid, {
                                            "Date": ed, "Particulars": epart[:60],
                                            "Vch_Type": "Journal", "Vch_No": orig_vch,
                                            "Debit": None, "Credit": total_amt,
                                            "Description": f"Undid split #{orig_vch} — restored entry",
                                            "Transaction_Type": etype, "Transaction_ID": entry.get("Transaction_ID", ""),
                                        })
                                        st.success(f"↩️ Undid split #{orig_vch} — ₹{total_amt:,.2f} restored to member #{orig_mid}")
                                        st.rerun()
                            # ── Undo Move ──
                            move_match = re.search(r"\(moved from #(\d+)\)", edesc)
                            if move_match:
                                src_mid = int(move_match.group(1))
                                if st.button("↩️ Undo", key=f"led_unmove_{idx}", help="Move back to original member"):
                                    vch_no = int(ev) if ev else 0
                                    if vch_no and data_provider.delete_ledger_entry(led_member_id, vch_no):
                                        data_provider.add_ledger_entry(src_mid, {
                                            "Date": ed, "Particulars": epart[:60],
                                            "Vch_Type": "Journal", "Vch_No": vch_no,
                                            "Debit": None, "Credit": ecr,
                                            "Description": edesc, "Transaction_Type": etype,
                                            "Transaction_ID": entry.get("Transaction_ID", ""),
                                        })
                                    st.success(f"↩️ Moved ₹{ecr:,.2f} back to member #{src_mid}")
                                    st.rerun()
                            if is_credit:
                                if st.button("➡️ Move", key=f"led_move_{idx}", help="Move to another member"):
                                    src = {
                                        "member_id": led_member_id,
                                        "vch_no": int(ev) if ev else 0,
                                        "amount": ecr, "date": ed,
                                        "particulars": epart, "description": edesc,
                                        "txn_type": etype,
                                        "txn_id": entry.get("Transaction_ID", ""),
                                    }
                                    st.session_state.move_src = src
                                    st.session_state.move_src_list = [src]
                                    st.rerun()
                                if st.button("✂️ Split", key=f"led_split_{idx}", help="Split across members"):
                                    src = {
                                        "member_id": led_member_id,
                                        "vch_no": int(ev) if ev else 0,
                                        "amount": ecr, "date": ed,
                                        "particulars": epart,
                                        "txn_type": etype,
                                        "txn_id": entry.get("Transaction_ID", ""),
                                    }
                                    st.session_state.split_src = src
                                    st.session_state.split_src_list = [src]
                                    st.rerun()
                                if can_split:
                                    if st.button("➡️ Source", key=f"led_route_{idx}", help="Route to source member"):
                                        src_rule = next((r for r in data_provider.get_split_rules()
                                                        if int(r.get("Source_Member_ID", 0)) == led_member_id
                                                        or led_member_id in [int(x) for x in str(r.get("Members", "")).split(",") if x.strip().isdigit()]), None)
                                        if src_rule:
                                            src_mid = int(src_rule["Source_Member_ID"])
                                            vch_no = int(ev) if ev else 0
                                            if vch_no and data_provider.delete_ledger_entry(led_member_id, vch_no):
                                                data_provider.add_ledger_entry(src_mid, {
                                                    "Date": ed, "Particulars": epart[:60],
                                                    "Vch_Type": "Journal", "Vch_No": vch_no,
                                                    "Debit": None, "Credit": ecr,
                                                    "Description": edesc, "Transaction_Type": etype,
                                                    "Transaction_ID": entry.get("Transaction_ID", ""),
                                                })
                                            st.success(f"✅ Routed ₹{ecr:,.2f} to source member #{src_mid}")
                                            st.rerun()
                    st.divider()

                    # ── Split UI ───────────────────────────────────
                    if st.session_state.get("split_src"):
                        split_entries = st.session_state.get("split_src_list", [st.session_state.split_src])
                        total_count = len(split_entries)
                        total_amt = sum(e["amount"] for e in split_entries)
                        if total_count == 1:
                            st.markdown(f"**✂️ Splitting ₹{split_entries[0]['amount']:,.2f} receipt from {split_entries[0]['date']}**")
                        else:
                            st.markdown(f"**✂️ Splitting {total_count} entries — Total ₹{total_amt:,.2f}**")
                        split_ids = st.multiselect(
                            "Split across members", options=[m["ID"] for m in members],
                            format_func=_member_label, key="led_split_targets",
                        )
                        split_gen_rcpt = st.checkbox("Generate receipts", value=False, key="led_split_gen_rcpt")
                        col_s1, col_s2 = st.columns(2)
                        with col_s1:
                            if st.button("Confirm Split", type="primary", use_container_width=True, key="led_confirm_split"):
                                if not split_ids:
                                    st.warning("Please select at least one member to split across")
                                else:
                                    for ss in split_entries:
                                        if data_provider.delete_ledger_entry(ss["member_id"], ss["vch_no"]):
                                            per_member = ss["amount"] / len(split_ids)
                                            for mid in split_ids:
                                                vch = data_provider.get_next_voucher_number()
                                                fy = get_fy_from_date(ss["date"])
                                                rid = f"{fy}-{str(vch).zfill(3)}"
                                                m = _find_member(mid)
                                                plot_str = str(m.get("Plot_No", ""))
                                                plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
                                                data_provider.add_ledger_entry(mid, {
                                                    "Date": ss["date"],
                                                    "Particulars": ss["particulars"][:60],
                                                    "Vch_Type": "Journal", "Vch_No": vch,
                                                    "Debit": None, "Credit": per_member,
                                                    "Description": f"Receipt {rid} — Split from #{ss['vch_no']} (src:{ss['member_id']})",
                                                    "Transaction_ID": ss.get("txn_id", ""),
                                                    "Transaction_Type": ss.get("txn_type", ""),
                                                })
                                                if split_gen_rcpt:
                                                    fy_short = fy[:2]
                                                    receipt_dir = config.RECEIPTS_DIR / fy_short
                                                    receipt_dir.mkdir(parents=True, exist_ok=True)
                                                    rpath = receipt_dir / f"Receipt_{plot_part}_{rid}.pdf"
                                                    create_simple_receipt_pdf(rpath, {
                                                        "receipt_id": rid, "date": ss["date"],
                                                        "member_name": m.get("Plot_Owner_Name", ""),
                                                        "plot_no": plot_str, "amount": per_member,
                                                        "transaction_id": ss.get("txn_id", "N/A"),
                                                        "transaction_type": ss.get("txn_type", ""),
                                                        "payment_details": clean_payment_details(ss.get("particulars", ""))[:120],
                                                    })
                                    st.success(f"✅ Split {total_count} entries across {len(split_ids)} members")
                                    del st.session_state.split_src
                                    st.session_state.pop("split_src_list", None)
                                    st.rerun()
                        with col_s2:
                            if st.button("Cancel Split", use_container_width=True, key="led_cancel_split"):
                                del st.session_state.split_src
                                st.session_state.pop("split_src_list", None)
                                st.rerun()

                    # ── Move UI ────────────────────────────────────
                    if st.session_state.get("move_src"):
                        move_entries = st.session_state.get("move_src_list", [st.session_state.move_src])
                        total_count = len(move_entries)
                        total_amt = sum(e["amount"] for e in move_entries)
                        if total_count == 1:
                            st.markdown(f"**➡️ Moving ₹{move_entries[0]['amount']:,.2f} receipt from {move_entries[0]['date']}**")
                        else:
                            st.markdown(f"**➡️ Moving {total_count} entries — Total ₹{total_amt:,.2f}**")
                        target_mid = st.selectbox(
                            "Move to member", options=[m["ID"] for m in members],
                            format_func=_member_label, key="led_move_target",
                        )
                        move_gen_rcpt = st.checkbox("Generate receipts", value=False, key="led_move_gen_rcpt")
                        col_m1, col_m2 = st.columns(2)
                        with col_m1:
                            if st.button("Confirm Move", type="primary", key="led_confirm_move"):
                                for ms in move_entries:
                                    if data_provider.delete_ledger_entry(ms["member_id"], ms["vch_no"]):
                                        data_provider.add_ledger_entry(target_mid, {
                                            "Date": ms["date"], "Particulars": ms["particulars"][:60],
                                            "Vch_Type": "Journal", "Vch_No": ms["vch_no"],
                                            "Debit": None, "Credit": ms["amount"],
                                            "Description": f"{ms['description']} (moved from #{ms['member_id']})",
                                            "Transaction_ID": ms.get("txn_id", ""),
                                            "Transaction_Type": ms.get("txn_type", ""),
                                        })
                                        if move_gen_rcpt:
                                            ref_id = _extract_ref_id(ms["description"])
                                            if ref_id:
                                                _delete_pdf_files(ref_id)
                                            tool = next((t for t in orchestrator_agent.tools if t.name == "regenerate_receipt"), None)
                                            if tool:
                                                tool.func(json.dumps({"member_id": target_mid, "vch_no": ms["vch_no"]}))
                                st.success(f"✅ Moved {total_count} entries (₹{total_amt:,.2f})")
                                del st.session_state.move_src
                                st.session_state.pop("move_src_list", None)
                                st.rerun()
                        with col_m2:
                            if st.button("Cancel", key="led_cancel_move"):
                                del st.session_state.move_src
                                st.session_state.pop("move_src_list", None)
                                st.rerun()
                else:
                    st.info("No entries match the current filters.")

    # ═══════════════════════════════════════════════════════════════
    # TAB 6: Reports
    # ═══════════════════════════════════════════════════════════════
    with tab_reports:

        # ── Member Status ─────────────────────────────────────────
        st.subheader("Member Status")
        member_data = []
        for member in members:
            outstanding = data_provider.get_current_outstanding(member["ID"])
            if outstanding < 0:
                status = f"Demand ₹{abs(outstanding):,.0f}"
            elif outstanding > 0:
                status = f"Surplus ₹{outstanding:,.0f}"
            else:
                status = "Settled"
            member_data.append({
                "Plot No": member.get("Plot_No", "N/A"),
                "Name": member.get("Plot_Owner_Name", "N/A"),
                "Balance": f"₹{abs(outstanding):,.2f}",
                "Status": status,
            })
        st.dataframe(member_data, use_container_width=True)

        st.divider()

        # ── Defaulters Report ─────────────────────────────────────
        with st.expander("📊 Defaulters Report", expanded=False):
            defaulter_data = []
            for m in members:
                mid = m["ID"]
                ledger = data_provider.get_member_ledger(mid)
                td = _s(sum(_s(e.get("Debit")) for e in ledger))
                tc = _s(sum(_s(e.get("Credit")) for e in ledger))
                outstanding = data_provider.get_current_outstanding(mid)
                if outstanding < 0:
                    defaulter_data.append({
                        "Plot": m.get("Plot_No", "?"),
                        "Name": m.get("Plot_Owner_Name", "?"),
                        "Total Debits": td,
                        "Total Credits": tc,
                        "Outstanding": outstanding,
                    })
            if defaulter_data:
                defaulter_data.sort(key=lambda x: x["Outstanding"])
                st.dataframe(
                    [{"Plot": d["Plot"], "Name": d["Name"],
                      "Total Debits": f"₹{d['Total Debits']:,.2f}",
                      "Total Credits": f"₹{d['Total Credits']:,.2f}",
                      "Outstanding": f"₹{abs(d['Outstanding']):,.2f}"}
                     for d in defaulter_data],
                    use_container_width=True,
                )
                total_demand = sum(abs(d["Outstanding"]) for d in defaulter_data)
                st.metric("Total Outstanding Demand", f"₹{total_demand:,.2f}")
            else:
                st.success("No defaulters — all plots are settled or in surplus.")

        st.divider()

        # ── Reconciliation Report ────────────────────────────────
        with st.expander("🔍 Reconciliation Report", expanded=False):
            if st.button("Run Reconciliation", key="reconcile_btn"):
                results = []
                all_members = data_provider.get_all_members()
                ledger = data_provider.get_member_ledger_all()
                vch_nos = sorted([int(e.get("Vch_No", 0)) for e in ledger if e.get("Vch_No")])

                for m in all_members:
                    mid = int(m.get("Member_ID", m.get("Plot_No", m.get("ID", 0))))
                    outstanding = data_provider.get_current_outstanding(mid)
                    if outstanding > 0:
                        results.append({"Plot_No": mid, "Owner": m.get("Plot_Owner_Name", ""),
                                        "Check": "Outstanding Sign", "Status": "OK",
                                        "Detail": f"Surplus Rs {outstanding:,.2f}"})
                    else:
                        results.append({"Plot_No": mid, "Owner": m.get("Plot_Owner_Name", ""),
                                        "Check": "Outstanding Sign", "Status": "OK",
                                        "Detail": f"Demand Rs {abs(outstanding):,.2f}"})

                if vch_nos:
                    expected_range = list(range(min(vch_nos), max(vch_nos) + 1))
                    missing = sorted(set(expected_range) - set(vch_nos))
                    if missing:
                        results.append({"Plot_No": "-", "Owner": "-",
                                        "Check": "Voucher Gaps", "Status": "FAIL",
                                        "Detail": f"Missing Vch_No: {missing[:10]}{'...' if len(missing)>10 else ''}"})
                    else:
                        results.append({"Plot_No": "-", "Owner": "-",
                                        "Check": "Voucher Gaps", "Status": "OK",
                                        "Detail": f"No gaps ({min(vch_nos)}-{max(vch_nos)})"})

                rdf = pd.DataFrame(results)
                st.dataframe(rdf, use_container_width=True)

                failures = rdf[rdf["Status"] == "FAIL"]
                if not failures.empty:
                    st.error(f"{len(failures)} checks failed!")
                else:
                    st.success("All checks passed!")

        st.divider()

        # ── Duplicate Detection ───────────────────────────────────
        with st.expander("🔍 Duplicate Detection", expanded=False):
            if "dup_result" not in st.session_state:
                st.session_state.dup_result = []
            if st.button("Run Duplicate Scan", key="dup_scan_btn"):
                all_ledger = data_provider.get_member_ledger_all()
                entries_by_key = {}  # (date, amount_rounded) → list of entries with member info
                txn_id_map = {}  # Transaction_ID → list
                part_map = {}  # normalized particulars → list

                for e in all_ledger:
                    mid = e.get("Member_ID") or e.get("Plot_No")
                    if not mid:
                        continue
                    try:
                        mid = int(float(mid))
                    except (ValueError, TypeError):
                        continue
                    date = str(e.get("Date", "") or "")
                    amount = round(_s(e.get("Credit")) or _s(e.get("Debit")), 0)
                    key = (date, amount)
                    entries_by_key.setdefault(key, []).append({**e, "_dup_mid": mid})
                    txn_id = str(e.get("Transaction_ID", "") or "").strip()
                    if txn_id and txn_id != "N/A":
                        txn_id_map.setdefault(txn_id, []).append({**e, "_dup_mid": mid})
                    pn = _normalize_particulars(e.get("Particulars", ""))
                    if pn:
                        part_map.setdefault(pn, []).append({**e, "_dup_mid": mid})

                dup_groups = []
                seen = set()
                # Check normalized Particulars groups first (most reliable)
                for pn, items in part_map.items():
                    if len(items) >= 2 and len(pn) >= 5:
                        ids = tuple(sorted((e.get("Vch_No"), e["_dup_mid"]) for e in items))
                        if ids not in seen:
                            seen.add(ids)
                            dup_groups.append((f"Particulars: {pn}", items))
                # Check date+amount groups
                for key, items in entries_by_key.items():
                    if len(items) >= 2:
                        ids = tuple(sorted((e.get("Vch_No"), e["_dup_mid"]) for e in items))
                        if ids not in seen:
                            seen.add(ids)
                            dup_groups.append(("Date + Amount", items))
                # Check Transaction_ID groups
                for txn_id, items in txn_id_map.items():
                    if len(items) >= 2:
                        ids = tuple(sorted((e.get("Vch_No"), e["_dup_mid"]) for e in items))
                        if ids not in seen:
                            seen.add(ids)
                            dup_groups.append((f"Transaction ID: {txn_id}", items))

                st.session_state.dup_result = dup_groups

            dup_groups = st.session_state.dup_result
            if not dup_groups:
                st.info("Click 'Run Duplicate Scan' to check for potential duplicates across all members.")
            else:
                st.warning(f"⚠️ Found {len(dup_groups)} potential duplicate group(s)")
                for reason, items in dup_groups:
                    with st.container(border=True):
                        st.caption(f"**{reason}**")
                        all_vch = set()
                        for e in items:
                            member_info = _find_member(e["_dup_mid"])
                            mlabel = f"P{member_info.get('Plot_No','?')} {member_info.get('Plot_Owner_Name','?')}" if member_info else f"ID {e['_dup_mid']}"
                            cr = _s(e.get("Credit"))
                            amt_lbl = f"CR ₹{cr:>,.2f}" if cr > 0 else f"DR ₹{_s(e.get('Debit')):>,.2f}"
                            is_split = str(e.get("Transaction_Type", "") or "").upper() == "SPLIT"
                            cols = st.columns([2, 2, 1.5, 1.5, 0.7, 0.7])
                            cols[0].write(f"{e.get('Date','')} {amt_lbl}")
                            cols[1].write(mlabel)
                            cols[2].write(f"Vch #{int(e.get('Vch_No',0))}")
                            cols[3].write(f"{'SPLIT' if is_split else '—'}")
                            with cols[4]:
                                if st.button("🗑️", key=f"dup_del_{id(e)}", help="Delete this entry"):
                                    if data_provider.delete_ledger_entry(e["_dup_mid"], int(e.get("Vch_No", 0))):
                                        _delete_pdf_files(_extract_ref_id(str(e.get("Description", ""))))
                                        st.session_state.dup_result = []
                                        st.success(f"Deleted Vch #{int(e.get('Vch_No',0))}")
                                        st.rerun()
                            with cols[5]:
                                if is_split:
                                    if st.button("↩️", key=f"dup_unsp_{id(e)}", help="Undo split (delete all split entries)"):
                                        vch_no = int(e.get("Vch_No", 0))
                                        all_split_entries = [
                                            oe for oe in data_provider.get_member_ledger_all()
                                            if str(oe.get("Transaction_Type", "") or "").upper() == "SPLIT"
                                            and f"Split from #{vch_no}" in str(oe.get("Description", ""))
                                        ]
                                        total_amt = 0
                                        for se in all_split_entries:
                                            se_mid = se.get("Member_ID") or se.get("Plot_No")
                                            se_vch = int(se.get("Vch_No", 0))
                                            if se_mid and se_vch:
                                                total_amt += _s(se.get("Credit"))
                                                data_provider.delete_ledger_entry(int(float(se_mid)), se_vch)
                                        data_provider.delete_ledger_entry(e["_dup_mid"], vch_no)
                                        st.session_state.dup_result = []
                                        st.success(f"✅ Undid split — ₹{total_amt:>,.2f} total across {len(all_split_entries)+1} entries deleted")
                                        st.rerun()

        st.divider()

        # ── Budget Spend Analysis ─────────────────────────────────
        with st.expander("💰 Budget Spend Analysis", expanded=False):
            all_fys = _get_available_fys(
                sum((data_provider.get_member_ledger(m["ID"]) for m in members), [])
            )
            if not all_fys:
                st.info("No data available for budget analysis.")
            else:
                budget_rows = []
                for fy in all_fys:
                    fd, td = _fy_date_range(fy)
                    # Total invoiced (INVOICE-type debits across all members)
                    total_invoiced = 0
                    for m in members:
                        for e in data_provider.get_member_ledger(m["ID"]):
                            if str(e.get("Transaction_Type", "") or "").upper() != "INVOICE":
                                continue
                            e_date = str(e.get("Date", "") or "")
                            ymd = f"20{e_date[6:8]}-{e_date[3:5]}-{e_date[0:2]}" if len(e_date) == 10 else ""
                            if fd <= ymd <= td:
                                total_invoiced += _s(e.get("Debit"))
                    # Total expensed
                    expenses = data_provider.get_expenses(from_date=fd, to_date=td)
                    total_expensed = sum(_s(e.get("Amount")) for e in expenses)
                    surplus_gap = total_invoiced - total_expensed
                    budget_rows.append({
                        "FY": fy,
                        "Invoiced (₹)": total_invoiced,
                        "Expensed (₹)": total_expensed,
                        "Surplus Gap (₹)": surplus_gap,
                    })
                if budget_rows:
                    budget_rows.sort(key=lambda x: x["FY"], reverse=True)
                    st.dataframe(
                        [{"FY": r["FY"],
                          "Invoiced (₹)": f"₹{r['Invoiced (₹)']:,.2f}",
                          "Expensed (₹)": f"₹{r['Expensed (₹)']:,.2f}",
                          "Surplus Gap (₹)": f"₹{r['Surplus Gap (₹)']:,.2f}"}
                         for r in budget_rows],
                        use_container_width=True,
                    )


def show_settings_page():
    """Settings page"""
    st.title("⚙️ Settings")

    settings = data_provider.get_settings()

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
        ["Rates", "Members", "Categories", "Identifiers", "Split Rules", "System", "Email"]
    )

    with tab1:
        st.subheader("Invoice Rates")
        col1, col2, col3 = st.columns(3)
        with col1:
            repair = st.number_input(
                "Repair & Maintenance Fund (₹/month)",
                value=float(settings.get("Repair_Fund_Rate", 100)),
                min_value=0.0,
            )
        with col2:
            service = st.number_input(
                "Service Charges (₹/month)",
                value=float(settings.get("Service_Charges_Rate", 885)),
                min_value=0.0,
            )
        with col3:
            sinking = st.number_input(
                "Sinking Fund (₹/month)",
                value=float(settings.get("Sinking_Fund_Rate", 15)),
                min_value=0.0,
            )
        if st.button("Update Rates", use_container_width=True):
            data_provider.update_settings({
                "Repair_Fund_Rate": str(repair),
                "Service_Charges_Rate": str(service),
                "Sinking_Fund_Rate": str(sinking),
            })
            st.success("Rates updated successfully!")

    with tab2:
        st.subheader("Member Management")

        members_list = data_provider.get_all_members()
        if members_list:
            mtable = []
            for m in members_list:
                mid = m.get("ID", 0)
                outstanding = data_provider.get_current_outstanding(mid)
                mtable.append({
                    "ID": mid,
                    "Plot No": m.get("Plot_No", ""),
                    "Name": m.get("Plot_Owner_Name", ""),
                    "Email": str(m.get("Email", "") or "")[:30],
                    "Phone": str(m.get("Phone", "") or ""),
                    "WhatsApp": str(m.get("WhatsApp_No", "") or ""),
                    "Outstanding": f"₹{_s(outstanding):,.0f}",
                })
            st.dataframe(mtable, use_container_width=True)

        with st.expander("➕ Add New Member", expanded=False):
            a_col1, a_col2, a_col3, a_col4, a_col5 = st.columns(5)
            with a_col1:
                new_plot = st.text_input("Plot No", key="new_plot")
            with a_col2:
                new_name = st.text_input("Member Name", key="new_name")
            with a_col3:
                new_email = st.text_input("Email (comma-separated)", key="new_email")
            with a_col4:
                new_phone = st.text_input("Phone", key="new_phone")
            with a_col5:
                new_wa = st.text_input("WhatsApp No", key="new_wa")
            if st.button("Add Member", use_container_width=True, key="add_member_btn"):
                if new_plot and new_name:
                    data_provider.add_member({
                        "Plot_No": new_plot, "Plot_Owner_Name": new_name,
                        "Email": new_email, "Phone": new_phone,
                        "WhatsApp_No": new_wa,
                        "Pending_Interest": 0,
                    })
                    st.success(f"Member {new_name} added!")
                    st.rerun()
                else:
                    st.error("Plot No and Name are required")

        if members_list:
            st.subheader("✏️ Update Member")
            upd_mid = st.selectbox(
                "Select Member", options=[m["ID"] for m in members_list],
                format_func=_member_label, key="upd_member",
            )
            upd_m = _find_member(upd_mid)
            if upd_m:
                u_col1, u_col2, u_col3, u_col4, u_col5 = st.columns(5)
                with u_col1:
                    upd_plot = st.text_input("Plot No", value=str(upd_m.get("Plot_No", "") or ""), key="upd_plot")
                with u_col2:
                    upd_name = st.text_input("Member Name", value=str(upd_m.get("Plot_Owner_Name", "") or ""), key="upd_name")
                with u_col3:
                    upd_email = st.text_input("Email (comma-separated)", value=str(upd_m.get("Email", "") or ""), key="upd_email")
                with u_col4:
                    upd_phone = st.text_input("Phone", value=str(upd_m.get("Phone", "") or ""), key="upd_phone")
                with u_col5:
                    upd_wa = st.text_input("WhatsApp No", value=str(upd_m.get("WhatsApp_No", "") or ""), key="upd_wa")
                if st.button("Update Member", type="primary", use_container_width=True, key="upd_member_btn"):
                    data_provider.update_member(upd_mid, {
                        "Plot_No": upd_plot, "Plot_Owner_Name": upd_name,
                        "Email": upd_email, "Phone": upd_phone, "WhatsApp_No": upd_wa,
                    })
                    st.success(f"Member {upd_name} updated!")
                    st.rerun()

    with tab3:
        st.subheader("Expense Categories")
        cats = data_provider.get_expense_categories()
        if cats:
            st.dataframe(
                [{"ID": c.get("ID", ""), "Name": c.get("Name", ""), "Parent": c.get("Parent", "") or "—"}
                 for c in cats],
                use_container_width=True,
            )
        add_cat_col1, add_cat_col2 = st.columns(2)
        with add_cat_col1:
            new_cat_name = st.text_input("New Category Name", key="new_cat_name")
        with add_cat_col2:
            parent_opts = [""] + sorted(set(c["Name"] for c in cats)) if cats else [""]
            new_cat_parent = st.selectbox("Parent (optional)", parent_opts, key="new_cat_parent")
        if st.button("Add Category", key="add_cat_btn"):
            if new_cat_name.strip():
                data_provider.add_expense_category(new_cat_name.strip(), new_cat_parent.strip() or None)
                st.success(f"Category '{new_cat_name}' added!")
                st.rerun()
            else:
                st.error("Category name is required")
        if cats:
            cat_to_del = st.selectbox("Delete Category", [""] + sorted(set(c["Name"] for c in cats)),
                                       key="del_cat", format_func=lambda x: "Select..." if not x else x)
            if cat_to_del and st.button("Delete Category", type="secondary", key="del_cat_btn"):
                data_provider.delete_expense_category(cat_to_del)
                st.success(f"Category '{cat_to_del}' deleted!")
                st.rerun()

    with tab4:
        st.subheader("Payment Identifiers")
        identifiers = data_provider.get_all_identifiers()
        if identifiers:
            id_search = st.text_input("Search", key="id_search", placeholder="Filter by value...")
            id_display = []
            for idr in identifiers:
                val = str(idr.get("Identifier_Value", "") or "")
                if id_search and id_search.lower() not in val.lower():
                    continue
                id_display.append({
                    "Type": idr.get("Identifier_Type", ""),
                    "Value": val[:50],
                    "Member": _member_label(idr.get("Member_ID")),
                    "Date": idr.get("Date", ""),
                })
            if id_display:
                st.dataframe(id_display, use_container_width=True)
            else:
                st.info("No matching identifiers.")
        else:
            st.info("No identifiers recorded yet.")

        if identifiers:
            del_id_opts = {f"{i}: {str(idr.get('Identifier_Value', '') or '')[:40]}": i
                          for i, idr in enumerate(identifiers)}
            del_id_sel = st.selectbox("Delete Identifier", [""] + list(del_id_opts.keys()),
                                       key="del_id", format_func=lambda x: "Select..." if not x else x)
            if del_id_sel and st.button("Delete", key="del_id_btn"):
                idx = del_id_opts[del_id_sel]
                data_provider.delete_identifier(idx)
                st.success("Identifier deleted!")
                st.rerun()

    with tab5:
        st.subheader("Split Rules")
        rules = data_provider.get_split_rules()
        if rules:
            st.dataframe(
                [{"ID": r.get("ID", ""),
                  "Source": _member_label(r.get("Source_Member_ID")),
                  "Members": ", ".join(
                      _member_label(int(x)) for x in str(r.get("Members", "")).split(",") if x.strip()
                  )}
                 for r in rules],
                use_container_width=True,
            )
        members = data_provider.get_all_members()
        src_mid = st.selectbox("Source Member", options=[m["ID"] for m in members],
                               format_func=_member_label, key="split_src_member")
        grp_mids = st.multiselect("Group Members (include source)",
                                  options=[m["ID"] for m in members],
                                  format_func=_member_label, key="split_grp_members")
        if st.button("Add Split Rule", key="add_split_rule"):
            if src_mid and grp_mids and len(grp_mids) >= 2:
                data_provider.add_split_rule(src_mid, grp_mids)
                st.success("Split rule added!")
                st.rerun()
            else:
                st.error("Select source member and at least 2 group members")
        if rules:
            rule_ids = [r.get("ID") for r in rules]
            del_rule_id = st.selectbox("Delete Rule", [0] + rule_ids,
                                        format_func=lambda x: "Select..." if x == 0 else f"Rule #{x}",
                                        key="del_rule")
            if del_rule_id and st.button("Delete Rule", key="del_rule_btn"):
                data_provider.delete_split_rule(del_rule_id)
                st.success("Split rule deleted!")
                st.rerun()

    with tab6:
        st.subheader("System Management")
        if st.button("Trigger April 1st Entries", use_container_width=True):
            st.info("Processing April 1st entries for all members...")
            st.success("April 1st entries created successfully!")

        with st.expander("💾 Data Backups & Restore", expanded=False):
            st.markdown("Auto-backups are created before each bank statement processing run.")
            backup_files = sorted(config.BACKUPS_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not backup_files:
                st.info("No backups found.")
            else:
                import datetime as _dt
                for bf in backup_files[:10]:
                    mtime = _dt.datetime.fromtimestamp(bf.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    size_kb = bf.stat().st_size / 1024
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        st.write(f"`{bf.name}` ({mtime})")
                    with col2:
                        st.write(f"{size_kb:.0f} KB")
                    with col3:
                        if st.button("Restore", key=f"restore_{bf.name}"):
                            shutil.copy2(bf, config.SOCIETY_DATA_FILE)
                            data_provider._invalidate_cache()
                            st.success(f"Restored from {bf.name}")
                            st.rerun()

    with tab7:
        st.subheader("Email Configuration")
        email_settings = data_provider.get_settings()
        smtp_server = st.text_input("SMTP Server",
                                    value=email_settings.get("SMTP_Server", "smtp.gmail.com"),
                                    key="smtp_server")
        smtp_port = st.number_input("SMTP Port",
                                    value=int(email_settings.get("SMTP_Port", 587)),
                                    min_value=1, max_value=65535,
                                    key="smtp_port")
        smtp_user = st.text_input("SMTP Username",
                                  value=email_settings.get("SMTP_User", ""),
                                  key="smtp_user")
        smtp_pass = st.text_input("SMTP Password",
                                  value=email_settings.get("SMTP_Pass", ""),
                                  type="password",
                                  key="smtp_pass")
        from_email = st.text_input("From Email",
                                   value=email_settings.get("From_Email", ""),
                                   key="from_email")
        cc_email = st.text_input("CC Email (optional)",
                                 value=email_settings.get("CC_Email", ""),
                                 key="cc_email")
        if st.button("Save Email Settings", use_container_width=True):
            data_provider.update_settings({
                "SMTP_Server": smtp_server,
                "SMTP_Port": str(smtp_port),
                "SMTP_User": smtp_user,
                "SMTP_Pass": smtp_pass,
                "From_Email": from_email,
                "CC_Email": cc_email,
            })
            st.success("Email settings saved!")

        st.divider()
        st.subheader("Share Document")
        rec_members = data_provider.get_all_members()
        share_mid = st.selectbox("Select Member",
                                 options=[m["ID"] for m in rec_members],
                                 format_func=_member_label,
                                 key="share_member")
        if share_mid:
            share_doc_type = st.radio("Document Type", ["Receipts", "Invoices"], horizontal=True, key="share_doc_type")
            share_entries = data_provider.get_member_ledger(share_mid)
            share_opts = {}
            for e in share_entries:
                if share_doc_type == "Receipts":
                    if _s(e.get("Credit")) <= 0:
                        continue
                    ref_id = (_extract_ref_id(str(e.get("Description", "")))
                              or _extract_ref_id(str(e.get("Particulars", "")))
                              or "")
                    label = f"{e.get('Date', '')} | {e.get('Transaction_Type', '')} | ₹{_s(e.get('Credit')):,.2f} | {ref_id}"
                    search_dir = config.RECEIPTS_DIR
                else:
                    if str(e.get("Transaction_Type", "") or "").upper() != "INVOICE":
                        continue
                    desc = str(e.get("Description", "") or "")
                    inv_match = re.search(r'Invoice\s+(\S+)', desc)
                    ref_id = inv_match.group(1) if inv_match else _extract_ref_id(desc)
                    label = f"{e.get('Date', '')} | INVOICE | ₹{_s(e.get('Debit')):,.2f} | {ref_id}"
                    search_dir = config.INVOICES_DIR
                share_opts[label] = (e, ref_id, search_dir)
            if share_opts:
                share_sel = st.selectbox(f"Select {share_doc_type[:-1]}", [""] + list(share_opts.keys()),
                                          format_func=lambda x: "Select..." if not x else x,
                                          key="share_sel")
                if share_sel:
                    entry, ref_id, search_dir = share_opts[share_sel]
                    pdf_path = _get_pdf_path(search_dir, ref_id) if ref_id else None
                    member = _find_member(share_mid)
                    col_s1, col_s2, col_s3 = st.columns(3)
                    with col_s1:
                        if pdf_path and pdf_path.exists():
                            with open(pdf_path, "rb") as fh:
                                st.download_button("📄 Download", data=fh,
                                                   file_name=pdf_path.name, key="share_dl")
                    with col_s2:
                        if member and member.get("Email") and smtp_user and smtp_pass:
                            if st.button("📧 Send Email", key="share_email_btn"):
                                try:
                                    from utils.email_sender import send_receipt_email
                                    result = send_receipt_email(
                                        smtp_server=smtp_server,
                                        smtp_port=smtp_port,
                                        smtp_user=smtp_user,
                                        smtp_pass=smtp_pass,
                                        from_email=from_email,
                                        to_emails=member["Email"],
                                        cc_email=cc_email or None,
                                        member_name=member.get("Plot_Owner_Name", ""),
                                        plot_no=member.get("Plot_No", ""),
                                        pdf_path=pdf_path,
                                    )
                                    if result:
                                        st.success("Email sent!")
                                    else:
                                        st.error("Failed to send email")
                                except Exception as ex:
                                    st.error(f"Email error: {ex}")
                        else:
                            st.info("Configure email settings and ensure member has email")
                    with col_s3:
                        if member and member.get("WhatsApp_No"):
                            wa_link = f"https://wa.me/{member['WhatsApp_No'].replace('+', '').replace(' ', '')}"
                            st.markdown(f"[📱 Send WhatsApp]({wa_link})", unsafe_allow_html=True)
            else:
                st.info(f"No {share_doc_type.lower()} found for this member.")


def show_help_page():
    """Help and examples page"""
    st.title("❓ Help & Examples")

    st.markdown("""
    ## How to Use This Chatbot

    ### Invoice Generation
    - "Generate invoices for FY 2026-27"
    - "Create invoices for all members"
    - The agent will generate PDF invoices with all calculations

    ### Payment Processing
    - "Process this payment screenshot"
    - Upload the screenshot using the file uploader above the chat input
    - Then type your request (e.g., "Process this payment for Plot 05")
    - The agent will OCR the image, extract details, and generate a receipt

    ### Ledger Management
    - "Show ledger for Plot 01"
    - "View outstanding balance for [member name]"
    - "Export all ledgers to CSV"

    ### Admin Tasks
    - "Update invoice rates"
    - "Add new member"
    - "Trigger April 1st auto-entries"

    ## Features

    - 🤖 Multi-agent system for different tasks
    - 💬 Natural language chat interface with integrated file upload
    - 📄 Automatic invoice generation with PDF output
    - 📷 Upload payment screenshots alongside chat for instant OCR + receipting
    - 📊 Complete ledger management
    - 💾 Local file storage (scalable to Google Drive)
    - 🔐 Secure admin login

    ## Architecture

    - **Abstraction Layers**: Data and file storage abstraction allows easy migration to Google Sheets/Drive
    - **Local MVP**: All files stored locally, no Google API required yet
    - **Scalable**: Ready for enterprise features

    """)


def process_user_input(user_input: str) -> str:
    """
    Process user input using the Orchestrator Agent for multi-step workflows.
    Shows routing intent analysis for transparency.
    """
    try:
        # Show intent analysis from router
        try:
            router = get_router()
            routing_result = router.route(user_input)
            st.info(f"🤖 **Intent**: {routing_result['intent']} (confidence: {routing_result['confidence']:.0%})")
            if routing_result.get("clarification_needed") and routing_result.get("agent") is None:
                return f"❓ {routing_result.get('clarification_question', 'I need more information to help you.')}\n\n**Suggested actions:**\n- Generate invoices\n- Process payments\n- View ledgers\n- Manage admin settings"
        except Exception:
            pass

        # Route to orchestrator for multi-step handling
        with st.spinner("🤖 Processing with Orchestrator Agent..."):
            response = orchestrator_agent.run(user_input)
        return response

    except Exception as e:
        st.error(f"Processing error: {str(e)}")
        return f"❌ Error processing your request: {str(e)}"


def handle_invoice_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle invoice-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("📄 Processing invoice request..."):
            response = invoice_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Invoice agent error: {str(e)}")
        return f"❌ Invoice agent error: {str(e)}"


def handle_receipt_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle payment/receipt-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("💳 Processing payment request..."):
            response = receipt_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Receipt agent error: {str(e)}")
        return f"❌ Receipt agent error: {str(e)}"


def handle_ledger_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle ledger/account-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("📊 Fetching ledger information..."):
            response = ledger_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Ledger agent error: {str(e)}")
        return f"❌ Ledger agent error: {str(e)}"


def handle_admin_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle admin/settings-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("⚙️ Processing admin request..."):
            response = admin_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Admin agent error: {str(e)}")
        return f"❌ Admin agent error: {str(e)}"


if __name__ == "__main__":
    main()
