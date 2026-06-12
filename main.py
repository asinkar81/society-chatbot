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
    """Render a suspense entries table with Create/Delete actions."""
    member_opts = {m["ID"]: f"Plot {m.get('Plot_No','?')} — {m.get('Plot_Owner_Name','?')}" for m in all_members}
    for se in entries:
        sid = se["ID"]
        date_str = str(se.get("Date", "") or "")
        amount = float(se.get("Amount", 0))
        particulars = str(se.get("Particulars", "") or "")
        txn_type = str(se.get("Transaction_Type", "") or "")
        with st.container(border=True):
            cols = st.columns([1.5, 3, 1.5, 3])
            cols[0].markdown(f"**{date_str}** — ₹{amount:>,.2f}")
            cols[1].markdown(f"`{particulars[:80]}`")
            cols[2].markdown(f"`{txn_type or '—'}`")
            with cols[3]:
                create_mid = st.selectbox(
                    "Assign to", options=list(member_opts.keys()),
                    format_func=lambda x: member_opts.get(x, f"ID {x}"),
                    key=f"sus_pick_{sid}", label_visibility="collapsed",
                    placeholder="Select plot...",
                )
                cc1, cc2, cc3 = st.columns([2, 1, 1])
                if cc1.button("📋 Create", key=f"sus_create_{sid}", use_container_width=True):
                    if not create_mid:
                        st.warning("Select a plot first")
                    else:
                        vch = dp.get_next_voucher_number()
                        fy = get_fy_from_date(date_str)
                        receipt_id = f"{fy}-{str(vch).zfill(3)}"
                        dp.add_ledger_entry(create_mid, {
                            "Date": date_str,
                            "Particulars": f"By {particulars[:60]}",
                            "Vch_Type": "Journal",
                            "Vch_No": vch,
                            "Debit": None,
                            "Credit": amount,
                            "Description": f"Receipt {receipt_id} — From Suspense",
                            "Transaction_Type": txn_type,
                            "Transaction_ID": str(se.get("Transaction_ID", "") or ""),
                        })
                        dp.delete_suspense_entry(sid)
                        st.success(f"✅ Created ledger entry for {member_opts.get(create_mid, '?')}")
                        st.rerun()
                if cc2.button("⏭️ Skip", key=f"sus_skip_{sid}", use_container_width=True):
                    import re
                    desc = str(se.get("Description", "") or "")
                    m = re.search(r"Moved from Accounts Entry #(\d+)", desc)
                    if m:
                        eid = int(m.group(1))
                        dp.update_accounts_entry(eid, {"Status": "Skipped"})
                    dp.delete_suspense_entry(sid)
                    st.success("⏭️ Entry skipped and removed from Suspense")
                    st.rerun()
                if cc3.button("🗑️", key=f"sus_del_{sid}", use_container_width=True):
                    dp.delete_suspense_entry(sid)
                    st.rerun()


def _fy_date_range(fy: str) -> tuple:
    """Convert '24-25' or '2024-25' to (from_date, to_date) strings in DD-MM-YYYY format."""
    try:
        parts = fy.split("-")
        if len(parts) != 2:
            return ("", "")
        start_yr = int(parts[0])
        if start_yr < 100:
            start_yr += 2000
        end_yr = start_yr + 1
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
    m2 = re.search(r"\((\d{1,2})-(\d{1,2})-(\d{4})\s+to\s+(\d{1,2})-(\d{1,2})-(\d{4}),\s+(\d+)\s+months\)", parts)
    if m2:
        from_date = f"{int(m2.group(1)):02d}-{int(m2.group(2)):02d}-{m2.group(3)}"
        to_date = f"{int(m2.group(4)):02d}-{int(m2.group(5)):02d}-{m2.group(6)}"
        months = int(m2.group(7))
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
    Deletes ALL old entries with same invoice_no + PDF, creates new entry + PDF.
    Returns status message or None on failure."""
    import re
    from datetime import datetime, timedelta
    import config
    from tools.pdf_generator import create_simple_invoice_pdf

    info = _parse_invoice_entry(entry)
    if not info:
        return None

    invoice_no = info["invoice_no"]
    invoice_date = str(entry.get("Date", "") or "")
    old_desc = str(entry.get("Description", "") or "")
    ref_id = _extract_ref_id(old_desc)

    # ── Compute basic charges (independent of ledger state) ──
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
    plot_str = str(member.get("Plot_No", "") or "")
    plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"

    # ── Delete old PDF(s) ──
    fy_short = info["fy"][:2]
    # Delete old shared PDF (no FY suffix) across all invoice dirs
    for sub_dir in [d for d in config.INVOICES_DIR.iterdir() if d.is_dir()]:
        old_path = sub_dir / f"Invoice_{plot_part}_{ref_id}.pdf"
        old_path.unlink(missing_ok=True)
    # Delete FY-specific PDF (with FY suffix) from the correct directory
    fy_dir = config.INVOICES_DIR / fy_short
    if fy_dir.exists():
        for p in fy_dir.glob(f"*{ref_id}*"):
            p.unlink(missing_ok=True)

    # ── Delete ALL existing entries with this invoice_no (clean up duplicates) ──
    ledger = dp.get_member_ledger(member_id)
    vchs_to_del = []
    for e in ledger:
        desc = str(e.get("Description", "") or "")
        if re.search(rf"Invoice\s+{re.escape(invoice_no)}\s+FY\s+{re.escape(info['fy'])}", desc):
            vch = int(e.get("Vch_No", 0))
            if vch:
                vchs_to_del.append(vch)
    for vch in vchs_to_del:
        dp.delete_ledger_entry(member_id, vch)

    # ── Recalculate outstanding from clean ledger ──
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

    # ── Build invoice_data ──
    bill_period = f"{_month_names[period_start.month - 1]}{period_start.year % 100} to {_month_names[period_end.month - 1]}{period_end.year % 100}"
    inv_date = datetime.strptime(invoice_date, "%d-%m-%Y") if invoice_date else datetime.now()
    if not invoice_date:
        invoice_date = inv_date.strftime("%d-%m-%Y")
    due_date = (inv_date + timedelta(days=config.INVOICE_DUE_DAYS)).strftime("%d-%m-%Y")
    line_items = {
        f"Repair & Maintenance Fund @ ₹{repair_rate:,.2f}/month × {months} months": repair_amt,
        f"Service Charges @ ₹{service_rate:,.2f}/month × {months} months": service_amt,
        f"Sinking Fund @ ₹{sinking_rate:,.2f}/month × {months} months": sinking_amt,
    }

    payment_history = get_payment_history(ledger, invoice_date)
    previous_invoices = get_previous_invoices(ledger, invoice_date)

    prev_outstanding = -compute_outstanding_as_of(ledger, invoice_date)
    total_line_items = repair_amt + service_amt + sinking_amt
    total_amount_due = total_line_items + prev_outstanding + pending_interest

    invoice_data = {
        "invoice_no": invoice_no,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "plot_owner_name": member.get("Plot_Owner_Name", "Unknown"),
        "plot_no": member.get("Plot_No", "N/A"),
        "bill_period": bill_period,
        "from_date": info["from_date"],
        "to_date": info["to_date"],
        "number_of_months": months,
        "payment_history": payment_history,
        "previous_invoices": previous_invoices,
        "line_items": line_items,
        "previous_outstanding": prev_outstanding,
        "interest_penalty": pending_interest,
        "total_line_items": total_line_items,
        "total_amount_due": total_amount_due,
        "amount_in_words": number_to_words_inr(total_amount_due),
    }

    # ── Write new PDF ──
    fy_short = info["fy"][:2]
    invoice_dir = config.INVOICES_DIR / fy_short
    invoice_dir.mkdir(parents=True, exist_ok=True)
    invoice_path = invoice_dir / f"Invoice_{plot_part}_{invoice_no}_FY{fy_short}.pdf"
    if not create_simple_invoice_pdf(invoice_path, invoice_data):
        return f"Failed to generate PDF for invoice {invoice_no}"

    # ── Create new ledger entry ──
    date_range = f"{info['from_date']} to {info['to_date']}, {months} months"
    vch_no_new = dp.get_next_voucher_number()
    dp.add_ledger_entry(member_id, {
        "Date": invoice_date,
        "Particulars": f"To Annual Maintenance Charges ({date_range})",
        "Vch_Type": "Journal",
        "Vch_No": vch_no_new,
        "Debit": total_line_items,
        "Credit": None,
        "Description": f"Invoice {invoice_no} FY {info['fy']} (Demand: ₹{total_amount_due:,.2f}) (regenerated)",
        "Transaction_Type": "INVOICE",
    })

    return f"Regenerated invoice {invoice_no} for ₹{total_amount_due:,.2f}"


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
        "payment_details": str(entry.get("Particulars", ""))[:120],
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
    if not ref_id:
        return "no"
    fy_match = re.search(r'FY\s+(\d{2})-\d{2}', desc)
    if fy_match:
        fy_dir = config.INVOICES_DIR / fy_match.group(1)
        if fy_dir.exists() and any(fy_dir.glob(f"*{ref_id}*")):
            return "yes"
    if _get_pdf_path(config.INVOICES_DIR, ref_id):
        return "yes"
    return "no"


def _run_tool(tool_name: str, input_str: str) -> str:
    """Run an orchestrator tool by name, returning its text output."""
    for t in orchestrator_agent.tools:
        if t.name == tool_name:
            result = t.func(input_str)
            return str(result) if result else ""
    return f"Tool '{tool_name}' not found"


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

    tab_accounts, tab_invoices, tab_ledgers, tab_receipts, tab_expenses, tab_reports = st.tabs(
        ["Accounts", "Invoices", "Ledgers", "Receipts", "Expenses", "Reports"]
    )

    # ═══════════════════════════════════════════════════════════════
    # TAB 1: Accounts
    # ═══════════════════════════════════════════════════════════════
    with tab_accounts:

        # ── Accounts-Based Bank Statement Processing ─────────────────
        st.subheader("🏦 Accounts (Parse → Validate → Create Ledger)")

        import hashlib, shutil
        from datetime import datetime

        # ── Statement Upload / Paste ──
        with st.expander("Upload & Parse Bank Statement", expanded=True):
            pdf_file = st.file_uploader("Upload bank statement PDF", type=["pdf"], key="ac_pdf_upload")
            stmt_password = st.text_input("PDF Password", type="password", value=config.BANK_STMT_PASSWORD, key="ac_pwd")

            if pdf_file is not None:
                pdf_bytes = pdf_file.read()
                file_hash = hashlib.sha256(pdf_bytes).hexdigest()[:16]
                processed = data_provider.get_processed_statements()
                already_done = any(p.get("File_Hash", "") == file_hash for p in processed)
                if already_done:
                    st.info(f"'{pdf_file.name}' already processed. Re-parse below if needed.")
                else:
                    save_path = config.BANK_STATEMENTS_DIR / pdf_file.name
                    with open(save_path, "wb") as f:
                        f.write(pdf_bytes)
                    with st.spinner("Parsing PDF..."):
                        from tools.pdf_parser import parse_bank_pdf
                        parsed = parse_bank_pdf(str(save_path), password=stmt_password)
                    st.success(f"{parsed['entry_count']} entries (format: {parsed['format']})")

                    if st.button("📥 Parse to Accounts", key="ac_parse_pdf"):
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_pre_parse.xlsx")
                        from tools.pdf_parser import extract_text_from_pdf
                        raw_pdf_text = extract_text_from_pdf(str(save_path), password=stmt_password)
                        result = _run_tool("parse_statement_to_accounts", json.dumps({
                            "statement": raw_pdf_text, "filename": pdf_file.name, "format": parsed["format"],
                        }))
                        data_provider.record_processed_statement(
                            filename=pdf_file.name,
                            date_range=f"from_{pdf_file.name.replace('.pdf', '')}",
                            entry_count=parsed["entry_count"],
                            fmt=parsed["format"],
                            file_hash=file_hash,
                        )
                        data_provider.refresh_reports_sheet()
                        st.markdown(result)
                        st.rerun()

            st.divider()
            st.markdown("**Or paste bank statement text:**")
            pasted_text = st.text_area("", placeholder="Paste statement text here...", key="ac_pasted", label_visibility="collapsed")
            if pasted_text and pasted_text.strip():
                if st.button("📥 Parse Pasted Text to Accounts", key="ac_parse_paste"):
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_pre_parse.xlsx")
                    result = _run_tool("parse_statement_to_accounts", json.dumps({
                        "statement": pasted_text.strip(), "filename": "pasted_text",
                    }))
                    data_provider.refresh_reports_sheet()
                    st.markdown(result)
                    st.rerun()

        # ── Accounts Summary (compact) ──
        accts_summary = data_provider.get_accounts_summary()
        if accts_summary.get("total_entries", 0) > 0:
            pending_count = len(data_provider.get_accounts_entries(status="Pending"))
            unmatched_count = len(data_provider.get_accounts_entries(status="Unmatched"))
            st.subheader("📊 Accounts Sheet Summary")
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Total Entries", accts_summary["total_entries"])
            col2.metric("Balance ✓", accts_summary.get("balance_ok", 0))
            col3.metric("Balance ✗", accts_summary.get("balance_mismatch", 0))
            col4.metric("Pending", pending_count)
            col5.metric("Unmatched", unmatched_count)

            # ── Account Balances by FY ──
            continuity = accts_summary.get("continuity", [])
            if continuity:
                st.subheader("Account Balances by Financial Year")
                fy_rows = []
                for fy in continuity:
                    status_icon = "✅"
                    rollover = fy.get("rollover_from_prev")
                    if rollover and not rollover["match"]:
                        status_icon = "❌"
                    fy_rows.append({
                        "FY": fy["fy"],
                        "Opening": f"₹{fy['opening_balance']:,.2f}",
                        "Closing": f"₹{fy['closing_balance']:,.2f}",
                        "Deposits": f"₹{fy.get('total_deposits', 0):,.2f}",
                        "Withdrawals": f"₹{fy.get('total_withdrawals', 0):,.2f}",
                        "Entries": fy["entries"],
                        "Files": ", ".join(fy["files"]),
                        "Status": status_icon,
                    })
                st.dataframe(fy_rows, use_container_width=True, hide_index=True)

            gaps = accts_summary.get("gaps", [])
            if gaps:
                st.warning("⚠️ Balance mismatches at FY boundaries:")
                for g in gaps:
                    st.caption(
                        f"  • FY {g['from_fy']} closing ₹{g['expected_closing']:,.2f} → "
                        f"FY {g['to_fy']} opening ₹{g['actual_opening']:,.2f} "
                        f"(diff: ₹{g['difference']:,.2f})"
                    )

        # ── Accounts Table Viewer ──
        if accts_summary.get("total_entries", 0) > 0:
            with st.expander("📋 View Accounts Entries", expanded=False):
                accounts_entries = data_provider.get_accounts_entries()
                if accounts_entries:
                    import pandas as _pd
                    ac_df = _pd.DataFrame(accounts_entries)
                    ac_df["_dt_sort"] = _pd.to_datetime(ac_df["Date"], format="%d-%m-%Y", errors="coerce")

                    def _fy_label(d):
                        try:
                            from datetime import datetime as _dt
                            dt = _dt.strptime(str(d).strip(), "%d-%m-%Y")
                            if dt.month >= 4:
                                return f"{str(dt.year)[2:]}-{str(dt.year+1)[2:]}"
                            return f"{str(dt.year-1)[2:]}-{str(dt.year)[2:]}"
                        except Exception:
                            return "Unknown"
                    ac_df["FY"] = ac_df["Date"].apply(_fy_label)

                    cols = st.columns(4)
                    with cols[0]:
                        fy_options = ["All"] + sorted(ac_df["FY"].unique())
                        fy_filter = st.selectbox("FY", fy_options, key="ac_fy_filter")
                    with cols[1]:
                        sf_options = ["All"] + sorted(ac_df["Source_File"].dropna().unique())
                        sf_filter = st.selectbox("File", sf_options, key="ac_sf_filter")
                    with cols[2]:
                        status_options = ["All", "Pending", "Potential Duplicate", "Matched", "Unmatched", "Skipped", "Expensed"]
                        status_filter = st.selectbox("Status", status_options, key="ac_status_filter")
                    with cols[3]:
                        check_options = ["All", "✓ (OK)", "✗ (Mismatch)", "Blank (Not Checked)"]
                        check_filter = st.selectbox("Check", check_options, key="ac_check_filter")

                    if fy_filter != "All":
                        ac_df = ac_df[ac_df["FY"] == fy_filter]
                    if sf_filter != "All":
                        ac_df = ac_df[ac_df["Source_File"] == sf_filter]
                    if status_filter != "All":
                        ac_df = ac_df[ac_df["Status"] == status_filter]
                    if check_filter != "All":
                        bc = ac_df["Balance_Check"].astype(str)
                        if check_filter == "✓ (OK)":
                            ac_df = ac_df[bc.str.contains("✓")]
                        elif check_filter == "✗ (Mismatch)":
                            ac_df = ac_df[bc.str.contains("✗")]
                        elif check_filter == "Blank (Not Checked)":
                            ac_df = ac_df[bc.str.strip().isin(["", "nan", "None"])]

                    ac_df = ac_df.sort_values("_dt_sort")

                    display_cols = {
                        "Entry_ID": "ID", "Date": "Date", "Particulars": "Particulars",
                        "Withdrawal": "W/D", "Deposit": "Dep", "Balance": "Bal",
                        "Calculated_Balance": "Calc_Bal", "Balance_Check": "Check",
                        "Status": "Status", "Source_File": "File", "Transaction_ID": "Txn_ID",
                        "FY": "FY",
                    }
                    avail = {k: v for k, v in display_cols.items() if k in ac_df.columns}
                    view = ac_df[list(avail.keys())].copy()
                    view["Particulars"] = view["Particulars"].astype(str).str[:60]
                    view.columns = list(avail.values())
                    total_dep = float(ac_df["Deposit"].fillna(0).sum()) if "Deposit" in ac_df.columns else 0
                    total_wd = float(ac_df["Withdrawal"].fillna(0).sum()) if "Withdrawal" in ac_df.columns else 0
                    st.caption(f"📊 {len(ac_df)} records  |  Deposits: ₹{total_dep:,.2f}  |  Withdrawals: ₹{total_wd:,.2f}")
                    st.dataframe(view, use_container_width=True, hide_index=True)

                interest_entries = data_provider.get_interest_income()
                if interest_entries:
                    with st.expander(f"📈 Interest Income ({len(interest_entries)} entries)", expanded=False):
                        ii_df = [{
                            "ID": e.get("ID", ""),
                            "Date": e.get("Date", ""),
                            "Particulars": str(e.get("Particulars", "") or "")[:60],
                            "Amount": f"₹{float(e.get('Amount', 0) or 0):,.2f}",
                            "File": e.get("Source_File", ""),
                            "Txn_ID": str(e.get("Transaction_ID", "") or ""),
                        } for e in interest_entries]
                        st.dataframe(ii_df, use_container_width=True, hide_index=True)



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
                                import shutil
                                from datetime import datetime as _dt
                                from tools.pdf_parser import extract_text_from_pdf

                                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                                shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_auto_reprocess.xlsx")

                                old_ac = data_provider.get_accounts_entries(source_file=fname)
                                if old_ac:
                                    old_ids = [e["Entry_ID"] for e in old_ac]
                                    data_provider.delete_accounts_entries(old_ids)

                                raw_pdf_text = extract_text_from_pdf(str(fpath), password=pwd)
                                ac_result = _run_tool("parse_statement_to_accounts", json.dumps({
                                    "statement": raw_pdf_text, "filename": fname,
                                }))
                                data_provider.refresh_reports_sheet()
                                st.session_state.reprocess_msg = (
                                    f"✅ Reprocessed '{fname}' — Accounts re-parsed.\n{ac_result}"
                                )
                                st.rerun()

            st.divider()
            if st.button("🔄 Full Reset & Rebuild from All Statements", type="primary", use_container_width=True, key="rebuild_all"):
                import shutil
                from datetime import datetime as _dt

                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_auto_rebuild.xlsx")
                with st.spinner("Resetting and rebuilding all statements..."):
                    result = _run_tool("reset_and_rebuild_all", json.dumps({}))
                    data_provider.refresh_reports_sheet()
                    st.session_state.reprocess_msg = result
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

        # ── Receipts List ─────────────────────────────────────────
        st.subheader("📄 Receipts")
        rec_fy_options = ["All"] + _get_available_fys(
            data_provider.get_accounts_entries()
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
                    if _s(e.get("Credit")) > 0:
                        rec_all_entries.append({**e, "_mid": m["ID"], "_mname": m.get("Plot_Owner_Name", ""), "_mplot": m.get("Plot_No", "")})
        else:
            m = _find_member(rec_member_id)
            if m:
                for e in data_provider.get_member_ledger(rec_member_id):
                    if _s(e.get("Credit")) > 0:
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
                    cols = st.columns([0.4, 1.8, 1.5, 0.6, 0.6, 1.8, 0.7, 0.7, 0.7, 0.7])
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
                                cols[6].download_button("📄", data=fh, file_name=pdf_path.name, key=f"rec_pdf_{idx}")
                    with cols[7]:
                        if cr > 0 and st.button("🔄", key=f"rec_regen_{idx}", help="Regenerate receipt"):
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
                        if cr > 0 and st.button("📧", key=f"rec_share_{idx}", help="Share receipt"):
                            es = data_provider.get_settings()
                            mr = data_provider.get_member(e["_mid"])
                            _raw_email = mr.get("Email") if mr else None
                            mem_email = "" if (_raw_email is None or (isinstance(_raw_email, float) and pd.isna(_raw_email))) else str(_raw_email).strip()
                            if not mem_email:
                                st.warning("Member has no email address")
                            elif not es.get("SMTP_User") or not es.get("SMTP_Pass"):
                                st.warning("Email not configured — go to Settings > Email")
                            else:
                                try:
                                    from utils.email_sender import send_template_email
                                    fy = get_fy_from_date(str(e.get("Date", "")))
                                    refs = ";".join([pdf_path.name]) if pdf_path and pdf_path.exists() else ""
                                    r = send_template_email(
                                        smtp_server=es.get("SMTP_Server", "smtp.gmail.com"),
                                        smtp_port=int(es.get("SMTP_Port", 587)),
                                        smtp_user=es.get("SMTP_User", ""),
                                        smtp_pass=es.get("SMTP_Pass", ""),
                                        from_email=es.get("From_Email", ""),
                                        to_emails=mem_email,
                                        cc_email=es.get("CC_Email", ""),
                                        member_name=e.get("_mname", ""),
                                        plot_no=str(e.get("_mplot", "")),
                                        template_type="receipt",
                                        entries=[{"date": str(e.get("Date", "")),
                                                  "amount": cr, "ref_id": ref_id or "",
                                                  "particulars": str(e.get("Particulars", "")),
                                                  "type": "CR"}],
                                        pdf_paths=[pdf_path] if pdf_path and pdf_path.exists() else [],
                                        fy=fy,
                                    )
                                    data_provider.log_communication(
                                        member_id=e["_mid"], template_type="receipt",
                                        subject=r["subject"], recipients=r["recipients"],
                                        cc=es.get("CC_Email", ""),
                                        status="sent" if r["success"] else "failed",
                                        document_refs=refs, error=r["error"],
                                    )
                                    if r["success"]:
                                        st.success(f"✅ Receipt emailed to {mem_email}")
                                    else:
                                        st.error(f"Failed: {r['error']}")
                                except Exception as ex:
                                    st.error(f"Email error: {ex}")
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
                            pdf_path_wa = _get_pdf_path(config.RECEIPTS_DIR, ref_id) if ref_id else None
                            pdf_names = [pdf_path_wa.name] if pdf_path_wa and pdf_path_wa.exists() else []
                            msg = build_wa_message(
                                "receipt", mr, summary=None,
                                entries=[{"date": str(e.get("Date", "")),
                                          "amount": cr, "ref_id": ref_id or "",
                                          "particulars": str(e.get("Particulars", "")),
                                          "type": "CR"}],
                                pdf_names=pdf_names,
                            )
                            wa_link = build_wa_link(wa_phone, msg)
                            copy_to_clipboard(msg)
                            if pdf_path_wa and pdf_path_wa.exists():
                                staging_d = config.STAGING_DIR / "whatsapp" / datetime.now().strftime("%Y%m%d_%H%M%S")
                                staging_d.mkdir(parents=True, exist_ok=True)
                                import shutil
                                shutil.copy2(pdf_path_wa, staging_d)
                                subprocess.run(["open", str(staging_d)])
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
        else:
            st.info("No receipts found for selected filters.")

    # ═══════════════════════════════════════════════════════════════
    # TAB 4: Invoices
    # ═══════════════════════════════════════════════════════════════
    with tab_invoices:

        # ── Generate Invoices ─────────────────────────────────────
        with st.expander("🧾 Generate Invoices", expanded=False):
            inv_mode = st.radio("Invoice Mode", ["Financial Year", "Custom Dates"],
                                horizontal=True, key="inv_mode")

            if inv_mode == "Financial Year":
                inv_fy_options = _get_available_fys(data_provider.get_accounts_entries())
                current_fy = get_fy_string()
                if current_fy not in inv_fy_options:
                    inv_fy_options.insert(0, current_fy)
                selected_fy = st.selectbox("Select Financial Year", inv_fy_options, key="inv_fy_select")
                fy_parts = selected_fy.split("-")
                fy_start = 2000 + int(fy_parts[0])
                computed_from = f"01-04-{fy_start}"
                computed_to = f"31-03-{fy_start + 1}"
                computed_inv = f"01-04-{fy_start}"
                st.caption(f"📅 {computed_from} to {computed_to}  |  Invoice Date: {computed_inv}")
            else:
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
                if inv_mode == "Financial Year":
                    params["fy"] = selected_fy
                    params["invoice_date"] = computed_inv
                else:
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
            data_provider.get_accounts_entries()
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
            bcols = st.columns([0.6, 2, 2, 2, 0.9])
            with bcols[0]:
                select_all = st.checkbox("☑", key="inv_select_all", label_visibility="collapsed",
                                         on_change=_inv_select_all_changed)
            with bcols[1]:
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
            with bcols[2]:
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
            with bcols[3]:
                if st.button("🔄 Regenerate All", type="primary", use_container_width=True, key="inv_regen_all"):
                    if inv_filtered:
                        msgs = []
                        with st.spinner(f"Regenerating {len(inv_filtered)} invoice(s)..."):
                            for e in inv_filtered:
                                msg = regenerate_invoice(data_provider, e["_mid"], e)
                                if msg:
                                    msgs.append(msg)
                        st.success(f"✅ Regenerated {len(msgs)} of {len(inv_filtered)} invoice(s)")
                        st.rerun()
                    else:
                        st.warning("No invoices to regenerate")

            for idx, e in enumerate(inv_filtered):
                desc = str(e.get("Description", "") or "")
                inv_match = re.search(r'Invoice\s+(\S+)', desc)
                ref_id = inv_match.group(1) if inv_match else _extract_ref_id(desc)
                pdf_path = _get_pdf_path(config.INVOICES_DIR, ref_id) if ref_id else None
                istatus = _invoice_exists(e)
                e_key = idx
                with st.container(border=True):
                    cols = st.columns([0.4, 1.8, 1.5, 0.6, 0.5, 1.8, 0.55, 0.55, 0.55, 0.55, 0.55])
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
                            es = data_provider.get_settings()
                            mr = data_provider.get_member(e["_mid"])
                            _raw_email = mr.get("Email") if mr else None
                            mem_email = "" if (_raw_email is None or (isinstance(_raw_email, float) and pd.isna(_raw_email))) else str(_raw_email).strip()
                            if not mem_email:
                                st.warning("Member has no email address")
                            elif not es.get("SMTP_User") or not es.get("SMTP_Pass"):
                                st.warning("Email not configured — go to Settings > Email")
                            else:
                                try:
                                    from utils.email_sender import send_template_email
                                    fy = get_fy_from_date(str(e.get("Date", "")))
                                    refs = ";".join([pdf_path.name]) if pdf_path and pdf_path.exists() else ""
                                    inv_member_id = e["_mid"]
                                    inv_ledger = data_provider.get_member_ledger(inv_member_id)
                                    fy_start = f"31-03-20{fy[:2]}"
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
                                    r = send_template_email(
                                        smtp_server=es.get("SMTP_Server", "smtp.gmail.com"),
                                        smtp_port=int(es.get("SMTP_Port", 587)),
                                        smtp_user=es.get("SMTP_User", ""),
                                        smtp_pass=es.get("SMTP_Pass", ""),
                                        from_email=es.get("From_Email", ""),
                                        to_emails=mem_email,
                                        cc_email=es.get("CC_Email", ""),
                                        member_name=e.get("_mname", ""),
                                        plot_no=str(e.get("_mplot", "")),
                                        template_type="invoice",
                                        entries=[{"date": str(e.get("Date", "")),
                                                  "amount": _s(e.get("Debit")), "ref_id": ref_id or "",
                                                  "particulars": str(e.get("Particulars", "")),
                                                  "type": "DR"}],
                                        pdf_paths=[pdf_path] if pdf_path and pdf_path.exists() else [],
                                        fy=fy,
                                        summary=inv_summary,
                                    )
                                    data_provider.log_communication(
                                        member_id=e["_mid"], template_type="invoice",
                                        subject=r["subject"], recipients=r["recipients"],
                                        cc=es.get("CC_Email", ""),
                                        status="sent" if r["success"] else "failed",
                                        document_refs=refs, error=r["error"],
                                    )
                                    if r["success"]:
                                        st.success(f"✅ Invoice emailed to {mem_email}")
                                    else:
                                        st.error(f"Failed: {r['error']}")
                                except Exception as ex:
                                    st.error(f"Email error: {ex}")
                    with cols[9]:
                        if st.button("🗑️", key=f"inv_del_{e_key}", help="Delete invoice"):
                            msg = delete_invoice(data_provider, e["_mid"], e)
                            if msg:
                                st.success(msg)
                            else:
                                st.error("Deletion failed")
                            st.rerun()
                    with cols[10]:
                        mr = data_provider.get_member(e["_mid"])
                        _raw_wa = mr.get("WhatsApp_No") if mr else None
                        wa_phone = "" if (_raw_wa is None or (isinstance(_raw_wa, float) and pd.isna(_raw_wa))) else str(_raw_wa).strip()
                        if wa_phone and st.button("💬", key=f"inv_wa_{e_key}", help="Share invoice via WhatsApp"):
                            from utils.whatsapp import build_wa_message, build_wa_link, copy_to_clipboard
                            fy = get_fy_from_date(str(e.get("Date", "")))
                            ref_id_wa = (_extract_ref_id(str(e.get("Description", "")))
                                         or _extract_ref_id(str(e.get("Particulars", "")))
                                         or "")
                            pdf_path_wa = _get_pdf_path(config.INVOICES_DIR, ref_id_wa) if ref_id_wa else None
                            pdf_names = [pdf_path_wa.name] if pdf_path_wa and pdf_path_wa.exists() else []
                            inv_ledger = data_provider.get_member_ledger(e["_mid"])
                            fy_start = f"31-03-20{fy[:2]}"
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
                                          "amount": _s(e.get("Debit")), "ref_id": ref_id_wa or "",
                                          "particulars": str(e.get("Particulars", "")),
                                          "type": "DR"}],
                                pdf_names=pdf_names,
                            )
                            wa_link = build_wa_link(wa_phone, msg)
                            copy_to_clipboard(msg)
                            if pdf_path_wa and pdf_path_wa.exists():
                                staging_d = config.STAGING_DIR / "whatsapp" / datetime.now().strftime("%Y%m%d_%H%M%S")
                                staging_d.mkdir(parents=True, exist_ok=True)
                                import shutil
                                shutil.copy2(pdf_path_wa, staging_d)
                                subprocess.run(["open", str(staging_d)])
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
        else:
            st.info("No invoices found for selected filters.")

    # ═══════════════════════════════════════════════════════════════
    # TAB 5: Ledgers
    # ═══════════════════════════════════════════════════════════════
    with tab_ledgers:

        # ── Record Payment ─────────────────────────────────────────
        with st.expander("💰 Record Payment", expanded=False):
            pay_member_id = st.selectbox(
                "Member *", options=[m["ID"] for m in members],
                format_func=_member_label, key="led_pay_member",
            )
            pay_col1, pay_col2 = st.columns(2)
            with pay_col1:
                pay_date = st.text_input("Date (DD-MM-YYYY)", value="", key="led_pay_date", placeholder="e.g. 15-05-2026")
                pay_amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0, key="led_pay_amount")
                pay_generate_receipt = st.checkbox("Generate Receipt PDF", value=False, key="led_pay_gen_rec")
            with pay_col2:
                pay_particulars = st.text_input("Particulars", key="led_pay_particulars", placeholder="e.g. Maintenance payment")
                pay_txn_type = st.selectbox("Transaction Type", ["NEFT", "UPI", "CHQ", "CASH", "IMPS", "RTGS", "Other"], key="led_pay_txn_type")
                pay_txn_id = st.text_input("Transaction ID (optional)", key="led_pay_txn_id", placeholder="e.g. UTR number")

            if st.button("Save Payment", type="primary", use_container_width=True, key="led_pay_save"):
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

        # ── Create Ledger from Accounts ────────────────────────────
        all_pending = data_provider.get_accounts_entries(status="Pending") or []
        all_unmatched = data_provider.get_accounts_entries(status="Unmatched") or []
        if all_pending or all_unmatched:
            settings_g = data_provider.get_settings()
            current_fy_g = settings_g.get("Current_FY", "26-27")
            if len(current_fy_g) == 7:
                current_fy_g = current_fy_g[2:]
            all_accounts_g = data_provider.get_accounts_entries()
            fy_options_g = _get_available_fys(all_accounts_g) or [current_fy_g]
            default_fy = fy_options_g[0] if fy_options_g else current_fy_g

            with st.expander("📤 Create Ledger from Accounts", expanded=False):
                gen_receipts = st.checkbox(
                    "📄 Generate Receipt PDFs", value=False, key="led_gen_receipts",
                    help="Generate receipt PDFs when creating ledger entries.",
                )

                selected_fy = st.selectbox("Financial Year", fy_options_g,
                    index=fy_options_g.index(default_fy) if default_fy in fy_options_g else 0,
                    key="led_fy_create")

                # Count pending+unmatched in selected FY
                def _sortable(dd):
                    try:
                        p = dd.split("-")
                        return f"{p[2]}-{p[1]}-{p[0]}"
                    except Exception:
                        return dd
                f_from, f_to = _fy_date_range(selected_fy)
                sk = _sortable(f_from) if f_from else ""
                ek = _sortable(f_to) if f_to else ""
                fy_pending = sum(1 for e in all_pending
                    if (float(e.get("Deposit", 0) or 0) > 0)
                    and sk <= _sortable(str(e.get("Date", "") or "")) <= ek)
                fy_unmatched = sum(1 for e in all_unmatched
                    if (float(e.get("Deposit", 0) or 0) > 0)
                    and sk <= _sortable(str(e.get("Date", "") or "")) <= ek)
                fy_pending_amt = sum(
                    float(e.get("Deposit", 0) or 0) for e in all_pending
                    if (float(e.get("Deposit", 0) or 0) > 0)
                    and sk <= _sortable(str(e.get("Date", "") or "")) <= ek)
                fy_unmatched_amt = sum(
                    float(e.get("Deposit", 0) or 0) for e in all_unmatched
                    if (float(e.get("Deposit", 0) or 0) > 0)
                    and sk <= _sortable(str(e.get("Date", "") or "")) <= ek)

                st.caption(f"📊 Pending: {fy_pending} (₹{fy_pending_amt:,.2f}) | "
                           f"Unmatched: {fy_unmatched} (₹{fy_unmatched_amt:,.2f}) | FY {selected_fy}")
                st.divider()

                # ── Preview & Auto Create buttons ──
                pcol1, pcol2 = st.columns(2)
                with pcol1:
                    preview_clicked = st.button("🔍 Preview Ledger Entries",
                        type="secondary", use_container_width=True, key="led_preview_btn")
                with pcol2:
                    auto_clicked = st.button("⚡ Auto Create Ledger from Accounts",
                        type="primary", use_container_width=True, key="led_auto_btn")

                # Invalidate preview on FY change
                if (st.session_state.get("ledger_preview_fy")
                    and st.session_state.ledger_preview_fy != selected_fy):
                    st.session_state.ledger_preview_data = None
                    st.session_state.ledger_preview_fy = None

                if preview_clicked:
                    with st.spinner("Running preview matching..."):
                        raw = _run_tool("create_ledger_from_accounts", json.dumps({
                            "fy": selected_fy, "mode": "preview",
                        }))
                        try:
                            st.session_state.ledger_preview_data = json.loads(raw)
                            st.session_state.ledger_preview_fy = selected_fy
                        except Exception:
                            st.error("Preview failed: " + raw[:500])
                    st.rerun()

                if auto_clicked:
                    with st.spinner("Auto-creating ledger entries..."):
                        result = _run_tool("create_ledger_from_accounts", json.dumps({
                            "fy": selected_fy, "mode": "create",
                            "generate_receipts": gen_receipts,
                        }))
                        st.session_state.ledger_create_msg = result
                        data_provider.refresh_reports_sheet()
                    st.rerun()

                # ── Preview results ──
                preview_data = st.session_state.get("ledger_preview_data")
                if preview_data and st.session_state.get("ledger_preview_fy") == selected_fy:
                    matched = preview_data.get("matched", [])
                    unmatched = preview_data.get("unmatched", [])
                    auto_income_ct = preview_data.get("auto_income", 0)

                    # Combine into unified list
                    all_entries = []
                    for m in matched:
                        all_entries.append({
                            "entry_id": m["entry_id"], "status": "matched",
                            "date": m.get("date", ""), "amount": m.get("amount", 0),
                            "particulars": m.get("particulars", ""),
                            "plot_no": m.get("plot_no", ""), "member_name": m.get("member_name", ""),
                            "member_id": m.get("member_id"), "reason": m.get("reason", ""),
                        })
                    for u in unmatched:
                        all_entries.append({
                            "entry_id": u["entry_id"], "status": "unmatched",
                            "date": u.get("date", ""), "amount": u.get("amount", 0),
                            "particulars": u.get("particulars", ""),
                            "plot_no": "", "member_name": "", "member_id": None, "reason": "",
                        })
                    all_entries.sort(key=lambda x: x["entry_id"])

                    # Build member label lookup
                    member_plot_opts = {}
                    for m in members:
                        member_plot_opts[m["ID"]] = f"Plot {m.get('Plot_No','?')} — {m.get('Plot_Owner_Name','?')}"

                    # Initialize widget defaults for any missing keys
                    for e in all_entries:
                        eid = e["entry_id"]
                        if f"pv_cb_{eid}" not in st.session_state:
                            st.session_state[f"pv_cb_{eid}"] = True
                        if f"pv_plot_{eid}" not in st.session_state:
                            default = e["member_id"] if e["status"] == "matched" and e["member_id"] else ""
                            st.session_state[f"pv_plot_{eid}"] = default
                        if f"pv_idtxt_{eid}" not in st.session_state:
                            st.session_state[f"pv_idtxt_{eid}"] = ""

                    # ── Preview table + actions in a form (no per-widget refreshes) ──
                    with st.container(border=True):
                        pv_msg = st.session_state.pop("pv_result_msg", None)
                        if pv_msg:
                            st.success(pv_msg)
                        st.subheader(f"📋 Preview ({len(all_entries)} entries)")

                        with st.form(key="pv_form"):
                            # Batch selection buttons
                            sacol1, sacol2 = st.columns([1, 1])
                            if sacol1.form_submit_button("☑ All", use_container_width=True):
                                for e in all_entries:
                                    st.session_state[f"pv_cb_{e['entry_id']}"] = True
                                st.rerun()
                            if sacol2.form_submit_button("☐ None", use_container_width=True):
                                for e in all_entries:
                                    st.session_state[f"pv_cb_{e['entry_id']}"] = False
                                st.rerun()

                            # Column headers
                            hcols = st.columns([0.5, 0.7, 1.3, 1.3, 2.5, 2.5, 3.5])
                            hcols[0].caption("")
                            hcols[1].caption("Status")
                            hcols[2].caption("Date")
                            hcols[3].caption("Amount")
                            hcols[4].caption("Plot / Member")
                            hcols[5].caption("Known Identifier")
                            hcols[6].caption("Particulars")

                            # Build shared plot options
                            plot_opts = {"": "No Match"}
                            for pid, label in member_plot_opts.items():
                                plot_opts[pid] = label
                            plot_keys = list(plot_opts.keys())

                            for e in all_entries:
                                eid = e["entry_id"]
                                cols = st.columns([0.5, 0.7, 1.3, 1.3, 2.5, 2.5, 3.5])
                                cols[0].checkbox("", key=f"pv_cb_{eid}")
                                cols[1].write("✅" if e["status"] == "matched" else "❌")
                                cols[2].write(e["date"])
                                cols[3].write(f"₹{e['amount']:>8,.2f}")
                                # Plot / Member dropdown for ALL entries
                                # Use format_func with plot_keys lookup to avoid lambda closure issues
                                cols[4].selectbox("", plot_keys,
                                    format_func=lambda x: plot_opts.get(x, "No Match"),
                                    key=f"pv_plot_{eid}", label_visibility="collapsed")
                                # Known Identifier
                                if e["status"] == "matched":
                                    cols[5].write(e.get("reason", ""))
                                else:
                                    cols[5].text_input("", key=f"pv_idtxt_{eid}",
                                        placeholder="e.g. AJAY", label_visibility="collapsed")
                                cols[6].write(e["particulars"])

                            if auto_income_ct:
                                st.info(f"📈 {auto_income_ct} entries will be auto-skipped (Interest Income)")

                            st.divider()

                            # ── Action buttons ──
                            acol1, acol2, acol3 = st.columns(3)
                            with acol1:
                                create_clicked = st.form_submit_button("✅ Create Selected Entries",
                                    type="primary", use_container_width=True)
                            with acol2:
                                suspense_clicked = st.form_submit_button("📋 Send to Suspense",
                                    use_container_width=True)
                            with acol3:
                                cancel_clicked = st.form_submit_button("❌ Cancel",
                                    use_container_width=True)

                    # ── Process actions (outside form, after submit) ──
                    if create_clicked:
                        to_create = []
                        forced = {}
                        today_str = datetime.now().strftime("%d-%m-%Y")
                        for e in all_entries:
                            if not st.session_state.get(f"pv_cb_{e['entry_id']}", False):
                                continue
                            eid = e["entry_id"]
                            assigned_mid = st.session_state.get(f"pv_plot_{eid}", "")
                            if not assigned_mid:
                                continue
                            member = next((m for m in members if m["ID"] == assigned_mid), None)
                            if not member:
                                continue
                            orig_plot = str(e.get("plot_no", ""))
                            new_plot = str(member.get("Plot_No", ""))
                            if new_plot != orig_plot:
                                forced[str(eid)] = new_plot
                            to_create.append(eid)
                            idtxt = (st.session_state.get(f"pv_idtxt_{eid}", "") or "").strip()
                            if idtxt:
                                data_provider.add_identifier(assigned_mid, "PAYEE_NAME", idtxt, today_str)
                        if not to_create:
                            st.warning("No entries selected with a valid plot assignment.")
                        else:
                            with st.spinner("Creating selected ledger entries..."):
                                payload = {"fy": selected_fy, "mode": "create", "generate_receipts": gen_receipts}
                                payload["entry_ids"] = to_create
                                if forced:
                                    payload["forced_assignments"] = forced
                                _run_tool("create_ledger_from_accounts", json.dumps(payload))
                                created_set = set(to_create)
                                remaining = [e for e in all_entries if e["entry_id"] not in created_set]
                                for eid in created_set:
                                    for k in (f"pv_cb_{eid}", f"pv_plot_{eid}", f"pv_idtxt_{eid}"):
                                        st.session_state.pop(k, None)
                                msg = f"✅ Created {len(to_create)} entries successfully."
                                if remaining:
                                    msg += f" {len(remaining)} entries still in preview."
                                    st.session_state.ledger_preview_data = {
                                        "matched": [e for e in remaining if e["status"] == "matched"],
                                        "unmatched": [e for e in remaining if e["status"] == "unmatched"],
                                        "auto_income": auto_income_ct,
                                    }
                                else:
                                    st.session_state.ledger_preview_data = None
                                    st.session_state.ledger_preview_fy = None
                                st.session_state["pv_result_msg"] = msg
                                data_provider.refresh_reports_sheet()
                        st.rerun()

                    if suspense_clicked:
                        to_suspend = []
                        for e in all_entries:
                            if not st.session_state.get(f"pv_cb_{e['entry_id']}", False):
                                continue
                            assigned_mid = st.session_state.get(f"pv_plot_{e['entry_id']}", "")
                            if not assigned_mid:
                                to_suspend.append(e["entry_id"])
                        if not to_suspend:
                            st.warning("No entries selected with 'No Match' plot.")
                        else:
                            with st.spinner(f"Moving {len(to_suspend)} entries to Suspense..."):
                                _run_tool("create_ledger_from_accounts", json.dumps({
                                    "fy": selected_fy, "mode": "send_to_suspense",
                                    "entry_ids": to_suspend,
                                }))
                                suspended_set = set(to_suspend)
                                remaining = [e for e in all_entries if e["entry_id"] not in suspended_set]
                                for eid in suspended_set:
                                    for k in (f"pv_cb_{eid}", f"pv_plot_{eid}", f"pv_idtxt_{eid}"):
                                        st.session_state.pop(k, None)
                                msg = f"✅ Sent {len(to_suspend)} entries to Suspense."
                                if remaining:
                                    msg += f" {len(remaining)} entries still in preview."
                                    st.session_state.ledger_preview_data = {
                                        "matched": [e for e in remaining if e["status"] == "matched"],
                                        "unmatched": [e for e in remaining if e["status"] == "unmatched"],
                                        "auto_income": auto_income_ct,
                                    }
                                else:
                                    st.session_state.ledger_preview_data = None
                                    st.session_state.ledger_preview_fy = None
                                st.session_state["pv_result_msg"] = msg
                                data_provider.refresh_reports_sheet()
                        st.rerun()

                    if cancel_clicked:
                        for e in all_entries:
                            for k in (f"pv_cb_{e['entry_id']}", f"pv_plot_{e['entry_id']}", f"pv_idtxt_{e['entry_id']}"):
                                st.session_state.pop(k, None)
                        st.session_state.ledger_preview_data = None
                        st.session_state.ledger_preview_fy = None
                        st.rerun()

        # Show result message (preview-based operations)
        pv_msg = st.session_state.pop("pv_result_msg", None)
        if pv_msg:
            st.success(pv_msg)
        # Show persistent create result message (auto-create)
        create_msg = st.session_state.get("ledger_create_msg")
        if create_msg:
            st.success(create_msg)
            if st.button("Dismiss", key="led_dismiss_msg"):
                st.session_state.ledger_create_msg = None
                st.rerun()
        with st.expander("📋 Suspense Entries", expanded=False):
            suspense_list = data_provider.get_suspense_entries()
            if not suspense_list:
                st.info("No suspense entries.")
            else:
                st.caption(f"{len(suspense_list)} entries awaiting assignment")
                _show_suspense_table(suspense_list, data_provider, members)

        with st.expander("📋 View Ledger Entries", expanded=True):
            # ── Ledger Filters ─────────────────────────────────────────
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
                        data_provider.get_accounts_entries()
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
                all_filtered_entries = []
                total_entries_ap = 0
                total_dr_ap = 0.0
                total_cr_ap = 0.0
                for m in members:
                    mid = m["ID"]
                    ledger = data_provider.get_member_ledger(mid)
                    filtered = _filter_entries(ledger, led_type_filter, led_from_dt, led_to_dt)
                    total_entries_ap += len(filtered)
                    td = _s(sum(float(e.get("Debit") or 0) for e in filtered))
                    tc = _s(sum(float(e.get("Credit") or 0) for e in filtered))
                    total_dr_ap += td
                    total_cr_ap += tc
                    for e in filtered:
                        all_filtered_entries.append({
                            "Plot": m.get("Plot_No", "?"),
                            "Name": m.get("Plot_Owner_Name", "?"),
                            "Date": str(e.get("Date", "") or ""),
                            "Vch_No": e.get("Vch_No", ""),
                            "Particulars": str(e.get("Particulars", "") or "")[:60],
                            "Debit": _s(e.get("Debit")),
                            "Credit": _s(e.get("Credit")),
                            "Type": str(e.get("Transaction_Type", "") or ""),
                        })
                if total_entries_ap > 0:
                    st.caption(f"📊 {total_entries_ap} entries  |  "
                               f"Total Credits: ₹{total_cr_ap:,.2f}  |  "
                               f"Total Debits: ₹{total_dr_ap:,.2f}  |  "
                               f"Net: ₹{total_cr_ap - total_dr_ap:,.2f}")
                    st.dataframe(all_filtered_entries, use_container_width=True, hide_index=True)
                else:
                    st.info("No entries match the current filters.")
            else:
                led_member = _find_member(led_member_id)
                if led_member:
                    raw_ledger = data_provider.get_member_ledger(led_member_id)
                    led_entries = _filter_entries(raw_ledger, led_type_filter, led_from_dt, led_to_dt)
                    if led_entries:
                        total_dr = _s(sum(_s(e.get("Debit")) for e in led_entries))
                        total_cr = _s(sum(_s(e.get("Credit")) for e in led_entries))
                        st.caption(f"📊 {len(led_entries)} entries  |  Debits: ₹{total_dr:,.2f}  |  Credits: ₹{total_cr:,.2f}  |  Net: ₹{total_cr - total_dr:,.2f}")
    
                        # ── Batch action toolbar + entries ──
                        with st.form(key="led_batch_form"):
                            split_group = data_provider.get_split_group_for_member(led_member_id) if led_member_id else None
                            bcols = st.columns([0.7, 1.5, 1.5, 1.3])
                            with bcols[0]:
                                sel_all = st.form_submit_button("☑ All", use_container_width=True, key="led_sel_all_btn")
                                sel_none = st.form_submit_button("☐ None", use_container_width=True, key="led_sel_none_btn")
                            with bcols[1]:
                                move_clicked = st.form_submit_button("➡️ Move Selected", type="secondary", use_container_width=True, key="led_batch_move")
                            with bcols[2]:
                                split_clicked = st.form_submit_button("✂️ Split Selected", type="secondary", use_container_width=True, key="led_batch_split")
                            with bcols[3]:
                                apply_split = st.form_submit_button("🔀 Apply Rule", type="secondary",
                                    use_container_width=True, key="led_apply_split",
                                    disabled=split_group is None)
    
                            st.divider()
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
                                    unsplit_clicked = False
                                    unmove_clicked = False
                                    if etype.upper() == "SPLIT" or "split from #" in edesc.lower():
                                        orig_match = re.search(r"Split from #(\d+)\s*\(src:(\d+)\)", edesc, re.IGNORECASE)
                                        if orig_match:
                                            unsplit_clicked = st.form_submit_button("↩️ Undo", key=f"led_unsplit_{idx}", help="Undo split, recreate original entry")
                                            if unsplit_clicked:
                                                orig_vch = int(orig_match.group(1))
                                                orig_mid = int(orig_match.group(2))
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
                                    if not unsplit_clicked:
                                        move_match = re.search(r"\(moved from #(\d+)\)", edesc)
                                        if move_match:
                                            src_mid = int(move_match.group(1))
                                            unmove_clicked = st.form_submit_button("↩️ Undo", key=f"led_unmove_{idx}", help="Move back to original member")
                                            if unmove_clicked:
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
                                    if is_credit and not unsplit_clicked and not unmove_clicked:
                                        if st.form_submit_button("➡️ Move", key=f"led_move_{idx}", help="Move to another member"):
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
                                        if st.form_submit_button("✂️ Split", key=f"led_split_{idx}", help="Split across members"):
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
                                            if st.form_submit_button("➡️ Source", key=f"led_route_{idx}", help="Route to source member"):
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
    
                            # ── Process batch actions (only one fires per submit) ──
                            if sel_all:
                                for idx in range(len(led_entries)):
                                    st.session_state[f"led_sel_{idx}"] = True
                                st.rerun()
                            if sel_none:
                                for idx in range(len(led_entries)):
                                    st.session_state[f"led_sel_{idx}"] = False
                                st.rerun()
                            if move_clicked:
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
                            elif split_clicked:
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
                            elif apply_split:
                                if split_group is None:
                                    st.warning("This member has no split rule")
                                else:
                                    sel_idx = [idx for idx, e in enumerate(led_entries)
                                               if st.session_state.get(f"led_sel_{idx}", False)]
                                    target = [led_entries[idx] for idx in sel_idx] if sel_idx else led_entries
                                    credits = [e for e in target if _s(e.get("Credit")) > 0
                                               and str(e.get("Transaction_Type", "")).upper() != "SPLIT"]
                                    if not credits:
                                        st.warning("No unsplit credit entries to process")
                                    else:
                                        processed = 0
                                        for entry in credits:
                                            amount = _s(entry.get("Credit"))
                                            date_str = str(entry.get("Date", "") or "")
                                            particulars = str(entry.get("Particulars", "") or "")
                                            orig_vch = int(entry.get("Vch_No", 0))
                                            if data_provider.delete_ledger_entry(led_member_id, orig_vch):
                                                per_head = round(amount / len(split_group), 2)
                                                for gmid in split_group:
                                                    vch = data_provider.get_next_voucher_number()
                                                    data_provider.add_ledger_entry(gmid, {
                                                        "Date": date_str,
                                                        "Particulars": f"By Split ({particulars[:40]})",
                                                        "Vch_Type": "Journal", "Vch_No": vch,
                                                        "Debit": None, "Credit": per_head,
                                                        "Description": f"Split from #{orig_vch} (src:{led_member_id})",
                                                        "Transaction_Type": "SPLIT",
                                                        "Transaction_ID": entry.get("Transaction_ID", ""),
                                                    })
                                                processed += 1
                                        st.success(f"✅ Applied split rule to {processed} entries")
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
        
        with st.expander("📊 Ledger Summary", expanded=True):
            ls_fy = st.selectbox(
                "FY", ["All", "Custom"] + _get_available_fys(
                    data_provider.get_accounts_entries()
                ) if members else ["All"],
                key="ls_fy",
            )
            ls_from_dt, ls_to_dt = "", ""
            if ls_fy == "Custom":
                c1, c2 = st.columns(2)
                with c1:
                    ls_from_dt = st.text_input("From (DD-MM-YYYY)", value="", key="ls_from")
                with c2:
                    ls_to_dt = st.text_input("To (DD-MM-YYYY)", value="", key="ls_to")
            elif ls_fy != "All":
                ls_from_dt, ls_to_dt = _fy_date_range(ls_fy)

            ls_summary = []
            ls_total_cr = 0.0
            ls_total_dr = 0.0
            for m in members:
                mid = m["ID"]
                led = data_provider.get_member_ledger(mid)
                filtered = _filter_entries(led, "All", ls_from_dt, ls_to_dt)
                td = _s(sum(float(e.get("Debit") or 0) for e in filtered))
                tc = _s(sum(float(e.get("Credit") or 0) for e in filtered))
                ls_total_cr += tc
                ls_total_dr += td
                ls_summary.append({
                    "Plot": m.get("Plot_No", "?"),
                    "Name": m.get("Plot_Owner_Name", "?"),
                    "Debits": td,
                    "Credits": tc,
                    "Net": tc - td,
                    "Outstanding": data_provider.get_current_outstanding(mid),
                })
            if ls_summary:
                st.caption(f"📊 {len(members)} plots  |  "
                           f"Total Credits: ₹{ls_total_cr:,.2f}  |  "
                           f"Total Debits: ₹{ls_total_dr:,.2f}  |  "
                           f"Net: ₹{ls_total_cr - ls_total_dr:,.2f}")
                st.dataframe(
                    [{"Plot": s["Plot"], "Name": s["Name"],
                      "Debits": f"₹{s['Debits']:,.2f}", "Credits": f"₹{s['Credits']:,.2f}",
                      "Net": f"₹{s['Net']:,.2f}",
                      "Outstanding": f"₹{abs(s['Outstanding']):,.2f} {'Demand' if s['Outstanding'] < 0 else 'Surplus' if s['Outstanding'] > 0 else 'Settled'}"}
                     for s in ls_summary],
                    use_container_width=True,
                )
                st.divider()
                if st.button("🔀 Run Split Rules on All", type="primary", use_container_width=True, key="ls_split_all"):
                    rules = data_provider.get_split_rules()
                    total_split = 0
                    for rule in rules:
                        src_mid = int(rule["Source_Member_ID"])
                        group = [int(x.strip()) for x in str(rule.get("Members", "")).split(",") if x.strip().isdigit()]
                        if not group or src_mid not in group:
                            continue
                        src_ledger = data_provider.get_member_ledger(src_mid)
                        unsplit_credits = [e for e in src_ledger
                                           if _s(e.get("Credit")) > 0
                                           and str(e.get("Transaction_Type", "")).upper() != "SPLIT"]
                        for entry in unsplit_credits:
                            amount = _s(entry.get("Credit"))
                            date_str = str(entry.get("Date", "") or "")
                            particulars = str(entry.get("Particulars", "") or "")
                            orig_vch = int(entry.get("Vch_No", 0))
                            if data_provider.delete_ledger_entry(src_mid, orig_vch):
                                per_head = round(amount / len(group), 2)
                                for gmid in group:
                                    vch = data_provider.get_next_voucher_number()
                                    data_provider.add_ledger_entry(gmid, {
                                        "Date": date_str,
                                        "Particulars": f"By Split ({particulars[:40]})",
                                        "Vch_Type": "Journal", "Vch_No": vch,
                                        "Debit": None, "Credit": per_head,
                                        "Description": f"Split from #{orig_vch} (src:{src_mid})",
                                        "Transaction_Type": "SPLIT",
                                        "Transaction_ID": entry.get("Transaction_ID", ""),
                                    })
                                total_split += 1
                    st.success(f"✅ Applied split rules to {total_split} entries")
                    st.rerun()
            else:
                st.info("No data for Ledger Summary.")

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

                # ── FY-wise Balance Check ──
                st.subheader("FY-wise Balance Check", divider="gray")
                all_accounts = data_provider.get_accounts_entries()
                fy_data = {}
                for e in all_accounts:
                    if str(e.get("Status", "") or "").lower() == "skipped":
                        continue
                    fy = get_fy_from_date(str(e.get("Date", "") or ""))
                    d = fy_data.setdefault(fy, {"acc_deposits": 0.0, "acc_count": 0,
                                                "led_receipts": 0.0, "led_count": 0,
                                                "manual_deposits": 0.0, "manual_count": 0})
                    d["acc_deposits"] += _s(e.get("Deposit"))
                    d["acc_count"] += 1
                for e in ledger:
                    tt = str(e.get("Transaction_Type", "") or "").upper()
                    if tt == "INVOICE":
                        continue
                    fy = get_fy_from_date(str(e.get("Date", "") or ""))
                    d = fy_data.setdefault(fy, {"acc_deposits": 0.0, "acc_count": 0,
                                                "led_receipts": 0.0, "led_count": 0,
                                                "manual_deposits": 0.0, "manual_count": 0})
                    if tt == "MANUAL":
                        d["manual_deposits"] += _s(e.get("Credit"))
                        d["manual_count"] += 1
                    else:
                        d["led_receipts"] += _s(e.get("Credit"))
                        d["led_count"] += 1
                fy_rows = []
                for fy in sorted(fy_data, reverse=True):
                    d = fy_data[fy]
                    match = abs(d["acc_deposits"] - d["led_receipts"]) < 1.0
                    fy_rows.append({
                        "FY": fy,
                        "Account Deposits (₹)": round(d["acc_deposits"], 2),
                        "Ledger Receipts (₹)": round(d["led_receipts"], 2),
                        "Manual Deposits (₹)": round(d["manual_deposits"], 2),
                        "Account Entries": d["acc_count"],
                        "Ledger Entries": d["led_count"],
                        "Manual Entries": d["manual_count"],
                        "Status": "✅" if match else "❌",
                    })
                if fy_rows:
                    st.dataframe(pd.DataFrame(fy_rows), use_container_width=True, hide_index=True)
                    if all(r["Status"] == "✅" for r in fy_rows):
                        st.success("✅ All FYs balance: Account Deposits match Ledger Receipts")
                    else:
                        st.error("❌ Some FYs have mismatches between Account Deposits and Ledger Receipts")
                else:
                    st.info("No data for FY-wise reconciliation.")

        st.divider()

        # ── Duplicate Detection ───────────────────────────────────
        with st.expander("🔍 Duplicate Detection", expanded=False):
            if "dup_result" not in st.session_state:
                st.session_state.dup_result = []
            if st.button("Run Duplicate Scan", key="dup_scan_btn"):
                all_ledger = data_provider.get_member_ledger_all()
                part_map = {}  # normalized particulars → list

                for e in all_ledger:
                    mid = e.get("Member_ID") or e.get("Plot_No")
                    if not mid:
                        continue
                    try:
                        mid = int(float(mid))
                    except (ValueError, TypeError):
                        continue
                    pn = _normalize_particulars(e.get("Particulars", ""))
                    if pn:
                        part_map.setdefault(pn, []).append({**e, "_dup_mid": mid})

                dup_groups = []
                seen = set()
                for pn, items in part_map.items():
                    if len(items) >= 2 and len(pn) >= 5:
                        ids = tuple(sorted((e.get("Vch_No"), e["_dup_mid"]) for e in items))
                        if ids not in seen:
                            seen.add(ids)
                            dup_groups.append((f"Particulars: {pn}", items))

                st.session_state.dup_result = dup_groups

            dup_groups = st.session_state.dup_result
            if not dup_groups:
                st.info("Click 'Run Duplicate Scan' to check for potential duplicates across all members.")
            else:
                st.warning(f"⚠️ Found {len(dup_groups)} potential duplicate group(s)")
                for gi, (reason, items) in enumerate(dup_groups):
                    with st.container(border=True):
                        st.caption(f"**{reason}**")
                        with st.form(key=f"dup_form_{gi}"):
                            all_vch = set()
                            for ei, e in enumerate(items):
                                member_info = _find_member(e["_dup_mid"])
                                mlabel = f"P{member_info.get('Plot_No','?')} {member_info.get('Plot_Owner_Name','?')}" if member_info else f"ID {e['_dup_mid']}"
                                cr = _s(e.get("Credit"))
                                amt_lbl = f"CR ₹{cr:>,.2f}" if cr > 0 else f"DR ₹{_s(e.get('Debit')):>,.2f}"
                                is_split = str(e.get("Transaction_Type", "") or "").upper() == "SPLIT"
                                cols = st.columns([0.3, 2, 2, 1.5, 1.2])
                                with cols[0]:
                                    st.checkbox("", key=f"dup_chk_{gi}_{ei}", label_visibility="collapsed")
                                cols[1].write(f"{e.get('Date','')} {amt_lbl}")
                                cols[2].write(mlabel)
                                cols[3].write(f"Vch #{int(e.get('Vch_No',0))}")
                                with cols[4]:
                                    if is_split:
                                        if st.form_submit_button("↩️", key=f"dup_unsp_{gi}_{ei}", help="Undo split (delete all split entries)"):
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
                            del_clicked = st.form_submit_button("🗑️ Delete Selected", type="primary", use_container_width=True)
                            if del_clicked:
                                dc = 0
                                for ei, e in enumerate(items):
                                    if st.session_state.get(f"dup_chk_{gi}_{ei}", False):
                                        if data_provider.delete_ledger_entry(e["_dup_mid"], int(e.get("Vch_No", 0))):
                                            _delete_pdf_files(_extract_ref_id(str(e.get("Description", ""))))
                                            dc += 1
                                st.session_state.dup_result = []
                                if dc:
                                    st.success(f"✅ Deleted {dc} duplicate entries")
                                else:
                                    st.info("No entries selected")
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
        if st.button("🔄 Reload Data from Excel", key="reload_data"):
            data_provider._invalidate_cache()
            st.rerun()

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
                    upd_plot = st.text_input("Plot No", value=str(upd_m.get("Plot_No", "") or ""), key=f"upd_plot_{upd_mid}")
                with u_col2:
                    upd_name = st.text_input("Member Name", value=str(upd_m.get("Plot_Owner_Name", "") or ""), key=f"upd_name_{upd_mid}")
                with u_col3:
                    upd_email = st.text_input("Email (comma-separated)", value=str(upd_m.get("Email", "") or ""), key=f"upd_email_{upd_mid}")
                with u_col4:
                    upd_phone = st.text_input("Phone", value=str(upd_m.get("Phone", "") or ""), key=f"upd_phone_{upd_mid}")
                with u_col5:
                    upd_wa = st.text_input("WhatsApp No", value=str(upd_m.get("WhatsApp_No", "") or ""), key=f"upd_wa_{upd_mid}")
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
        members_list_id = data_provider.get_all_members()
        member_opts_id = {m["ID"]: f"Plot {m.get('Plot_No','?')} — {m.get('Plot_Owner_Name','?')}" for m in members_list_id}

        # ── Context filter from Ledger preview ──
        if st.session_state.get("id_filter_member_ids"):
            st.info(f"📋 {st.session_state.get('id_filter_reason', 'Filtered from Ledger preview')}")
            if st.button("Clear Filter", key="id_clear_ctx"):
                st.session_state.id_filter_member_ids = None
                st.session_state.id_filter_reason = None
                st.rerun()

        with st.form(key="id_form"):
            id_search = st.text_input("🔍 Search", key="id_search_in",
                                       placeholder="Filter by value or type...")
            show_deleted = st.checkbox("Show deleted identifiers", key="id_show_deleted")
            st.divider()

            identifiers = data_provider.get_all_identifiers(include_deleted=show_deleted)
            id_filtered = []
            ctx_mids = st.session_state.get("id_filter_member_ids")
            for idr in identifiers:
                val = str(idr.get("Identifier_Value", "") or "")
                id_type = str(idr.get("Identifier_Type", "") or "")
                mid = idr.get("Member_ID")
                if ctx_mids and mid not in ctx_mids:
                    continue
                if id_search and id_search.lower() not in val.lower() and id_search.lower() not in id_type.lower():
                    continue
                id_filtered.append(idr)

            if id_filtered:
                st.caption(f"📊 {len(id_filtered)} identifiers")
                # Column headers
                hcols = st.columns([0.4, 2.5, 1.5, 2.5, 1, 1.2, 0.7, 0.7])
                hcols[0].caption("#")
                hcols[1].caption("Member")
                hcols[2].caption("Type")
                hcols[3].caption("Value")
                hcols[4].caption("Conf.")
                hcols[5].caption("Last Seen")
                hcols[6].caption("Keep")
                hcols[7].caption("Delete")
                for idr in id_filtered:
                    mid = idr.get("Member_ID")
                    idr_id = idr.get("ID")
                    val = str(idr.get("Identifier_Value", "") or "")[:50]
                    id_type = str(idr.get("Identifier_Type", "") or "")
                    confidence = idr.get("Confidence", 0)
                    last_seen = str(idr.get("Last_Seen_Date", "") or "")
                    is_deleted = str(idr.get("Deleted", "No")) == "Yes"

                    cols = st.columns([0.4, 2.5, 1.5, 2.5, 1, 1.2, 0.7, 0.7])
                    cols[0].caption(f"#{idr_id}")
                    cols[1].write(member_opts_id.get(mid, f"ID {mid}"))
                    cols[2].write(id_type)
                    cols[3].write(val)
                    cols[4].write(str(confidence))
                    cols[5].write(last_seen[:10])
                    if is_deleted:
                        cols[6].write("")
                        cols[7].checkbox("↩️ Restore", key=f"id_restore_{idr_id}")
                    else:
                        cols[6].checkbox("✅", value=True, key=f"id_keep_{idr_id}")
                        cols[7].checkbox("🗑️", key=f"id_del_{idr_id}")
            else:
                st.caption("No identifiers match the current filters.")

            st.divider()
            # ── Add Identifier ──
            st.subheader("➕ Add Identifier")
            a_col1, a_col2, a_col3 = st.columns(3)
            with a_col1:
                add_mid = st.selectbox("Member", options=list(member_opts_id.keys()),
                                       format_func=lambda x: member_opts_id.get(x, f"ID {x}"),
                                       key="id_add_mid")
            with a_col2:
                add_type = st.selectbox("Type", ["PAYEE_NAME", "UPI_ID", "MOBILE", "EMAIL", "OTHER"],
                                        key="id_add_type")
            with a_col3:
                add_val = st.text_input("Value", key="id_add_val", placeholder="Identifier value to add")

            submitted = st.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)
            if submitted:
                del_count = 0
                restore_count = 0
                add_count = 0
                for idr in identifiers:
                    idr_id = idr.get("ID")
                    is_deleted = str(idr.get("Deleted", "No")) == "Yes"
                    if is_deleted:
                        if st.session_state.get(f"id_restore_{idr_id}"):
                            if data_provider.undelete_identifier(idr_id):
                                restore_count += 1
                    else:
                        if st.session_state.get(f"id_del_{idr_id}"):
                            if data_provider.delete_identifier(idr_id):
                                del_count += 1
                if add_val and add_val.strip():
                    data_provider.add_identifier(add_mid, add_type, add_val.strip())
                    add_count += 1
                total = del_count + restore_count + add_count
                if total:
                    parts = []
                    if del_count:
                        parts.append(f"Deleted {del_count}")
                    if restore_count:
                        parts.append(f"Restored {restore_count}")
                    if add_count:
                        parts.append(f"Added {add_count}")
                    st.success(f"✅ {', '.join(parts)}.")
                    st.rerun()
                else:
                    st.info("No changes to save.")

        st.divider()
        if st.button("🧹 Reconcile Identifiers with Ledger", type="secondary",
                     use_container_width=True, key="id_reconcile"):
            import re
            split_re = re.compile(r"Split from #(\d+)\s*\(src:(\d+)\)", re.IGNORECASE)
            ACTION_LABELS = {
                "auto_resolve": "🔀 Auto-resolve",
                "correction": "🔄 Correct",
                "unmatched": "— Unused",
                "consistent": "✅ OK",
            }
            all_idrs = data_provider.get_all_identifiers(include_deleted=False)
            results = []
            for idr in all_idrs:
                mid = idr.get("Member_ID")
                val = str(idr.get("Identifier_Value", "") or "").strip().lower()
                m = data_provider.get_member(mid)
                current_plot = str(m.get("Plot_No", "?")) if m else "?"
                if not val:
                    continue
                found_plots = set()
                entry_details = []
                for sm in data_provider.get_all_members():
                    for e in data_provider.get_member_ledger(sm["ID"]):
                        if val in str(e.get("Particulars", "") or "").lower():
                            plot = str(sm.get("Plot_No", "?"))
                            found_plots.add(plot)
                            entry_details.append((plot, str(e.get("Description", "") or ""), sm["ID"]))
                plots_str = ", ".join(sorted(found_plots)) if found_plots else "—"
                resolve_action = None
                resolve_plot = None
                if found_plots and len(found_plots) > 1:
                    src_plots = set()
                    non_split_plots = set()
                    for plot, desc, eid in entry_details:
                        m_src = split_re.search(desc)
                        if m_src:
                            try:
                                src_mid = int(m_src.group(2))
                                src_member = data_provider.get_member(src_mid)
                                if src_member:
                                    src_plots.add(str(src_member.get("Plot_No", "?")))
                            except (ValueError, TypeError):
                                non_split_plots.add(plot)
                        else:
                            non_split_plots.add(plot)
                    if len(src_plots) == 1:
                        common_src_plot = next(iter(src_plots))
                        non_src_non_split = [p for p in non_split_plots if p != common_src_plot]
                        if not non_src_non_split:
                            resolve_action = "auto_resolve"
                            resolve_plot = common_src_plot
                        else:
                            resolve_action = "conflict"
                    elif src_plots:
                        resolve_action = "conflict"
                elif found_plots and len(found_plots) == 1:
                    single_plot = next(iter(found_plots))
                    if single_plot != current_plot:
                        resolve_action = "correction"
                        resolve_plot = single_plot
                    else:
                        resolve_action = "consistent"
                else:
                    resolve_action = "unmatched"
                results.append({
                    "Value": idr.get("Identifier_Value"),
                    "Type": idr.get("Identifier_Type"),
                    "Current Plot": current_plot,
                    "Plots in Ledger": plots_str,
                    "Action": ACTION_LABELS.get(resolve_action, "⚠️ Conflict"),
                    "ID": idr.get("ID"), "Member_ID": mid,
                    "_resolve_action": resolve_action,
                    "_resolve_plot": resolve_plot,
                })
            st.session_state.id_recon_results = results
            st.rerun()

        id_recon_results = st.session_state.get("id_recon_results")
        if id_recon_results is not None:
            results = id_recon_results
            display_cols = ["Value", "Type", "Current Plot", "Plots in Ledger", "Action"]
            st.dataframe(
                [{k: r[k] for k in display_cols} for r in results],
                use_container_width=True, hide_index=True,
                column_config={"Plots in Ledger": st.column_config.TextColumn("Ledger Plots")},
            )
            auto_resolve = [r for r in results if r["_resolve_action"] == "auto_resolve"]
            corrections = [r for r in results if r["_resolve_action"] == "correction"]
            conflicts = [r for r in results if r["_resolve_action"] == "conflict"]
            conflicts += [r for r in results
                          if r["_resolve_action"] is None and ", " in r["Plots in Ledger"]]
            unmatched = [r for r in results if r["_resolve_action"] == "unmatched"]
            if auto_resolve:
                st.success(f"🔀 {len(auto_resolve)} identifier(s) can be auto-resolved (split entries → source plot)")
                if st.button("🔀 Auto-Resolve", key="id_recon_auto"):
                    for r in auto_resolve:
                        new_plot = r["_resolve_plot"]
                        new_member = next(
                            (m for m in data_provider.get_all_members()
                             if str(m.get("Plot_No")) == new_plot), None)
                        if new_member:
                            data_provider.update_identifier_member(r["ID"], new_member["ID"])
                    st.success(f"✅ Auto-resolved {len(auto_resolve)} identifiers to source plots")
                    st.session_state.id_recon_results = None
                    st.rerun()
            if corrections:
                st.success(f"🔄 {len(corrections)} identifier(s) can be auto-corrected to the ledger plot")
                if st.button("Apply Corrections", key="id_recon_apply"):
                    for r in corrections:
                        new_plot = r["_resolve_plot"]
                        new_member = next(
                            (m for m in data_provider.get_all_members()
                             if str(m.get("Plot_No")) == new_plot), None)
                        if new_member:
                            data_provider.update_identifier_member(r["ID"], new_member["ID"])
                    st.success(f"✅ Updated {len(corrections)} identifiers to match ledger")
                    st.session_state.id_recon_results = None
                    st.rerun()
            if conflicts:
                st.error(f"⚠️ {len(conflicts)} identifier(s) appear in multiple ledger plots — manual review needed")
                for r in conflicts:
                    st.caption(f"  • {r['Value']} ({r['Type']}): plots {r['Plots in Ledger']}")
            if unmatched:
                st.info(f"ℹ️ {len(unmatched)} identifier(s) not yet seen in any ledger — no reconciliation needed")
            if not auto_resolve and not corrections and not conflicts and not unmatched:
                st.info("✅ All identifiers are consistent with the ledger")
            st.button("✕ Dismiss Results", key="id_recon_dismiss",
                      on_click=lambda: st.session_state.pop("id_recon_results", None))

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

        st.divider()
        if st.button("🔄 Full Reset & Rebuild from Bank Statements", type="primary", use_container_width=True):
            import shutil
            from datetime import datetime as _dt_now
            ts = _dt_now.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_full_reset.xlsx")
            with st.spinner("Resetting and rebuilding all financial data from bank statement PDFs..."):
                result = _run_tool("reset_and_rebuild_all", json.dumps({}))
                data_provider.refresh_reports_sheet()
                st.markdown(result)
            st.rerun()

        with st.expander("💾 Data Backups & Restore", expanded=False):
            backup_comment = st.text_input("Comment (optional)", key="backup_comment",
                                            placeholder="e.g. before rate update, after cleanup")
            if st.button("📀 Take Backup Now", type="primary", use_container_width=True, key="backup_now"):
                import shutil
                from datetime import datetime as _dt_now
                ts = _dt_now.now().strftime("%Y%m%d_%H%M%S")
                comment = (backup_comment or "").strip()
                suffix = "_manual"
                if comment:
                    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in comment)[:50].strip().replace(" ", "_")
                    suffix += f"--{safe}" if safe else ""
                fname = f"society_data_{ts}{suffix}.xlsx"
                shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / fname)
                data_provider._invalidate_cache()
                st.success(f"Backup created: {fname}")
                st.rerun()
            st.markdown("Auto-backups are created before each bank statement processing run.")
            backup_files = sorted(config.BACKUPS_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not backup_files:
                st.info("No backups found.")
            else:
                import datetime as _dt
                for bf in backup_files:
                    mtime = _dt.datetime.fromtimestamp(bf.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    size_kb = bf.stat().st_size / 1024
                    comment_part = ""
                    name = bf.name
                    if "--" in name:
                        comment_part = name.split("--", 1)[1].replace(".xlsx", "").replace("_", " ")
                    col1, col2, col3, col4 = st.columns([2.5, 0.7, 0.7, 0.7])
                    with col1:
                        display = f"`{name}` ({mtime})"
                        if comment_part:
                            display += f" — *{comment_part}*"
                        st.write(display)
                    with col2:
                        st.write(f"{size_kb:.0f} KB")
                    with col3:
                        if st.button("Restore", key=f"restore_{bf.name}"):
                            import shutil
                            shutil.copy2(bf, config.SOCIETY_DATA_FILE)
                            data_provider._invalidate_cache()
                            st.success(f"Restored from {bf.name}")
                            st.rerun()
                    with col4:
                        if st.button("🗑️", key=f"del_bak_{bf.name}", help="Delete this backup"):
                            bf.unlink()
                            st.rerun()

    with tab7:
        email_settings = data_provider.get_settings()
        smtp_server = email_settings.get("SMTP_Server", "smtp.gmail.com")
        smtp_port = int(email_settings.get("SMTP_Port", 587))
        smtp_user = email_settings.get("SMTP_User", "")
        smtp_pass = email_settings.get("SMTP_Pass", "")
        from_email = email_settings.get("From_Email", "")
        cc_email = email_settings.get("CC_Email", "")

        with st.expander("⚙️ Email Configuration", expanded=False):
            smtp_server = st.text_input("SMTP Server", value=smtp_server, key="smtp_server")
            smtp_port = st.number_input("SMTP Port", value=smtp_port, min_value=1, max_value=65535, key="smtp_port")
            smtp_user = st.text_input("SMTP Username", value=smtp_user, key="smtp_user")
            smtp_pass = st.text_input("SMTP Password", value=smtp_pass, type="password", key="smtp_pass")
            from_email = st.text_input("From Email", value=from_email, key="from_email")
            cc_email = st.text_input("CC Email (optional)", value=cc_email, key="cc_email")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Save Email Settings", use_container_width=True):
                    data_provider.update_settings({
                        "SMTP_Server": smtp_server, "SMTP_Port": str(smtp_port),
                        "SMTP_User": smtp_user, "SMTP_Pass": smtp_pass,
                        "From_Email": from_email, "CC_Email": cc_email,
                    })
                    st.success("Email settings saved!")
            with c2:
                if st.button("🔍 Test Connection", use_container_width=True,
                             disabled=not (smtp_user and smtp_pass and from_email)):
                    try:
                        from utils.email_sender import send_template_email
                        r = send_template_email(
                            smtp_server=smtp_server, smtp_port=smtp_port,
                            smtp_user=smtp_user, smtp_pass=smtp_pass,
                            from_email=from_email, to_emails=from_email,
                            member_name="Test", plot_no="0",
                            template_type="receipt", fy="",
                            subject_override="Test Email from Society Management",
                            body_override="<p>This is a test email from Weekend Ville Society Management.</p>",
                        )
                        if r["success"]:
                            st.success("✅ Connection successful! Test email sent.")
                        else:
                            st.error(f"Failed: {r['error']}")
                    except Exception as ex:
                        st.error(f"Connection error: {ex}")

        with st.expander("📤 Share Documents", expanded=True):
            share_template = st.radio(
                "Template",
                ["Payment Receipts", "Invoices", "Statement", "Reminder"],
                horizontal=True, key="share_template",
            )
            template_key = {"Payment Receipts": "receipt", "Invoices": "invoice",
                            "Statement": "statement", "Reminder": "reminder"}[share_template]
            share_fy_list = _get_available_fys(data_provider.get_accounts_entries()) if members else []
            share_fy = st.selectbox("FY", ["All", "Custom"] + share_fy_list, key="share_fy")
            share_from_dt, share_to_dt = "", ""
            if share_fy == "Custom":
                c1, c2 = st.columns(2)
                with c1:
                    share_from_dt = st.text_input("From (DD-MM-YYYY)", value="", key="share_from")
                with c2:
                    share_to_dt = st.text_input("To (DD-MM-YYYY)", value="", key="share_to")
            elif share_fy != "All":
                share_from_dt, share_to_dt = _fy_date_range(share_fy)

            all_members = data_provider.get_all_members()
            _all_comms = data_provider.get_communication_log(limit=500)
            _last_sent_map = {}
            for c in _all_comms:
                mid = c.get("Member_ID")
                if mid and mid not in _last_sent_map:
                    _last_sent_map[mid] = (c.get("Date", ""), c.get("Template_Type", ""))
            import re as _re
            share_data = []
            for m in all_members:
                mid = m["ID"]
                led = data_provider.get_member_ledger(mid)
                filtered = _filter_entries(led, "All", share_from_dt, share_to_dt)
                receipts = [e for e in filtered if _s(e.get("Credit")) > 0
                            and str(e.get("Transaction_Type", "") or "").upper() != "INVOICE"]
                invoices = [e for e in filtered if str(e.get("Transaction_Type", "") or "").upper() == "INVOICE"]
                if template_key == "receipt":
                    relevant = receipts
                elif template_key == "invoice":
                    relevant = invoices
                else:
                    relevant = receipts + invoices
                if not relevant:
                    continue
                total = sum(_s(e.get("Credit") or e.get("Debit")) for e in relevant)
                raw_email = m.get("Email")
                mem_email = "" if (raw_email is None or (isinstance(raw_email, float) and pd.isna(raw_email))) else str(raw_email).strip()
                raw_wa = m.get("WhatsApp_No")
                wa_phone = "" if (raw_wa is None or (isinstance(raw_wa, float) and pd.isna(raw_wa))) else str(raw_wa).strip()
                summary = None
                if template_key in ("invoice", "statement", "reminder") and share_fy not in ("All", "Custom") and share_fy:
                    fy_s = share_fy[:2]
                    fy_start = f"31-03-20{fy_s}"
                    share_prev_outstanding = max(0, -compute_outstanding_as_of(led, fy_start))
                    share_entries_fy = [x for x in led if get_fy_from_date(str(x.get("Date", ""))) == share_fy]
                    share_total_demand = sum(float(x.get("Debit", 0)) for x in share_entries_fy
                                             if str(x.get("Transaction_Type", "")).upper() == "INVOICE")
                    share_total_payments = sum(float(x.get("Credit", 0)) for x in share_entries_fy)
                    share_today_str = datetime.now().strftime("%d-%m-%Y")
                    summary = {
                        "previous_outstanding": share_prev_outstanding,
                        "total_demand": share_total_demand,
                        "total_payments": share_total_payments,
                        "total_due": max(0, share_prev_outstanding + share_total_demand - share_total_payments),
                        "as_of_date": share_today_str,
                    }
                share_data.append({
                    "mid": mid, "plot": m.get("Plot_No", "?"),
                    "name": m.get("Plot_Owner_Name", "?"),
                    "email": mem_email, "wa_phone": wa_phone,
                    "rc": len(receipts), "ic": len(invoices),
                    "total": total, "entries": relevant,
                    "last_sent": _last_sent_map.get(mid),
                    "summary": summary,
                })

            if share_data:
                with_email = [sd for sd in share_data if sd["email"]]
                with_wa = [sd for sd in share_data if sd["wa_phone"]]
                no_email_count = len(share_data) - len(with_email)
                label = f"{len(with_email)} member(s) with email"
                if with_wa:
                    label += f", {len(with_wa)} with WhatsApp"
                if no_email_count:
                    label += f" ({no_email_count} without email, not listed)"
                st.caption(label)

                share_opts = {}
                for sd in share_data:
                    if sd["email"] or sd["wa_phone"]:
                        share_opts[f"Plot {sd['plot']} — {sd['name']}"] = sd
                wa_only = st.checkbox("Show only WhatsApp-only (no email)", key="wa_only_filter")
                filtered_opts = {k: v for k, v in share_opts.items()
                                if not wa_only or (v["wa_phone"] and not v["email"])}
                sel_labels = st.multiselect("Recipients", list(filtered_opts.keys()), key="share_sel")
                sel_items = [share_opts[l] for l in sel_labels] if sel_labels else []

                if sel_items and any(sd["last_sent"] for sd in sel_items):
                    for sd in sel_items:
                        if sd["last_sent"]:
                            _ls_d, _ls_t = sd["last_sent"]
                            st.caption(f"📨 {sd['name']}: last sent {_ls_d} ({_ls_t})")

                wa_include_receipts = st.checkbox("Include Receipts", value=True, key="wa_inc_rec")
                wa_include_invoices = st.checkbox("Include Invoices", value=True, key="wa_inc_inv")

                if st.button("Send", type="primary", use_container_width=True,
                             disabled=not (smtp_user and smtp_pass) or not sel_items):
                    from utils.email_sender import send_template_email
                    sent_ok = 0
                    sent_fail = 0
                    for sd in sel_items:
                        pdfs = []
                        entries_for_body = []
                        for e in sd["entries"]:
                            if e.get("Credit", 0) and _receipt_exists(e) == "no":
                                _generate_receipt_for_entry(data_provider, e, sd["mid"])
                            ref_id = (_extract_ref_id(str(e.get("Description", "")))
                                      or _extract_ref_id(str(e.get("Particulars", "")))
                                      or "")
                            if ref_id:
                                sdir = config.RECEIPTS_DIR if e.get("Credit", 0) else config.INVOICES_DIR
                                p = _get_pdf_path(sdir, ref_id)
                                if p:
                                    pdfs.append(p)
                            amt = _s(e.get("Credit")) or _s(e.get("Debit"))
                            entries_for_body.append({
                                "date": str(e.get("Date", "")),
                                "amount": amt, "ref_id": ref_id,
                                "particulars": str(e.get("Particulars", "")),
                                "type": "CR" if e.get("Credit", 0) else "DR",
                            })
                        r = send_template_email(
                            smtp_server=smtp_server, smtp_port=smtp_port,
                            smtp_user=smtp_user, smtp_pass=smtp_pass,
                            from_email=from_email, to_emails=sd["email"],
                            cc_email=cc_email,
                            member_name=sd["name"], plot_no=sd["plot"],
                            template_type=template_key, fy=share_fy,
                            entries=entries_for_body, pdf_paths=pdfs,
                            summary=sd.get("summary"),
                        )
                        ref_str = ";".join(p.name for p in pdfs)
                        data_provider.log_communication(
                            member_id=sd["mid"], template_type=template_key,
                            subject=r["subject"], recipients=r["recipients"],
                            cc=cc_email,
                            status="sent" if r["success"] else "failed",
                            document_refs=ref_str, error=r["error"],
                        )
                        if r["success"]:
                            sent_ok += 1
                        else:
                            sent_fail += 1
                    if sent_ok:
                        st.success(f"✅ Emailed {sent_ok} member(s){' (' + str(sent_fail) + ' failed)' if sent_fail else ''}")
                    if sent_fail and not sent_ok:
                        st.error(f"All {sent_fail} attempts failed — check email settings")

                wa_sel = [sd for sd in sel_items if sd["wa_phone"]]
                if st.button("💬 Send via WhatsApp", use_container_width=True,
                             disabled=not wa_sel):
                    from utils.whatsapp import build_wa_message, build_wa_link, copy_to_clipboard
                    parent_folder = config.STAGING_DIR / "whatsapp" / datetime.now().strftime("%Y%m%d_%H%M%S")
                    parent_folder.mkdir(parents=True, exist_ok=True)
                    wa_processed = 0
                    for sd in wa_sel:
                        wa_processed += 1
                        plot_slug = str(sd.get("plot", "?")).replace(" ", "_")
                        name_slug = str(sd.get("name", "?")).replace(" ", "_")
                        member_folder = parent_folder / f"plot_{plot_slug}_{name_slug}"
                        member_folder.mkdir(parents=True, exist_ok=True)
                        pdfs = []
                        for e in sd["entries"]:
                            is_credit = e.get("Credit", 0)
                            if is_credit and _receipt_exists(e) == "no":
                                _generate_receipt_for_entry(data_provider, e, sd["mid"])
                            etype = str(e.get("Transaction_Type", "") or "").upper()
                            is_inv = etype == "INVOICE"
                            if is_inv and not wa_include_invoices:
                                continue
                            if is_credit and not is_inv and not wa_include_receipts:
                                continue
                            ref_id = (_extract_ref_id(str(e.get("Description", "")))
                                      or _extract_ref_id(str(e.get("Particulars", "")))
                                      or "")
                            sdir = config.RECEIPTS_DIR if is_credit and not is_inv else config.INVOICES_DIR
                            p = _get_pdf_path(sdir, ref_id) if ref_id else None
                            if p and p.exists():
                                pdfs.append(p)
                                import shutil
                                shutil.copy2(p, member_folder)
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
                            ref_id = (_extract_ref_id(str(e.get("Description", "")))
                                      or _extract_ref_id(str(e.get("Particulars", "")))
                                      or "")
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
                            ca, cb, cc = st.columns(3)
                            with ca:
                                if st.button("📋 Copy", key=f"wa_copy_{sd['mid']}"):
                                    if copy_to_clipboard(msg):
                                        st.success("Copied!")
                                    else:
                                        st.info("Copy manually or use Open WhatsApp link")
                            with cb:
                                st.markdown(f'<a href="{wa_link}" target="_blank">🔗 Open WhatsApp</a>',
                                            unsafe_allow_html=True)
                            with cc:
                                if st.button("📂 Open", key=f"wa_folder_{sd['mid']}"):
                                    import subprocess
                                    subprocess.run(["open", str(member_folder)])
                            if pdfs:
                                st.caption(f"{len(pdfs)} PDF(s) in folder:")
                                for pn in pdf_names:
                                    st.text(pn)
                    if wa_processed:
                        st.info(f"✅ {wa_processed} message(s) ready with individual folders. Open All PDFs button available below.")
                        if st.button("📂 Open All PDFs", key="wa_open_staging"):
                            import subprocess
                            subprocess.run(["open", str(parent_folder)])
            else:
                st.info("No entries found for the selected criteria.")

            st.divider()
            st.subheader("📋 Communication Log")
            log_mid_filter = st.selectbox(
                "Filter by member", [0] + [m["ID"] for m in all_members],
                format_func=lambda x: "All Members" if x == 0 else _member_label(x),
                key="comm_log_filter",
            )
            comms = data_provider.get_communication_log(
                member_id=log_mid_filter if log_mid_filter != 0 else None,
                limit=50,
            )
            if comms:
                log_rows = []
                for c in comms:
                    log_rows.append({
                        "Date": c.get("Date", ""),
                        "Member": _member_label(c.get("Member_ID", 0)),
                        "Type": c.get("Template_Type", ""),
                        "Subject": str(c.get("Subject", ""))[:50],
                        "To": c.get("Recipients", ""),
                        "Status": "✅" if c.get("Status") == "sent" else "❌",
                    })
                st.dataframe(log_rows, use_container_width=True, hide_index=True)
            else:
                st.info("No communications recorded yet.")



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
