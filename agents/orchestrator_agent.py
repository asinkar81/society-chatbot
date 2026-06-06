"""
Orchestrator Agent — combines all agent capabilities for multi-step workflows.
The LLM plans and executes a sequence of tool calls, passing outputs between steps.
"""
import json
import re
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from agents.base_agent import BaseAgent
from data_providers.base_provider import DataProvider
from file_storage.base_storage import FileStorage
from tools.ocr_processor import OCRProcessor
from tools.pdf_generator import create_simple_receipt_pdf, create_simple_invoice_pdf, create_consolidated_receipt_pdf
from utils.converters import (
    get_current_date, get_fy_string, get_fy_from_date, get_due_date, get_bill_period,
    compute_outstanding_as_of, get_payment_history, get_previous_invoices,
    number_to_words_inr, clean_payment_details,
)
import config


def _parse_action_input(input_str: str) -> dict:
    """Parse a tool action input string into a dict.
    Handles JSON, key=value pairs, and comma-separated positionals.
    Positional values get keys _0, _1, etc.
    """
    input_str = input_str.strip().strip('"\'')
    if not input_str:
        return {}
    if input_str.startswith("{"):
        try:
            return json.loads(input_str)
        except json.JSONDecodeError:
            pass
    result = {}
    kvs = re.findall(r'(\w+)\s*=\s*([^,]+)', input_str)
    if kvs:
        for k, v in kvs:
            result[k] = v.strip().strip('"\'')
        return result
    parts = [p.strip().strip('"\'') for p in input_str.split(",")]
    for i, p in enumerate(parts):
        result[f"_{i}"] = p
    return result


def _normalize_plot_id(identifier: str) -> str:
    """Strip common plot prefixes and normalize."""
    raw = identifier.lower().strip()
    raw = re.sub(r'^plot[\s_]*', '', raw)
    raw = re.sub(r'^(no|number|#)[\s_]*', '', raw)
    raw = raw.strip().lstrip('0')
    return raw or identifier.strip()


def _check_duplicate_payment(ledger: list, transaction_id: str, date: str, amount: float) -> dict:
    """Check if a payment with same transaction_id + date + amount already exists in the ledger.
    Returns the matching entry dict if found, or None if no duplicate."""
    if not transaction_id:
        return None
    txn_clean = str(transaction_id).strip()
    for entry in ledger:
        existing_txn = str(entry.get("Transaction_ID", "") or "").strip()
        if not existing_txn:
            continue
        if existing_txn != txn_clean:
            continue
        existing_date = str(entry.get("Date", "") or "").strip()
        if existing_date != str(date).strip():
            continue
        existing_credit = _safe_float(entry.get("Credit"))
        if abs(existing_credit - amount) > 0.01:
            continue
        return entry
    return None


def _check_duplicate_expense(expenses: list, date: str, amount: float, particulars: str) -> dict:
    """Check if an expense with same date + amount + particulars prefix already exists.
    Returns the matching entry dict if found, or None if no duplicate."""
    part_clean = str(particulars or "").strip().upper()[:40]
    if not part_clean:
        return None
    for e in expenses:
        e_date = str(e.get("Date", "") or "").strip()
        e_amount = _safe_float(e.get("Amount"))
        if e_date == str(date).strip() and abs(e_amount - amount) < 0.01:
            e_part = str(e.get("Particulars", "") or "").strip().upper()[:40]
            if part_clean in e_part or e_part in part_clean:
                return e
    return None


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        v = float(val)
        return 0.0 if v != v else v
    except (ValueError, TypeError):
        return 0.0


def _extract_ref_id(desc: str) -> Optional[str]:
    """Extract a reference/receipt ID from a description string like RCPT-2025-001."""
    if not desc or not isinstance(desc, str):
        return None
    m = re.search(r'(?:RCPT|RC|RECEIPT)[-\s]*(\d{4}-\d+|\d+)', desc, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'(\d{4}-\d{3,})', desc)
    if m:
        return m.group(1)
    return None


def _delete_pdf_files(ref_id: Optional[str]) -> None:
    """Delete all PDF files matching a given ref_id in the receipts directory."""
    if not ref_id:
        return
    for fy_dir in config.RECEIPTS_DIR.iterdir():
        if fy_dir.is_dir():
            for pdf in fy_dir.glob(f"*{ref_id}*.pdf"):
                try:
                    pdf.unlink()
                except OSError:
                    pass


def _fy_date_range(fy: str) -> tuple[str, str]:
    """Convert FY string like '24-25' or '2025-26' to (from_date, to_date)."""
    try:
        parts = fy.split("-")
        if len(parts) != 2:
            return ("", "")
        start_yr = int(parts[0])
        if start_yr < 100:
            start_yr += 2000
        return (f"01-04-{start_yr}", f"31-03-{start_yr + 1}")
    except Exception:
        return ("", "")


def _find_members_by_name(members: list, name: str) -> list:
    """Find members by fuzzy token matching against Plot_Owner_Name.
    Returns list of matching member dicts, sorted by relevance."""
    import re
    TITLES = {"mr", "mrs", "ms", "miss", "dr", "smt", "shri"}
    def tokens(n):
        return [t.strip().lower() for t in re.split(r'[&\s/]+', n)
                if t.strip() and t.strip().lower() not in TITLES]
    query_tokens = tokens(name)
    if not query_tokens:
        return []
    scored = []
    for m in members:
        name_tokens = tokens(m.get("Plot_Owner_Name", ""))
        if not name_tokens:
            continue
        matches = sum(1 for qt in query_tokens
                      if any(qt in nt or nt in qt for nt in name_tokens))
        score = matches / len(query_tokens)
        if score >= 0.5:
            scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored]


ORCHESTRATOR_SYSTEM_PROMPT = """You are the Society Management Orchestrator Agent. You handle ALL society tasks (member lookup, payments, receipts, ledgers, invoices, bank statement processing, admin).

IMPORTANT RULES:
1. ALWAYS call get_member_details FIRST to resolve a plot number or name to a member_id.
2. For invoices, ALWAYS ask the user for from_date and to_date if not provided. Calculate months from the date range.
3. For bank statements: ALWAYS use the process_bank_statement_pdf tool.
   The PDF has already been uploaded, parsed, and its entries cleaned by the UI.
   Your job is to match the cleaned entries to members and generate receipts.
   Do NOT ask the user to paste text or upload — the entries are passed to you directly.
4. When the user says "force" or "ignore duplicate" for a payment, pass force=true to generate_receipt.
5. To modify an existing ledger entry (change amount, particulars, etc.), use update_ledger_entry.
   To delete ANY ledger entry (receipt, invoice, or demand), use delete_ledger_entry.
6. For splitting an entry across two members who share ownership:
   a) Use get_member_ledger to view entries with their Vch_No and Transaction_ID.
   b) Match entries by Transaction_ID to identify existing splits.
   c) For non-split entries: use update_ledger_entry to reduce the original credit/debit, then call add_ledger_entry or generate_receipt to create the matching entry for the other member.
   d) Outstanding balances are auto-updated at each step — no manual recalculation needed.
7. For manual/cash entries that don't need a PDF document, use add_ledger_entry.
   Set entry_type="CREDIT" for payments received, entry_type="DEBIT" for charges/expenses.
   Use generate_receipt instead only when the user asks for a receipt PDF or when the entry comes from a bank statement.
   For BATCH processing of a LIST of payments (e.g. "these 14 people paid for Shivaji's salary"),
   use record_manual_payments instead — it handles member resolution, multi-plot
   splitting across listed plots, and duplicate detection in one call.
8. When looking up by name, get_member_details returns ALL members with matching names.
   If two members share the same name (different plot numbers), they are the same person
   owning multiple plots.
9. For multi-plot payments (e.g. "Plot 38 & 38 paid ₹2000"):
   Split the amount EQUALLY across each plot's member entry.
   In the particulars field, record the total amount and plot range
   (e.g. 'Shivaji salary contribution — ₹2000 (Plot 38 & 39)').
   If unclear about how to split, ask the user.

MEMBER MATCHING:
- The process_bank_statement_pdf tool handles member matching internally (surname, name tokens, email, phone, known identifiers).
- The system maintains a Payment Reference Store that learns known UPI IDs, mobile numbers, emails,
  and payee names from each processed payment. This makes future matches more accurate.
- When the process_bank_statement_pdf tool returns unmatched entries, ask the user to specify the plot number
  for each, then call generate_receipt with member_id, amount, date, and transaction_id.
"""


class OrchestratorAgent(BaseAgent):
    """Agent that can handle multi-step workflows by combining all tool capabilities."""

    def __init__(self, data_provider: DataProvider, file_storage: FileStorage):
        super().__init__(
            name="Orchestrator Agent",
            description="Handles all society management tasks including multi-step workflows",
            data_provider=data_provider,
            file_storage=file_storage,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        )
        self.ocr_processor = OCRProcessor()
        self.get_tools()

    def get_tools(self):
        """Register all tools for the orchestrator."""

        # ── Member tools ──────────────────────────────────────────────

        def get_member_details(input_str: str = None):
            """Get member details by ID, Plot No, or name. Use this FIRST to resolve a plot number or name to a member_id before calling other tools. Input: plot_no, member_id, or name. Name lookup returns ALL matching members (useful for multi-plot owners)."""
            data = _parse_action_input(input_str or "")
            identifier = (str(data.get("member_id") or "") or
                          str(data.get("plot_no") or "") or
                          str(data.get("plot") or "") or
                          str(data.get("_0") or "") or
                          (input_str or ""))
            if not identifier:
                return "Please provide a member ID, plot number, or name"
            raw = _normalize_plot_id(identifier)
            try:
                member = self.data_provider.get_member(int(raw))
                if not member:
                    member = self.data_provider.get_member_by_plot_no(raw)
            except ValueError:
                member = self.data_provider.get_member_by_plot_no(raw)
            if member:
                o = self.data_provider.get_current_outstanding(member["ID"])
                return json.dumps({
                    "member_id": member["ID"],
                    "name": member.get("Plot_Owner_Name"),
                    "plot_no": member.get("Plot_No"),
                    "outstanding": o,
                })
            # Name fallback: search all members for partial name match
            members = self.data_provider.get_all_members()
            query = identifier.lower().strip()
            matches = [m for m in members if query in m.get("Plot_Owner_Name", "").lower()]
            if matches:
                return json.dumps([{
                    "member_id": m["ID"],
                    "plot_no": m.get("Plot_No"),
                    "name": m.get("Plot_Owner_Name"),
                } for m in matches], indent=2)
            return f"Member not found for: {identifier}"

        # ── Payment / Receipt tools ───────────────────────────────────

        def extract_payment_from_screenshot(image_path: str):
            """Extract payment details (amount, date, transaction_id) from a payment screenshot using vision AI. Input: file path to the image."""
            result = self.ocr_processor.extract_payment_details(Path(image_path))
            return json.dumps(result) if not isinstance(result, str) else result

        def batch_process_historical_receipts(input_str: str = None):
            """Process ALL historical receipt images from a folder. For each image: run OCR, generate receipt PDF, and update the ledger. Input JSON keys: folder_path (default: config.HISTORICAL_RECEIPTS_DIR), default_plot_no (optional, used if filename has no plot number). Returns a summary of all processed receipts."""
            data = _parse_action_input(input_str or "")
            folder = data.get("folder_path") or data.get("folder") or data.get("_0") or ""
            default_plot = data.get("default_plot_no") or data.get("default_plot") or ""

            if not folder:
                folder = str(config.DATA_DIR / "Historical_Receipts")
            folder_path = Path(folder)
            if not folder_path.is_dir():
                return f"Folder not found: {folder}"

            image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
            images = sorted(f for f in folder_path.iterdir() if f.suffix.lower() in image_exts)
            if not images:
                return f"No image files found in {folder}"

            results = []
            for img_path in images:
                try:
                    # Try to extract plot_no from filename
                    stem = img_path.stem
                    plot_no = default_plot
                    if not plot_no:
                        m = re.search(r'(?:plot[_\s]*)?(\d{1,3})', stem, re.IGNORECASE)
                        if m:
                            plot_no = m.group(1)
                            # Verify it's a valid member (optional — agent can override later)

                    # Extract payment details via OCR
                    payment = self.ocr_processor.extract_payment_details(img_path)
                    if "error" in payment:
                        results.append(f"  ✗ {img_path.name}: OCR failed — {payment['error']}")
                        continue

                    amount = payment.get("amount")
                    date = payment.get("date") or get_current_date()
                    txn_id = payment.get("transaction_id") or ""

                    # Try to identify member
                    member = None
                    if plot_no:
                        member = self.data_provider.get_member_by_plot_no(plot_no)
                    if not member:
                        results.append(f"  ? {img_path.name}: ₹{amount} extracted but no member found for plot '{plot_no or 'unknown'}'. Skipping ledger update.")
                        continue

                    member_id = member["ID"]
                    fy = get_fy_from_date(date)
                    vch_no = self.data_provider.get_next_voucher_number()
                    receipt_id = f"{fy}-{str(vch_no).zfill(3)}"

                    # Detect transaction type from OCR if available, or from filename
                    txn_type = payment.get("transaction_type", "").upper() if isinstance(payment, dict) else ""
                    if not txn_type:
                        if "neft" in img_path.name.lower():
                            txn_type = "NEFT"
                        elif "upi" in img_path.name.lower():
                            txn_type = "UPI"
                        elif "imps" in img_path.name.lower():
                            txn_type = "IMPS"
                        elif "chq" in img_path.name.lower() or "cheque" in img_path.name.lower():
                            txn_type = "CHQ"

                    ledger = self.data_provider.get_member_ledger(member_id)
                    led_after = list(ledger) + [{"Date": date, "Credit": amount, "Debit": None}]
                    as_of_outstanding = compute_outstanding_as_of(led_after, date)
                    receipt_data = {
                        "receipt_id": receipt_id,
                        "date": date,
                        "member_name": member.get("Plot_Owner_Name", ""),
                        "plot_no": member.get("Plot_No", ""),
                        "amount": amount,
                        "transaction_id": txn_id or "N/A",
                        "transaction_type": txn_type,
                        "outstanding_balance": as_of_outstanding,
                    }
                    receipt_dir = config.RECEIPTS_DIR / fy
                    receipt_dir.mkdir(parents=True, exist_ok=True)
                    plot_str = str(member.get("Plot_No", "") or "")
                    plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
                    rpath = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"
                    create_simple_receipt_pdf(rpath, receipt_data)

                    # Duplicate detection before ledger update
                    if txn_id:
                        existing_ledger = self.data_provider.get_member_ledger(member_id)
                        dup = _check_duplicate_payment(existing_ledger, txn_id, date, amount)
                        if dup:
                            results.append(
                                f"  ⚠️ {img_path.name}: ₹{amount} — DUPLICATE (txn {txn_id} on {date} "
                                f"already recorded for {member.get('Plot_Owner_Name')}). "
                                f"Receipt PDF generated but ledger NOT updated."
                            )
                            continue

                    self.data_provider.add_ledger_entry(member_id, {
                        "Date": date,
                        "Particulars": "By Payment Received (Historical)",
                        "Vch_Type": "Journal",
                        "Vch_No": vch_no,
                        "Debit": None,
                        "Credit": amount,
                        "Description": f"Receipt {receipt_id} — Historical",
                        "Transaction_ID": txn_id or None,
                        "Transaction_Type": txn_type,
                    })
                    # Record identifiers for future matching
                    from tools.pdf_parser import _extract_search_tokens
                    _, identifiers = _extract_search_tokens(str(txn_id or ""), txn_type)
                    for id_value, id_type in identifiers:
                        self.data_provider.record_payment_reference(member_id, id_type, id_value, date, transaction_type=txn_type)

                except Exception as e:
                    results.append(f"  ✗ {img_path.name}: Error — {str(e)}")

            summary = f"Processed {len(images)} images:\n" + "\n".join(results)
            succeed = sum(1 for r in results if r.startswith("  ✓"))
            skipped = sum(1 for r in results if r.startswith("  ?"))
            dupes = sum(1 for r in results if "DUPLICATE" in r)
            failed = sum(1 for r in results if r.startswith("  ✗"))
            summary += f"\n\nSummary: {succeed} added, {dupes} duplicates skipped, {skipped} skipped (no member match), {failed} failed"
            return summary

        def generate_receipt(input_str: str = None):
            """Generate a receipt PDF and update the ledger. Input JSON keys: member_id (or plot_no), amount, date, transaction_id (optional), transaction_type (optional — NEFT/UPI/CHQ/IMPS/CASH), payment_details (optional — text for identifier recording), force (optional bool to bypass duplicate check). Example: {"member_id": 2, "amount": 3000, "date": "05-05-2026", "transaction_id": "UPI123", "transaction_type": "UPI"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            amount = data.get("amount")
            date = data.get("date")
            transaction_id = data.get("transaction_id")
            transaction_type = data.get("transaction_type") or data.get("txn_type") or ""
            payment_details = data.get("payment_details") or ""
            force = data.get("force", False)

            if not member_id:
                plot_no = _normalize_plot_id(str(data.get("plot_no") or data.get("plot")
                           or data.get("_0") or ""))
                if plot_no:
                    member = self.data_provider.get_member_by_plot_no(plot_no)
                    member_id = member.get("ID") if member else None
                if not member_id:
                    return "Please provide a member_id or plot_no"
            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return f"Invalid member_id: {member_id}"

            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return f"Invalid amount: {amount}"

            if not date:
                date = get_current_date()

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            # Duplicate detection
            if transaction_id and not force:
                ledger = self.data_provider.get_member_ledger(member_id)
                dup = _check_duplicate_payment(ledger, transaction_id, date, amount)
                if dup:
                    return (
                        f"⚠️ DUPLICATE: A payment with transaction_id '{transaction_id}' "
                        f"on {date} for ₹{amount:,.2f} is already recorded for "
                        f"{member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}).\n\n"
                        f"If this is intentional and should be processed regardless, "
                        f"re-run with 'force': true to bypass the duplicate check."
                    )

            fy = get_fy_from_date(date)
            vch_no = self.data_provider.get_next_voucher_number()
            receipt_id = f"{fy}-{str(vch_no).zfill(3)}"

            current_outstanding = self.data_provider.get_current_outstanding(member_id)
            new_outstanding = current_outstanding + amount

            receipt_data = {
                "receipt_id": receipt_id,
                "date": date,
                "member_name": member.get("Plot_Owner_Name", "Unknown"),
                "plot_no": member.get("Plot_No", "N/A"),
                "amount": amount,
                "transaction_id": transaction_id or "N/A",
                "transaction_type": transaction_type.upper() if transaction_type else "",
                "payment_details": str(payment_details or "")[:120],
                "outstanding_balance": new_outstanding,
            }

            receipt_dir = config.RECEIPTS_DIR / fy
            receipt_dir.mkdir(parents=True, exist_ok=True)
            plot_str = str(member.get("Plot_No", "") or "")
            plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
            receipt_path = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"

            success = create_simple_receipt_pdf(receipt_path, receipt_data)
            if not success:
                return f"Failed to generate receipt PDF for member {member_id}"

            ledger_entry = {
                "Date": date,
                "Particulars": f"By {str(payment_details or 'Payment Received')[:60]}",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": None,
                "Credit": amount,
                "Description": f"Receipt {receipt_id}",
                "Transaction_ID": transaction_id or None,
                "Transaction_Type": transaction_type.upper() if transaction_type else "",
            }
            self.data_provider.add_ledger_entry(member_id, ledger_entry)

            # Record identifiers from payment_details
            if payment_details:
                from tools.pdf_parser import _extract_search_tokens
                _, identifiers = _extract_search_tokens(str(payment_details), transaction_type, transaction_id)
                if not identifiers:
                    STOP_WORDS = {"MR", "MRS", "MS", "SHRI", "SMT", "DR", "SRI", "M/S", "CMN",
                                  "PAY", "AND", "THE", "FROM", "B", "PAYMENT", "RECEIVED",
                                  "TRANSFER", "NEFT", "RTGS", "IMPS", "CHQ", "CHEQUE",
                                  "BANK", "REFERENCE", "CREDIT", "DEBIT", "BY", "TO", "VIA"}
                    for t in re.split(r'[\s/]+', str(payment_details)):
                        t_clean = t.strip().upper()
                        if (len(t_clean) > 2 and t_clean not in STOP_WORDS
                            and not t_clean.isdigit()
                            and not (t_clean.isalpha() and t_clean.isupper() and len(t_clean) <= 4)
                            and not re.match(r'^[\d,]+\.\d{2}$', t_clean)):
                            identifiers.append((t_clean, "PAYEE_NAME"))
                for id_value, id_type in identifiers:
                    self.data_provider.record_payment_reference(member_id, id_type, id_value, date, transaction_type=transaction_type)

            return f"Receipt {receipt_id} generated for {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}) for ₹{amount:,.2f}. Ledger updated."

        def regenerate_receipt(input_str: str = None):
            """Regenerate a receipt PDF from an existing ledger entry. Input JSON keys: member_id, vch_no, new_member_id (optional for move). Example: {"member_id": 2, "vch_no": 15}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            vch_no = data.get("vch_no")
            new_member_id = data.get("new_member_id")

            if not member_id or not vch_no:
                return "member_id and vch_no are required"

            try:
                member_id = int(member_id)
                vch_no = int(vch_no)
                if new_member_id:
                    new_member_id = int(new_member_id)
            except (ValueError, TypeError):
                return "member_id and vch_no must be integers"

            ledger = self.data_provider.get_member_ledger(member_id)
            entry = next((e for e in ledger if int(e.get("Vch_No", 0)) == vch_no), None)
            if not entry:
                return f"Entry with Vch_No {vch_no} not found for member {member_id}"

            date = str(entry.get("Date", "") or "")
            amount = _safe_float(entry.get("Credit")) or _safe_float(entry.get("Debit"))
            particulars = str(entry.get("Particulars", "") or "")
            description = str(entry.get("Description", "") or "")
            txn_id = str(entry.get("Transaction_ID", "") or "")
            txn_type = str(entry.get("Transaction_Type", "") or "")
            receipt_id = _extract_ref_id(description)
            if not receipt_id:
                receipt_id = f"{get_fy_from_date(date)}-{str(vch_no).zfill(3)}"

            # Handle Move: delete from old member, re-add to new member
            if new_member_id and new_member_id != member_id:
                if not self.data_provider.delete_ledger_entry(member_id, vch_no):
                    return f"Failed to delete entry from member {member_id}"
                self.data_provider.add_ledger_entry(new_member_id, {
                    "Date": date,
                    "Particulars": particulars,
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": _safe_float(entry.get("Debit")) or None,
                    "Credit": _safe_float(entry.get("Credit")) or None,
                    "Description": description,
                    "Transaction_ID": txn_id or None,
                    "Transaction_Type": txn_type,
                })
                target_member = self.data_provider.get_member(new_member_id)
                member_id = new_member_id
            else:
                target_member = self.data_provider.get_member(member_id)

            if not target_member:
                return "Target member not found"

            fy = get_fy_from_date(date)
            plot_str = str(target_member.get("Plot_No", "") or "")
            plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"

            # Delete old PDF
            _delete_pdf_files(receipt_id)

            # Generate new receipt
            receipt_dir = config.RECEIPTS_DIR / fy
            receipt_dir.mkdir(parents=True, exist_ok=True)
            rpath = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"
            outstanding = self.data_provider.get_current_outstanding(member_id)
            receipt_data = {
                "receipt_id": receipt_id,
                "date": date,
                "member_name": target_member.get("Plot_Owner_Name", ""),
                "plot_no": plot_str,
                "amount": amount,
                "transaction_id": txn_id or "N/A",
                "transaction_type": txn_type,
                "payment_details": clean_payment_details(particulars)[:120],
            }
            create_simple_receipt_pdf(rpath, receipt_data)

            return f"✅ Receipt {receipt_id} regenerated for {target_member.get('Plot_Owner_Name')} (Plot {plot_str})"

        def generate_consolidated_receipt(input_str: str = None):
            """Generate a consolidated receipt PDF listing all receipts for a member in a given FY. Input JSON: member_id, fy (optional). Example: {"member_id": 2, "fy": "25-26"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            fy = data.get("fy", "")

            if not member_id:
                return "member_id is required"

            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return "member_id must be an integer"

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            ledger = self.data_provider.get_member_ledger(member_id)
            credit_entries = [e for e in ledger if _safe_float(e.get("Credit")) > 0]

            if fy:
                from_date, to_date = _fy_date_range(fy)
                credit_entries = [e for e in credit_entries
                                  if from_date <= str(e.get("Date", "")) <= to_date]

            if not credit_entries:
                return "No credit entries found for this member in the given period"

            # Pick best FY from entries
            if not fy and credit_entries:
                fy = get_fy_from_date(str(credit_entries[0].get("Date", "")))

            receipts = []
            for e in credit_entries:
                ref_id = _extract_ref_id(str(e.get("Description", "")))
                if not ref_id:
                    ref_id = _extract_ref_id(str(e.get("Particulars", "")))
                receipts.append({
                    "receipt_id": ref_id or f"{fy}-{str(e.get('Vch_No', '')).zfill(3)}",
                    "date": str(e.get("Date", "")),
                    "amount": _safe_float(e.get("Credit")),
                    "particulars": str(e.get("Particulars", "") or ""),
                })

            # Create the PDF
            plot_str = str(member.get("Plot_No", "") or "").zfill(2)
            fy_part = fy or "all"
            pdf_name = f"Consolidated_Receipt_Plot_{plot_str}_{fy_part}.pdf"
            pdf_path = config.RECEIPTS_DIR / fy_part / pdf_name
            pdf_path.parent.mkdir(parents=True, exist_ok=True)

            success = create_consolidated_receipt_pdf(
                pdf_path, receipts,
                member_name=member.get("Plot_Owner_Name", ""),
                plot_no=str(member.get("Plot_No", "") or ""),
                fy=fy,
            )
            if success:
                return f"✅ Consolidated receipt generated: {pdf_path.name} ({len(receipts)} receipts, total ₹{sum(r['amount'] for r in receipts):,.2f})"
            return "❌ Failed to generate consolidated receipt"

        # ── Ledger tools ──────────────────────────────────────────────

        def get_member_ledger(input_str: str = None):
            """Get the full ledger for a member. Input: member_id or plot_no."""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            if not member_id:
                plot_no = _normalize_plot_id(str(data.get("plot_no") or data.get("plot") or data.get("_0") or ""))
                if plot_no:
                    member = self.data_provider.get_member_by_plot_no(plot_no)
                    member_id = member.get("ID") if member else None
            if not member_id:
                return "Please provide a member_id or plot_no"
            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return f"Invalid member_id: {member_id}"

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            entries = self.data_provider.get_member_ledger(member_id)
            if not entries:
                return f"No ledger entries for {member.get('Plot_Owner_Name')}"

            lines = [f"\n{'='*100}", f"LEDGER — {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')})", f"{'='*100}"]
            lines.append(f"{'Date':<12} {'Vch_No':>6} {'Type':<10} {'Particulars':<28} {'Txn_ID':<22} {'Amount':>13}")
            lines.append(f"{'-'*93}")
            for e in entries:
                vch = str(e.get("Vch_No", "") or "")
                vtype = (str(e.get("Vch_Type", "") or ""))[:10]
                part = (str(e.get("Particulars", "") or ""))[:28]
                txn = (str(e.get("Transaction_ID", "") or ""))[:22]
                desc = str(e.get("Description", "") or "")
                credit = _safe_float(e.get("Credit"))
                debit = _safe_float(e.get("Debit"))
                if credit > 0:
                    amt_str = f"{credit:>11,.2f} Cr"
                elif debit > 0:
                    amt_str = f"{debit:>11,.2f} Dr"
                else:
                    amt_str = f"{0:>11,.2f}"
                line = f"{str(e.get('Date','')):<12} {vch:>6} {vtype:<10} {part:<28} {txn:<22} {amt_str}"
                # Append first 30 chars of Description in parens if it adds info beyond Particulars
                if desc and desc != part and desc[:28] != part:
                    line += f" ({desc[:28]})"
                lines.append(line)
            o = self.data_provider.get_current_outstanding(member_id)
            lines.append(f"{'-'*93}")
            label = "SURPLUS" if o >= 0 else "DEMAND"
            lines.append(f"{'BALANCE':<80} ₹{abs(o):>10,.2f} ({label})")
            lines.append(f"{'='*100}")
            return "\n".join(lines)

        def get_outstanding_summary(_: str = None):
            """Get outstanding balance summary for all members."""
            members = self.data_provider.get_all_members()
            lines = ["\nOUTSTANDING SUMMARY", "=" * 60,
                     f"{'Plot No':<10} {'Name':<25} {'Balance':>15}"]
            lines.append("-" * 60)
            total = 0
            for m in sorted(members, key=lambda x: str(x.get("Plot_No", ""))):
                o = self.data_provider.get_current_outstanding(m["ID"])
                total += o
                tag = " (demand)" if o < 0 else " (surplus)" if o > 0 else ""
                lines.append(f"{str(m.get('Plot_No','')):<10} {str(m.get('Plot_Owner_Name',''))[:24]:<25} ₹{abs(o):>10,.2f}{tag}")
            lines.append("-" * 60)
            tag = "NET DEMAND" if total < 0 else "NET SURPLUS"
            lines.append(f"{'TOTAL':<35} ₹{abs(total):>10,.2f} ({tag})")
            lines.append("=" * 60)
            return "\n".join(lines)

        # ── Ledger Update / Delete tools ───────────────────────────────

        def update_ledger_entry(input_str: str = None):
            """Update fields of an existing ledger entry (amount, particulars, date, transaction_id, description). Use this to modify an entry — e.g., reduce credit amount when splitting a payment across members, or change particulars/date/transaction reference. Outstanding is auto-recalculated after update. Input JSON keys: member_id (required), vch_no (required), plus any of: credit, debit, particulars, date, transaction_id, description. Example: {"member_id": 5, "vch_no": 42, "credit": 5000, "particulars": "By Payment (split)"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            vch_no = data.get("vch_no")

            if not member_id or not vch_no:
                return "member_id and vch_no are required"

            try:
                member_id = int(member_id)
                vch_no = int(vch_no)
            except (ValueError, TypeError):
                return "member_id and vch_no must be integers"

            updates = {}
            for key in ("credit", "debit", "particulars", "date", "transaction_id", "description",
                        "Credit", "Debit", "Particulars", "Date", "Transaction_ID", "Description"):
                if key in data:
                    val = data[key]
                    if key.lower() in ("credit", "debit"):
                        try:
                            val = float(val)
                        except (ValueError, TypeError):
                            return f"Invalid {key}: {val}"
                    updates[key] = val

            if not updates:
                return "No update fields provided. Send at least one of: credit, debit, particulars, date, transaction_id, description."

            # Normalize field names to match provider schema
            field_map = {
                "credit": "Credit", "debit": "Debit",
                "particulars": "Particulars", "date": "Date",
                "transaction_id": "Transaction_ID", "description": "Description",
                "Credit": "Credit", "Debit": "Debit",
                "Particulars": "Particulars", "Date": "Date",
                "Transaction_ID": "Transaction_ID", "Description": "Description",
            }
            normalized = {}
            for k, v in updates.items():
                normalized[field_map.get(k, k)] = v

            if not self.data_provider.update_ledger_entry(member_id, vch_no, normalized):
                return f"Failed to update entry Vch_No {vch_no} for member {member_id} — entry not found."

            member = self.data_provider.get_member(member_id)
            name = member.get("Plot_Owner_Name", f"Member {member_id}") if member else f"Member {member_id}"
            o = self.data_provider.get_current_outstanding(member_id)
            return f"✅ Entry Vch_No {vch_no} updated for {name}. Updated fields: {', '.join(normalized.keys())}. Outstanding: ₹{abs(o):,.2f} ({'demand' if o < 0 else 'surplus' if o > 0 else 'zero'})."

        def delete_ledger_entry(input_str: str = None):
            """Delete ANY ledger entry by member_id and vch_no (works for receipts, invoices, demands — any Vch_Type). Outstanding is auto-recalculated after deletion. Use this to remove an entry before recreating it with adjusted amounts (e.g., when re-splitting). Input JSON keys: member_id, vch_no. Example: {"member_id": 5, "vch_no": 42}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            vch_no = data.get("vch_no")

            if not member_id or not vch_no:
                return "member_id and vch_no are required"

            try:
                member_id = int(member_id)
                vch_no = int(vch_no)
            except (ValueError, TypeError):
                return "member_id and vch_no must be integers"

            if not self.data_provider.delete_ledger_entry(member_id, vch_no):
                return f"Failed to delete entry Vch_No {vch_no} for member {member_id} — entry not found."

            member = self.data_provider.get_member(member_id)
            name = member.get("Plot_Owner_Name", f"Member {member_id}") if member else f"Member {member_id}"
            o = self.data_provider.get_current_outstanding(member_id)
            return f"✅ Entry Vch_No {vch_no} deleted for {name}. Outstanding: ₹{abs(o):,.2f} ({'demand' if o < 0 else 'surplus' if o > 0 else 'zero'})."

        def add_ledger_entry(input_str: str = None):
            """Add an arbitrary debit or credit entry to a member's ledger (no PDF generated).
            Use for manual/cash entries, adjustments, or any entry that doesn't need a document.
            For DEBIT: adds Debit=amount, Credit=None (member owes money).
            For CREDIT: adds Debit=None, Credit=amount (member paid money).
            Input JSON keys:
              member_id or plot_no (required),
              amount (required, positive number),
              entry_type (required, "DEBIT" or "CREDIT"),
              date (DD-MM-YYYY, optional — defaults to today),
              particulars (optional, max 60 chars — shown as the line item),
              transaction_type (optional: CASH/CHQ/NEFT/UPI/etc.),
              description (optional, internal note),
              transaction_id (optional, bank reference/UTR).
            Outstanding is auto-updated.
            Example: {"member_id": 5, "amount": 5000, "entry_type": "CREDIT",
                      "date": "15-06-2026", "transaction_type": "CASH",
                      "particulars": "Cash payment received"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            amount = data.get("amount")
            entry_type = str(data.get("entry_type", "")).upper().strip()
            date = str(data.get("date", "") or "").strip()
            particulars = str(data.get("particulars", "") or "").strip()
            transaction_type = str(data.get("transaction_type", "") or "").strip()
            description = str(data.get("description", "") or "").strip()
            transaction_id = str(data.get("transaction_id", "") or "").strip()

            if not member_id:
                plot_no = data.get("plot_no")
                if plot_no:
                    members = self.data_provider.get_all_members()
                    m = next((x for x in members if str(x.get("Plot_No", "")).strip() == str(plot_no).strip()), None)
                    if m:
                        member_id = m["ID"]
            if not member_id:
                return "member_id or plot_no is required"
            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return "member_id must be an integer"

            if not amount:
                return "amount is required"
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return "amount must be a number"
            if amount <= 0:
                return "amount must be positive"

            if entry_type not in ("DEBIT", "CREDIT"):
                return "entry_type must be 'DEBIT' or 'CREDIT'"

            if not date:
                from datetime import datetime as _dt
                date = _dt.now().strftime("%d-%m-%Y")

            if not particulars:
                particulars = f"{'Charge' if entry_type == 'DEBIT' else 'Payment'} (manual)"

            vch_no = self.data_provider.get_next_voucher_number()
            entry = {
                "Date": date,
                "Particulars": f"{'To' if entry_type == 'DEBIT' else 'By'} {particulars[:60]}",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": amount if entry_type == "DEBIT" else None,
                "Credit": None if entry_type == "DEBIT" else amount,
                "Description": description or f"Manual {entry_type} entry",
                "Transaction_Type": transaction_type.upper() if transaction_type else "MANUAL",
                "Transaction_ID": transaction_id or None,
            }
            self.data_provider.add_ledger_entry(member_id, entry)

            member = self.data_provider.get_member(member_id)
            name = member.get("Plot_Owner_Name", f"Member {member_id}") if member else f"Member {member_id}"
            o = self.data_provider.get_current_outstanding(member_id)
            return (f"✅ ₹{amount:,.2f} {entry_type} entry added for {name} "
                    f"(Vch_No {vch_no}). Outstanding: ₹{abs(o):,.2f} "
                    f"({'demand' if o < 0 else 'surplus' if o > 0 else 'zero'}).")

        def record_manual_payments(input_str: str = None):
            """Process a batch of manual payment records — create CREDIT entries for all.
            Handles member resolution (by plot_no or fuzzy name match), multi-plot
            splitting (equal split across listed plots), and duplicate detection.
            Use this when the user provides a LIST of payments to record (e.g. list of
            names with amounts for common purpose). For a SINGLE entry, use add_ledger_entry.

            Input JSON: {
                "entries": [
                    {
                        "name": "Mrs. Dhanashri Deshpande",
                        "amount": 2000,
                        "date": "17-12-2021",
                        "particulars": "Shivaji salary contribution",
                        "plots": ["38", "39"]     // optional: split across plots
                    },
                    ...
                ]
            }
            Returns a per-entry summary of created/skipped/failed results.
            """
            data = _parse_action_input(input_str or "")
            entries = data.get("entries", [])
            if not entries:
                return "No entries provided. Pass a JSON object with an 'entries' list."

            import copy
            all_members = self.data_provider.get_all_members()
            results = []
            total_created = total_skipped = total_failed = 0

            for idx, entry in enumerate(entries):
                amount = _safe_float(entry.get("amount"))
                date = str(entry.get("date", "") or "").strip()
                plots = entry.get("plots") or []
                plot_no = str(entry.get("plot_no", "") or "").strip()
                name = str(entry.get("name", "") or "").strip()
                particulars = str(entry.get("particulars", "") or "").strip()

                if amount <= 0:
                    results.append(f"  #{idx+1}: Invalid amount")
                    total_failed += 1
                    continue
                if not date:
                    results.append(f"  #{idx+1}: Date required")
                    total_failed += 1
                    continue

                target_plots = []
                if plots:
                    target_plots = [str(p).strip() for p in plots]
                elif plot_no:
                    target_plots = [plot_no]
                elif name:
                    members_found = _find_members_by_name(all_members, name)
                    if members_found:
                        target_plots = [str(m["Plot_No"]) for m in members_found]
                        # only the first match if it's a high-scoring exact name
                        if len(target_plots) > 1:
                            best = members_found[0]
                            if best.get("Plot_Owner_Name", "").lower().strip() == name.lower().strip():
                                target_plots = [str(best["Plot_No"])]

                if not target_plots:
                    results.append(f"  #{idx+1}: Could not resolve member for '{name or plot_no}'")
                    total_failed += 1
                    continue

                split_amount = round(amount / len(target_plots), 2)
                full_particulars = particulars or "Manual payment"

                created_here = 0
                for p in target_plots:
                    member = self.data_provider.get_member_by_plot_no(p)
                    if not member:
                        results.append(f"  #{idx+1} Plot {p}: member not found")
                        total_failed += 1
                        continue

                    mid = member["ID"]
                    ledger = self.data_provider.get_member_ledger(mid)
                    is_dup = any(
                        _safe_float(e.get("Credit")) == split_amount
                        and str(e.get("Date", "")) == date
                        and full_particulars in str(e.get("Description", ""))
                        for e in ledger
                    )
                    if is_dup:
                        results.append(f"  #{idx+1} Plot {p}: skipped — duplicate")
                        total_skipped += 1
                        continue

                    vch_no = self.data_provider.get_next_voucher_number()
                    self.data_provider.add_ledger_entry(mid, {
                        "Date": date,
                        "Particulars": f"By {full_particulars[:60]}",
                        "Vch_Type": "Journal",
                        "Vch_No": vch_no,
                        "Debit": None,
                        "Credit": split_amount,
                        "Description": full_particulars,
                        "Transaction_Type": "MANUAL",
                    })
                    results.append(f"  #{idx+1} Plot {p}: ₹{split_amount:,.2f} (Vch_No {vch_no})")
                    created_here += 1
                    total_created += 1

                if created_here == 0:
                    total_failed += 1

            summary = f"✅ {total_created} created, {total_skipped} skipped, {total_failed} failed."
            return summary + "\n" + "\n".join(results)

        # ── Invoice tools ─────────────────────────────────────────────

        _month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        def _parse_date_range(from_date_input, to_date_input, fy_input):
            """Unify from_date, to_date, months, fy into a consistent set.
            Returns (from_date, to_date, months, fy_str, bill_period) or an error string."""
            if from_date_input and to_date_input:
                try:
                    d1 = datetime.strptime(from_date_input, "%d-%m-%Y")
                    d2 = datetime.strptime(to_date_input, "%d-%m-%Y")
                except ValueError:
                    return f"Invalid date format. Use DD-MM-YYYY. Got from='{from_date_input}', to='{to_date_input}'"
                if d2 < d1:
                    return f"to_date ({to_date_input}) is before from_date ({from_date_input})"
                # Inclusive month count
                months = (d2.year - d1.year) * 12 + (d2.month - d1.month) + 1
                from_date = from_date_input
                to_date = to_date_input
                fy_str = f"{d1.year % 100}-{d2.year % 100}"
                bill_period = f"{_month_names[d1.month-1]}{d1.year % 100} to {_month_names[d2.month-1]}{d2.year % 100}"
                return from_date, to_date, months, fy_str, bill_period

            # Fallback: parse from fy
            if not fy_input:
                fy_input = get_fy_string()
            parts = fy_input.split("-")
            fy_start = int(parts[0]) if len(parts) > 0 else 0
            if fy_start < 100:
                fy_start += 2000
            from_date = f"1-4-{fy_start}"
            to_date = f"31-3-{fy_start + 1}"
            months = 12
            fy_str = f"{fy_start % 100}-{(fy_start + 1) % 100}"
            return from_date, to_date, months, fy_str, get_bill_period()

        def generate_invoice(input_str: str = None):
            """Generate an invoice PDF AND add a debit entry to the member's ledger (automatically — no separate ledger tool call needed). Input JSON keys: member_id (or plot_no),
            invoice_date (optional, DD-MM-YYYY — defaults to today, used for back-dated invoices),
            from_date and to_date (both optional, DD-MM-YYYY format — calculate months automatically),
            fy (optional, e.g. '21-22' or '2021-2022' — only used if from_date/to_date not given).
            Example: {"plot_no": 5, "from_date": "01-11-2021", "to_date": "31-03-2022", "invoice_date": "15-11-2021"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            from_date_input = data.get("from_date") or data.get("from") or ""
            to_date_input = data.get("to_date") or data.get("to") or ""
            fy = data.get("fy")
            if not member_id:
                plot_no = _normalize_plot_id(str(data.get("plot_no") or data.get("plot") or data.get("_0") or ""))
                if plot_no:
                    member = self.data_provider.get_member_by_plot_no(plot_no)
                    member_id = member.get("ID") if member else None
            if not member_id:
                return "Please provide a member_id or plot_no"
            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return f"Invalid member_id: {member_id}"

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            # Resolve date range
            range_result = _parse_date_range(from_date_input, to_date_input, fy)
            if isinstance(range_result, str):
                return range_result
            from_date, to_date, months, fy_str, bill_period = range_result

            settings = self.data_provider.get_settings()
            repair_rate = float(settings.get("Repair_Fund_Rate", 100.0))
            service_rate = float(settings.get("Service_Charges_Rate", 885.0))
            sinking_rate = float(settings.get("Sinking_Fund_Rate", 15.0))
            repair_amount = repair_rate * months
            service_amount = service_rate * months
            sinking_amount = sinking_rate * months
            pending_interest = float(member.get("Pending_Interest", 0) or 0)
            gross_total = repair_amount + service_amount + sinking_amount + pending_interest

            # Invoice date — use provided or default to today
            invoice_date_input = data.get("invoice_date") or data.get("date") or ""
            if invoice_date_input:
                try:
                    inv_date = datetime.strptime(invoice_date_input, "%d-%m-%Y")
                except ValueError:
                    return f"Invalid invoice_date format. Use DD-MM-YYYY. Got: '{invoice_date_input}'"
            else:
                inv_date = datetime.now()
                invoice_date_input = inv_date.strftime("%d-%m-%Y")

            # Payment received during this invoice period only (from_date to to_date)
            ledger = self.data_provider.get_member_ledger(member_id)
            fd_parts = from_date.split("-")
            td_parts = to_date.split("-")
            period_start = datetime(int(fd_parts[2]), int(fd_parts[1]), int(fd_parts[0]))
            period_end = datetime(int(td_parts[2]), int(td_parts[1]), int(td_parts[0]))
            payment_received = 0
            for e in ledger:
                e_date_str = str(e.get("Date", "") or "").strip()
                if e_date_str:
                    try:
                        e_dt = datetime.strptime(e_date_str, "%d-%m-%Y")
                        if period_start <= e_dt <= period_end:
                            payment_received += _safe_float(e.get("Credit"))
                    except ValueError:
                        pass

            # Payment history and previous invoices for display
            payment_history = get_payment_history(ledger, invoice_date_input)
            previous_invoices = get_previous_invoices(ledger, invoice_date_input)

            # Previous Outstanding = debits - credits up to invoice date (positive = owes)
            prev_outstanding = -compute_outstanding_as_of(ledger, invoice_date_input)

            total_line_items = repair_amount + service_amount + sinking_amount
            total_amount_due = total_line_items + prev_outstanding + pending_interest

            invoice_no = f"{int(member.get('Plot_No', 0)):03d}{inv_date.strftime('%m%d')}"
            due_date = (inv_date + timedelta(days=config.INVOICE_DUE_DAYS)).strftime("%d-%m-%Y")
            plot_str = str(member.get("Plot_No", "") or "")
            plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
            line_items = {
                f"Repair & Maintenance Fund @ ₹{repair_rate:,.2f}/month × {months} months": repair_amount,
                f"Service Charges @ ₹{service_rate:,.2f}/month × {months} months": service_amount,
                f"Sinking Fund @ ₹{sinking_rate:,.2f}/month × {months} months": sinking_amount,
            }
            invoice_data = {
                "invoice_no": invoice_no,
                "invoice_date": invoice_date_input,
                "due_date": due_date,
                "plot_owner_name": member.get("Plot_Owner_Name", "Unknown"),
                "plot_no": member.get("Plot_No", "N/A"),
                "bill_period": bill_period,
                "from_date": from_date,
                "to_date": to_date,
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
            invoice_dir = config.INVOICES_DIR / fy_str[:2]
            invoice_dir.mkdir(parents=True, exist_ok=True)
            invoice_filename = f"Invoice_{plot_part}_{invoice_no}.pdf"
            invoice_path = invoice_dir / invoice_filename
            success = create_simple_invoice_pdf(invoice_path, invoice_data)
            if not success:
                return f"Failed to generate invoice for member {member_id}"

            # Add ledger entry (demand = debit) using invoice date
            vch_no = self.data_provider.get_next_voucher_number()
            date_range = f"{from_date} to {to_date}, {months} months" if from_date and to_date else f"{bill_period} ({months} months)"
            self.data_provider.add_ledger_entry(member_id, {
                "Date": invoice_date_input,
                "Particulars": f"To Annual Maintenance Charges ({date_range})",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": total_amount_due,
                "Credit": None,
                "Description": f"Invoice {invoice_no} FY {fy_str}",
                "Transaction_Type": "INVOICE",
            })
            o = self.data_provider.get_current_outstanding(member_id)

            return f"Invoice {invoice_filename} generated for {member.get('Plot_Owner_Name')} for ₹{total_amount_due:,.2f} ({months} months: {bill_period}). Outstanding: ₹{abs(o):,.2f} ({'demand' if o < 0 else 'surplus' if o > 0 else 'zero'})"

        def regenerate_invoice(input_str: str = None):
            """Regenerate an invoice PDF from an existing ledger entry using current rates. Input JSON keys: member_id, vch_no, new_member_id (optional for move). Example: {"member_id": 2, "vch_no": 15}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            vch_no = data.get("vch_no")
            new_member_id = data.get("new_member_id")

            if not member_id or not vch_no:
                return "member_id and vch_no are required"

            try:
                member_id = int(member_id)
                vch_no = int(vch_no)
                if new_member_id:
                    new_member_id = int(new_member_id)
            except (ValueError, TypeError):
                return "member_id and vch_no must be integers"

            ledger = self.data_provider.get_member_ledger(member_id)
            entry = next((e for e in ledger if int(e.get("Vch_No", 0)) == vch_no and str(e.get("Transaction_Type", "") or "").upper() == "INVOICE"), None)
            if not entry:
                return f"Invoice entry with Vch_No {vch_no} not found for member {member_id}"

            date = str(entry.get("Date", "") or "")
            description = str(entry.get("Description", "") or "")
            particulars = str(entry.get("Particulars", "") or "")
            invoice_no = ""
            fy_str = ""
            inv_match = re.search(r'Invoice\s+(\S+)', description)
            if inv_match:
                invoice_no = inv_match.group(1)
            fy_match = re.search(r'FY\s+([\d-]+)', description)
            if fy_match:
                fy_str = fy_match.group(1)

            # Extract original month count from particulars
            months_match = re.search(r'(\d+)\s*months?', particulars)
            months = int(months_match.group(1)) if months_match else 12

            settings = self.data_provider.get_settings()
            repair_rate = float(settings.get("Repair_Fund_Rate", 100.0))
            service_rate = float(settings.get("Service_Charges_Rate", 885.0))
            sinking_rate = float(settings.get("Sinking_Fund_Rate", 15.0))
            repair_amount = repair_rate * months
            service_amount = service_rate * months
            sinking_amount = sinking_rate * months

            member = self.data_provider.get_member(member_id)
            pending_interest = float(member.get("Pending_Interest", 0) or 0) if member else 0
            gross_total = repair_amount + service_amount + sinking_amount + pending_interest

            # Payment received during the original invoice period
            fd_match = re.search(r'(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})', particulars)
            from_date = fd_match.group(1) if fd_match else "01-04-2024"
            to_date = fd_match.group(2) if fd_match else "31-03-2025"
            try:
                fd_parts = from_date.split("-")
                td_parts = to_date.split("-")
                period_start = datetime(int(fd_parts[2]), int(fd_parts[1]), int(fd_parts[0]))
                period_end = datetime(int(td_parts[2]), int(td_parts[1]), int(td_parts[0]))
            except (ValueError, IndexError):
                period_start = None
                period_end = None

            payment_received = 0
            if period_start and period_end:
                for e in ledger:
                    e_date_str = str(e.get("Date", "") or "").strip()
                    if e_date_str:
                        try:
                            e_dt = datetime.strptime(e_date_str, "%d-%m-%Y")
                            if period_start <= e_dt <= period_end:
                                payment_received += _safe_float(e.get("Credit"))
                        except ValueError:
                            pass

            total_line_items = repair_amount + service_amount + sinking_amount
            # Previous Outstanding: exclude current invoice entry
            filtered_ledger = [e for e in ledger if int(e.get("Vch_No", 0)) != vch_no]
            prev_outstanding = -compute_outstanding_as_of(filtered_ledger, date)
            total_amount_due = total_line_items + prev_outstanding + pending_interest

            # Handle Move
            if new_member_id and new_member_id != member_id:
                old_pdf_paths = _get_invoice_pdf_paths(invoice_no)
                for p in old_pdf_paths:
                    try:
                        p.unlink()
                    except OSError:
                        pass
                if not self.data_provider.delete_ledger_entry(member_id, vch_no):
                    return f"Failed to delete entry from member {member_id}"
                self.data_provider.add_ledger_entry(new_member_id, {
                    "Date": date,
                    "Particulars": particulars,
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": total_amount_due,
                    "Credit": None,
                    "Description": description,
                    "Transaction_Type": "INVOICE",
                })
                target_member = self.data_provider.get_member(new_member_id)
                member_id = new_member_id
            else:
                target_member = self.data_provider.get_member(member_id)
                if target_member:
                    self.data_provider.update_ledger_entry(member_id, vch_no, {
                        "Debit": total_amount_due,
                    })

            if not target_member:
                return "Target member not found"

            plot_str = str(target_member.get("Plot_No", "") or "")
            plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
            fy_part = fy_str[:2] if fy_str else "20"

            invoice_dir = config.INVOICES_DIR / fy_part
            invoice_dir.mkdir(parents=True, exist_ok=True)
            invoice_filename = f"Invoice_{plot_part}_{invoice_no}.pdf" if invoice_no else f"Invoice_{plot_part}_regen.pdf"
            invoice_path = invoice_dir / invoice_filename

            # Delete old PDFs for this invoice_no
            for p in invoice_dir.glob(f"*{invoice_no}*.pdf"):
                try:
                    p.unlink()
                except OSError:
                    pass

            target_ledger = self.data_provider.get_member_ledger(member_id)
            payment_history = get_payment_history(target_ledger, date)
            previous_invoices = get_previous_invoices(target_ledger, date)

            invoice_data = {
                "invoice_no": invoice_no or "REGEN",
                "invoice_date": date,
                "due_date": date,
                "plot_owner_name": target_member.get("Plot_Owner_Name", "Unknown"),
                "plot_no": plot_str,
                "bill_period": f"{from_date} to {to_date}",
                "from_date": from_date,
                "to_date": to_date,
                "number_of_months": months,
                "payment_history": payment_history,
                "previous_invoices": previous_invoices,
                "line_items": {
                    f"Repair & Maintenance Fund @ ₹{repair_rate:,.2f}/month × {months} months": repair_amount,
                    f"Service Charges @ ₹{service_rate:,.2f}/month × {months} months": service_amount,
                    f"Sinking Fund @ ₹{sinking_rate:,.2f}/month × {months} months": sinking_amount,
                },
                "previous_outstanding": prev_outstanding,
                "interest_penalty": pending_interest,
                "total_line_items": total_line_items,
                "total_amount_due": total_amount_due,
                "amount_in_words": number_to_words_inr(total_amount_due),
            }

            success = create_simple_invoice_pdf(invoice_path, invoice_data)
            if not success:
                return f"Failed to regenerate invoice for member {member_id}"

            return f"✅ Invoice {invoice_no or 'REGEN'} regenerated for {target_member.get('Plot_Owner_Name')} (Plot {plot_str}) — ₹{total_amount_due:,.2f}"

        def delete_invoice(input_str: str = None):
            """Delete an invoice entry and its PDF from the ledger. Input JSON keys: member_id, vch_no. Example: {"member_id": 2, "vch_no": 15}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            vch_no = data.get("vch_no")

            if not member_id or not vch_no:
                return "member_id and vch_no are required"

            try:
                member_id = int(member_id)
                vch_no = int(vch_no)
            except (ValueError, TypeError):
                return "member_id and vch_no must be integers"

            ledger = self.data_provider.get_member_ledger(member_id)
            entry = next((e for e in ledger if int(e.get("Vch_No", 0)) == vch_no), None)
            if not entry:
                return f"Entry with Vch_No {vch_no} not found for member {member_id}"

            description = str(entry.get("Description", "") or "")
            inv_match = re.search(r'Invoice\s+(\S+)', description)
            invoice_no = inv_match.group(1) if inv_match else ""

            # Delete PDFs
            if invoice_no:
                for fy_dir in config.INVOICES_DIR.iterdir():
                    if fy_dir.is_dir():
                        for pdf in fy_dir.glob(f"*{invoice_no}*.pdf"):
                            try:
                                pdf.unlink()
                            except OSError:
                                pass

            if not self.data_provider.delete_ledger_entry(member_id, vch_no):
                return f"Failed to delete entry from member {member_id}"

            return f"✅ Invoice {invoice_no or f'Vch {vch_no}'} deleted for member {member_id}"

        def batch_generate_invoices(input_str: str = None):
            """Generate invoice PDFs AND add debit entries to each member's ledger (automatically — no separate ledger tool call needed). Input JSON keys:
            invoice_date (optional, DD-MM-YYYY — defaults to today, used for back-dated invoices),
            from_date and to_date (both optional, DD-MM-YYYY — duration calculated automatically),
            fy (optional), plots (optional list, defaults to all)."""
            data = _parse_action_input(input_str or "")
            from_date_input = data.get("from_date") or data.get("from") or ""
            to_date_input = data.get("to_date") or data.get("to") or ""
            fy = data.get("fy")
            plots_input = data.get("plots")
            if isinstance(plots_input, str):
                plots_input = [p.strip() for p in plots_input.split(",")]

            range_result = _parse_date_range(from_date_input, to_date_input, fy)
            if isinstance(range_result, str):
                return range_result
            from_date, to_date, months, fy_str, bill_period = range_result

            members = self.data_provider.get_all_members()
            if plots_input:
                plot_nos = [_normalize_plot_id(p) for p in plots_input]
                members = [m for m in members if _normalize_plot_id(str(m.get("Plot_No", ""))) in plot_nos]

            settings = self.data_provider.get_settings()
            repair_rate = float(settings.get("Repair_Fund_Rate", 100.0))
            service_rate = float(settings.get("Service_Charges_Rate", 885.0))
            sinking_rate = float(settings.get("Sinking_Fund_Rate", 15.0))
            repair_amount = repair_rate * months
            service_amount = service_rate * months
            sinking_amount = sinking_rate * months

            # Invoice date — use provided or default to today
            invoice_date_input = data.get("invoice_date") or data.get("date") or ""
            if invoice_date_input:
                try:
                    inv_date = datetime.strptime(invoice_date_input, "%d-%m-%Y")
                except ValueError:
                    return f"Invalid invoice_date format. Use DD-MM-YYYY. Got: '{invoice_date_input}'"
            else:
                inv_date = datetime.now()
                invoice_date_input = inv_date.strftime("%d-%m-%Y")
            due_date = (inv_date + timedelta(days=config.INVOICE_DUE_DAYS)).strftime("%d-%m-%Y")

            added = 0
            skipped = 0
            results = []
            for member in members:
                mid = member["ID"]
                # Check if invoice already exists for this period
                member_ledger = self.data_provider.get_member_ledger(mid)
                exists = any(f"FY {fy_str}" in (e.get("Description", "") or "") and "INVOICE" in (e.get("Description", "") or "").upper() for e in member_ledger)
                if exists:
                    skipped += 1
                    continue

                pending_interest = float(member.get("Pending_Interest", 0) or 0)
                gross_total = repair_amount + service_amount + sinking_amount + pending_interest

                # Payment received during this invoice period only
                payment_received = 0
                fd_parts = from_date.split("-")
                td_parts = to_date.split("-")
                period_start = datetime(int(fd_parts[2]), int(fd_parts[1]), int(fd_parts[0]))
                period_end = datetime(int(td_parts[2]), int(td_parts[1]), int(td_parts[0]))
                for e in member_ledger:
                    e_date_str = str(e.get("Date", "") or "").strip()
                    if e_date_str:
                        try:
                            e_dt = datetime.strptime(e_date_str, "%d-%m-%Y")
                            if period_start <= e_dt <= period_end:
                                payment_received += _safe_float(e.get("Credit"))
                        except ValueError:
                            pass

                payment_history = get_payment_history(member_ledger, invoice_date_input)
                previous_invoices = get_previous_invoices(member_ledger, invoice_date_input)

                prev_outstanding = -compute_outstanding_as_of(member_ledger, invoice_date_input)
                total_line_items = repair_amount + service_amount + sinking_amount
                total_amount_due = total_line_items + prev_outstanding + pending_interest

                invoice_no = f"{int(member.get('Plot_No', 0)):03d}{inv_date.strftime('%m%d')}"
                plot_str = str(member.get("Plot_No", "") or "")
                plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
                line_items = {
                    f"Repair & Maintenance Fund @ ₹{repair_rate:,.2f}/month × {months} months": repair_amount,
                    f"Service Charges @ ₹{service_rate:,.2f}/month × {months} months": service_amount,
                    f"Sinking Fund @ ₹{sinking_rate:,.2f}/month × {months} months": sinking_amount,
                }
                invoice_data = {
                    "invoice_no": invoice_no,
                    "invoice_date": invoice_date_input,
                    "due_date": due_date,
                    "plot_owner_name": member.get("Plot_Owner_Name", "Unknown"),
                    "plot_no": member.get("Plot_No", "N/A"),
                    "bill_period": bill_period,
                    "from_date": from_date,
                    "to_date": to_date,
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
                invoice_dir = config.INVOICES_DIR / fy_str[:2]
                invoice_dir.mkdir(parents=True, exist_ok=True)
                invoice_filename = f"Invoice_{plot_part}_{invoice_no}.pdf"
                invoice_path = invoice_dir / invoice_filename
                success = create_simple_invoice_pdf(invoice_path, invoice_data)
                if not success:
                    results.append(f"  ✗ {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}): PDF generation failed")
                    continue

                vch_no = self.data_provider.get_next_voucher_number()
                date_range = f"{from_date} to {to_date}, {months} months" if from_date and to_date else f"{bill_period} ({months} months)"
                self.data_provider.add_ledger_entry(mid, {
                    "Date": invoice_date_input,
                    "Particulars": f"To Annual Maintenance Charges ({date_range})",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": total_amount_due,
                    "Credit": None,
                    "Description": f"Invoice {invoice_no} FY {fy_str}",
                    "Transaction_Type": "INVOICE",
                })
                added += 1
                results.append(f"  ✓ {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}): ₹{total_amount_due:,.2f} ({months} months: {bill_period}) → {invoice_filename}")

            summary = f"Batch invoice generation ({months} months: {bill_period}):\n" + "\n".join(results)
            summary += f"\n\nGenerated: {added}, Skipped (already exist): {skipped}"
            return summary

        # ── Bank Statement Processing ─────────────────────────────────

        def process_bank_statement_pdf(input_str: str = None):
            """Process parsed bank statement entries (from PDF upload) to auto-match entries to members.
            CREDIT entries → ledger entries (receipt PDFs optional).
            DEBIT entries → expenses (auto-recorded with "Other" category).
            Unmatched CREDIT entries → need user validation.
            Unmatched DEBIT entries → auto-recorded as expenses.
            Set generate_receipts=false to only add ledger entries without PDF generation.
            Input is JSON with key=statement (cleaned entries text), key=generate_receipts (bool),
            key=format (format profile name), key=filename (original PDF filename).

            The tool handles ALL of the following automatically:
              - Multi-line entries (NEFT details on continuation lines)
              - Date lines (DD-MM-YYYY) as entry separators
              - Column parsing (DATE | PARTICULARS | CHQ.NO. | WITHDRAWALS | DEPOSITS | BALANCE)
              - Credit and debit detection via Dr suffix, cheque numbers, or balance movement
              - Balance column (Cr suffix) detection
              - NEFT/UPI/MOBFT/IMPS transaction type detection
              - Amount extraction from deposits/withdrawals columns
              - Member matching by surname, name tokens, email local-part, phone, and known identifiers
              - Auto-split receipts across group members when split rules exist

            Input: the raw bank statement text OR JSON: {"statement": "...", "generate_receipts": false}"""
            raw = input_str or ""

            if not raw:
                return "Please provide the bank statement text (copy-pasted from the statement)."

            # Support JSON-wrapped input for passing options like generate_receipts
            generate_receipts = False
            if raw.strip().startswith("{"):
                try:
                    parsed = json.loads(raw)
                    raw = parsed.get("statement", "")
                    generate_receipts = parsed.get("generate_receipts", False)
                except (json.JSONDecodeError, TypeError):
                    pass

            if not raw:
                return "Please provide the bank statement text (copy-pasted from the statement)."

            lines = [l.rstrip("\r") for l in raw.strip().split("\n") if l.strip()]

            # ── Preprocess: normalize and filter lines ──────────────────
            # Handle new format where date is directly followed by transaction ref (no space).
            # Also skip separator/header/balance-summary lines.
            normalized_lines = []
            for line in lines:
                # Skip dashed separators
                if re.match(r'^[\s\-]+$', line):
                    continue
                # Skip statement header lines
                if re.match(r'^STATEMENT\s+OF\s+ACCOUNT', line, re.IGNORECASE):
                    continue
                # Skip cumulative totals / balance summary lines
                if re.search(
                    r'(?:OPENING\s+)?BALANCE(?:\s+(?:B/F|C/F|BROUGHT|CARRIED))?'
                    r'|TOTAL\s+(?:DEBITS|CREDITS|DEPOSITS|WITHDRAWALS)'
                    r'|SUB\s*TOTAL|GRAND\s+TOTAL'
                    r'|CUMULATIVE\s+TOTAL',
                    line, re.IGNORECASE,
                ):
                    continue
                # Skip column headers (Date/Id or SI Date/Serial Number formats)
                if re.match(r'^(Date|Id|SI)\s', line, re.IGNORECASE):
                    continue
                # Skip page header/footer lines
                if re.search(r"Page\s+\d+(?:\s+of\s+\d+)?", line, re.IGNORECASE):
                    continue
                # Strip leading serial numbers before dates (e.g. "1 02-03-2026 ...")
                line = re.sub(r'^\d+\s+(?=\d{2}-\d{2}-\d{4})', '', line)
                # Insert space after DD-MM-YYYY date if followed by non-whitespace
                normalized = re.sub(r'^(\d{2}-\d{2}-\d{4})(\S)', r'\1 \2', line)
                normalized_lines.append(normalized)
            lines = normalized_lines

            # Fetch existing expenses for duplicate checking
            existing_expenses = self.data_provider.get_expenses()

            # ── Phase 1: Group lines into entries ──────────────────────
            # A new entry starts with a DATE (DD-MM-YYYY) line.
            # Subsequent lines without a date are continuation lines of the current entry.
            entries = []
            current = None
            for line in lines:
                date_match = re.match(r'^(\d{2}-\d{2}-\d{4})\s+(.*)', line)
                if date_match:
                    if current:
                        entries.append(current)
                    current = {
                        "date": date_match.group(1),
                        "first_line": date_match.group(2),
                        "all_lines": [line],
                    }
                elif current:
                    if re.match(r'^-{3,}$', line.strip()):
                        entries.append(current)
                        current = None
                        continue
                    current["all_lines"].append(line)

            if current:
                entries.append(current)

            if not entries:
                return "Could not parse any entries. Expected DATE in DD-MM-YYYY format at the start of each row."

            # ── Phase 2: Extract structured data from each entry ───────
            def _extract_entry_amounts(entry, prev_balance=None):
                """Extract deposit amount and balance from an entry.
                
                In the bank statement format:
                  DEPOSITS column = the second-to-last decimal number
                  BALANCE column = the last decimal number (always has Cr suffix)
                  WITHDRAWALS column = the third-to-last decimal number (if present)
                
                prev_balance: balance from the previous entry (used for ambiguity resolution
                              when the transaction amount has no Dr/Cr suffix).
                
                Returns (deposit_amount, balance_amount, transaction_type) or None if not a deposit.
                """
                combined = "\n".join(entry["all_lines"])

                # Reject cumulative/balance-summary/non-transaction rows
                if re.search(
                    r'(?:TOTAL\s+(?:DEBITS|CREDITS|DEPOSITS|WITHDRAWALS)'
                    r'|BALANCE\s+(?:B/F|C/F|BROUGHT|CARRIED)'
                    r'|SUB\s*TOTAL|GRAND\s+TOTAL)',
                    combined, re.IGNORECASE,
                ):
                    return None

                # Find all decimal numbers in order, along with Cr/Dr suffix
                all_amounts = list(re.finditer(r'([\d,]+\.\d{2})\s*(Cr|Dr)?', combined, re.IGNORECASE))
                if not all_amounts:
                    return None

                # The last amount is always the BALANCE (may have Cr suffix)
                balance_str = all_amounts[-1].group(1).replace(",", "")
                balance = float(balance_str)

                n = len(all_amounts)
                if n < 2:
                    return None

                # Check the second-to-last amount (the transaction amount)
                txn_amount_str = all_amounts[-2].group(1).replace(",", "")
                txn_amount = float(txn_amount_str)
                txn_suffix = (all_amounts[-2].group(2) or "").upper()

                # If the transaction amount has Dr suffix → definitely a withdrawal
                if txn_suffix == "DR":
                    return {
                        "type": "debit",
                        "amount": txn_amount,
                        "balance": balance,
                    }
                
                # If the transaction amount has Cr suffix → definitely a deposit
                if txn_suffix == "CR":
                    return {
                        "type": "credit",
                        "amount": txn_amount,
                        "balance": balance,
                    }

                # No Cr/Dr suffix on transaction amount — check for cheque number
                # Cheque numbers are all-digit tokens (6-9 digits) appearing between
                # the textual description and the first decimal amount, but only when
                # accompanied by a cheque-related keyword (CHQ/CHEQUE/CTS/INST).
                # Pure-numeric UTR references (e.g. 425054098) should NOT match.
                first_amt_pos = all_amounts[-2].start()
                text_before_amt = combined[:first_amt_pos].rstrip()
                # Match an all-digit token right before the amount
                cheque_match = re.search(r'\b(\d{6,9})\s*$', text_before_amt)
                if cheque_match and re.search(r'(?:CHQ|CHEQUE|CTS|INST)', text_before_amt, re.IGNORECASE):
                    # This is a cheque withdrawal
                    return {
                        "type": "debit",
                        "amount": txn_amount,
                        "balance": balance,
                    }

                # If we have a previous balance, determine debit/credit by balance movement.
                # This handles single-column formats (no Dr/Cr on transaction amounts).
                if prev_balance is not None:
                    diff_w = abs(balance - (prev_balance - txn_amount))
                    diff_d = abs(balance - (prev_balance + txn_amount))
                    if diff_w < diff_d:
                        # Balance closer to decrease → withdrawal
                        return {
                            "type": "debit",
                            "amount": txn_amount,
                            "balance": balance,
                        }
                    elif diff_d < diff_w:
                        # Balance closer to increase → deposit
                        return {
                            "type": "credit",
                            "amount": txn_amount,
                            "balance": balance,
                        }

                # No distinguishing feature — assume deposit (most common case)
                return {
                    "type": "credit",
                    "amount": txn_amount,
                    "balance": balance,
                }

            def _get_txn_type(particulars):
                """Detect transaction type from particulars text.
                
                Uses containment rather than prefix matching to handle formats
                where a transaction reference number precedes the type keyword.
                """
                p = particulars.upper()
                if "MOBFT" in p:
                    return "MOBFT"
                if "NEFT" in p:
                    return "NEFT"
                if "UPI" in p:
                    return "UPI"
                if "IMPS" in p:
                    return "IMPS"
                if "RTGS" in p:
                    return "RTGS"
                if "CHQ" in p or "CHEQUE" in p or "CTS" in p:
                    return "CHQ"
                if "CASH" in p:
                    return "CASH"
                return ""

            def _extract_txn_id(particulars, txn_type, all_lines):
                """Extract transaction ID from particulars."""
                if txn_type == "NEFT":
                    # Strip trailing amounts to find UTR at end
                    after_prefix = re.sub(r'^NEFT:?\s*', '', particulars)
                    after_amounts = re.sub(r'\s+[\d,]+\.\d{2}\s*(?:Cr)?(?:\s+[\d,]+\.\d{2}\s*(?:Cr)?)?\s*$', '', after_prefix, count=1)
                    parts = after_amounts.split()
                    if len(parts) >= 2:
                        return parts[-1]
                    # Fallback: find UTR Number: line in continuation
                    for line in all_lines:
                        utr = re.search(r'UTR\s*(?:Number|#)?\s*:?\s*(\S+)', line, re.IGNORECASE)
                        if utr:
                            return utr.group(1)
                elif txn_type == "UPI":
                    # UPI ref is the numeric segment after UPI prefix
                    ref_match = re.search(r'UPI[A-Za-z]*/(\d{6,})', particulars)
                    if ref_match:
                        return ref_match.group(1)
                # Generic: find any long alphanumeric reference
                ref_match = re.search(r'([A-Z0-9]{8,})', particulars)
                if ref_match:
                    return ref_match.group(1)
                return ""

            def _extract_search_tokens(particulars, txn_type, txn_id=None):
                """Extract member search tokens from particulars text. Returns (tokens: set, identifiers: list)"""
                tokens = set()
                identifiers = []

                TITLE_WORDS = {"MR", "MRS", "MS", "SHRI", "SMT", "DR", "SRI", "M/S", "CMN",
                               "PAY", "AND", "THE", "FROM", "B"}
                STOP_WORDS = TITLE_WORDS | {"PAYMENT", "RECEIVED", "TRANSFER", "NEFT", "RTGS",
                                            "IMPS", "CHQ", "CHEQUE", "BANK", "REFERENCE",
                                            "CREDIT", "DEBIT", "BY", "TO", "VIA", "THROUGH",
                                            "NUMBER", "SENDER", "TRANSACTION", "BALANCE", "AMOUNT",
                                            "PARTICULARS", "REMARKS", "DETAILS", "NAME", "DATE",
                                            "STATUS", "TYPE", "VALUE", "TOTAL", "CHARGES", "FEE", "FEES",
                                            "TAX", "GST", "ACCOUNT", "ACCT", "CODE", "INFO",
                                            "DESCRIPTION", "PERIOD", "SUMMARY", "DETAIL", "RECORD",
                                            "ENTRY", "ITEMS", "CLOSING", "OPENING", "AVAILABLE",
                                            "LEDGER", "REF", "UTR", "RRN", "IFSC", "BRANCH", "CARD",
                                             "MOBILE", "EMAIL", "PHONE", "ORDER", "INVOICE", "BILL",
                                             "PAID", "DUE", "NET", "GROSS",
                                             "BAL", "TXN",
                                             }

                def _should_record_name(token):
                    t = token.upper()
                    if len(t) <= 2:
                        return False
                    if t in STOP_WORDS:
                        return False
                    if re.search(r'\d+[.,]\d{2}', t):
                        return False
                    if bool(re.match(r'^[\d,]+\.\d{2}$', t)):
                        return False
                    if re.match(r'^\d+$', t):
                        return False
                    if re.match(r'^[A-Z0-9]{4,}$', t) and not re.search(r'[AEIOU]', t):
                        return False
                    return True

                # UPI: find name after /CR/
                cr_match = re.search(r'/CR/([^/]+)', particulars)
                if cr_match:
                    name_raw = cr_match.group(1).strip()
                    name_raw = re.sub(r'^(Mr|Mrs|Ms|Shri|Smt|Dr|Sri)\s+', '', name_raw, flags=re.IGNORECASE)
                    for t in re.split(r'[\s.]+', name_raw):
                        if len(t) > 1:
                            token = t.upper()
                            tokens.add(token)
                            if _should_record_name(token):
                                identifiers.append((token, "PAYEE_NAME"))

                # UPI: extract handle (last segment before amount)
                if txn_type == "UPI":
                    segments = particulars.split("/")
                    if segments:
                        last_seg = segments[-1].strip().split()[0]
                        last_seg = re.sub(r'[\s.,]', '', last_seg)
                        if len(last_seg) > 3 and not last_seg.isdigit():
                            token = last_seg.upper()
                            tokens.add(token)
                            identifiers.append((token, "UPI_ID"))

                # NEFT: name between prefix and UTR (strip trailing amounts)
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
                                if _should_record_name(token):
                                    identifiers.append((token, "PAYEE_NAME"))

                # MOBFT: extract name after "from: "
                mobft_match = re.search(r'from:\s*([A-Za-z\s.]+?)(?:/|\s+\d)', particulars)
                if mobft_match:
                    name_raw = mobft_match.group(1).strip()
                    for t in re.split(r'[\s.]+', name_raw):
                        if len(t) > 1:
                            token = t.upper()
                            tokens.add(token)
                            if _should_record_name(token):
                                identifiers.append((token, "PAYEE_NAME"))

                # Email: split firstname.surname@domain
                email_match = re.search(r'([\w.]+)@', particulars)
                if email_match:
                    for p in email_match.group(1).split("."):
                        if len(p) > 2:
                            token = p.upper()
                            tokens.add(token)
                            identifiers.append((token, "UPI_ID"))

                # Phone numbers (Indian mobile prefix)
                for phone in re.findall(r'([6-9]\d{9})', particulars):
                    if txn_id and phone in txn_id:
                        continue
                    tokens.add(phone)
                    identifiers.append((phone, "MOBILE"))

                # IMPS: extract name between "/" and "IMPS" (e.g. "KMB / AJAY IMPSAB/...")
                imps_match = re.search(r'/\s*([A-Za-z]+)\s+IMPS', particulars)
                if imps_match:
                    name_raw = imps_match.group(1).strip()
                    for t in re.split(r'[\s.]+', name_raw):
                        if len(t) > 1:
                            token = t.upper()
                            tokens.add(token)
                            if _should_record_name(token):
                                identifiers.append((token, "PAYEE_NAME"))

                return tokens, identifiers

            def _ngram_match(a, b, n=5):
                """Check if any n-gram of a appears as substring in b."""
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

            parsed_entries = []
            prev_balance = None
            for entry in entries:
                first_line = entry["first_line"]
                all_text = "\n".join(entry["all_lines"])

                # Track running balance from every entry (even skipped ones)
                _all_amts = list(re.finditer(r'([\d,]+\.\d{2})\s*(Cr|Dr)?', all_text, re.IGNORECASE))
                _entry_balance = float(_all_amts[-1].group(1).replace(",", "")) if _all_amts else None

                amounts = _extract_entry_amounts(entry, prev_balance)
                if amounts is None:
                    if _entry_balance is not None:
                        prev_balance = _entry_balance
                    continue

                amount = amounts["amount"]
                entry_type = amounts["type"]
                if amount <= 0:
                    if _entry_balance is not None:
                        prev_balance = _entry_balance
                    continue
                if amount < 100:
                    if _entry_balance is not None:
                        prev_balance = _entry_balance
                    continue  # skip test/trivial transactions

                txn_type = _get_txn_type(first_line)
                txn_id = _extract_txn_id(first_line, txn_type, entry["all_lines"])
                search_tokens, search_identifiers = _extract_search_tokens(first_line, txn_type, txn_id)

                # Merge continuation lines into particulars (e.g. UTR/ref number on next line)
                contin_text = " ".join(l.strip() for l in entry["all_lines"][1:])
                particulars = (first_line + " " + contin_text).strip() if contin_text else first_line
                parsed_entries.append({
                    "date": entry["date"],
                    "particulars": particulars,
                    "full_particulars": all_text,
                    "amount": amount,
                    "balance": amounts["balance"],
                    "entry_type": entry_type,
                    "txn_type": txn_type,
                    "txn_id": txn_id,
                    "search_tokens": search_tokens,
                    "search_identifiers": search_identifiers,
                })
                if _entry_balance is not None:
                    prev_balance = _entry_balance

            if not parsed_entries:
                return "No entries found in the statement."

            # ── Phase 3: Match entries to members ──────────────────────
            members = self.data_provider.get_all_members()
            results = []
            unmatched = []
            duplicates = []
            dup_expenses = []
            pending_entries = []

            for pentry in parsed_entries:
                tokens = pentry["search_tokens"]
                particulars = pentry["particulars"]
                amount = pentry["amount"]
                date = pentry["date"]
                txn_id_val = pentry.get("txn_id", "")

                # Phase 3a: Check reference store for exact identifier matches (highest confidence)
                ref_match = None
                ref_reason = ""
                for token in tokens:
                    candidate = self.data_provider.find_member_by_identifier(token)
                    if candidate:
                        ref_match = candidate
                        ref_reason = f"known identifier '{token}'"
                        break

                if ref_match:
                    best_match = ref_match
                    best_reason = ref_reason
                    best_score = 100  # override: reference store match is definitive
                else:
                    best_match = None
                    best_reason = ""
                    best_score = 0

                # Phase 3b: Fuzzy name/token matching (only if no reference match)
                if best_score < 100:
                    for member in members:
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
                        name_tokens = set(re.split(r'[\s.]+', name))

                        score = 0
                        reason_parts = []

                        # Surname match (highest priority)
                        name_parts_list = re.split(r'[\s.]+', name)
                        surname = name_parts_list[-1] if name_parts_list else ""
                        if surname and len(surname) > 2:
                            if surname in tokens:
                                score += 20
                                reason_parts.append("surname")
                            else:
                                matched = False
                                for token in tokens:
                                    if surname in token and len(token) > len(surname):
                                        score += 15
                                        reason_parts.append(f"surname_in_{token}")
                                        matched = True
                                        break
                                if not matched:
                                    for token in tokens:
                                        if len(token) > 2 and _ngram_match(token, surname):
                                            score += 15
                                            reason_parts.append(f"surname_fuzzy:{token}")
                                            break

                        # Any name token match
                        common = tokens & name_tokens
                        if common:
                            score += 5 * len(common)
                            reason_parts.append(f"name:{','.join(common)}")
                        # Fuzzy name token match (in addition to exact)
                        fuzzy_common = set()
                        for t in tokens:
                            if len(t) <= 2:
                                continue
                            for nt in name_tokens:
                                if len(nt) > 2 and t != nt and _ngram_match(t, nt):
                                    fuzzy_common.add(t)
                                    break
                        deduped = fuzzy_common - common
                        if deduped:
                            score += 3 * len(deduped)
                            reason_parts.append(f"name_fuzzy:{','.join(deduped)}")

                        # Email local-part match
                        if email and "@" in email:
                            email_local = email.split("@")[0]
                            email_parts = set(re.split(r'[.\s]+', email_local))
                            common_email = tokens & email_parts
                            if common_email:
                                score += 3 * len(common_email)
                                reason_parts.append(f"email:{','.join(common_email)}")

                        # Phone match
                        if phone and phone in tokens:
                            score += 8
                            reason_parts.append("phone")

                        if score > best_score:
                            best_score = score
                            best_match = member
                            best_reason = ", ".join(reason_parts)

                entry_type = pentry.get("entry_type", "credit")

                # Only auto-match if score >= 5 (avoids weak/false matches)
                if best_match and best_score >= 5 and amount:
                    mid = best_match["ID"]
                    ledger = self.data_provider.get_member_ledger(mid)

                    if entry_type == "debit":
                        # ── DEBIT → auto-create expense (with duplicate check) ──
                        dup_exp = _check_duplicate_expense(existing_expenses, date, amount, particulars[:80])
                        if dup_exp:
                            dup_expenses.append({
                                "date": date,
                                "amount": amount,
                                "particulars": particulars[:80],
                            })
                            results.append({
                                "date": date,
                                "amount": amount,
                                "txn_type": pentry.get('txn_type', ''),
                                "entry_type": "debit_duplicate",
                                "member_name": best_match.get("Plot_Owner_Name", ""),
                                "plot_no": best_match.get("Plot_No", ""),
                                "receipt_id": f"EXP-{dup_exp.get('ID', '?')}",
                                "member_id": mid,
                                "particulars": particulars[:80],
                            })
                        else:
                            exp_id = self.data_provider.add_expense({
                                "Member_ID": mid,
                                "Date": date,
                                "Particulars": particulars[:80],
                                "Amount": amount,
                                "Category": "Other",
                                "Bill_File": "",
                                "Comments": f"Bank withdrawal — {particulars[:60]}",
                                "Transaction_ID": pentry.get("txn_id") or "",
                                "Transaction_Type": pentry.get("txn_type", ""),
                            })
                            results.append({
                                "date": date,
                                "amount": amount,
                                "txn_type": pentry.get('txn_type', ''),
                                "entry_type": "debit",
                                "member_name": best_match.get("Plot_Owner_Name", ""),
                                "plot_no": best_match.get("Plot_No", ""),
                                "receipt_id": f"EXP-{exp_id}",
                                "member_id": mid,
                                "particulars": particulars[:80],
                            })
                    else:
                        # ── CREDIT → duplicate check + receipt (existing) ──
                        dup_entry = _check_duplicate_payment(ledger, pentry.get("txn_id") or "", date, amount)
                        if not dup_entry:
                            # Also check by date + amount + particulars prefix (covers missing txn_id)
                            raw_part = str(particulars or "").strip()
                            part_clean = raw_part[3:] if raw_part.upper().startswith("BY ") else raw_part
                            part_clean = part_clean[:40].upper()
                            for e in ledger:
                                e_part_upper = str(e.get("Particulars", "") or "").upper()
                                if "SPLIT FROM" in e_part_upper:
                                    continue
                                e_date = str(e.get("Date", "") or "").strip()
                                e_credit = _safe_float(e.get("Credit"))
                                if e_date == date and abs(e_credit - amount) < 0.01:
                                    e_part = str(e.get("Particulars", "") or "").strip()
                                    e_part_clean = e_part[3:] if e_part.upper().startswith("BY ") else e_part
                                    e_part_clean = e_part_clean[:40].upper()
                                    if part_clean and e_part_clean and (part_clean in e_part_clean or e_part_clean in part_clean):
                                        dup_entry = e
                                        break

                        # — Check for partial match: same date + particulars but different amount —
                        update_entry = None
                        if not dup_entry:
                            raw_part = str(particulars or "").strip()
                            part_clean = raw_part[3:] if raw_part.upper().startswith("BY ") else raw_part
                            part_clean = part_clean[:40].upper()
                            for e in ledger:
                                e_part_upper = str(e.get("Particulars", "") or "").upper()
                                if "SPLIT FROM" in e_part_upper:
                                    continue
                                e_date = str(e.get("Date", "") or "").strip()
                                e_credit = _safe_float(e.get("Credit"))
                                if e_date == date and e_credit > 0 and abs(e_credit - amount) >= 0.01:
                                    e_part = str(e.get("Particulars", "") or "").strip()
                                    e_part_clean = e_part[3:] if e_part.upper().startswith("BY ") else e_part
                                    e_part_clean = e_part_clean[:40].upper()
                                    if part_clean and e_part_clean and (part_clean in e_part_clean or e_part_clean in part_clean):
                                        update_entry = e
                                        break

                        if update_entry:
                            old_amt = _safe_float(update_entry.get("Credit"))
                            vch_no = int(update_entry.get("Vch_No", 0))
                            self.data_provider.update_ledger_entry(mid, vch_no, {
                                "Credit": amount,
                                "Transaction_ID": pentry.get("txn_id") or update_entry.get("Transaction_ID", ""),
                            })
                            ref_id = _extract_ref_id(str(update_entry.get("Description", "")) or "")
                            txn_type = pentry.get("txn_type", "")
                            plot_str = str(best_match.get("Plot_No", "") or "")
                            plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
                            fy = get_fy_from_date(date)
                            _delete_pdf_files(ref_id)
                            if generate_receipts:
                                receipt_dir = config.RECEIPTS_DIR / fy
                                receipt_dir.mkdir(parents=True, exist_ok=True)
                                rpath = receipt_dir / f"Receipt_{plot_part}_{ref_id}.pdf"
                                receipt_data = {
                                    "receipt_id": ref_id or f"{fy}-{str(vch_no).zfill(3)}",
                                    "date": date,
                                    "member_name": best_match.get("Plot_Owner_Name", ""),
                                    "plot_no": plot_str,
                                    "amount": amount,
                                    "transaction_id": pentry.get("txn_id") or "N/A",
                                    "transaction_type": txn_type,
                                    "payment_details": particulars[:120],
                                }
                                create_simple_receipt_pdf(rpath, receipt_data)
                            results.append({
                                "date": date,
                                "amount": amount,
                                "txn_type": txn_type,
                                "entry_type": "credit_updated",
                                "member_name": best_match.get("Plot_Owner_Name", ""),
                                "plot_no": plot_str,
                                "receipt_id": ref_id or f"{fy}-{str(vch_no).zfill(3)}",
                                "member_id": mid,
                                "particulars": particulars[:80],
                                "note": f"Updated from ₹{old_amt:,.2f} to ₹{amount:,.2f}",
                            })
                        elif dup_entry:
                            duplicates.append({
                                "date": date,
                                "amount": amount,
                                "txn_type": pentry['txn_type'],
                                "member_name": best_match.get("Plot_Owner_Name", ""),
                                "plot_no": best_match.get("Plot_No", ""),
                                "particulars": particulars[:80],
                            })
                        else:
                            fy = get_fy_from_date(date)
                            vch_no = self.data_provider.get_next_voucher_number()
                            receipt_id = f"{fy}-{str(vch_no).zfill(3)}"

                            txn_type = pentry.get("txn_type", "")
                            # Outstanding as of the transaction date
                            led_after = list(ledger) + [{"Date": date, "Credit": amount, "Debit": None}]
                            current_outstanding = compute_outstanding_as_of(led_after, date)
                            receipt_data = {
                                "receipt_id": receipt_id,
                                "date": date,
                                "member_name": best_match.get("Plot_Owner_Name", ""),
                                "plot_no": best_match.get("Plot_No", ""),
                                "amount": amount,
                                "transaction_id": pentry.get("txn_id") or "N/A",
                                "transaction_type": txn_type,
                                "outstanding_balance": current_outstanding,
                                "payment_details": particulars[:120],
                            }
                            if generate_receipts:
                                receipt_dir = config.RECEIPTS_DIR / fy
                                receipt_dir.mkdir(parents=True, exist_ok=True)
                                plot_str = str(best_match.get("Plot_No", "") or "")
                                plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
                                rpath = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"
                                create_simple_receipt_pdf(rpath, receipt_data)

                            pending_entries.append((mid, {
                                "Date": date,
                                "Particulars": f"By {particulars[:60]}",
                                "Vch_Type": "Journal",
                                "Vch_No": vch_no,
                                "Debit": None,
                                "Credit": amount,
                                "Description": f"Receipt {receipt_id} — Bank Statement ({txn_type})",
                                "Transaction_Type": txn_type,
                                "Transaction_ID": pentry.get("txn_id") or "",
                            }))

                            # ── Auto-split check ──
                            split_group = self.data_provider.get_split_group_for_member(mid)
                            if split_group:
                                # Remove full-amount entry, replace with per_head for all group members
                                pending_entries.pop()
                                split_amt = round(amount / len(split_group), 2)
                                for smid in split_group:
                                    orig_vch = vch_no
                                    svch = self.data_provider.get_next_voucher_number()
                                    sfy = get_fy_from_date(date)
                                    srid = f"{sfy}-{str(svch).zfill(3)}"
                                    sdata = {
                                        "receipt_id": srid,
                                        "date": date,
                                        "member_name": "Split Receipt",
                                        "plot_no": "",
                                        "amount": split_amt,
                                        "transaction_id": f"SPLIT-{receipt_id}",
                                        "transaction_type": "SPLIT",
                                        "outstanding_balance": 0,
                                        "payment_details": f"Split from {receipt_id} — {clean_payment_details(particulars)[:60]}",
                                    }
                                    if generate_receipts:
                                        sdir = config.RECEIPTS_DIR / sfy
                                        sdir.mkdir(parents=True, exist_ok=True)
                                        spath = sdir / f"Receipt_Plot_No_{str(smid).zfill(2)}_{srid}.pdf"
                                        create_simple_receipt_pdf(spath, sdata)
                                    pending_entries.append((smid, {
                                        "Date": date,
                                        "Particulars": f"By Split from {best_match.get('Plot_Owner_Name', '')} ({particulars[:40]})",
                                        "Vch_Type": "Journal",
                                        "Vch_No": svch,
                                        "Debit": None,
                                        "Credit": split_amt,
                                        "Description": f"Split from #{orig_vch} (src:{mid})",
                                        "Transaction_Type": "SPLIT",
                                        "Transaction_ID": f"SPLIT-{receipt_id}",
                                    }))

                            # Record known identifiers for future matching
                            identifiers = pentry.get("search_identifiers", [])
                            txn_type = pentry.get("txn_type", "")
                            for id_value, id_type in identifiers:
                                self.data_provider.record_payment_reference(mid, id_type, id_value, date, transaction_type=txn_type)

                            results.append({
                                "date": date,
                                "amount": amount,
                                "txn_type": pentry['txn_type'],
                                "member_name": best_match.get("Plot_Owner_Name", ""),
                                "plot_no": best_match.get("Plot_No", ""),
                                "receipt_id": receipt_id,
                                "member_id": mid,
                                "particulars": particulars[:80],
                                "has_pdf": generate_receipts,
                            })
                elif entry_type == "debit":
                    # Unmatched DEBIT → auto-create expense with duplicate check
                    dup_exp = _check_duplicate_expense(existing_expenses, date, amount, particulars[:80])
                    if dup_exp:
                        dup_expenses.append({
                            "date": date,
                            "amount": amount,
                            "particulars": particulars[:80],
                        })
                        results.append({
                            "date": date,
                            "amount": amount,
                            "txn_type": pentry.get('txn_type', ''),
                            "entry_type": "debit_duplicate",
                            "member_name": "(Unmatched Withdrawal)",
                            "plot_no": "",
                            "receipt_id": f"EXP-{dup_exp.get('ID', '?')}",
                            "member_id": None,
                            "particulars": particulars[:80],
                        })
                    else:
                        exp_id = self.data_provider.add_expense({
                            "Member_ID": None,
                            "Date": date,
                            "Particulars": particulars[:80],
                            "Amount": amount,
                            "Category": "Other",
                            "Bill_File": "",
                            "Comments": f"Auto-recorded bank withdrawal — {particulars[:60]}",
                            "Transaction_ID": pentry.get("txn_id") or "",
                            "Transaction_Type": pentry.get("txn_type", ""),
                        })
                        results.append({
                            "date": date,
                            "amount": amount,
                            "txn_type": pentry.get('txn_type', ''),
                            "entry_type": "debit",
                            "member_name": "(Unmatched Withdrawal)",
                            "plot_no": "",
                            "receipt_id": f"EXP-{exp_id}",
                            "member_id": None,
                            "particulars": particulars[:80],
                        })
                else:
                    unmatched.append({
                        "date": date,
                        "amount": amount,
                        "particulars": particulars[:80],
                        "full_particulars": pentry.get("full_particulars", ""),
                        "txn_type": pentry.get("txn_type", ""),
                        "txn_id": pentry.get("txn_id", ""),
                    })

            lines = []
            lines.append("Bank Statement Processing Results:\n")
            receipt_count = 0
            expense_count = 0
            update_count = 0
            expense_dup_count = 0
            for r in results:
                if r.get("entry_type") == "debit":
                    lines.append(
                        f"  ↓ {r['date']} | ₹{r['amount']:>8,.2f} | [{r['txn_type']}] "
                        f"{r['member_name']} → Expense {r['receipt_id']}"
                    )
                    expense_count += 1
                elif r.get("entry_type") == "debit_duplicate":
                    lines.append(
                        f"  ⚠️ {r['date']} | ₹{r['amount']:>8,.2f} | [{r['txn_type']}] "
                        f"{r['member_name']} — expense skipped (already exists {r['receipt_id']})"
                    )
                    expense_dup_count += 1
                elif r.get("entry_type") == "credit_updated":
                    note = r.get("note", "")
                    lines.append(
                        f"  ✎ {r['date']} | ₹{r['amount']:>8,.2f} | [{r['txn_type']}] "
                        f"{r['member_name']} (Plot {r['plot_no']}) → {r['receipt_id']} {note}"
                    )
                    update_count += 1
                else:
                    lines.append(
                        f"  ✓ {r['date']} | ₹{r['amount']:>8,.2f} | [{r['txn_type']}] "
                        f"{r['member_name']} (Plot {r['plot_no']}) → Receipt {r['receipt_id']}"
                    )
                    receipt_count += 1
            if not results:
                lines.append("  (No entries processed)")

            if unmatched:
                lines.append("\n\n--- UNMATCHED CREDIT ENTRIES (need your validation) ---")
                for u in unmatched:
                    tag = f"[{u['txn_type']}]" if u['txn_type'] else ""
                    lines.append(
                        f"  ? {u['date']} | ₹{u['amount']:>8,.2f} | {tag} {u['particulars']}"
                    )
                lines.append("\nFor each unmatched entry above, please tell me the plot number or member name to process it.")

            if duplicates:
                lines.append(f"\n⚠️ DUPLICATES SKIPPED: {len(duplicates)}")
                for d in duplicates:
                    lines.append(
                        f"  ⚠️ {d['date']} | ₹{d['amount']:>8,.2f} | [{d['txn_type']}] "
                        f"{d['member_name']} (Plot {d['plot_no']}) — already exists"
                    )

            if dup_expenses:
                lines.append(f"\n⚠️ DUPLICATE EXPENSES SKIPPED: {len(dup_expenses)}")
                for d in dup_expenses:
                    lines.append(
                        f"  ⚠️ {d['date']} | ₹{d['amount']:>8,.2f} | {d['particulars'][:40]} — expense already exists"
                    )

            lines.append(f"\n{'-'*50}")
            parts = [f"Receipts generated: {receipt_count}", f"Expenses recorded: {expense_count}", f"Total processed: {len(results)}"]
            if update_count:
                parts.insert(0, f"Entries updated: {update_count}")
            lines.append(" | ".join(parts))
            if duplicates:
                lines.append(f"Duplicates skipped: {len(duplicates)} entries already existed.")
            if dup_expenses:
                lines.append(f"Duplicate expenses skipped: {len(dup_expenses)} entries already existed.")
            lines.append(f"Unmatched credit entries: {len(unmatched)} need your input.")
            summary_text = "\n".join(lines)

            if pending_entries:
                self.data_provider.add_ledger_entries(pending_entries)

            return {
                "summary": summary_text,
                "matched": results,
                "unmatched": unmatched,
                "duplicates": duplicates,
                "dup_expenses": dup_expenses,
            }

        # ── Admin tools ───────────────────────────────────────────────

        def trigger_april_entries(fy: str = None):
            """Trigger April 1st auto-entries for all members (yearly maintenance demand)."""
            if fy is None:
                fy = get_fy_string()
            members = self.data_provider.get_all_members()
            amount = config.AUTO_ENTRY_AMOUNT
            success = 0
            skipped = 0
            for member in members:
                mid = member["ID"]
                ledger = self.data_provider.get_member_ledger(mid)
                exists = any(f"FY {fy}" in (e.get("Description", "") or "") for e in ledger)
                if exists:
                    skipped += 1
                    continue
                vch_no = self.data_provider.get_next_voucher_number()
                self.data_provider.add_ledger_entry(mid, {
                    "Date": "1-4-2026",
                    "Particulars": "To Member Contribution Received",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": amount,
                    "Credit": None,
                    "Description": f"YEARLY MAINTENANCE DEMAND FY {fy}",
                    "Transaction_Type": "DEMAND",
                })
                success += 1
            return f"April entries: {success} added, {skipped} skipped"

        def add_demand_entry(input_str: str = None):
            """Add a yearly maintenance demand (debit) for a single member. Input JSON keys: member_id (or plot_no), amount (optional, defaults to AUTO_ENTRY_AMOUNT), fy (optional), date (optional). Example: {"plot_no": 5, "amount": 12000, "fy": "26-27"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            amount = data.get("amount")
            fy = data.get("fy") or get_fy_string()
            date = data.get("date") or f"1-4-{fy[:2]}"  # April 1st of FY start year

            if not member_id:
                plot_no = _normalize_plot_id(str(data.get("plot_no") or data.get("plot") or data.get("_0") or ""))
                if plot_no:
                    member = self.data_provider.get_member_by_plot_no(plot_no)
                    member_id = member.get("ID") if member else None
            if not member_id:
                return "Please provide a member_id or plot_no"
            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return f"Invalid member_id: {member_id}"

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            if not amount:
                amount = config.AUTO_ENTRY_AMOUNT
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return f"Invalid amount: {amount}"

            # Check if already exists for this FY
            ledger = self.data_provider.get_member_ledger(member_id)
            exists = any(f"FY {fy}" in (e.get("Description", "") or "") and "DEMAND" in (e.get("Description", "") or "").upper() for e in ledger)
            if exists:
                return f"Demand entry for FY {fy} already exists for {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}). Skipping."

            vch_no = self.data_provider.get_next_voucher_number()
            self.data_provider.add_ledger_entry(member_id, {
                "Date": date,
                "Particulars": "To Annual Maintenance Charges",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": amount,
                "Credit": None,
                "Description": f"YEARLY MAINTENANCE DEMAND FY {fy}",
                "Transaction_Type": "DEMAND",
            })
            o = self.data_provider.get_current_outstanding(member_id)
            return f"Demand of ₹{amount:,.2f} added for {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}) for FY {fy}. Outstanding: ₹{abs(o):,.2f} ({'demand' if o < 0 else 'surplus' if o > 0 else 'zero'})"

        def batch_add_demand_entries(input_str: str = None):
            """Add yearly maintenance demand for ALL members (or a list of plots). Input JSON keys: amount (optional, defaults to AUTO_ENTRY_AMOUNT), fy (optional), plots (optional list, defaults to all)."""
            data = _parse_action_input(input_str or "")
            amount = data.get("amount") or config.AUTO_ENTRY_AMOUNT
            fy = data.get("fy") or get_fy_string()
            date = data.get("date") or f"1-4-{fy[:2]}"
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = config.AUTO_ENTRY_AMOUNT

            plots_input = data.get("plots")
            if isinstance(plots_input, str):
                plots_input = [p.strip() for p in plots_input.split(",")]

            members = self.data_provider.get_all_members()
            if plots_input:
                plot_nos = [_normalize_plot_id(p) for p in plots_input]
                members = [m for m in members if _normalize_plot_id(str(m.get("Plot_No", ""))) in plot_nos]

            added = 0
            skipped_exists = 0
            skipped_unknown = 0
            results = []
            for member in members:
                mid = member["ID"]
                ledger = self.data_provider.get_member_ledger(mid)
                exists = any(f"FY {fy}" in (e.get("Description", "") or "") and "DEMAND" in (e.get("Description", "") or "").upper() for e in ledger)
                if exists:
                    skipped_exists += 1
                    continue
                vch_no = self.data_provider.get_next_voucher_number()
                self.data_provider.add_ledger_entry(mid, {
                    "Date": date,
                    "Particulars": "To Annual Maintenance Charges",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": amount,
                    "Credit": None,
                    "Description": f"YEARLY MAINTENANCE DEMAND FY {fy}",
                    "Transaction_Type": "DEMAND",
                })
                added += 1
                results.append(f"  ✓ {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}): ₹{amount:,.2f}")

            summary = f"Demand entries for FY {fy}:\n" + "\n".join(results)
            summary += f"\n\nAdded: {added}, Already existed: {skipped_exists}"
            return summary

        def get_current_settings(_: str = None):
            """Get current system settings (rates, FY, etc.)."""
            settings = self.data_provider.get_settings()
            return "\n".join(f"{k}: {v}" for k, v in settings.items())

        def add_new_member(input_str: str = None):
            """Add a new member. Input JSON keys: plot_no, name, email (optional), phone (optional)."""
            data = _parse_action_input(input_str or "")
            plot_no = data.get("plot_no") or data.get("plot") or data.get("_0") or ""
            name = data.get("name") or data.get("_1") or ""
            if not plot_no or not name:
                return "Please provide plot_no and name"
            email = data.get("email", "")
            phone = data.get("phone", "")
            member_data = {
                "Plot_No": plot_no,
                "Plot_Owner_Name": name,
                "Email": email,
                "Phone": phone,
                "Pending_Interest": 0,
            }
            member_id = self.data_provider.add_member(member_data)
            return f"Member added: ID={member_id}, Plot={plot_no}, Name={name}"

        def update_rates(input_str: str = None):
            """Update invoice rates. Input JSON keys: repair, service, sinking (all optional)."""
            data = _parse_action_input(input_str or "")
            key_map = {
                "repair": "Repair_Fund_Rate",
                "service": "Service_Charges_Rate",
                "sinking": "Sinking_Fund_Rate",
            }
            settings = {}
            for k, excel_key in key_map.items():
                if k in data:
                    settings[excel_key] = str(data[k])
            if not settings:
                for i, key in enumerate(["_0", "_1", "_2"]):
                    if key in data:
                        settings[list(key_map.values())[i]] = str(data[key])
            if settings:
                self.data_provider.update_settings(settings)
                return f"Rates updated: {settings}"
            return "No rates provided"

        self.register_tool(process_bank_statement_pdf, "process_bank_statement_pdf",
                           "Process parsed bank statement entries (from PDF upload) "
                           "and auto-generate receipts for matched members. "
                           "Input is JSON with key=statement (cleaned entries text), "
                           "key=generate_receipts (bool, default true), "
                           "key=format (format profile name), "
                           "key=filename (original PDF filename). "
                           "Returns dict with matched, unmatched, duplicates. "
                           "Wrapper around the existing entry processing logic.")

        # ── New Accounts-based tools ──────────────────────────────────

        from tools.pdf_parser import parse_entries_to_accounts as _do_parse

        def parse_statement_to_accounts(input_str: str = None):
            """Parse bank statement text into the Accounts sheet.
            Each entry is recorded as-is with Withdrawal, Deposit, Balance columns
            determined by the format profile. Balance is validated per-row.
            Input: JSON with key=statement (raw entries text), key=filename (optional).
            Returns validation summary: entries count, per-file balance check, gaps."""
            raw = input_str or ""
            if not raw:
                return "Please provide the bank statement text."
            if raw.strip().startswith("{"):
                try:
                    parsed = json.loads(raw)
                    raw = parsed.get("statement", "")
                    filename = parsed.get("filename", "pasted_text")
                    format_override = parsed.get("format", "")
                except (json.JSONDecodeError, TypeError):
                    filename = "pasted_text"
                    format_override = ""
            else:
                filename = "pasted_text"
                format_override = ""
            if not raw:
                return "Please provide the bank statement text."

            lines = [l.rstrip("\r").strip() for l in raw.strip().split("\n") if l.strip()]
            import importlib
            import tools.pdf_parser
            importlib.reload(tools.pdf_parser)
            from tools.pdf_parser import detect_format, clean_entries
            from tools.pdf_parser import parse_entries_to_accounts as _do_parse
            fmt = format_override or detect_format(lines)
            cleaned = clean_entries(lines)
            if not cleaned:
                return "Could not parse any entries. Expected DATE in DD-MM-YYYY format."

            result = _do_parse(cleaned, fmt)
            entries = result["entries"]
            if not entries:
                return "Could not extract any entries with valid amounts."

            for e in entries:
                e["Source_File"] = filename

            dup_check = self.data_provider.get_accounts_entries()
            existing_keys = set()
            for d in dup_check:
                key = (
                    str(d.get("Date", "")),
                    str(d.get("Transaction_Type", "") or ""),
                    str(d.get("Transaction_ID", "") or ""),
                    round(float(d.get("Deposit") or d.get("Withdrawal") or 0), 2),
                    "W" if d.get("Withdrawal") else "D",
                )
                existing_keys.add(key)

            added = 0
            dup_flagged = 0
            for e in entries:
                key = (
                    str(e["Date"]),
                    str(e["Transaction_Type"] or ""),
                    str(e["Transaction_ID"] or ""),
                    round(float(e["Deposit"] or e["Withdrawal"] or 0), 2),
                    "W" if e["Withdrawal"] else "D",
                )
                if key in existing_keys:
                    e["Status"] = "Potential Duplicate"
                    dup_flagged += 1
                existing_keys.add(key)
                added += 1

            self.data_provider.add_accounts_entries(entries)

            # Auto-record bank interest as Income
            auto_income = 0
            for e in entries:
                particulars = str(e.get("Particulars", "") or "")
                deposit = float(e.get("Deposit", 0) or 0)
                if "Int.Pd" in particulars and deposit > 0:
                    self.data_provider.add_interest_income({
                        "Date": e["Date"],
                        "Particulars": particulars[:200],
                        "Amount": deposit,
                        "Transaction_ID": e.get("Transaction_ID", "") or "",
                        "Transaction_Type": e.get("Transaction_Type", "") or "",
                        "Source_File": filename,
                        "Accounts_Entry_ID": e["Entry_ID"],
                    })
                    self.data_provider.update_accounts_entry(e["Entry_ID"], {"Status": "Skipped"})
                    auto_income += 1

            summary = self.data_provider.get_accounts_summary()

            lines_out = []
            lines_out.append(f"Parsed {fmt} → {result['entry_count']} entries found, {added} added to Accounts sheet.")
            if dup_flagged:
                lines_out.append(f"⚠️ {dup_flagged} entries flagged as Potential Duplicates (review in Accounts tab).")
            if auto_income:
                lines_out.append(f"📈 {auto_income} interest entry(ies) auto-recorded as Income (Interest_Income sheet).")
            lines_out.append("")
            for stmt in summary.get("statements", []):
                if stmt["source_file"] == filename:
                    lines_out.append(f"  File: {filename}")
                    lines_out.append(f"    Period:     {stmt['first_date']} → {stmt['last_date']}")
                    lines_out.append(f"    Entries:    {stmt['entries']}")
                    lines_out.append(f"    Deposits:   ₹{stmt['total_deposits']:,.2f}")
                    lines_out.append(f"    Withdrawals: ₹{stmt['total_withdrawals']:,.2f}")
                    lines_out.append(f"    Opening:    ₹{stmt['opening_balance']:,.2f}")
                    lines_out.append(f"    Closing:    ₹{stmt['closing_balance']:,.2f}")
                    if stmt["mismatches"]:
                        lines_out.append(f"    ❌ Balance mismatches: {stmt['mismatches']} rows (fix before Ledger creation)")
                    else:
                        lines_out.append(f"    ✓ Balance validated — all rows match")
            continuity = summary.get("continuity", [])
            if continuity:
                lines_out.append("")
                lines_out.append("📊 Statement Continuity by Financial Year:")
                for fy in continuity:
                    fy_lbl = fy["fy"]
                    fy_yr = 2000 + int(fy_lbl[:2])
                    fy_range = f"Apr {fy_yr} — Mar {fy_yr+1}"
                    rollover = fy.get("rollover_from_prev")
                    files_str = ", ".join(fy["files"])
                    lines_out.append(f"  FY {fy_lbl} ({fy_range})")
                    lines_out.append(f"    Opening: ₹{fy['opening_balance']:,.2f} ({fy['opening_date']}) | "
                                     f"Closing: ₹{fy['closing_balance']:,.2f} ({fy['closing_date']}) "
                                     f"— {fy['entries']} entries")
                    lines_out.append(f"    Files: {files_str}")
                    if rollover:
                        if rollover["match"]:
                            lines_out.append(f"    ✅ Rollover from FY {rollover['from_fy']}: "
                                             f"₹{rollover['from_closing_balance']:,.2f} → ₹{rollover['to_opening_balance']:,.2f}")
                        else:
                            lines_out.append(f"    ❌ Gap at FY boundary: FY {rollover['from_fy']} closed "
                                             f"₹{rollover['from_closing_balance']:,.2f} but FY {fy_lbl} opens "
                                             f"₹{rollover['to_opening_balance']:,.2f} "
                                             f"(diff: ₹{rollover['difference']:,.2f})")

            gaps = summary.get("gaps", [])
            if gaps:
                lines_out.append("")
                lines_out.append("⚠️ Balance mismatches at FY boundaries (missing entries suspected):")
                for g in gaps:
                    lines_out.append(f"  • FY {g['from_fy']} closing ₹{g['expected_closing']:,.2f} → "
                                     f"FY {g['to_fy']} opening ₹{g['actual_opening']:,.2f} "
                                     f"(diff: ₹{g['difference']:,.2f})")

            return "\n".join(lines_out)

        self.register_tool(parse_statement_to_accounts, "parse_statement_to_accounts",
                           "Parse bank statement text into the Accounts sheet. "
                           "Records all entries as-is with Withdrawal, Deposit, Balance columns. "
                           "Validates balance per-row and reports mismatches. "
                           "Flags potential duplicates. "
                           "Input JSON: statement (raw text), filename (optional). "
                           "Returns validation summary.")

        def create_ledger_from_accounts(input_str: str = None):
            """Create Ledger entries from Pending deposits in the Accounts sheet.
            Matches each deposit to a member using Payment Reference Store lookup,
            fuzzy name/token/phone/email matching, and WhatsApp_No matching.
            Applies Split Rules for matched members.

            Modes:
              preview  → dry-run matching, returns JSON string with matched/unmatched arrays (no side effects)
              create   → process entries (respects entry_ids filter + forced_assignments)
              send_to_suspense → move given entry_ids to Suspense sheet

            Input JSON: {
              fy (optional, e.g. '26-27'),
              mode (optional, 'create' | 'preview' | 'send_to_suspense', default 'create'),
              generate_receipts (bool, default false),
              entry_ids (optional list of Entry_ID values to restrict processing),
              forced_assignments (optional dict of entry_id -> plot_no for unmatched entries)
            }
            Returns summary of matched and unmatched entries (text in create mode, JSON in preview mode)."""
            import json as _json
            data = _parse_action_input(input_str or "{}")
            mode = str(data.get("mode", "create") or "create").strip()
            settings = self.data_provider.get_settings()
            fy = data.get("fy", "") or settings.get("Current_FY", "26-27")
            generate_receipts = str(data.get("generate_receipts", "false")).lower() in ("true", "1", "yes")
            entry_ids = data.get("entry_ids", None)
            forced_assignments = data.get("forced_assignments", None) or {}
            from_date, to_date = _fy_date_range(fy)
            if not from_date:
                return f"Invalid FY format: {fy}"

            # ── send_to_suspense mode ────────────────────────────────
            if mode == "send_to_suspense":
                if not entry_ids:
                    return "entry_ids required for send_to_suspense mode."
                moved = 0
                for eid in entry_ids:
                    acct = None
                    try:
                        all_acct = self.data_provider.get_accounts_entries()
                        for a in all_acct:
                            if int(a.get("Entry_ID", 0)) == eid:
                                acct = a
                                break
                    except Exception:
                        pass
                    if not acct:
                        continue
                    self.data_provider.update_accounts_entry(eid, {"Status": "Suspended"})
                    self.data_provider.add_suspense_entry({
                        "Date": str(acct.get("Date", "") or ""),
                        "Particulars": str(acct.get("Particulars", "") or "")[:200],
                        "Amount": float(acct.get("Deposit", 0) or 0),
                        "Transaction_ID": str(acct.get("Transaction_ID", "") or ""),
                        "Transaction_Type": str(acct.get("Transaction_Type", "") or ""),
                        "Description": f"Moved from Accounts Entry #{eid}",
                    })
                    moved += 1
                return f"✅ {moved} entries moved to Suspense."

            # ── Preview / Create modes ───────────────────────────────
            is_preview = (mode == "preview")

            # For create mode, fetch only Pending entries.
            # For preview mode, also include Unmatched entries so the user can assign them.
            if is_preview:
                all_statuses = ["Pending", "Unmatched"]
                all_entries_raw = []
                for s in all_statuses:
                    all_entries_raw.extend(self.data_provider.get_accounts_entries(status=s) or [])
            else:
                all_entries_raw = self.data_provider.get_accounts_entries(status="Pending") or []
                # Also fetch Unmatched entries referenced by forced_assignments
                if forced_assignments:
                    forced_ids = set()
                    for k in forced_assignments:
                        try:
                            forced_ids.add(int(k))
                        except (ValueError, TypeError):
                            pass
                    if forced_ids:
                        extra = self.data_provider.get_accounts_entries(status="Unmatched") or []
                        for e in extra:
                            if int(e.get("Entry_ID", 0)) in forced_ids:
                                all_entries_raw.append(e)

            all_entries = []
            seen_ids = set()
            for e in all_entries_raw:
                eid = int(e.get("Entry_ID", 0))
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    all_entries.append(e)

            if not all_entries:
                return "No Pending entries in Accounts sheet."

            def _sortable(dd):
                try:
                    p = dd.split("-")
                    return f"{p[2]}-{p[1]}-{p[0]}"
                except Exception:
                    return dd
            from_key = _sortable(from_date) if from_date else ""
            to_key = _sortable(to_date) if to_date else ""
            fy_filtered = []
            for e in all_entries:
                ed = str(e.get("Date", "") or "")
                if from_key <= _sortable(ed) <= to_key:
                    fy_filtered.append(e)

            if not fy_filtered:
                return f"No entries within FY {fy} ({from_date} to {to_date})."

            deposit_entries = [e for e in fy_filtered if e.get("Deposit") and float(e["Deposit"]) > 0]
            if not deposit_entries:
                return f"No deposit entries found in FY {fy}."

            # Restrict to given entry_ids if provided
            if entry_ids is not None:
                entry_ids_set = set(int(x) for x in entry_ids)
                # Ensure forced_assignment IDs are included in the filter
                if forced_assignments:
                    for k in forced_assignments:
                        try:
                            entry_ids_set.add(int(k))
                        except (ValueError, TypeError):
                            pass
                deposit_entries = [e for e in deposit_entries if int(e.get("Entry_ID", 0)) in entry_ids_set]
                if not deposit_entries:
                    return "No matching deposit entries for the given entry_ids."

            members = self.data_provider.get_all_members()
            matched_results = []
            unmatched_entries = []
            pending_ledger = []

            import importlib
            import tools.pdf_parser
            importlib.reload(tools.pdf_parser)
            from tools.pdf_parser import _ngram_match, _extract_search_tokens

            auto_income = 0
            for acct_entry in deposit_entries:
                date = str(acct_entry.get("Date", "") or "")
                amount = float(acct_entry["Deposit"])
                particulars = str(acct_entry.get("Particulars", "") or "")
                txn_type = str(acct_entry.get("Transaction_Type", "") or "")
                txn_id = str(acct_entry.get("Transaction_ID", "") or "")
                entry_id = int(acct_entry.get("Entry_ID", 0))

                # Auto-record bank interest as Income (skip member matching)
                if "Int.Pd" in particulars:
                    if not is_preview:
                        self.data_provider.add_interest_income({
                            "Date": date,
                            "Particulars": particulars[:200],
                            "Amount": amount,
                            "Transaction_ID": txn_id,
                            "Transaction_Type": txn_type,
                            "Source_File": acct_entry.get("Source_File", ""),
                            "Accounts_Entry_ID": entry_id,
                        })
                        self.data_provider.update_accounts_entry(entry_id, {"Status": "Skipped"})
                    auto_income += 1
                    continue

                # Check forced assignment
                forced_plot = forced_assignments.get(str(entry_id)) or forced_assignments.get(entry_id)
                if forced_plot:
                    forced_member = self.data_provider.get_member_by_plot_no(str(forced_plot).strip())
                    if forced_member:
                        best_match = forced_member
                        best_reason = f"user-assigned plot {forced_plot}"
                        best_score = 100
                    else:
                        if not is_preview:
                            self.data_provider.update_accounts_entry(entry_id, {"Status": "Unmatched"})
                        unmatched_entries.append({
                            "date": date, "amount": amount, "particulars": particulars,
                            "txn_type": txn_type, "txn_id": txn_id, "entry_id": entry_id,
                            "status": "unmatched",
                        })
                        continue
                else:
                    best_match = None
                    best_reason = ""
                    best_score = 0

                search_identifiers = []
                if not forced_plot:
                    search_tokens, search_identifiers = _extract_search_tokens(particulars, txn_type, txn_id)

                    # Phase 3a: Reference store match
                    ref_match = None
                    ref_reason = ""
                    for token in search_tokens:
                        candidate = self.data_provider.find_member_by_identifier(token)
                        if candidate:
                            ref_match = candidate
                            ref_reason = f"known identifier '{token}'"
                            break

                    if ref_match:
                        best_match = ref_match
                        best_reason = ref_reason
                        best_score = 100

                    # Phase 3b: Fuzzy matching
                    if best_score < 100:
                        for member in members:
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
                                            if len(token) > 2 and _ngram_match(token, surname):
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
                                    if len(nt) > 2 and t != nt and _ngram_match(t, nt):
                                        fuzzy_common.add(t)
                                        break
                            deduped = fuzzy_common - common
                            if deduped:
                                score += 3 * len(deduped)
                                reason_parts.append(f"name_fuzzy:{','.join(deduped)}")

                            # Substring/prefix: short search token is contained in name token (or vice versa)
                            # Catches "SHW"→"SHWETA", "FUT"→"FUTANE" where ngram is too short
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

                            if score > best_score:
                                best_score = score
                                best_match = member
                                best_reason = ", ".join(reason_parts)

                if best_match and best_score >= 5 and amount:
                    mid = best_match["ID"]

                    fy_local = get_fy_from_date(date)
                    vch_no = self.data_provider.get_next_voucher_number()
                    receipt_id = f"{fy_local}-{str(vch_no).zfill(3)}"

                    if not is_preview:
                        self.data_provider.update_accounts_entry(entry_id, {"Status": "Matched"})
                        pending_ledger.append((mid, {
                            "Date": date,
                            "Particulars": f"By {particulars[:60]}",
                            "Vch_Type": "Journal",
                            "Vch_No": vch_no,
                            "Debit": None,
                            "Credit": amount,
                            "Description": f"Receipt {receipt_id} — Bank Statement ({txn_type})",
                            "Transaction_Type": txn_type,
                            "Transaction_ID": txn_id,
                        }))

                    if not is_preview and generate_receipts:
                        from tools.pdf_generator import create_simple_receipt_pdf
                        receipt_dir = config.RECEIPTS_DIR / fy_local
                        receipt_dir.mkdir(parents=True, exist_ok=True)
                        plot_str = str(best_match.get("Plot_No", "") or "")
                        plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
                        rpath = receipt_dir / f"Receipt_{plot_part}_{receipt_id}.pdf"
                        receipt_data = {
                            "receipt_id": receipt_id,
                            "date": date,
                            "member_name": best_match.get("Plot_Owner_Name", ""),
                            "plot_no": plot_str,
                            "amount": amount,
                            "transaction_id": txn_id or "N/A",
                            "transaction_type": txn_type,
                            "outstanding_balance": 0,
                            "payment_details": particulars[:120],
                        }
                        create_simple_receipt_pdf(rpath, receipt_data)

                    # Split Rules
                    if not is_preview:
                        split_group = self.data_provider.get_split_group_for_member(mid)
                        if split_group:
                            # Remove full-amount entry, replace with per_head for all group members
                            pending_ledger.pop()
                            split_amt = round(amount / len(split_group), 2)
                            for smid in split_group:
                                orig_vch = vch_no
                                svch = self.data_provider.get_next_voucher_number()
                                sfy = get_fy_from_date(date)
                                srid = f"{sfy}-{str(svch).zfill(3)}"
                                pending_ledger.append((smid, {
                                    "Date": date,
                                    "Particulars": f"By Split from {best_match.get('Plot_Owner_Name', '')} ({particulars[:40]})",
                                    "Vch_Type": "Journal",
                                    "Vch_No": svch,
                                    "Debit": None,
                                    "Credit": split_amt,
                                    "Description": f"Split from #{orig_vch} (src:{mid})",
                                    "Transaction_Type": "SPLIT",
                                    "Transaction_ID": f"SPLIT-{receipt_id}",
                                }))
                                if generate_receipts:
                                    sdir = config.RECEIPTS_DIR / sfy
                                    sdir.mkdir(parents=True, exist_ok=True)
                                    spath = sdir / f"Receipt_Plot_No_{str(smid).zfill(2)}_{srid}.pdf"
                                    sdata = {
                                        "receipt_id": srid,
                                        "date": date,
                                        "member_name": "Split Receipt",
                                        "plot_no": "",
                                        "amount": split_amt,
                                        "transaction_id": f"SPLIT-{receipt_id}",
                                        "transaction_type": "SPLIT",
                                        "outstanding_balance": 0,
                                        "payment_details": f"Split from {receipt_id} — {particulars[:60]}",
                                    }
                                    create_simple_receipt_pdf(spath, sdata)
                        # Record identifiers (non-preview only)
                        for id_value, id_type in search_identifiers:
                            self.data_provider.record_payment_reference(mid, id_type, id_value, date, transaction_type=txn_type)

                    matched_results.append({
                        "date": date,
                        "amount": amount,
                        "entry_id": entry_id,
                        "member_name": best_match.get("Plot_Owner_Name", ""),
                        "plot_no": best_match.get("Plot_No", ""),
                        "member_id": mid,
                        "receipt_id": receipt_id,
                        "reason": best_reason,
                        "has_pdf": generate_receipts,
                        "particulars": particulars,
                        "status": "matched",
                    })
                else:
                    if not is_preview:
                        self.data_provider.update_accounts_entry(entry_id, {"Status": "Unmatched"})
                    unmatched_entries.append({
                        "date": date,
                        "amount": amount,
                        "particulars": particulars,
                        "txn_type": txn_type,
                        "txn_id": txn_id,
                        "entry_id": entry_id,
                        "status": "unmatched",
                    })

            if not is_preview and pending_ledger:
                self.data_provider.add_ledger_entries(pending_ledger)

            if is_preview:
                return _json.dumps({
                    "matched": matched_results,
                    "unmatched": unmatched_entries,
                    "auto_income": auto_income,
                    "summary": f"Preview for FY {fy}: {len(matched_results)} matched, "
                               f"{len(unmatched_entries)} unmatched, {auto_income} interest income",
                })

            lines = [f"Ledger creation for FY {fy} completed:"]
            lines.append(f"  ✓ Matched: {len(matched_results)} entries")
            if auto_income:
                lines.append(f"  📈 Interest Income (auto): {auto_income} entries")
            if matched_results:
                for r in matched_results:
                    lines.append(f"    • ₹{r['amount']:>8,.2f} → {r['member_name']} (Plot {r['plot_no']}) "
                                 f"— {r['reason']}")
            lines.append(f"  ? Unmatched: {len(unmatched_entries)} entries")
            if unmatched_entries:
                for u in unmatched_entries:
                    lines.append(f"    • {u['date']} | ₹{u['amount']:>8,.2f} | {u['particulars']}")
            return "\n".join(lines)

        self.register_tool(create_ledger_from_accounts, "create_ledger_from_accounts",
                           "Create Ledger entries from Pending deposits in the Accounts sheet. "
                           "Matches deposits to members using known identifiers, fuzzy name/phone/email matching. "
                           "Applies Split Rules for matched members. "
                           "Modes: 'preview' (dry-run, returns JSON with matched/unmatched, no side effects), "
                           "'create' (process entries, respects entry_ids + forced_assignments), "
                           "'send_to_suspense' (move entry_ids to Suspense sheet). "
                           "Input JSON: fy (optional), mode (default 'create'), "
                           "generate_receipts (bool, default false), "
                           "entry_ids (optional list of ints), "
                           "forced_assignments (optional dict entry_id->plot_no). "
                           "Returns summary of matched and unmatched (text in create mode, JSON in preview mode).")

        # ── Register all tools ────────────────────────────────────────

        self.register_tool(get_member_details, "get_member_details",
                           "Look up a member by plot_no, member_id, or name. "
                           "Returns JSON with keys: member_id, name, plot_no, outstanding. "
                           "Name lookup: pass a name string (e.g. 'Mrs. Dhanashri Deshpande') to find all "
                           "matching members. Returns a list if multiple members share the same name "
                           "(multi-plot owners). "
                           "Use this FIRST to resolve plot numbers or names to member_ids before "
                           "calling other tools. "
                           "The member_id from the output is accepted by all tools that take member_id.")

        self.register_tool(extract_payment_from_screenshot, "extract_payment",
                           "Extract payment details (amount, date, transaction_id) from a payment screenshot "
                           "using vision AI. Input: file path to the image. Returns JSON with parsed fields. "
                           "Pass extracted fields to generate_receipt to record the payment.")

        self.register_tool(batch_process_historical_receipts, "batch_process_historical_receipts",
                           "Process ALL historical receipt images from a folder. "
                           "Scans folder, runs OCR on each image, generates receipt PDFs, and updates ledgers. "
                           "Input JSON keys: folder_path (optional, defaults to Historical_Receipts folder), "
                           "default_plot_no (optional for fallback). "
                           "Returns summary of processed receipts (added/duplicates/skipped/failed).")

        self.register_tool(generate_receipt, "generate_receipt",
                           "Generate a receipt for a member payment (adds a credit entry to the ledger "
                           "+ creates receipt PDF). "
                           "For cash entries where no PDF is needed, use add_ledger_entry with "
                           "entry_type='CREDIT' instead (lighter, no PDF). "
                           "Input JSON keys: member_id (or plot_no), amount, date (DD-MM-YYYY), "
                           "transaction_id (optional for bank ref), "
                           "transaction_type (optional: NEFT/UPI/CHQ/IMPS/CASH), "
                           "particulars (optional), force (optional bool to bypass duplicate check). "
                           "The receipt reference follows the pattern RCPT-<FY>-<VchNo>. "
                           "To reduce the amount after creation (e.g., for splitting), "
                           "call update_ledger_entry with a lower credit value. "
                           "Outstanding is auto-updated.")

        self.register_tool(regenerate_receipt, "regenerate_receipt",
                           "Regenerate a receipt PDF from an existing ledger entry. "
                           "Input JSON keys: member_id, vch_no (both required). "
                           "Optionally add new_member_id to MOVE the entry to a different member. "
                           "Useful when fixing a receipt that was assigned to the wrong member. "
                           "To SPLIT instead (keep original at reduced amount + create new entry for other member), "
                           "first call update_ledger_entry to reduce the amount, "
                           "then call generate_receipt for the new entry.")

        self.register_tool(generate_consolidated_receipt, "generate_consolidated_receipt",
                           "Generate a consolidated receipt PDF for a member listing all receipts in a FY. "
                           "Input JSON keys: member_id (required), fy (optional, e.g. '26-27'). "
                           "Returns the PDF filename and total amount of receipts included.")

        self.register_tool(get_member_ledger, "get_member_ledger",
                           "View the complete ledger for a member. "
                           "Input: member_id or plot_no. "
                           "OUTPUT includes: Date, Vch_No (use with update_ledger_entry / delete_ledger_entry), "
                           "Type (RECEIPT/INVOICE/DEMAND), Particulars, "
                           "Txn_ID (use to match entries across members — same Txn_ID in both ledgers "
                           "indicates a split payment), Amount (Cr/Dr), and Description. "
                           "Use the Vch_No from the output to reference entries for updates or deletion. "
                           "Use the Txn_ID to identify which entries are split across two members' ledgers.")

        self.register_tool(get_outstanding_summary, "get_outstanding_summary",
                           "Get outstanding balance summary for ALL members. "
                           "Shows each member's plot, name, and balance (demand if negative, surplus if positive). "
                           "Outstanding is auto-updated after every ledger write operation "
                           "(generate_receipt, delete_ledger_entry, update_ledger_entry, etc.) — "
                           "no manual recalculation needed.")

        self.register_tool(update_ledger_entry, "update_ledger_entry",
                           "Modify fields of an existing ledger entry — amount (credit/debit), "
                           "particulars, date, transaction_id, description. "
                           "Outstanding is auto-recalculated after update. "
                           "Use this to reduce an entry's credit when splitting a payment across two members: "
                           "call update_ledger_entry to halve the amount, "
                           "then call generate_receipt to add the other half to the second member. "
                           "Input JSON keys: member_id (required), vch_no (required), "
                            "plus any of: credit, debit, particulars, date, transaction_id, description. "
                           "Example input: member_id=5, vch_no=42, credit=5000")

        self.register_tool(delete_ledger_entry, "delete_ledger_entry",
                            "Delete ANY ledger entry by member_id and vch_no — works for receipts, invoices, "
                           "demands, or any Vch_Type. Outstanding is auto-recalculated after deletion. "
                           "Use this to remove an entry before recreating it with adjusted amounts "
                           "(e.g., when re-splitting a payment that was assigned to the wrong member). "
                            "Input JSON keys: member_id, vch_no. "
                           "Example input: member_id=5, vch_no=42")

        self.register_tool(add_ledger_entry, "add_ledger_entry",
                           "Add an arbitrary debit or credit entry to a member's ledger (no PDF generated). "
                           "Use for manual/cash entries, adjustments, or entries that don't need a document. "
                           "Input JSON keys: member_id or plot_no (required), "
                           "amount (required, positive number), "
                           "entry_type (required, 'DEBIT' or 'CREDIT'), "
                           "date (DD-MM-YYYY, optional, defaults to today), "
                           "particulars (optional), "
                           "transaction_type (optional: CASH/CHQ/NEFT/UPI/etc.), "
                           "description (optional internal note), "
                           "transaction_id (optional). "
                           "Outstanding is auto-updated. "
                            "For PDF-generating receipts with auto reference IDs, use generate_receipt instead.")

        self.register_tool(record_manual_payments, "record_manual_payments",
                           "Process a BATCH of manual payment records — create CREDIT entries for all. "
                           "Use this when the user provides a LIST of payments to record "
                           "(e.g. '14 people paid amounts for Shivaji salary'). "
                           "Handles member resolution (by plot_no or fuzzy name match), multi-plot splitting, "
                           "and skips duplicates automatically. "
                           "For a SINGLE entry, use add_ledger_entry instead. "
                           "Input JSON: {\"entries\": [{\"name\": \"...\", \"amount\": 2000, "
                           "\"date\": \"DD-MM-YYYY\", \"particulars\": \"...\", "
                           "\"plots\": [\"38\",\"39\"]}, ...]}. "
                           "Returns a per-entry summary of created/skipped/failed results.")

        self.register_tool(add_demand_entry, "add_demand_entry",
                           "Add a yearly maintenance demand (debit entry) for a single member. "
                           "Use this to record new annual maintenance charges. "
                           "Input JSON keys: member_id or plot_no (required), "
                           "amount (optional, defaults to configured AUTO_ENTRY_AMOUNT), "
                           "fy (optional, e.g. '26-27'), date (optional, defaults to 1-Apr of FY). "
                           "Skips if a demand for the same FY already exists. "
                           "Outstanding is auto-updated.")

        self.register_tool(batch_add_demand_entries, "batch_add_demand_entries",
                           "Add yearly maintenance demand entries for ALL members (or specific plots) at once. "
                           "Input JSON keys: amount (optional, defaults to configured AUTO_ENTRY_AMOUNT), "
                           "fy (optional, e.g. '26-27'), plots (optional list, e.g. [1,2,3] — omit for all). "
                           "Skips members that already have a demand for the given FY. "
                           "Outstanding is auto-updated for each member.")

        self.register_tool(generate_invoice, "generate_invoice",
                           "Generate a single invoice PDF AND auto-add a debit entry to the ledger. "
                           "CRITICAL: ALWAYS pass from_date & to_date in DD-MM-YYYY when the user mentions a specific period "
                           "(e.g. 'Nov 21 to Mar 22' -> from_date='01-11-2021', to_date='31-03-2022'). "
                           "Without these, it defaults to the current FY. "
                           "Input JSON keys: member_id or plot_no (required), "
                           "from_date (DD-MM-YYYY), to_date (DD-MM-YYYY), "
                           "invoice_date (DD-MM-YYYY, defaults to today), fy (fallback if from/to missing). "
                           "Outstanding is auto-updated.")

        self.register_tool(regenerate_invoice, "regenerate_invoice",
                           "Regenerate an invoice PDF from an existing ledger entry using current rates. "
                           "Input JSON keys: member_id, vch_no (both required). "
                           "Optionally add new_member_id to MOVE the invoice to a different member. "
                           "Useful when rates have changed and an invoice needs re-issuing. "
                           "Outstanding is auto-updated.")

        self.register_tool(delete_invoice, "delete_invoice",
                           "Delete an invoice entry AND its PDF from the ledger. "
                           "Only works for invoice-type entries (Vch_Type=INVOICE). "
                           "For other entry types (receipts, demands), use delete_ledger_entry instead. "
                           "Input JSON keys: member_id, vch_no. "
                           "Outstanding is auto-updated.")

        self.register_tool(batch_generate_invoices, "batch_generate_invoices",
                           "Generate invoice PDFs for ALL members (or specific plots) AND auto-add debit entries. "
                           "CRITICAL: ALWAYS pass from_date & to_date in DD-MM-YYYY when the user mentions a specific period "
                           "(e.g. 'November 21 to March 22' -> from_date='01-11-2021', to_date='31-03-2022'). "
                           "Without these, it defaults to the current FY (12 months). "
                           "Input JSON keys: "
                           "from_date (DD-MM-YYYY), to_date (DD-MM-YYYY), "
                           "invoice_date (DD-MM-YYYY, defaults to today), "
                           "fy (fallback if from/to missing), "
                           "plots (optional list, e.g. [1,2,3] — omits for all members). "
                           "Skips members that already have an invoice for the given period. "
                           "Outstanding is auto-updated for each member.")

        self.register_tool(trigger_april_entries, "trigger_april_entries",
                           "Trigger yearly maintenance demand entries for all members (legacy tool). "
                           "Input JSON key: fy (optional, defaults to current FY). "
                           "Skips members that already have a demand for the FY. "
                           "Outstanding is auto-updated.")

        self.register_tool(get_current_settings, "get_current_settings",
                           "View current system settings and rates. "
                           "Returns all key-value pairs: Current_FY, Repair_Fund_Rate, "
                           "Service_Charges_Rate, Sinking_Fund_Rate, etc. "
                           "Use this to check rates before generating invoices.")

        self.register_tool(add_new_member, "add_new_member",
                           "Add a new member to the system. "
                           "Input JSON keys: plot_no (required), name (required), "
                           "email (optional), phone (optional). "
                           "Returns the new member's ID.")

        self.register_tool(update_rates, "update_rates",
                           "Update invoice rates. "
                           "Input JSON keys: repair (Repair_Fund_Rate), "
                           "service (Service_Charges_Rate), sinking (Sinking_Fund_Rate) — all optional. "
                            "Only provided rates are updated; others remain unchanged. "
                            "Example input: repair=150, service=900, sinking=20")

        def reset_and_rebuild_all(input_str: str = None):
            """Full reset: clear all auto-generated data, re-parse all bank
            statement PDFs in numeric-prefix order, rebuild Processed_Statements.
            Int.Pd entries are auto-recorded as Interest_Income.
            Preserved: Members, Settings, Split_Rules, Payment_References."""
            import hashlib
            from tools.pdf_parser import extract_text_from_pdf, detect_format

            params = json.loads(input_str or "{}") if input_str else {}
            pwd = params.get("password", config.BANK_STMT_PASSWORD) or ""

            cleared = self.data_provider.clear_all_auto_data()
            lines = []
            cleared_summary = " | ".join(f"{k}: {v}" for k, v in cleared.items())
            lines.append(f"Cleared: {cleared_summary}")
            lines.append("")

            pdf_dir = config.BANK_STATEMENTS_DIR
            pdfs = sorted(pdf_dir.glob("*.pdf"), key=lambda f: (
                (int(re.match(r"^(\d+)", f.stem).group(1)), "")
                if re.match(r"^(\d+)", f.stem) else (float("inf"), f.name.lower())
            ))

            errors = []
            total_e = 0
            for pdf_path in pdfs:
                try:
                    raw_text = extract_text_from_pdf(str(pdf_path), pwd)
                except Exception as e:
                    errors.append(f"'{pdf_path.name}': {e}")
                    continue
                fmt = detect_format([l.strip() for l in raw_text.split("\n") if l.strip()])
                try:
                    result_text = parse_statement_to_accounts(json.dumps({
                        "statement": raw_text,
                        "filename": pdf_path.name,
                    }))
                except Exception as e:
                    errors.append(f"'{pdf_path.name}': parse error — {e}")
                    continue
                file_hash = hashlib.sha256(open(pdf_path, "rb").read()).hexdigest()[:16]
                self.data_provider.record_processed_statement(
                    filename=pdf_path.name,
                    date_range=f"from_{pdf_path.stem}",
                    entry_count=0,
                    fmt=fmt,
                    file_hash=file_hash,
                )
                lines.append(f"  {pdf_path.name}:")
                for rl in result_text.strip().split("\n"):
                    lines.append(f"    {rl}")
                total_e += 1

            if errors:
                lines.append("")
                lines.append(f"⚠️ {len(errors)} error(s):")
                for err in errors:
                    lines.append(f"  ❌ {err}")

            self.data_provider.refresh_reports_sheet()
            lines.append("")
            lines.append(f"✅ Rebuilt {total_e}/{len(pdfs)} files successfully.")
            return "\n".join(lines)

        self.register_tool(reset_and_rebuild_all, "reset_and_rebuild_all",
                           "Full reset and rebuild from bank statement PDFs. "
                           "Clears all auto-generated data (Accounts, Ledger, Expenses, "
                           "Interest_Income, Suspense_Entries, Reports, Processed_Statements), "
                           "preserves Members, Settings, Split_Rules, Payment_References. "
                           "Re-parses all PDFs from data/bank_statements/ in numeric-prefix order. "
                           "Int.Pd entries auto-recorded as Interest_Income. "
                           "No input required — call with empty JSON object.")
