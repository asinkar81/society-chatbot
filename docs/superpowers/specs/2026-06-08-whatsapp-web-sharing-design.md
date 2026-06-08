# WhatsApp Web Sharing

**Date:** 2026-06-08
**Status:** Draft

## Problem

Users share invoices and receipts with society members via WhatsApp manually today. The process is cumbersome:
- Receipts and invoices are scattered across different folders
- The Summary table (balance, demand, payments, outstanding) is only available via email
- Member phone numbers must be typed manually to launch a WhatsApp chat
- No single-click or streamlined workflow exists

## Goal

Provide a semi-automated WhatsApp sharing experience that:
1. Builds a rich text Summary message (like email templates but as plain text, not HTML)
2. Opens `wa.me` link with pre-filled message so the user clicks Send
3. Collects all relevant PDFs (receipts + invoices) in one place for drag-drop
4. Works both per-row (single receipt/invoice) and in bulk (consolidated FY sharing)

## Non-Goals

- Full automated sending (no WhatsApp Cloud/Business API — user explicitly wants manual send via wa.me)
- WhatsApp Web automation (Selenium/Puppeteer)
- Image-based summary (text only)
- Tracking/history beyond existing `log_communication()` infrastructure

## Architecture

### New Module: `utils/whatsapp.py`

Single module with pure functions:

```python
def build_wa_message(template_type: str, member: dict, summary: Optional[dict],
                     entries: Optional[List[dict]], pdf_names: List[str]) -> str
    """Build formatted WhatsApp message text.
    
    Message format:
        Weekend Ville Society
        Plot {plot} — {name}
        FY {fy}

        Summary:
        Balance carried forward: ₹X
        New Invoice Demand: ₹X
        Payments Received: ₹X
        Total Outstanding as of {date}: ₹X

        Attached Documents:
        1. {filename}
        2. {filename}
    """

def build_wa_link(phone: str, text: str) -> str:
    """Build https://wa.me/91XXXXXXXXXX?text=URL_ENCODED_MSG"""

def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard using pyperclip or pbcopy.
    Returns True on success, False if clipboard not available."""
```

### Summary Text Formatting

The summary dict (identical to email's `_summary_html` input) is formatted as plain text:

| Entry | Format |
|---|---|
| Receipt | `Dear {name}, a payment of ₹{amount} has been received for Plot {plot} at Weekend Ville Society. Details: {receipt_id}, {date}, UTR: {txn_id}\n\nSummary:\n...\n\nAttached Documents:\n1. {pdf_name}` |
| Invoice | `Dear {name}, your invoice for Plot {plot} at Weekend Ville Society is ready.\n\nSummary:\n...\n\nAttached Documents:\n1. {pdf_name}` |
| Statement | `Dear {name}, your statement for Plot {plot} at Weekend Ville Society, FY {fy}.\n\nSummary:\n...\n\nAttached Documents:\n1-{n}. {pdf_names}` |
| Reminder | `Dear {name}, a gentle reminder for outstanding dues for Plot {plot} at Weekend Ville Society.\n\nSummary:\n...\n\nAttached Documents:\n1-{n}. {pdf_names}` |

### wa.me Link Generation

- Phone number taken from member's `WhatsApp_No` field
- Link format: `https://wa.me/{country_code}{phone}?text={url_encoded_message}`
- Country code defaults to `91` (India)
- Message is URL-encoded using `urllib.parse.quote`
- Link opens in same tab (or can be configured to open new tab via target attribute in Streamlit)

### Clipboard Fallback

- Primary: Click opens wa.me link with pre-filled message
- Secondary: Button also copies plain message to clipboard via `pyperclip` (preferred) or `pbcopy` (macOS) fallback
- User can paste into any chat if wa.me doesn't work for some reason

## UI Changes

### Per-Row Buttons (Receipts Tab)

- Add `💬` button per row alongside existing `📧` button
- Click → builds single-entry message → copies to clipboard → opens wa.me link
- Logs communication with `template_type="whatsapp"`

### Per-Row Buttons (Invoices Tab)

- Add `💬` button per row alongside existing `📧` button
- Click → builds single-entry message with summary → copies to clipboard → opens wa.me link
- Logs communication with `template_type="whatsapp"`

### Settings > Email > Share Documents (Consolidated)

- Existing "Send" button becomes "📧 Send via Email"
- New "💬 Send via WhatsApp" button alongside it
- Document filtering subsection appears when a recipient is selected:
  - "📄 Documents to share" heading
  - Two checkboxes: ☐ Include Receipts, ☐ Include Invoices (both checked by default for statement/reminder)
  - Clicking "💬 Send via WhatsApp" shows the formatted message in a `st.text_area` (editable), a "📋 Copy Message" button, and an "🔗 Open WhatsApp" link (wa.me)
  - Shows list of PDFs to attach with their file paths

### Document Collector

When user clicks "Send via WhatsApp" in bulk mode:
1. Collects all matching PDFs into a temporary staging folder: `data/staging/whatsapp/{plot}_{timestamp}/`
2. Copies PDFs into this folder (not moves — originals stay)
3. Provides a "📂 Open Staging Folder" button that runs `open {staging_path}` (macOS) or `xdg-open`
4. User drags files from staging folder into WhatsApp Web

## Data Flow

```
User clicks 💬
    │
    ├─ Get member from data_provider.get_member(mid)
    ├─ Get WhatsApp_No (validate: non-empty, digits only)
    ├─ Get PDF paths via _get_pdf_path() or from computed paths
    ├─ Compute summary dict (same as email: outstanding, demand, payments, due)
    ├─ Call whatsapp.build_wa_message(template_type, member, summary, entries, pdf_names)
    ├─ Call whatsapp.copy_to_clipboard(message)
    ├─ Call whatsapp.build_wa_link(phone, message)
    ├─ Open wa.me link (st.markdown with target="_self" or st.link_button)
    ├─ Log communication via data_provider.log_communication(...)
    └─ Show success/info message
```

## Error Handling

| Scenario | Behavior |
|---|---|
| No WhatsApp_No for member | Show "No WhatsApp number" warning, disable button |
| Invalid phone number | Show validation error |
| No PDFs found | Include "No documents attached" in message |
| Clipboard unavailable | Still open wa.me link (message text is pre-filled there) |
| Summary computation fails | Fall back to simpler message without summary |

## Testing

- Unit tests for `build_wa_message`: verify message format for all 4 templates
- Unit tests for `build_wa_link`: verify URL encoding, phone format
- Integration test: clicking 💬 opens expected URL
- Integration test: communication logged with correct template_type

## Files Changed

| File | Change |
|---|---|
| `utils/whatsapp.py` | **New** — message builder + wa.me link + clipboard |
| `main.py` | Add 💬 buttons in Receipts/Invoices tabs, WhatsApp button in Share Documents |
| `data_providers/local_excel_provider.py` | No changes needed (communication log already generic) |
| `data_providers/base_provider.py` | No changes needed |
| `config.py` | Add `STAGING_DIR = DATA_DIR / "staging"` + ensure it's created |
| `utils/email_sender.py` | No changes |
