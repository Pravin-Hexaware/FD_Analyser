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

KEY_VAULT_URL = os.getenv(
    "KEY_VAULT_URL",
    "https://fstodevazureopenai.vault.azure.net/",
)

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
