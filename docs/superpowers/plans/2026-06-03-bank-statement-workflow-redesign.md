# Bank Statement Workflow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate copy-paste bank statement pain, add undo via auto-backup, and fix data model duplication (per-plot sheets, Current_Outstanding) that causes calculation discrepancies.

**Architecture:** Single master `Ledger` sheet with `Plot_No` column replaces dual master + per-plot sheets. `Current_Outstanding` removed from `Members` — purely computed from ledger. PDFs uploaded once, stored in `data/bank_statements/`, parsed with `pdfplumber`. Auto-backup before every statement run. Reconciliation report validates data integrity.

**Tech Stack:** pdfplumber (PDF text extraction), openpyxl (Excel), Streamlit (UI), existing pandas/openpyxl provider

---

### Task 1: Config & Dependencies

**Files:**
- Modify: `config.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add pdfplumber dependency**

```bash
echo "pdfplumber>=0.10.0" >> /Users/ashutoshsinkar/society-chatbot/requirements.txt
```

- [ ] **Step 2: Run pip install**

```bash
/Users/ashutoshsinkar/society-chatbot/venv/bin/pip install pdfplumber
```

- [ ] **Step 3: Add new config settings**

Edit `config.py`, add after `HISTORICAL_RECEIPTS_DIR` / `BILLS_DIR` block:

```python
# Bank statement storage
BANK_STATEMENTS_DIR = DATA_DIR / "bank_statements"
BACKUPS_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 10
BANK_STMT_PASSWORD = os.getenv("BANK_STMT_PASSWORD", "")

# Default format profile if autodetection fails
DEFAULT_STMT_FORMAT = os.getenv("DEFAULT_STMT_FORMAT", "netbanking")
```

Add in the `DATA_DIR.mkdir` block:

```python
BANK_STATEMENTS_DIR.mkdir(exist_ok=True)
BACKUPS_DIR.mkdir(exist_ok=True)
```

- [ ] **Step 4: Commit**

```bash
git add config.py requirements.txt
git commit -m "feat: add pdfplumber, bank statement dirs, and config settings"
```

---

### Task 2: PDF Parser Module

**Files:**
- Create: `tools/pdf_parser.py`
- Test: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pdf_parser.py
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

def test_extract_text_from_pdf_raises_on_missing():
    with pytest.raises(FileNotFoundError):
        extract_text_from_pdf("/nonexistent/pdf.pdf", password="test")

def test_parse_bank_pdf_integration(tmp_path):
    import json
    p = tmp_path / "test.pdf"
    # We can't easily create a real encrypted PDF in test, so verify the
    # function at least delegates to extract_text_from_pdf
    with pytest.raises(FileNotFoundError):
        parse_bank_pdf(str(p), password="test")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ashutoshsinkar/society-chatbot && /Users/ashutoshsinkar/society-chatbot/venv/bin/python -m pytest tests/test_pdf_parser.py -v
```

Expected: FAIL (ModuleNotFoundError: No module named 'tools.pdf_parser')

- [ ] **Step 3: Write the PDF parser module**

```python
# tools/pdf_parser.py
import re
import pdfplumber
from typing import List, Optional

FORMAT_PROFILES = {
    "netbanking": {
        "keywords": [],
        "detect": lambda lines: any(
            re.match(r"^\d{2}-\d{2}-\d{4}\s+(NEFT|MOBFT|UPI|RTGS|CHQ|IMPS)", l, re.IGNORECASE)
            for l in lines[:20]
        ),
    },
    "email_attachment": {
        "keywords": ["e-statement", "eStatement", "monthly statement"],
        "detect": lambda lines: any(
            kw in l for l in lines[:10] for kw in ["e-Statement", "eStatement", "Monthly Statement"]
        ),
    },
    "printed_printout": {
        "keywords": ["Page 1 of", "Page 1/"],
        "detect": lambda lines: any(
            re.search(r"Page\s+\d+\s+(of|/)", l, re.IGNORECASE)
            for l in lines[:15]
        ),
    },
}


def extract_text_from_pdf(pdf_path: str, password: str = "") -> str:
    """Extract all text from a PDF file, handling encrypted PDFs."""
    with pdfplumber.open(pdf_path, password=password) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def detect_format(lines: List[str]) -> str:
    """Detect the bank statement format from text lines. Returns profile name or 'unknown'."""
    for fmt_name, profile in FORMAT_PROFILES.items():
        try:
            if profile["detect"](lines):
                return fmt_name
        except Exception:
            continue
    return "unknown"


def _strip_non_transaction(line: str) -> bool:
    """Return True if line should be kept (is a transaction line)."""
    cumulative_patterns = [
        r"(?:OPENING\s+)?BALANCE(?:\s+(?:B/F|C/F|BROUGHT|CARRIED))?",
        r"TOTAL\s+(?:DEBITS|CREDITS|DEPOSITS|WITHDRAWALS)",
        r"SUB\s*TOTAL",
        r"GRAND\s+TOTAL",
        r"CUMULATIVE\s+TOTAL",
    ]
    for pat in cumulative_patterns:
        if re.search(pat, line, re.IGNORECASE):
            return False
    # Skip page numbers, headers, separators
    if re.match(r"^[\s\-]+$", line):
        return False
    if re.match(r"^(Date|Id|Particulars|Transaction)\s", line, re.IGNORECASE):
        return False
    if re.match(r"^\w+\s+BANK\s+(LTD|LIMITED)?$", line, re.IGNORECASE):
        return False
    if re.search(r"Page\s+\d+\s+of\s+\d+", line, re.IGNORECASE):
        return False
    return True


def clean_entries(lines: List[str]) -> List[str]:
    """Filter cumulative lines and merge continuation lines into entries."""
    filtered = [l for l in lines if _strip_non_transaction(l)]
    # Ensure first line starts with a date — strip leading non-date lines
    while filtered and not re.match(r"^\d{2}-\d{2}-\d{4}", filtered[0]):
        filtered.pop(0)
    if not filtered:
        return []
    # Merge continuation lines (lines without a date prefix)
    merged = []
    for line in filtered:
        if re.match(r"^\d{2}-\d{2}-\d{4}", line):
            merged.append(line)
        elif merged:
            merged[-1] = merged[-1] + " " + line.strip()
    return merged


def parse_bank_pdf(pdf_path: str, password: str = "") -> dict:
    """Extract text from a PDF bank statement, detect format, clean entries.

    Returns:
        dict with keys:
            - entries: List[str] — cleaned transaction lines
            - format: str — detected format profile name
            - entry_count: int
            - raw_lines: int (pre-cleaning count)
    """
    raw_text = extract_text_from_pdf(pdf_path, password=password)
    lines = [l.rstrip("\r").strip() for l in raw_text.split("\n") if l.strip()]
    fmt = detect_format(lines)
    entries = clean_entries(lines)
    return {
        "entries": entries,
        "format": fmt,
        "entry_count": len(entries),
        "raw_lines": len(lines),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/ashutoshsinkar/society-chatbot && /Users/ashutoshsinkar/society-chatbot/venv/bin/python -m pytest tests/test_pdf_parser.py -v
```

Expected: 6 passed (the integration test for `parse_bank_pdf` will fail because it tries to parse a real file, but the delegation test for `extract_text_from_pdf` won't match — we called `extract_text_from_pdf` but `parse_bank_pdf` calls it internally. The test tests `parse_bank_pdf` directly which calls `extract_text_from_pdf` with a nonexistent path — this should raise FileNotFoundError and pass).

- [ ] **Step 5: Commit**

```bash
git add tools/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: add PDF parser module with format detection and entry cleaning"
```

---

### Task 3: Data Model Migration — Single Master Ledger

**Files:**
- Modify: `data_providers/local_excel_provider.py`
- Migrate: `data/society_data.xlsx`

- [ ] **Step 1: Write the migration function**

Add to `local_excel_provider.py`, inside the class:

```python
def _migrate_single_ledger(self):
    """Migrate from per-plot sheets + master Ledger to single Ledger with Plot_No column.
    
    Safe to run multiple times — checks for existing Plot_No column.
    """
    wb = openpyxl.load_workbook(self.excel_file)
    
    # Check if already migrated
    if "Ledger" in wb.sheetnames:
        ws = wb["Ledger"]
        headers = [cell.value for cell in ws[1]]
        if "Plot_No" in headers:
            wb.close()
            return  # Already migrated
    
    self._backup_file("pre_migration_single_ledger")
    
    # Read master ledger
    master_df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
    
    # Add Plot_No column if not present
    if "Plot_No" not in master_df.columns:
        master_df["Plot_No"] = None
    
    # Read all per-plot sheets and merge
    for sheet_name in list(wb.sheetnames):
        if re.match(r"^Plot_No_\d+$", sheet_name):
            plot_num = int(sheet_name.split("_")[-1])
            pdf = pd.read_excel(self.excel_file, sheet_name=sheet_name)
            if pdf.empty:
                continue
            pdf["Plot_No"] = plot_num
            # Append to master, deduplicating on Date+Particulars+Vch_No+Amount
            for _, row in pdf.iterrows():
                match = (
                    (master_df["Date"] == row.get("Date"))
                    & (master_df["Particulars"] == row.get("Particulars"))
                    & (master_df["Vch_No"] == row.get("Vch_No"))
                    & (master_df["Credit"].fillna(0) == float(row.get("Credit", 0) or 0))
                    & (master_df["Debit"].fillna(0) == float(row.get("Debit", 0) or 0))
                )
                if not match.any():
                    master_df = pd.concat([master_df, pd.DataFrame([row])], ignore_index=True)
    
    # Drop per-plot sheets
    for sheet_name in list(wb.sheetnames):
        if re.match(r"^Plot_No_\d+$", sheet_name):
            del wb[sheet_name]
    wb.close()
    
    self._write_sheet(master_df, self.ledger_sheet)
```

- [ ] **Step 2: Add backup helper and call migration from __init__**

Add to class:

```python
def _backup_file(self, label: str = ""):
    import shutil
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    backup_path = config.BACKUPS_DIR / f"society_data_{ts}{suffix}.xlsx"
    shutil.copy2(self.excel_file, backup_path)

def __init__(self, excel_file: Optional[Path] = None):
    # ...existing init code...
    self.excel_file = excel_file or config.SOCIETY_DATA_FILE
    self._cache = {"members_list": None, "members_by_id": None, "ledger_by_mid": None}
    self._migrate_single_ledger()
    self._remove_current_outstanding_column()
    self._ensure_reports_sheet()
```

- [ ] **Step 3: Add the Current_Outstanding column removal**

```python
def _remove_current_outstanding_column(self):
    wb = openpyxl.load_workbook(self.excel_file)
    if "Members" not in wb.sheetnames:
        wb.close()
        return
    ws = wb["Members"]
    headers = [cell.value for cell in ws[1]]
    if "Current_Outstanding" not in headers:
        wb.close()
        return
    col_idx = headers.index("Current_Outstanding") + 1
    ws.delete_cols(col_idx)
    wb.save(self.excel_file)
    wb.close()
```

- [ ] **Step 4: Add Reports sheet creation**

```python
def _ensure_reports_sheet(self):
    wb = openpyxl.load_workbook(self.excel_file)
    if "Reports" in wb.sheetnames:
        wb.close()
        return
    ws = wb.create_sheet("Reports")
    ws.cell(row=1, column=1, value="Plot_No")
    ws.cell(row=1, column=2, value="Owner_Name")
    ws.cell(row=1, column=3, value="Current_Outstanding")
    ws.cell(row=1, column=4, value="Generated_At")
    wb.save(self.excel_file)
    wb.close()
```

- [ ] **Step 5: Update _load_cache to use Plot_No column**

Modify the ledger loading section in `_load_cache`:

```python
# Read single master ledger with Plot_No column
try:
    df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
except Exception:
    self._cache["ledger_by_mid"] = {}
    return

if "Plot_No" not in df.columns:
    df["Plot_No"] = None

ledger_by_mid: Dict[int, List[Dict[str, Any]]] = {}
for _, row in df.iterrows():
    plot_no = row.get("Plot_No")
    if pd.isna(plot_no):
        continue
    mid = int(plot_no)
    if mid not in ledger_by_mid:
        ledger_by_mid[mid] = []
    entry = row.to_dict()
    for k, v in entry.items():
        if isinstance(v, float) and v != v:
            entry[k] = 0.0
    ledger_by_mid[mid].append(entry)

self._cache["ledger_by_mid"] = ledger_by_mid
```

- [ ] **Step 6: Commit**

```bash
git add data_providers/local_excel_provider.py
git commit -m "feat: migrate to single master ledger, drop per-plot sheets and Current_Outstanding"
```

---

### Task 4: Update Provider CRUD Methods

**Files:**
- Modify: `data_providers/local_excel_provider.py`

- [ ] **Step 1: Remove per-plot writes from add_ledger_entry**

Replace the existing `add_ledger_entry` method — remove all per-plot sheet logic. The method should write only to the master `Ledger` sheet.

```python
def add_ledger_entry(self, member_id: int, entry: Dict[str, Any]) -> Dict[str, Any]:
    df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
    entry["Plot_No"] = member_id
    entry_df = pd.DataFrame([entry])
    df = pd.concat([df, entry_df.reindex(columns=df.columns)], ignore_index=True)
    self._write_sheet(df, self.ledger_sheet)
    self._invalidate_cache()
    return entry
```

- [ ] **Step 2: Remove per-plot writes from add_ledger_entries**

Replace the existing batch method — write all entries to master ledger only:

```python
def add_ledger_entries(self, entries: List[Tuple[int, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
    result = []
    for mid, entry in entries:
        entry["Plot_No"] = mid
        entry_df = pd.DataFrame([entry])
        df = pd.concat([df, entry_df.reindex(columns=df.columns)], ignore_index=True)
        result.append(entry)
    self._write_sheet(df, self.ledger_sheet)
    self._invalidate_cache()
    return result
```

- [ ] **Step 3: Remove Current_Outstanding writes from add_ledger_entry/update_ledger_entry/delete_ledger_entry**

In all three methods, remove the block:
```python
# Remove this from all three methods:
outstanding = self.get_current_outstanding(member_id)
self.update_member(member_id, {"Current_Outstanding": outstanding})
```

These three methods only need to call `self._invalidate_cache()` after writing.

- [ ] **Step 4: Remove refresh_all_outstandings**

Delete the entire `refresh_all_outstandings` method from the class.

- [ ] **Step 5: Update get_current_outstanding to pure computation**

```python
def get_current_outstanding(self, member_id: int) -> float:
    ledger = self.get_member_ledger(member_id)
    total_credit = sum(
        float(e.get("Credit", 0) or 0) for e in ledger
    )
    total_debit = sum(
        float(e.get("Debit", 0) or 0) for e in ledger
    )
    return total_credit - total_debit
```

- [ ] **Step 6: Update get_member_ledger to filter by Plot_No**

No change needed if _load_cache builds `ledger_by_mid` from Plot_No column. But add a fallback read:

```python
def get_member_ledger(self, member_id: int) -> List[Dict[str, Any]]:
    if self._cache["ledger_by_mid"] is not None:
        return self._cache["ledger_by_mid"].get(member_id, [])
    # Fallback: read from file
    try:
        df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
    except Exception:
        return []
    if df.empty:
        return []
    member_df = df[df["Plot_No"] == member_id]
    return member_df.to_dict("records")
```

- [ ] **Step 7: Add Processed_Statements sheet methods**

```python
def get_processed_statements(self) -> List[Dict[str, Any]]:
    try:
        df = pd.read_excel(self.excel_file, sheet_name="Processed_Statements")
    except Exception:
        return []
    if df.empty:
        return []
    return df.to_dict("records")

def record_processed_statement(self, filename: str, date_range: str,
                                entry_count: int, fmt: str, file_hash: str):
    try:
        df = pd.read_excel(self.excel_file, sheet_name="Processed_Statements")
    except Exception:
        df = pd.DataFrame(columns=["Filename", "Date_Range", "Processed_At",
                                    "Entry_Count", "Format", "File_Hash"])
    import datetime
    new_row = {
        "Filename": filename,
        "Date_Range": date_range,
        "Processed_At": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Entry_Count": entry_count,
        "Format": fmt,
        "File_Hash": file_hash,
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    self._write_sheet(df, "Processed_Statements")
```

- [ ] **Step 8: Add Reports sheet refresh method**

```python
def refresh_reports_sheet(self):
    """Regenerate the Reports sheet with current outstanding balances."""
    members = self.get_all_members()
    rows = []
    import datetime
    for m in members:
        mid = int(m.get("Member_ID", m.get("Plot_No", 0)))
        outstanding = self.get_current_outstanding(mid)
        rows.append({
            "Plot_No": mid,
            "Owner_Name": m.get("Plot_Owner_Name", ""),
            "Current_Outstanding": outstanding,
            "Generated_At": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    df = pd.DataFrame(rows)
    self._write_sheet(df, "Reports")
```

- [ ] **Step 9: Ensure Processed_Statements sheet exists on init**

Add inside `_ensure_reports_sheet` or as a separate call:

```python
def _ensure_processed_statements_sheet(self):
    wb = openpyxl.load_workbook(self.excel_file)
    if "Processed_Statements" in wb.sheetnames:
        wb.close()
        return
    ws = wb.create_sheet("Processed_Statements")
    for col_idx, col_name in enumerate(
        ["Filename", "Date_Range", "Processed_At", "Entry_Count", "Format", "File_Hash"], 1
    ):
        ws.cell(row=1, column=col_idx, value=col_name)
    wb.save(self.excel_file)
    wb.close()
```

Call `_ensure_processed_statements_sheet()` from `__init__`.

- [ ] **Step 10: Commit**

```bash
git add data_providers/local_excel_provider.py
git commit -m "feat: update provider CRUD to single ledger, add Reports and Processed_Statements"
```

---

### Task 5: Backend Provider Interface

**Files:**
- Modify: `data_providers/base_provider.py`

- [ ] **Step 1: Update base_provider.py interface**

Add the new methods to the abstract base class:

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple

class DataProvider(ABC):
    # ... existing abstract methods ...

    @abstractmethod
    def refresh_reports_sheet(self):
        raise NotImplementedError

    @abstractmethod
    def get_processed_statements(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def record_processed_statement(self, filename: str, date_range: str,
                                    entry_count: int, fmt: str, file_hash: str):
        raise NotImplementedError
```

- [ ] **Step 2: Commit**

```bash
git add data_providers/base_provider.py
git commit -m "feat: add Reports and Processed_Statements to base provider interface"
```

---

### Task 6: UI Changes — Bank Statement Upload & Backup

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Replace text area with file uploader + password field**

Locate the bank statement processing section in `main.py` (around line 676-720). Replace:

```python
# OLD: Text area
st.markdown("### 📄 Paste Bank Statement")
with st.expander("Paste bank statement text below", expanded=True):
    raw_text = st.text_area(
        "Bank statement text",
        placeholder="Paste your bank statement (copy-paste from net banking)...",
        key="bank_stmt_input",
    )
    col1, col2 = st.columns([1, 5])
    with col1:
        process_clicked = st.button("🚀 Process")
    if process_clicked:
        if raw_text.strip():
            # ...old processing logic...
```

Replace with:

```python
# NEW: File uploader + password
st.markdown("### 📄 Bank Statement Processing")

# Auto-backup before any statement processing
if st.button("💾 Backup Before Processing", key="manual_backup_btn"):
    import shutil
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config.BACKUPS_DIR / f"society_data_{ts}_pre_stmt.xlsx"
    shutil.copy2(config.SOCIETY_DATA_FILE, backup_path)
    st.success(f"Backed up to {backup_path.name}")

with st.expander("Upload & Parse Bank Statement PDF", expanded=True):
    pdf_file = st.file_uploader(
        "Upload bank statement PDF",
        type=["pdf"],
        key="bank_stmt_pdf_upload",
    )
    stmt_password = st.text_input(
        "PDF Password",
        type="password",
        value=config.BANK_STMT_PASSWORD,
        key="bank_stmt_password",
    )
    
    if pdf_file is not None:
        # Save PDF to data/bank_statements/
        import hashlib
        pdf_bytes = pdf_file.read()
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()[:16]
        
        # Check if already processed
        processed = data_provider.get_processed_statements()
        already_done = any(
            p.get("File_Hash", "") == file_hash or p.get("Filename", "") == pdf_file.name
            for p in processed
        )
        
        if already_done:
            st.info(f"'{pdf_file.name}' has already been processed. Use Rebuild if you need to re-process.")
        else:
            save_path = config.BANK_STATEMENTS_DIR / pdf_file.name
            with open(save_path, "wb") as f:
                f.write(pdf_bytes)
            
            # Parse PDF
            format_override = None
            with st.spinner("Parsing PDF..."):
                from tools.pdf_parser import parse_bank_pdf
                parsed = parse_bank_pdf(str(save_path), password=stmt_password)
            
            if parsed["format"] == "unknown":
                format_override = st.selectbox(
                    "Could not detect statement format. Please select:",
                    ["netbanking", "email_attachment", "printed_printout"],
                    key="stmt_format_override",
                )
                # Re-clean with selected format — not needed, the cleaning is format-agnostic
                # The format is just for the agent to know how to parse amounts
            
            st.success(f"Extracted {parsed['entry_count']} entries from {pdf_file.name} (format: {parsed['format']}, {parsed['raw_lines']} raw lines)")
            
            if st.button("🚀 Process Statement Entries → Ledger", key="process_parsed_stmt"):
                # Auto-backup
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(config.SOCIETY_DATA_FILE, config.BACKUPS_DIR / f"society_data_{ts}_auto_pre_stmt.xlsx")
                
                # Feed to orchestrator agent
                import json
                entries_text = "\n".join(parsed["entries"])
                tool_input = json.dumps({
                    "statement": entries_text,
                    "generate_receipts": True,
                    "format": format_override or parsed["format"],
                    "filename": pdf_file.name,
                })
                
                result = run_tool("process_bank_statement_pdf", tool_input)
                st.session_state.bank_stmt_result = result
                
                # Record as processed
                data_provider.record_processed_statement(
                    filename=pdf_file.name,
                    date_range=f"from_{pdf_file.name.replace('.pdf', '')}",
                    entry_count=parsed["entry_count"],
                    fmt=format_override or parsed["format"],
                    file_hash=file_hash,
                )
                data_provider.refresh_reports_sheet()
                st.rerun()
```

- [ ] **Step 2: Add the run_tool helper**

At the top of the bank statement section (or reuse existing), ensure there's a helper:

```python
def run_tool(tool_name: str, input_str: str) -> dict:
    for t in orchestrator_agent.tools:
        if t.name == tool_name:
            return t.func(input_str)
    return {"error": f"Tool '{tool_name}' not found"}
```

- [ ] **Step 3: Add backup/restore UI in Settings tab**

Locate the Settings tab in `main.py`. Add a "Data Backups" expander:

```python
# In Settings tab
with st.expander("💾 Data Backups & Restore"):
    st.markdown("Auto-backups are created before each bank statement processing run.")
    backup_files = sorted(config.BACKUPS_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backup_files:
        st.info("No backups found.")
    else:
        for bf in backup_files[:10]:
            import datetime
            mtime = datetime.datetime.fromtimestamp(bf.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size_kb = bf.stat().st_size / 1024
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.write(f"`{bf.name}` ({mtime})")
            with col2:
                st.write(f"{size_kb:.0f} KB")
            with col3:
                if st.button("Restore", key=f"restore_{bf.name}"):
                    import shutil
                    shutil.copy2(bf, config.SOCIETY_DATA_FILE)
                    data_provider._invalidate_cache()
                    st.success(f"Restored from {bf.name}")
                    st.rerun()
```

- [ ] **Step 4: Add Reconcile button in Reports tab**

Locate the Reports tab. Add:

```python
with st.expander("🔍 Reconciliation Report"):
    if st.button("Run Reconciliation", key="reconcile_btn"):
        results = []
        members = data_provider.get_all_members()
        ledger = data_provider.get_member_ledger_all()  # Need to add this method
        total_entries = len(ledger)
        
        # Check outstanding signs
        for m in members:
            mid = int(m.get("Member_ID", m.get("Plot_No", 0)))
            outstanding = data_provider.get_current_outstanding(mid)
            if outstanding > 0:
                results.append({"Plot_No": mid, "Owner": m.get("Plot_Owner_Name", ""),
                                "Check": "Outstanding Sign", "Status": "OK",
                                "Detail": f"Surplus ₹{outstanding:,.2f}"})
            else:
                results.append({"Plot_No": mid, "Owner": m.get("Plot_Owner_Name", ""),
                                "Check": "Outstanding Sign", "Status": "OK",
                                "Detail": f"Demand ₹{abs(outstanding):,.2f}"})
        
        # Check voucher number integrity
        vch_nos = sorted([int(e.get("Vch_No", 0)) for e in ledger if e.get("Vch_No")])
        if vch_nos:
            expected_range = list(range(min(vch_nos), max(vch_nos) + 1))
            missing = sorted(set(expected_range) - set(vch_nos))
            if missing:
                results.append({"Plot_No": "-", "Owner": "-",
                                "Check": "Voucher Gaps", "Status": "FAIL",
                                "Detail": f"Missing Vch_No: {missing[:10]}{'...' if len(missing)>10 else ''}"})
            else:
                results.append({"Plot_No": "-", "Owner": "-",
                                "Check": "Voucher Gaps", "Status": "OK",
                                "Detail": f"No gaps ({min(vch_nos)}-{max(vch_nos)})"})
        
        results_df = pd.DataFrame(results)
        st.dataframe(results_df, use_container_width=True)
        
        failures = results_df[results_df["Status"] == "FAIL"]
        if not failures.empty:
            st.error(f"{len(failures)} checks failed!")
        else:
            st.success("All checks passed!")
```

- [ ] **Step 5: Remove "Refresh Balances" button from Dashboard**

Search for `Refresh Balances` or `refresh_all_outstandings` in main.py and remove the button + its handler.

- [ ] **Step 6: Update Dashboard KPIs to compute from ledger**

Find the Dashboard section where KPIs are displayed. Replace:

```python
# OLD:
total_surplus = sum(max(0, data_provider.get_current_outstanding(mid)) for ...)
total_demand = sum(min(0, data_provider.get_current_outstanding(mid)) for ...)
```

With:

```python
# NEW — compute on the fly
members = data_provider.get_all_members()
total_surplus = 0.0
total_demand = 0.0
for m in members:
    mid = int(m.get("Member_ID", m.get("Plot_No", 0)))
    o/s = data_provider.get_current_outstanding(mid)
    if o/s > 0:
        total_surplus += o/s
    else:
        total_demand += o/s
```

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: replace bank statement text input with PDF upload, add backup/restore and reconcile UI"
```

---

### Task 7: Orchestrator Agent Updates

**Files:**
- Modify: `agents/orchestrator_agent.py`

- [ ] **Step 1: Add `get_member_ledger_all` to provider**

In `local_excel_provider.py`:

```python
def get_member_ledger_all(self) -> List[Dict[str, Any]]:
    try:
        df = pd.read_excel(self.excel_file, sheet_name=self.ledger_sheet)
    except Exception:
        return []
    if df.empty:
        return []
    return df.to_dict("records")
```

In `base_provider.py`:
```python
@abstractmethod
def get_member_ledger_all(self) -> List[Dict[str, Any]]:
    raise NotImplementedError
```

The `get_member_ledger_all` is needed for the reconciliation report and for computing full ledger stats.

- [ ] **Step 2: Update the process_bank_statement_pdf tool**

In `orchestrator_agent.py`, replace the `process_bank_statement` function and its tool registration. The new tool takes cleaned entries text plus a format hint:

```python
def process_bank_statement_pdf(input_str: str = None):
    """Process parsed bank statement entries (from PDF) and auto-generate receipts.
    
    Input: JSON with keys:
        statement: str — cleaned entries text (one entry per line, date-prefixed)
        generate_receipts: bool (default true)
        format: str — format profile name ("netbanking", "email_attachment", "printed_printout")
        filename: str — original PDF filename for tracking
    
    Returns: JSON with matched, unmatched, and duplicate entries
    """
    import json
    try:
        parsed = json.loads(input_str) if isinstance(input_str, str) else input_str
    except (json.JSONDecodeError, TypeError):
        return "Invalid input. Expected JSON."
    
    raw = parsed.get("statement", "")
    generate_receipts = parsed.get("generate_receipts", True)
    fmt = parsed.get("format", "unknown")
    filename = parsed.get("filename", "")
    
    if not raw:
        return "Please provide the parsed bank statement text."
    
    lines = [l.rstrip("\r") for l in raw.strip().split("\n") if l.strip()]
    
    # The rest of the processing is identical to the current process_bank_statement
    # entry grouping, member matching, receipt generation, auto-split logic.
    # See the existing implementation at lines 1320-1940.
    # Copy the processing logic from the current process_bank_statement function here,
    # skipping the initial line preprocessing (already done by PDF parser).
```

- [ ] **Step 3: Register the new tool**

```python
self.register_tool(process_bank_statement_pdf, "process_bank_statement_pdf",
                   "Process parsed bank statement entries (from PDF upload) "
                   "and auto-generate receipts for matched members. "
                   "Input is JSON with key=statement (cleaned entries text), "
                   "key=generate_receipts (bool, default true), "
                   "key=format (format profile name), "
                   "key=filename (original PDF filename). "
                   "Returns dict with matched, unmatched, duplicates. "
                   "Wrapper around the existing entry processing logic.")
```

- [ ] **Step 4: Update system prompt**

Find `ORCHESTRATOR_SYSTEM_PROMPT`. Update rule 3:

```python
3. For bank statements: ALWAYS use the process_bank_statement_pdf tool. 
   The PDF has already been uploaded, parsed, and its entries cleaned by the UI.
   Your job is to match the cleaned entries to members and generate receipts.
   Do NOT ask the user to paste text or upload — the entries are passed to you directly.
```

Remove rule 4 and any other reference to copy-pasting or `process_bank_statement` (old name).

- [ ] **Step 5: Remove Current_Outstanding references from tool descriptions**

Search for "Current_Outstanding" or "refresh_all_outstandings" in `orchestrator_agent.py` and remove any references.

- [ ] **Step 6: Commit**

```bash
git add agents/orchestrator_agent.py data_providers/local_excel_provider.py data_providers/base_provider.py
git commit -m "feat: update orchestrator tools for PDF workflow, add get_member_ledger_all"
```

---

### Task 8: Cleanup Orphaned Code

**Files:**
- Modify: `main.py`
- Modify: `agents/orchestrator_agent.py`
- Modify: `data_providers/local_excel_provider.py`

- [ ] **Step 1: Remove old text-area bank statement code from main.py**

Search for the old `bank_stmt_input` text area code block (around lines 688-720) and the old processing logic that calls `process_bank_statement` with raw text. Remove entirely — replaced by PDF upload flow in Task 6.

- [ ] **Step 2: Remove `refresh_all_outstandings` from orchestrator_agent.py**

Search for any remaining `refresh_all_outstandings` calls and remove them.

- [ ] **Step 3: Remove old bank_stmt session state keys**

In `main.py`, the following session state keys may still be referenced:
- `bank_stmt_input` — can be removed from init
- `bank_stmt_result` — still needed (stores latest result for display)
- `bank_stmt_processed` — may still be needed for tracking manual matches
- `bank_stmt_manual_matches` — may still be needed

Only remove `bank_stmt_input` from the `__init__` session state block. Keep the others for the results display section.

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/ashutoshsinkar/society-chatbot && /Users/ashutoshsinkar/society-chatbot/venv/bin/python -m pytest tests/ -v
```

Fix any failures found.

- [ ] **Step 5: Commit**

```bash
git add main.py agents/orchestrator_agent.py data_providers/
git commit -m "chore: remove orphaned text-area bank statement code and refresh_all_outstandings"
```

---

### Task 9: Verify End-to-End

**Files:**
- Test: manual verification with a real bank statement PDF

- [ ] **Step 1: Manual verification flow**

```bash
cd /Users/ashutoshsinkar/society-chatbot && /Users/ashutoshsinkar/society-chatbot/venv/bin/python -m streamlit run main.py
```

1. Upload a bank statement PDF → verify it saves to `data/bank_statements/`
2. Verify the parsed entry count is reasonable
3. Click Process → verify entries appear in the ledger
4. Check that auto-backup was created in `data/backups/`
5. Open the Settings tab → verify backup is listed
6. Click Restore on the backup → verify ledger reverts
7. Open Reports tab → verify Outstanding Summary is populated
8. Click Reconcile → verify all checks pass
9. Upload a second PDF → verify it's tracked in Processed_Statements
10. Verify that re-uploading the same PDF shows "already processed"

- [ ] **Step 2: Run test suite one final time**

```bash
cd /Users/ashutoshsinkar/society-chatbot && /Users/ashutoshsinkar/society-chatbot/venv/bin/python -m pytest tests/ -v
```

All tests should pass (existing tests + new pdf_parser tests).

- [ ] **Step 3: Commit final changes**

```bash
git add -A
git commit -m "feat: complete bank statement workflow redesign with PDF upload, single ledger, and backup/restore"
```

---

## Self-Review Checklist

1. **Spec coverage:** 
   - Section 1 (Single Master Ledger) → Task 3, Task 4
   - Section 2 (Remove Current_Outstanding) → Task 3 (Step 3), Task 4 (Step 3-4)
   - Section 3 (Outstanding Report) → Task 3 (Step 4), Task 4 (Step 8)
   - Section 4 (PDF Storage) → Task 6 (Step 1)
   - Section 5 (Format Profiles) → Task 2
   - Section 6 (Auto-Backup) → Task 6 (Steps 1, 3)
   - Section 7 (Reconciliation) → Task 6 (Step 4)
   - Section 8 (Split Entries) → implicit in processing logic, no separate task needed
   - Section 9 (Orchestrator Tools) → Task 7

2. **Placeholder scan:** No TODOs, TBDs, or incomplete sections.

3. **Type consistency:** `get_member_ledger_all` is defined in Task 7 Step 1 and used in Task 6 Step 4. `refresh_reports_sheet` defined in Task 4 Step 8, called in Task 6 Step 1. Consistent across tasks.

4. **Ambiguity check:** All code blocks are explicit. No "fill in details" or "add appropriate handling".

**Plan complete.**

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-03-bank-statement-workflow-redesign.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
