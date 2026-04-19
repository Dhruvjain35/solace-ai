"""AI medical scribe. Converts the patient's lay voice transcript + intake context
into a structured clinical documentation note in standard medical shorthand (SOAP-style).

The clinician sees this on the dashboard in place of (or alongside) the raw transcript.
The scribe's output is always a decision-support draft — it is not the patient's chart.
"""
from __future__ import annotations

import logging
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_SYSTEM = """You are an experienced medical scribe documenting an ER encounter. Convert the \
patient's verbal description and intake data into a dense, professional clinical note using \
standard medical shorthand.

Output format — exactly this structure, plain text, no markdown fences, no preamble:

CC: <chief complaint, 3-7 words>
HPI: <2-4 sentences in clinical shorthand covering onset, location, duration, character, aggravating/relieving factors, radiation, timing, severity (OLD CARTS) where available; use c/o, hx, sx, pt, SOB, N/V, HA, abd, assoc, denies, etc.>
ROS: <relevant positives/negatives from transcript + follow-up answers; pertinent only>
PMHx: <prior conditions or 'none reported'>
Meds: <current medications or 'none reported'>
Allergies: <allergies or 'NKDA'>
Social: <if mentioned in transcript — smoking, alcohol, occupation; else 'not discussed'>
Assessment (AI draft): <1-2 line working differential or impression; always prefix with 'AI draft —'>

Rules:
- Use standard abbreviations: c/o, hx, PMHx, sx, pt, SOB, N/V, HA, abd, LLQ/RLQ/RUQ/LUQ, BLE/BUE, CP, NKDA, neg, pos, assoc.
- Do NOT invent vitals, physical exam findings, or labs — none are available.
- Do NOT name specific drugs in the assessment. The physician prescribes.
- If patient mentioned pain, include its 0-10 scale and quality (sharp, dull, crushing, etc.).
- Keep HPI under 60 words.
- If context is too thin for a field, write 'not discussed' — never invent.
"""


def generate_clinical_note(
    transcript: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
) -> str:
    if not settings.anthropic_api_key:
        return _fallback(transcript)
    try:
        from services.followups import format_qa_for_prompts

        user_parts = [f'Patient transcript (verbatim):\n"""\n{transcript.strip()}\n"""']
        if medical_info:
            user_parts.append(f"Medical info (structured): {_fmt(medical_info)}")
        if followup_qa:
            qa = format_qa_for_prompts(followup_qa)
            if qa:
                user_parts.append(f"Follow-up Q&A:\n{qa}")
        if photo_analysis and photo_analysis.get("description"):
            user_parts.append(f"Photo: {photo_analysis['description']}")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            purpose="scribe",
        )
        text = "".join(b.text for b in resp.content).strip()
        return text or _fallback(transcript)
    except Exception as e:
        log.exception("Scribe generation failed: %s", e)
        return _fallback(transcript)


def _fmt(info: dict[str, Any]) -> str:
    parts = []
    if info.get("age"):
        parts.append(f"{info['age']}yo")
    if info.get("sex"):
        parts.append(str(info["sex"]))
    if info.get("pregnant"):
        parts.append("pregnant")
    for key, label in (("allergies", "allergies"), ("medications", "meds"), ("conditions", "pmh")):
        arr = info.get(key) or []
        if arr and not (len(arr) == 1 and str(arr[0]).lower() == "none"):
            parts.append(f"{label}: {', '.join(str(x) for x in arr)}")
    return "; ".join(parts) if parts else "none reported"


def _fallback(transcript: str) -> str:
    return (
        "CC: not available\n"
        f"HPI: {transcript[:200].strip() if transcript else 'no transcript available'}"
    )
