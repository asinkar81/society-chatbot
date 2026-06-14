"""
Authentication utilities
"""
import streamlit as st
import hashlib
import httpx
import config
from typing import Optional


def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify password against stored hash"""
    return stored_hash == hash_password(provided_password)


def get_user_role(username: str) -> str:
    """Determine role based on username/email"""
    if not username:
        return "member"
    
    # Standard local admin bypass / credentials
    if username.lower() == config.ADMIN_USERNAME.lower():
        return "admin"
        
    # Check if email matches configured admin emails
    admin_emails = [email.strip().lower() for email in getattr(config, "ADMIN_EMAILS", "").split(",") if email.strip()]
    if username.lower() in admin_emails:
        return "admin"
        
    return "member"


def authenticate_firebase(email: str, password: str) -> Optional[dict]:
    """
    Authenticate against Firebase Auth REST API using Email/Password.
    Returns the user data dict on success, None on failure.
    """
    if not config.FIREBASE_AUTH_ENABLED:
        return None

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={config.FIREBASE_API_KEY}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }
    try:
        with httpx.Client() as client:
            response = client.post(url, json=payload, timeout=10.0)
            if response.status_code == 200:
                return response.json()
            else:
                error_data = response.json()
                error_message = error_data.get("error", {}).get("message", "Authentication failed")
                st.error(f"Authentication failed: {error_message}")
                return None
    except Exception as e:
        st.error(f"Error connecting to Firebase Auth: {str(e)}")
        return None


def login_required(func):
    """Decorator to require login before accessing function"""

    def wrapper(*args, **kwargs):
        if "authenticated" not in st.session_state or not st.session_state.authenticated:
            st.warning("Please log in first")
            return
        return func(*args, **kwargs)

    return wrapper


def show_login_page():
    """Display login page"""
    st.set_page_config(page_title="Login - Society Management", page_icon="🔐")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🏘️ Society Management")
        st.subheader("Agentic Chatbot")

        st.markdown("---")

        if config.FIREBASE_AUTH_ENABLED:
            st.info("🔐 Firebase Authentication is enabled.")
            username_label = "Email"
        else:
            st.warning("⚠️ Local Authentication (Demo Mode) is active.")
            username_label = "Username"

        username = st.text_input(username_label)
        password = st.text_input("Password", type="password")

        if st.button("Login", use_container_width=True):
            # Check local credentials fallback first
            if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
                st.session_state.authenticated = True
                st.session_state.username = username
                st.success("✅ Login successful (local admin)!")
                st.rerun()
            elif config.FIREBASE_AUTH_ENABLED:
                # Try Firebase Auth if local credentials didn't match
                firebase_user = authenticate_firebase(username, password)
                if firebase_user:
                    st.session_state.authenticated = True
                    st.session_state.username = firebase_user.get("email", username)
                    st.session_state.firebase_uid = firebase_user.get("localId")
                    st.session_state.id_token = firebase_user.get("idToken")
                    st.success("✅ Login successful via Firebase!")
                    st.rerun()
            else:
                st.error("❌ Invalid credentials")

        st.markdown("---")
        if config.FIREBASE_AUTH_ENABLED:
            st.caption("Enter your Firebase project user email & password.")
        else:
            st.caption("Demo credentials: admin / password123")


def logout():
    """Logout user"""
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.clear()
    st.rerun()
