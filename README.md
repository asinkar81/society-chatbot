# Society Management Agentic Chatbot

A conversational AI chatbot built with Streamlit, LangChain, and Claude to automate society management tasks including invoice generation, receipt processing, and ledger management.

## Features

🤖 **Multi-Agent System**
- Invoice Generation Agent: Generates yearly invoices with calculated maintenance charges
- Receipt Generation Agent: Processes payment screenshots with OCR and generates receipts
- Ledger Management Agent: Maintains member accounts and transaction history
- Admin Agent: System settings, member management, and April 1st auto-entries

💬 **Conversational Interface**
- Natural language chat with agents
- Multi-turn conversations with clarifications
- Real-time processing and feedback

📄 **Document Management**
- PDF invoice generation from templates
- Receipt creation with transaction details
- CSV ledger exports
- Local file organization by fiscal year

📷 **Payment Processing**
- Vision-based OCR for payment screenshots
- Automatic amount and date extraction
- Transaction validation and confirmation

💾 **Data Management**
- Local Excel-based storage (MVP)
- Abstraction layers for future Google Sheets/Drive integration
- Complete ledger tracking with opening/closing balances
- Member database with outstanding balance calculation

🔐 **Security**
- Admin login authentication
- Session-based access control
- Secure data storage

## Project Structure

```
society-chatbot/
├── main.py                    # Streamlit application entry point
├── config.py                  # Configuration and settings
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variables template
├── PROJECT_PLAN.md            # Detailed implementation plan
│
├── agents/                    # Agent implementations
│   ├── base_agent.py          # Base agent class with LangChain integration
│   ├── invoice_agent.py       # Invoice generation agent
│   ├── receipt_agent.py       # Receipt and payment processing agent
│   ├── ledger_agent.py        # Ledger management agent
│   └── admin_agent.py         # Administrative tasks agent
│
├── data_providers/            # Data persistence abstraction
│   ├── base_provider.py       # Abstract DataProvider interface
│   ├── local_excel_provider.py # Local Excel implementation
│   └── google_sheets_provider.py # Future: Google Sheets stub
│
├── file_storage/              # File storage abstraction
│   ├── base_storage.py        # Abstract FileStorage interface
│   ├── local_storage.py       # Local filesystem implementation
│   └── google_drive_storage.py # Future: Google Drive stub
│
├── tools/                     # Tool implementations
│   ├── excel_processor.py     # Excel template handling
│   ├── pdf_generator.py       # PDF generation from templates
│   ├── ocr_processor.py       # Vision-based OCR for screenshots
│   └── converters.py          # Utility converters (number-to-words, date formatting)
│
├── utils/                     # Utilities
│   ├── auth.py                # Authentication and login
│   ├── chat_manager.py        # Chat history and context management
│   └── helpers.py             # Common utility functions
│
├── ui/                        # UI components (placeholder)
│
├── data/                      # Data storage directory
│   ├── society_data.xlsx      # Excel workbook with Members, Ledger, Settings sheets
│   ├── templates/             # Invoice and receipt templates
│   ├── invoices/              # Generated invoices organized by FY
│   ├── receipts/              # Generated receipts organized by FY
│   └── ledgers/               # Exported ledger reports
│
└── tests/                     # Test suite
```

## Quick Start

### 1. Install Dependencies

```bash
cd /Users/ashutoshsinkar/society-chatbot
pip install -r requirements.txt
```

### 2. Setup Environment

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxx
ADMIN_USERNAME=admin
ADMIN_PASSWORD=password123
```

### 3. Run the Application

```bash
streamlit run main.py
```

The app will open at `http://localhost:8501`

### 4. Login

- Username: `admin`
- Password: `password123`

## Usage Examples

### Generate Invoices
```
User: "Generate invoices for FY 2026-27"
Agent: "I'll generate invoices for all 44 members. Calculating amounts..."
Agent: "Invoice generation complete: 44 invoices saved to data/invoices/2026-27/"
```

### Process Payment
```
User: "I have a payment screenshot"
Agent: "Please upload the payment screenshot"
User: (uploads file)
Agent: "Extracted: ₹53,000 on 15-May-2026. Which member? (Plot No)"
User: "Plot 01"
Agent: "Receipt 25-26-001 generated. Outstanding balance: ₹17,000"
```

### View Ledger
```
User: "Show ledger for Plot 01"
Agent: (displays transaction history with opening/closing balances)
```

### Admin Tasks
```
User: "Trigger April 1st entries"
Agent: "Processing ₹12,000 entry for all 44 members..."
Agent: "April 1st entries: 44 added, 0 skipped"
```

## Data Schema

### Members Sheet
- ID: Unique member identifier
- Plot_No: Plot number (01, 02, etc.)
- Plot_Owner_Name: Owner's name
- Email: Email address
- Phone: Phone number
- Current_Outstanding: Outstanding balance
- Pending_Interest: Any interest charges

### Ledger Sheet
- Member_ID: Reference to member
- Date: Transaction date (DD-MM-YYYY)
- Particulars: Transaction description
- Vch_Type: Voucher type (Journal, etc.)
- Vch_No: Voucher number
- Debit: Debit amount
- Credit: Credit amount
- Description: Detailed description

### Settings Sheet
- Current_FY: Financial year (e.g., 2026-27)
- Repair_Fund_Rate: Monthly repair charge
- Service_Charges_Rate: Monthly service charge
- Sinking_Fund_Rate: Monthly sinking fund
- April_1st_Auto_Entry_Amount: Annual contribution (₹12,000)
- Last_Voucher_No: Sequential counter for vouchers

## Architecture Highlights

### Abstraction Layers
- **DataProvider**: Abstract interface for data operations
  - Current: `LocalExcelDataProvider` (reads/writes Excel)
  - Future: `GoogleSheetsDataProvider` (will read/write Google Sheets)
  
- **FileStorage**: Abstract interface for file operations
  - Current: `LocalFileStorage` (saves to local filesystem)
  - Future: `GoogleDriveStorage` (will upload to Google Drive)

### Agent Framework
- Built on **LangChain** with **Claude 3.5 Haiku** (efficient tool-calling)
- **Claude 3.5 Sonnet** for vision tasks (payment OCR)
- Each agent has specialized tools registered
- ReAct pattern for reasoning and acting

### Chat Interface
- **Streamlit** for UI
- Session-based state management
- Chat history tracking
- Multi-turn conversations

## Configuration

Edit `config.py` to customize:

```python
TOTAL_MEMBERS = 44                    # Number of members
AUTO_ENTRY_AMOUNT = 12000             # Annual contribution
INVOICE_DUE_DAYS = 60                 # Invoice due date
INVOICE_PERIOD_MONTHS = 12            # Invoice period

# Invoice rates (per month)
INVOICE_RATES = {
    "repair_maintenance": 100.00,
    "service_charges": 885.00,
    "sinking_fund": 15.00,
}
```

## Future Enhancements

### Phase 2: Google Integration
- Replace `LocalExcelDataProvider` with `GoogleSheetsDataProvider`
- Replace `LocalFileStorage` with `GoogleDriveStorage`
- No agent code changes needed (abstraction layers handle it)

### Phase 3: Advanced Features
- Email notifications for invoices and receipts
- Partial payment tracking
- Automatic penalty calculations
- Payment reminders
- SMS notifications
- Dashboard analytics and reports

### Phase 4: Enterprise Features
- Role-based access control (treasurer, secretary, member)
- Audit logs
- Multi-society support
- Integration with accounting software
- Mobile app

## API Keys Required

- **Anthropic API Key**: For Claude LLM and vision models
  - Get one at: https://console.anthropic.com/

## Database Files

All data is stored in local Excel files:
- `data/society_data.xlsx` — Main data file
- `data/invoices/{FY}/` — Generated invoices
- `data/receipts/{FY}/` — Generated receipts
- `data/ledgers/` — Exported ledger reports

Backup these files regularly!

## Troubleshooting

### Excel file locked error
- Close any Excel applications that have the file open
- The app uses openpyxl which can't modify open files

### Anthropic API errors
- Verify API key is valid and not expired
- Check internet connection
- Ensure API key has vision model access (claude-3-5-sonnet)

### Login issues
- Default credentials: admin / password123
- Change in `.env` file
- Restart app after changing credentials

## Support

For issues or questions:
1. Check the PROJECT_PLAN.md for detailed architecture
2. Review agent logs in chat history
3. Verify data in Excel files

## License

This project is for internal society use. All rights reserved.

---

**Built with**: Streamlit | LangChain | Claude | openpyxl | reportlab

**Version**: 1.0 (MVP)

**Last Updated**: May 2026
