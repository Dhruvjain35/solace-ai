"""Claude-generated clinician pre-brief.

`generate()` returns the classic one-dense-paragraph summary (public signature
unchanged — intake.py persists this string).

`generate_structured()` returns a sectioned dict the clinician panel can render
as labeled fields: one-liner, HPI, pertinent positives/negatives, history, and
an action cue. It reuses the same Claude call budget but asks for JSON.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings
from lib.medical_format import format_medical_info

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_SYSTEM = """You are writing a structured ER pre-brief for an attending clinician. \
Be dense, clinical, accurate. No fluff, no greetings, no preamble.

Output a single paragraph (1-3 sentences total), in this structure:
"[age]yo [sex], [chief complaint] [duration], [key associated symptoms], [relevant negatives if any], [pertinent hx/allergies/meds]. Photo: [1 sentence or 'none']."

Rules:
- Use medical shorthand (hx, c/o, pt, SOB, n/v, denies) where natural.
- Include allergies only if patient reported any (not 'none').
- Include medications only if relevant to complaint (e.g. blood thinners with bleeding).
- Do NOT invent details. Do NOT include the ESI level."""


_SYSTEM_STRUCTURED = """You are writing a structured ER pre-brief for an attending clinician. \
Be dense, clinical, accurate. No fluff, no greetings, no preamble.

Output JSON ONLY (no markdown fence, no preamble):
{
  "one_liner": "[age]yo [sex] c/o [chief complaint] x[duration]",
  "hpi": "2-4 clause history of present illness in clinical shorthand",
  "pertinent_positives": ["finding 1", "finding 2"],
  "pertinent_negatives": ["denies X", "denies Y"],
  "history": "relevant PMHx / allergies / meds, or empty string if none reported",
  "photo_note": "1 sentence on the photo, or 'none'",
  "action_cue": "1 short clause on the most time-sensitive next step"
}

Rules:
- Use medical shorthand (hx, c/o, pt, SOB, n/v, denies) where natural.
- Include allergies/meds only if reported and relevant.
- Do NOT invent details. Do NOT include the ESI level in any field."""


def generate(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
) -> str:
    if not settings.anthropic_api_key:
        return _fallback(transcript)
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=300,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _build_user(transcript, photo_analysis, esi_level, medical_info, followup_qa)}],
            purpose="prebrief",
        )
        text = "".join(b.text for b in resp.content).strip()
        return text or _fallback(transcript)
    except Exception as e:
        log.exception("Pre-brief generation failed: %s", e)
        return _fallback(transcript)


def generate_structured(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
) -> dict:
    """Sectioned pre-brief for the clinician panel.

    Returns a dict with keys: one_liner, hpi, pertinent_positives,
    pertinent_negatives, history, photo_note, action_cue, summary, source.
    `summary` is the flattened one-paragraph form so callers that only want a
    string can still use it. Always returns; never raises.
    """
    if not settings.anthropic_api_key:
        return _structured_fallback(transcript, photo_analysis)
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=500,
            system=_SYSTEM_STRUCTURED,
            messages=[{"role": "user", "content": _build_user(transcript, photo_analysis, esi_level, medical_info, followup_qa)}],
            purpose="prebrief",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse_structured(raw, transcript, photo_analysis)
    except Exception as e:
        log.exception("Structured pre-brief generation failed: %s", e)
        return _structured_fallback(transcript, photo_analysis)


def _build_user(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    medical_info: dict[str, Any] | None,
    followup_qa: list[dict] | None,
) -> str:
    user_parts = [f'Patient transcript:\n"""\n{transcript.strip()}\n"""']
    if medical_info:
        user_parts.append(f"Medical history: {format_medical_info(medical_info)}")
    if followup_qa:
        from services.followups import format_qa_for_prompts

        qa = format_qa_for_prompts(followup_qa)
        if qa:
            user_parts.append(f"Follow-up Q&A:\n{qa}")
    user_parts.append(f"Photo analysis: {(photo_analysis or {}).get('description') or 'none'}")
    user_parts.append(f"Triage ESI (context, do not include in output): {esi_level}")
    return "\n\n".join(user_parts)


def _parse_structured(
    raw: str,
    transcript: str,
    photo_analysis: dict[str, Any] | None,
) -> dict:
    match = re.search(r"\{[\s\S]*\}", raw.strip())
    if not match:
        return _structured_fallback(transcript, photo_analysis)
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _structured_fallback(transcript, photo_analysis)
    if not isinstance(obj, dict):
        return _structured_fallback(transcript, photo_analysis)

    def _s(key: str) -> str:
        return str(obj.get(key, "")).strip()

    def _l(key: str) -> list[str]:
        return [str(x).strip() for x in (obj.get(key) or []) if str(x).strip()][:6]

    sections = {
        "one_liner": _s("one_liner"),
        "hpi": _s("hpi"),
        "pertinent_positives": _l("pertinent_positives"),
        "pertinent_negatives": _l("pertinent_negatives"),
        "history": _s("history"),
        "photo_note": _s("photo_note") or "none",
        "action_cue": _s("action_cue"),
        "source": "claude",
    }
    sections["summary"] = _flatten(sections)
    return sections


def _flatten(s: dict) -> str:
    """Collapse the structured sections into the one-paragraph form."""
    bits: list[str] = []
    if s.get("one_liner"):
        bits.append(s["one_liner"].rstrip("."))
    if s.get("hpi"):
        bits.append(s["hpi"].rstrip("."))
    pos = s.get("pertinent_positives") or []
    if pos:
        bits.append("+ " + ", ".join(pos))
    neg = s.get("pertinent_negatives") or []
    if neg:
        bits.append("denies " + ", ".join(x.replace("denies ", "") for x in neg))
    if s.get("history"):
        bits.append(s["history"].rstrip("."))
    para = ". ".join(b for b in bits if b)
    if para:
        para += "."
    photo = s.get("photo_note") or "none"
    return (para + f" Photo: {photo}.").strip()


def _fallback(transcript: str) -> str:
    t = (transcript or "").strip()
    return (t[:197] + "...") if len(t) > 200 else t or "(no transcript)"


def _structured_fallback(transcript: str, photo_analysis: dict[str, Any] | None) -> dict:
    summary = _fallback(transcript)
    return {
        "one_liner": "",
        "hpi": summary,
        "pertinent_positives": [],
        "pertinent_negatives": [],
        "history": "",
        "photo_note": (photo_analysis or {}).get("description") or "none",
        "action_cue": "",
        "summary": summary,
        "source": "fallback",
    }
