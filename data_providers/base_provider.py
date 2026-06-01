"""
Abstract base class for data persistence providers
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime


class DataProvider(ABC):
    """Abstract interface for data persistence"""

    @abstractmethod
    def get_all_members(self) -> List[Dict[str, Any]]:
        """Fetch all society members"""
        pass

    @abstractmethod
    def get_member(self, member_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a specific member by ID"""
        pass

    @abstractmethod
    def get_member_by_plot_no(self, plot_no: str) -> Optional[Dict[str, Any]]:
        """Fetch member by plot number"""
        pass

    @abstractmethod
    def add_member(self, member_data: Dict[str, Any]) -> int:
        """Add a new member, return member ID"""
        pass

    @abstractmethod
    def update_member(self, member_id: int, member_data: Dict[str, Any]) -> bool:
        """Update member details"""
        pass

    @abstractmethod
    def get_member_ledger(self, member_id: int) -> List[Dict[str, Any]]:
        """Fetch complete ledger for a member"""
        pass

    @abstractmethod
    def add_ledger_entry(self, member_id: int, entry: Dict[str, Any]) -> bool:
        """Add a transaction entry to member's ledger"""
        pass

    @abstractmethod
    def get_ledger_entries(
        self, member_id: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Fetch ledger entries for a date range"""
        pass

    @abstractmethod
    def get_settings(self) -> Dict[str, Any]:
        """Fetch system settings"""
        pass

    @abstractmethod
    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """Update system settings"""
        pass

    @abstractmethod
    def get_next_voucher_number(self) -> int:
        """Get next sequential voucher number"""
        pass

    @abstractmethod
    def get_current_outstanding(self, member_id: int) -> float:
        """Calculate current outstanding balance for a member"""
        pass
