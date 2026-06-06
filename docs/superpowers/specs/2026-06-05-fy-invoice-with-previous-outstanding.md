# FY-based Invoice Generation with Previous Outstanding

## Motivation
The current invoice generator requires manual date entry (From Date, To Date, Invoice Date). Users need a simpler FY-based workflow and invoices that reflect the member's full outstanding balance including unpaid amounts from prior periods.

## Changes

### 1. UI — FY / Custom Date toggle (main.py)
- Radio button: "Financial Year" | "Custom Dates"
- "Financial Year": shows FY dropdown (populated from ledger), auto-fills From Date = 1-Apr-{fy_start}, To Date = 31-Mar-{fy_end}, Invoice Date = 1-Apr-{fy_start}
- "Custom Dates": existing date inputs
- Both modes pass the same parameters to the backend

### 2. Invoice PDF Template (pdf_generator.py)
**New line items table order:**
1. Repair & Maintenance Fund
2. Service Charges
3. Sinking Fund
4. **Total** (1+2+3)
5. **Previous Outstanding** (ledger balance as of invoice date — positive = owed, negative = credit)
6. Interest Penalty Charges
7. **Total Amount Due** (4 + 5 + 6)

"Payment Received Till Date" line is removed from line items. Payment History remains as a separate table below.

### 3. Previous Outstanding Computation
- `previous_outstanding = debits - credits` from ledger entries with Date <= invoice_date
- Positive = member owes (shown as "Add: Previous Outstanding")
- Negative = member overpaid (shown as "Less: Credit Balance B/F")
- For **regen**: exclude the current invoice entry from the ledger before computing

### 4. Ledger Debit Entry
Unchanged — the debit remains `gross_total` (current period charges only). Previous outstanding was already recorded in prior ledger entries. The invoice PDF is informational, showing the full cumulative picture.

### 5. Files to Update
| File | Changes |
|------|---------|
| `tools/pdf_generator.py` | Restructure table, accept `previous_outstanding` + `total_amount_due` |
| `agents/orchestrator_agent.py` (generate_invoice) | Compute previous_outstanding, pass to PDF, update invoice_data |
| `agents/orchestrator_agent.py` (batch_generate_invoices) | Same |
| `agents/orchestrator_agent.py` (regenerate_invoice) | Same, but exclude current invoice entry |
| `main.py` (regenerate_invoice helper) | Same |
| `main.py` (Invoices tab UI) | Add FY/Custom toggle, FY dropdown |

### 6. Tests
- Previous outstanding computation with various ledger states
- FY invoice generation via API
- Regenerate preserves previous outstanding correctly
