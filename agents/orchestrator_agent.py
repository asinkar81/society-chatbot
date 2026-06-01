"""
Orchestrator Agent — combines all agent capabilities for multi-step workflows.
The LLM plans and executes a sequence of tool calls, passing outputs between steps.
"""
import json
import re
import csv
from pathlib import Path
from datetime import datetime, timedelta
from agents.base_agent import BaseAgent
from data_providers.base_provider import DataProvider
from file_storage.base_storage import FileStorage
from tools.ocr_processor import OCRProcessor
from tools.pdf_generator import create_simple_receipt_pdf, create_simple_invoice_pdf
from utils.converters import (
    get_current_date, get_fy_string, get_due_date, get_bill_period,
    number_to_words_inr,
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


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        v = float(val)
        return 0.0 if v != v else v
    except (ValueError, TypeError):
        return 0.0


class OrchestratorAgent(BaseAgent):
    """Agent that can handle multi-step workflows by combining all tool capabilities."""

    def __init__(self, data_provider: DataProvider, file_storage: FileStorage):
        super().__init__(
            name="Orchestrator Agent",
            description="Handles all society management tasks including multi-step workflows",
            data_provider=data_provider,
            file_storage=file_storage,
        )
        self.ocr_processor = OCRProcessor()
        self.get_tools()

    def get_tools(self):
        """Register all tools for the orchestrator."""

        # ── Member tools ──────────────────────────────────────────────

        def get_member_details(input_str: str = None):
            """Get member details by ID or Plot No. Use this FIRST to resolve a plot number to a member_id before calling other tools. Input: plot_no, member_id, or name."""
            data = _parse_action_input(input_str or "")
            identifier = (str(data.get("member_id") or "") or
                          str(data.get("plot_no") or "") or
                          str(data.get("plot") or "") or
                          str(data.get("_0") or "") or
                          (input_str or ""))
            if not identifier:
                return "Please provide a member ID or plot number"
            raw = _normalize_plot_id(identifier)
            try:
                member = self.data_provider.get_member(int(raw))
                if not member:
                    member = self.data_provider.get_member_by_plot_no(raw)
            except ValueError:
                member = self.data_provider.get_member_by_plot_no(raw)
            if not member:
                return f"Member not found for: {identifier}"
            o = self.data_provider.get_current_outstanding(member["ID"])
            return json.dumps({
                "member_id": member["ID"],
                "name": member.get("Plot_Owner_Name"),
                "plot_no": member.get("Plot_No"),
                "outstanding": o,
            })

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
                    fy = get_fy_string()
                    receipt_no = self.data_provider.get_next_voucher_number()
                    receipt_id = f"{fy}-{str(receipt_no).zfill(3)}"

                    receipt_data = {
                        "receipt_id": receipt_id,
                        "date": date,
                        "member_name": member.get("Plot_Owner_Name", ""),
                        "plot_no": member.get("Plot_No", ""),
                        "amount": amount,
                        "transaction_id": txn_id or "N/A",
                        "outstanding_balance": 0,
                    }
                    receipt_dir = config.RECEIPTS_DIR / fy
                    receipt_dir.mkdir(parents=True, exist_ok=True)
                    rpath = receipt_dir / f"Receipt_{receipt_id}.pdf"
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

                    vch_no = self.data_provider.get_next_voucher_number()
                    self.data_provider.add_ledger_entry(member_id, {
                        "Date": date,
                        "Particulars": "By Payment Received (Historical)",
                        "Vch_Type": "Journal",
                        "Vch_No": vch_no,
                        "Debit": None,
                        "Credit": amount,
                        "Description": f"Receipt {receipt_id} — Historical",
                        "Transaction_ID": txn_id or None,
                    })
                    o = self.data_provider.get_current_outstanding(member_id)
                    self.data_provider.update_member(member_id, {"Current_Outstanding": o})

                    results.append(f"  ✓ {img_path.name}: ₹{amount} → {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}) → Receipt {receipt_id}")

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
            """Generate a receipt PDF and update the ledger. Input JSON keys: member_id (or plot_no), amount, date, transaction_id (optional), force (optional bool to bypass duplicate check). Example: {"member_id": 2, "amount": 3000, "date": "05-05-2026", "transaction_id": "UPI123"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            amount = data.get("amount")
            date = data.get("date")
            transaction_id = data.get("transaction_id")
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

            fy = get_fy_string()
            receipt_no = self.data_provider.get_next_voucher_number()
            receipt_id = f"{fy}-{str(receipt_no).zfill(3)}"

            current_outstanding = self.data_provider.get_current_outstanding(member_id)
            new_outstanding = current_outstanding + amount

            receipt_data = {
                "receipt_id": receipt_id,
                "date": date,
                "member_name": member.get("Plot_Owner_Name", "Unknown"),
                "plot_no": member.get("Plot_No", "N/A"),
                "amount": amount,
                "transaction_id": transaction_id or "N/A",
                "outstanding_balance": new_outstanding,
            }

            receipt_dir = config.RECEIPTS_DIR / fy
            receipt_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = receipt_dir / f"Receipt_{receipt_id}.pdf"

            success = create_simple_receipt_pdf(receipt_path, receipt_data)
            if not success:
                return f"Failed to generate receipt PDF for member {member_id}"

            vch_no = self.data_provider.get_next_voucher_number()
            ledger_entry = {
                "Date": date,
                "Particulars": "By Payment Received",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": None,
                "Credit": amount,
                "Description": f"Receipt {receipt_id}",
                "Transaction_ID": transaction_id or None,
            }
            self.data_provider.add_ledger_entry(member_id, ledger_entry)
            self.data_provider.update_member(member_id, {"Current_Outstanding": new_outstanding})

            return f"Receipt {receipt_id} generated for {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}) for ₹{amount:,.2f}. Ledger updated."

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

            lines = [f"\n{'='*80}", f"LEDGER — {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')})", f"{'='*80}"]
            lines.append(f"{'Date':<12} {'Particulars':<30} {'Amount':>12}")
            lines.append(f"{'-'*54}")
            for e in entries:
                amt = _safe_float(e.get("Credit")) - _safe_float(e.get("Debit"))
                label = "Credit" if amt >= 0 else "Debit "
                lines.append(f"{str(e.get('Date','')):<12} {str(e.get('Particulars',''))[:30]:<30} {abs(amt):>11,.2f} ({label})")
            o = self.data_provider.get_current_outstanding(member_id)
            lines.append(f"{'-'*54}")
            label = "SURPLUS" if o >= 0 else "DEMAND"
            lines.append(f"{'BALANCE':<42} ₹{abs(o):>10,.2f} ({label})")
            lines.append(f"{'='*80}")
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
            return from_date, to_date, months, fy_input, get_bill_period()

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
            total = repair_amount + service_amount + sinking_amount + pending_interest

            # Payment received till date = sum of all credits in member's ledger
            ledger = self.data_provider.get_member_ledger(member_id)
            payment_received = sum(_safe_float(e.get("Credit")) for e in ledger)

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

            invoice_no = f"{int(member.get('Plot_No', 0)):03d}{inv_date.strftime('%m%d')}"
            due_date = (inv_date + timedelta(days=config.INVOICE_DUE_DAYS)).strftime("%d-%m-%Y")
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
                "payment_received_till_date": payment_received,
                "line_items": {
                    f"Repair & Maintenance Fund @ ₹{repair_rate:,.2f}/month × {months} months": repair_amount,
                    f"Service Charges @ ₹{service_rate:,.2f}/month × {months} months": service_amount,
                    f"Sinking Fund @ ₹{sinking_rate:,.2f}/month × {months} months": sinking_amount,
                    "Interest Penalty Charges": pending_interest,
                },
                "total_amount": total,
                "amount_in_words": number_to_words_inr(total),
            }
            invoice_dir = config.INVOICES_DIR / fy_str[:2]
            invoice_dir.mkdir(parents=True, exist_ok=True)
            invoice_filename = f"Invoice_{member.get('Plot_No', 'Unknown')}_{invoice_no}.pdf"
            invoice_path = invoice_dir / invoice_filename
            success = create_simple_invoice_pdf(invoice_path, invoice_data)
            if not success:
                return f"Failed to generate invoice for member {member_id}"

            # Add ledger entry (demand = debit) using invoice date
            vch_no = self.data_provider.get_next_voucher_number()
            ledger_entry = {
                "Date": invoice_date_input,
                "Particulars": "To Annual Maintenance Charges",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": total,
                "Credit": None,
                "Description": f"Invoice {invoice_no} FY {fy_str}",
            }
            self.data_provider.add_ledger_entry(member_id, ledger_entry)
            o = self.data_provider.get_current_outstanding(member_id)
            self.data_provider.update_member(member_id, {"Current_Outstanding": o})

            return f"Invoice {invoice_filename} generated for {member.get('Plot_Owner_Name')} for ₹{total:,.2f} ({months} months: {bill_period}). Outstanding: ₹{abs(o):,.2f} ({'demand' if o < 0 else 'surplus' if o > 0 else 'zero'})"

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
                total = repair_amount + service_amount + sinking_amount + pending_interest

                # Payment received till date = sum of all credits
                payment_received = sum(_safe_float(e.get("Credit")) for e in member_ledger)

                invoice_no = f"{int(member.get('Plot_No', 0)):03d}{inv_date.strftime('%m%d')}"
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
                    "payment_received_till_date": payment_received,
                    "line_items": {
                        f"Repair & Maintenance Fund @ ₹{repair_rate:,.2f}/month × {months} months": repair_amount,
                        f"Service Charges @ ₹{service_rate:,.2f}/month × {months} months": service_amount,
                        f"Sinking Fund @ ₹{sinking_rate:,.2f}/month × {months} months": sinking_amount,
                        "Interest Penalty Charges": pending_interest,
                    },
                    "total_amount": total,
                    "amount_in_words": number_to_words_inr(total),
                }
                invoice_dir = config.INVOICES_DIR / fy_str[:2]
                invoice_dir.mkdir(parents=True, exist_ok=True)
                invoice_filename = f"Invoice_{member.get('Plot_No', 'Unknown')}_{invoice_no}.pdf"
                invoice_path = invoice_dir / invoice_filename
                success = create_simple_invoice_pdf(invoice_path, invoice_data)
                if not success:
                    results.append(f"  ✗ {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}): PDF generation failed")
                    continue

                vch_no = self.data_provider.get_next_voucher_number()
                self.data_provider.add_ledger_entry(mid, {
                    "Date": invoice_date_input,
                    "Particulars": "To Annual Maintenance Charges",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": total,
                    "Credit": None,
                    "Description": f"Invoice {invoice_no} FY {fy_str}",
                })
                o = self.data_provider.get_current_outstanding(mid)
                self.data_provider.update_member(mid, {"Current_Outstanding": o})
                added += 1
                results.append(f"  ✓ {member.get('Plot_Owner_Name')} (Plot {member.get('Plot_No')}): ₹{total:,.2f} ({months} months: {bill_period}) → {invoice_filename}")

            summary = f"Batch invoice generation ({months} months: {bill_period}):\n" + "\n".join(results)
            summary += f"\n\nGenerated: {added}, Skipped (already exist): {skipped}"
            return summary

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
                entry = {
                    "Date": "1-4-2026",
                    "Particulars": "To Member Contribution Received",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": amount,
                    "Credit": None,
                    "Description": f"YEARLY MAINTENANCE DEMAND FY {fy}",
                }
                self.data_provider.add_ledger_entry(mid, entry)
                o = self.data_provider.get_current_outstanding(mid)
                self.data_provider.update_member(mid, {"Current_Outstanding": o})
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
            entry = {
                "Date": date,
                "Particulars": "To Annual Maintenance Charges",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": amount,
                "Credit": None,
                "Description": f"YEARLY MAINTENANCE DEMAND FY {fy}",
            }
            self.data_provider.add_ledger_entry(member_id, entry)
            o = self.data_provider.get_current_outstanding(member_id)
            self.data_provider.update_member(member_id, {"Current_Outstanding": o})
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
                entry = {
                    "Date": date,
                    "Particulars": "To Annual Maintenance Charges",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": amount,
                    "Credit": None,
                    "Description": f"YEARLY MAINTENANCE DEMAND FY {fy}",
                }
                self.data_provider.add_ledger_entry(mid, entry)
                o = self.data_provider.get_current_outstanding(mid)
                self.data_provider.update_member(mid, {"Current_Outstanding": o})
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
                "Current_Outstanding": 0,
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

        # ── Register all tools ────────────────────────────────────────

        self.register_tool(get_member_details, "get_member_details",
                           "Look up a member by plot_no or member_id. Returns member details including member_id. Use this FIRST to resolve plot numbers.")
        self.register_tool(extract_payment_from_screenshot, "extract_payment",
                           "Extract payment details from a screenshot image. Input: file path to image. Returns JSON with amount, date, transaction_id.")
        self.register_tool(batch_process_historical_receipts, "batch_process_historical_receipts",
                           "Process ALL historical receipt images from a folder. Scans folder, runs OCR on each image, generates receipt PDFs, and updates ledgers. Input JSON: folder_path (optional, defaults to Historical_Receipts folder), default_plot_no (optional for fallback).")
        self.register_tool(generate_receipt, "generate_receipt",
                           "Generate a single receipt PDF and update the ledger. Input JSON: member_id, amount, date, transaction_id (optional). Use get_member_details first to get member_id.")
        self.register_tool(get_member_ledger, "get_member_ledger",
                           "View the complete ledger for a member. Input: member_id or plot_no. Shows all transactions with credit/debit and the current balance.")
        self.register_tool(get_outstanding_summary, "get_outstanding_summary",
                           "Get outstanding balance summary for ALL members. Shows who owes money (demand) and who has overpaid (surplus).")
        self.register_tool(add_demand_entry, "add_demand_entry",
                           "Add a yearly maintenance demand (debit entry) for a single member. Input JSON: member_id or plot_no, amount (optional), fy (optional). Use this to record new annual maintenance charges.")
        self.register_tool(batch_add_demand_entries, "batch_add_demand_entries",
                           "Add yearly maintenance demand entries for ALL members (or a specific list of plots) at once. Input JSON: amount (optional), fy (optional), plots (optional list).")
        self.register_tool(generate_invoice, "generate_invoice",
                           "Generate a single invoice PDF AND auto-add a debit entry to the ledger. "
                           "CRITICAL: ALWAYS pass from_date & to_date in DD-MM-YYYY when the user mentions a specific period "
                           "(e.g. 'Nov 21 to Mar 22' -> from_date='01-11-2021', to_date='31-03-2022'). "
                           "Without these, it defaults to the current FY. "
                           "Input JSON keys: member_id or plot_no (required), "
                           "from_date (DD-MM-YYYY, e.g. '01-11-2021'), to_date (DD-MM-YYYY, e.g. '31-03-2022'), "
                           "invoice_date (DD-MM-YYYY, defaults to today), fy (fallback if from/to missing).")
        self.register_tool(batch_generate_invoices, "batch_generate_invoices",
                           "Generate invoice PDFs for ALL members (or specific plots) AND auto-add debit entries. "
                           "CRITICAL: ALWAYS pass from_date & to_date in DD-MM-YYYY when the user mentions a specific period "
                           "(e.g. 'November 21 to March 22' -> from_date='01-11-2021', to_date='31-03-2022'). "
                           "Without these, it defaults to the current FY (12 months). "
                           "Input JSON keys: "
                           "from_date (DD-MM-YYYY, e.g. '01-11-2021'), "
                           "to_date (DD-MM-YYYY, e.g. '31-03-2022'), "
                           "invoice_date (DD-MM-YYYY, defaults to today), "
                           "fy (fallback if from/to missing), "
                           "plots (optional list, e.g. [1,2,3] — omits for all).")
        self.register_tool(trigger_april_entries, "trigger_april_entries",
                           "Trigger yearly maintenance demand entries for all members (legacy tool).")
        self.register_tool(get_current_settings, "get_current_settings",
                           "View current system settings and rates.")
        self.register_tool(add_new_member, "add_new_member",
                           "Add a new member to the system. Input JSON: plot_no, name, email (optional), phone (optional).")
        self.register_tool(update_rates, "update_rates",
                           "Update invoice rates. Input JSON: repair, service, sinking (all optional).")
