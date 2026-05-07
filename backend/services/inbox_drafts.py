"""Inbox auto-draft replies + abnormal-result patient communication.

Two related surfaces:

1. **Patient message reply draft** — given an inbound patient portal message + the
   patient's chart context, produce a clinician-edit-then-send draft. Safety:
   never suggests specific dosing, escalates to clinician for red-flag content,
   refuses topics outside scope (legal, financial), uses 6th-grade language.

2. **Abnormal lab/result reply** — same machinery but seeded with the abnormal
   result and reference range. Includes plain-language explanation, the action
   the clinician recommends, and clear next-step instructions.

Both surface a `requires_clinician_review` flag (always True under FDA's
human-in-loop carve-out) and a `red_flags` list for triage routing.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_RED_FLAG_PATTERNS = [
    (r"\bchest pain\b", "chest pain"),
    (r"\b(short(ness)? of breath|sob|trouble breathing)\b", "shortness of breath"),
    (r"\b(suicid|kill myself|hurt myself|end my life)\b", "suicidality"),
    (r"\b(stroke|face droop|slurred speech|one[ -]sided weakness)\b", "stroke symptoms"),
    (r"\b(heavy bleeding|hemorrhage|black stool|coffee[ -]ground)\b", "active bleeding"),
    (r"\b(passed out|fainted|syncope)\b", "syncope"),
    (r"\b(allerg.*reaction|throat (closing|swelling)|anaphylax)\b", "anaphylaxis"),
    (r"\b(can'?t (urinate|pee)|abdominal swelling|vomit.*blood)\b", "acute abdomen"),
    (r"\bpregnan.*(bleed|pain)\b", "obstetric red flag"),
]


def detect_red_flags(text: str) -> list[str]:
    t = (text or "").lower()
    out = []
    for pat, label in _RED_FLAG_PATTERNS:
        if re.search(pat, t):
            out.append(label)
    return list(dict.fromkeys(out))


_REPLY_SYSTEM = """You draft empathetic, plain-language patient portal message replies for a US-licensed clinician. \
The reply will be reviewed and edited by the clinician before sending — you are drafting, not sending.

Hard rules:
- Never recommend specific drug doses ("take 400 mg of ibuprofen"). You may name a drug class only if the chart shows it's been prescribed.
- 6th-grade reading level. No jargon. Short paragraphs.
- If red flags appear (chest pain, suicidality, stroke symptoms, anaphylaxis, heavy bleeding, syncope, severe pregnancy symptoms): the entire reply MUST instruct the patient to call 911 or go to the ED immediately, and route to the clinician for urgent review.
- Do NOT give legal, financial, or insurance advice. Refer to the office.
- Sign with "Your care team at {hospital_name}" — never name a specific clinician.
- 80-160 words.

Return JSON ONLY:
{
  "draft": "the message body",
  "red_flags": ["..."],
  "tone": "empathetic | matter-of-fact | urgent",
  "requires_clinician_review": true,
  "suggested_action": "send_after_review | escalate_now | call_patient"
}
"""


def draft_reply(
    inbound_message: str,
    *,
    patient_chart: dict[str, Any] | None = None,
    hospital_name: str = "our clinic",
) -> dict[str, Any]:
    rf = detect_red_flags(inbound_message)
    if not settings.anthropic_api_key:
        return {
            "draft": "(AI not configured — please reply manually)",
            "red_flags": rf,
            "tone": "matter-of-fact",
            "requires_clinician_review": True,
            "suggested_action": "escalate_now" if rf else "send_after_review",
        }
    payload = {
        "inbound_message": inbound_message,
        "patient_chart": patient_chart or {},
        "hospital_name": hospital_name,
        "red_flags_detected": rf,
    }
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_REPLY_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
            purpose="inbox_draft",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(text)
    except Exception as e:
        log.warning("inbox draft failed: %s", e)
        out = {"draft": "(draft failed — please reply manually)", "tone": "matter-of-fact"}
    out["red_flags"] = rf
    out["requires_clinician_review"] = True
    if rf and out.get("suggested_action") not in ("escalate_now", "call_patient"):
        out["suggested_action"] = "escalate_now"
    return out


# ---- Abnormal-result triage + plain-language draft -------------------------------
_ABNORMAL_REFS: dict[str, dict[str, Any]] = {
    "a1c": {"low": None, "high": 5.7, "unit": "%", "lay": "long-term blood sugar"},
    "glucose_fasting": {"low": 70, "high": 99, "unit": "mg/dL", "lay": "fasting blood sugar"},
    "tsh": {"low": 0.4, "high": 4.0, "unit": "mIU/L", "lay": "thyroid hormone"},
    "ldl": {"low": None, "high": 130, "unit": "mg/dL", "lay": "bad cholesterol"},
    "potassium": {"low": 3.5, "high": 5.1, "unit": "mEq/L", "lay": "potassium"},
    "sodium": {"low": 135, "high": 145, "unit": "mEq/L", "lay": "sodium"},
    "creatinine": {"low": 0.5, "high": 1.3, "unit": "mg/dL", "lay": "kidney marker"},
    "hemoglobin": {"low": 12, "high": 17, "unit": "g/dL", "lay": "blood iron"},
    "wbc": {"low": 4.0, "high": 11.0, "unit": "K/uL", "lay": "infection-fighting cell count"},
    "platelets": {"low": 150, "high": 400, "unit": "K/uL", "lay": "clotting cells"},
    "alt": {"low": None, "high": 40, "unit": "U/L", "lay": "liver enzyme"},
    "ast": {"low": None, "high": 40, "unit": "U/L", "lay": "liver enzyme"},
}


def classify_lab(name: str, value: float) -> dict[str, Any]:
    n = name.lower().replace(" ", "_")
    ref = _ABNORMAL_REFS.get(n)
    if not ref:
        return {"name": name, "value": value, "status": "unknown_reference"}
    low, high = ref["low"], ref["high"]
    status = "normal"
    if low is not None and value < low:
        status = "low"
    elif high is not None and value > high:
        # critical thresholds
        if n == "potassium" and value > 6.0:
            status = "critical_high"
        elif n == "potassium" and value < 3.0:
            status = "critical_low"
        elif n == "a1c" and value >= 9.0:
            status = "critical_high"
        else:
            status = "high"
    return {"name": name, "value": value, "unit": ref["unit"], "lay_name": ref["lay"], "status": status, "ref_low": low, "ref_high": high}


_RESULT_DRAFT_SYSTEM = """You draft a plain-language explanation of a lab/imaging result for a patient. \
6th-grade reading level. Empathetic, calm, no jargon. <= 120 words.

Hard rules:
- Critical results (e.g. potassium > 6 or < 3, A1c >= 9, hemoglobin < 7, WBC < 1) MUST instruct the patient to contact the office today or go to the ED if office is closed.
- No specific drug dosing.
- Sign with "Your care team."
- Return JSON: {"draft": "...", "urgency": "routine | same_day | go_now"}"""


def draft_result_message(lab_name: str, value: float, *, recommended_action: str = "") -> dict[str, Any]:
    cls = classify_lab(lab_name, value)
    if not settings.anthropic_api_key:
        return {"classification": cls, "draft": "(AI not configured)"}
    user = json.dumps({"classification": cls, "recommended_action": recommended_action})
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=400,
            system=_RESULT_DRAFT_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="result_draft",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(text)
    except Exception as e:
        log.warning("result draft failed: %s", e)
        out = {"draft": "(draft failed)", "urgency": "routine"}
    out["classification"] = cls
    if cls["status"].startswith("critical"):
        out["urgency"] = "go_now"
    return out
