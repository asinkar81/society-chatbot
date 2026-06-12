"""
Invoice generation agent
"""
from agents.base_agent import BaseAgent
from data_providers.base_provider import DataProvider
from file_storage.base_storage import FileStorage
from tools.pdf_generator import create_simple_invoice_pdf
from utils.converters import (
    number_to_words_inr,
    format_amount,
    get_current_date,
    get_due_date,
    get_fy_string,
    get_bill_period,
)
from pathlib import Path
from datetime import datetime
import config


class InvoiceAgent(BaseAgent):
    """Agent for generating invoices"""

    def __init__(self, data_provider: DataProvider, file_storage: FileStorage):
        super().__init__(
            name="Invoice Generation Agent",
            description="Generates invoices for society members based on maintenance charges",
            data_provider=data_provider,
            file_storage=file_storage,
        )
        self.get_tools()

    def get_tools(self):
        """Register tools for invoice generation"""

        def fetch_members(_: str = None):
            """Fetch all members from database"""
            members = self.data_provider.get_all_members()
            return f"Found {len(members)} members: {[m.get('Plot_No', 'Unknown') for m in members[:5]]}..."

        def calculate_invoice_amount(member_id: int, fy: str):
            """Calculate invoice amount for a member"""
            settings = self.data_provider.get_settings()

            # Get rates
            repair_rate = float(settings.get("Repair_Fund_Rate", 100.0))
            service_rate = float(settings.get("Service_Charges_Rate", 885.0))
            sinking_rate = float(settings.get("Sinking_Fund_Rate", 15.0))

            # Calculate amounts (12 months)
            months = 12
            repair_amount = repair_rate * months
            service_amount = service_rate * months
            sinking_amount = sinking_rate * months

            # Get member details
            member = self.data_provider.get_member(member_id)
            pending_interest = float(member.get("Pending_Interest", 0)) if member else 0

            # Get payments received so far
            outstanding = self.data_provider.get_current_outstanding(member_id)

            total = repair_amount + service_amount + sinking_amount + pending_interest
            total_amount_due = total - outstanding

            return {
                "member_id": member_id,
                "fy": fy,
                "repair_amount": repair_amount,
                "service_amount": service_amount,
                "sinking_amount": sinking_amount,
                "interest_amount": pending_interest,
                "total_amount": total,
                "total_amount_due": total_amount_due,
                "outstanding": outstanding,
            }

        def generate_invoice(member_id: int, fy: str = None):
            """Generate invoice for a member"""
            if fy is None:
                fy = get_fy_string()

            member = self.data_provider.get_member(member_id)
            if not member:
                return f"Member {member_id} not found"

            # Calculate amounts
            calc = calculate_invoice_amount(member_id, fy)

            # Generate invoice number
            invoice_no = f"{int(member.get('Plot_No', 0)):03d}{datetime.now().strftime('%y%m%d')}"

            # Prepare invoice data
            invoice_data = {
                "invoice_no": invoice_no,
                "invoice_date": get_current_date(),
                "due_date": get_due_date(config.INVOICE_DUE_DAYS),
                "plot_owner_name": member.get("Plot_Owner_Name", "Unknown"),
                "plot_no": member.get("Plot_No", "N/A"),
                "bill_period": get_bill_period(),
                "number_of_months": 12,
                "line_items": {
                    "Repair & Maintenance Fund": calc["repair_amount"],
                    "Service Charges": calc["service_amount"],
                    "Sinking Fund": calc["sinking_amount"],
                    "Interest Penalty Charges": calc["interest_amount"],
                },
                "total_amount": calc["total_amount"],
                "total_amount_due": calc["total_amount_due"],
                "amount_in_words": number_to_words_inr(calc["total_amount_due"]),
            }

            # Generate PDF
            invoice_dir = config.INVOICES_DIR / fy
            invoice_dir.mkdir(parents=True, exist_ok=True)
            plot_str = str(member.get("Plot_No", "") or "")
            plot_part = f"Plot_No_{plot_str.zfill(2)}" if plot_str else "Unknown"
            invoice_filename = f"Invoice_{plot_part}_{invoice_no}.pdf"
            invoice_path = invoice_dir / invoice_filename

            success = create_simple_invoice_pdf(invoice_path, invoice_data)

            if success:
                return f"Invoice generated: {invoice_filename} for {member.get('Plot_Owner_Name', 'Unknown')}"
            else:
                return f"Failed to generate invoice for member {member_id}"

        def generate_all_invoices(fy: str = None):
            """Generate invoices for all members"""
            if fy is None:
                fy = get_fy_string()

            members = self.data_provider.get_all_members()
            success_count = 0
            failed_count = 0

            for idx, member in enumerate(members, 1):
                try:
                    result = generate_invoice(member["ID"], fy)
                    if "generated" in result.lower():
                        success_count += 1
                    else:
                        failed_count += 1
                    print(f"[{idx}/{len(members)}] {result}")
                except Exception as e:
                    failed_count += 1
                    print(f"[{idx}/{len(members)}] Error: {str(e)}")

            summary = f"Invoice generation complete: {success_count} success, {failed_count} failed"
            return summary

        # Register tools
        self.register_tool(fetch_members, "fetch_members", "Fetch all members from database")
        self.register_tool(
            calculate_invoice_amount,
            "calculate_invoice_amount",
            "Calculate invoice amount for a member",
        )
        self.register_tool(generate_invoice, "generate_invoice", "Generate invoice for a member")
        self.register_tool(generate_all_invoices, "generate_all_invoices", "Generate invoices for all members")
