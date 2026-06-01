"""
Admin agent for system management
"""
from agents.base_agent import BaseAgent
from data_providers.base_provider import DataProvider
from file_storage.base_storage import FileStorage
from utils.converters import get_fy_string, get_current_date
from datetime import datetime
import config


class AdminAgent(BaseAgent):
    """Agent for administrative tasks"""

    def __init__(self, data_provider: DataProvider, file_storage: FileStorage):
        super().__init__(
            name="Admin Agent",
            description="Handles administrative tasks like settings and member management",
            data_provider=data_provider,
            file_storage=file_storage,
        )
        self.get_tools()

    def get_tools(self):
        """Register tools for admin tasks"""

        def update_rates(repair: float = None, service: float = None, sinking: float = None):
            """Update invoice rates"""
            settings = {}
            if repair is not None:
                settings["Repair_Fund_Rate"] = str(repair)
            if service is not None:
                settings["Service_Charges_Rate"] = str(service)
            if sinking is not None:
                settings["Sinking_Fund_Rate"] = str(sinking)

            if settings:
                success = self.data_provider.update_settings(settings)
                if success:
                    return f"Rates updated successfully: Repair={repair}, Service={service}, Sinking={sinking}"
                else:
                    return "Failed to update rates"
            else:
                return "No rates provided"

        def get_current_settings(_: str = None):
            """Get current system settings"""
            settings = self.data_provider.get_settings()
            result = "Current Settings:\n"
            for key, value in settings.items():
                result += f"  {key}: {value}\n"
            return result

        def add_new_member(plot_no: str, name: str, email: str = None, phone: str = None):
            """Add a new member"""
            member_data = {
                "Plot_No": plot_no,
                "Plot_Owner_Name": name,
                "Email": email or "",
                "Phone": phone or "",
                "Current_Outstanding": 0,
                "Pending_Interest": 0,
            }
            member_id = self.data_provider.add_member(member_data)
            return f"Member added successfully: ID={member_id}, Plot={plot_no}, Name={name}"

        def trigger_april_first_entry(fy: str = None):
            """Trigger April 1st auto-entry for all members"""
            if fy is None:
                fy = get_fy_string()

            members = self.data_provider.get_all_members()
            success_count = 0
            skip_count = 0

            for member in members:
                member_id = member["ID"]
                plot_no = member.get("Plot_No", "Unknown")

                # Check if entry already exists for this FY
                ledger = self.data_provider.get_member_ledger(member_id)
                entry_exists = any(
                    f"FY {fy}" in entry.get("Description", "")
                    for entry in ledger
                )

                if entry_exists:
                    skip_count += 1
                    continue

                # Add April 1st entry
                try:
                    vch_no = self.data_provider.get_next_voucher_number()
                    ledger_entry = {
                        "Date": "1-4-2026",  # April 1st
                        "Particulars": "To Member Contribution Received",
                        "Vch_Type": "Journal",
                        "Vch_No": vch_no,
                        "Debit": config.AUTO_ENTRY_AMOUNT,
                        "Credit": None,
                        "Description": f"YEARLY MEMBER CONTRIBUTION FOR FY {fy}",
                    }
                    self.data_provider.add_ledger_entry(member_id, ledger_entry)
                    success_count += 1
                except Exception as e:
                    print(f"Error adding entry for member {plot_no}: {str(e)}")

            return f"April 1st entries: {success_count} added, {skip_count} skipped (already exist)"

        def get_member_count(_: str = None):
            """Get total member count"""
            members = self.data_provider.get_all_members()
            return f"Total members: {len(members)}"

        def get_system_summary(_: str = None):
            """Get system summary"""
            members = self.data_provider.get_all_members()
            total_members = len(members)
            total_outstanding = 0

            for member in members:
                outstanding = self.data_provider.get_current_outstanding(member["ID"])
                total_outstanding += outstanding

            summary = f"""
SYSTEM SUMMARY
====================
Total Members: {total_members}
Total Outstanding: ₹{total_outstanding:,.2f}
Current FY: {get_fy_string()}
Current Date: {get_current_date()}
====================
"""
            return summary

        # Register tools
        self.register_tool(
            update_rates,
            "update_rates",
            "Update invoice rates (repair, service, sinking)",
        )
        self.register_tool(get_current_settings, "get_current_settings", "Get current system settings")
        self.register_tool(add_new_member, "add_new_member", "Add a new member")
        self.register_tool(
            trigger_april_first_entry,
            "trigger_april_first_entry",
            "Trigger April 1st auto-entry",
        )
        self.register_tool(get_member_count, "get_member_count", "Get total member count")
        self.register_tool(get_system_summary, "get_system_summary", "Get system summary")
