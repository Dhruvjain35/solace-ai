"""Claude-generated clinician pre-brief. One dense sentence per patient."""
from __future__ import annotations

import logging
from typing import Any

from lib import claude
from lib.config import settings

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
        user_parts = [f'Patient transcript:\n"""\n{transcript.strip()}\n"""']
        if medical_info:
            user_parts.append(f"Medical history: {_fmt_medical(medical_info)}")
        if followup_qa:
            from services.followups import format_qa_for_prompts

            qa = format_qa_for_prompts(followup_qa)
            if qa:
                user_parts.append(f"Follow-up Q&A:\n{qa}")
        user_parts.append(f"Photo analysis: {(photo_analysis or {}).get('description') or 'none'}")
        user_parts.append(f"Triage ESI (context, do not include in output): {esi_level}")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=300,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            purpose="prebrief",
        )
        text = "".join(b.text for b in resp.content).strip()
        return text or _fallback(transcript)
    except Exception as e:
        log.exception("Pre-brief generation failed: %s", e)
        return _fallback(transcript)


def _fmt_medical(info: dict[str, Any]) -> str:
    parts = []
    if info.get("age"):
        parts.append(f"age {info['age']}")
    if info.get("sex"):
        parts.append(str(info["sex"]))
    if info.get("pregnant"):
        parts.append("pregnant")
    for key, label in (("allergies", "allergies"), ("medications", "meds"), ("conditions", "hx")):
        arr = info.get(key) or []
        if arr and not (len(arr) == 1 and str(arr[0]).lower() == "none"):
            parts.append(f"{label}: {', '.join(str(x) for x in arr)}")
    return "; ".join(parts) if parts else "none reported"


def _fallback(transcript: str) -> str:
    t = (transcript or "").strip()
    return (t[:197] + "...") if len(t) > 200 else t or "(no transcript)"
