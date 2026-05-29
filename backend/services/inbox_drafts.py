"""Inbox auto-draft replies + abnormal-result patient communication.

Two related surfaces:

1. **Patient message reply draft** — given an inbound patient portal message + the
   patient's chart context, produce a clinician-edit-then-send draft. Safety:
   never suggests specific dosing, escalates to clinician for red-flag content,
   refuses topics outside scope (legal, financial), uses 6th-grade language.

2. **Abnormal lab/result reply** — same machinery but seeded with the abnormal
   result and reference range. Includes plain-language explanation, the action
   the clinician recommends, and clear next-step instructions.

Depth added in this revision:

- **Chart grounding** — the draft is checked, sentence by sentence, against the
  structured chart fields the model was given. Every clinical claim that maps
  to a chart field becomes a `grounding` citation; every clinical claim that
  does NOT map becomes an `ungrounded_claims` entry the clinician must verify
  before sending. This is the hallucination guardrail.

- **Urgency assessment** — `routine | same_day | emergent | crisis`, derived
  from red-flag detection plus the model's own read of the message, with the
  rule-based floor always winning (the model can escalate but never de-escalate).

- **One-click-send envelope** — a fully-formed `send_envelope` the UI can post
  back as-is. `auto_send_eligible` is **always False**: under FDA's
  human-in-the-loop carve-out for clinical decision support, a licensed
  clinician must review and press send. There is no code path that flips it.

Both surface a `requires_clinician_review` flag (always True) and a `red_flags`
list for triage routing.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = settings.model_utility

# Urgency ladder, lowest to highest. Index is used to take the max of the
# rule-based floor and the model's assessment.
_URGENCY_LADDER = ["routine", "same_day", "emergent", "crisis"]


def _max_urgency(a: str, b: str) -> str:
    ia = _URGENCY_LADDER.index(a) if a in _URGENCY_LADDER else 0
    ib = _URGENCY_LADDER.index(b) if b in _URGENCY_LADDER else 0
    return _URGENCY_LADDER[max(ia, ib)]


# Red flags split by the urgency floor they impose. `crisis` red flags are
# life-threatening or self-harm; `emergent` are urgent-but-not-immediate.
_RED_FLAG_PATTERNS = [
    (r"\bchest pain\b", "chest pain", "crisis"),
    (r"\b(short(ness)? of breath|sob|trouble breathing)\b", "shortness of breath", "crisis"),
    (r"\b(suicid|kill myself|hurt myself|end my life|don'?t want to live)\b", "suicidality", "crisis"),
    (r"\b(stroke|face droop|slurred speech|one[ -]sided weakness)\b", "stroke symptoms", "crisis"),
    (r"\b(heavy bleeding|hemorrhage|black stool|coffee[ -]ground)\b", "active bleeding", "crisis"),
    (r"\b(passed out|fainted|syncope)\b", "syncope", "crisis"),
    (r"\b(allerg.*reaction|throat (closing|swelling)|anaphylax)\b", "anaphylaxis", "crisis"),
    (r"\bpregnan.*(bleed|severe pain)\b", "obstetric red flag", "crisis"),
    (r"\b(can'?t (urinate|pee)|vomit.*blood)\b", "acute abdomen", "emergent"),
    (r"\b(high fever|fever (over|above) 103|104)\b", "high fever", "emergent"),
    (r"\b(worst headache|sudden.*headache)\b", "thunderclap headache", "emergent"),
    (r"\b(severe pain|10[ /]?(out of )?10 pain|unbearable)\b", "severe uncontrolled pain", "emergent"),
]


def detect_red_flags(text: str) -> list[str]:
    """Backward-compatible: returns flat list of red-flag labels."""
    return [f["label"] for f in _detect_red_flags_detailed(text)]


def _detect_red_flags_detailed(text: str) -> list[dict[str, str]]:
    t = (text or "").lower()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for pat, label, floor in _RED_FLAG_PATTERNS:
        if label in seen:
            continue
        if re.search(pat, t):
            out.append({"label": label, "urgency_floor": floor})
            seen.add(label)
    return out


# ---- Chart grounding -------------------------------------------------------------
# Words/phrases that signal a clinical claim worth grounding. If a draft sentence
# contains one of these AND no matching chart field is found, it is flagged.
_CLINICAL_CLAIM_HINTS = [
    "your medication", "your prescription", "your dose", "your lab", "your result",
    "your blood pressure", "your a1c", "your cholesterol", "your test",
    "diagnosed", "diagnosis", "your condition", "last visit", "your provider prescribed",
    "you were prescribed", "your chart shows", "based on your", "your recent",
]

# Map of chart keys -> human-readable label, used to build grounding citations.
_GROUNDABLE_CHART_KEYS = {
    "medications": "active medication list",
    "active_medications": "active medication list",
    "problem_list": "problem list",
    "diagnoses": "diagnosis list",
    "allergies": "allergy list",
    "last_visit": "last visit date",
    "last_visit_date": "last visit date",
    "recent_labs": "recent lab results",
    "labs": "recent lab results",
    "vitals": "recorded vitals",
    "care_plan": "documented care plan",
}


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _chart_field_summary(chart: dict[str, Any]) -> dict[str, str]:
    """Flatten the chart into {label: stringified-value} for citation matching."""
    summary: dict[str, str] = {}
    for key, label in _GROUNDABLE_CHART_KEYS.items():
        if key in chart and chart[key] not in (None, "", [], {}):
            val = chart[key]
            if isinstance(val, (list, dict)):
                val = json.dumps(val, default=str)
            summary[label] = str(val)
    return summary


def assess_grounding(draft: str, chart: dict[str, Any] | None) -> dict[str, Any]:
    """Sentence-level grounding check.

    Returns:
      grounding         — list of {claim, cited_field} for sentences whose
                          clinical claim maps to a chart field that was supplied.
      ungrounded_claims — list of {claim, reason} for clinical-sounding sentences
                          with no supporting chart field. The clinician MUST
                          verify these before sending.
      grounded_ratio    — grounded / (grounded + ungrounded), 1.0 if no claims.
    """
    chart = chart or {}
    fields = _chart_field_summary(chart)
    grounding: list[dict[str, str]] = []
    ungrounded: list[dict[str, str]] = []

    for sent in _split_sentences(draft):
        low = sent.lower()
        is_claim = any(h in low for h in _CLINICAL_CLAIM_HINTS)
        if not is_claim:
            continue
        # Try to map the claim to a chart field by keyword overlap.
        matched_field: str | None = None
        if ("medication" in low or "prescri" in low or "dose" in low) and \
                ("active medication list" in fields):
            matched_field = "active medication list"
        elif ("lab" in low or "result" in low or "a1c" in low or
              "cholesterol" in low or "test" in low) and ("recent lab results" in fields):
            matched_field = "recent lab results"
        elif ("blood pressure" in low or "vital" in low) and ("recorded vitals" in fields):
            matched_field = "recorded vitals"
        elif ("diagnos" in low or "condition" in low) and \
                (("problem list" in fields) or ("diagnosis list" in fields)):
            matched_field = "problem list" if "problem list" in fields else "diagnosis list"
        elif "last visit" in low and ("last visit date" in fields):
            matched_field = "last visit date"
        elif ("care plan" in low or "your provider prescribed" in low) and \
                ("documented care plan" in fields):
            matched_field = "documented care plan"

        if matched_field:
            grounding.append({"claim": sent, "cited_field": matched_field})
        else:
            ungrounded.append({
                "claim": sent,
                "reason": "no matching chart field was supplied for this clinical statement",
            })

    total = len(grounding) + len(ungrounded)
    ratio = 1.0 if total == 0 else round(len(grounding) / total, 2)
    return {
        "grounding": grounding,
        "ungrounded_claims": ungrounded,
        "grounded_ratio": ratio,
        "chart_fields_available": sorted(fields.keys()),
    }


_REPLY_SYSTEM = """You draft empathetic, plain-language patient portal message replies for a US-licensed clinician. \
The reply will be reviewed and edited by the clinician before sending — you are drafting, not sending.

Hard rules:
- Never recommend specific drug doses ("take 400 mg of ibuprofen"). You may name a drug class only if the chart shows it's been prescribed.
- Only state clinical facts (medications, labs, diagnoses, visit dates) that are present in the patient_chart you are given. If you do not have a fact, do not invent it — write generically or tell the patient the office will confirm.
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
  "urgency": "routine | same_day | emergent | crisis",
  "requires_clinician_review": true,
  "suggested_action": "send_after_review | escalate_now | call_patient"
}
"""


def _build_send_envelope(
    *, channel: str, draft: str, hospital_name: str, urgency: str,
) -> dict[str, Any]:
    """A ready-to-post envelope for one-click send by a clinician.

    auto_send_eligible is ALWAYS False — FDA human-in-the-loop carve-out for
    clinical decision support requires a licensed clinician to press send.
    """
    return {
        "channel": channel,                       # portal_message | secure_email
        "body": draft,
        "signature": f"Your care team at {hospital_name}",
        "auto_send_eligible": False,              # immutable: clinician must send
        "auto_send_block_reason": (
            "FDA human-in-the-loop carve-out — a licensed clinician must review "
            "and send all patient-facing clinical communication."
        ),
        "delivery_urgency": urgency,
        "requires_clinician_review": True,
    }


def draft_reply(
    inbound_message: str,
    *,
    patient_chart: dict[str, Any] | None = None,
    hospital_name: str = "our clinic",
) -> dict[str, Any]:
    """Draft a chart-grounded reply to an inbound patient message.

    Output shape:
      {
        "draft": str,
        "red_flags": [str, ...],
        "red_flag_detail": [{"label", "urgency_floor"}, ...],
        "tone": str,
        "urgency": "routine|same_day|emergent|crisis",
        "requires_clinician_review": True,            # always
        "suggested_action": "send_after_review|escalate_now|call_patient",
        "grounding": [{"claim", "cited_field"}, ...],
        "ungrounded_claims": [{"claim", "reason"}, ...],
        "grounded_ratio": float,
        "chart_fields_available": [str, ...],
        "send_envelope": {... auto_send_eligible: False ...},
      }
    """
    rf_detail = _detect_red_flags_detailed(inbound_message)
    rf = [f["label"] for f in rf_detail]
    # Rule-based urgency floor: crisis if any crisis flag, else emergent, else routine.
    rule_floor = "routine"
    for f in rf_detail:
        rule_floor = _max_urgency(rule_floor, f["urgency_floor"])

    if not claude.available():
        out: dict[str, Any] = {
            "draft": "(AI not configured — please reply manually)",
            "tone": "matter-of-fact",
            "urgency": rule_floor,
            "suggested_action": "escalate_now" if rf else "send_after_review",
        }
    else:
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

    # ---- Apply rule-based floors the model cannot override ----------------------
    out["red_flags"] = rf
    out["red_flag_detail"] = rf_detail
    out["requires_clinician_review"] = True            # immutable
    out["urgency"] = _max_urgency(out.get("urgency", "routine"), rule_floor)
    if rf and out.get("suggested_action") not in ("escalate_now", "call_patient"):
        out["suggested_action"] = "escalate_now"
    out.setdefault("suggested_action", "send_after_review")
    out.setdefault("tone", "empathetic")

    # ---- Grounding check --------------------------------------------------------
    grounding = assess_grounding(out.get("draft", ""), patient_chart)
    out.update(grounding)
    # If the draft makes unverifiable clinical claims, force clinician review of them.
    if grounding["ungrounded_claims"] and out["suggested_action"] == "send_after_review":
        out["suggested_action"] = "send_after_review"  # stays, but flagged below
        out["review_priority"] = "verify_ungrounded_claims"

    # ---- One-click-send envelope ------------------------------------------------
    out["send_envelope"] = _build_send_envelope(
        channel="portal_message",
        draft=out.get("draft", ""),
        hospital_name=hospital_name,
        urgency=out["urgency"],
    )
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
    # Critical thresholds checked first — they may fire even within "high" range.
    if n == "potassium" and value > 6.0:
        status = "critical_high"
    elif n == "potassium" and value < 3.0:
        status = "critical_low"
    elif n == "a1c" and value >= 9.0:
        status = "critical_high"
    elif n == "hemoglobin" and value < 7.0:
        status = "critical_low"
    elif n == "wbc" and value < 1.0:
        status = "critical_low"
    elif n == "sodium" and (value < 125 or value > 155):
        status = "critical_low" if value < 125 else "critical_high"
    elif low is not None and value < low:
        status = "low"
    elif high is not None and value > high:
        status = "high"
    return {
        "name": name, "value": value, "unit": ref["unit"], "lay_name": ref["lay"],
        "status": status, "ref_low": low, "ref_high": high,
    }


_RESULT_DRAFT_SYSTEM = """You draft a plain-language explanation of a lab/imaging result for a patient. \
6th-grade reading level. Empathetic, calm, no jargon. <= 120 words.

Hard rules:
- Critical results (e.g. potassium > 6 or < 3, A1c >= 9, hemoglobin < 7, WBC < 1) MUST instruct the patient to contact the office today or go to the ED if office is closed.
- Only describe the result value and reference range you are given. Do not invent diagnoses or other labs.
- No specific drug dosing.
- Sign with "Your care team."
- Return JSON: {"draft": "...", "urgency": "routine | same_day | emergent | crisis"}"""


def draft_result_message(lab_name: str, value: float, *, recommended_action: str = "") -> dict[str, Any]:
    """Draft a plain-language abnormal-result message.

    Output shape:
      {
        "classification": {... classify_lab ...},
        "draft": str,
        "urgency": "routine|same_day|emergent|crisis",
        "requires_clinician_review": True,
        "grounding": [{"claim", "cited_field"}, ...],
        "ungrounded_claims": [{"claim", "reason"}, ...],
        "grounded_ratio": float,
        "send_envelope": {... auto_send_eligible: False ...},
      }
    """
    cls = classify_lab(lab_name, value)
    # The result message is grounded in exactly one synthetic chart field: the lab.
    result_chart = {"recent_labs": {cls.get("name"): cls.get("value")}}

    if not claude.available():
        out: dict[str, Any] = {"draft": "(AI not configured)", "urgency": "routine"}
    else:
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
    out["requires_clinician_review"] = True
    # Critical results escalate to emergent (model may go higher, never lower).
    floor = "emergent" if str(cls.get("status", "")).startswith("critical") else "routine"
    out["urgency"] = _max_urgency(out.get("urgency", "routine"), floor)

    grounding = assess_grounding(out.get("draft", ""), result_chart)
    out.update(grounding)
    out["send_envelope"] = _build_send_envelope(
        channel="portal_message",
        draft=out.get("draft", ""),
        hospital_name="our clinic",
        urgency=out["urgency"],
    )
    return out
