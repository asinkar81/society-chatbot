"""
Ledger management agent
"""
from agents.base_agent import BaseAgent
from data_providers.base_provider import DataProvider
from file_storage.base_storage import FileStorage
from utils.converters import get_current_date
from datetime import datetime
import csv
from pathlib import Path
import config


class LedgerAgent(BaseAgent):
    """Agent for ledger management and queries"""

    def __init__(self, data_provider: DataProvider, file_storage: FileStorage):
        super().__init__(
            name="Ledger Management Agent",
            description="Manages ledger entries and provides account information",
            data_provider=data_provider,
            file_storage=file_storage,
        )
        self.get_tools()

    def get_tools(self):
        """Register tools for ledger management"""

        def get_member_ledger(member_identifier: str):
            """Get full ledger for a member"""
            # Try to find member
            try:
                member = self.data_provider.get_member(int(member_identifier))
                member_id = int(member_identifier)
            except:
                member = self.data_provider.get_member_by_plot_no(member_identifier)
                member_id = member.get("ID") if member else None

            if not member or not member_id:
                return f"Member {member_identifier} not found"

            ledger_entries = self.data_provider.get_member_ledger(member_id)

            if not ledger_entries:
                return f"No ledger entries found for {member.get('Plot_Owner_Name', 'Unknown')}"

            # Format ledger
            result = f"\n{'='*80}\n"
            result += f"LEDGER ACCOUNT - {member.get('Plot_Owner_Name', 'Unknown')}\n"
            result += f"Plot No: {member.get('Plot_No', 'N/A')}\n"
            result += f"{'='*80}\n"
            result += f"{'Date':<12} {'Particulars':<30} {'Debit':<12} {'Credit':<12}\n"
            result += f"{'-'*80}\n"

            total_debit = 0
            total_credit = 0

            for entry in ledger_entries:
                date = entry.get("Date", "N/A")
                particulars = entry.get("Particulars", "")[:30]
                debit = float(entry.get("Debit", 0) or 0)
                credit = float(entry.get("Credit", 0) or 0)

                total_debit += debit
                total_credit += credit

                result += f"{str(date):<12} {particulars:<30} {debit:>11,.2f} {credit:>11,.2f}\n"

            result += f"{'-'*80}\n"
            result += f"{'TOTAL':<42} {total_debit:>11,.2f} {total_credit:>11,.2f}\n"
            result += f"{'-'*80}\n"
            outstanding = total_debit - total_credit
            result += f"Outstanding Balance: ₹ {outstanding:,.2f}\n"
            result += f"{'='*80}\n"

            return result

        def add_manual_payment(member_identifier: str, amount: float, date: str = None, description: str = None, transaction_id: str = None):
            """Add manual payment entry to ledger with optional transaction_id"""
            # Find member
            try:
                member = self.data_provider.get_member(int(member_identifier))
                member_id = int(member_identifier)
            except:
                member = self.data_provider.get_member_by_plot_no(member_identifier)
                member_id = member.get("ID") if member else None

            if not member or not member_id:
                return f"Member {member_identifier} not found"

            # Create ledger entry
            vch_no = self.data_provider.get_next_voucher_number()
            ledger_entry = {
                "Date": date or get_current_date(),
                "Particulars": "By Manual Payment",
                "Vch_Type": "Journal",
                "Vch_No": vch_no,
                "Debit": None,
                "Credit": amount,
                "Description": description or "Manual payment entry",
                "Transaction_ID": transaction_id or None,
            }

            success = self.data_provider.add_ledger_entry(member_id, ledger_entry)

            if success:
                # Update member outstanding
                current_outstanding = self.data_provider.get_current_outstanding(member_id)
                self.data_provider.update_member(member_id, {"Current_Outstanding": current_outstanding})
                return f"Payment of ₹{amount:,.2f} recorded for {member.get('Plot_Owner_Name')}"
            else:
                return "Failed to record payment"

        def export_ledger_to_csv(member_identifier: str = None):
            """Export ledger to CSV file"""
            if member_identifier:
                # Export single member ledger
                try:
                    member = self.data_provider.get_member(int(member_identifier))
                    member_id = int(member_identifier)
                except:
                    member = self.data_provider.get_member_by_plot_no(member_identifier)
                    member_id = member.get("ID") if member else None

                if not member or not member_id:
                    return f"Member {member_identifier} not found"

                ledger_entries = self.data_provider.get_member_ledger(member_id)
                filename = f"Ledger_{member.get('Plot_No', 'Unknown')}.csv"
            else:
                # Export all members ledger
                all_members = self.data_provider.get_all_members()
                all_entries = []
                for member in all_members:
                    entries = self.data_provider.get_member_ledger(member["ID"])
                    all_entries.extend(entries)
                ledger_entries = all_entries
                filename = "Ledger_All_Members.csv"

            # Write to CSV
            ledger_dir = config.LEDGERS_DIR
            ledger_dir.mkdir(parents=True, exist_ok=True)
            filepath = ledger_dir / filename

            try:
                with open(filepath, "w", newline="") as f:
                    if ledger_entries:
                        writer = csv.DictWriter(f, fieldnames=ledger_entries[0].keys())
                        writer.writeheader()
                        writer.writerows(ledger_entries)

                return f"Ledger exported to {filename}"
            except Exception as e:
                return f"Failed to export ledger: {str(e)}"

        def get_outstanding_summary(member_identifier: str = None):
            """Get outstanding balance summary for all members"""
            members = self.data_provider.get_all_members()

            result = "\nOUTSTANDING BALANCE SUMMARY\n"
            result += f"{'='*60}\n"
            result += f"{'Plot No':<10} {'Name':<25} {'Outstanding':<15}\n"
            result += f"{'-'*60}\n"

            total_outstanding = 0

            for member in sorted(members, key=lambda m: m.get("Plot_No", "")):
                outstanding = self.data_provider.get_current_outstanding(member["ID"])
                total_outstanding += outstanding
                result += f"{member.get('Plot_No', ''):<10} {member.get('Plot_Owner_Name', ''):<25} ₹{outstanding:>12,.2f}\n"

            result += f"{'-'*60}\n"
            result += f"{'TOTAL':<35} ₹{total_outstanding:>12,.2f}\n"
            result += f"{'='*60}\n"

            return result

        # Register tools
        self.register_tool(get_member_ledger, "get_member_ledger", "Get full ledger for a member")
        self.register_tool(add_manual_payment, "add_manual_payment", "Add manual payment to ledger")
        self.register_tool(export_ledger_to_csv, "export_ledger_to_csv", "Export ledger to CSV")
        self.register_tool(get_outstanding_summary, "get_outstanding_summary", "Get outstanding summary")
