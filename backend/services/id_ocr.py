"""Driver's-license / state-ID OCR via Claude vision.

Returns a structured identity dict with name, DOB, license number, address.
Used by `/scan-id` to identify returning patients without making them retype
their data, and to drive an EHR lookup-by-identity.

Design priorities:
  * Quality gate first — a blurry/glare photo gets `{"error": "needs_rescan"}`
    before any AI call.
  * Partial-card handling — a license with three readable fields out of ten
    still returns those three. We never blank the whole result because one
    field was illegible, and we never emit a confidently-wrong value
    (e.g. an invalid two-letter "state" or a malformed date).
  * State-code validation — `issuing_state` and `state` are validated against
    the real 50 states + DC + territories; anything else is dropped.

Never logs PHI — only field-presence booleans and verdict codes.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from services import vision

log = logging.getLogger(__name__)


_SYSTEM = """You are an OCR assistant reading a US driver's license or state-issued ID card.

Output JSON ONLY (no preamble, no markdown fence) in this exact shape:
{
  "is_id_card": true,
  "first_name": "...",
  "middle_name": "...",
  "last_name": "...",
  "dob": "YYYY-MM-DD",
  "license_number": "...",
  "issuing_state": "two-letter US state code, e.g. TX",
  "address": "single-line street address or empty",
  "city": "...",
  "state": "two-letter US state code",
  "zip": "5-digit or ZIP+4",
  "issue_date": "YYYY-MM-DD or empty",
  "expiry": "YYYY-MM-DD or empty",
  "sex": "M" | "F" | "X" | "",
  "height": "as printed, e.g. 5-10, or empty",
  "eye_color": "as printed, or empty",
  "document_type": "drivers_license" | "state_id" | "other"
}

Rules:
- If the image is NOT a government-issued ID, return {"is_id_card": false}.
- Use an empty string for any field you cannot read confidently. NEVER guess —
  a partially readable card should still return whatever IS legible.
- DOB, issue_date and expiry MUST be normalized to YYYY-MM-DD. Convert from
  MM/DD/YYYY, MM-DD-YYYY, or labels like 'DOB 01-15-1982'.
- issuing_state and state MUST be the two-letter postal code (TX, CA, NY, ...).
- Strip honorifics from names (no "Dr.", "Mr.", etc).
"""


# 50 states + DC + the 5 inhabited US territories. Used to reject OCR noise
# masquerading as a state code.
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}

# Fields that constitute a "usable" identity result.
_KEY_FIELDS = ("first_name", "last_name", "dob")


def extract(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Run Claude vision on the ID image. Always returns a dict.

    Return shapes (routers/identity.py branches on the `error` key):
      * empty image          -> {"error": "empty_image"}
      * bad photo            -> {"error": "needs_rescan", "reason", "message"}
      * no AI key            -> {"error": "ocr_unavailable"}
      * not an ID            -> {"error": "not_an_id_card"}
      * provider/parse error -> {"error": "ocr_failed" | "ocr_parse_failed"}
      * success / partial    -> cleaned field dict (no `error` key) carrying
                                `_completeness`, `_partial`, and `_warnings`.

    A partially readable card is a SUCCESS, not an error — it returns the
    legible fields with `_partial: true` so the UI can prompt the patient to
    fill the rest rather than re-scanning a perfectly fine card.
    """
    if not image_bytes:
        return {"error": "empty_image"}

    gate = vision.image_quality_gate(image_bytes)
    if not gate.get("ok"):
        log.info("id_ocr: quality gate rejected photo (%s)", gate.get("reason"))
        return {
            "error": "needs_rescan",
            "reason": gate.get("reason", "image_quality"),
            "message": gate.get("message", "Please retake the photo of the ID."),
        }

    raw = vision.vision_extract(
        image_bytes,
        prompt="Read this ID. Return the JSON object only.",
        system=_SYSTEM,
        mime_type=mime_type,
        purpose="id_ocr",
        max_tokens=700,
    )
    err = raw.get("_error")
    if err == "vision_unavailable":
        return {"error": "ocr_unavailable"}
    if err == "parse_failed":
        return {"error": "ocr_parse_failed"}
    if err:  # empty_image / vision_failed
        return {"error": "ocr_failed"}

    if raw.get("is_id_card") is False:
        return {"error": "not_an_id_card"}

    fields = _clean_id(raw)

    # A card that yielded nothing usable is treated as a failed read, not a
    # silently-empty success — the UI should ask for a rescan.
    if not any(fields.get(k) for k in _KEY_FIELDS):
        log.info("id_ocr: no usable fields extracted")
        return {
            "error": "needs_rescan",
            "reason": "id_unreadable",
            "message": "We couldn't read the ID. Please retake the photo in good light.",
        }

    log.info(
        "id_ocr: extracted ID (name=%s dob=%s lic=%s state=%s completeness=%.2f partial=%s)",
        bool(fields.get("first_name") and fields.get("last_name")),
        bool(fields.get("dob")),
        bool(fields.get("license_number")),
        bool(fields.get("issuing_state")),
        fields["_completeness"],
        fields["_partial"],
    )
    return fields


def extract_fields(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Eligibility-shaped projection — kept symmetric with insurance_ocr so the
    `insurance_to_eligibility` chain can fall through to an ID photo. An ID has
    no payer/member info, so those keys come back empty and the chain reports
    incomplete OCR rather than reaching the synthetic fallback."""
    result = extract(image_bytes, mime_type=mime_type)
    if result.get("error"):
        return {
            "payer_name": "",
            "member_id": "",
            "patient_first": "",
            "patient_last": "",
            "patient_dob": "",
            "_ocr": result,
            "_error": result["error"],
        }
    return {
        "payer_name": "",
        "member_id": "",
        "patient_first": result.get("first_name", ""),
        "patient_last": result.get("last_name", ""),
        "patient_dob": result.get("dob", ""),
        "_ocr": result,
    }


# --- helpers -------------------------------------------------------------------


def _clean_id(obj: dict[str, Any]) -> dict[str, Any]:
    """Allow-list, normalize, and validate. Invalid values become empty rather
    than confidently-wrong; every drop is recorded in `_warnings`."""
    warnings: list[str] = []

    issuing_state = _validate_state(obj.get("issuing_state", ""), "issuing_state", warnings)
    state = _validate_state(obj.get("state", ""), "state", warnings)

    dob = _norm_date(obj.get("dob", ""), "dob", warnings)
    issue_date = _norm_date(obj.get("issue_date", ""), "issue_date", warnings)
    expiry = _norm_date(obj.get("expiry", ""), "expiry", warnings)

    fields: dict[str, Any] = {
        "first_name": _clean(obj.get("first_name", "")),
        "middle_name": _clean(obj.get("middle_name", "")),
        "last_name": _clean(obj.get("last_name", "")),
        "dob": dob,
        "license_number": _norm_license(obj.get("license_number", "")),
        "issuing_state": issuing_state,
        "address": _clean(obj.get("address", "")),
        "city": _clean(obj.get("city", "")),
        "state": state,
        "zip": _norm_zip(obj.get("zip", ""), warnings),
        "issue_date": issue_date,
        "expiry": expiry,
        "sex": _norm_sex(obj.get("sex", "")),
        "height": _clean(obj.get("height", "")),
        "eye_color": _clean(obj.get("eye_color", "")),
        "document_type": _norm_doc_type(obj.get("document_type", "")),
    }

    # Flag an expired ID — useful for the intake nurse, not a hard failure.
    if expiry:
        try:
            y, m, d = (int(x) for x in expiry.split("-"))
            if date(y, m, d) < date.today():
                warnings.append("id_expired")
        except Exception:  # noqa: BLE001
            pass

    present = sum(1 for k in _KEY_FIELDS if fields.get(k))
    fields["_completeness"] = round(present / len(_KEY_FIELDS), 2)
    # Partial = at least one key field present but not all, OR any field dropped.
    fields["_partial"] = present < len(_KEY_FIELDS) or bool(warnings)
    fields["_warnings"] = warnings
    return fields


def _clean(s: Any) -> str:
    txt = str(s or "").strip()
    if txt.lower() in {"null", "none", "n/a", "na", "unknown", ""}:
        return ""
    return txt


def _validate_state(v: Any, label: str, warnings: list[str]) -> str:
    """Two-letter postal code, validated against real US states/territories.
    An unrecognized code is dropped (empty) — never returned as-is."""
    code = _clean(v).upper()[:2]
    if not code:
        return ""
    if code in _US_STATES:
        return code
    warnings.append(f"{label}_invalid")
    return ""


def _norm_date(v: Any, label: str, warnings: list[str]) -> str:
    """Accept ISO, MM/DD/YYYY, MM-DD-YYYY, or 2-digit-year variants. Return a
    real, calendar-valid YYYY-MM-DD or empty (recording a warning on a value
    that looked like a date but didn't parse)."""
    txt = _clean(v)
    if not txt:
        return ""

    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", txt)
    if iso:
        y, m, d = (int(x) for x in iso.groups())
    else:
        us = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", txt)
        if not us:
            warnings.append(f"{label}_unparseable")
            return ""
        mm, dd, yy = us.groups()
        m, d = int(mm), int(dd)
        y = int(yy)
        if y < 100:  # 2-digit year — pivot at 30 (1931-2029 era for IDs)
            y += 1900 if y >= 30 else 2000

    try:
        return date(y, m, d).isoformat()
    except ValueError:
        warnings.append(f"{label}_invalid")
        return ""


def _norm_license(v: Any) -> str:
    """License numbers are alphanumeric with occasional hyphens. Strip label
    text and surrounding whitespace; keep internal structure."""
    s = _clean(v)
    if not s:
        return ""
    s = re.sub(r"(?i)^(dl|lic(ense)?|id|no|number)\s*[:#.]?\s*", "", s).strip()
    return re.sub(r"\s+", "", s).upper()


def _norm_zip(v: Any, warnings: list[str]) -> str:
    """5-digit or ZIP+4. Anything else is dropped."""
    s = _clean(v)
    if not s:
        return ""
    m = re.fullmatch(r"(\d{5})(?:-?\d{4})?", s)
    if m:
        return s if "-" in s else m.group(0)
    warnings.append("zip_invalid")
    return ""


def _norm_sex(v: Any) -> str:
    s = _clean(v).upper()[:1]
    return s if s in {"M", "F", "X"} else ""


def _norm_doc_type(v: Any) -> str:
    s = _clean(v).lower().replace(" ", "_").replace("'", "")
    if "driver" in s or s == "dl":
        return "drivers_license"
    if "state" in s or "id" in s:
        return "state_id"
    return "other" if s else ""
