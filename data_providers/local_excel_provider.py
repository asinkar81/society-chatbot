"""
Local Excel-based implementation of DataProvider
"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import openpyxl
from openpyxl.utils import get_column_letter

from data_providers.base_provider import DataProvider
import config


class LocalExcelDataProvider(DataProvider):
    """Local Excel file-based data storage using openpyxl and pandas"""

    LEDGER_HEADERS = [
        "Member_ID", "Date", "Particulars", "Vch_Type",
        "Vch_No", "Debit", "Credit", "Description", "Transaction_ID",
    ]

    def __init__(self, excel_file: Path = None):
        self.excel_file = excel_file or config.SOCIETY_DATA_FILE
        self.members_sheet = "Members"
        self.ledger_sheet = "Ledger"
        self.settings_sheet = "Settings"
        self._ensure_workbook_exists()

    def _plot_ledger_sheet(self, plot_no) -> str:
        """Get the ledger sheet name for a given plot number."""
        return f"Ledger_Plot_{str(plot_no).zfill(2)}"

    def _get_or_create_plot_ledger_sheet(self, member_id: int, plot_no=None) -> str:
        """Ensure a per-plot ledger sheet exists for the member."""
        if plot_no is None:
            member = self.get_member(member_id)
            if not member:
                return self.ledger_sheet
            plot_no = member.get("Plot_No", str(member_id))
        sheet_name = self._plot_ledger_sheet(plot_no)
        wb = openpyxl.load_workbook(self.excel_file)
        if sheet_name not in wb.sheetnames:
            ws = wb.create_sheet(sheet_name)
            ws.append(self.LEDGER_HEADERS)
            wb.save(self.excel_file)
        else:
            wb.close()
        return sheet_name

    def _ensure_workbook_exists(self):
        """Create workbook with required sheets if it doesn't exist"""
        if not self.excel_file.exists():
            wb = openpyxl.Workbook()
            wb.remove(wb.active)

            ws_members = wb.create_sheet(self.members_sheet)
            ws_members.append([
                "ID", "Plot_No", "Plot_Owner_Name", "Email",
                "Phone", "Current_Outstanding", "Pending_Interest",
            ])

            ws_ledger = wb.create_sheet(self.ledger_sheet)
            ws_ledger.append(self.LEDGER_HEADERS)

            ws_settings = wb.create_sheet(self.settings_sheet)
            ws_settings.append(["Key", "Value"])
            for row in [
                ["Current_FY", "2026-27"],
                ["Repair_Fund_Rate", "100.00"],
                ["Service_Charges_Rate", "885.00"],
                ["Sinking_Fund_Rate", "15.00"],
                ["April_1st_Auto_Entry_Amount", "12000"],
                ["Last_Voucher_No", "0"],
            ]:
                ws_settings.append(row)

            wb.save(self.excel_file)

    def get_all_members(self) -> List[Dict[str, Any]]:
        """Fetch all members from Excel"""
        df = pd.read_excel(self.excel_file, sheet_name=self.members_sheet)
        return df.to_dict("records")

    def get_member(self, member_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a specific member by ID"""
        df = pd.read_excel(self.excel_file, sheet_name=self.members_sheet)
        member = df[df["ID"] == member_id]
        if member.empty:
            return None
        return member.iloc[0].to_dict()

    def get_member_by_plot_no(self, plot_no: str) -> Optional[Dict[str, Any]]:
        """Fetch member by plot number"""
        df = pd.read_excel(self.excel_file, sheet_name=self.members_sheet)
        member = df[df["Plot_No"].astype(str) == str(plot_no).zfill(2)]
        if member.empty:
            return None
        return member.iloc[0].to_dict()

    def add_member(self, member_data: Dict[str, Any]) -> int:
        """Add a new member and create their per-plot ledger sheet"""
        df = pd.read_excel(self.excel_file, sheet_name=self.members_sheet)
        max_id = df["ID"].max() if len(df) > 0 else 0
        new_id = int(max_id) + 1
        member_data["ID"] = new_id
        new_row = pd.DataFrame([member_data])
        df = pd.concat([df, new_row], ignore_index=True)
        self._write_sheet(df, self.members_sheet)

        # Create per-plot ledger sheet
        plot_no = member_data.get("Plot_No", str(new_id))
        self._get_or_create_plot_ledger_sheet(new_id, str(plot_no))

        return new_id

    def update_member(self, member_id: int, member_data: Dict[str, Any]) -> bool:
        """Update member details"""
        df = pd.read_excel(self.excel_file, sheet_name=self.members_sheet)
        mask = df["ID"] == member_id
        if not mask.any():
            return False
        for key, value in member_data.items():
            df.loc[mask, key] = value
        self._write_sheet(df, self.members_sheet)
        return True

    def _get_plot_no(self, member_id: int) -> str:
        """Get plot number string for a member."""
        member = self.get_member(member_id)
        return str(member.get("Plot_No", member_id)) if member else str(member_id)

    def get_member_ledger(self, member_id: int) -> List[Dict[str, Any]]:
        """Fetch complete ledger for a member from their per-plot sheet"""
        plot_no = self._get_plot_no(member_id)
        sheet_name = self._plot_ledger_sheet(plot_no)

        # Try per-plot sheet first
        try:
            df = pd.read_excel(self.excel_file, sheet_name=sheet_name)
            entries = df[df["Member_ID"] == member_id].to_dict("records")
            if entries:
                return entries
        except Exception:
            pass

        # Fall back to main Ledger sheet and populate per-plot sheet
        df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
        member_ledger = df[df["Member_ID"] == member_id]
        if not member_ledger.empty:
            self._get_or_create_plot_ledger_sheet(member_id, plot_no)
            self._write_sheet(member_ledger, sheet_name)
        return member_ledger.to_dict("records")

    def add_ledger_entry(self, member_id: int, entry: Dict[str, Any]) -> bool:
        """Add a transaction entry to member's ledger (writes to both per-plot and main sheets)"""
        entry["Member_ID"] = member_id

        # Write to main Ledger sheet
        df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
        new_row = pd.DataFrame([entry]).reindex(columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
        self._write_sheet(df, self.ledger_sheet)

        # Write to per-plot sheet
        plot_no = self._get_plot_no(member_id)
        sheet_name = self._get_or_create_plot_ledger_sheet(member_id, plot_no)
        try:
            pdf = pd.read_excel(self.excel_file, sheet_name=sheet_name)
        except Exception:
            pdf = pd.DataFrame(columns=self.LEDGER_HEADERS)
        new_row_aligned = pd.DataFrame([entry]).reindex(columns=pdf.columns)
        pdf = pd.concat([pdf, new_row_aligned], ignore_index=True)
        self._write_sheet(pdf, sheet_name)

        return True

    def get_ledger_entries(
        self, member_id: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Fetch ledger entries for a date range"""
        df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
        df = df[df["Member_ID"] == member_id]

        if start_date or end_date:
            df["Date"] = pd.to_datetime(df["Date"], format="%d-%m-%Y", errors="coerce")
            if start_date:
                df = df[df["Date"] >= start_date]
            if end_date:
                df = df[df["Date"] <= end_date]

        return df.to_dict("records")

    def get_settings(self) -> Dict[str, Any]:
        """Fetch system settings"""
        df = pd.read_excel(self.excel_file, sheet_name=self.settings_sheet)
        settings = {}
        for _, row in df.iterrows():
            key = row["Key"]
            value = row["Value"]
            # Try to convert to appropriate type
            if isinstance(value, str):
                if value.isdigit():
                    settings[key] = int(value)
                elif value.replace(".", "", 1).isdigit():
                    settings[key] = float(value)
                else:
                    settings[key] = value
            else:
                settings[key] = value
        return settings

    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """Update system settings"""
        df = pd.read_excel(self.excel_file, sheet_name=self.settings_sheet)
        for key, value in settings.items():
            mask = df["Key"] == key
            if mask.any():
                df.loc[mask, "Value"] = value
            else:
                new_row = pd.DataFrame([{"Key": key, "Value": value}])
                df = pd.concat([df, new_row], ignore_index=True)
        self._write_sheet(df, self.settings_sheet)
        return True

    def get_next_voucher_number(self) -> int:
        """Get next sequential voucher number"""
        settings = self.get_settings()
        last_vch = int(settings.get("Last_Voucher_No", 0))
        next_vch = last_vch + 1
        self.update_settings({"Last_Voucher_No": str(next_vch)})
        return next_vch

    @staticmethod
    def _safe_float(val) -> float:
        """Convert a value to float, treating NaN/None as 0."""
        if val is None:
            return 0.0
        try:
            v = float(val)
            return 0.0 if v != v else v  # NaN check
        except (ValueError, TypeError):
            return 0.0

    def get_current_outstanding(self, member_id: int) -> float:
        """Calculate current outstanding for a member.
        
        Convention: Credit = payment received (+), Debit = demand charged (-)
        Outstanding = total_credit - total_debit
        Positive = surplus (member overpaid), Negative = demand due (member owes)
        
        Falls back to the stored Current_Outstanding (negated for old convention)
        when no ledger entries exist.
        """
        ledger = self.get_member_ledger(member_id)
        if ledger:
            total_credit = sum(self._safe_float(e.get("Credit")) for e in ledger)
            total_debit = sum(self._safe_float(e.get("Debit")) for e in ledger)
            return total_credit - total_debit
        # No entries yet — use stored value (negate: old debit-credit → new credit-debit)
        member = self.get_member(member_id)
        if member:
            return -float(member.get("Current_Outstanding", 0) or 0)
        return 0.0

    def _write_sheet(self, df: pd.DataFrame, sheet_name: str):
        """Write dataframe to Excel sheet"""
        with pd.ExcelWriter(self.excel_file, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
