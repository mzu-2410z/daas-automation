"""
main.py
-------
Pipeline orchestrator.

Execution flow:
  1. Configure logging.
  2. Load and validate all configuration (via config.py import).
  3. For each target ZIP code:
       a. Fetch pre-foreclosure records from the real estate API.
       b. For each property, run skip-trace enrichment.
  4. Merge + clean all data with data_processor.
  5. Append clean leads to Google Sheets via gsheet_manager.
  6. Log a run summary.

Run:
    python main.py

For scheduled execution use cron, GitHub Actions, or a cloud scheduler.
"""

import logging
import sys
import time
from typing import Any

import config  # Must be first import so env vars are loaded before others.
import api_client
import data_processor
import gsheet_manager


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    """
    Set up root logger to write to both stdout and a rotating log file.
    Log level is driven by the LOG_LEVEL env var (default: INFO).
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s – %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]

    if config.LOG_FILE:
        try:
            file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
            handlers.append(file_handler)
        except OSError as exc:
            # Don't crash if the log file path is not writable.
            print(f"[main] WARNING: Could not open log file '{config.LOG_FILE}': {exc}")

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format=log_format,
        datefmt=date_format,
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Per-ZIP processing
# ---------------------------------------------------------------------------

def _process_zip(zip_code: str) -> tuple[list[dict], list[dict]]:
    """
    Fetch pre-foreclosure listings for one ZIP code, run skip-trace on each,
    and return parallel (property_records, skip_trace_results) lists.
    """
    logger = logging.getLogger(__name__)

    # ---- Step 1: Real Estate API -----------------------------------------
    try:
        property_records: list[dict[str, Any]] = api_client.fetch_pre_foreclosures(
            zip_code=zip_code,
            limit=config.PROPERTIES_PER_ZIP,
        )
    except api_client.APIError as exc:
        logger.error(
            "[main] Failed to fetch pre-foreclosures for ZIP %s: %s. Skipping.",
            zip_code,
            exc,
        )
        return [], []

    if not property_records:
        logger.info("[main] No records returned for ZIP %s.", zip_code)
        return [], []

    # ---- Step 2: Skip Trace enrichment -----------------------------------
    skip_trace_results: list[dict[str, str]] = []

    for idx, prop in enumerate(property_records, start=1):
        owner_name = prop.get("owner_name", "")
        address    = prop.get("address", "")
        city       = prop.get("city", "")
        state      = prop.get("state", "")

        logger.debug(
            "[main] Skip-tracing record %d/%d: '%s' at '%s'.",
            idx,
            len(property_records),
            owner_name,
            address,
        )

        contact = api_client.skip_trace_owner(
            owner_name=owner_name,
            property_address=address,
            city=city,
            state=state,
            zip_code=zip_code,
        )
        skip_trace_results.append(contact)

        # Additional inter-request delay between skip trace calls
        # (the api_client already sleeps REQUEST_DELAY_SECONDS per call,
        # but we add a small extra buffer here for safety).
        if idx < len(property_records):
            time.sleep(0.5)

    return property_records, skip_trace_results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    """Execute the full DaaS pipeline end-to-end."""
    _configure_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("DaaS Pre-Foreclosure Pipeline – START")
    logger.info("Target ZIP codes : %s", config.TARGET_ZIP_CODES)
    logger.info("Properties / ZIP : %d", config.PROPERTIES_PER_ZIP)
    logger.info("=" * 60)

    all_property_records: list[dict[str, Any]] = []
    all_skip_trace_results: list[dict[str, str]] = []

    # ---- Process each ZIP code -------------------------------------------
    for zip_code in config.TARGET_ZIP_CODES:
        logger.info("[main] ── Processing ZIP code: %s ──", zip_code)
        props, contacts = _process_zip(zip_code)
        all_property_records.extend(props)
        all_skip_trace_results.extend(contacts)

    if not all_property_records:
        logger.warning("[main] No property records collected. Pipeline complete (no-op).")
        return

    logger.info(
        "[main] Total raw records collected across all ZIPs: %d",
        len(all_property_records),
    )

    # ---- Clean & merge ---------------------------------------------------
    logger.info("[main] Building clean DataFrame…")
    try:
        clean_df = data_processor.build_clean_dataframe(
            property_records=all_property_records,
            skip_trace_results=all_skip_trace_results,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[main] Data processing failed: %s", exc)
        sys.exit(1)

    if clean_df.empty:
        logger.warning(
            "[main] Clean DataFrame is empty after filtering "
            "(all leads lacked Phone 1). Nothing to write."
        )
        return

    logger.info("[main] %d actionable leads ready for Google Sheets.", len(clean_df))

    # ---- Append to Google Sheet -----------------------------------------
    logger.info("[main] Appending leads to Google Sheet…")
    try:
        rows_written = gsheet_manager.append_dataframe(clean_df)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[main] Google Sheets write failed: %s", exc)
        sys.exit(1)

    # ---- Summary ---------------------------------------------------------
    logger.info("=" * 60)
    logger.info("DaaS Pre-Foreclosure Pipeline – COMPLETE")
    logger.info("Rows appended to Google Sheet : %d", rows_written)
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()
