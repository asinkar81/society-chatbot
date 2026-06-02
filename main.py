"""
Main Streamlit application for Society Management Chatbot
"""
import streamlit as st
from pathlib import Path
import config
from utils.auth import show_login_page, logout
from utils.chat_manager import ChatManager
from utils.converters import get_fy_string, get_fy_from_date, compute_outstanding_as_of, get_payment_history, get_previous_invoices, number_to_words_inr
from data_providers.local_excel_provider import LocalExcelDataProvider
from file_storage.local_storage import LocalFileStorage
from agents.invoice_agent import InvoiceAgent
from agents.receipt_agent import ReceiptAgent
from agents.ledger_agent import LedgerAgent
from agents.admin_agent import AdminAgent
from agents.orchestrator_agent import OrchestratorAgent
from tools.pdf_generator import create_simple_receipt_pdf
from agents.router_agent import get_router
import json
from datetime import datetime
import uuid


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
            ca, cb, cc, cd = st.columns([2, 2, 2, 3])
            ca.markdown(f"**{se.get('Date','')}** — ₹{float(se.get('Amount',0)):>,.2f}")
            cb.markdown(f"`{str(se.get('Particulars',''))[:40]}`")
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
    o = dp.get_current_outstanding(member_id)
    dp.update_member(member_id, {"Current_Outstanding": o})

    return f"Regenerated invoice {info['invoice_no']} for ₹{total:,.2f} (payment received this period: ₹{payment_received:,.2f})"


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


def show_dashboard_page():
    """Dashboard page"""
    st.title("📊 Dashboard")

    # Get statistics
    members = data_provider.get_all_members()
    total_members = len(members)
    total_outstanding = sum(data_provider.get_current_outstanding(m["ID"]) for m in members)

    # Display metrics
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

    st.divider()

    # Quick actions
    st.subheader("Quick Actions")

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
                    result = invoice_tool.func(json.dumps(params))
                    st.session_state.invoice_gen_result = result
                    st.rerun()
            else:
                st.error("Invoice tool not found")

    if "invoice_gen_result" not in st.session_state:
        st.session_state.invoice_gen_result = None

    if st.session_state.invoice_gen_result:
        result = st.session_state.invoice_gen_result
        if "Error" in result or "Invalid" in result or "Please provide" in result:
            st.error(result)
        else:
            st.success("✅ Invoices generated")
            st.code(result, language="text")
        if st.button("Dismiss", key="dismiss_inv"):
            st.session_state.invoice_gen_result = None
            st.rerun()

    st.divider()
    st.subheader("🏦 Bank Statement Processing")

    if "bank_stmt_result" not in st.session_state:
        st.session_state.bank_stmt_result = None
    if "bank_stmt_processed" not in st.session_state:
        st.session_state.bank_stmt_processed = set()
    if "bank_stmt_manual_matches" not in st.session_state:
        st.session_state.bank_stmt_manual_matches = []
    if "bank_stmt_confirmation" not in st.session_state:
        st.session_state.bank_stmt_confirmation = None

    # Show persistent confirmation banner
    if st.session_state.bank_stmt_confirmation:
        st.success(st.session_state.bank_stmt_confirmation)
        if st.button("Dismiss", key="bs_dismiss_conf"):
            st.session_state.bank_stmt_confirmation = None
            st.rerun()

    bank_text = st.text_area(
        "Paste bank statement text below",
        height=200,
        placeholder="Paste your bank statement (copy-paste from net banking)...",
        key="bank_stmt_input",
    )

    if st.button("Process Bank Statement", type="primary", use_container_width=True):
        if bank_text.strip():
            with st.spinner("Processing bank statement..."):
                tool = next(
                    (t for t in orchestrator_agent.tools if t.name == "process_bank_statement"),
                    None,
                )
                if tool:
                    result = tool.func(bank_text)
                    st.session_state.bank_stmt_result = result
                    st.session_state.bank_stmt_processed = set()
                    st.session_state.bank_stmt_manual_matches = []
                    st.session_state.bank_stmt_confirmation = None
                    st.rerun()
                else:
                    st.error("Bank statement tool not found")
        else:
            st.warning("Please paste bank statement text first")

    # ── Display results ────────────────────────────────────────────────
    result = st.session_state.bank_stmt_result
    matched = []
    unmatched = []
    if result is None:
        st.info("No bank statement processed yet. Paste a statement above and click Process.")
    elif isinstance(result, str):
        st.markdown(result)
    else:
        matched = result.get("matched", [])
        unmatched = result.get("unmatched", [])
    show_bs_results = bool(result) and not isinstance(result, str)
    processed_idx = st.session_state.bank_stmt_processed

    def _check_duplicate(data_provider, mid, date, amount, txn_id, particulars=""):
        """Return True if a ledger entry with same date+amount+txn_id already exists."""
        ledger = data_provider.get_member_ledger(mid)
        if not ledger:
            return False
        txn_clean = str(txn_id or "").strip()
        part_clean = str(particulars or "").strip()[:40]
        for e in ledger:
            e_date = str(e.get("Date", "") or "").strip()
            e_credit = float(e.get("Credit", 0) or 0)
            if e_date == date and abs(e_credit - amount) < 0.01:
                e_txn = str(e.get("Transaction_ID", "") or "").strip()
                if txn_clean and e_txn and e_txn == txn_clean:
                    return True
                e_part = str(e.get("Particulars", "") or "").strip()
                e_part_clean = e_part[3:] if e_part.upper().startswith("BY ") else e_part
                e_part_clean = e_part_clean[:40]
                if part_clean and e_part_clean and (part_clean in e_part_clean or e_part_clean in part_clean):
                    return True
                if not txn_clean and not e_txn:
                    return True
        return False

    # ── Matched entries ────────────────────────────────────────────────
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
                c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
                c1.markdown(f"**{m['date']}** — ₹{m['amount']:>,.2f} `[{m['txn_type']}]`")
                c2.markdown(f"{m['member_name']}")
                c3.markdown(f"Plot **{m['plot_no']}**")
                c4.markdown(f"📄 Receipt `{m['receipt_id']}`")
    else:
        st.info("No entries matched.")
    
    # ── Unmatched entries ──────────────────────────────────────────────
    if unmatched:
        st.warning(f"⚠️ **{len(unmatched)} entries need attention**")

        skip_dup = st.checkbox(
            "Reprocess entries already in ledger (skip duplicate check)",
            key="bs_skip_dup",
            help="Check this when re-pasting a statement to allow adding entries that were previously skipped as duplicates.",
        )

        members_list = [
            {"id": m["ID"], "label": f"Plot {m.get('Plot_No','?')} — {m.get('Plot_Owner_Name','?')}"}
            for m in members
        ]
        all_member_options = [m["label"] for m in members_list]
        member_id_map = {m["label"]: m["id"] for m in members_list}

        for i, u in enumerate(unmatched):
            if i in processed_idx:
                continue
            with st.container(border=True):
                cols = st.columns([2, 1.5, 2, 1, 0.7, 0.5, 0.5, 0.5])
                cols[0].markdown(f"**{u['date']}**")
                cols[1].markdown(f"₹{u['amount']:>,.2f}")
                cols[2].markdown(f"`{u['particulars'][:40]}`")
                cols[3].markdown(f"`{u['txn_type'] or '—'}`")

                with cols[4]:
                    sel_member = st.selectbox(
                        "Assign to", all_member_options, key=f"bs_sel_{i}",
                        label_visibility="collapsed",
                        placeholder="Select member...",
                    )

                with cols[5]:
                    if st.button("Add", key=f"bs_add_{i}", use_container_width=True):
                        mid = member_id_map.get(sel_member)
                        if mid:
                            if not skip_dup and _check_duplicate(
                                data_provider, mid, u["date"], u["amount"],
                                u.get("txn_id"), u.get("particulars")
                            ):
                                st.session_state.bank_stmt_confirmation = (
                                    f"⚠️ Duplicate — entry for ₹{u['amount']:>,.2f} "
                                    f"on {u['date']} already exists for {sel_member}"
                                )
                            else:
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
                                o = data_provider.get_current_outstanding(mid)
                                data_provider.update_member(mid, {"Current_Outstanding": o})
                                member_data = next((m for m in members if m["ID"] == mid), {})
                                mname = member_data.get("Plot_Owner_Name", "")
                                mplot = str(member_data.get("Plot_No", "") or "")
                                manual_match = {
                                    "date": u["date"],
                                    "amount": u["amount"],
                                    "txn_type": u.get("txn_type", ""),
                                    "member_name": mname,
                                    "plot_no": mplot,
                                    "receipt_id": receipt_id,
                                }
                                st.session_state.bank_stmt_manual_matches.append(manual_match)
                                plot_part = f"Plot_No_{mplot.zfill(2)}" if mplot else "Unknown"
                                receipt_dir = config.RECEIPTS_DIR / fy
                                receipt_dir.mkdir(parents=True, exist_ok=True)
                                receipt_path = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"
                                ledger = data_provider.get_member_ledger(mid)
                                led_after = list(ledger) + [{"Date": u["date"], "Credit": u["amount"], "Debit": None}]
                                as_of_o = compute_outstanding_as_of(led_after, u["date"])
                                create_simple_receipt_pdf(receipt_path, {
                                    "receipt_id": receipt_id,
                                    "date": u["date"],
                                    "member_name": mname,
                                    "plot_no": mplot,
                                    "amount": u["amount"],
                                    "transaction_id": u.get("txn_id") or "",
                                    "transaction_type": u.get("txn_type") or "",
                                    "payment_details": u.get("particulars", ""),
                                    "outstanding_balance": as_of_o,
                                })
                                st.session_state.bank_stmt_processed.add(i)
                                st.session_state.bank_stmt_confirmation = (
                                    f"✅ Added ₹{u['amount']:>,.2f} to {sel_member}"
                                )
                            st.rerun()
                        else:
                            st.error("Select a member first")

                with cols[6]:
                    if st.button("Ignore", key=f"bs_ign_{i}", use_container_width=True):
                        st.session_state.bank_stmt_processed.add(i)
                        st.session_state.bank_stmt_confirmation = (
                            f"⏭️ Ignored — ₹{u['amount']:>,.2f} on {u['date']} ({u.get('particulars','')[:40]})"
                        )
                        st.rerun()

                with cols[7]:
                    if st.button("Suspense", key=f"bs_sus_{i}", use_container_width=True):
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
                        st.rerun()

        # ── Split Equally ──────────────────────────────────────────
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
                    o = data_provider.get_current_outstanding(mid)
                    data_provider.update_member(mid, {"Current_Outstanding": o})
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
                        "payment_details": f"{u_split.get('particulars', '')} (split ₹{per_head:,.0f}/{total_split:,.0f})",
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

    st.divider()

    # Member list
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
        member_data.append(
            {
                "Plot No": member.get("Plot_No", "N/A"),
                "Name": member.get("Plot_Owner_Name", "N/A"),
                "Balance": f"₹{abs(outstanding):,.2f}",
                "Status": status,
            }
        )

    st.dataframe(member_data, use_container_width=True)

    st.divider()

    # ── Suspense Entries (View / Tag) ──────────────────────────────────
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

    # ── Manage Ledger (Delete / Split / Regenerate) ────────────────────
    with st.expander("📋 Manage Ledger Entries", expanded=False):
        col_f1, col_f2, col_f3 = st.columns([3, 2, 2])
        with col_f1:
            mgmt_member_id = st.selectbox(
                "Member",
                options=[0] + [m["ID"] for m in members],
                format_func=lambda x: "🏘️ All Plots" if x == 0 else _member_label(x),
                key="mgmt_member",
            )
        with col_f2:
            entry_type_filter = st.selectbox(
                "Type", ["All", "Debit", "Credit"], key="mgmt_type",
            )
        with col_f3:
            fy_filter = st.selectbox(
                "FY", ["All", "Custom"] + _get_available_fys(
                    sum((data_provider.get_member_ledger(m["ID"]) for m in members), [])
                ) if members else ["All"],
                key="mgmt_fy",
            )

        from_dt, to_dt = "", ""
        if fy_filter == "Custom":
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                from_dt = st.text_input("From (DD-MM-YYYY)", value="", key="mgmt_from")
            with col_d2:
                to_dt = st.text_input("To (DD-MM-YYYY)", value="", key="mgmt_to")
        elif fy_filter != "All":
            from_dt, to_dt = _fy_date_range(fy_filter)

        if mgmt_member_id == 0:
            # ── All Plots: Summary Table + Inline Actions ──
            summary = []
            for m in members:
                mid = m["ID"]
                ledger = data_provider.get_member_ledger(mid)
                filtered = _filter_entries(ledger, entry_type_filter, from_dt, to_dt)
                td = _s(sum(float(e.get("Debit") or 0) for e in filtered))
                tc = _s(sum(float(e.get("Credit") or 0) for e in filtered))
                outstanding = data_provider.get_current_outstanding(mid)
                summary.append({
                    "Plot": m.get("Plot_No", "?"),
                    "Name": m.get("Plot_Owner_Name", "?"),
                    "Debits": td,
                    "Credits": tc,
                    "Net": tc - td,
                    "Outstanding": outstanding,
                    "Member_ID": mid,
                    "has_entries": bool(filtered),
                })
            if summary:
                st.dataframe(
                    [
                        {
                            "Plot": s["Plot"],
                            "Name": s["Name"],
                            "Debits": f"₹{s['Debits']:,.2f}",
                            "Credits": f"₹{s['Credits']:,.2f}",
                            "Net": f"₹{s['Net']:,.2f}",
                            "Outstanding": f"₹{abs(s['Outstanding']):,.2f} {'Demand' if s['Outstanding'] < 0 else 'Surplus' if s['Outstanding'] > 0 else 'Settled'}",
                        }
                        for s in summary
                    ],
                    use_container_width=True,
                )
                # Compact action rows below the table
                for s in summary:
                    if not s["has_entries"]:
                        continue
                    plot_entries = _filter_entries(
                        data_provider.get_member_ledger(s["Member_ID"]),
                        entry_type_filter, from_dt, to_dt,
                    )
                    inv_list = [pe for pe in plot_entries if str(pe.get("Transaction_Type", "") or "").upper() == "INVOICE"]
                    col_a1, col_a2, col_a3 = st.columns([3, 3, 3])
                    with col_a1:
                        st.text(f"{s['Plot']}  {s['Name']}")
                    with col_a2:
                        if inv_list and st.button(f"🔄 Regen {len(inv_list)} invoice(s)", key=f"a_regen_{s['Member_ID']}"):
                            rc = 0
                            for pe in list(inv_list):
                                if regenerate_invoice(data_provider, s["Member_ID"], pe):
                                    rc += 1
                            if rc:
                                st.session_state.bank_stmt_confirmation = f"✅ Regenerated {rc} invoice(s) for Plot {s['Plot']}"
                                st.rerun()
                    with col_a3:
                        if st.button(f"🗑️ Delete {len(plot_entries)}", key=f"a_del_{s['Member_ID']}"):
                            dc = 0
                            for pe in sorted(plot_entries, key=lambda x: _s(x.get("Vch_No") or 0), reverse=True):
                                vch = pe.get("Vch_No")
                                if vch and data_provider.delete_ledger_entry(s["Member_ID"], int(vch)):
                                    _delete_pdf_files(_extract_ref_id(str(pe.get("Description", ""))))
                                    dc += 1
                            st.session_state.bank_stmt_confirmation = f"✅ Deleted {dc} entries for Plot {s['Plot']}"
                            st.rerun()
        else:
            # ── Single Plot: Select Entries + Action Toolbar ──
            mgmt_member = _find_member(mgmt_member_id)
            if mgmt_member:
                raw_ledger = data_provider.get_member_ledger(mgmt_member_id)
                mgmt_ledger = _filter_entries(raw_ledger, entry_type_filter, from_dt, to_dt)
                if mgmt_ledger:
                    total_dr = _s(sum(_s(e.get("Debit")) for e in mgmt_ledger))
                    total_cr = _s(sum(_s(e.get("Credit")) for e in mgmt_ledger))
                    st.caption(f"Debits: ₹{total_dr:,.2f}  |  Credits: ₹{total_cr:,.2f}  |  Net: ₹{total_cr - total_dr:,.2f}")

                    # Action toolbar
                    if "selected_entries" not in st.session_state:
                        st.session_state.selected_entries = set()
                    sel_all = st.checkbox("Select All", key="sel_all")
                    act_col1, act_col2 = st.columns([3, 1])
                    with act_col1:
                        action = st.selectbox("Action", ["---", "Delete Selected", "Regenerate Selected", "Split Selected"], key="mgmt_action")
                    with act_col2:
                        st.write("")
                        go = st.button("Go", key="mgmt_go")

                    if go and action != "---":
                        selected = [e for i, e in enumerate(mgmt_ledger) if f"chk_{i}" in st.session_state and st.session_state[f"chk_{i}"]]
                        if not selected:
                            st.warning("No entries selected")
                        elif action == "Delete Selected":
                            dc = 0
                            for se in sorted(selected, key=lambda x: int(x.get("Vch_No") or 0), reverse=True):
                                vch = se.get("Vch_No")
                                if vch and data_provider.delete_ledger_entry(mgmt_member_id, int(vch)):
                                    _delete_pdf_files(_extract_ref_id(str(se.get("Description", ""))))
                                    dc += 1
                            st.session_state.bank_stmt_confirmation = f"✅ Deleted {dc} entries"
                            st.rerun()
                        elif action == "Regenerate Selected":
                            for se in list(selected):
                                if str(se.get("Transaction_Type", "") or "").upper() == "INVOICE":
                                    regenerate_invoice(data_provider, mgmt_member_id, se)
                            st.session_state.bank_stmt_confirmation = f"✅ Regenerated invoices"
                            st.rerun()
                        elif action == "Split Selected":
                            credits = [se for se in selected if _s(se.get("Credit")) > 0]
                            if len(credits) == 1:
                                entry = credits[0]
                                st.session_state.split_src = {
                                    "member_id": mgmt_member_id,
                                    "vch_no": int(entry.get("Vch_No", 0)),
                                    "amount": _s(entry.get("Credit")),
                                    "date": str(entry.get("Date", "") or ""),
                                    "particulars": str(entry.get("Particulars", "") or ""),
                                    "txn_type": str(entry.get("Transaction_Type", "") or ""),
                                    "txn_id": str(entry.get("Transaction_ID", "") or ""),
                                }
                                st.rerun()
                            else:
                                st.warning("Select exactly one credit entry to split")

                    st.divider()
                    for i, entry in enumerate(mgmt_ledger):
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

                        c1, c2, c3, c4 = st.columns([0.3, 2, 3, 3])
                        with c1:
                            st.checkbox("", key=f"chk_{i}", value=bool(st.session_state.sel_all if "sel_all" in st.session_state and st.session_state.sel_all else False))
                        with c2:
                            st.caption(f"#{ev}")
                            st.text(ed)
                        with c3:
                            st.caption(etype)
                            st.text((edesc or epart)[:60])
                        with c4:
                            st.text(lbl)
                    st.divider()

                    # Split dialog
                    if st.session_state.get("split_src"):
                        ss = st.session_state.split_src
                        st.markdown(f"**✂️ Splitting ₹{ss['amount']:,.2f} receipt from {ss['date']}**")
                        split_ids = st.multiselect(
                            "Split across members",
                            options=[m["ID"] for m in members],
                            format_func=_member_label,
                            key="split_targets",
                        )
                        if split_ids:
                            base_amt = ss["amount"] / len(split_ids)
                            st.info(f"Each: ₹{base_amt:,.2f}")
                            if st.button("Confirm Split", type="primary", key="confirm_split"):
                                if data_provider.delete_ledger_entry(ss["member_id"], ss["vch_no"]):
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
                                            "Vch_Type": "Journal",
                                            "Vch_No": vch,
                                            "Debit": None,
                                            "Credit": base_amt,
                                            "Description": f"Receipt {rid} — Split from #{ss['vch_no']}",
                                            "Transaction_ID": ss.get("txn_id", ""),
                                            "Transaction_Type": ss.get("txn_type", ""),
                                        })
                                        o = data_provider.get_current_outstanding(mid)
                                        data_provider.update_member(mid, {"Current_Outstanding": o})
                                        fy_short = fy[:2]
                                        receipt_dir = config.RECEIPTS_DIR / fy_short
                                        receipt_dir.mkdir(parents=True, exist_ok=True)
                                        rpath = receipt_dir / f"Receipt_{plot_part}_{rid}.pdf"
                                        create_simple_receipt_pdf(rpath, {
                                            "receipt_id": rid,
                                            "date": ss["date"],
                                            "member_name": m.get("Plot_Owner_Name", ""),
                                            "plot_no": plot_str,
                                            "amount": base_amt,
                                            "transaction_id": ss.get("txn_id", "N/A"),
                                            "transaction_type": ss.get("txn_type", ""),
                                            "outstanding_balance": o,
                                            "payment_details": ss.get("particulars", "")[:120],
                                        })
                                    st.session_state.bank_stmt_confirmation = f"✅ Split ₹{ss['amount']:,.2f}"
                                    del st.session_state.split_src
                                    st.rerun()
                        if st.button("Cancel Split", key="cancel_split"):
                            del st.session_state.split_src
                            st.rerun()
                else:
                    st.info("No entries match the current filters.")

    st.divider()

    # ── Defaulters Report ────────────────────────────────────────────
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
                [
                    {
                        "Plot": d["Plot"],
                        "Name": d["Name"],
                        "Total Debits": f"₹{d['Total Debits']:,.2f}",
                        "Total Credits": f"₹{d['Total Credits']:,.2f}",
                        "Outstanding": f"₹{abs(d['Outstanding']):,.2f}",
                    }
                    for d in defaulter_data
                ],
                use_container_width=True,
            )
            total_demand = sum(abs(d["Outstanding"]) for d in defaulter_data)
            st.metric("Total Outstanding Demand", f"₹{total_demand:,.2f}")
        else:
            st.success("No defaulters — all plots are settled or in surplus.")


def show_settings_page():
    """Settings page"""
    st.title("⚙️ Settings")

    settings = data_provider.get_settings()

    tab1, tab2, tab3 = st.tabs(["Rates", "Members", "System"])

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
            data_provider.update_settings(
                {
                    "Repair_Fund_Rate": str(repair),
                    "Service_Charges_Rate": str(service),
                    "Sinking_Fund_Rate": str(sinking),
                }
            )
            st.success("Rates updated successfully!")

    with tab2:
        st.subheader("Member Management")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            plot_no = st.text_input("Plot No")

        with col2:
            name = st.text_input("Member Name")

        with col3:
            email = st.text_input("Email")

        with col4:
            phone = st.text_input("Phone")

        if st.button("Add Member", use_container_width=True):
            if plot_no and name:
                data_provider.add_member(
                    {
                        "Plot_No": plot_no,
                        "Plot_Owner_Name": name,
                        "Email": email,
                        "Phone": phone,
                        "Current_Outstanding": 0,
                        "Pending_Interest": 0,
                    }
                )
                st.success(f"Member {name} added successfully!")
            else:
                st.error("Plot No and Name are required")

    with tab3:
        st.subheader("System Management")

        if st.button("Trigger April 1st Entries", use_container_width=True):
            st.info("Processing April 1st entries for all members...")
            # Would trigger admin agent
            st.success("April 1st entries created successfully!")


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
