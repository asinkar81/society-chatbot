import pytest
from tools.pdf_parser import extract_text_from_pdf, detect_format, clean_entries, parse_bank_pdf


def test_detect_format_netbanking():
    lines = [
        "01-04-2024 NEFT X12345 SOME DESCRIPTION        1,000.00    1,00,000.00 Cr",
        "02-04-2024 MOBFT Y67890 ANOTHER ENTRY           2,500.00    1,02,500.00 Cr",
    ]
    fmt = detect_format(lines)
    assert fmt == "netbanking", f"Expected netbanking, got {fmt}"


def test_detect_format_email():
    lines = [
        "e-Statement for April 2024",
        "Date        Particulars          Withdrawals    Deposits    Balance",
        "01-04-2024  NEFT X12345                      1,000.00  1,00,000.00",
    ]
    fmt = detect_format(lines)
    assert fmt == "email_attachment", f"Expected email_attachment, got {fmt}"


def test_detect_format_printed():
    lines = [
        "PUNJAB NATIONAL BANK",
        "Page 1 of 2",
        "01-04-2024  NEFT X12345  SOME DESCRIPTION  1,000.00  1,00,000.00",
    ]
    fmt = detect_format(lines)
    assert fmt == "printed_printout", f"Expected printed_printout, got {fmt}"


def test_detect_format_serial_number_prefix():
    lines = [
        "STATEMENT OF ACCOUNT FOR THE PERIOD FROM 01-03-2026 TO 31-03-2026",
        "SI Date Particulars Chq Num Withdrawal Deposit Balance",
        "1 02-03-2026 PANDIT HIRAJI VAIRAL 17060260 12,000.00 5,09,607.62 Cr",
        "2 02-03-2026 CLG:VAISHALI DADAPATIL WALUN 12034759 5,940.00 5,03,667.62 Cr",
    ]
    fmt = detect_format(lines)
    assert fmt == "serial_number_prefix", f"Expected serial_number_prefix, got {fmt}"


def test_detect_format_fallback():
    lines = ["garbage text", "no recognizable format"]
    fmt = detect_format(lines)
    assert fmt == "unknown", f"Expected unknown, got {fmt}"


def test_clean_entries_removes_cumulative():
    raw = [
        "01-04-2024 NEFT X12345 DESCRIPTION          1,000.00    1,00,000.00 Cr",
        "TOTAL DEBITS 50,000.00 5,00,000.00 Cr",
        "02-04-2024 MOBFT Y67890 ANOTHER             2,500.00    1,02,500.00 Cr",
        "BALANCE B/F 5,00,000.00 Cr",
        "03-04-2024 CHQ Z12345 WITHDRAWAL            5,000.00    97,500.00 Dr",
    ]
    result = clean_entries(raw)
    assert len(result) == 3
    assert "NEFT X12345" in result[0]
    assert "TOTAL DEBITS" not in "\n".join(result)
    assert "BALANCE B/F" not in "\n".join(result)


def test_clean_entries_continuation_lines():
    raw = [
        "01-04-2024 NEFT X12345 DESCRIPTION LINE 1",
        "  CONTINUATION LINE 2",
        "  CONTINUATION LINE 3  1,000.00    1,00,000.00 Cr",
    ]
    result = clean_entries(raw)
    assert len(result) == 1
    assert "CONTINUATION LINE 2" in result[0]


def test_clean_entries_serial_number_prefix():
    """Strips serial numbers before dates and skips headers in serial-number format."""
    raw = [
        "STATEMENT OF ACCOUNT FOR THE PERIOD FROM 01-03-2026 TO 31-03-2026",
        "SI Date Particulars Chq Num Withdrawal Deposit Balance",
        "1 02-03-2026 PANDIT HIRAJI VAIRAL 17060260 12,000.00 5,09,607.62 Cr",
        "2 02-03-2026 CLG:VAISHALI DADAPATIL WALUN 12034759 5,940.00 5,03,667.62 Cr",
        "3 04-03-2026 MOBFT/AVINASH BALKRISHNA",
        "B/311483317873 1,000.00 5,04,667.62 Cr",
    ]
    result = clean_entries(raw)
    assert len(result) == 3, f"Expected 3 entries, got {len(result)}: {result}"
    assert result[0].startswith("02-03-2026"), f"Expected date-start, got: {result[0]}"
    assert result[0].startswith("02-03-2026 PANDIT"), f"Expected PANDIT entry, got: {result[0]}"
    assert result[2].startswith("04-03-2026 MOBFT"), "Third entry should start with MOBFT"
    # Continuation line merged
    assert "B/311483317873" in result[2], "Continuation line should be merged"


def test_extract_text_from_pdf_raises_on_missing():
    with pytest.raises(FileNotFoundError):
        extract_text_from_pdf("/nonexistent/pdf.pdf", password="test")


def test_parse_bank_pdf_integration(tmp_path):
    p = tmp_path / "test.pdf"
    with pytest.raises(FileNotFoundError):
        parse_bank_pdf(str(p), password="test")
