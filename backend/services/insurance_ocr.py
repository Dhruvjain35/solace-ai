"""Claude Vision OCR for US health insurance cards.

Two public surfaces:

  * `extract(image_bytes, mime_type)` — the original card-OCR contract used by
    routers/insurance.py. Runs a no-AI quality gate first; on a bad photo it
    returns `{"error": "needs_rescan", ...}` so the UI asks for a clearer shot
    *before* spending an AI call. On a good photo it returns the full set of
    card fields.

  * `extract_fields(image_bytes)` — eligibility-shaped projection of the same
    OCR result (payer_name / member_id / patient_first / ...). This is the hook
    that `services/insurance_to_eligibility._ocr_image()` looks for; once it
    exists the synthetic "Aetna / Jane Doe" fallback is never reached.

  * `to_eligibility_request(fields)` — map either shape into the kwargs that
    `eligibility.check()` expects.

Never logs PHI — only field-presence booleans, sizes, and verdict codes.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services import vision

log = logging.getLogger(__name__)


_SYSTEM = """You are an OCR assistant reading a photo of a US health insurance card.
You read both the front and (when shown) the back. Be precise; never invent text."""


_PROMPT = """Read this US health insurance card. Extract every field you can see.

Return JSON ONLY, no preamble, no markdown fence:
{
  "is_insurance_card": true,
  "provider": "insurance company / payer name, or null",
  "plan_name": "plan name as printed, or null",
  "plan_type": "one of HMO, PPO, EPO, POS, HDHP, Medicare, Medicaid, or null",
  "member_id": "member / subscriber / ID number, or null",
  "group_number": "group number, or null",
  "name_on_card": "subscriber/member name as printed, or null",
  "dependents": ["other names printed on the card"],
  "rx_bin": "pharmacy RxBIN (usually 6 digits), or null",
  "rx_pcn": "pharmacy RxPCN, or null",
  "rx_group": "pharmacy Rx group, or null",
  "payer_id": "electronic payer ID / claims payer ID, or null",
  "effective_date": "coverage effective date, or null",
  "copay_pcp": "primary-care office-visit copay if printed, or null",
  "copay_specialist": "specialist copay if printed, or null",
  "copay_er": "emergency-room copay if printed, or null",
  "customer_service_phone": "member services phone, or null",
  "claims_address": "claims mailing address if printed, or null",
  "card_side": "front, back, or unknown"
}

Rules:
- Return null (not a guess) for any field that is not clearly legible.
- "member_id" is the subscriber's ID — do NOT confuse it with the group number.
- RxBIN is a pharmacy routing number, often labeled BIN; RxPCN is labeled PCN.
- Normalize plan_type to the closest standard abbreviation if a variant is printed.
- If this is NOT a health insurance card, return exactly: {"is_insurance_card": false}
"""


# Canonical plan types we will accept; anything else is normalized or dropped.
_PLAN_TYPES = {"HMO", "PPO", "EPO", "POS", "HDHP", "MEDICARE", "MEDICAID"}


def extract(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """OCR an insurance card.

    Return shapes (the router branches on the `error` key):
      * bad/unreadable photo -> {"error": "needs_rescan", "reason": ..., "message": ...}
      * empty / no AI key    -> {"error": "empty_image" | "anthropic_key_missing"}
      * not a card           -> {"error": "not_an_insurance_card"}
      * provider/parse error -> {"error": "ocr_failed" | "parse_failed"}
      * success              -> the cleaned field dict (no `error` key), which
                                additionally carries `_quality` and
                                `_completeness` metadata.
    """
    if not image_bytes:
        return {"error": "empty_image"}

    # 1. No-AI quality gate FIRST — do not pay for an AI call on a photo we can
    #    already tell is unreadable.
    gate = vision.image_quality_gate(image_bytes)
    if not gate.get("ok"):
        log.info("insurance_ocr: quality gate rejected photo (%s)", gate.get("reason"))
        return {
            "error": "needs_rescan",
            "reason": gate.get("reason", "image_quality"),
            "message": gate.get("message", "Please retake the photo of the card."),
        }

    # 2. Deterministic vision call — never raises.
    raw = vision.vision_extract(
        image_bytes,
        prompt=_PROMPT,
        system=_SYSTEM,
        mime_type=mime_type,
        purpose="insurance_ocr",
        max_tokens=700,
    )
    err = raw.get("_error")
    if err == "vision_unavailable":
        return {"error": "anthropic_key_missing"}
    if err == "parse_failed":
        return {"error": "parse_failed"}
    if err:  # empty_image / vision_failed
        return {"error": "ocr_failed"}

    if raw.get("is_insurance_card") is False:
        return {"error": "not_an_insurance_card"}

    fields = _clean_card(raw)
    fields["_quality"] = {
        "edge_variance": gate.get("metrics", {}).get("edge_variance"),
        "bright_fraction": gate.get("metrics", {}).get("bright_fraction"),
    }
    fields["_completeness"] = _completeness(fields)
    log.info(
        "insurance_ocr: extracted card (provider=%s member_id=%s rx=%s completeness=%.2f)",
        bool(fields.get("provider")),
        bool(fields.get("member_id")),
        bool(fields.get("rx_bin")),
        fields["_completeness"],
    )
    return fields


def extract_fields(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Eligibility-shaped projection of `extract()`.

    Returns the keys `insurance_to_eligibility` consumes:
      payer_name, member_id, group_number, plan_type, plan_name,
      patient_first, patient_last, patient_dob, rx_bin, rx_pcn,
      and `_ocr` with the full card detail / errors.

    On a failed scan the caller (`insurance_to_eligibility.chain`) sees empty
    `payer_name` / `member_id` and surfaces an "incomplete OCR" message — no
    synthetic fallback is reached because this function now exists.
    """
    card = extract(image_bytes, mime_type=mime_type)
    if card.get("error"):
        return {
            "payer_name": "",
            "member_id": "",
            "patient_first": "",
            "patient_last": "",
            "patient_dob": "",
            "_ocr": card,
            "_error": card["error"],
        }

    first, last = _split_name(card.get("name_on_card", ""))
    return {
        "payer_name": card.get("provider") or "",
        "member_id": card.get("member_id") or "",
        "group_number": card.get("group_number") or "",
        "plan_type": card.get("plan_type") or "",
        "plan_name": card.get("plan_name") or "",
        "patient_first": first,
        "patient_last": last,
        "patient_dob": "",  # not printed on most insurance cards
        "rx_bin": card.get("rx_bin") or "",
        "rx_pcn": card.get("rx_pcn") or "",
        "_ocr": card,
    }


def to_eligibility_request(fields: dict[str, Any]) -> dict[str, str]:
    """Map an OCR result (either `extract()` or `extract_fields()` shape) into
    the kwargs `eligibility.check()` accepts.

    Accepts loose input — both `payer_name`/`provider` and
    `patient_first`/`first_name` styles are tolerated so callers can pass
    whichever shape they hold.
    """
    fields = fields or {}
    name_first, name_last = _split_name(fields.get("name_on_card", ""))
    return {
        "payer_name": _s(fields.get("payer_name") or fields.get("provider")),
        "member_id": _s(fields.get("member_id")),
        "patient_first": _s(fields.get("patient_first") or fields.get("first_name") or name_first),
        "patient_last": _s(fields.get("patient_last") or fields.get("last_name") or name_last),
        "patient_dob": _s(fields.get("patient_dob") or fields.get("dob")),
    }


# --- helpers -------------------------------------------------------------------


def _clean_card(raw: dict[str, Any]) -> dict[str, Any]:
    """Allow-list and normalize the model output. We never trust arbitrary keys."""
    plan_type = _s(raw.get("plan_type")).upper().replace(" ", "")
    if plan_type and plan_type not in _PLAN_TYPES:
        # Tolerate close variants ("PPO Plan", "HDHP/HSA").
        plan_type = next((p for p in _PLAN_TYPES if p in plan_type), "")

    deps = raw.get("dependents")
    dependents = [_s(d) for d in deps if _s(d)] if isinstance(deps, list) else []

    return {
        "provider": _s(raw.get("provider")) or None,
        "plan_name": _s(raw.get("plan_name")) or None,
        "plan_type": plan_type or None,
        "member_id": _norm_id(raw.get("member_id")) or None,
        "group_number": _norm_id(raw.get("group_number")) or None,
        "name_on_card": _s(raw.get("name_on_card")) or None,
        "dependents": dependents,
        "rx_bin": _norm_rx_bin(raw.get("rx_bin")) or None,
        "rx_pcn": _s(raw.get("rx_pcn")) or None,
        "rx_group": _s(raw.get("rx_group")) or None,
        "payer_id": _s(raw.get("payer_id")) or None,
        "effective_date": _s(raw.get("effective_date")) or None,
        "copay_pcp": _s(raw.get("copay_pcp")) or None,
        "copay_specialist": _s(raw.get("copay_specialist")) or None,
        "copay_er": _s(raw.get("copay_er")) or None,
        "customer_service_phone": _s(raw.get("customer_service_phone")) or None,
        "claims_address": _s(raw.get("claims_address")) or None,
        "card_side": _s(raw.get("card_side")).lower() or "unknown",
    }


# Fields that matter for a usable card. completeness = fraction present.
_KEY_FIELDS = ("provider", "member_id", "group_number", "plan_type", "name_on_card")


def _completeness(fields: dict[str, Any]) -> float:
    present = sum(1 for k in _KEY_FIELDS if fields.get(k))
    return round(present / len(_KEY_FIELDS), 2)


def _s(v: Any) -> str:
    """String-ify, strip, and reject model null-isms."""
    s = str(v or "").strip()
    if s.lower() in {"null", "none", "n/a", "na", "not visible", "unknown", ""}:
        return ""
    return s


def _norm_id(v: Any) -> str:
    """Member / group IDs: keep alphanumerics and a few separators, drop label
    text like 'ID:' that OCR sometimes pulls in."""
    s = _s(v)
    if not s:
        return ""
    s = re.sub(r"(?i)^(member|subscriber|group|id|grp|no)\s*[:#.]?\s*", "", s).strip()
    # Collapse internal whitespace; cards print IDs with spaces sometimes.
    return re.sub(r"\s+", "", s)


def _norm_rx_bin(v: Any) -> str:
    """RxBIN is a 6-digit pharmacy routing number. Keep digits only; reject
    anything that isn't 5-7 digits to avoid confidently-wrong values."""
    s = re.sub(r"\D", "", _s(v))
    return s if 5 <= len(s) <= 7 else ""


def _split_name(full: Any) -> tuple[str, str]:
    """Best-effort first/last split of a name printed on a card.

    Handles 'LAST, FIRST' and 'FIRST MIDDLE LAST'. Returns ("", "") when the
    name is unreadable rather than guessing."""
    s = _s(full)
    if not s:
        return "", ""
    if "," in s:
        last, _, first = s.partition(",")
        return _titlecase(first.strip().split(" ")[0]), _titlecase(last.strip())
    parts = [p for p in s.split() if p]
    if len(parts) == 1:
        return _titlecase(parts[0]), ""
    return _titlecase(parts[0]), _titlecase(parts[-1])


def _titlecase(s: str) -> str:
    """Title-case names printed in ALL CAPS without mangling already-mixed case."""
    return s.title() if s.isupper() else s
