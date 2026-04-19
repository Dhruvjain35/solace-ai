"""Plain-English patient education summary. Combines clinician note + scribe note + transcript
so Claude always has enough context — never bails on short clinician notes."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


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
