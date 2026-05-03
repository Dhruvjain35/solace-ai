"""Driver's-license / state-ID OCR via Claude vision.

Returns a structured `IdFields` dict with name, DOB, license number, address.
Used by `/scan-id` to identify returning patients without making them retype
their data, and to drive an EHR lookup-by-identity.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

_SYSTEM = """You are an OCR assistant reading a US driver's license or state-issued ID card.

Output JSON ONLY (no preamble, no markdown fence) in this exact shape:
{
  "is_id_card": true,
  "first_name": "...",
  "last_name": "...",
  "dob": "YYYY-MM-DD",
  "license_number": "...",
  "issuing_state": "TX" or two-letter code,
  "address": "single-line street address or empty",
  "city": "...",
  "state": "...",
  "zip": "...",
  "expiry": "YYYY-MM-DD or empty",
  "sex": "M" | "F" | "X" | ""
}

Rules:
- If the image is NOT a government-issued ID, return {"is_id_card": false}.
- Empty string for fields you can't read confidently. Don't guess.
- DOB and expiry MUST be normalized to YYYY-MM-DD. If only DOB is shown as
  MM/DD/YYYY or 'DOB 01-15-1982', convert.
- Strip honorifics from names (no "Dr.", "Mr.", etc).
"""


def extract(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Run Claude vision on the ID image. Always returns a dict; on failure
    returns {"error": "..."} so the caller renders a clean retry state."""
    if not settings.anthropic_api_key:
        return {"error": "ocr_unavailable"}
    try:
        b64 = base64.standard_b64encode(image_bytes).decode()
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                    {"type": "text", "text": "Read this ID. Return the JSON object only."},
                ],
            }],
            purpose="id_ocr",
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        return _parse(raw)
    except Exception as e:  # noqa: BLE001
        log.exception("id_ocr failed: %s", e)
        return {"error": "ocr_failed"}


def _parse(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {"error": "ocr_parse_failed"}
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"error": "ocr_parse_failed"}
    if not isinstance(obj, dict):
        return {"error": "ocr_parse_failed"}
    if obj.get("is_id_card") is False:
        return {"error": "not_an_id_card"}
    # Normalize fields with explicit allow-list — we do NOT trust arbitrary keys.
    return {
        "first_name": _clean(obj.get("first_name", "")),
        "last_name":  _clean(obj.get("last_name", "")),
        "dob":        _norm_date(obj.get("dob", "")),
        "license_number": _clean(obj.get("license_number", "")),
        "issuing_state":  _clean(obj.get("issuing_state", ""))[:2].upper(),
        "address": _clean(obj.get("address", "")),
        "city":    _clean(obj.get("city", "")),
        "state":   _clean(obj.get("state", "")),
        "zip":     _clean(obj.get("zip", "")),
        "expiry":  _norm_date(obj.get("expiry", "")),
        "sex":     _clean(obj.get("sex", "")).upper()[:1],
    }


def _clean(s: Any) -> str:
    return str(s or "").strip()


def _norm_date(s: Any) -> str:
    """Accept YYYY-MM-DD, MM/DD/YYYY, MM-DD-YYYY. Return YYYY-MM-DD or empty."""
    txt = _clean(s)
    if not txt:
        return ""
    # Already ISO?
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", txt)
    if m:
        return txt
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", txt)
    if m:
        mm, dd, yyyy = m.groups()
        return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
    return ""
