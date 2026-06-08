"""tests/test_whatsapp.py"""
import pytest
from utils.whatsapp import build_wa_message, build_wa_link, copy_to_clipboard


def test_build_wa_message_receipt():
    member = {"Plot_No": "25", "Plot_Owner_Name": "Anil Sharma"}
    summary = None
    entries = [{"date": "01-06-2026", "amount": 5000, "ref_id": "26-27-005",
                "particulars": "By NEFT", "type": "CR"}]
    pdf_names = ["Receipt_Plot_No_25_26-27-005.pdf"]
    msg = build_wa_message("receipt", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "\n25\n" in msg
    assert "Dear Anil Sharma" in msg
    assert "₹5,000" in msg or "₹ 5,000" in msg
    assert "Receipt_Plot_No_25_26-27-005.pdf" in msg


def test_build_wa_message_invoice_with_summary():
    member = {"Plot_No": "12", "Plot_Owner_Name": "Amit Patel"}
    summary = {
        "previous_outstanding": 2500, "total_demand": 12000,
        "total_payments": 3000, "total_due": 11500,
        "as_of_date": "15-06-2026",
    }
    entries = [{"date": "01-06-2026", "amount": 12000, "ref_id": "26-27-001",
                "particulars": "Invoice for FY 26-27", "type": "DR"}]
    pdf_names = ["Invoice_Plot_No_12_26-27-001.pdf"]
    msg = build_wa_message("invoice", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "\n12\n" in msg
    assert "Dear Amit Patel" in msg
    assert "Invoice" in msg
    assert "Balance carried forward" in msg
    assert "₹2,500" in msg or "₹ 2,500" in msg
    assert "New Invoice Demand" in msg
    assert "₹12,000" in msg or "₹ 12,000" in msg
    assert "Outstanding" in msg
    assert "₹11,500" in msg or "₹ 11,500" in msg


def test_build_wa_message_statement():
    member = {"Plot_No": "5", "Plot_Owner_Name": "Priya Singh"}
    summary = {
        "previous_outstanding": 0, "total_demand": 12000,
        "total_payments": 8000, "total_due": 4000,
        "as_of_date": "15-06-2026",
    }
    entries = [
        {"date": "01-04-2026", "amount": 12000, "ref_id": "26-27-001",
         "particulars": "Invoice", "type": "DR"},
        {"date": "10-05-2026", "amount": 5000, "ref_id": "26-27-003",
         "particulars": "By NEFT", "type": "CR"},
        {"date": "01-06-2026", "amount": 3000, "ref_id": "26-27-005",
         "particulars": "By UPI", "type": "CR"},
    ]
    pdf_names = ["Invoice_Plot_No_5_26-27-001.pdf", "Receipt_Plot_No_5_26-27-003.pdf"]
    msg = build_wa_message("statement", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "\n5\n" in msg
    assert "statement" in msg
    assert "Summary" in msg
    assert "Attached Documents" in msg
    assert pdf_names[0] in msg


def test_build_wa_message_reminder():
    member = {"Plot_No": "8", "Plot_Owner_Name": "Rajesh Kumar"}
    summary = {
        "previous_outstanding": 1000, "total_demand": 12000,
        "total_payments": 2000, "total_due": 11000,
        "as_of_date": "15-06-2026",
    }
    entries = []
    pdf_names = []
    msg = build_wa_message("reminder", member, summary, entries, pdf_names)
    assert "Weekend Ville Society" in msg
    assert "\n8\n" in msg
    assert "reminder" in msg
    assert "Outstanding" in msg


def test_build_wa_link():
    phone = "9876543210"
    text = "Hello World"
    link = build_wa_link(phone, text)
    assert link.startswith("https://wa.me/919876543210?text=")
    assert "Hello%20World" in link


def test_build_wa_link_with_country_code():
    phone = "+1-555-1234"
    text = "Test"
    link = build_wa_link(phone, text, country_code="1")
    assert "15551234" in link


def test_copy_to_clipboard_returns_bool():
    result = copy_to_clipboard("test")
    assert isinstance(result, bool)
