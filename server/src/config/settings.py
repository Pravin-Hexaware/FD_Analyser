"""Centralized application settings and paths."""
import os
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "Data"
LOGS_DIR = SRC_DIR / "logs"
MARKDOWN_DIR = SRC_DIR / "markdown"
OVERALL_LOGS_DIR = SRC_DIR / "Overall_logs"

DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "financial_data.db")))
COMPANY_METADATA_CSV = DATA_DIR / "Company_metadata.csv"
VALIDATION_CSV = DATA_DIR / "Validation.csv"
MISSING_COMPANIES_CSV = DATA_DIR / "missing_companies.csv"
NIFTY500_CSV = DATA_DIR / "ind_nifty500list.csv"
NIFTY500_CSV_URL = os.getenv(
    "NIFTY500_CSV_URL",
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
)
NIFTY500_REFRESH_DAYS = int(os.getenv("NIFTY500_REFRESH_DAYS", "7"))

KEY_VAULT_URL = os.getenv(
    "KEY_VAULT_URL",
    "https://fstodevazureopenai.vault.azure.net/",
)

# LangSmith (see utils/langsmith_tracing.py)
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", ""))
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "finbot"))
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", ""))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
