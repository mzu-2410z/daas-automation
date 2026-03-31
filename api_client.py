"""
api_client.py
-------------
Handles all outbound HTTP communication.

Design principles:
  - Zero hardcoded URLs or secrets (all sourced from config.py).
  - Exponential back-off retry on transient failures (5xx, timeouts).
  - Per-request rate-limit delay to avoid IP bans.
  - Structured logging for every request lifecycle event.
  - Raises typed exceptions so the orchestrator can react appropriately.
"""

import time
import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class APIError(Exception):
    """Raised when an API returns a non-recoverable error response."""


class RateLimitError(APIError):
    """Raised on HTTP 429 – Too Many Requests."""


# ---------------------------------------------------------------------------
# Session Factory
# ---------------------------------------------------------------------------

def _build_session(total_retries: int, backoff_factor: float) -> requests.Session:
    """
    Create a requests.Session pre-configured with:
      - Connection-level retry (handles network blips).
      - Automatic back-off between attempts.
      - Explicit timeout enforced at the call-site.
    
    Note: HTTP 429 / 5xx retries are intentionally *not* delegated to urllib3
    because we want to log each attempt and honour our own delay budget.
    """
    session = requests.Session()
    retry_cfg = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_cfg)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# Shared session – reuses TCP connections across the pipeline run.
_SESSION: requests.Session = _build_session(
    total_retries=config.MAX_RETRIES,
    backoff_factor=config.RETRY_BACKOFF_FACTOR,
)


# ---------------------------------------------------------------------------
# Internal request helper
# ---------------------------------------------------------------------------

def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Execute an HTTP request with:
      - Pre-request rate-limit sleep.
      - Structured request/response logging.
      - Graceful error classification.

    Returns the parsed JSON body as a dict.
    Raises APIError (or subclass) on all non-2xx responses.
    """
    # Honour inter-request delay to avoid triggering API rate limits.
    time.sleep(config.REQUEST_DELAY_SECONDS)

    logger.debug("[api_client] %s %s | params=%s", method.upper(), url, params)

    try:
        response = _SESSION.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        logger.error("[api_client] Request timed out: %s %s", method.upper(), url)
        raise APIError(f"Request timed out: {method.upper()} {url}")
    except requests.exceptions.ConnectionError as exc:
        logger.error("[api_client] Connection error: %s", exc)
        raise APIError(f"Connection error: {exc}") from exc

    # ---- Response classification ----------------------------------------
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        logger.warning(
            "[api_client] HTTP 429 – rate limited. Retry-After: %s", retry_after
        )
        raise RateLimitError(
            f"Rate limited by {url}. Retry-After header: {retry_after}"
        )

    if response.status_code == 401:
        logger.error("[api_client] HTTP 401 – invalid or missing API key for %s", url)
        raise APIError("Authentication failed – check your API key in .env")

    if response.status_code == 403:
        logger.error("[api_client] HTTP 403 – access forbidden for %s", url)
        raise APIError(f"Access forbidden: {url}")

    if not response.ok:
        logger.error(
            "[api_client] HTTP %s error for %s: %s",
            response.status_code,
            url,
            response.text[:500],
        )
        raise APIError(
            f"HTTP {response.status_code} from {url}: {response.text[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("[api_client] Non-JSON response from %s: %s", url, response.text[:200])
        raise APIError(f"Non-JSON response from {url}") from exc

    logger.debug("[api_client] Response OK from %s", url)
    return payload


# ---------------------------------------------------------------------------
# Real Estate Data API
# ---------------------------------------------------------------------------

def fetch_pre_foreclosures(zip_code: str, limit: int = 50) -> list[dict[str, Any]]:
    """
    Pull pre-foreclosure / tax-default listings for a single ZIP code.

    Expected response schema (mocked ATTOM/Estated-style):
    {
        "status": "success",
        "data": [
            {
                "property_id": "...",
                "address": "123 Main St",
                "city": "Los Angeles",
                "state": "CA",
                "zip": "90210",
                "owner_name": "John Doe",
                "estimated_equity": 145000,
                "default_amount": 8200,
                "default_type": "pre-foreclosure"
            },
            ...
        ]
    }
    """
    url = f"{config.REALESTATE_API_BASE_URL}/properties/pre-foreclosures"
    headers = {
        "X-API-Key": config.REALESTATE_API_KEY,
        "Accept": "application/json",
    }
    params = {"zip_code": zip_code, "limit": limit}

    logger.info(
        "[api_client] Fetching pre-foreclosures | zip=%s limit=%s", zip_code, limit
    )

    payload = _request("GET", url, headers=headers, params=params)

    records: list[dict[str, Any]] = payload.get("data", [])
    logger.info(
        "[api_client] Received %d pre-foreclosure record(s) for ZIP %s",
        len(records),
        zip_code,
    )
    return records


# ---------------------------------------------------------------------------
# Skip Trace / Enrichment API
# ---------------------------------------------------------------------------

def skip_trace_owner(
    owner_name: str,
    property_address: str,
    city: str,
    state: str,
    zip_code: str,
) -> dict[str, str]:
    """
    Look up owner contact information via the skip trace API.

    Expected response schema:
    {
        "status": "found",
        "phone_1": "+12135550100",
        "phone_2": "+13105550177",
        "email": "john.doe@example.com"
    }

    Returns a dict with keys: phone_1, phone_2, email.
    Returns an empty dict if the record is not found or the call fails
    (non-fatal; the data_processor will drop rows with null Phone 1).
    """
    url = f"{config.SKIPTRACE_API_BASE_URL}/search"
    headers = {
        "X-API-Key": config.SKIPTRACE_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "owner_name": owner_name,
        "address": property_address,
        "city": city,
        "state": state,
        "zip": zip_code,
    }

    logger.debug(
        "[api_client] Skip-tracing owner='%s' at '%s, %s'",
        owner_name,
        property_address,
        zip_code,
    )

    try:
        payload = _request("POST", url, headers=headers, json_body=body)
    except APIError as exc:
        # Skip trace failures are non-fatal – we log and return empty.
        logger.warning(
            "[api_client] Skip trace failed for '%s' – %s. Row will be dropped.",
            owner_name,
            exc,
        )
        return {}

    contact = {
        "phone_1": payload.get("phone_1", ""),
        "phone_2": payload.get("phone_2", ""),
        "email": payload.get("email", ""),
    }
    logger.debug("[api_client] Skip trace result for '%s': %s", owner_name, contact)
    return contact
