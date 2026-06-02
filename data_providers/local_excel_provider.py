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
        "Transaction_Type",
    ]

    PAYMENT_REF_HEADERS = [
        "Member_ID", "Identifier_Type", "Identifier_Value",
        "Last_Seen_Date", "Confidence",
    ]

    SUSPENSE_HEADERS = [
        "ID", "Date", "Particulars", "Amount", "Transaction_ID",
        "Transaction_Type", "Description", "Entry_Date", "Status",
        "Tagged_To", "Tagged_Date",
    ]

    def __init__(self, excel_file: Path = None):
        self.excel_file = excel_file or config.SOCIETY_DATA_FILE
        self.members_sheet = "Members"
        self.ledger_sheet = "Ledger"
        self.settings_sheet = "Settings"
        self.payment_refs_sheet = "Payment_References"
        self.suspense_sheet = "Suspense_Entries"
        self._ensure_workbook_exists()
        self._ensure_payment_refs_sheet_exists()
        self._ensure_suspense_sheet_exists()

    def _ensure_payment_refs_sheet_exists(self):
        """Create Payment_References sheet if it doesn't exist in existing workbook."""
        try:
            wb = openpyxl.load_workbook(self.excel_file)
            if self.payment_refs_sheet not in wb.sheetnames:
                ws = wb.create_sheet(self.payment_refs_sheet)
                ws.append(self.PAYMENT_REF_HEADERS)
                wb.save(self.excel_file)
            wb.close()
        except Exception:
            pass

    def _ensure_suspense_sheet_exists(self):
        """Create Suspense_Entries sheet if it doesn't exist."""
        try:
            wb = openpyxl.load_workbook(self.excel_file)
            if self.suspense_sheet not in wb.sheetnames:
                ws = wb.create_sheet(self.suspense_sheet)
                ws.append(self.SUSPENSE_HEADERS)
                wb.save(self.excel_file)
            wb.close()
        except Exception:
            pass

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

            ws_refs = wb.create_sheet(self.payment_refs_sheet)
            ws_refs.append(self.PAYMENT_REF_HEADERS)

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

        def _ensure_columns(df, entry_columns):
            """Add any missing columns from entry to df to avoid data loss on concat."""
            for col in entry_columns:
                if col not in df.columns:
                    df[col] = None
            return df

        entry_df = pd.DataFrame([entry])

        # Write to main Ledger sheet
        df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
        df = _ensure_columns(df, entry_df.columns)
        df = pd.concat([df, entry_df.reindex(columns=df.columns)], ignore_index=True)
        self._write_sheet(df, self.ledger_sheet)

        # Write to per-plot sheet
        plot_no = self._get_plot_no(member_id)
        sheet_name = self._get_or_create_plot_ledger_sheet(member_id, plot_no)
        try:
            pdf = pd.read_excel(self.excel_file, sheet_name=sheet_name)
        except Exception:
            pdf = pd.DataFrame(columns=self.LEDGER_HEADERS)
        pdf = _ensure_columns(pdf, entry_df.columns)
        pdf = pd.concat([pdf, entry_df.reindex(columns=pdf.columns)], ignore_index=True)
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

    def record_payment_reference(self, member_id: int, identifier_type: str, identifier_value: str, date: str = None):
        """Store or update a known payment identifier for a member.
        
        identifier_type: UPI_ID, MOBILE, PAYEE_NAME, EMAIL, TRANSACTION_ID, TRANSACTION_TYPE
        identifier_value: the actual value (e.g. 'rameshdhebe070', '9422318440', 'SHWETA S')
        """
        if not identifier_value or not identifier_type:
            return
        val = str(identifier_value).strip()
        if not val:
            return
        self._ensure_payment_refs_sheet_exists()
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.payment_refs_sheet)
        except Exception:
            df = pd.DataFrame(columns=self.PAYMENT_REF_HEADERS)

        existing = df[(df["Member_ID"] == member_id) & (df["Identifier_Type"] == identifier_type) & (df["Identifier_Value"] == val)]
        if not existing.empty:
            df.loc[existing.index[0], "Last_Seen_Date"] = date or datetime.now().strftime("%d-%m-%Y")
            c = int(existing.iloc[0].get("Confidence", 0) or 0) + 1
            df.loc[existing.index[0], "Confidence"] = min(c, 100)
        else:
            new_row = pd.DataFrame([{
                "Member_ID": member_id,
                "Identifier_Type": identifier_type,
                "Identifier_Value": val,
                "Last_Seen_Date": date or datetime.now().strftime("%d-%m-%Y"),
                "Confidence": 1,
            }])
            df = pd.concat([df, new_row], ignore_index=True)

        self._write_sheet(df, self.payment_refs_sheet)

    def delete_ledger_entry(self, member_id: int, vch_no: int) -> bool:
        """Remove a ledger entry by member ID and voucher number from both main
        and per-plot sheets. Recalculates and updates the member's outstanding balance."""
        deleted = False

        def _remove_row(df, col, val):
            nonlocal deleted
            mask = df[col] == val
            if mask.any():
                df = df[~mask].reset_index(drop=True)
                deleted = True
            return df

        # Remove from per-plot sheet
        plot_no = self._get_plot_no(member_id)
        sheet_name = self._plot_ledger_sheet(plot_no)
        try:
            pdf = pd.read_excel(self.excel_file, sheet_name=sheet_name)
            pdf = _remove_row(pdf, "Vch_No", vch_no)
            self._write_sheet(pdf, sheet_name)
        except Exception:
            pass

        # Remove from main Ledger sheet
        df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
        df = _remove_row(df, "Vch_No", vch_no)
        self._write_sheet(df, self.ledger_sheet)

        if deleted:
            o = self.get_current_outstanding(member_id)
            self.update_member(member_id, {"Current_Outstanding": o})

        return deleted

    def find_member_by_identifier(self, identifier_value: str) -> Optional[Dict[str, Any]]:
        """Look up a member by any known payment identifier (UPI ID, mobile, email, payee name).
        Returns the best-confidence match or None."""
        if not identifier_value:
            return None
        val = str(identifier_value).strip().upper()
        self._ensure_payment_refs_sheet_exists()
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.payment_refs_sheet)
        except Exception:
            return None
        if df.empty:
            return None
        df["match"] = df["Identifier_Value"].astype(str).str.strip().str.upper() == val
        matches = df[df["match"]]
        if matches.empty:
            return None
        best = matches.sort_values("Confidence", ascending=False).iloc[0]
        return self.get_member(int(best["Member_ID"]))

    def get_known_identifiers(self, member_id: int, min_confidence: int = 1) -> List[Dict[str, str]]:
        """Get all known payment identifiers for a member with confidence >= threshold."""
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.payment_refs_sheet)
        except Exception:
            return []
        if df.empty:
            return []
        member_refs = df[(df["Member_ID"] == member_id) & (df["Confidence"] >= min_confidence)]
        return member_refs.to_dict("records")

    # ── Suspense Entries ──────────────────────────────────────────────

    def add_suspense_entry(self, entry: Dict[str, Any]) -> int:
        """Add an entry to Suspense_Entries sheet. Returns the new entry ID."""
        self._ensure_suspense_sheet_exists()
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.suspense_sheet)
        except Exception:
            df = pd.DataFrame(columns=self.SUSPENSE_HEADERS)
        new_id = int(df["ID"].max()) + 1 if not df.empty and "ID" in df.columns else 1
        entry["ID"] = new_id
        entry["Entry_Date"] = entry.get("Entry_Date", datetime.now().strftime("%d-%m-%Y %H:%M"))
        entry["Status"] = entry.get("Status", "Pending")
        entry["Tagged_To"] = entry.get("Tagged_To", None)
        entry["Tagged_Date"] = entry.get("Tagged_Date", None)
        row = pd.DataFrame([{h: entry.get(h) for h in self.SUSPENSE_HEADERS}])
        if df.empty:
            df = row
        else:
            df = pd.concat([df, row], ignore_index=True)
        self._write_sheet(df, self.suspense_sheet)
        return new_id

    def get_suspense_entries(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch suspense entries, optionally filtered by status."""
        self._ensure_suspense_sheet_exists()
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.suspense_sheet)
        except Exception:
            return []
        if df.empty:
            return []
        if status:
            df = df[df["Status"] == status]
        return df.to_dict("records")

    def tag_suspense_entry(self, entry_id: int, member_id: int) -> bool:
        """Tag a suspense entry to a member (Status → Tagged)."""
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.suspense_sheet)
        except Exception:
            return False
        if df.empty or "ID" not in df.columns:
            return False
        idx = df[df["ID"] == entry_id].index
        if idx.empty:
            return False
        for col in ["Status", "Tagged_To", "Tagged_Date"]:
            if col in df.columns and df[col].dtype.kind in ("i", "f"):
                df[col] = df[col].astype(object)
        df.loc[idx, "Status"] = "Tagged"
        df.loc[idx, "Tagged_To"] = member_id
        df.loc[idx, "Tagged_Date"] = datetime.now().strftime("%d-%m-%Y %H:%M")
        self._write_sheet(df, self.suspense_sheet)
        return True

    def delete_suspense_entry(self, entry_id: int) -> bool:
        """Remove a suspense entry by ID."""
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.suspense_sheet)
        except Exception:
            return False
        if df.empty or "ID" not in df.columns:
            return False
        before = len(df)
        df = df[df["ID"] != entry_id]
        if len(df) == before:
            return False
        self._write_sheet(df.reset_index(drop=True), self.suspense_sheet)
        return True

    # ── Ledger duplicate check ────────────────────────────────────────

    def check_duplicate_ledger_entry(
        self, txn_id: str, date: str, amount: float, particulars: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Check if an entry with the same Transaction_ID (+ date + amount) exists
        in ANY member's ledger. Returns the matching entry or None."""
        try:
            df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
        except Exception:
            return None
        if df.empty:
            return None
        txn_clean = str(txn_id or "").strip()
        part_clean = str(particulars or "").strip()[:40]
        for _, e in df.iterrows():
            e_date = str(e.get("Date", "") or "").strip()
            e_credit = float(e.get("Credit", 0) or 0)
            if e_date != date or abs(e_credit - amount) > 0.01:
                continue
            e_txn = str(e.get("Transaction_ID", "") or "").strip()
            # Primary: match by Transaction_ID
            if txn_clean and e_txn == txn_clean:
                return e.to_dict()
            # Fallback: match by particulars prefix
            e_part = str(e.get("Particulars", "") or "").strip()
            e_part_clean = e_part[3:] if e_part.upper().startswith("BY ") else e_part
            e_part_clean = e_part_clean[:40]
            if part_clean and e_part_clean and (part_clean in e_part_clean or e_part_clean in part_clean):
                return e.to_dict()
        return None

    def _write_sheet(self, df: pd.DataFrame, sheet_name: str):
        """Write dataframe to Excel sheet"""
        with pd.ExcelWriter(self.excel_file, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
