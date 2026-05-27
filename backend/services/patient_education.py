"""Plain-English patient education. Two products:

1. generate_summary() — encounter-specific discharge summary that synthesizes
   the clinician note + scribe note + transcript. Unchanged public signature.
2. generate_handout() — condition-specific teaching handout: plain-language,
   reading-level aware, multi-language aware, with red-flag return precautions.
   Plus generate_handout_batch() for parallel multi-condition fan-out.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"
_MAX_BATCH_WORKERS = 6

# Reading-level presets — drives target grade + sentence guidance.
READING_LEVELS: dict[str, str] = {
    "basic": "3rd-4th grade. Very short sentences. Only the most common words.",
    "standard": "6th grade. Short sentences. Everyday words, no medical jargon.",
    "advanced": "9th-10th grade. Plain but may use a defined medical term once.",
}
_DEFAULT_READING_LEVEL = "standard"


_SYSTEM = """You are explaining an ER encounter to the patient in plain language. \
Target 6th-grade reading level. Empathetic but honest. No medical jargon.

You receive three sources of information and MUST use all of them:
- The clinician's note (what the doctor thinks + plans — may be short, may use shorthand)
- The scribe's clinical summary (structured HPI + assessment — always present)
- The patient's original words (for tone context only)

Synthesize these into a single patient-friendly summary.

Return JSON ONLY, no preamble, no markdown fence:
{
  "headline": "one short sentence on what the doctor thinks is happening",
  "what_we_are_doing": "2-3 short sentences explaining the plan in plain language",
  "things_to_do_at_home": ["short action", "short action", "short action"],
  "when_to_come_back": "2-3 short sentences listing specific red flags",
  "closing": "one sentence of calm reassurance"
}

Rules:
- No medical abbreviations — write 'blood pressure' not 'BP', 'heart tracing' not 'ECG'.
- Prefer 'your care team' over 'the doctor'.
- Only mention medications if the clinician explicitly prescribed them.
- Total across all fields: under 180 words.
- Always generate — never return an error. Even a very short clinician note can be expanded using the scribe's structured note + transcript."""


def generate_summary(
    clinician_note: str = "",
    scribe_note: str = "",
    transcript: str = "",
    patient_language: str = "en",
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"error": "anthropic_key_missing"}
    # Require at least one meaningful source
    if not (clinician_note.strip() or scribe_note.strip() or transcript.strip()):
        return {"error": "no_context"}
    try:
        lang_hint = (
            "" if patient_language == "en" else f"\n\nOutput entirely in language code: {patient_language}."
        )
        user = f"""Clinician note:
\"\"\"
{clinician_note.strip() or '(clinician did not write a free-text note — use scribe note + transcript)'}
\"\"\"

Scribe's clinical summary:
\"\"\"
{scribe_note.strip() or '(not available)'}
\"\"\"

Patient's original words (tone reference only):
\"\"\"
{transcript.strip()[:800]}
\"\"\"{lang_hint}

Return the JSON now."""
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=700,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="patient_education",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw)
    except Exception as e:
        log.exception("Patient education generation failed: %s", e)
        return {"error": "generation_failed"}


def _parse(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {"error": "parse_failed"}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        log.warning("Patient ed parse fail (len=%d, content redacted)", len(raw))
        return {"error": "parse_failed"}
    if not isinstance(parsed, dict):
        return {"error": "parse_failed"}
    return parsed


# ---- Condition-specific teaching handout -------------------------------------------

_HANDOUT_SYSTEM = """You write a patient teaching handout about ONE medical condition.

The handout is given to a patient (or caregiver) to take home. It must be
trustworthy, calm, and easy to act on. It is NOT a substitute for the patient's
own care plan — it explains the condition in general terms.

You receive a target reading level and a target language. Honor BOTH exactly:
write the entire handout AT that reading level and IN that language.

Return JSON ONLY, no preamble, no markdown fence:
{
  "title": "the condition in plain words",
  "overview": "2-3 short sentences: what this condition is, in plain language",
  "why_it_happens": "1-2 short sentences on common causes (general, not the patient's specific cause)",
  "what_to_expect": "2-3 short sentences on the usual course and recovery",
  "self_care": ["short action", "short action", "short action", "short action"],
  "medication_notes": "1-2 sentences on how related medicines are usually taken; say 'follow your care team' for specifics",
  "red_flags": ["specific warning sign that means come back now", "...", "..."],
  "when_to_seek_care": "one sentence: where to go for the red flags above (ER vs call clinic)",
  "follow_up": "one sentence on typical follow-up",
  "closing": "one sentence of calm, honest reassurance"
}

Rules:
- No medical abbreviations. Write 'blood pressure', not 'BP'.
- red_flags must be concrete and observable by a non-medical person.
- Never invent medication doses. Defer dose/timing specifics to the care team.
- Do not diagnose or contradict the patient's clinician — this is general teaching.
- Keep the whole handout under 320 words.
- Always produce the handout — never return an error."""


def generate_handout(
    condition: str,
    patient_context: str = "",
    reading_level: str = _DEFAULT_READING_LEVEL,
    patient_language: str = "en",
) -> dict[str, Any]:
    """Generate a condition-specific, plain-language teaching handout.

    Args:
      condition: the condition/diagnosis to teach about (e.g. "type 2 diabetes").
      patient_context: optional free text to tailor tone (age, caregiver, etc.).
                       Kept brief and used only to adjust tone, not to diagnose.
      reading_level: one of READING_LEVELS keys; unknown values fall back to standard.
      patient_language: ISO language code; output is written entirely in it.

    Returns a dict with the handout fields plus echoed metadata:
      {
        "condition": str, "reading_level": str, "language": str,
        "title", "overview", "why_it_happens", "what_to_expect",
        "self_care": [...], "medication_notes", "red_flags": [...],
        "when_to_seek_care", "follow_up", "closing",
      }
    On failure returns {"error": "...", "condition": ..., ...metadata}.
    """
    level_key = reading_level if reading_level in READING_LEVELS else _DEFAULT_READING_LEVEL
    meta = {
        "condition": condition,
        "reading_level": level_key,
        "language": patient_language,
    }
    if not condition or not condition.strip():
        return {**meta, "error": "no_condition"}
    if not settings.anthropic_api_key:
        return {**meta, "error": "anthropic_key_missing"}
    try:
        lang_hint = (
            "Write the handout in English."
            if patient_language == "en"
            else f"Write the ENTIRE handout in language code: {patient_language}."
        )
        user = f"""Condition to teach about:
\"\"\"
{condition.strip()}
\"\"\"

Patient context (tone reference only — do not diagnose from this):
\"\"\"
{patient_context.strip()[:600] or '(none provided)'}
\"\"\"

Target reading level: {level_key} — {READING_LEVELS[level_key]}
{lang_hint}

Return the JSON now."""
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1100,
            system=_HANDOUT_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="patient_handout",
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        parsed = _parse(raw)
        if parsed.get("error"):
            return {**meta, **parsed}
        return {**meta, **parsed}
    except Exception as e:
        log.exception("Patient handout generation failed: %s", e)
        return {**meta, "error": "generation_failed"}


def generate_handout_batch(
    conditions: list[str | dict[str, Any]],
    reading_level: str = _DEFAULT_READING_LEVEL,
    patient_language: str = "en",
) -> list[dict[str, Any]]:
    """Generate handouts for several conditions in parallel.

    Each item may be a plain condition string, or a dict
    {"condition": str, "patient_context": str, "reading_level": str,
     "patient_language": str} to override the shared defaults per item.

    Returns a list aligned with input order; per-item failures are captured
    in the result dict (never raised).
    """
    if not conditions:
        return []

    def _norm(item: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, dict):
            return {
                "condition": item.get("condition", ""),
                "patient_context": item.get("patient_context", ""),
                "reading_level": item.get("reading_level", reading_level),
                "patient_language": item.get("patient_language", patient_language),
            }
        return {
            "condition": str(item),
            "patient_context": "",
            "reading_level": reading_level,
            "patient_language": patient_language,
        }

    def _one(item: str | dict[str, Any]) -> dict[str, Any]:
        args = _norm(item)
        try:
            return generate_handout(**args)
        except Exception as e:  # defensive — keep batch resilient
            log.warning("generate_handout_batch item failed: %s", e)
            return {
                "condition": args["condition"],
                "reading_level": args["reading_level"],
                "language": args["patient_language"],
                "error": "generation_failed",
            }

    workers = min(_MAX_BATCH_WORKERS, len(conditions))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one, conditions))
