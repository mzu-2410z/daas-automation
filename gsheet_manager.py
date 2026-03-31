"""
gsheet_manager.py
-----------------
Manages all interaction with the target Google Sheet.

Responsibilities:
  - Authenticate via a Google Service Account JSON credentials file.
  - Open the target spreadsheet by ID (never by name – IDs are stable).
  - Find the first truly empty row so we never overwrite existing leads.
  - Append a cleaned pandas DataFrame as new rows.
  - Handle quota errors gracefully with a logged warning.
"""

import logging
import time
from typing import Any

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OAuth scopes required for read + write access to Sheets (and Drive metadata).
# ---------------------------------------------------------------------------
_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _get_gspread_client() -> gspread.Client:
    """
    Build and return an authenticated gspread client using the Service Account
    credentials file path configured in .env.

    Raises:
        FileNotFoundError: If the credentials file does not exist at the path.
        google.auth.exceptions.MutualTLSChannelError / similar: On auth failure.
    """
    creds_path = config.GOOGLE_CREDENTIALS_PATH

    logger.debug("[gsheet_manager] Loading credentials from: %s", creds_path)

    try:
        creds = Credentials.from_service_account_file(creds_path, scopes=_SCOPES)
    except FileNotFoundError:
        logger.error(
            "[gsheet_manager] credentials.json not found at '%s'. "
            "Check GOOGLE_CREDENTIALS_PATH in your .env file.",
            creds_path,
        )
        raise

    client = gspread.authorize(creds)
    logger.info("[gsheet_manager] Google Sheets client authenticated successfully.")
    return client


# ---------------------------------------------------------------------------
# Sheet helpers
# ---------------------------------------------------------------------------

def _open_worksheet(client: gspread.Client) -> gspread.Worksheet:
    """
    Open the target worksheet by sheet ID and tab name (both from config).
    """
    try:
        spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(
            "[gsheet_manager] Spreadsheet with ID '%s' not found. "
            "Ensure the sheet ID is correct and the service account has been "
            "shared on this spreadsheet.",
            config.GOOGLE_SHEET_ID,
        )
        raise

    try:
        worksheet = spreadsheet.worksheet(config.GOOGLE_SHEET_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        logger.error(
            "[gsheet_manager] Tab '%s' not found in spreadsheet '%s'.",
            config.GOOGLE_SHEET_TAB_NAME,
            spreadsheet.title,
        )
        raise

    logger.info(
        "[gsheet_manager] Opened worksheet '%s' in '%s'.",
        worksheet.title,
        spreadsheet.title,
    )
    return worksheet


def _find_next_empty_row(worksheet: gspread.Worksheet) -> int:
    """
    Return the 1-based row index of the first completely empty row.

    Strategy: fetch all values once (single API call) and count populated rows.
    Adding 1 gives us the next empty row.  This approach is safe even when
    rows have been manually deleted leaving gaps.
    """
    all_values: list[list[Any]] = worksheet.get_all_values()
    # Filter out rows that are entirely empty strings.
    non_empty_rows = [row for row in all_values if any(cell.strip() for cell in row)]
    next_row = len(non_empty_rows) + 1
    logger.debug("[gsheet_manager] Next empty row index: %d", next_row)
    return next_row


def _write_header_if_needed(
    worksheet: gspread.Worksheet,
    columns: list[str],
    next_row: int,
) -> int:
    """
    If the sheet is completely empty (next_row == 1), write the column headers
    as row 1 and return 2 (the first data row).
    Otherwise return next_row unchanged.
    """
    if next_row == 1:
        logger.info("[gsheet_manager] Sheet is empty – writing column headers.")
        worksheet.update(
            range_name="A1",
            values=[columns],
        )
        return 2  # Data starts on row 2.
    return next_row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_dataframe(df: pd.DataFrame) -> int:
    """
    Authenticate, locate the next empty row, and append all rows of `df`
    to the configured Google Sheet tab.

    Returns:
        int: Number of rows successfully appended.

    Raises:
        gspread.exceptions.APIError: On quota exhaustion or other Sheets errors.
    """
    if df.empty:
        logger.warning("[gsheet_manager] DataFrame is empty – nothing to append.")
        return 0

    client = _get_gspread_client()
    worksheet = _open_worksheet(client)
    next_row = _find_next_empty_row(worksheet)

    # Write headers only when the sheet starts fresh.
    next_row = _write_header_if_needed(worksheet, list(df.columns), next_row)

    # Serialise DataFrame to a list-of-lists (gspread's native input format).
    # Replace NaN / NaT with empty string for clean cells.
    rows: list[list[Any]] = (
        df.fillna("")
        .astype(str)
        .values.tolist()
    )

    # Build the A1 notation range for the batch update.
    start_cell = f"A{next_row}"

    logger.info(
        "[gsheet_manager] Appending %d row(s) starting at cell %s.",
        len(rows),
        start_cell,
    )

    try:
        worksheet.update(
            range_name=start_cell,
            values=rows,
        )
    except gspread.exceptions.APIError as exc:
        logger.error("[gsheet_manager] Google Sheets API error: %s", exc)
        raise

    logger.info(
        "[gsheet_manager] Successfully appended %d row(s) to '%s'.",
        len(rows),
        worksheet.title,
    )
    return len(rows)
