# Bank Statement Workflow Redesign

## Problem

The current bank statement workflow has three major pain points:

1. **Manual copy-paste:** Password-protected PDF bank statements must be opened manually, password entered, and transaction lines copy-pasted into a text area. Headers, footers, and junk text break the parser, requiring manual cleanup. Doing this 50+ times is painful.

2. **No undo:** If a duplicate entry slips through or the wrong member gets tagged, calculations become incorrect across multiple members (especially with split rules). There is no way to roll back — the user must delete everything and start from scratch, including re-opening bank statements.

3. **Data model duplication causes discrepancies:** Every ledger entry is written to both a master `Ledger` sheet AND per-plot sheets (`Plot_No_01` through `Plot_No_44`). These copies drift apart over time (outstanding sign mismatches, record count differences). The `Current_Outstanding` column in the `Members` sheet is an additional stale cache that must be refreshed after every mutation.

## Solution

### 1. Single Master Ledger Data Model

Drop all per-plot ledger sheets. Add a `Plot_No` column to the master `Ledger` sheet. Individual member ledgers become filtered views on the single source of truth.

**Changes:**

- New column: `Plot_No` (integer) in the `Ledger` sheet, populated from the per-plot sheet name during migration
- Drop sheets: `Plot_No_01` through `Plot_No_44`
- `get_member_ledger(member_id)`: Filter master `Ledger` by `Plot_No == member_id`
- `add_ledger_entry` / `add_ledger_entries`: Write only to master `Ledger`
- `update_ledger_entry` / `delete_ledger_entry`: Operate only on master `Ledger`
- All `add_ledger_entry` callers lose the per-plot write path (~10 sites)
- Cache (`_cache["ledger_by_mid"]`): Build from single master `Ledger` on load, keyed by `Plot_No`

### 2. Remove Current_Outstanding from Members Sheet

`Current_Outstanding` is a cached value that goes stale. Computing it from the ledger is cheap (44 dict lookups + sums).

**Changes:**

- Drop the `Current_Outstanding` column from the `Members` sheet
- Remove `refresh_all_outstandings()` from provider
- `get_current_outstanding(member_id)`: Pure computation from `get_member_ledger(member_id)` — no stored fallback
- Remove all `update_member({"Current_Outstanding": ...})` calls from `add_ledger_entry`, `update_ledger_entry`, `delete_ledger_entry` (~15 sites across main.py and orchestrator_agent.py)
- Remove the "Refresh Balances" button from Dashboard
- Dashboard KPIs (total surplus, total demand): Compute on the fly from full ledger

### 3. Outstanding Summary Report in Excel

A persistent `Reports` sheet in `society_data.xlsx` for offline reference.

**Columns:** `Plot_No`, `Owner_Name`, `Current_Outstanding`, `Generated_At`

**Behavior:**
- Regenerated on app launch (reads ledger → overwrites sheet)
- "Refresh Report" button in Reports tab (same computation, manual trigger)
- Feeds Dashboard KPIs and Defaulter Report
- The Excel file alone is sufficient to see outstanding balances without launching Streamlit

### 4. Bank Statement PDF Storage

Store uploaded PDFs in `data/bank_statements/` for persistence and rebuild capability.

**Directory structure:**

```
data/bank_statements/
  2024-04_2024-06.pdf
  2024-07_2024-09.pdf
  ...
```

**Processed_Statements sheet** in the Excel tracks:

| Column      | Description                        |
|-------------|------------------------------------|
| Filename    | PDF file name                      |
| Date_Range  | Date range of statements           |
| Processed_At| Timestamp when first processed     |
| Entry_Count | Number of entries extracted        |
| Format      | Parser profile used ("netbanking", "email_attachment", "printed") |
| File_Hash   | SHA256 of PDF for change detection |

**Workflow:**
1. **First time:** Upload PDF via Streamlit file uploader → saved to `data/bank_statements/` → parsed → recorded in `Processed_Statements`
2. **New statement:** Same upload flow
3. **Re-parse:** "🔄 Rebuild from All Statements" button — clears only bank-statement-originated entries (those without `"MANUAL"` in `Transaction_Type` and without `"MANUAL-"` prefix in `Transaction_ID`) and re-imports all PDFs. Manually entered entries and invoice entries are preserved
4. **Parse unprocessed only:** "📄 Parse Unprocessed" button — processes only PDFs not in `Processed_Statements`
5. **Password:** Configurable in `config.py` (default) + overridable text field on UI

### 5. PDF Parsing with Format Profiles

Use `pdfplumber` to extract text from encrypted PDFs.

**Parser profiles** (autodetected):
- **netbanking:** Downloaded from net banking website. Lines start with date followed by transaction details.
- **email_attachment:** From monthly email statements. May include running balances, "TOTAL DEBITS/CREDITS" lines, column headers per page.
- **printed_printout:** Scanned/printed format from bank. May have extra spacing, page numbers, "Page 1 of N" markers.

**Detection:** First 20 lines of PDF text are scanned for format-specific keywords or layout patterns. The detected format is stored in `Processed_Statements` so re-parsing uses the same profile.

**Fallback:** If autodetection fails (no clear match), the UI shows a dropdown to manually select the format. The user's choice is saved for that PDF so subsequent re-parses reuse it.

**Post-processing (all profiles):**
- Strip headers, footers, page numbers, "Page X of Y"
- Remove balance summary lines (TOTAL DEBITS/CREDITS, BALANCE B/F/C/F, CUMULATIVE TOTAL, SUB TOTAL, GRAND TOTAL)
- Remove opening/closing balance lines
- Merge continuation lines (lines without a date prefix)

### 6. Auto-Backup & One-Click Restore

**Auto-backup:** Before every bank statement processing run, copy `data/society_data.xlsx` to `data/backups/bank_stmt_<timestamp>.xlsx`.

**Backup management:**
- Show last 10 backups in Settings tab with timestamps
- One-click "Restore" button next to each backup
- Restoration: swap current file with backup, invalidate all caches, rerun

**Storage:** ~200KB per backup; 10 backups ≈ 2MB. Trivial.

### 7. Reconciliation Report

A "Reconcile" button in the Reports tab that validates:

- **Outstanding signs:** Surplus (+) and demand (-) match computed values for every member
- **Voucher number integrity:** No gaps or duplicate voucher numbers in the ledger
- **Entry count:** Total entries in master ledger matches expected count (from member count and voucher ranges)
- **Credit/debit balance:** Sum of credits - sum of debits across all entries equals net surplus/demand
- **Cross-plot totals conflict:** Outstanding report total matches sum of individual member outstandings

Results displayed as a pass/fail table with details on any discrepancies.

### 8. Split Entries

Split entries are synthetic entries created when a payment for member A is automatically divided across members B and C (per split rules). They have `Transaction_ID = "SPLIT-{receipt_id}"` and particulars like `"By Split from Owner (NEFT X12345)"`.

**With single master ledger:**
- Split entries are stored identically to real entries — same `Ledger` sheet, same columns, just with `Plot_No` set to the split target member
- The existing "Split from" exclusion in duplicate checks (Added June 3: case-insensitive + skip `SPLIT FROM` in particulars) prevents them from matching real bank transactions during reprocessing
- `Transaction_Type = "SPLIT"` identifies them as synthetic

**During auto-split (bank statement processing):**
- Each split entry gets its own `Vch_No`, `Transaction_ID = "SPLIT-{source_receipt_id}"`, and `Plot_No` pointing to the split target
- The source member's full payment entry is stored with the real bank transaction details
- This continues to work unchanged — only the storage target changes (master sheet only, no per-plot)

**During "Rebuild from All Statements":**
- Re-parsing all PDFs recreates the original entries, and auto-split rules fire again (because split rules still exist in the `Split_Rules` sheet)
- Split entries are correctly recreated — no manual intervention needed
- Entries that were manually split (via the Ledgers tab Split UI) are NOT tied to any bank statement and must be excluded from rebuild. The rebuild operation clears only entries whose `Transaction_Type` is NOT `"MANUAL"` and whose `Transaction_ID` does not start with `"MANUAL-"`. Manually created entries are preserved.

**During reconciliation:**
- The reconciliation report should show split entry counts separately (e.g., "X bank entries + Y split entries = Z total")
- Outstanding calculations naturally include split entries as credits for the target members, which is correct

### 9. Orchestrator Agent Tools Impact

The following tools registered with the LLM (`agents/orchestrator_agent.py`) are affected:

| Tool | Impact |
|------|--------|
| `get_member_details` | No change — reads from `Members` sheet, filtered views don't affect it |
| `get_member_ledger` | No change — already returns a filtered list. Will now filter by `Plot_No` column instead of reading a per-plot sheet. Output format unchanged |
| `get_outstanding_summary` | Simplified — reads from `Reports` sheet (which is auto-generated on app launch) instead of computing from `get_current_outstanding`. Faster, no per-member loop |
| `process_bank_statement` | Removed (text-paste path). Replaced by `process_bank_statement_pdf` which accepts a filename from `data/bank_statements/` instead of raw text. The PDF is already uploaded and parsed by the UI; this tool handles the member matching + receipt generation logic that used to follow text parsing. Format profile is passed as a parameter |
| `generate_receipt` | No change — creates PDF receipt, doesn't touch ledger |
| `regenerate_receipt` | No change — same as above |
| `generate_consolidated_receipt` | No change |
| `update_ledger_entry` | No change — still operates on the ledger. The underlying provider method now writes to single sheet instead of dual sheets |
| `delete_ledger_entry` | No change — same as above |
| `add_demand_entry` | No change — still adds to ledger, writing to single sheet |
| `batch_add_demand_entries` | No change — same as above |
| `generate_invoice` | No change |
| `regenerate_invoice` | No change |
| `delete_invoice` | No change |
| `batch_generate_invoices` | No change |
| `trigger_april_entries` | No change |
| `get_current_settings` | No change |
| `add_new_member` | No change — adds to Members sheet, outstanding now auto-computed from ledger instead of being stored |
| `update_rates` | No change |
| `extract_payment` | No change — manual payment entry, writes to single ledger sheet |
| `batch_process_historical_receipts` | No change |

**System prompt updates:**
- Update rule 3: "For bank statements: use the `process_bank_statement_pdf` tool with the filename from `data/bank_statements/`. The PDF has already been uploaded and parsed by the UI — your job is to match parsed entries to members and generate receipts"
- Remove any references to copy-pasting bank statement text
- Remove any references to `Current_Outstanding` or `refresh_all_outstandings`

## Migration Plan

1. Take a manual backup of `data/society_data.xlsx` before any changes
2. Add `Plot_No` column to master `Ledger` sheet:
   - For each per-plot sheet `Plot_No_XX`, copy all entries into master `Ledger` with `Plot_No = XX`
   - Handle deduplication: if an entry already exists in master (matching on all of: Date + Particulars + Vch_No + Amount), skip it. The master `Ledger` sheet already contains all entries (it was written in parallel with per-plot sheets), so most entries will be deduplicated away
3. Drop per-plot sheets
4. Drop `Current_Outstanding` column from `Members` sheet
5. Update `_load_cache` to read `Plot_No` column and build `ledger_by_mid` from single sheet
6. Remove all outdated code paths (per-plot writes, outstanding updates, refresh_all_outstandings)
7. Create `data/bank_statements/` directory and `Reports` sheet
8. Verify: all existing tests pass, manual spot-check of 3-4 member ledgers

## Testing

- All existing tests must pass after migration
- New tests for PDF extraction with sample PDFs (no real bank data)
- Reconciliation test: inject known discrepancies, verify detection
- Backup/restore test: process statement, restore backup, verify state matches pre-statement

## Files Changed

| File | Change |
|------|--------|
| `data_providers/local_excel_provider.py` | Drop per-plot writes, remove `Current_Outstanding` write paths, remove `refresh_all_outstandings`, add `Reports` sheet management, add `Processed_Statements` sheet management |
| `data_providers/base_provider.py` | Update interface if needed |
| `main.py` | Replace text-area input with file uploader + password field, add auto-backup, add restore UI, remove Refresh Balances button, add Reconcile button, update Dashboard KPI computations |
| `agents/orchestrator_agent.py` | Replace `process_bank_statement` with `process_bank_statement_pdf` (takes filename + format profile), remove `Current_Outstanding` update calls, update system prompt rules 3 and 4 |
| `config.py` | Add `BANK_STATEMENTS_DIR`, `BACKUPS_DIR`, `BANK_STMT_PASSWORD` env var, `MAX_BACKUPS` |
| `tools/pdf_parser.py` | NEW — PDF text extraction with `pdfplumber`, format profile detection, post-processing |
| `requirements.txt` | Add `pdfplumber` |
