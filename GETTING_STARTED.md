# Getting Started with Society Management Chatbot

## ⚡ Quick Start (5 minutes)

### Step 1: Install Dependencies
```bash
cd /Users/ashutoshsinkar/society-chatbot
pip install -r requirements.txt
```

**Expected output**: All packages installed successfully

### Step 2: Configure Environment
```bash
cp .env.example .env
```

Edit `.env` and add your API key:
```
ANTHROPIC_API_KEY=sk-ant-xxxxx  # Get from https://console.anthropic.com/
ADMIN_USERNAME=admin
ADMIN_PASSWORD=password123
```

### Step 3: Initialize Sample Data (Optional)
```bash
python init_sample_data.py
```

This creates:
- 44 sample members (Plot 01-44)
- Some with outstanding balances for testing

**Expected output**: "44 members added successfully"

### Step 4: Run Tests (Optional)
```bash
python -m pytest tests/ -v
```

Or:
```bash
python tests/test_agents.py
```

**Expected output**: All tests should pass ✓

### Step 5: Start the App
```bash
streamlit run main.py
```

The browser will open automatically to `http://localhost:8501`

### Step 6: Login
- Username: `admin`
- Password: `password123`

## 📋 Verification Checklist

After running the app, verify these features work:

### ✅ Chat Interface
- [ ] Login page appears
- [ ] Chat page loads with empty history
- [ ] Can type messages in the input field
- [ ] "Send" button is clickable

### ✅ Dashboard
- [ ] Shows "Total Members: 44" (if sample data added)
- [ ] Shows "Total Outstanding" amount
- [ ] Displays member list with outstanding balances

### ✅ Settings Page
- [ ] Can view/update invoice rates
- [ ] Can add new members
- [ ] Can trigger April 1st entries

### ✅ File System
- [ ] `data/society_data.xlsx` is created
- [ ] Contains Members, Ledger, Settings sheets
- [ ] Directories exist: invoices/, receipts/, ledgers/

---

## 🚀 Try These Commands in Chat

Once logged in, try these in the chat:

### 1. Generate Invoices (Recommended First Test)
```
User: "Generate invoices for FY 2026-27"
```

Expected: Agent will generate invoices for all members

### 2. View Ledger
```
User: "Show ledger for Plot 01"
```

Expected: Shows transaction history for that member

### 3. Get Summary
```
User: "Show outstanding summary"
```

Expected: Lists all members with outstanding balances

### 4. System Status
```
User: "System summary"
```

Expected: Shows total members, outstanding, current FY

---

## 📁 Project Structure Verification

Verify these files exist:

```
society-chatbot/
✓ main.py                      (1200+ lines)
✓ config.py                    (60+ lines)
✓ PROJECT_PLAN.md              (detailed plan)
✓ README.md                     (documentation)
✓ requirements.txt             (dependencies)
✓ .env.example                 (config template)

✓ agents/
  ✓ base_agent.py
  ✓ invoice_agent.py
  ✓ receipt_agent.py
  ✓ ledger_agent.py
  ✓ admin_agent.py

✓ data_providers/
  ✓ base_provider.py
  ✓ local_excel_provider.py
  ✓ google_sheets_provider.py (stub)

✓ file_storage/
  ✓ base_storage.py
  ✓ local_storage.py
  ✓ google_drive_storage.py (stub)

✓ tools/
  ✓ excel_processor.py
  ✓ pdf_generator.py
  ✓ ocr_processor.py
  ✓ converters.py

✓ utils/
  ✓ auth.py
  ✓ chat_manager.py
  ✓ helpers.py
  ✓ converters.py

✓ data/
  (will be created on first run)
```

---

## 🐛 Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'streamlit'"
**Solution**: 
```bash
pip install -r requirements.txt
```

### Issue: "FileNotFoundError: [Errno 2] No such file or directory: 'society_data.xlsx'"
**Solution**: 
- Run the app once, it will create the file automatically
- Or run: `python init_sample_data.py`

### Issue: Excel file locked error
**Solution**: 
- Close Excel application if it has the file open
- Delete `data/society_data.xlsx` and restart app

### Issue: "API key not found" error
**Solution**: 
- Add your Anthropic API key to `.env`
- Get one at: https://console.anthropic.com/api-keys

### Issue: App doesn't open in browser
**Solution**: 
- Manually open: http://localhost:8501
- Check terminal for error messages
- Try: `streamlit run main.py --logger.level=debug`

---

## 📊 Expected Database State

After initialization, `data/society_data.xlsx` should have:

### Members Sheet (44 rows + header)
```
ID  Plot_No  Plot_Owner_Name           Email                    Current_Outstanding
1   01       Mrs. Asha Ganpat Dalvi   asha@example.com         29000
2   02       Mr. Rajesh Kumar         rajesh@example.com       15000
3   03       Ms. Priya Sharma         priya@example.com        0
...
44  44       Member 44                member44@example.com     53000
```

### Settings Sheet
```
Key                              Value
Current_FY                       2026-27
Repair_Fund_Rate                100.00
Service_Charges_Rate            885.00
Sinking_Fund_Rate               15.00
April_1st_Auto_Entry_Amount     12000
Last_Voucher_No                 0
```

### Ledger Sheet
```
(Empty initially, populated as agents create entries)
```

---

## 🔧 Configuration Tips

### Change Default Login Credentials
Edit `.env`:
```
ADMIN_USERNAME=treasurer
ADMIN_PASSWORD=myPassword123
```

### Customize Invoice Rates
Edit `config.py`:
```python
INVOICE_RATES = {
    "repair_maintenance": 100.00,  # Change this
    "service_charges": 885.00,     # Change this
    "sinking_fund": 15.00,         # Change this
}
```

### Change Invoice Due Days
Edit `config.py`:
```python
INVOICE_DUE_DAYS = 60  # Change to 30, 45, 90, etc.
```

---

## ✨ Next Steps

After verification:

1. **Add Real Members**: Use Settings page or chat to add your actual 44 members
2. **Upload Templates**: Add your Excel invoice/receipt templates to `data/templates/`
3. **Test End-to-End**: Generate invoice → View in `data/invoices/` → Verify PDF
4. **Customize**: Adjust rates, templates, and styling as needed
5. **Plan Google Integration**: When ready, implement Google Sheets/Drive (future phase)

---

## 📚 Documentation Files

- **PROJECT_PLAN.md** - Detailed architecture and implementation plan
- **README.md** - Complete project documentation
- **GETTING_STARTED.md** (this file) - Quick start guide
- **main.py** - Inline comments explaining chat routing logic

---

## 🎯 Success Criteria

✅ You've succeeded when:

1. App starts and login page appears
2. Can log in with credentials
3. Chat page loads and is responsive
4. Dashboard shows statistics
5. Can type and receive responses from agents
6. Invoice generation completes without errors
7. Files are created in `data/invoices/`, `data/receipts/`, etc.
8. Excel file is updated with ledger entries

---

## 💡 Tips for Development

### Enable Debug Logging
```bash
streamlit run main.py --logger.level=debug
```

### Run Specific Tests
```bash
python -m pytest tests/test_agents.py::TestDataProvider::test_add_member -v
```

### Clear Session State
- Logout and login again (Streamlit resets session state)
- Or close the browser and reopen

### Monitor File Changes
```bash
# Watch data/society_data.xlsx changes
ls -lh data/society_data.xlsx
```

---

## 🚀 You're Ready!

Your Society Management Chatbot is now ready to use. Happy automating! 🎉

Need help? Check:
- PROJECT_PLAN.md for architecture details
- README.md for complete documentation
- Agent source files for implementation details

---

**Questions?** Review the chat agent responses to understand how they work. Each agent logs its reasoning to the chat!
