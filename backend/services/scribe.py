"""AI medical scribe. Converts the patient's lay voice transcript + intake context
into a structured clinical documentation note in standard medical shorthand (SOAP-style).

The clinician sees this on the dashboard in place of (or alongside) the raw transcript.
The scribe's output is always a decision-support draft — it is not the patient's chart.

This module produces the *intake-side* note (lay patient voice -> clinical note).
The encounter-side ambient scribe (clinician + patient conversation, Linked
Evidence, HealthScribe) lives in ``services.ambient_scribe``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from lib import claude, content_guard
from lib.config import settings
from lib.medical_format import format_medical_info

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

# Specialty-aware emphasis appended to the system prompt. Keeps the same plain-text
# SOAP shape but steers which fields the scribe foregrounds.
_SPECIALTY_GUIDANCE: dict[str, str] = {
    "emergency": "Specialty lens: Emergency Medicine — foreground acuity and the must-not-miss differential in the assessment.",
    "primary_care": "Specialty lens: Primary Care — foreground chronic-disease context and medication reconciliation.",
    "cardiology": "Specialty lens: Cardiology — capture cardiac risk factors and exertional symptoms; assessment notes cardiac differential.",
    "pediatrics": "Specialty lens: Pediatrics — note caregiver-reported history and weight/age context.",
}

_SPECIALTY_ALIASES = {
    "ed": "emergency", "er": "emergency", "emergency_medicine": "emergency",
    "family_medicine": "primary_care", "internal_medicine": "primary_care",
    "gp": "primary_care", "peds": "pediatrics", "cards": "cardiology",
}


def _resolve_specialty(specialty: str | None) -> str | None:
    if not specialty:
        return None
    key = specialty.strip().lower().replace("-", "_").replace(" ", "_")
    key = _SPECIALTY_ALIASES.get(key, key)
    return key if key in _SPECIALTY_GUIDANCE else None


def generate_clinical_note(
    transcript: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    *,
    specialty: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Generate the intake-side clinical note.

    ``specialty`` / ``source_ip`` / ``user_agent`` are keyword-only and optional,
    so the original four-positional-arg signature is unchanged. The transcript is
    routed through ``content_guard.scan`` (SEC-005 / COMP-001) before reaching
    Claude.
    """
    if not settings.anthropic_api_key:
        return _fallback(transcript)

    safe, cleaned, findings = content_guard.scan(
        transcript or "", label="scribe", source_ip=source_ip, user_agent=user_agent
    )
    if not safe:
        log.warning("scribe blocked by content_guard: %s", findings)
        return _fallback(transcript)

    try:
        from services.followups import format_qa_for_prompts

        user_parts = [f'Patient transcript (verbatim):\n"""\n{cleaned.strip()}\n"""']
        if medical_info:
            user_parts.append(f"Medical info (structured): {format_medical_info(medical_info)}")
        if followup_qa:
            qa = format_qa_for_prompts(followup_qa)
            if qa:
                user_parts.append(f"Follow-up Q&A:\n{qa}")
        if photo_analysis and photo_analysis.get("description"):
            user_parts.append(f"Photo: {photo_analysis['description']}")

        spec = _resolve_specialty(specialty)
        system = _SYSTEM + ("\n\n" + _SPECIALTY_GUIDANCE[spec] if spec else "")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            purpose="scribe",
        )
        text = "".join(b.text for b in resp.content).strip()
        return text or _fallback(transcript)
    except Exception as e:
        log.exception("Scribe generation failed: %s", e)
        return _fallback(transcript)


async def generate_clinical_note_async(
    transcript: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    *,
    specialty: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Async wrapper for ``generate_clinical_note``. ``lib.claude.messages_create``
    is synchronous, so this offloads it with ``asyncio.to_thread`` — letting a
    router run the scribe alongside other independent AI work under
    ``asyncio.gather`` without blocking the event loop."""
    return await asyncio.to_thread(
        generate_clinical_note,
        transcript, medical_info, followup_qa, photo_analysis,
        specialty=specialty, source_ip=source_ip, user_agent=user_agent,
    )


def _fallback(transcript: str) -> str:
    return (
        "CC: not available\n"
        f"HPI: {transcript[:200].strip() if transcript else 'no transcript available'}"
    )
