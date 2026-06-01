# Plan: Agentic Society Management Chatbot (REVISED - MVP with Local Storage)

**TL;DR**: Build a conversational chatbot interface in Streamlit where users interact with agents through natural language prompts. Agents handle invoice generation, receipt processing, and ledger management using local Excel files for data storage. Architecture designed with abstraction layers to seamlessly migrate to Google Drive/Sheets later without code restructuring.

---

## Steps

### Phase 1: Infrastructure & Setup
1. Initialize Python project with local file structure (data/, templates/, invoices/, receipts/, ledgers/ directories)
2. Configure LangChain + Claude (Anthropic API key)
3. Create Streamlit app skeleton with simple admin login (password in .env)
4. Build abstraction layer for data persistence:
   - `DataProvider` interface (methods: read_members, write_ledger, etc.)
   - `LocalExcelDataProvider` implementation (uses openpyxl/pandas)
   - Designed so future `GoogleSheetsDataProvider` can be swapped in without changing agent code
5. Build abstraction layer for file storage:
   - `FileStorage` interface (upload, download, list_files methods)
   - `LocalFileStorage` implementation (saves to local directories)
   - Designed for future `GoogleDriveStorage` swap-in
6. Create helper modules: Excel reader/writer, file operations, number-to-words converter (INR), PDF generator

### Phase 2: Data Schema & Local Excel Setup
7. Design Excel workbook structure (`society_data.xlsx`):
   - **Sheet 1: Members** → ID, Plot_No, Plot_Owner_Name, Email, Phone, Current_Outstanding, Pending_Interest
   - **Sheet 2: Ledger** → Member_ID, Date, Particulars, Vch_Type, Vch_No, Debit, Credit, Description
   - **Sheet 3: Settings** → Financial Year, Invoice Rates (Repair, Service, Sinking), Auto-entry flag for April 1st
8. Create template Excel files locally (`templates/invoice_template.xlsx`, `templates/receipt_template.xlsx`)
   - Store placeholder patterns (e.g., {{PLOT_OWNER_NAME}}, {{INVOICE_NO}})
9. Initialize file directories:
   - `data/society_data.xlsx` — Master data
   - `data/templates/` — Excel templates
   - `data/invoices/` — Generated invoices (organized by FY)
   - `data/receipts/` — Generated receipts (organized by FY)
   - `data/ledgers/` — Exported ledger reports

### Phase 3: Conversational Chatbot Interface
10. Design chatbot conversation flow in Streamlit:
    - Chat history display (showing past conversations and actions)
    - Input box at bottom for user queries (natural language)
    - System processes queries, triggers agents, displays results in chat
11. Implement chat context management:
    - Store conversation history in session state
    - Agents can ask follow-up questions (e.g., "Which member?" → user responds)
    - Multi-turn conversation support (user refines prompts, agents clarify)
12. Example conversation flows:
    - User: "Generate invoices for FY 2026-27"
    - Agent: "I'll generate invoices for all 44 members. Shall I proceed?" (confirmation prompt)
    - User: "Yes"
    - Agent: Generates, shows progress, reports completion
    
    - User: "I have a payment screenshot for Plot 10"
    - Agent: "Please upload the screenshot"
    - User: (uploads file)
    - Agent: Extracts details via vision, asks "Amount ₹X on Y date. Correct?" 
    - User: "Yes" / "No, it's ₹Z" (correction)
    - Agent: Generates receipt, updates ledger, confirms

### Phase 4: Agent Framework Design & Implementation
13. Create LangChain agent base class with:
    - Tools for data operations (uses `DataProvider` abstraction)
    - Tools for file operations (uses `FileStorage` abstraction)
    - Conversation memory (track context across turns within session)
    - Error handling with user-friendly fallbacks
14. **Invoice Generation Agent**:
    - Understands prompts: "Generate invoices for FY 2026-27", "Create invoices for all members", etc.
    - Tool: Fetch all 44 members from Excel (via DataProvider)
    - Tool: Check if April 1st entry exists; if not, ask user to trigger auto-entry
    - Tool: Load invoice template from local `data/templates/`
    - Tool: For each member, calculate line items (Repair, Service, Sinking, Interest, Payments)
    - Tool: Render PDF with populated values
    - Tool: Save invoices to `data/invoices/{FY}/` (via FileStorage)
    - Tool: Update ledger in Excel with invoice records (optional)
    - Provides progress updates and confirmation
15. **Receipt Generation Agent**:
    - Understands prompts: "Process payment for Plot 5", "Generate receipt", etc.
    - Tool: Accept file upload from Streamlit
    - Tool: Use Claude's vision to extract amount, date, transaction ID from screenshot
    - Tool: Ask user to confirm extracted details (multi-turn conversation)
    - Tool: Fetch member info from Excel
    - Tool: Load receipt template from `data/templates/`
    - Tool: Render PDF receipt with confirmed data
    - Tool: Save receipt to `data/receipts/{FY}/{receipt_id}/` (via FileStorage)
    - Tool: Update ledger in Excel (new payment entry, recalculate balance)
    - Tool: Update member's Current_Outstanding in Members sheet
16. **Ledger Management Agent**:
    - Understands prompts: "Show ledger for Plot 1", "View member account", "Export ledger", etc.
    - Tool: Fetch member ledger from Excel
    - Tool: Display formatted transaction history in chat
    - Tool: Support manual entry (if OCR failed): "Add payment of ₹X for Plot Y dated Z"
    - Tool: Validate balance consistency
    - Tool: Export ledger to CSV/PDF for user download
17. **Admin Agent** (for system tasks):
    - Understands prompts: "Set April 1st entry", "Update rates", "Add member", etc.
    - Tool: Modify Settings sheet (rates, auto-entry flag)
    - Tool: Add/edit members in Members sheet
    - Tool: Trigger April 1st auto-entry logic (add ₹12,000 to all members)
    - Tool: Validate data integrity
18. **Router/Dispatcher Agent**:
    - Listens to user prompts
    - Routes to appropriate agent (Invoice, Receipt, Ledger, Admin, or asks clarifying question)
    - Manages conversation context between agents

### Phase 5: Streamlit UI Components
19. Build main Streamlit app structure:
    - Admin login (username/password from .env)
    - Sidebar: Navigation (Dashboard, Chat, Settings, Help)
    - Main area: Chat interface
20. Dashboard page (optional, accessed from sidebar):
    - Summary stats (total members, pending invoices, total outstanding, recent receipts)
    - Quick-action buttons (Generate Invoices, Process Payment, View Ledger)
21. Chat page (primary interface):
    - Chat history display (scrollable, formatted messages)
    - Input field with send button
    - Visual indicators (agent thinking, processing, complete)
    - Error messages and confirmations
22. Settings page (for admin):
    - Upload new Excel templates
    - Configure rates (Repair, Service, Sinking, Fiscal Year start date)
    - Add/remove/edit members (table view)
    - Trigger April 1st auto-entry
23. Help page:
    - Example prompts
    - Conversation flow diagrams
    - FAQ

### Phase 6: April 1st Automation
24. Implement April 1st auto-entry logic (admin-triggered, not background job):
    - Admin page has button: "Trigger Annual Maintenance Entry (April 1st)"
    - System checks current fiscal year
    - For each of 44 members, adds ₹12,000 entry to ledger
    - Validates no duplicates (checks if entry already exists)
    - Reports success/failures in chat
    - Alternative: System auto-detects April 1st and notifies admin via chat ("Today is April 1st. Ready to create annual entries? Reply 'yes'")

### Phase 7: Data Persistence & Abstraction
25. Implement `DataProvider` abstract class:
    - Methods: `get_all_members()`, `get_member(id)`, `update_member(data)`, `add_ledger_entry()`, `get_ledger(member_id)`, `get_settings()`, `update_settings(data)`
    - `LocalExcelDataProvider`: Implements with openpyxl/pandas
    - All agents use DataProvider, not direct Excel calls
26. Implement `FileStorage` abstract class:
    - Methods: `upload(file_path, destination)`, `download(file_id)`, `list_files(folder)`, `delete(file_id)`
    - `LocalFileStorage`: Implements with local filesystem
    - All agents use FileStorage, not direct file calls
27. Design configuration layer to switch providers:
    - `config.py`: `DATA_PROVIDER = "local"` or `"google"` (future)
    - Dependency injection: Agents receive provider at init time

### Phase 8: Verification & Testing
28. Manual testing:
    - Admin login flow
    - Chat interface responsiveness
    - Invoice generation via chat prompt (single member, then bulk)
    - Receipt OCR and generation via chat
    - Ledger queries and updates
    - File creation in local directories
    - April 1st auto-entry trigger
    - Member management (add/edit)
29. Multi-turn conversation testing:
    - User asks ambiguous prompt → agent asks clarifying question → user responds → agent acts
    - Example: User says "Generate invoices" → Agent: "For which FY?" → User: "2026-27" → Agent proceeds
30. Edge cases:
    - Corrupted Excel file (graceful error handling)
    - Missing template file (clear error message + guidance)
    - OCR failure (fallback to manual entry prompt)
    - Duplicate April 1st entry (skip if already exists)
    - File permission issues (error handling for Windows/Mac)

---

## Project Structure

```
society-chatbot/
├── main.py                           # Streamlit entry point
├── requirements.txt
├── .env.example                      # ADMIN_USERNAME, ADMIN_PASSWORD, ANTHROPIC_API_KEY
├── config.py                         # App settings, provider selection
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py                 # LangChain agent base class
│   ├── router_agent.py               # Dispatches to specific agents
│   ├── invoice_agent.py              # Invoice generation
│   ├── receipt_agent.py              # Receipt + OCR
│   ├── ledger_agent.py               # Ledger queries/updates
│   └── admin_agent.py                # Settings, member management
│
├── data_providers/
│   ├── __init__.py
│   ├── base_provider.py              # Abstract DataProvider class
│   ├── local_excel_provider.py       # LocalExcelDataProvider implementation
│   └── google_sheets_provider.py     # (Future) GoogleSheetsDataProvider stub
│
├── file_storage/
│   ├── __init__.py
│   ├── base_storage.py               # Abstract FileStorage class
│   ├── local_storage.py              # LocalFileStorage implementation
│   └── google_drive_storage.py       # (Future) GoogleDriveStorage stub
│
├── tools/
│   ├── __init__.py
│   ├── excel_processor.py            # Read/write Excel
│   ├── pdf_generator.py              # Template → PDF conversion
│   ├── ocr_processor.py              # Claude vision for screenshots
│   └── converters.py                 # Number-to-words, date formatting
│
├── utils/
│   ├── __init__.py
│   ├── auth.py                       # Admin login
│   ├── chat_manager.py               # Chat history, context
│   └── helpers.py                    # Common utilities
│
├── ui/
│   ├── __init__.py
│   ├── chat_interface.py             # Chat UI components
│   ├── dashboard.py                  # Dashboard page
│   ├── settings.py                   # Settings page
│   └── help.py                       # Help/examples
│
├── data/
│   ├── society_data.xlsx             # Master data file
│   ├── templates/
│   │   ├── invoice_template.xlsx
│   │   └── receipt_template.xlsx
│   ├── invoices/
│   │   └── 2026-27/
│   ├── receipts/
│   │   └── 2026-27/
│   └── ledgers/                      # Exported reports
│
├── tests/
│   └── test_agents.py
│
└── README.md
```

---

## Key Tech Stack

- LangChain: Agent framework with Claude 3.5 Haiku (tool-calling)
- Claude 3.5 Sonnet for vision (payment OCR)
- Streamlit: UI & chat interface
- openpyxl / pandas: Excel read/write
- reportlab / python-docx: PDF generation
- python-dateutil: Date handling
- num2words: INR conversion

---

## Data Schema

**Local Excel Structure** (`data/society_data.xlsx`):

*Sheet: Members*
```
ID | Plot_No | Plot_Owner_Name | Email | Phone | Current_Outstanding | Pending_Interest
1  | 01      | Mrs. Asha Ganpat Dalvi | ... | ... | 29000 | 0
2  | 02      | ... | ... | ... | ... | ...
```

*Sheet: Ledger*
```
Member_ID | Date | Particulars | Vch_Type | Vch_No | Debit | Credit | Description
1 | 1-4-2026 | Opening Balance | | | 17000 | | 
1 | 1-4-2026 | To Member Contribution | Journal | 36 | 12000 | | YEARLY MEMBER CONTRIBUTION FOR FY 2026-2027
1 | 15-5-2026 | By Payment Received | Journal | 37 | | 53000 | Receipt 25-26-001
```

*Sheet: Settings*
```
Key | Value
Current_FY | 2026-27
Repair_Fund_Rate | 100.00
Service_Charges_Rate | 885.00
Sinking_Fund_Rate | 15.00
April_1st_Auto_Entry_Amount | 12000
```

---

## Conversation Examples

```
User: "Generate invoices for all members"
Agent: "I'll generate invoices for FY 2026-27 for all 44 members. Proceed? (Yes/No)"
User: "Yes"
Agent: "Starting invoice generation... (1/44) (2/44)... Complete! 44 invoices saved to data/invoices/2026-27/"

User: "I have a payment screenshot"
Agent: "Please upload the payment screenshot."
User: (uploads file)
Agent: "I see a payment of ₹53,000 dated 15-May-2026. Which member is this for? (Enter Plot No. or Name)"
User: "Plot 01"
Agent: "Confirmed. Generating receipt 25-26-001 and updating ledger for Plot 01..."
Agent: "Done! Receipt saved. Plot 01's outstanding balance: ₹17,000"

User: "Show me the ledger for Plot 01"
Agent: (displays full transaction history)
Agent: "Opening Balance: ₹17,000 | Invoices: ₹53,000 | Payments: ₹53,000 | Current Outstanding: ₹17,000"
```

---

## Decisions

- **MVP Storage**: Local Excel + filesystem (no Google APIs)
- **Architecture**: Abstraction layers (DataProvider, FileStorage) for future scalability
- **Interface**: Chat-based (conversational) for intuitive interaction
- **Data Format**: Excel files (familiar to end users, easy to backup/share)
- **Confirmation Prompts**: Multi-turn conversations for user approvals
- **April 1st Entry**: Admin-triggered (not background job) via chat prompt
- **Templates**: Excel-based (local), same structure as Google Sheets (for future migration)
- **File Organization**: FY-based folders (data/invoices/2026-27/, data/receipts/2026-27/)
- **OCR Fallback**: Manual entry if vision fails
- **Session State**: Streamlit session_state for chat history and conversation context

---

## Verification Checklist

- [ ] Data Provider Abstraction: Verify agents use only DataProvider interface (no direct Excel calls)
- [ ] File Storage Abstraction: Verify agents use only FileStorage interface (no direct filesystem calls)
- [ ] Local File Operations: Create society_data.xlsx with sample members, generate invoices, receipts, verify files
- [ ] Chat Interface: Login → Chat page loads → Chat with agents
- [ ] Multi-turn Conversation: Ambiguous prompt → Agent asks clarifying question → User responds → Agent acts
- [ ] April 1st Auto-Entry: Admin Settings → Click "Trigger Annual Entry" → Verify all 44 members get ₹12,000
- [ ] Migration Path: Swap LocalExcelDataProvider with GoogleSheetsDataProvider stub, test same flows
