"""
config.py
---------
Centralized, validated configuration loader.
All secrets and runtime parameters are sourced exclusively from the .env file.
Never import this module in a context where dotenv has not been loaded first.
"""

import os
import logging
from dotenv import load_dotenv

# Load .env from the project root (one directory above this file if needed)
load_dotenv()

logger = logging.getLogger(__name__)


def _require(key: str) -> str:
    """Fetch a required env var; raise immediately if missing."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"[config] Required environment variable '{key}' is not set. "
            f"See .env.example for the full list of required variables."
        )
    return value


def _optional(key: str, default: str = "") -> str:
    """Fetch an optional env var with a safe default."""
    return os.getenv(key, default)


# ---------------------------------------------------------------------------
# Real Estate Data API
# ---------------------------------------------------------------------------
REALESTATE_API_BASE_URL: str = _require("REALESTATE_API_BASE_URL")
REALESTATE_API_KEY: str = _require("REALESTATE_API_KEY")

# ---------------------------------------------------------------------------
# Skip Trace / Enrichment API
# ---------------------------------------------------------------------------
SKIPTRACE_API_BASE_URL: str = _require("SKIPTRACE_API_BASE_URL")
SKIPTRACE_API_KEY: str = _require("SKIPTRACE_API_KEY")

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
GOOGLE_CREDENTIALS_PATH: str = _require("GOOGLE_CREDENTIALS_PATH")
GOOGLE_SHEET_ID: str = _require("GOOGLE_SHEET_ID")
GOOGLE_SHEET_TAB_NAME: str = _optional("GOOGLE_SHEET_TAB_NAME", "Leads")

# ---------------------------------------------------------------------------
# Pipeline Runtime Parameters
# ---------------------------------------------------------------------------
TARGET_ZIP_CODES: list[str] = [
    z.strip() for z in _optional("TARGET_ZIP_CODES", "90210").split(",") if z.strip()
]
PROPERTIES_PER_ZIP: int = int(_optional("PROPERTIES_PER_ZIP", "50"))

# ---------------------------------------------------------------------------
# Rate-limiting & Retry
# ---------------------------------------------------------------------------
REQUEST_DELAY_SECONDS: float = float(_optional("REQUEST_DELAY_SECONDS", "1.5"))
MAX_RETRIES: int = int(_optional("MAX_RETRIES", "3"))
RETRY_BACKOFF_FACTOR: float = float(_optional("RETRY_BACKOFF_FACTOR", "2.0"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = _optional("LOG_LEVEL", "INFO").upper()
LOG_FILE: str = _optional("LOG_FILE", "pipeline.log")
