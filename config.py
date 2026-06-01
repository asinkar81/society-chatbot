"""
Configuration settings for the Society Management Chatbot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project root
PROJECT_ROOT = Path(__file__).parent

# Admin credentials
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password123")

# API Provider selection ("anthropic" or "openrouter")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter")  # Default to direct Anthropic API

# API keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Data storage configuration
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "local")  # "local" or "google"
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
INVOICES_DIR = DATA_DIR / "invoices"
RECEIPTS_DIR = DATA_DIR / "receipts"
LEDGERS_DIR = DATA_DIR / "ledgers"

# Excel data file
SOCIETY_DATA_FILE = DATA_DIR / "society_data.xlsx"

# Society settings
TOTAL_MEMBERS = 44
FINANCIAL_YEAR_START = 4  # April
AUTO_ENTRY_AMOUNT = 12000  # Annual contribution

# Invoice rates (per month)
INVOICE_RATES = {
    "repair_maintenance": 100.00,
    "service_charges": 885.00,
    "sinking_fund": 15.00,
}

# Invoice settings
INVOICE_DUE_DAYS = 30
INVOICE_PERIOD_MONTHS = 12

# Set to True to skip the login page (useful for local dev / demos)
BYPASS_LOGIN = os.getenv("BYPASS_LOGIN", "false").lower() in ("true", "1", "yes")

# Streamlit configuration
STREAMLIT_PAGE_ICON = "💰"
STREAMLIT_PAGE_TITLE = "Society Management Chatbot"
STREAMLIT_LAYOUT = "wide"

HISTORICAL_RECEIPTS_DIR = DATA_DIR / "Historical_Receipts"
UPLOADS_DIR = DATA_DIR / "uploads"

# Ensure data directories exist
DATA_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)
INVOICES_DIR.mkdir(exist_ok=True)
RECEIPTS_DIR.mkdir(exist_ok=True)
LEDGERS_DIR.mkdir(exist_ok=True)
HISTORICAL_RECEIPTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# LLM settings
LLM_TEMPERATURE = 0.7
LLM_MAX_TOKENS = 2048

# Set to True to use free models, False for paid high-quality models
USE_FREE_MODELS = os.getenv("USE_FREE_MODELS", "true").lower() in ("true", "1", "yes")

# Model names: OpenRouter uses different model IDs than Anthropic direct API
# Anthropic-native names (for Anthropic SDK / ChatAnthropic)
ANTHROPIC_MODEL_MAIN = "claude-3-5-haiku-20241022"
ANTHROPIC_MODEL_VISION = "claude-3-5-sonnet-20241022"
# OpenRouter slug names — free tier
#OPENROUTER_MODEL_MAIN_FREE = "openrouter/free"
OPENROUTER_MODEL_MAIN_FREE = "qwen/qwen3-coder:free"
OPENROUTER_MODEL_VISION_FREE = "google/gemini-2.0-flash:free"
# OpenRouter slug names — paid tier
OPENROUTER_MODEL_MAIN_PAID = "anthropic/claude-3.5-haiku"
OPENROUTER_MODEL_VISION_PAID = "anthropic/claude-3.5-sonnet"

if LLM_PROVIDER == "openrouter":
    if USE_FREE_MODELS:
        LLM_MODEL_MAIN = OPENROUTER_MODEL_MAIN_FREE
        LLM_MODEL_VISION = OPENROUTER_MODEL_VISION_FREE
    else:
        LLM_MODEL_MAIN = OPENROUTER_MODEL_MAIN_PAID
        LLM_MODEL_VISION = OPENROUTER_MODEL_VISION_PAID
else:
    LLM_MODEL_MAIN = ANTHROPIC_MODEL_MAIN
    LLM_MODEL_VISION = ANTHROPIC_MODEL_VISION

# OpenRouter settings (if using OpenRouter provider)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Optional: Set a site URL for OpenRouter analytics
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost:8501")
# Optional: Set a site name for OpenRouter analytics
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "Society Chatbot")
