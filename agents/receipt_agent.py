"""
Receipt generation agent
"""
import json
import re
from agents.base_agent import BaseAgent
from data_providers.base_provider import DataProvider
from file_storage.base_storage import FileStorage
from tools.ocr_processor import OCRProcessor
from tools.pdf_generator import create_simple_receipt_pdf
from utils.converters import get_current_date, get_fy_string
from pathlib import Path
from datetime import datetime
import config
import tempfile


def _parse_action_input(input_str: str) -> dict:
    """Parse a tool action input string into a dict of parameters.
    
    Handles: JSON, comma-separated, key=value pairs.
    Keys are numbered _0, _1, etc. for positional values.
    """
    input_str = input_str.strip().strip('"\'')
    if not input_str:
        return {}

    # Strategy 1: JSON
    if input_str.startswith("{"):
        try:
            return json.loads(input_str)
        except json.JSONDecodeError:
            pass

    result = {}

    # Strategy 2: key=value pairs
    kvs = re.findall(r'(\w+)\s*=\s*([^,]+)', input_str)
    if kvs:
        for k, v in kvs:
            result[k] = v.strip().strip('"\'')
        return result

    # Strategy 3: comma-separated positional values
    parts = [p.strip().strip('"\'') for p in input_str.split(",")]
    for i, part in enumerate(parts):
        result[f"_{i}"] = part

    return result


class ReceiptAgent(BaseAgent):
    """Agent for processing payments and generating receipts"""

    def __init__(self, data_provider: DataProvider, file_storage: FileStorage):
        super().__init__(
            name="Receipt Generation Agent",
            description="Processes payment screenshots and generates receipts",
            data_provider=data_provider,
            file_storage=file_storage,
        )
        self.ocr_processor = OCRProcessor()  # OCRProcessor now auto-configures from config.py
        self.get_tools()

    def get_tools(self):
        """Register tools for receipt generation"""

        def extract_payment_from_screenshot(image_path: str):
            """Extract payment details from screenshot using vision"""
            payment_details = self.ocr_processor.extract_payment_details(Path(image_path))
            if "error" in payment_details:
                return f"Error extracting payment details: {payment_details['error']}"
            return str(payment_details)

        def confirm_payment_details(input_str: str = None):
            """Confirm and record payment details. Input JSON keys: member_id or plot_no, amount, date, transaction_type (optional). Example: {"member_id": 2, "amount": 3000, "date": "05-05-2026", "transaction_type": "UPI"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            amount = data.get("amount")
            date = data.get("date")

            if not member_id:
                plot_no = (data.get("plot_no") or data.get("plot") or
                           data.get("plot_numbers") or data.get("_0") or "")
                # Handle list of plot numbers
                if isinstance(plot_no, list):
                    plot_no = plot_no[0] if plot_no else ""
                if plot_no:
                    member = self.data_provider.get_member_by_plot_no(plot_no)
                    member_id = member.get("ID") if member else None
                if not member_id:
                    return "Please provide a member ID or plot number to confirm payment details"

            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return f"Invalid member ID: {member_id}"

            if amount is None:
                return "Please provide the payment amount"
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return f"Invalid amount: {amount}"

            if not date:
                date = get_current_date()

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            current_outstanding = self.data_provider.get_current_outstanding(member_id)
            new_outstanding = max(0, current_outstanding - amount)

            return {
                "confirmed": True,
                "member_name": member.get("Plot_Owner_Name"),
                "amount": amount,
                "date": date,
                "current_outstanding": current_outstanding,
                "new_outstanding": new_outstanding,
            }

        def generate_receipt(input_str: str = None):
            """Generate receipt for payment. Input JSON keys: member_id (or plot_no), amount, date, transaction_id (optional), transaction_type (optional - NEFT/UPI/CHQ/IMPS/CASH). Example: {"member_id": 2, "amount": 3000, "date": "05-05-2026", "transaction_type": "UPI"}"""
            data = _parse_action_input(input_str or "")
            member_id = data.get("member_id")
            amount = data.get("amount")
            date = data.get("date")
            transaction_id = data.get("transaction_id")
            transaction_type = data.get("transaction_type") or data.get("txn_type") or ""

            if not member_id:
                plot_no = (data.get("plot_no") or data.get("plot") or
                           data.get("plot_numbers") or data.get("_0") or "")
                if isinstance(plot_no, list):
                    plot_no = plot_no[0] if plot_no else ""
                if plot_no:
                    member = self.data_provider.get_member_by_plot_no(plot_no)
                    member_id = member.get("ID") if member else None
                if not member_id:
                    return "Please provide a member ID or plot number to generate receipt"

            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return f"Invalid member ID: {member_id}"

            if amount is None:
                return "Please provide the payment amount"
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return f"Invalid amount: {amount}"

            if not date:
                date = get_current_date()

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            # Generate receipt ID
            fy = get_fy_string()
            receipt_no = self.data_provider.get_next_voucher_number()
            receipt_id = f"{fy}-{str(receipt_no).zfill(3)}"

            # Calculate new outstanding
            current_outstanding = self.data_provider.get_current_outstanding(member_id)
            new_outstanding = max(0, current_outstanding - amount)

            # Prepare receipt data
            txn_type = transaction_type.upper() if transaction_type else ""
            receipt_data = {
                "receipt_id": receipt_id,
                "date": date or get_current_date(),
                "member_name": member.get("Plot_Owner_Name", "Unknown"),
                "plot_no": member.get("Plot_No", "N/A"),
                "amount": amount,
                "transaction_id": transaction_id or "N/A",
                "transaction_type": txn_type,
                "outstanding_balance": new_outstanding,
                "payment_details": "",
            }

            # Generate PDF
            receipt_dir = config.RECEIPTS_DIR / fy
            receipt_dir.mkdir(parents=True, exist_ok=True)
            plot_str = str(member.get("Plot_No", "") or "")
            plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
            receipt_filename = f"Receipt_{plot_part}_{receipt_id}.pdf"
            receipt_path = receipt_dir / receipt_filename

            success = create_simple_receipt_pdf(receipt_path, receipt_data)

            if success:
                # Update ledger
                vch_no = self.data_provider.get_next_voucher_number()
                self.data_provider.add_ledger_entry(member_id, {
                    "Date": date or get_current_date(),
                    "Particulars": "By Payment Received",
                    "Vch_Type": "Journal",
                    "Vch_No": vch_no,
                    "Debit": None,
                    "Credit": amount,
                    "Description": f"Receipt {receipt_id}",
                    "Transaction_ID": transaction_id or None,
                    "Transaction_Type": txn_type,
                })

                # Update member outstanding
                self.data_provider.update_member(member_id, {"Current_Outstanding": new_outstanding})

                return f"Receipt {receipt_id} generated successfully. New outstanding: ₹{new_outstanding:,.2f}"
            else:
                return f"Failed to generate receipt for member {member_id}"

        def get_member_details(member_identifier: str):
            """Get member details by ID or Plot No"""
            try:
                # Try as ID first
                member = self.data_provider.get_member(int(member_identifier))
                if not member:
                    # Try as plot number
                    member = self.data_provider.get_member_by_plot_no(member_identifier)
            except:
                member = self.data_provider.get_member_by_plot_no(member_identifier)

            if not member:
                return f"Member {member_identifier} not found"

            outstanding = self.data_provider.get_current_outstanding(member["ID"])
            return {
                "id": member.get("ID"),
                "name": member.get("Plot_Owner_Name"),
                "plot_no": member.get("Plot_No"),
                "email": member.get("Email"),
                "outstanding": outstanding,
            }

        # Register tools
        self.register_tool(
            extract_payment_from_screenshot,
            "extract_payment_from_screenshot",
            "Extract payment details from screenshot",
        )
        self.register_tool(
            confirm_payment_details,
            "confirm_payment_details",
            "Confirm payment details. Input: JSON with member_id (or plot_no), amount, date. Use after get_member_details to get the member_id.",
        )
        self.register_tool(
            generate_receipt,
            "generate_receipt",
            "Generate a receipt PDF for a payment. Input: JSON with member_id (or plot_no), amount, date, transaction_id (optional). Use after get_member_details to get the member_id.",
        )
        self.register_tool(
            get_member_details,
            "get_member_details",
            "Get member details by ID or Plot No. Use this FIRST to find the member_id before calling other tools.",
        )
