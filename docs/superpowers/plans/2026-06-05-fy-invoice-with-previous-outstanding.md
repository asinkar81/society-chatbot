# FY-based Invoice with Previous Outstanding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FY-based invoice generation with FY/Custom toggle in UI, and include Previous Outstanding (ledger balance as of invoice date) in the invoice line items table.

**Architecture:** Four changes touch five locations: invoice PDF template (restructure table), 3 orchestrator agent tools (compute previous_outstanding), 1 main.py helper (regenerate), and the Streamlit UI (FY toggle).

**Tech Stack:** Python, Streamlit, reportlab, openpyxl

---
### Task 1: Invoice PDF Template — restructure line items table

**Files:**
- Modify: `tools/pdf_generator.py:63-332`

- [ ] **Step 1: Update `create_simple_invoice_pdf` to accept new fields**

Change function signature and add `previous_outstanding` + `total_amount_due` handling.

Replace the line items table loop and total/outstanding sections. New table structure:

```
Repair & Maintenance Fund @ ₹X/month × N months    X.XX
Service Charges @ ₹X/month × N months               X.XX
Sinking Fund @ ₹X/month × N months                  X.XX
Total                                                X.XX    ← NEW subtotal
Previous Outstanding                                 X.XX    ← NEW line
Interest Penalty Charges                             X.XX
Total Amount Due                                     X.XX    ← NEW final total
```

Remove the "Payment Received Till Date" line and the old `outstanding_balance` rendering.

- [ ] **Step 2: Remove old outstanding balance section**

Find: `Outstanding Balance: ₹ {outstanding_balance}` at existing line 178. Replace with computing `amount_in_words` from `total_amount_due`.

- [ ] **Step 3: Update `invoice_data` dict handling**

Ensure the function reads these keys from `invoice_data`:
- `previous_outstanding` (float, new)
- `total_amount_due` (float, new — = line_items_total + previous_outstanding + interest)

If `previous_outstanding` is not present (backward compat with old invoices during regen), default to 0 and compute `total_amount_due` = `total_amount` (existing).

- [ ] **Step 4: Run test to verify PDF generator still works**

Run: `python -c "from tools.pdf_generator import create_simple_invoice_pdf; print('import ok')"`
Expected: no import errors

- [ ] **Step 5: Commit**

```bash
git add tools/pdf_generator.py
git commit -m "feat: restructure invoice table with Previous Outstanding and Total Amount Due"
```

### Task 2: `generate_invoice` tool — add previous outstanding

**Files:**
- Modify: `agents/orchestrator_agent.py:787-918`

- [ ] **Step 1: Add previous_outstanding computation**

After line 858 (where ledger and invoice_date_input are available), add:

```python
from utils.converters import compute_outstanding_as_of
prev_outstanding = -compute_outstanding_as_of(ledger, invoice_date_input)
```

`compute_outstanding_as_of` returns `credits - debits`. Negating gives `debits - credits` (positive = owes).

- [ ] **Step 2: Update line_items — remove Payment Received**

Remove lines 875-876 (`if payment_received > 0: line_items[...`).

- [ ] **Step 3: Add new fields to invoice_data dict**

After `total = gross_total - payment_received` (line 863), compute:

```python
total_line_items = repair_amount + service_amount + sinking_amount
total_amount_due = total_line_items + prev_outstanding + pending_interest
```

Update `invoice_data` dict: remove `"outstanding_balance"`, remove `"payment_received_till_date"`, add:
```python
"total_line_items": total_line_items,
"previous_outstanding": prev_outstanding,
"interest_penalty": pending_interest,
"total_amount_due": total_amount_due,
"amount_in_words": number_to_words_inr(total_amount_due),
```

- [ ] **Step 4: Update ledger debit amount**

The debit entry should now be `total_amount_due` instead of `gross_total`.

Change line 911: `"Debit": gross_total` → `"Debit": total_amount_due`

- [ ] **Step 5: Commit**

```bash
git add agents/orchestrator_agent.py
git commit -m "feat: add previous outstanding to generate_invoice tool"
```

### Task 3: `batch_generate_invoices` tool — add previous outstanding

**Files:**
- Modify: `agents/orchestrator_agent.py:1121-1256`

- [ ] **Step 1: Add previous_outstanding computation**

Inside the per-member loop, after `payment_history = ...` (line 1195), add:

```python
from utils.converters import compute_outstanding_as_of
prev_outstanding = -compute_outstanding_as_of(member_ledger, invoice_date_input)
```

- [ ] **Step 2: Update line_items — remove Payment Received**

Remove lines 1209-1210 (`if payment_received > 0: line_items[...`).

- [ ] **Step 3: Add new fields to invoice_data dict**

After `total = gross_total - payment_received` (line 1198), compute:

```python
total_line_items = repair_amount + service_amount + sinking_amount
total_amount_due = total_line_items + prev_outstanding + pending_interest
```

Update `invoice_data` dict (lines 1212-1229): remove `"outstanding_balance"`, remove `"payment_received_till_date"`, add the new fields from Task 2 Step 3.

- [ ] **Step 4: Update ledger debit amount**

Change line 1246: `"Debit": gross_total` → `"Debit": total_amount_due`

- [ ] **Step 5: Commit**

```bash
git add agents/orchestrator_agent.py
git commit -m "feat: add previous outstanding to batch_generate_invoices tool"
```

### Task 4: `regenerate_invoice` tool (orchestrator_agent)

**Files:**
- Modify: `agents/orchestrator_agent.py:920-1080`

- [ ] **Step 1: Exclude current invoice entry and compute previous_outstanding**

After line 938 (`ledger = ...`), before the line 939 `entry = next(...)`:

```python
current_vch = vch_no
```

After computing payment_received (before line 996 `total = ...`), add:

```python
from utils.converters import compute_outstanding_as_of
# Exclude current invoice entry from outstanding calculation
filtered_ledger = [e for e in ledger if int(e.get("Vch_No", 0)) != current_vch]
prev_outstanding = -compute_outstanding_as_of(filtered_ledger, date)
```

- [ ] **Step 2: Update line_items — remove Payment Received**

Remove lines 1073-1074 (`if payment_received > 0: invoice_data["line_items"]...`).

- [ ] **Step 3: Add new fields to invoice_data dict**

After `total = gross_total - payment_received` (line 996), compute:

```python
total_line_items = repair_amount + service_amount + sinking_amount
total_amount_due = total_line_items + prev_outstanding + pending_interest
```

Update `invoice_data` dict (lines 1050-1072): remove `"outstanding_balance"`, remove `"payment_received_till_date"`, add new fields.

- [ ] **Step 4: Update ledger debit amount**

Change line 1024: `"Debit": gross_total` → `"Debit": total_amount_due`

- [ ] **Step 5: Commit**

```bash
git add agents/orchestrator_agent.py
git commit -m "feat: add previous outstanding to regenerate_invoice tool"
```

### Task 5: UI-level `regenerate_invoice` helper (main.py)

**Files:**
- Modify: `main.py:396-511`

- [ ] **Step 1: Exclude current invoice entry and compute previous_outstanding**

After `ledger = dp.get_member_ledger(member_id)` (line 433), add:

```python
current_vch_no = vch_no
filtered_ledger = [e for e in ledger if int(e.get("Vch_No", 0)) != current_vch_no]
from utils.converters import compute_outstanding_as_of
prev_outstanding = -compute_outstanding_as_of(filtered_ledger, invoice_date)
```

- [ ] **Step 2: Update line_items — remove Payment Received**

Remove lines 465-466 (`if payment_received > 0: ...`).

- [ ] **Step 3: Update invoice_data dict**

Add new fields and remove old ones (similar to Task 2 Step 3). Update lines 471-488.

- [ ] **Step 4: Update ledger debit amount**

Change line 505: `"Debit": gross_total` → `"Debit": total_amount_due`

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: add previous outstanding to UI regenerate_invoice helper"
```

### Task 6: UI — FY toggle in Invoices tab

**Files:**
- Modify: `main.py:1118-1174` (Generate Invoices section)

- [ ] **Step 1: Add radio toggle for FY vs Custom Dates**

Before the existing date inputs, add:

```python
inv_mode = st.radio("Invoice Mode", ["Financial Year", "Custom Dates"],
                     horizontal=True, key="inv_mode")
```

- [ ] **Step 2: Add FY dropdown (shown when FY mode selected)**

When `inv_mode == "Financial Year"`:

```python
# Collect FYs from ledger
all_ledger = dp.get_all_ledger_entries()
available_fys = sorted(set(
    get_fy_from_date(str(e.get("Date", "")))
    for e in all_ledger if e.get("Date")
), reverse=True)
current_fy = get_fy_string()
if current_fy not in available_fys:
    available_fys.insert(0, current_fy)
selected_fy = st.selectbox("Select Financial Year", available_fys, key="inv_fy")
```

Auto-compute dates:
```python
fy_parts = selected_fy.split("-")
fy_start = 2000 + int(fy_parts[0])
from_date = f"01-04-{fy_start}"
to_date = f"31-03-{fy_start + 1}"
inv_date = f"01-04-{fy_start}"
```

- [ ] **Step 3: Show/hide date inputs based on mode**

When `inv_mode == "Custom Dates"`: show existing date inputs. When FY mode: hide them (the dates are computed from FY).

Wrap existing date inputs (from_d, to_d, inv_d, lines 1118-1132) in `if inv_mode == "Custom Dates":`.

- [ ] **Step 4: Pass correct params to backend**

Update the params dict (around lines 1137-1142) to pass `fy` when in FY mode, and date values when in Custom Dates mode:

```python
params = {}
if inv_mode == "Financial Year":
    params["fy"] = selected_fy
    params["invoice_date"] = inv_date
else:
    if from_d.strip(): params["from_date"] = from_d.strip()
    if to_d.strip(): params["to_date"] = to_d.strip()
    if inv_d.strip(): params["invoice_date"] = inv_d.strip()
if selected_plots: params["plots"] = selected_plots
```

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: add FY/Custom toggle to invoice generation UI"
```

### Task 7: Run all tests

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 129+ passed

- [ ] **Step 2: Verify no regressions**

If any failures, identify whether they predate our changes. Fix any that our code broke.

### Task 8: Manual verification

- [ ] **Step 1: Test invoice generation via UI**

Start the app, open Invoices tab, select "Financial Year" mode, pick an FY, click Generate. Verify the PDF shows the new table structure.

- [ ] **Step 2: Test Custom Dates mode still works**

Switch to Custom Dates, enter dates, generate. Verify it works and PDF shows the new structure.

- [ ] **Step 3: Test regenerate**

Find an existing invoice, regenerate it. Verify PDF includes Previous Outstanding.
