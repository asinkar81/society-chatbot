"""
Authentication utilities
"""
import streamlit as st
import hashlib
import config


def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify password against stored hash"""
    return stored_hash == hash_password(provided_password)


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

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login", use_container_width=True):
            if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
                st.session_state.authenticated = True
                st.session_state.username = username
                st.success("✅ Login successful!")
                st.rerun()
            else:
                st.error("❌ Invalid credentials")

        st.markdown("---")
        st.caption("Demo credentials: admin / password123")


def logout():
    """Logout user"""
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.clear()
    st.rerun()
