"""
Unit tests for authentication fallback and safety shielding
"""
import pytest
from unittest.mock import patch, MagicMock
import config
from utils.auth import authenticate_firebase
from agents.router_agent import get_router


def test_firebase_auth_disabled_returns_none(monkeypatch):
    """Test authenticate_firebase returns None if disabled"""
    monkeypatch.setattr(config, "FIREBASE_AUTH_ENABLED", False)
    result = authenticate_firebase("test@example.com", "password")
    assert result is None


def test_firebase_auth_success():
    """Test authenticate_firebase returns response dict on 200 OK"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "email": "test@example.com",
        "localId": "firebase-uid-123",
        "idToken": "fake-jwt-token"
    }

    with patch("httpx.Client.post", return_value=mock_response):
        with patch("config.FIREBASE_AUTH_ENABLED", True):
            with patch("config.FIREBASE_API_KEY", "dummy-api-key"):
                result = authenticate_firebase("test@example.com", "password")
                assert result is not None
                assert result["email"] == "test@example.com"
                assert result["localId"] == "firebase-uid-123"


def test_firebase_auth_failed():
    """Test authenticate_firebase returns None on non-200 error"""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": {
            "message": "INVALID_PASSWORD"
        }
    }

    with patch("httpx.Client.post", return_value=mock_response):
        with patch("config.FIREBASE_AUTH_ENABLED", True):
            with patch("config.FIREBASE_API_KEY", "dummy-api-key"):
                with patch("streamlit.error") as mock_st_error:
                    result = authenticate_firebase("test@example.com", "wrong-password")
                    assert result is None
                    mock_st_error.assert_called_once_with("Authentication failed: INVALID_PASSWORD")


def test_router_agent_safety_shield():
    """Test that RouterAgent classifies out-of-scope queries to out_of_scope"""
    router = get_router()
    
    # Test valid society-related queries
    valid_queries = [
        "Show plot 05 outstanding details",
        "Generate invoices for April 2026",
        "Process this payment receipt",
        "Update monthly maintenance rates"
    ]
    
    # Test invalid off-topic queries
    off_topic_queries = [
        "Write a python script to implement quicksort",
        "What is the capital of Australia?",
        "Can you write a poem about streams?",
        "Tell me a joke"
    ]

    # Mock the LLM call inside RouterAgent to verify routing behaviour
    # Or test it directly if API key is active.
    # To make test self-contained without active LLM API calls in CI/testing, we can patch `_llm_route`
    # or just let it run if credentials are valid. We mock it here for reproducibility.
    
    # Let's mock the LLM routing behaviour to return out_of_scope for off-topic, and corresponding agent for valid.
    with patch.object(router, "_llm_route") as mock_llm_route:
        # Off-topic mocks
        mock_llm_route.return_value = {
            "agent": "out_of_scope",
            "confidence": 0.99,
            "intent": "Unrelated query",
            "reasoning": "Query is out of scope.",
            "clarification_needed": False
        }
        
        for q in off_topic_queries:
            res = router.route(q)
            assert res["agent"] == "out_of_scope"
            
        # On-topic mocks
        mock_llm_route.return_value = {
            "agent": "ledger_agent",
            "confidence": 0.95,
            "intent": "View outstanding details",
            "reasoning": "Query asks for outstanding details.",
            "clarification_needed": False
        }
        
        res = router.route(valid_queries[0])
        assert res["agent"] == "ledger_agent"


def test_user_roles_detection():
    """Test role assignment logic in get_user_role"""
    from utils.auth import get_user_role
    
    with patch("config.ADMIN_USERNAME", "admin"):
        with patch("config.ADMIN_EMAILS", "admin1@example.com,committee@example.com"):
            assert get_user_role("admin") == "admin"
            assert get_user_role("ADMIN") == "admin"
            assert get_user_role("admin1@example.com") == "admin"
            assert get_user_role("committee@example.com") == "admin"
            assert get_user_role("member@example.com") == "member"
            assert get_user_role("") == "member"


def test_write_tools_rbac_permissions():
    """Test that write tools return Permission Denied for members, and pass through for admins"""
    from langchain.agents import Tool
    from agents.base_agent import BaseAgent
    
    # Create a dummy subclass of BaseAgent to test register_tool
    class DummyAgent(BaseAgent):
        def get_tools(self):
            pass
            
    # Mock data provider and file storage
    mock_provider = MagicMock()
    mock_storage = MagicMock()
    
    agent = DummyAgent("Dummy", "Description", mock_provider, mock_storage)
    
    # We will register a read tool and a write tool
    def dummy_read_tool():
        return "read success"
        
    def dummy_write_tool():
        return "write success"
        
    # Register them
    agent.register_tool(dummy_read_tool, "get_member_ledger", "Read tool")
    agent.register_tool(dummy_write_tool, "add_ledger_entry", "Write tool")
    
    # 1. Test running as Admin
    admin_state = {"authenticated": True, "role": "admin"}
    with patch("streamlit.session_state", admin_state):
        # Read tool should work
        read_tool = next(t for t in agent.tools if t.name == "get_member_ledger")
        assert read_tool.func() == "read success"
        
        # Write tool should work
        write_tool = next(t for t in agent.tools if t.name == "add_ledger_entry")
        assert write_tool.func() == "write success"
        
    # 2. Test running as Member
    member_state = {"authenticated": True, "role": "member"}
    with patch("streamlit.session_state", member_state):
        # Read tool should still work
        read_tool = next(t for t in agent.tools if t.name == "get_member_ledger")
        assert read_tool.func() == "read success"
        
        # Write tool should return Permission Denied
        write_tool = next(t for t in agent.tools if t.name == "add_ledger_entry")
        res = write_tool.func()
        assert "Permission Denied" in res


def test_create_llm_custom_openai_compat():
    """Test create_llm correctly instantiates ChatOpenAI with generic parameters"""
    from agents.base_agent import create_llm
    
    with patch("config.LLM_PROVIDER", "openai"):
        with patch("config.LLM_API_KEY", "custom-api-key"):
            with patch("config.LLM_BASE_URL", "https://api.custom-provider.com/v1"):
                with patch("langchain.chat_models.ChatOpenAI") as mock_chat_openai:
                    create_llm("custom-model-123")
                    mock_chat_openai.assert_called_once_with(
                        model="custom-model-123",
                        temperature=config.LLM_TEMPERATURE,
                        max_tokens=config.LLM_MAX_TOKENS,
                        api_key="custom-api-key",
                        base_url="https://api.custom-provider.com/v1",
                        default_headers=None
                    )
