"""
Stub for future Google Sheets implementation
"""
from data_providers.base_provider import DataProvider
from typing import List, Dict, Any, Optional
from datetime import datetime


class GoogleSheetsDataProvider(DataProvider):
    """Google Sheets implementation (stub for future development)"""

    def __init__(self, sheet_id: str):
        self.sheet_id = sheet_id
        raise NotImplementedError("Google Sheets integration coming in future release")

    def get_all_members(self) -> List[Dict[str, Any]]:
        pass

    def get_member(self, member_id: int) -> Optional[Dict[str, Any]]:
        pass

    def get_member_by_plot_no(self, plot_no: str) -> Optional[Dict[str, Any]]:
        pass

    def add_member(self, member_data: Dict[str, Any]) -> int:
        pass

    def update_member(self, member_id: int, member_data: Dict[str, Any]) -> bool:
        pass

    def get_member_ledger(self, member_id: int) -> List[Dict[str, Any]]:
        pass

    def add_ledger_entry(self, member_id: int, entry: Dict[str, Any]) -> bool:
        pass

    def get_ledger_entries(
        self, member_id: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        pass

    def get_settings(self) -> Dict[str, Any]:
        pass

    def update_settings(self, settings: Dict[str, Any]) -> bool:
        pass

    def get_next_voucher_number(self) -> int:
        pass

    def get_current_outstanding(self, member_id: int) -> float:
        pass
