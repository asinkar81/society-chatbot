"""
Comprehensive test suite for the Society Management Chatbot
"""
import sys
sys.path.insert(0, '/Users/ashutoshsinkar/society-chatbot')

import unittest
from pathlib import Path
import tempfile
import config
from data_providers.local_excel_provider import LocalExcelDataProvider
from file_storage.local_storage import LocalFileStorage
from utils.converters import number_to_words_inr, format_amount, get_fy_string


class TestDataProvider(unittest.TestCase):
    """Test data provider functionality"""

    def setUp(self):
        """Create temporary Excel file for testing"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_data.xlsx"
        self.provider = LocalExcelDataProvider(self.test_file)

    def tearDown(self):
        """Cleanup"""
        self.temp_dir.cleanup()

    def test_workbook_creation(self):
        """Test that workbook is created with required sheets"""
        self.assertTrue(self.test_file.exists())
        print("✓ Workbook creation test passed")

    def test_add_member(self):
        """Test adding a member"""
        member_data = {
            "Plot_No": "01",
            "Plot_Owner_Name": "Test Member",
            "Email": "test@example.com",
            "Phone": "9876543210",
            "Current_Outstanding": 0,
            "Pending_Interest": 0,
        }
        member_id = self.provider.add_member(member_data)
        self.assertIsNotNone(member_id)
        print("✓ Add member test passed")

    def test_get_member(self):
        """Test retrieving a member"""
        member_data = {
            "Plot_No": "02",
            "Plot_Owner_Name": "Another Member",
            "Email": "another@example.com",
            "Phone": "9876543211",
            "Current_Outstanding": 50000,
            "Pending_Interest": 0,
        }
        member_id = self.provider.add_member(member_data)
        retrieved = self.provider.get_member(member_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["Plot_Owner_Name"], "Another Member")
        print("✓ Get member test passed")

    def test_ledger_entry(self):
        """Test adding ledger entry"""
        # Add a member first
        member_data = {
            "Plot_No": "03",
            "Plot_Owner_Name": "Test for Ledger",
            "Email": "ledger@example.com",
            "Phone": "9876543212",
            "Current_Outstanding": 0,
            "Pending_Interest": 0,
        }
        member_id = self.provider.add_member(member_data)

        # Add ledger entry
        entry = {
            "Date": "01-04-2026",
            "Particulars": "Test Entry",
            "Vch_Type": "Journal",
            "Vch_No": 1,
            "Debit": 1000,
            "Credit": None,
            "Description": "Test",
        }
        success = self.provider.add_ledger_entry(member_id, entry)
        self.assertTrue(success)
        print("✓ Ledger entry test passed")

    def test_settings(self):
        """Test settings management"""
        settings = self.provider.get_settings()
        self.assertIn("Current_FY", settings)
        print("✓ Settings test passed")


class TestFileStorage(unittest.TestCase):
    """Test file storage functionality"""

    def setUp(self):
        """Create temporary directory for testing"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = LocalFileStorage(Path(self.temp_dir.name))

    def tearDown(self):
        """Cleanup"""
        self.temp_dir.cleanup()

    def test_folder_creation(self):
        """Test folder creation"""
        success = self.storage.create_folder("test_folder")
        self.assertTrue(success)
        print("✓ Folder creation test passed")

    def test_file_upload(self):
        """Test file upload"""
        # Create a test file
        test_content = "test content"
        test_file = Path(self.temp_dir.name) / "source.txt"
        test_file.write_text(test_content)

        # Upload it
        result = self.storage.upload(str(test_file), "uploads", "uploaded.txt")
        self.assertIsNotNone(result)
        print("✓ File upload test passed")

    def test_file_exists(self):
        """Test file existence check"""
        test_file = Path(self.temp_dir.name) / "source2.txt"
        test_file.write_text("test")
        self.storage.upload(str(test_file), "uploads", "test2.txt")

        exists = self.storage.file_exists("uploads/test2.txt")
        self.assertTrue(exists)
        print("✓ File exists test passed")


class TestConverters(unittest.TestCase):
    """Test utility converters"""

    def test_number_to_words(self):
        """Test number to words conversion"""
        result = number_to_words_inr(53000)
        self.assertIn("Thousand", result)
        print(f"✓ Number to words test passed: {result}")

    def test_format_amount(self):
        """Test amount formatting"""
        result = format_amount(12345.67)
        self.assertIn("₹", result)
        self.assertIn(",", result)
        print(f"✓ Format amount test passed: {result}")

    def test_get_fy_string(self):
        """Test FY string generation"""
        result = get_fy_string()
        self.assertIn("-", result)
        print(f"✓ FY string test passed: {result}")


def run_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("RUNNING TEST SUITE")
    print("="*60 + "\n")

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestDataProvider))
    suite.addTests(loader.loadTestsFromTestCase(TestFileStorage))
    suite.addTests(loader.loadTestsFromTestCase(TestConverters))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "="*60)
    if result.wasSuccessful():
        print("✓ ALL TESTS PASSED!")
    else:
        print(f"✗ {len(result.failures)} tests failed")
    print("="*60 + "\n")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
