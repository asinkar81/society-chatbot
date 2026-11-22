# Project Progress & Guidelines

## Goal
- Enhance society management system with batch payment processing, unified ledger preview, payment identifier management, simplified suspense flow, auto-split fixes, retroactive split rule application, undo-compatible split descriptions, FY-wise reconciliation, safe Excel writes, reliable batch manual entry handling, Phase 1 email sharing, identifier matching fixes (IMPS, short-name substring, preference persistence), enhanced email templates (invoice summary, statement type column), email/regenerate bug fixes, and WhatsApp Web sharing

## Constraints & Preferences
- Preview-then-confirm workflow for Ledger creation in a `st.form` to avoid per-widget page refreshes
- All entries (matched + unmatched) get a plot dropdown — matched default to auto-assigned plot, unmatched default to "No Match"
- Matched entries can be reassigned to a different plot or set to "No Match" (sent to Suspense)
- Create processes selected entries with a plot assigned; Suspense processes selected entries with "No Match"
- Unmatched entries get a text input for Known Identifier — if plot+identifier are both filled, system learns the identifier as PAYEE_NAME on create
- Result message displayed as a banner at top of the preview table (`pv_result_msg`, popped from session state)
- Auto-create button uses separate global message (`ledger_create_msg`) for fallback
- Backups support optional comments embedded in filename via `--` separator
- Backups have a delete button per row (immediate), and show all backups (no 10-item limit)
- Identifiers UI shows column headers and two checkboxes per row (Keep + Delete for active, Restore for deleted)
- Identifiers save summary shows per-action counts ("Deleted 3, Restored 1, Added 1") instead of generic total
- Soft-delete for Payment Identifiers (with "Deleted" flag), not hard deletion
- Payment Identifiers managed from Settings → Identifiers tab, not mixed with Ledger UI
- STOP_WORDS expanded to filter out generic bank statement tokens
- Identifiers should NOT record amounts, numeric-only strings, code-like tokens without vowels, or tokens with embedded decimal amounts
- Entry counts and totals (credits/debits) should be FY-filtered, not all-time
- FY filtering in all paths must use YYYY-MM-DD date comparison, not raw DD-MM-YYYY string comparison
- PDF generation is opt-in (checkbox defaults to off)
- Short uppercase name tokens (SHW, FUT, AJAY) should be recorded as identifiers and match via substring/prefix in Phase 3b — `_clean_payment_refs` must NOT purge them (changed threshold from `len<=4` to `len<=2`)
- The Ledgers tab should not contain Invoice regeneration or Delete entry buttons — those belong in Invoices tab
- **Suspense flow simplified**: no Pending/Tagged states. Single flat list with plot dropdown + "📋 Create Ledger Entry" button per entry.
- **Auto-split**: When a member has a split rule, the full-amount entry must be removed and replaced with `per_head` entries for ALL group members (including source). Must use Undo-compatible description format: `"Split from #{orig_vch} (src:{mid})"`. Source member must NOT get a receipt PDF for the full amount — only per_head receipts for all group members.
- **`st.form_submit_button` only**: Widgets with `on_change` callbacks inside `st.form()` are illegal (Streamlit v1.42+). **`st.button()` also cannot be used inside `st.form()`**.
- **Tool descriptions must escape `{`**: JSON examples with unescaped `{` cause `KeyError` during `str.format()` in `PromptTemplate`.
- **`record_manual_payments` must accept `member_id`**: pass resolved member_id directly instead of relying on plot_no fuzzy lookup.
- **Plot_no lookup must handle zero-padding**: `get_member_by_plot_no` should try both zfill(2) and raw plot_no.
- **Excel write failures must be reported**: `add_ledger_entry` returns False when `PermissionError`/`OSError` occurs.
- **Email sharing phases**: Phase 1 = Email (implemented), Phase 2 = WhatsApp Web (implemented), Phase 3 = Tracking & History (future)
- **4 email templates**: Payment Receipts, Invoices (summary-only table), Statement (summary + Type column), Reminder (entries table)
- **Consolidated sends**: Single FY sends via Settings > Email Share Document; single-entry 1-click via 📧/💬 buttons in Receipts/Invoices tabs
- **NaN-safe email access**: ALL `.get("Email", "")` calls must check `pd.isna()` or use raw-email guard (`"" if pd.isna(raw) else str(raw).strip()`) — empty Excel cells return `float('nan')` which is truthy
- **Collapsible sections** in Settings > Email: 1. Share Documents, 2. Email Configuration
- **Multi-select recipients**: single `st.multiselect` with `"Plot X — Name"` labels replaces old individual dropdown + batch button split
- **Auto-generate missing receipt PDFs** before attaching to email
- **`regenerate_invoice` must delete ALL entries with same invoice_no+FY** before creating new one — cleans up duplicates, prevents cross-FY deletions
- **`delete_ledger_entry` must catch PermissionError** like `add_ledger_entry` does
- **`_split_emails` must guard non-string input**: return `[]` if `raw` is not a `str`
- **Email subjects must start with "Weekend Ville"** prefix for all 4 templates
- **Email body entries sorted by date ascending** (earliest first) — not by Vch_No
- **Statement total** must compute CR − DR (net), not sum of all amounts
- **PDF filenames** shown as attachment list in all email templates
- **Invoice ledger entries** store only `total_line_items` (base charges), not `total_amount_due` (which included previous outstanding). Total demand shown in Description text only.
- **Identifier reconciliation** searches only `Particulars` (not Description)
- **Per-row button keys** must use stable `idx` (loop index), never `id(e)` — `id()` returns different value on every Streamlit rerun, making buttons unclickable
- **Pending count** only counts entries with `Deposit > 0` (excludes withdrawals)
- **Reconcile Identifiers button must be outside `st.form()`** — `st.button()` cannot be nested inside `st.form()` in Streamlit
- **Action buttons in Reconcile Identifiers must be at top-level script scope** (not inside another `st.button` trigger) — use `st.session_state` to persist results across reruns
- **Manual Excel edits need cache invalidation**: `LocalExcelDataProvider._cache` only invalidates on writes; external edits invisible without file-mtime tracking or a Reload button
- **IMPS regex must handle two formats**: (A) `"KMB / AJAY IMPSAB/..."` — name between `/` and `IMPS`, (B) `"IMPSAB/UTRN/PayeeName"` — name after UTR. UTRN is transaction-unique (not reusable for sender lookup).
- **Invoice email template**: shows Summary table only (4 rows: prev outstanding, demand, payments, total due) — no entries table
- **Statement email template**: shows Summary table + entries table with Type column (Invoice/Receipt)
- **WhatsApp Web sharing via wa.me**: wa.me deep links, no automation (user clicks Send), staging folder at `data/staging/whatsapp/` collects PDFs for drag-drop, Summary table as text, message copied to clipboard

## Progress
### Done
- Created `record_manual_payments` tool: batch processes list of payment entries in one call, handles member resolution, multi-plot equal splitting, duplicate detection, per-entry summary
- Added `_find_members_by_name` helper: token-overlap scoring with ≥50% threshold, strips titles, handles transliteration
- Increased `max_iterations=30` and `max_execution_time=120` in `base_agent.py:188`
- Updated system prompt rule 7: instructs LLM to use `record_manual_payments` for batch lists, `add_ledger_entry` for single entries
- Modified `create_ledger_from_accounts` to support 3 modes (preview/create/send_to_suspense) with `forced_assignments`
- Fixed UnboundLocalError for `search_identifiers` — initialized `= []` before `if not forced_plot:` block
- Redesigned UI: unified preview table inside `st.form(key="pv_form")` with three action `form_submit_button`s
- Added backup comment text input + 🗑️ Delete button per backup row + removed 10-item limit
- Identifiers tab: column headers + two checkboxes per row + per-action save summary
- Preview Ledger particulars column shows full value (not truncated)
- Expanded STOP_WORDS in `pdf_parser.py:196-212` and `orchestrator_agent.py:1773-1802`
- Improved `_should_record_name` / `should_record_name`: rejects purely numeric, code-like without vowels, embedded decimal amounts
- Removed `t.isalpha() and t.isupper() and len(t) <= 4` filter — was blocking legitimate short name tokens
- Added IMPS extraction pattern to `_extract_search_tokens` in both files (now handles Format A + Format B correctly)
- Added `importlib.reload(tools.pdf_parser)` before import in `create_ledger_from_accounts`
- Fixed FY date comparison in both `main.py` and `orchestrator_agent.py` using `_sortable()` conversion
- Added substring/prefix matching in Phase 3b in BOTH Path A and Path B: `name_sub` check scores +5
- **Fixed `led_sel_all` callback crash**: replaced `st.checkbox("☑", on_change=...)` inside form with ☑ All / ☐ None `form_submit_button` buttons
- **Simplified Suspense flow**: removed Status/Tagged_To/Tagged_Date columns, tag_suspense_entry method, Pending/Tagged tabs
- **Fixed auto-split over-credit bug**: `pending_ledger.pop()` / `pending_entries.pop()` to remove full-amount entry before creating per_head entries
- **Fixed description format**: `"Split from #{orig_vch} (src:{mid})"` — matches Undo Split regex
- **Fixed receipt PDF mismatch in auto-split**: source member no longer gets full-amount PDF
- Added **🔀 Run Split Rules on All** button and **🔀 Apply Rule** button in per-member toolbar
- Cleaned up base_provider.py: removed `status` param from abstract `get_suspense_entries`, deleted abstract `tag_suspense_entry`
- Updated tests: removed tagging tests, renamed `test_get_suspense_entries_pending`, simplified roundtrip, 3 `TestEmailSender` backward-compat tests (138 total pass)
- Added **FY-wise Reconciliation Table** with ₹1 tolerance
- **Fixed `KeyError: '"entries"'`** in `record_manual_payments` tool description — replaced raw JSON with plain-text field list
- **Fixed `get_member_by_plot_no` zero-padding**: tries both `str(plot_no).zfill(2)` and raw `str(plot_no)`
- **Fixed `add_ledger_entry`/`add_ledger_entries` write failures**: wrapped `_write_sheet` in `try/except (PermissionError, OSError)` — returns `False`/`0` instead of always `True`/`len()`
- Added `member_id` input support to `record_manual_payments` — checked before `plots`/`plot_no`/`name`
- Updated system prompt rules 1 and 7: tell LLM to trust explicitly provided plot_no/member_id
- Added `add_ledger_entry` tool return value check in orchestrator_agent.py: reports write failure message when returns False
- **Phase 1 Email Sharing implemented**: `send_template_email()` with 4 HTML templates, multi-PDF, auto-subject, styled tables; `COMM_HEADERS` + `log_communication` + `get_communication_log` in Excel provider; 📧 1-click buttons in Receipts/Invoices tabs
- **Fixed NaN email in Share Document**: `"" if pd.isna(raw) else str(raw).strip()` for all `.get("Email")` calls
- **Fixed `_split_emails` type guard**: `not isinstance(raw, str)` returns `[]` immediately
- **Added try/except** around `send_template_email` calls in Receipts and Invoices tabs
- **Fixed `regenerate_invoice` duplicate cleanup**: regex narrowed to match same invoice_no + same FY (`FY {fy_str}` appended), preventing cross-FY deletions. Deletes all matching entries before creating single replacement. Re-fetches ledger after deletions for correct outstanding.
- **Fixed `delete_ledger_entry` PermissionError**: wrapped `_write_sheet` in `try/except (PermissionError, OSError)` returning `False`
- **Settings > Email redesign**: collapsible expanders (Share Documents, Email Configuration); removed Payment Identifier Cleanup section (moved to Identifiers tab); multi-select recipients; single "Send" button
- **Auto-generate missing receipt PDFs** before building attachment list
- **Email subject prefix**: "Weekend Ville" on all 4 templates
- **Email entries sorted by date ascending** using `_sortable_date()` helper
- **Statement total fixed**: computes CR − DR (net) instead of sum of all amounts
- **Attachment filenames shown**: all email templates list attached PDF names
- **`_parse_invoice_entry` date regex fixed**: `\d{1,2}` for day/month with zero-padding — handles `"1-4-2021"` format
- **Pending count fixed**: `fy_pending`/`fy_unmatched` counts filter to `Deposit > 0` only
- **Suspense ⏭️ Skip button added**: marks Account Entry as "Skipped", removes from Suspense
- **New Reconcile Identifiers button** on Identifiers tab: searches `Particulars` in all ledgers, shows results table with conflict detection, auto-correction and auto-resolve buttons
- **`update_identifier_member` method** added to `LocalExcelDataProvider` and `BaseProvider`
- **Invoice ledger entries store only base charges**: all 5 creation paths changed `Debit: total_amount_due` → `Debit: total_line_items`
- **Regenerate All button** added to Invoices tab toolbar
- **Fixed `e_key = id(e)` bug** in main.py: Invoices (line 1378) and Receipts (lines 1136/1138/1150) — changed `id(e)` to `idx` (loop index), making per-row 🔄📧🗑️📄 buttons clickable
- **Fixed `st.button()` inside `st.form()`** in Settings > Identifiers tab: moved "🧹 Reconcile Identifiers with Ledger" and "Apply Corrections" buttons outside `with st.form(key="id_form")` block
- **Enhanced Reconcile Identifiers with auto-resolve**: multi-plot identifiers that are all split entries from the same source → auto-resolve to source plot; non-split entries on different plot → conflict
- **Moved action buttons to top-level script scope** using `st.session_state.id_recon_results`: Reconcile trigger stores results in session state and reruns; action buttons render at top level (not nested inside trigger) so clicks fire correctly; added Dismiss button
- **Fixed Bug: Manual Excel edits not picked up**: Added `os.path.getmtime` auto-invalidation in `LocalExcelDataProvider._load_cache()`; added "🔄 Reload Data from Excel" button in Members tab
- **Fixed Bug: Update Member fields not populating**: Changed 5 widget keys from static (`"upd_plot"`, etc.) to member-unique (`f"upd_plot_{upd_mid}"`, etc.) — widget state now switches correctly when member changes
- **Enhanced Invoice email template**: Now shows Summary table only (4 rows: Balance carried forward, New Demand, Payments Received, Total Outstanding as of date) — no entries table
- **Enhanced Statement email template**: Shows Summary table (same 4 rows) above entries table; entries table has new **Type** column (Invoice/Receipt); Net Total shown instead of total
- **Added `summary` parameter** to `_build_html_body()` and `send_template_email()` — computed at 1-click 📧 callsite (Invoice tab) and batch Share Documents call (Settings > Email), passed through to template
- **Fixed IMPS regex** in `_extract_search_tokens` (both `pdf_parser.py` and `orchestrator_agent.py`): handles Format A (`"KMB / AJAY IMPSAB/..."` via `/`-before-`IMPS` regex) AND Format B (`"IMPSAB/UTRN/PayeeName"` via split-by-`/` reverse-scan, skipping phone segments and "IMPS"-containing segments)
- **Fixed `_clean_payment_refs` purging short identifiers**: changed `is_short_upper` threshold from `len(val) <= 4` to `len(val) <= 2` — SHW, FUT, SHR, PRI (3-char UPI names) now survive restart cleanup
- **Added `name_sub` substring matching to Path A** (`process_bank_statement_pdf` in `orchestrator_agent.py`): previously only Path B had it; now both paths match "SHW"→"SHWETA", "FUT"→"FUTANE"
- **Extracted matching logic into shared utility**: Created `utils/matching.py` with `score_member_match()` and `ngram_match()` — used by both Path A and Path B, removed duplicate code from `orchestrator_agent.py` and `pdf_parser.py`
- **Phase 2: WhatsApp Web sharing implemented**:
  - `utils/whatsapp.py` — `build_wa_message()`, `build_wa_link()`, `copy_to_clipboard()` via `pbcopy` (macOS)
  - 💬 buttons in Receipts and Invoices tabs (per-row 1-click, copies message + opens wa.me)
  - 💬 Send via WhatsApp in Settings > Email > Share Documents (consolidated bulk sharing)
  - Document filtering checkboxes (Include Receipts, Include Invoices) for selective PDF staging
  - Staging folder (`data/staging/whatsapp/`) collects PDFs for drag-drop into WhatsApp Web
  - Messages include Weekend Ville Society context + Summary table as plain text
  - Communication logged with `template_type="whatsapp"`
- **Table Grid PDF Extraction & Header Stripping Fix (`tools/pdf_parser.py`)**:
  - Identified table grid structure in digital statements (Union Bank of India statements from March 2026 onwards).
  - Implemented `_extract_table_grid_lines()` and `has_table_grid()`: extracts cells directly from table boundaries, completely eliminating multi-line cell baseline shifts where payee names bled into previous entries (e.g. Ashutosh Vijaykumar bleeding into Rama Salvi).
  - Tagged table grid withdrawals with `Dr` and deposits with `Cr` during extraction so first-row withdrawals/deposits calculate correctly without ambiguity.
  - Added header metadata pattern filtering in `_strip_non_transaction()` and `clean_entries()` (`DETAILS OF STATEMENT`, `Customer ID`, `Branch`, `IFSC`, `MICR`, `KYC`, etc.) to prevent bank statement metadata from leaking into first-row transaction particulars.
  - Added 100% backward-compatible fallback to character extraction for legacy passbook/printed statements without table grids (verified statements 1-5 continue to match 100%).
  - Added automated unit tests in `tests/test_pdf_parser.py` (`test_has_table_grid_detection`, `test_table_grid_multiline_isolation`, `test_extract_text_backward_compatibility`, `test_batch_statements_june_to_oct_2026`). Full test suite passes 156/156 tests.
  - Restored `data/society_data.xlsx` from pre-parse backup `society_data_20261121_155200_pre_parse.xlsx`, resetting Accounts (441 rows) and Ledger (603 rows) to clean state before June statement ingestion.
  - Verified batch parsing of statements from `9_June_26.pdf` through `13_Oct_26.pdf`: all 60 entries across 5 months parsed with zero `Balance_Check` discrepancies, zero header bleed, and mathematical continuity from ₹2,86,627.72 down to ₹1,67,710.67.
- **Auto-Reconcile & Retag for Manual Ledger Entries (`orchestrator_agent.py` & `main.py`)**:
  - Automatically cross-references pending Accounts statement deposits against existing Ledger entries by `Date + Amount + (Transaction_ID or UTR inside Particulars/Description)` or `Member + Date + Amount + MANUAL`.
  - In Preview mode, flags entries as `reconciled` with `🔗` icon and `"Already in Ledger (Vch #{vch}) — Bank Verified"`.
  - Added unit test `test_reconcile_existing_manual_ledger_entry` in `tests/test_comprehensive.py`. Full test suite passes 157/157 tests.
- **Reconciliation Report & Balance Fixes (`main.py`, `tools/pdf_parser.py`, `orchestrator_agent.py`)**:
  - Replaced naive continuous sequence check with **Voucher Uniqueness Check** (`FAIL` only if duplicate vouchers exist; currently 0 duplicates) and an informational **Voucher Sequence Audit** (`OK`, explaining FY series block jumps and auto-split parent removals).
  - Enhanced MOBFT regex in `tools/pdf_parser.py` and `agents/orchestrator_agent.py` to match `MOBFT/<name>/...` formats in addition to `from: <name>`.
  - Added transactional atomicity to `create_ledger_from_accounts`: tracks `pending_accounts_status` and applies `update_accounts_entry` only after `add_ledger_entries(pending_ledger)` completes, preventing partial failures from leaving accounts entries marked "Matched" without ledger entries.
  - Resolved FY 26-27 balance mismatch by creating missing entries for Plot 10 (Entry 442) and Plot 41 (Entry 444), bringing FY 26-27 to 100% balance (`₹272,000.00 == ₹272,000.00 ✅`). All 6 financial years now pass balance reconciliation.
  - Added automated unit tests `test_extract_search_tokens_mobft` and `test_mobft_matching_and_atomicity`. Full test suite passes 159/159 tests.
- **Accounting-Sound Duplicate Detection Engine (`utils/matching.py` & `main.py`)**:
  - Replaced naive `_normalize_particulars` grouping which previously generated **55 false positive duplicate groups** by grouping identical particulars without checking plot, date, amount, or transaction type (e.g., flagging standard annual invoices for 41 different plots as one duplicate group, legitimate multi-plot split entries, and recurring annual payments across years).
  - Implemented `extract_txn_ref(e)` to safely extract genuine bank transaction references/UTRs while ignoring split references and stop words.
  - Implemented `scan_ledger_duplicates(ledger)` in `utils/matching.py` with 3 accounting-sound checks:
    1. **Same-Plot Duplicate**: Same plot + date + amount + direction, unless entries have distinct verified UTRs (permits legitimate same-day multiple payments).
    2. **Cross-Plot UTR Collision**: Same real alphanumeric bank UTR assigned to multiple plots, strictly excluding intentional `SPLIT` entries.
    3. **Duplicate Invoices**: Same plot billed more than once within the same Financial Year.
  - Updated UI in `main.py`: cleanly differentiates un-run (`None`), zero duplicates found (`✅ No duplicates found! All ledger entries are verified.`), and genuine duplicates found, while preserving per-row delete and undo-split capabilities.
  - Added `TestLedgerDuplicateScanner` unit tests in `tests/test_comprehensive.py`. Full test suite passes 165/165 tests.
  - Verified on live database: drops from 55 false positive groups to 0 duplicates.
- **Defaulters Report Audit & Multi-Category Enhancement (`main.py`)**:
  - Investigated why Plot 33 (Mrs. Sangita Sunil Varpe) was missing from the Defaulters report: Plot 33 is NOT a defaulter. Plot 33 has ₹67,000 in credits vs ₹65,000 in debits across all 6 financial years, having a **net surplus of +₹2,000.00** (advance paid).
  - Identified 4 anomalies in Defaulters report: silent omission of non-defaulters without explanation, lack of categorization filter, missing high-level summary KPIs, and redundant N+1 Excel ledger reads (82 reads per load).
  - Enhanced `main.py`: aggregated ledger in a single memory pass with `_s()` NaN safety, added 4 KPI metric cards (🔴 37 Defaulters: ₹11,35,999 due | 🟢 2 In Surplus: ₹3,000 | ⚪ 2 Settled | 📋 41 Total Plots), added an interactive view filter radio (`Defaulters`, `In Surplus / Advance`, `Settled`, `All Plots`), and added an explanatory caption in the Defaulters view clarifying that 4 plots have no pending dues (Plots 16 and 33 in surplus; Plots 26 and 30 settled).
- **Comprehensive 41-Plot Ledger Audit & Anomaly Resolution**:
  - Cross-referenced all 41 accountant plot PDFs in `data/Accountant Ledgers/` against our database ledger.
  - Proved ₹18,000 Anshul Rathod payment was 100% correctly credited to Plots 5 & 20; accountant erroneously credited it to Ashutosh Pujari (Plots 28 & 29).
  - Confirmed phone 9960184874 belongs to Plot 18 (Mrs. Manjiri Gavande); master record for Pujari updated with 9962132503.
  - Verified user moved Vch #920 (₹18k) from Plot 27 to Plot 36, and Vch #683 (₹5k `CONTINUUM`) from Plot 18 to Plot 19.
  - Tagged `NEFT:CONTINUUM` to Plot 19 in `Payment_References`, soft-deleted duplicate, and hardened `LocalExcelDataProvider.find_member_by_identifier()` against soft-deleted entries.
  - Forensic investigation of Plot 8 vs 37 misassignment: branch token `SHAN` (HDFC Shanipar) misattributed to Shantanu Kulkarni; Ajaykumar's phone verified for Plot 37.
  - Resolved `ValueError: cannot convert float NaN to integer` in `local_excel_provider.py:1080` by cleaning `Split_Rules` sheet and adding `pd.isna()` type guards.
- **Bank Debits Recording & Society Expenses Dashboard (`main.py` & `local_excel_provider.py`)**:
  - Extracted, deduplicated, and classified all **129 genuine bank debit entries** (totaling **₹14,82,003.33**) from `Accounts` into `Expenses` sheet across 5 financial years (FY 22-23 to FY 26-27).
  - Implemented `sync_accounts_debits_to_expenses()` in `LocalExcelDataProvider` to scan and auto-classify any future debit transactions.
  - Upgraded `get_expense_summary(fy)` to support financial year filtering.
  - Completely revamped `tab_expenses` in `main.py`: added 4 metric KPI cards, an interactive multi-year FY breakdown pivot matrix, search and category/FY filter drill-downs, a "🔄 Sync Bank Debits" button, and manual expense recording. Full test suite passes 165/165 tests.
- **Treasurer's AGM Financial Report, Expense Analysis & Next FY Budget Artifacts**:
  - Created and finalized [agm_audit_validation_report.md](file:///Users/ashutoshsinkar/.gemini/antigravity/brain/db392fa2-4f19-47cd-a060-f89008858d15/agm_audit_validation_report.md) with two-report publishing strategy, 41-plot audit reconciliation, Builder WhatsApp Nov 2021 salary evidence, and member reimbursement policy.
  - Created, revised, and secured user approval on [treasurer_budget_and_expense_analysis.md](file:///Users/ashutoshsinkar/.gemini/antigravity/brain/db392fa2-4f19-47cd-a060-f89008858d15/treasurer_budget_and_expense_analysis.md):
    * Audited 5-year spend trends (Salaries ₹6.63L, MSEB ₹5.32L, Reserves ₹1.00L, Maintenance/Repairs ₹1.24L, Audit/Accts ₹32.6k, NA Tax ₹29.1k).
    * Factual root cause of MSEB escalation: 3-year non-issuance of bills by MSEDCL resulting in accumulated arrears/penalties under residential rates; 100% of arrears now cleared and eligible for ownership transfer.
    * 37-plot Defaulter Crisis (₹10.53 Lakhs unpaid dues, 60.6% collection efficiency, with 54.3% concentrated in 9 chronic defaulters).
    * Statutory recovery framework under Section 154B-29 of Maharashtra Co-operative Societies Act, including detailed legal analysis on water regulation (immediate disconnection for non-essential water; due process with 15-day notice for domestic water).
    * Operational Budget (OPEX) for Next FY (₹5.38 Lakhs / year): Caretaker Pandit hike to ₹14,000/mo, dedicated Society Property Manager @ ₹9,000/mo, regularized MSEB, and taxes.
    * 3-Tier Prioritized Capital Budget (CAPEX) totaling ₹8,32,000 (~₹20,000/plot): Must Have (₹1 Lakh for Club House legal ownership/lawyer, MSEB meter transfer ₹40k, standby pump ₹65k); Requires Immediate Attention (Solar Power Plant ₹3.25L, CCTV network ₹1.35L, railing red oxide ₹70k, gutter clearing ₹35k, grass machine overhaul ₹12k); Nice to Have (Children's play area downscaled to ₹50k).
    * Tabled 6 formal Draft AGM Resolutions for the Treasurer to move at tomorrow's AGM.

### In Progress
- (none)

### Blocked
- (none)

## Key Decisions
- Preview table wrapped in `st.form(key="pv_form")` — eliminates per-widget page refresh on dropdown/checkbox/text changes
- All entries get a plot dropdown instead of matched=read-only text — enables reassignment of wrongly matched entries
- Suspense button accepts ALL entries with No Match (originally matched or unmatched)
- Create handler forces new plot assignment via `forced_assignments` when matched entry's dropdown differs from original
- Identifier learning happens in frontend BEFORE backend create call
- Result message uses `pv_result_msg` popped from session state — shown once then disappears
- Backups embed comments in filename via `--` separator
- Identifiers Keep checkbox is informational — only Delete checkbox triggers action on save
- Payment Identifiers use soft-delete with `Deleted` flag, not row removal
- Suspense tagging eliminated — Pending/Tagged state concept removed
- Auto-split must delete original entry: full-amount entry on source is removed and replaced with per_head entries for ALL group members
- Split description format must match Undo Split regex: `"Split from #{orig_vch} (src:{mid})"`
- Split receipt PDFs: source member must NOT get full-amount receipt
- Manual entries via Chat bypass split rules
- INVOICE entries are DEBIT entries unrelated to auto-split which only processes CREDIT entries
- Tool descriptions must avoid `{` in `register_tool` calls
- `get_member_by_plot_no` must try both padded/unpadded plot_no
- `add_ledger_entry` must return False on write error
- Reset & Rebuild preserves Split Rules but creates NO automatic backup
- Email sharing phased approach: Phase 1 = Email (done), Phase 2 = WhatsApp Web (done), Phase 3 = Tracking & History (future)
- Consolidated FY sends in Settings > Email; 📧/💬 1-click buttons in tabs send single-entry
- Communication Log stored in Excel `Communications` sheet
- NaN-safe email extraction: ALL `.get("Email", "")` calls must guard with `pd.isna()`
- Collapsible sections in Settings > Email: Share Docs, Email Configuration — Payment Identifier Cleanup removed from Email tab, moved to Identifiers tab
- Multi-select recipients replaces individual + batch split — single "Send" button for all selected
- Auto-generate missing receipt PDFs before sending
- `regenerate_invoice` must delete ALL matching invoice_no entries by same FY — fixes wrong outstanding from duplicate accumulation and prevents cross-FY deletion
- Invoice ledger entries store only `total_line_items` (base charges), NOT `total_amount_due`
- Email templates: subjects prefixed with "Weekend Ville", entries sorted by date ascending, statement total = CR − DR, PDF filenames listed as attachments
- Identifier reconciliation searches only `Particulars` (not Description)
- Per-row button keys must use `idx` (loop index), never `id(e)` — `id()` is unstable across reruns
- Reconcile Identifiers button must be outside `st.form()` — `st.button()` inside `st.form()` is illegal in Streamlit
- Action buttons (Auto-Resolve, Apply Corrections, Dismiss) must be at top-level script scope (not inside trigger `st.button`), with results persisted in `st.session_state`
- `LocalExcelDataProvider._load_cache()` must auto-invalidate on file modification time change — external edits otherwise invisible without write operation
- Update Member text fields must use member-unique widget keys (`f"upd_plot_{upd_mid}"`) — static keys cause stale data across member selection
- Invoice email template: Summary table only (no entries table) — the attached PDF has the full breakdown
- Statement email template: Summary table + entries table with Type column (Invoice/Receipt) — both summary and detailed entries
- UTRN is transaction-unique — NOT reusable as a sender identifier lookup
- IMPS regex must handle both formats: (A) name between `/` and `IMPS` (old format), (B) name after UTR in split-by-`/` segments (new format)
- Matching logic shared: `utils/matching.py` with `ngram_match()` and `score_member_match()` — single source of truth, WhatsApp scoring +8pts now applies in both Path A and Path B
- WhatsApp Web sharing via wa.me links: no automated sending, message copied to clipboard + wa.me pre-filled, staging folder for PDFs, text-based Summary table

## Next Steps
1. Phase 3: Tracking & History (communication dashboard)
2. Consider whatsapp number validation in settings

## Critical Context
- `search_identifiers` must be initialized (`= []`) before `if not forced_plot:` block in `create_ledger_from_accounts`
- DD-MM-YYYY string comparison breaks for cross-year ranges — ALL date comparisons must use `_sortable()` YYYY-MM-DD conversion
- `_extract_search_tokens` exists in TWO places: local closure in `orchestrator_agent.py:1768` and import from `pdf_parser.py:192`. Both must be kept in sync (IMPS regex now matches in both).
- `create_ledger_from_accounts` has `importlib.reload(tools.pdf_parser)` before the import
- Widget keys for preview form: `pv_cb_{eid}` (checkbox), `pv_plot_{eid}` (dropdown), `pv_idtxt_{eid}` (text input)
- Result message key: `st.session_state["pv_result_msg"]` — popped at start of preview container
- **`id(e)` is fixed**: all per-row buttons (regenerate, email, delete, download) now use `idx` (loop index) instead of `id(e)`
- **`regenerate_invoice` function works correctly**: Parse, PDF creation, ledger entry creation all verified
- **Invoice entries with `total_amount_due` as debit** create compounding bug — fixed: now store only `total_line_items`. Existing entries need regeneration to fix.
- **`_parse_invoice_entry` handles all Description formats**: `"Invoice X FY YY-YY"`, `"Invoice X FY YY-YY (regenerated)"`, `"Invoice X FY YY-YY (Demand: ₹X)"` all parse correctly
- **`send_template_email` returns dict** with `success`, `subject`, `error`, `recipients` — caller responsible for logging via `data_provider.log_communication()`
- **`data_provider` is available** in all tab sections of `main.py`
- **`compute_outstanding_as_of`** returns `credits - debits`; negate to get "amount owed"
- **`st.button()` inside `st.form()`** is illegal in Streamlit — the Reconcile Identifiers button was fixed by moving it outside the form
- **Action buttons nested inside trigger `st.button`** never fire — must persist results in `st.session_state` and render buttons at top-level script scope
- **`LocalExcelDataProvider._cache`** stale-data bug: fixed by adding `os.path.getmtime` check in `_load_cache()`. Also added "🔄 Reload Data from Excel" button.
- **Widget key collision** in Update Member: fixed by making keys unique per member ID
- **IMPS UTRN is transaction-unique** — cannot be used to identify recurring senders; only the payee name after the UTR matters
- **`_clean_payment_refs` threshold** changed from `len<=4` to `len<=2` — short UPI names like SHW, FUT, SHR, PRI survive cleanup
- **`name_sub` substring matching** now exists in BOTH Path A and Path B — short tokens match member name substrings consistently
- **`utils/matching.py`** contains shared `ngram_match()` and `score_member_match()` — eliminates duplicated fuzzy matching logic
- **WhatsApp Web**: wa.me deep links, no automated sending. `utils/whatsapp.py` with `build_wa_message()`, `build_wa_link()`, `copy_to_clipboard()`. Staging folder at `config.STAGING_DIR / "whatsapp" / {timestamp}`. Communication logged with `template_type="whatsapp"`.

## Relevant Files
- `agents/orchestrator_agent.py`: `_find_members_by_name` (line 149), `record_manual_payments` (line 883), `create_ledger_from_accounts` with importlib.reload (line 2784), auto-split fixes (lines 2247, 3138), description format change, expanded STOP_WORDS (line 1773), Phase 3b substring matching in BOTH paths (lines ~2066, ~3081), IMPS fix in both _extract_search_tokens copies (line ~1891), tool description brace fix (line 3363), invoice ledger entry fixes (lines 1177, 1283, 1294, 1513)
- `agents/base_agent.py:188`: max_iterations=30, max_execution_time=120
- `tools/pdf_generator.py`: `create_simple_invoice_pdf`, `create_simple_receipt_pdf`, `create_consolidated_receipt_pdf` — used by email sender for attachments
- `tools/pdf_parser.py:192-301`: expanded STOP_WORDS, `should_record_name` filters, IMPS extraction (Format A + Format B), `_extract_search_tokens`
- `data_providers/local_excel_provider.py`: Suspense simplified (no Status/Tagged), `get_member_by_plot_no` dual-format, `add_ledger_entry`/`add_ledger_entries` PermissionError handling, `delete_ledger_entry` PermissionError fixed (line 463), `COMM_HEADERS` + `log_communication` + `get_communication_log`, `update_identifier_member`, `_clean_payment_refs` threshold `len<=2`, file-mtime auto-invalidation in `_load_cache()`
- `data_providers/base_provider.py`: abstract methods for suspension (no status param), communication logging, `update_identifier_member` abstract
- `utils/email_sender.py`: `send_template_email()` with `summary` parameter, `_build_html_body()` with summary support, 4 HTML templates (invoice = summary-only, statement = summary + Type column), `_split_emails` with `not isinstance(raw, str)` guard, "Weekend Ville" subject prefix, date-ascending sort, statement total CR−DR, `_summary_html()` helper
- `utils/matching.py`: Shared fuzzy matching logic — `ngram_match()` and `score_member_match()`, single source used by both Path A and Path B
- `utils/whatsapp.py`: WhatsApp Web sharing — `build_wa_message()`, `build_wa_link()`, `copy_to_clipboard()`
- `main.py`: `e_key = idx` fix (line 1378 Invoices, lines 1136/1138/1150 Receipts), `st.button()` outside `st.form()` fix, session-state-based Reconcile action buttons (Auto-Resolve + Dismiss), NaN-safe email with `pd.isna()` guard, Settings > Email redesigned with collapsible expanders, multi-select recipients, Reload Data button in Members tab, unique widget keys in Update Member section (`f"upd_plot_{upd_mid}"`), `summary` computation in Invoice 📧 and Share Documents call sites, auto-resolve split detection in Reconcile logic, 💬 buttons in Receipts/Invoices tabs, WhatsApp bulk sharing in Share Documents
- `utils/converters.py`: `compute_outstanding_as_of`, `get_payment_history`, `get_previous_invoices`, `number_to_words_inr` — used by `regenerate_invoice` for outstanding calculation, also by email summary computation
- `tests/test_comprehensive.py`: 138 tests — includes IMPS tests (Format A + short-name extraction), name_sub tests, CR short-name tests
- `tests/test_whatsapp.py`: 7 tests for WhatsApp message builder, wa.me links, clipboard
- `config.py`: STAGING_DIR for WhatsApp staging folder
- **`Split_Rules` NaN crash fix**: `ValueError: cannot convert float NaN to integer` occurred in `get_split_group_for_member` when manual Excel edits left trailing rows with NaN in `Source_Member_ID`. Cleaned `Split_Rules` sheet in `society_data.xlsx`, hardened `get_split_rules` and `get_split_group_for_member` in `local_excel_provider.py` to drop invalid/NaN rows, and added `pd.isna()` guards across all call sites in `main.py`.
- **AGM Audit Cross-Verification**: Audited all 41 accountant plot ledgers against system records. 15 plots match 100%. Confirmed Anshul Rathod's ₹18k was 100% correctly attributed to Plots 5 & 20 in our system (accountant mistakenly gave it to Ashutosh Pujari in `PLOT NO.28 PUJARI.pdf`). Confirmed phone `9960184874` belongs to Plot 18 (Manjiri Gavande), validating that Vch #286 (₹6,000 on 03-07-2022) is correctly credited to Plot 18 in both systems. Detailed raw entry for 09-12-2025 UPI payment (`534366020481`) with 5-point rationale for Plot 36 (Rahul Palnitkar) vs Plot 27 (Rahul Bachikar). Clarified Continuum Industries (₹5,000) for Plots 18/19 where combined dues match ₹49,000. Full audit documented in `agm_audit_validation_report.md`.
- **Treasurer's Financial Report, Expense Analysis & FY 2027-28 Budget PDF (`tools/generate_agm_budget_pdf.py`)**:
  - Implemented an exact 5-page, publication-grade executive presentation PDF optimized for WhatsApp sharing and AGM printing:
    - **Page 1**: Executive Summary & Liquid Financial Position (₹2.68L total liquid reserves) + 5-Year Audited Spend Matrix (129 bank debits totaling ₹14,82,003.33) + Factual clarification callout on MSEB non-billing arrears and 100% regularized residential rates.
    - **Page 2**: Defaulter Severity Analysis (₹10.50L arrears across 37 plots) + Plot 37 audit clarification + Comprehensive Section 154B-29 (MCS Act) summary recovery legal powers and water regulation/disconnection rules.
    - **Page 3**: Master 41-Plot Individual Audit Reconciliation Sheet (all 41 plots + total row fitted on a single dedicated page with single-line rows, no line wrapping, color-coded severity badges).
    - **Page 4**: Proposed OPEX Routine Budget (₹5,38,000/yr, ₹1,093/plot/mo) + Prioritized 3-Tier CAPEX Plan (₹8,32,000 total: Must Have ₹2.05L, Requires Immediate Attention ₹5.77L, Nice to Have ₹50k).
    - **Page 5**: Funding Recommendations (Maintenance revision to ₹1,500/mo, Special Capital Levy ₹20,000/plot, Defaulter recovery linkage to fast-track Solar/CCTV) + 6 Formal Draft AGM Resolutions + Society Treasurer Certification block.
  - Universal mobile rendering: Uses universal `Rs.` notation and en-dash `&ndash;` (eliminates ReportLab Latin-1 character conversion issues and `(cid:xxx)` missing glyphs on iOS/Android WhatsApp viewers).
  - Generated identical copies to root `Weekend_Ville_Treasurer_Budget_and_Expense_Analysis.pdf`, WhatsApp staging folder `data/staging/whatsapp/`, and artifact folder.
- **AGM Audit Validation & Reconciliation Report PDF (`tools/generate_agm_audit_pdf.py`)**:
  - Implemented an exact 4-page, publication-grade executive audit report PDF optimized for WhatsApp sharing and AGM printing:
    - **Page 1**: Executive Summary & The Two-Report Approach (Statutory Audit as of 31-Mar-2026 for formal adoption vs Management Live Reconciled Addendum as of 31-Oct-2026) + High-Level Reconciliation KPI Summary Table (15 plots 100% match, family groups reconciled, ₹13,110 net verified bank collections) + Accounting Policy on Member Expenses (Plots 13 & 26 direct reimbursement principle).
    - **Page 2**: Builder's Verified Record (November 2021 Shivaji Salary register from Mr. Shailesh Dave, Axis Bank breakdown, proving Plot 12 Maskikar duplicate cash entry) + Proven Audit Errors Table (6 plots with verified bank UTRs: Rathod ₹18k, Pujari ₹18k reversal, Modak ₹9k, Bhosale ₹2k, Maskikar ₹1k duplicate reversal, Phutane ₹1k reimbursement) + Specific Live Adjustments (Plot 36 Palnitkar vs Plot 27 Bachikar Vch #920 moved, Plot 19 Continuum Vch #683 moved, Plot 18 Phone 9960184874 verification, Plot 8 vs 37 Rs. 3k validation).
    - **Page 3**: Master 41-Plot Audit Reconciliation Table (all 41 plots + total row comparing Accountant Audit Credits vs Society Records Credits vs Audit Net Balance vs Status badges fitted completely on a single dedicated page).
    - **Page 4**: Formal Draft AGM Resolution for General Body Minutes (Resolution No. __: Adoption of Audited Accounts for FY 2025-26 & Authorization of FY 2026-27 Rectification Journal Entries across 5 clauses) + Managing Committee Certification & Sign-off Block (dual columns for Treasurer and Secretary/Chairman).
  - Generated identical copies to root `Weekend_Ville_AGM_Audit_Validation_Report.pdf`, WhatsApp staging folder `data/staging/whatsapp/`, and artifact folder.


