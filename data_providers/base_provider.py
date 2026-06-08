"""
Abstract base class for data persistence providers
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
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
    def record_payment_reference(self, member_id: int, identifier_type: str, identifier_value: str, date: str = None, transaction_type: str = None):
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

    @abstractmethod
    def update_ledger_entry(self, member_id: int, vch_no: int, updates: Dict[str, Any]) -> bool:
        """Update fields of a ledger entry (Date, Particulars, Debit, Credit, etc.). Recalculates outstanding."""
        pass

    # ── Suspense Entries ────────────────────────────────────────────────

    @abstractmethod
    def add_suspense_entry(self, entry: Dict[str, Any]) -> int:
        """Add an entry to the Suspense_Entries sheet. Returns the new entry ID."""
        pass

    @abstractmethod
    def get_suspense_entries(self) -> List[Dict[str, Any]]:
        """Fetch all suspense entries."""
        pass

    @abstractmethod
    def delete_suspense_entry(self, entry_id: int) -> bool:
        """Remove a suspense entry by ID."""
        pass

    # ── Expenses ───────────────────────────────────────────────────────

    @abstractmethod
    def add_expense(self, entry: Dict[str, Any]) -> int:
        """Add an expense entry. Returns the expense ID."""
        pass

    @abstractmethod
    def get_expenses(self, member_id: Optional[int] = None, from_date: Optional[str] = None,
                     to_date: Optional[str] = None, category: Optional[str] = None,
                     search: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch expense entries with optional filters."""
        pass

    @abstractmethod
    def delete_expense(self, expense_id: int) -> bool:
        """Remove an expense entry by ID."""
        pass

    @abstractmethod
    def get_expense_summary(self, fy: str) -> Dict[str, float]:
        """Get total expense amounts per category for a given FY."""
        pass

    # ── Expense Categories ────────────────────────────────────────────

    @abstractmethod
    def get_expense_categories(self, parent: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all expense categories, optionally filtered by parent."""
        pass

    @abstractmethod
    def add_expense_category(self, name: str, parent: Optional[str] = None) -> int:
        """Add a new expense category. Returns ID."""
        pass

    @abstractmethod
    def delete_expense_category(self, category_id: int) -> bool:
        """Remove an expense category (fails if in-use)."""
        pass

    # ── Split Rules ───────────────────────────────────────────────────

    @abstractmethod
    def get_split_rules(self) -> List[Dict[str, Any]]:
        """Fetch all split rules."""
        pass

    @abstractmethod
    def add_split_rule(self, source_member_id: int, member_ids: List[int]) -> int:
        """Add a split rule: source member + all members in group."""
        pass

    @abstractmethod
    def delete_split_rule(self, rule_id: int) -> bool:
        """Remove a split rule."""
        pass

    @abstractmethod
    def get_split_group_for_member(self, member_id: int) -> Optional[List[int]]:
        """If member_id is the source of a split rule, return the full member group list. Else None."""
        pass

    # ── Reports & Processed Statements ──────────────────────────────

    @abstractmethod
    def refresh_reports_sheet(self):
        """Regenerate the Reports sheet with current outstanding balances."""
        raise NotImplementedError

    @abstractmethod
    def get_processed_statements(self) -> List[Dict[str, Any]]:
        """Fetch all processed bank statement records."""
        raise NotImplementedError

    @abstractmethod
    def record_processed_statement(self, filename: str, date_range: str,
                                    entry_count: int, fmt: str, file_hash: str):
        """Record a successfully processed bank statement."""
        raise NotImplementedError

    @abstractmethod
    def get_member_ledger_all(self) -> List[Dict[str, Any]]:
        """Fetch the entire ledger (all members)."""
        raise NotImplementedError

    # ── Identifiers (all types) ──────────────────────────────────────

    @abstractmethod
    def get_all_identifiers(self, id_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all identifiers, optionally filtered by type."""
        pass

    @abstractmethod
    def delete_identifier(self, ref_id: int) -> bool:
        """Remove a payment/expense identifier by its row ID."""
        pass

    @abstractmethod
    def add_identifier(self, member_id: int, id_type: str, id_value: str,
                       date: str = None, confidence: int = 1) -> int:
        """Add a new identifier manually."""
        pass

    @abstractmethod
    def update_identifier_member(self, idr_id: int, new_member_id: int) -> bool:
        """Reassign an identifier record to a different member."""
        pass

    # ── Accounts Sheet ─────────────────────────────────────────────────

    @abstractmethod
    def add_accounts_entries(self, entries: List[Dict[str, Any]]) -> int:
        """Add bank statement entries to the Accounts sheet. Returns count added."""
        pass

    @abstractmethod
    def get_accounts_entries(
        self, source_file: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch Accounts entries, optionally filtered by source file and/or status."""
        pass

    @abstractmethod
    def update_accounts_entry(self, entry_id: int, updates: Dict[str, Any]) -> bool:
        """Update a single Accounts entry by Entry_ID."""
        pass

    @abstractmethod
    def delete_accounts_entries(self, entry_ids: List[int]) -> int:
        """Delete Accounts entries by Entry_ID list. Returns count deleted."""
        pass

    @abstractmethod
    def get_accounts_summary(self) -> Dict[str, Any]:
        """Return per-statement balance validation summary and gap report."""
        pass

    @abstractmethod
    def clear_accounts(self) -> int:
        """Delete all Accounts entries. Returns count deleted."""
        pass

    @abstractmethod
    def migrate_accounts_from_ledger(self) -> int:
        """One-time: reconstruct Accounts sheet from existing Ledger + Expenses + Suspense data.
        Returns count of entries created."""
        pass

    # ── Communication Log ───────────────────────────────────────────────

    @abstractmethod
    def log_communication(self, member_id: int, template_type: str, subject: str,
                          recipients: str, cc: str, status: str,
                          document_refs: str = "", error: str = "") -> int:
        """Record an email/communication send attempt. Returns record ID."""
        pass

    @abstractmethod
    def get_communication_log(self, member_id: Optional[int] = None,
                              limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch recent communication log entries, optionally filtered by member."""
        pass
