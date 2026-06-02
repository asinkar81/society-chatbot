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

    @abstractmethod
    def record_payment_reference(self, member_id: int, identifier_type: str, identifier_value: str, date: str = None):
        """Store a known payment identifier for future matching"""
        pass

    @abstractmethod
    def find_member_by_identifier(self, identifier_value: str) -> Optional[Dict[str, Any]]:
        """Look up a member by known payment identifier (UPI ID, mobile, email, payee name)"""
        pass

    @abstractmethod
    def get_known_identifiers(self, member_id: int, min_confidence: int = 1) -> List[Dict[str, str]]:
        """Get all known payment identifiers for a member with confidence >= threshold"""
        pass

    @abstractmethod
    def delete_ledger_entry(self, member_id: int, vch_no: int) -> bool:
        """Remove a ledger entry by member ID and voucher number. Recalculates outstanding."""
        pass

    # ── Suspense Entries ────────────────────────────────────────────────

    @abstractmethod
    def add_suspense_entry(self, entry: Dict[str, Any]) -> int:
        """Add an entry to the Suspense_Entries sheet. Returns the new entry ID."""
        pass

    @abstractmethod
    def get_suspense_entries(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all suspense entries, optionally filtered by status (Pending/Tagged)."""
        pass

    @abstractmethod
    def tag_suspense_entry(self, entry_id: int, member_id: int) -> bool:
        """Tag a suspense entry to a member. Sets status to Tagged + records date."""
        pass

    @abstractmethod
    def delete_suspense_entry(self, entry_id: int) -> bool:
        """Remove a suspense entry by ID."""
        pass
