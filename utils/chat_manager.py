"""
Chat management utilities
"""
import streamlit as st
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


class ChatManager:
    """Manage chat history and context"""

    def __init__(self):
        self.init_session_state()

    def init_session_state(self):
        """Initialize session state for chat"""
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        if "chat_context" not in st.session_state:
            st.session_state.chat_context = {}

    def add_message(self, role: str, content: str, metadata: Dict[str, Any] = None,
                    attachments: List[Dict[str, Any]] = None):
        """Add message to chat history"""
        message = {
            "role": role,  # "user", "agent", "system"
            "content": content,
            "timestamp": datetime.now(),
            "metadata": metadata or {},
            "attachments": attachments or [],
        }
        st.session_state.chat_history.append(message)

    def get_chat_history(self) -> List[Dict[str, Any]]:
        """Get full chat history"""
        return st.session_state.chat_history

    def clear_chat_history(self):
        """Clear chat history"""
        st.session_state.chat_history = []

    def set_context(self, key: str, value: Any):
        """Set context variable (e.g., selected member)"""
        st.session_state.chat_context[key] = value

    def get_context(self, key: str, default=None):
        """Get context variable"""
        return st.session_state.chat_context.get(key, default)

    def clear_context(self, key: str = None):
        """Clear context variable or all context"""
        if key:
            st.session_state.chat_context.pop(key, None)
        else:
            st.session_state.chat_context = {}

    def display_chat_history(self):
        """Display chat history in Streamlit"""
        for message in st.session_state.chat_history:
            role = message["role"]
            content = message["content"]
            attachments = message.get("attachments", [])

            if role == "user":
                with st.chat_message("user"):
                    st.markdown(content)
                    for att in attachments:
                        path = att.get("path", "")
                        fname = att.get("filename", Path(path).name) if path else att.get("filename", "")
                        if path and Path(path).exists():
                            ext = Path(path).suffix.lower()
                            if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                                st.image(path, caption=fname, width=300)
                            else:
                                st.caption(f"📎 {fname}")
                        else:
                            st.caption(f"📎 {fname}")
            elif role == "agent":
                with st.chat_message("assistant"):
                    st.markdown(content)
            elif role == "system":
                with st.chat_message("system"):
                    st.info(content)
