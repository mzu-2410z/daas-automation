"""
data_processor.py
-----------------
All data wrangling lives here.

Responsibilities:
  - Merge raw property records with skip-trace contact data.
  - Normalise and clean every field.
  - Format phone numbers to E.164 standard (+1XXXXXXXXXX for US numbers).
  - Drop rows that lack an actionable Phone 1.
  - Return a clean pandas DataFrame with standardised column headers
    ready for Google Sheets insertion.
"""

import re
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Final column order as it will appear in the Google Sheet.
OUTPUT_COLUMNS: list[str] = [
    "Property Address",
    "City",
    "State",
    "ZIP",
    "Owner Name",
    "Default Type",
    "Default Amount",
    "Estimated Equity",
    "Phone 1",
    "Phone 2",
    "Email",
]

# Raw field names coming from the real estate API response.
_REALESTATE_FIELD_MAP: dict[str, str] = {
    "address":          "Property Address",
    "city":             "City",
    "state":            "State",
    "zip":              "ZIP",
    "owner_name":       "Owner Name",
    "default_type":     "Default Type",
    "default_amount":   "Default Amount",
    "estimated_equity": "Estimated Equity",
}

# Raw field names coming from the skip trace response.
_SKIPTRACE_FIELD_MAP: dict[str, str] = {
    "phone_1": "Phone 1",
    "phone_2": "Phone 2",
    "email":   "Email",
}


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------

def _normalise_phone(raw: Any) -> str:
    """
    Attempt to convert a raw phone value to E.164 format (+1XXXXXXXXXX).

    Rules:
      - Strip all non-digit characters.
      - If 10 digits remain, prepend US country code (1).
      - If 11 digits and starts with 1, keep as-is.
      - Anything else is treated as unparseable → return empty string.

    This is a best-effort US-centric normaliser.  Swap in a library such
    as `phonenumbers` for international support.
    """
    if not raw:
        return ""

    digits = re.sub(r"\D", "", str(raw))

    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"

    logger.debug("[data_processor] Unparseable phone value dropped: '%s'", raw)
    return ""


# ---------------------------------------------------------------------------
# Core pipeline functions
# ---------------------------------------------------------------------------

def merge_records(
    property_records: list[dict[str, Any]],
    skip_trace_results: list[dict[str, str]],
) -> pd.DataFrame:
    """
    Combine property records (list of dicts) with skip trace results
    (parallel list of dicts, same order / length) into a single DataFrame.

    Both lists must be the same length – each index corresponds to the
    same property.
    """
    if len(property_records) != len(skip_trace_results):
        raise ValueError(
            f"[data_processor] Length mismatch: "
            f"{len(property_records)} property records vs "
            f"{len(skip_trace_results)} skip trace results."
        )

    merged: list[dict[str, Any]] = []
    for prop, contact in zip(property_records, skip_trace_results):
        row = {**prop, **contact}
        merged.append(row)

    df = pd.DataFrame(merged)
    logger.info("[data_processor] Merged DataFrame shape: %s", df.shape)
    return df


def clean_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform the merged raw DataFrame into the clean output schema.

    Steps:
      1. Rename columns to human-readable headers.
      2. Ensure all expected columns exist (fill missing ones with empty string).
      3. Normalise phone numbers to E.164.
      4. Strip leading/trailing whitespace from string fields.
      5. Drop rows where Phone 1 is null/empty (non-actionable leads).
      6. Reset index and enforce final column order.
    """
    df = raw_df.copy()

    # ---- 1. Rename raw fields -------------------------------------------
    rename_map = {**_REALESTATE_FIELD_MAP, **_SKIPTRACE_FIELD_MAP}
    df.rename(columns=rename_map, inplace=True)

    # ---- 2. Guarantee all output columns exist --------------------------
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            logger.debug("[data_processor] Adding missing column: '%s'", col)
            df[col] = ""

    df = df[OUTPUT_COLUMNS]  # Enforce order and drop unknown columns.

    # ---- 3. Normalise phone numbers -------------------------------------
    df["Phone 1"] = df["Phone 1"].apply(_normalise_phone)
    df["Phone 2"] = df["Phone 2"].apply(_normalise_phone)

    # ---- 4. Strip whitespace from string columns ------------------------
    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda s: s.str.strip())

    # ---- 5. Drop rows without an actionable Phone 1 --------------------
    before = len(df)
    df = df[df["Phone 1"].notna() & (df["Phone 1"] != "")]
    dropped = before - len(df)
    if dropped:
        logger.info(
            "[data_processor] Dropped %d row(s) with no Phone 1 "
            "(%d actionable leads remaining).",
            dropped,
            len(df),
        )

    # ---- 6. Final tidy-up ----------------------------------------------
    df.reset_index(drop=True, inplace=True)

    # Coerce monetary fields to numeric where possible.
    for col in ("Default Amount", "Estimated Equity"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("[data_processor] Clean DataFrame shape: %s", df.shape)
    return df


def build_clean_dataframe(
    property_records: list[dict[str, Any]],
    skip_trace_results: list[dict[str, str]],
) -> pd.DataFrame:
    """
    Convenience wrapper: merge → clean → return.
    This is the primary entry point called by main.py.
    """
    if not property_records:
        logger.warning("[data_processor] No property records to process.")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    raw_df = merge_records(property_records, skip_trace_results)
    clean_df = clean_dataframe(raw_df)
    return clean_df
