"""Multi-language discharge / care plan with red-flag return-precautions.

Wraps the existing patient_education.generate_summary() and adds a structured
red-flag return-precautions block tailored to the assessment, in the patient's
preferred language. This is the SMS body + the printed handout body.

It also produces a deeper, *condition-specific sectioned* discharge plan:
named sections (medications, activity, diet, wound care, follow-up ...) plus
a TIERED return-precautions block that sorts every warning sign into one of
three urgency tiers: 911, go to the ED, or call the office.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from lib import claude
from lib.config import settings
from services import patient_education

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

# Return-precaution urgency tiers, most-urgent first.
PRECAUTION_TIERS = ("emergency_911", "emergency_department", "call_office")
_TIER_LABEL = {
    "emergency_911": "Call 911 now",
    "emergency_department": "Go to the emergency department",
    "call_office": "Call our office today",
}

# Canonical discharge-plan section keys, in the order they should be rendered.
DISCHARGE_SECTIONS = (
    "understanding",     # what the condition is, plain language
    "medications",       # what to take, how, why
    "activity",          # activity / rest / work / driving guidance
    "diet",              # food / fluid guidance
    "wound_care",        # incision / wound / cast care (omit if N/A)
    "symptom_relief",    # comfort measures at home
    "follow_up",         # appointments and tests to arrange
)

# Mirrors the 20-language patient intake list
SUPPORTED_LANGUAGES = [
    "en", "es", "zh", "tl", "vi", "ar", "fr", "ko", "ru", "de",
    "ht", "pt", "it", "pl", "ja", "fa", "ur", "hi", "bn", "gu",
]

LANG_NAME = {
    "en": "English", "es": "Spanish", "zh": "Chinese (Simplified)", "tl": "Tagalog", "vi": "Vietnamese",
    "ar": "Arabic", "fr": "French", "ko": "Korean", "ru": "Russian", "de": "German",
    "ht": "Haitian Creole", "pt": "Portuguese", "it": "Italian", "pl": "Polish", "ja": "Japanese",
    "fa": "Persian/Farsi", "ur": "Urdu", "hi": "Hindi", "bn": "Bengali", "gu": "Gujarati",
}


_RED_FLAG_SYSTEM = """You produce 4-7 plain-language red-flag return precautions tailored to the assessment. \
6th-grade reading level. Each item is a short sentence beginning with the symptom and ending with what to do.

Return JSON ONLY: {"items": ["...", "..."]}

Rules:
- Always include any clearly relevant life-threats for this assessment.
- Use the patient's language (specified in the user message).
- No medical jargon. Plain words for body parts ("chest" not "thorax").
- "Call 911" or "Go to the emergency department" for true emergencies; "Call our office today" for urgent-but-not-emergent.
"""


def red_flags(assessment: str, language: str = "en") -> list[str]:
    if not settings.anthropic_api_key:
        return ["Worsening symptoms — call our office or go to the ED."]
    lang_full = LANG_NAME.get(language, "English")
    user = f"Assessment: {assessment}\n\nLanguage: {lang_full}\n\nReturn JSON now."
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=500,
            system=_RED_FLAG_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="discharge_redflags",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(text)
        return out.get("items", [])
    except Exception as e:
        log.warning("red flag gen failed: %s", e)
        return []


def build_discharge_plan(
    *,
    clinician_note: str = "",
    scribe_note: str = "",
    transcript: str = "",
    assessment: str = "",
    patient_language: str = "en",
    hospital_name: str = "your clinic",
    follow_up: str = "",
) -> dict[str, Any]:
    """Returns {summary: ..., red_flags: [...], follow_up_text: ..., sms_body: ...}"""
    summary = patient_education.generate_summary(
        clinician_note=clinician_note,
        scribe_note=scribe_note,
        transcript=transcript,
        patient_language=patient_language,
    )
    rf = red_flags(assessment or summary.get("headline", ""), patient_language)
    follow_up_text = follow_up or summary.get("when_to_come_back") or ""

    # Compose an SMS-friendly body (under 320 chars)
    sms_lines = []
    if summary.get("headline"):
        sms_lines.append(summary["headline"])
    if rf:
        sms_lines.append("Return precautions: " + " | ".join(rf[:3]))
    if follow_up_text:
        sms_lines.append("Follow up: " + follow_up_text)
    sms_body = ("Care plan from " + hospital_name + ": " + " ".join(sms_lines))[:320]

    return {
        "language": patient_language,
        "summary": summary,
        "red_flags": rf,
        "follow_up_text": follow_up_text,
        "sms_body": sms_body,
    }


# ===========================================================================
# Tiered return-precautions
# ===========================================================================

_TIERED_SYSTEM = """You produce return precautions for a discharged patient, SORTED INTO THREE URGENCY TIERS.

6th-grade reading level. Each item is one short sentence: the warning sign, plainly stated.

Return JSON ONLY, no preamble or markdown fence:
{{"emergency_911": ["..."], "emergency_department": ["..."], "call_office": ["..."]}}

Tier rules:
- "emergency_911": immediate life-threats — call an ambulance, do not drive
  (e.g. crushing chest pain, trouble breathing, fainting, stroke signs, heavy bleeding).
- "emergency_department": serious but the patient can be driven in
  (e.g. high fever that will not come down, a wound that looks infected, persistent vomiting).
- "call_office": concerning but not emergent — phone the clinic for advice or a sooner visit.
- Tailor every item to THIS assessment. Include any clearly relevant life-threats.
- 2-5 items per tier. A tier may be empty only if nothing fits it.
- No medical jargon. Plain words for body parts.
- Write all items in language code: {lang}. Keep the JSON keys in English."""


def _empty_tiers() -> dict[str, list[str]]:
    return {t: [] for t in PRECAUTION_TIERS}


def tiered_return_precautions(assessment: str, language: str = "en") -> dict[str, Any]:
    """Return-precautions sorted into 911 / ED / call-office tiers.

    Returns:
      {
        "tiers": {"emergency_911": [...], "emergency_department": [...],
                  "call_office": [...]},
        "labels": {tier: human label},
        "language": "..."
      }
    Falls back to a single conservative ED-tier item if AI is unavailable.
    """
    if not settings.anthropic_api_key:
        tiers = _empty_tiers()
        tiers["emergency_department"] = [
            "Symptoms get worse or you are worried — go to the emergency department."
        ]
        return {"tiers": tiers, "labels": dict(_TIER_LABEL), "language": language}
    lang_full = LANG_NAME.get(language, "English")
    user = f"Assessment: {assessment}\n\nLanguage: {lang_full}\n\nReturn JSON now."
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_TIERED_SYSTEM.format(lang=lang_full),
            messages=[{"role": "user", "content": user}],
            purpose="discharge_tiered_precautions",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        obj = json.loads(text)
        tiers = _empty_tiers()
        for t in PRECAUTION_TIERS:
            tiers[t] = [str(x).strip() for x in (obj.get(t) or []) if str(x).strip()][:5]
        return {"tiers": tiers, "labels": dict(_TIER_LABEL), "language": language}
    except Exception as e:
        log.warning("tiered precaution gen failed: %s", e)
        tiers = _empty_tiers()
        tiers["emergency_department"] = [
            "Symptoms get worse or you are worried — go to the emergency department."
        ]
        return {"tiers": tiers, "labels": dict(_TIER_LABEL), "language": language}


# ===========================================================================
# Condition-specific sectioned discharge instructions
# ===========================================================================

_SECTIONED_SYSTEM = """You write a condition-specific discharge instruction sheet for one patient.

6th-grade reading level. Plain words. No medical abbreviations.

Return JSON ONLY, no preamble or markdown fence:
{{"sections": [
   {{"key": "<one of the allowed keys>", "title": "...", "body": ["short sentence", ...]}}
]}}

Allowed section keys (use only these, in this order, skip any that do not apply):
  understanding, medications, activity, diet, wound_care, symptom_relief, follow_up

Rules:
- Tailor every section to THIS condition — generic advice is not acceptable.
- Each section "body" is 1-4 short bullet sentences.
- Only include "medications" content the clinician note actually prescribes.
- Only include "wound_care" if there is a wound, incision, or cast.
- Always include "understanding" and "follow_up".
- "title" is a short plain-language heading in the patient's language.
- Write all "title" and "body" text in language code: {lang}. Keep "key" in English."""


def _sectioned_instructions(
    condition: str,
    clinician_note: str,
    language: str,
) -> list[dict[str, Any]]:
    """Claude-generated condition-specific sectioned instructions."""
    if not settings.anthropic_api_key:
        return [{
            "key": "follow_up",
            "title": "Follow up",
            "body": ["Keep your follow-up appointment with your care team."],
        }]
    lang_full = LANG_NAME.get(language, "English")
    user = (
        f"Condition / assessment: {condition}\n\n"
        f"Clinician note: {clinician_note or '(none)'}\n\n"
        f"Language: {lang_full}\n\nReturn JSON now."
    )
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_SECTIONED_SYSTEM.format(lang=lang_full),
            messages=[{"role": "user", "content": user}],
            purpose="discharge_sectioned",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        obj = json.loads(text)
        order = {k: i for i, k in enumerate(DISCHARGE_SECTIONS)}
        out: list[dict[str, Any]] = []
        for s in obj.get("sections") or []:
            if not isinstance(s, dict):
                continue
            key = str(s.get("key", "")).strip()
            if key not in order:
                continue
            body = [str(b).strip() for b in (s.get("body") or []) if str(b).strip()][:4]
            title = str(s.get("title", key.replace("_", " ").title())).strip()
            if not body:
                continue
            out.append({"key": key, "title": title, "body": body})
        out.sort(key=lambda s: order[s["key"]])
        return out
    except Exception as e:
        log.warning("sectioned discharge gen failed: %s", e)
        return [{
            "key": "follow_up",
            "title": "Follow up",
            "body": ["Keep your follow-up appointment with your care team."],
        }]


def build_detailed_discharge_plan(
    *,
    condition: str = "",
    clinician_note: str = "",
    scribe_note: str = "",
    transcript: str = "",
    assessment: str = "",
    patient_language: str = "en",
    hospital_name: str = "your clinic",
    follow_up: str = "",
) -> dict[str, Any]:
    """Deep, condition-specific discharge plan.

    Builds on build_discharge_plan() and adds:
      - "sections": condition-specific sectioned instructions
      - "tiered_precautions": return-precautions sorted into 911 / ED / call-office

    The sectioned-instruction and tiered-precaution Claude calls run in
    PARALLEL. Returns the base plan plus the two new keys.

    Returns:
      { ...build_discharge_plan() keys...,
        "condition": "...",
        "sections": [{key, title, body[]}, ...],
        "tiered_precautions": {tiers, labels, language} }
    """
    base = build_discharge_plan(
        clinician_note=clinician_note,
        scribe_note=scribe_note,
        transcript=transcript,
        assessment=assessment,
        patient_language=patient_language,
        hospital_name=hospital_name,
        follow_up=follow_up,
    )
    cond = condition or assessment or base.get("summary", {}).get("headline", "") or ""

    sections: list[dict[str, Any]] = []
    tiered: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_sections = pool.submit(_sectioned_instructions, cond, clinician_note, patient_language)
        fut_tiers = pool.submit(tiered_return_precautions, cond, patient_language)
        for fut in as_completed((fut_sections, fut_tiers)):
            try:
                if fut is fut_sections:
                    sections = fut.result()
                else:
                    tiered = fut.result()
            except Exception as e:
                log.warning("detailed discharge worker failed: %s", e)

    if not tiered:
        tiered = tiered_return_precautions(cond, patient_language)

    return {
        **base,
        "condition": cond,
        "sections": sections,
        "tiered_precautions": tiered,
    }
