"""Multi-language discharge / care plan with red-flag return-precautions.

Wraps the existing patient_education.generate_summary() and adds a structured
red-flag return-precautions block tailored to the assessment, in the patient's
preferred language. This is the SMS body + the printed handout body.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from lib import claude
from lib.config import settings
from services import patient_education

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

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
