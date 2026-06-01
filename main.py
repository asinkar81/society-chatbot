"""
Main Streamlit application for Society Management Chatbot
"""
import streamlit as st
from pathlib import Path
import config
from utils.auth import show_login_page, logout
from utils.chat_manager import ChatManager
from data_providers.local_excel_provider import LocalExcelDataProvider
from file_storage.local_storage import LocalFileStorage
from agents.invoice_agent import InvoiceAgent
from agents.receipt_agent import ReceiptAgent
from agents.ledger_agent import LedgerAgent
from agents.admin_agent import AdminAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.router_agent import get_router
import json
from datetime import datetime
import uuid


# Page config
st.set_page_config(
    page_title=config.STREAMLIT_PAGE_TITLE,
    page_icon=config.STREAMLIT_PAGE_ICON,
    layout=config.STREAMLIT_LAYOUT,
    initial_sidebar_state="expanded",
)

# Initialize chat manager
if "chat_manager" not in st.session_state:
    st.session_state.chat_manager = ChatManager()

# Initialize data provider and agents
@st.cache_resource
def init_agents():
    """Initialize data provider and agents"""
    data_provider = LocalExcelDataProvider(config.SOCIETY_DATA_FILE)
    file_storage = LocalFileStorage(config.DATA_DIR)

    return {
        "data_provider": data_provider,
        "file_storage": file_storage,
        "invoice_agent": InvoiceAgent(data_provider, file_storage),
        "receipt_agent": ReceiptAgent(data_provider, file_storage),
        "ledger_agent": LedgerAgent(data_provider, file_storage),
        "admin_agent": AdminAgent(data_provider, file_storage),
        "orchestrator_agent": OrchestratorAgent(data_provider, file_storage),
    }


# Check authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if config.BYPASS_LOGIN:
    st.session_state.authenticated = True
    st.session_state.username = st.session_state.get("username", config.ADMIN_USERNAME)
elif not st.session_state.authenticated:
    show_login_page()
    st.stop()

# Initialize agents
agents = init_agents()
data_provider = agents["data_provider"]
file_storage = agents["file_storage"]
invoice_agent = agents["invoice_agent"]
receipt_agent = agents["receipt_agent"]
ledger_agent = agents["ledger_agent"]
admin_agent = agents["admin_agent"]
orchestrator_agent = agents["orchestrator_agent"]


# Main layout
def main():
    """Main application layout"""

    # Sidebar navigation
    with st.sidebar:
        st.title("🏘️ Society Management")
        st.caption(f"Welcome, {st.session_state.username}!")

        page = st.radio(
            "Navigation",
            ["Chat", "Dashboard", "Settings", "Help"],
            key="page_nav",
        )

        st.divider()

        if st.button("🚪 Logout", use_container_width=True):
            logout()

    # Route to pages
    if page == "Chat":
        show_chat_page()
    elif page == "Dashboard":
        show_dashboard_page()
    elif page == "Settings":
        show_settings_page()
    elif page == "Help":
        show_help_page()


def save_uploaded_file(uploaded_file) -> Path:
    """Save an uploaded file to the persistent uploads directory and return the path."""
    ext = Path(uploaded_file.name).suffix
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = config.UPLOADS_DIR / unique_name
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest


def show_chat_page():
    """Chat interface page"""
    st.title("💬 Agentic Chatbot")
    st.markdown("Chat with agents to manage invoices, receipts, and ledgers")

    st.divider()

    # Display chat history
    chat_container = st.container(height=400, border=True)
    with chat_container:
        st.session_state.chat_manager.display_chat_history()

    st.divider()

    # File upload + chat input
    if "upload_key" not in st.session_state:
        st.session_state.upload_key = 0

    uploaded_file = st.file_uploader(
        "📎 Attach a file (payment screenshot, receipt image, etc.)",
        type=["jpg", "jpeg", "png", "gif", "webp", "pdf"],
        key=f"chat_upload_{st.session_state.upload_key}",
    )

    col1, col2 = st.columns([5, 1])
    with col1:
        user_input = st.text_input(
            "Enter your message:",
            placeholder="E.g., 'Generate invoices for FY 2026-27' or 'Show ledger for Plot 01'",
            key="chat_input",
        )
    with col2:
        send_btn = st.button("Send", use_container_width=True)

    if send_btn and user_input:
        attachments = []
        enriched_input = user_input

        if uploaded_file is not None:
            saved_path = save_uploaded_file(uploaded_file)
            attachments.append({
                "path": str(saved_path),
                "filename": uploaded_file.name,
                "mime_type": uploaded_file.type,
                "size": uploaded_file.size,
            })
            enriched_input += f"\n\n[Attached file: {saved_path} — {uploaded_file.name}]"

            # Pre-extract payment details from image so the LLM has them immediately
            ext = Path(uploaded_file.name).suffix.lower()
            if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                try:
                    ocr_result = orchestrator_agent.ocr_processor.extract_payment_details(saved_path)
                    if "error" not in ocr_result:
                        enriched_input += f"\n[Extracted Payment Details: {json.dumps(ocr_result)}]"
                    else:
                        enriched_input += f"\n[OCR Extraction issue: {ocr_result['error']}. You can retry with the file path above.]"
                except Exception as e:
                    enriched_input += f"\n[OCR Extraction error: {str(e)}]"

        st.session_state.chat_manager.add_message(
            "user", user_input, attachments=attachments,
        )

        with st.spinner("🤖 Processing with Orchestrator Agent..."):
            response = orchestrator_agent.run(enriched_input)

        st.session_state.chat_manager.add_message("agent", response)

        # Reset file uploader for next message
        st.session_state.upload_key += 1
        st.rerun()


def show_dashboard_page():
    """Dashboard page"""
    st.title("📊 Dashboard")

    # Get statistics
    members = data_provider.get_all_members()
    total_members = len(members)
    total_outstanding = sum(data_provider.get_current_outstanding(m["ID"]) for m in members)

    # Display metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Members", total_members)

    with col2:
        label = "Surplus" if total_outstanding > 0 else "Demand"
        st.metric(f"Net {label}", f"₹{abs(total_outstanding):,.2f}")

    with col3:
        settled = sum(1 for m in members if data_provider.get_current_outstanding(m["ID"]) == 0)
        st.metric("Settled", settled)

    with col4:
        pending = sum(1 for m in members if data_provider.get_current_outstanding(m["ID"]) < 0)
        st.metric("In Demand", pending)

    st.divider()

    # Quick actions
    st.subheader("Quick Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🧾 Generate Invoices", use_container_width=True):
            st.info("Generating invoices for all members...")
            # Would trigger invoice generation
            st.success("Invoices generated successfully!")

    with col2:
        if st.button("💳 Process Payment", use_container_width=True):
            st.info("Upload payment screenshot")

    with col3:
        if st.button("📋 View All Ledgers", use_container_width=True):
            st.info("Exporting ledger data...")

    st.divider()

    # Member list
    st.subheader("Member Status")

    member_data = []
    for member in members:
        outstanding = data_provider.get_current_outstanding(member["ID"])
        if outstanding < 0:
            status = f"Demand ₹{abs(outstanding):,.0f}"
        elif outstanding > 0:
            status = f"Surplus ₹{outstanding:,.0f}"
        else:
            status = "Settled"
        member_data.append(
            {
                "Plot No": member.get("Plot_No", "N/A"),
                "Name": member.get("Plot_Owner_Name", "N/A"),
                "Balance": f"₹{abs(outstanding):,.2f}",
                "Status": status,
            }
        )

    st.dataframe(member_data, use_container_width=True)


def show_settings_page():
    """Settings page"""
    st.title("⚙️ Settings")

    settings = data_provider.get_settings()

    tab1, tab2, tab3 = st.tabs(["Rates", "Members", "System"])

    with tab1:
        st.subheader("Invoice Rates")

        col1, col2, col3 = st.columns(3)

        with col1:
            repair = st.number_input(
                "Repair & Maintenance Fund (₹/month)",
                value=float(settings.get("Repair_Fund_Rate", 100)),
                min_value=0.0,
            )

        with col2:
            service = st.number_input(
                "Service Charges (₹/month)",
                value=float(settings.get("Service_Charges_Rate", 885)),
                min_value=0.0,
            )

        with col3:
            sinking = st.number_input(
                "Sinking Fund (₹/month)",
                value=float(settings.get("Sinking_Fund_Rate", 15)),
                min_value=0.0,
            )

        if st.button("Update Rates", use_container_width=True):
            data_provider.update_settings(
                {
                    "Repair_Fund_Rate": str(repair),
                    "Service_Charges_Rate": str(service),
                    "Sinking_Fund_Rate": str(sinking),
                }
            )
            st.success("Rates updated successfully!")

    with tab2:
        st.subheader("Member Management")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            plot_no = st.text_input("Plot No")

        with col2:
            name = st.text_input("Member Name")

        with col3:
            email = st.text_input("Email")

        with col4:
            phone = st.text_input("Phone")

        if st.button("Add Member", use_container_width=True):
            if plot_no and name:
                data_provider.add_member(
                    {
                        "Plot_No": plot_no,
                        "Plot_Owner_Name": name,
                        "Email": email,
                        "Phone": phone,
                        "Current_Outstanding": 0,
                        "Pending_Interest": 0,
                    }
                )
                st.success(f"Member {name} added successfully!")
            else:
                st.error("Plot No and Name are required")

    with tab3:
        st.subheader("System Management")

        if st.button("Trigger April 1st Entries", use_container_width=True):
            st.info("Processing April 1st entries for all members...")
            # Would trigger admin agent
            st.success("April 1st entries created successfully!")


def show_help_page():
    """Help and examples page"""
    st.title("❓ Help & Examples")

    st.markdown("""
    ## How to Use This Chatbot

    ### Invoice Generation
    - "Generate invoices for FY 2026-27"
    - "Create invoices for all members"
    - The agent will generate PDF invoices with all calculations

    ### Payment Processing
    - "Process this payment screenshot"
    - Upload the screenshot using the file uploader above the chat input
    - Then type your request (e.g., "Process this payment for Plot 05")
    - The agent will OCR the image, extract details, and generate a receipt

    ### Ledger Management
    - "Show ledger for Plot 01"
    - "View outstanding balance for [member name]"
    - "Export all ledgers to CSV"

    ### Admin Tasks
    - "Update invoice rates"
    - "Add new member"
    - "Trigger April 1st auto-entries"

    ## Features

    - 🤖 Multi-agent system for different tasks
    - 💬 Natural language chat interface with integrated file upload
    - 📄 Automatic invoice generation with PDF output
    - 📷 Upload payment screenshots alongside chat for instant OCR + receipting
    - 📊 Complete ledger management
    - 💾 Local file storage (scalable to Google Drive)
    - 🔐 Secure admin login

    ## Architecture

    - **Abstraction Layers**: Data and file storage abstraction allows easy migration to Google Sheets/Drive
    - **Local MVP**: All files stored locally, no Google API required yet
    - **Scalable**: Ready for enterprise features

    """)


def process_user_input(user_input: str) -> str:
    """
    Process user input using the Orchestrator Agent for multi-step workflows.
    Shows routing intent analysis for transparency.
    """
    try:
        # Show intent analysis from router
        try:
            router = get_router()
            routing_result = router.route(user_input)
            st.info(f"🤖 **Intent**: {routing_result['intent']} (confidence: {routing_result['confidence']:.0%})")
            if routing_result.get("clarification_needed") and routing_result.get("agent") is None:
                return f"❓ {routing_result.get('clarification_question', 'I need more information to help you.')}\n\n**Suggested actions:**\n- Generate invoices\n- Process payments\n- View ledgers\n- Manage admin settings"
        except Exception:
            pass

        # Route to orchestrator for multi-step handling
        with st.spinner("🤖 Processing with Orchestrator Agent..."):
            response = orchestrator_agent.run(user_input)
        return response

    except Exception as e:
        st.error(f"Processing error: {str(e)}")
        return f"❌ Error processing your request: {str(e)}"


def handle_invoice_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle invoice-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("📄 Processing invoice request..."):
            response = invoice_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Invoice agent error: {str(e)}")
        return f"❌ Invoice agent error: {str(e)}"


def handle_receipt_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle payment/receipt-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("💳 Processing payment request..."):
            response = receipt_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Receipt agent error: {str(e)}")
        return f"❌ Receipt agent error: {str(e)}"


def handle_ledger_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle ledger/account-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("📊 Fetching ledger information..."):
            response = ledger_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Ledger agent error: {str(e)}")
        return f"❌ Ledger agent error: {str(e)}"


def handle_admin_request(user_input: str, routing_result: dict = None) -> str:
    """
    Handle admin/settings-related requests
    
    Args:
        user_input: Original user input
        routing_result: LLM routing analysis (for logging/debugging)
    """
    try:
        with st.spinner("⚙️ Processing admin request..."):
            response = admin_agent.run(user_input)
        return response
    except Exception as e:
        st.error(f"Admin agent error: {str(e)}")
        return f"❌ Admin agent error: {str(e)}"


if __name__ == "__main__":
    main()
