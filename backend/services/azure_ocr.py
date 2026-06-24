"""Azure Document Intelligence (prebuilt-read) OCR client.

Submit-then-poll against the async analyze API:
  1. POST {endpoint}/documentintelligence/documentModels/prebuilt-read:analyze
     with the raw document bytes -> 202 + Operation-Location header.
  2. GET the operation URL until status is succeeded/failed, bounded by a
     hard deadline (POLL_DEADLINE_S).

Transient submit failures (429 / 5xx / transport) are retried up to
SUBMIT_RETRIES times with linear backoff. Configuration comes from
settings.azure_di_endpoint / settings.azure_di_key — when unset, callers get
AzureOcrNotConfigured so the router can answer 503 with a clear message.
"""
from __future__ import annotations

import logging
import time

import httpx

from lib.config import settings

log = logging.getLogger(__name__)

API_VERSION = "2024-11-30"
SUBMIT_RETRIES = 3          # retries AFTER the first attempt (4 attempts total)
POLL_DEADLINE_S = 20.0
POLL_INTERVAL_S = 0.75
_REQUEST_TIMEOUT_S = 15.0

# Test seam — monkeypatch to a no-op so retry/poll tests run instantly.
_sleep = time.sleep


class AzureOcrNotConfigured(Exception):
    """Raised when AZURE_DI_ENDPOINT / AZURE_DI_KEY are not set."""


class AzureOcrError(Exception):
    """Raised on a hard Azure DI failure (after retries / poll timeout)."""


def configured() -> bool:
    return bool(settings.azure_di_endpoint and settings.azure_di_key)


def _client() -> httpx.Client:
    """Test seam — monkeypatch to return a Client with httpx.MockTransport."""
    return httpx.Client(timeout=_REQUEST_TIMEOUT_S)


def read_text(document_bytes: bytes, mime_type: str) -> str:
    """OCR a document/image and return its full extracted text."""
    if not configured():
        raise AzureOcrNotConfigured(
            "Azure Document Intelligence is not configured — set "
            "AZURE_DI_ENDPOINT and AZURE_DI_KEY."
        )
    submit_url = (
        settings.azure_di_endpoint.rstrip("/")
        + f"/documentintelligence/documentModels/prebuilt-read:analyze"
        + f"?api-version={API_VERSION}"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": settings.azure_di_key,
        "Content-Type": mime_type or "application/octet-stream",
    }
    with _client() as client:
        operation_url = _submit(client, submit_url, headers, document_bytes)
        return _poll(client, operation_url)


def _submit(client: httpx.Client, url: str, headers: dict, data: bytes) -> str:
    last_error = "unknown"
    for attempt in range(SUBMIT_RETRIES + 1):
        if attempt:
            _sleep(0.5 * attempt)  # linear backoff between retries
        try:
            r = client.post(url, headers=headers, content=data)
        except httpx.HTTPError as e:
            last_error = f"transport error: {e}"
            continue
        if r.status_code in (200, 202):
            operation_url = r.headers.get("operation-location")
            if not operation_url:
                raise AzureOcrError("Azure DI accepted the document but returned "
                                    "no Operation-Location header")
            return operation_url
        if r.status_code == 429 or r.status_code >= 500:
            last_error = f"HTTP {r.status_code}"
            continue
        # 4xx other than 429 — a retry can't fix the request
        raise AzureOcrError(f"Azure DI rejected the document (HTTP {r.status_code})")
    raise AzureOcrError(f"Azure DI submit failed after "
                        f"{SUBMIT_RETRIES + 1} attempts ({last_error})")


def _poll(client: httpx.Client, operation_url: str) -> str:
    headers = {"Ocp-Apim-Subscription-Key": settings.azure_di_key}
    deadline = time.monotonic() + POLL_DEADLINE_S
    while time.monotonic() < deadline:
        try:
            r = client.get(operation_url, headers=headers)
        except httpx.HTTPError as e:
            log.info("azure ocr poll transport error (retrying): %s", e)
            _sleep(POLL_INTERVAL_S)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            _sleep(POLL_INTERVAL_S)
            continue
        if r.status_code != 200:
            raise AzureOcrError(f"Azure DI poll failed (HTTP {r.status_code})")
        body = r.json()
        status = str(body.get("status") or "").lower()
        if status == "succeeded":
            return str((body.get("analyzeResult") or {}).get("content") or "")
        if status == "failed":
            err = (body.get("error") or {}).get("message") or "analysis failed"
            raise AzureOcrError(f"Azure DI analysis failed: {err}")
        _sleep(POLL_INTERVAL_S)  # notStarted / running
    raise AzureOcrError(f"Azure DI analysis timed out after {int(POLL_DEADLINE_S)}s")
