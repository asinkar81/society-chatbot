"""
Comprehensive test suite for all new features:
- Suspense Entries (add, get, tag, delete)
- Ledger Management (delete_ledger_entry, recalculation)
- Duplicate Detection (check_duplicate_ledger_entry)
- Invoice Regeneration (parse_invoice_entry, regenerate)
- Filter Helpers (fy_date_range, filter_entries, get_available_fys)
- Payment References
"""
import sys
sys.path.insert(0, '/Users/ashutoshsinkar/society-chatbot')

import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import pandas as pd

import config
from data_providers.local_excel_provider import LocalExcelDataProvider
from utils.converters import get_fy_from_date, get_fy_string


# ── Helper functions (copied from main.py for testability) ────────────

def _fy_date_range(fy: str) -> tuple:
    try:
        parts = fy.split("-")
        start_yr = int(parts[0]) + 2000
        end_yr = int(parts[1]) + 2000
        return (f"01-04-{start_yr}", f"31-03-{end_yr}")
    except Exception:
        return ("", "")


def _get_available_fys(entries: List[Dict]) -> List[str]:
    fys = set()
    for e in entries:
        d = str(e.get("Date", "") or "")
        if d:
            fys.add(get_fy_from_date(d))
    return sorted(fys, reverse=True)


def _sf(val) -> float:
    if val is None:
        return 0.0
    try:
        v = float(val)
        return 0.0 if v != v else v
    except (ValueError, TypeError):
        return 0.0


def _sortable_dd(dd: str) -> str:
    try:
        p = dd.split("-")
        return f"{p[2]}-{p[1]}-{p[0]}"
    except Exception:
        return dd


def _filter_entries(entries: List[Dict], entry_type: str, from_dt: str, to_dt: str) -> List[Dict]:
    result = []
    from_key = _sortable_dd(from_dt) if from_dt else ""
    to_key = _sortable_dd(to_dt) if to_dt else ""
    for e in entries:
        d = str(e.get("Date", "") or "")
        d_key = _sortable_dd(d)
        if from_key and d_key < from_key:
            continue
        if to_key and d_key > to_key:
            continue
        deb = _sf(e.get("Debit"))
        cr = _sf(e.get("Credit"))
        if entry_type == "Debit" and deb <= 0:
            continue
        if entry_type == "Credit" and cr <= 0:
            continue
        result.append(e)
    return result


def _parse_invoice_entry(entry: Dict) -> Optional[Dict]:
    import re
    desc = str(entry.get("Description", "") or "")
    parts = str(entry.get("Particulars", "") or "")
    m = re.search(r"Invoice\s+(\w+)\s+FY\s+(\d{2}-\d{2})", desc)
    if not m:
        return None
    invoice_no = m.group(1)
    fy_str = m.group(2)
    m2 = re.search(r"\((\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4}),\s+(\d+)\s+months\)", parts)
    if m2:
        from_date = m2.group(1)
        to_date = m2.group(2)
        months = int(m2.group(3))
    else:
        from_date, to_date = _fy_date_range(fy_str)
        months = 12
    return {
        "invoice_no": invoice_no,
        "fy": fy_str,
        "from_date": from_date,
        "to_date": to_date,
        "months": months,
    }


def _extract_ref_id(desc: str) -> Optional[str]:
    import re
    lower = desc.lower()
    for tok in desc.split():
        if re.match(r"^\d{2}-\d{2}$", tok):
            continue
        if any(c.isdigit() for c in tok) and "-" in tok:
            return tok
    if "invoice" in lower:
        for tok in desc.split():
            if re.match(r"^\d{2}-\d{2}$", tok):
                continue
            if any(c.isdigit() for c in tok) and not tok.startswith("FY"):
                return tok
    return None


# ── Test Classes ─────────────────────────────────────────────────────

class TestSuspenseEntries(unittest.TestCase):
    """Test Suspense_Entries CRUD operations"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_suspense.xlsx"
        self.provider = LocalExcelDataProvider(self.test_file)
        # Add a member to reference in tag tests
        mid = self.provider.add_member({
            "Plot_No": "99",
            "Plot_Owner_Name": "Suspense Test Member",
            "Email": "suspense@test.com",
            "Phone": "9999999999",
            "Current_Outstanding": 0,
            "Pending_Interest": 0,
        })
        self.member_id = mid

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_suspense_entry(self):
        """Test adding a suspense entry returns a valid ID"""
        eid = self.provider.add_suspense_entry({
            "Date": "15-06-2026",
            "Particulars": "Test payment",
            "Amount": 5000.00,
            "Transaction_ID": "TXN001",
            "Transaction_Type": "NEFT",
            "Description": "From bank statement",
        })
        self.assertIsNotNone(eid)
        self.assertGreater(eid, 0)
        print("  ✓ add_suspense_entry returns valid ID")

    def test_get_suspense_entries_empty(self):
        """Test getting suspense entries when none exist"""
        entries = self.provider.get_suspense_entries()
        self.assertEqual(entries, [])
        print("  ✓ get_suspense_entries returns empty list when none exist")

    def test_get_suspense_entries_pending(self):
        """Test getting pending suspense entries"""
        self.provider.add_suspense_entry({
            "Date": "15-06-2026",
            "Particulars": "Test payment",
            "Amount": 5000.00,
            "Transaction_ID": "TXN001",
            "Transaction_Type": "NEFT",
            "Description": "From bank statement",
        })
        entries = self.provider.get_suspense_entries(status="Pending")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["Status"], "Pending")
        print("  ✓ get_suspense_entries returns pending entries")

    def test_tag_suspense_entry(self):
        """Test tagging a suspense entry to a member"""
        eid = self.provider.add_suspense_entry({
            "Date": "15-06-2026",
            "Particulars": "Test payment",
            "Amount": 5000.00,
            "Transaction_ID": "TXN001",
            "Transaction_Type": "NEFT",
            "Description": "From bank statement",
        })
        success = self.provider.tag_suspense_entry(eid, self.member_id)
        self.assertTrue(success)
        entries = self.provider.get_suspense_entries(status="Tagged")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["Tagged_To"], self.member_id)
        print("  ✓ tag_suspense_entry sets status to Tagged")

    def test_tag_suspense_entry_invalid_id(self):
        """Test tagging non-existent entry returns False"""
        success = self.provider.tag_suspense_entry(99999, self.member_id)
        self.assertFalse(success)
        print("  ✓ tag_suspense_entry with invalid ID returns False")

    def test_delete_suspense_entry(self):
        """Test deleting a suspense entry"""
        eid = self.provider.add_suspense_entry({
            "Date": "15-06-2026",
            "Particulars": "To be deleted",
            "Amount": 1000.00,
        })
        success = self.provider.delete_suspense_entry(eid)
        self.assertTrue(success)
        entries = self.provider.get_suspense_entries()
        self.assertEqual(len(entries), 0)
        print("  ✓ delete_suspense_entry removes the entry")

    def test_delete_suspense_entry_invalid_id(self):
        """Test deleting non-existent entry returns False"""
        success = self.provider.delete_suspense_entry(99999)
        self.assertFalse(success)
        print("  ✓ delete_suspense_entry with invalid ID returns False")

    def test_suspense_roundtrip(self):
        """Full roundtrip: add → list pending → tag → list tagged → delete all"""
        ids = []
        for i in range(3):
            eid = self.provider.add_suspense_entry({
                "Date": f"{i+1:02d}-06-2026",
                "Particulars": f"Payment {i+1}",
                "Amount": (i + 1) * 1000.0,
            })
            ids.append(eid)
        self.assertEqual(len(self.provider.get_suspense_entries(status="Pending")), 3)
        # Tag one
        self.provider.tag_suspense_entry(ids[0], self.member_id)
        self.assertEqual(len(self.provider.get_suspense_entries(status="Pending")), 2)
        self.assertEqual(len(self.provider.get_suspense_entries(status="Tagged")), 1)
        # Delete all
        for eid in ids:
            self.provider.delete_suspense_entry(eid)
        self.assertEqual(len(self.provider.get_suspense_entries()), 0)
        print("  ✓ Suspense roundtrip (add→tag→delete) succeeded")


class TestLedgerDelete(unittest.TestCase):
    """Test ledger entry deletion and outstanding recalculation"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_ledger.xlsx"
        self.provider = LocalExcelDataProvider(self.test_file)
        self.member_id = self.provider.add_member({
            "Plot_No": "10",
            "Plot_Owner_Name": "Ledger Test",
            "Email": "ledger@test.com",
            "Phone": "8888888888",
            "Current_Outstanding": 0,
            "Pending_Interest": 0,
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def _add_entry(self, date, debit=None, credit=None, desc="Test"):
        vch = self.provider.get_next_voucher_number()
        self.provider.add_ledger_entry(self.member_id, {
            "Date": date,
            "Particulars": desc,
            "Vch_Type": "Journal",
            "Vch_No": vch,
            "Debit": debit,
            "Credit": credit,
            "Description": desc,
        })
        return vch

    def test_delete_ledger_entry(self):
        """Test deleting a ledger entry"""
        vch = self._add_entry("01-06-2026", debit=5000)
        self.provider.update_member(self.member_id, {"Current_Outstanding": -5000})
        success = self.provider.delete_ledger_entry(self.member_id, vch)
        self.assertTrue(success)
        ledger = self.provider.get_member_ledger(self.member_id)
        vchs = [e.get("Vch_No") for e in ledger]
        self.assertNotIn(vch, vchs)
        print("  ✓ delete_ledger_entry removes entry from ledger")

    def test_delete_ledger_entry_recalculates_outstanding(self):
        """Test that deleting an entry recalculates outstanding"""
        self._add_entry("01-04-2026", credit=10000)
        self._add_entry("01-05-2026", debit=3000)
        vch_to_delete = self._add_entry("01-06-2026", debit=2000)
        self.provider.update_member(self.member_id, {"Current_Outstanding": 5000})
        # Delete the 2000 debit
        self.provider.delete_ledger_entry(self.member_id, vch_to_delete)
        o = self.provider.get_current_outstanding(self.member_id)
        # Expected: 10000 credit - 3000 debit = 7000
        self.assertAlmostEqual(o, 7000.0, places=2)
        print("  ✓ delete_ledger_entry recalculates outstanding correctly")

    def test_delete_ledger_entry_invalid(self):
        """Test deleting non-existent entry returns False"""
        success = self.provider.delete_ledger_entry(self.member_id, 99999)
        self.assertFalse(success)
        print("  ✓ delete_ledger_entry with invalid Vch_No returns False")

    def test_delete_ledger_entry_removes_from_both_sheets(self):
        """Test entry is removed from both main Ledger and per-plot sheets"""
        vch = self._add_entry("01-04-2026", credit=5000)
        # Verify it's in main sheet
        df_main = pd.read_excel(self.test_file, sheet_name="Ledger")
        self.assertIn(vch, df_main["Vch_No"].values)
        # Verify it's in per-plot sheet
        plot_no = self.provider._get_plot_no(self.member_id)
        sheet_name = self.provider._plot_ledger_sheet(plot_no)
        df_plot = pd.read_excel(self.test_file, sheet_name=sheet_name)
        self.assertIn(vch, df_plot["Vch_No"].values)
        # Delete and verify both
        self.provider.delete_ledger_entry(self.member_id, vch)
        df_main = pd.read_excel(self.test_file, sheet_name="Ledger")
        self.assertNotIn(vch, df_main["Vch_No"].values)
        df_plot = pd.read_excel(self.test_file, sheet_name=sheet_name)
        self.assertNotIn(vch, df_plot["Vch_No"].values)
        print("  ✓ delete_ledger_entry removes from both sheets")


class TestDuplicateDetection(unittest.TestCase):
    """Test duplicate ledger entry detection"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_dup.xlsx"
        self.provider = LocalExcelDataProvider(self.test_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_no_duplicate(self):
        """Test no duplicate found for non-existent entry"""
        result = self.provider.check_duplicate_ledger_entry(
            "TXN999", "01-06-2026", 5000
        )
        self.assertIsNone(result)
        print("  ✓ check_duplicate_ledger_entry returns None for no match")

    def test_detect_duplicate_by_txn_id(self):
        """Test duplicate detection by Transaction_ID"""
        mid = self.provider.add_member({
            "Plot_No": "11", "Plot_Owner_Name": "Dup Test",
            "Email": "dup@test.com", "Phone": "7777777777",
            "Current_Outstanding": 0, "Pending_Interest": 0,
        })
        vch = self.provider.get_next_voucher_number()
        self.provider.add_ledger_entry(mid, {
            "Date": "01-06-2026", "Particulars": "By Test",
            "Vch_Type": "Journal", "Vch_No": vch,
            "Debit": None, "Credit": 5000,
            "Description": "Receipt 26-27-001 — Test",
            "Transaction_ID": "TXN001",
        })
        result = self.provider.check_duplicate_ledger_entry(
            "TXN001", "01-06-2026", 5000
        )
        self.assertIsNotNone(result)
        print("  ✓ check_duplicate_ledger_entry detects by Transaction_ID")

    def test_detect_duplicate_by_particulars(self):
        """Test duplicate detection by particulars (fallback)"""
        mid = self.provider.add_member({
            "Plot_No": "12", "Plot_Owner_Name": "Dup Part Test",
            "Email": "dup2@test.com", "Phone": "6666666666",
            "Current_Outstanding": 0, "Pending_Interest": 0,
        })
        vch = self.provider.get_next_voucher_number()
        self.provider.add_ledger_entry(mid, {
            "Date": "15-06-2026", "Particulars": "By NEFT ABC123",
            "Vch_Type": "Journal", "Vch_No": vch,
            "Debit": None, "Credit": 3000,
            "Description": "Receipt — Test",
            "Transaction_ID": "",
        })
        result = self.provider.check_duplicate_ledger_entry(
            "", "15-06-2026", 3000, particulars="NEFT ABC123"
        )
        self.assertIsNotNone(result)
        print("  ✓ check_duplicate_ledger_entry detects by particulars prefix")


class TestInvoiceParsing(unittest.TestCase):
    """Test invoice entry parsing logic"""

    def test_parse_full_details(self):
        """Test parsing invoice with full Particulars"""
        entry = {
            "Description": "Invoice 0051121 FY 21-22",
            "Particulars": "To Annual Maintenance Charges (01-11-2021 to 31-03-2022, 5 months)",
            "Debit": 5000,
            "Credit": None,
        }
        result = _parse_invoice_entry(entry)
        self.assertIsNotNone(result)
        self.assertEqual(result["invoice_no"], "0051121")
        self.assertEqual(result["fy"], "21-22")
        self.assertEqual(result["from_date"], "01-11-2021")
        self.assertEqual(result["to_date"], "31-03-2022")
        self.assertEqual(result["months"], 5)
        print("  ✓ _parse_invoice_entry extracts all fields from full details")

    def test_parse_regenerated(self):
        """Test parsing regenerated invoice (description has '(regenerated)' suffix)"""
        entry = {
            "Description": "Invoice 0051121 FY 21-22 (regenerated)",
            "Particulars": "To Annual Maintenance Charges (01-11-2021 to 31-03-2022, 5 months)",
            "Debit": 5000,
            "Credit": None,
        }
        result = _parse_invoice_entry(entry)
        self.assertIsNotNone(result)
        self.assertEqual(result["invoice_no"], "0051121")
        print("  ✓ _parse_invoice_entry handles regenerated description suffix")

    def test_parse_fy_fallback(self):
        """Test parsing invoice that falls back to FY-based dates"""
        entry = {
            "Description": "Invoice 0991231 FY 24-25",
            "Particulars": "To Annual Maintenance Charges",
            "Debit": 10000,
            "Credit": None,
        }
        result = _parse_invoice_entry(entry)
        self.assertIsNotNone(result)
        self.assertEqual(result["fy"], "24-25")
        self.assertEqual(result["from_date"], "01-04-2024")
        self.assertEqual(result["to_date"], "31-03-2025")
        self.assertEqual(result["months"], 12)
        print("  ✓ _parse_invoice_entry falls back to FY-based dates")

    def test_parse_no_invoice(self):
        """Test parsing non-invoice entry returns None"""
        entry = {
            "Description": "Receipt 26-27-001",
            "Particulars": "By NEFT",
            "Debit": None,
            "Credit": 5000,
        }
        result = _parse_invoice_entry(entry)
        self.assertIsNone(result)
        print("  ✓ _parse_invoice_entry returns None for non-invoice entries")


class TestHelperFunctions(unittest.TestCase):
    """Test standalone helper functions"""

    def test_fy_date_range(self):
        """Test FY date range conversion"""
        fd, td = _fy_date_range("24-25")
        self.assertEqual(fd, "01-04-2024")
        self.assertEqual(td, "31-03-2025")
        print("  ✓ _fy_date_range converts '24-25' correctly")

    def test_fy_date_range_invalid(self):
        """Test FY date range with invalid input"""
        fd, td = _fy_date_range("invalid")
        self.assertEqual(fd, "")
        self.assertEqual(td, "")
        print("  ✓ _fy_date_range handles invalid input gracefully")

    def test_get_available_fys(self):
        """Test extracting unique FYs from entries"""
        entries = [
            {"Date": "15-06-2024"},
            {"Date": "20-12-2024"},
            {"Date": "05-01-2025"},
            {"Date": "10-08-2023"},
        ]
        fys = _get_available_fys(entries)
        self.assertIn("24-25", fys)
        self.assertIn("23-24", fys)
        self.assertEqual(len(fys), 2)
        # Should be sorted desc
        self.assertEqual(fys, sorted(fys, reverse=True))
        print("  ✓ _get_available_fys extracts unique FYs sorted desc")

    def test_filter_entries_all(self):
        """Test filter with type='All' returns all entries in range"""
        entries = [
            {"Date": "01-04-2024", "Debit": 1000, "Credit": 0},
            {"Date": "15-06-2024", "Debit": 0, "Credit": 500},
            {"Date": "01-08-2025", "Debit": 2000, "Credit": 0},
        ]
        result = _filter_entries(entries, "All", "01-04-2024", "31-03-2025")
        self.assertEqual(len(result), 2)  # Only first two are in FY 24-25
        print("  ✓ _filter_entries with All returns correct count")

    def test_filter_entries_debit(self):
        """Test filter with type='Debit'"""
        entries = [
            {"Date": "01-04-2024", "Debit": 1000, "Credit": 0},
            {"Date": "15-06-2024", "Debit": 0, "Credit": 500},
        ]
        result = _filter_entries(entries, "Debit", "", "")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Debit"], 1000)
        print("  ✓ _filter_entries with Debit returns only debit entries")

    def test_filter_entries_credit(self):
        """Test filter with type='Credit'"""
        entries = [
            {"Date": "01-04-2024", "Debit": 1000, "Credit": 0},
            {"Date": "15-06-2024", "Debit": 0, "Credit": 500},
        ]
        result = _filter_entries(entries, "Credit", "", "")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Credit"], 500)
        print("  ✓ _filter_entries with Credit returns only credit entries")

    def test_filter_entries_no_date_range(self):
        """Test filter with empty date range returns all entries"""
        entries = [
            {"Date": "01-04-2024", "Debit": 100, "Credit": 0},
            {"Date": "01-04-2025", "Debit": 0, "Credit": 200},
        ]
        result = _filter_entries(entries, "All", "", "")
        self.assertEqual(len(result), 2)
        print("  ✓ _filter_entries with no date range returns all")

    def test_extract_ref_id_receipt(self):
        """Test extracting receipt ID from description"""
        desc = "Receipt 26-27-297 — Manual Bank Statement (NEFT)"
        result = _extract_ref_id(desc)
        self.assertEqual(result, "26-27-297")
        print("  ✓ _extract_ref_id extracts receipt ID with dashes")

    def test_extract_ref_id_invoice(self):
        """Test extracting invoice reference from description"""
        desc = "Invoice 0051121 FY 24-25"
        result = _extract_ref_id(desc)
        self.assertEqual(result, "0051121")
        print("  ✓ _extract_ref_id extracts invoice number")


class TestPaymentReferences(unittest.TestCase):
    """Test payment reference store and lookup"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_payref.xlsx"
        self.provider = LocalExcelDataProvider(self.test_file)
        self.member_id = self.provider.add_member({
            "Plot_No": "15",
            "Plot_Owner_Name": "PayRef Test",
            "Email": "payref@test.com",
            "Phone": "5555555555",
            "Current_Outstanding": 0,
            "Pending_Interest": 0,
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_and_identify_upi(self):
        self.provider.record_payment_reference(self.member_id, "UPI_ID", "test@paytm", "01-06-2026")
        found = self.provider.find_member_by_identifier("test@paytm")
        self.assertIsNotNone(found)
        self.assertEqual(found["ID"], self.member_id)
        print("  ✓ find_member_by_identifier finds by UPI ID")

    def test_record_and_identify_mobile(self):
        self.provider.record_payment_reference(self.member_id, "MOBILE", "9876543210", "01-06-2026")
        found = self.provider.find_member_by_identifier("9876543210")
        self.assertIsNotNone(found)
        print("  ✓ find_member_by_identifier finds by mobile")

    def test_known_identifiers(self):
        # Call multiple times to raise confidence for UPI
        self.provider.record_payment_reference(self.member_id, "UPI_ID", "test@phonepe", "01-06-2026")
        self.provider.record_payment_reference(self.member_id, "UPI_ID", "test@phonepe", "01-06-2026")  # confidence → 2
        self.provider.record_payment_reference(self.member_id, "UPI_ID", "test@phonepe", "01-06-2026")  # confidence → 3
        self.provider.record_payment_reference(self.member_id, "PAYEE_NAME", "TEST USER", "01-06-2026")  # confidence → 1
        ids = self.provider.get_known_identifiers(self.member_id, min_confidence=2)
        self.assertEqual(len(ids), 1)
        self.assertEqual(ids[0]["Identifier_Value"], "test@phonepe")
        print("  ✓ get_known_identifiers filters by confidence threshold")

    def test_no_match_for_unknown(self):
        found = self.provider.find_member_by_identifier("nonexistent@xyz.com")
        self.assertIsNone(found)
        print("  ✓ find_member_by_identifier returns None for unknown")


class TestSettingsConsistency(unittest.TestCase):
    """Test settings are persisted correctly"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_settings.xlsx"
        self.provider = LocalExcelDataProvider(self.test_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_settings_roundtrip(self):
        settings = self.provider.get_settings()
        settings["Repair_Fund_Rate"] = "200"
        self.provider.update_settings(settings)
        retrieved = self.provider.get_settings()
        val = retrieved.get("Repair_Fund_Rate")
        self.assertTrue(val == "200" or val == 200,
                        f"Expected '200' or 200, got {repr(val)}")
        print("  ✓ Settings roundtrip preserves values")

    def test_default_settings(self):
        settings = self.provider.get_settings()
        self.assertIn("Current_FY", settings)
        self.assertIn("Repair_Fund_Rate", settings)
        self.assertIn("Service_Charges_Rate", settings)
        self.assertIn("Sinking_Fund_Rate", settings)
        print("  ✓ Default settings have all required keys")


def run_tests():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("  COMPREHENSIVE TEST SUITE — NEW FEATURES")
    print("=" * 60 + "\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestSuspenseEntries))
    suite.addTests(loader.loadTestsFromTestCase(TestLedgerDelete))
    suite.addTests(loader.loadTestsFromTestCase(TestDuplicateDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestInvoiceParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestHelperFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestPaymentReferences))
    suite.addTests(loader.loadTestsFromTestCase(TestSettingsConsistency))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    tests_run = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    print(f"  Tests run: {tests_run}  |  Passed: {tests_run - failures - errors}  |  "
          f"Failures: {failures}  |  Errors: {errors}")
    if result.wasSuccessful():
        print("  ✅ ALL TESTS PASSED!")
        print("=" * 60 + "\n")
    else:
        print("  ❌ SOME TESTS FAILED")
        print("=" * 60 + "\n")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
