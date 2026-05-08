"""Multi-encounter stitching + huddle mode.

Two related capabilities Solace ships that ambient-only competitors don't:

1. **Stitching** — combine related visits (same chief complaint, follow-ups)
   into a single longitudinal narrative. Useful for chronic-disease management
   and post-procedure follow-ups where the clinician wants "what happened
   between visits" surfaced.

2. **Huddle mode** — capture rounds with 3+ speakers (attending, resident,
   nurse, pharmacist, social work). Roles inferred from speech content +
   prior speaker labels. Output is per-patient I-PASS-shaped sign-out plus
   a team-decision log.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_STITCH_SYSTEM = """You synthesize a longitudinal narrative across multiple related encounters \
for the SAME patient. Track problem evolution: was the chief complaint the same? did the dx \
change? what worked, what failed?

Return JSON ONLY:
{
  "narrative_summary": "3-5 sentences. Cover trajectory: chief complaint, key changes between visits, current status.",
  "active_problems": [
    {"problem": "...", "first_documented": "visit_index", "last_status": "improving | stable | worsening", "notes": "..."}
  ],
  "interventions_tried": [
    {"intervention": "...", "outcome": "effective | partial | failed | unknown"}
  ],
  "open_questions_for_clinician": ["..."]
}

Rules:
- Use clinical shorthand.
- Cite by visit index ('v1', 'v2') when possible.
- Don't invent — only what's supported by the supplied notes.
"""


def stitch(notes: list[dict[str, Any]]) -> dict[str, Any]:
    """notes: [{'visit_index': int|str, 'date': str, 'note_text': str, 'chief_complaint': str}]"""
    if not settings.anthropic_api_key or not notes:
        return {"available": False, "reason": "no_input_or_key"}
    payload = json.dumps(notes)[:14000]
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1100,
            system=_STITCH_SYSTEM,
            messages=[{"role": "user", "content": payload}],
            purpose="multi_encounter_stitch",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return {"available": True, **json.loads(text)}
    except Exception as e:
        log.warning("multi_encounter stitch failed: %s", e)
        return {"available": False, "error": str(e)}


_HUDDLE_SYSTEM = """You parse a multi-speaker rounds / huddle transcript into a structured team \
decision log per patient. The transcript has 3+ speakers: attending, resident(s), nurse, \
pharmacist, social work, etc. Speaker roles may be inferred from content.

Return JSON ONLY:
{
  "patients": [
    {
      "patient_label": "Bed 4 / Mr X / etc.",
      "team_decisions": [
        {"decision": "...", "by": "attending | resident | team", "rationale": "..."}
      ],
      "action_items": [
        {"action": "...", "owner": "RN | resident | pharmacy | SW", "by_when": "today / shift / next round"}
      ],
      "ipass": {
        "illness_severity": "stable | watcher | unstable",
        "patient_summary": "...",
        "synthesis_prompt": "..."
      }
    }
  ],
  "team_followups": ["unit-level decisions, e.g. M&M case to write up"]
}
"""


def parse_huddle(transcript: str, *, ward_context: str = "") -> dict[str, Any]:
    if not settings.anthropic_api_key or not transcript.strip():
        return {"available": False, "reason": "no_input_or_key"}
    user = (
        (f"Ward context: {ward_context}\n\n" if ward_context else "")
        + f'Rounds transcript:\n"""\n{transcript[:14000]}\n"""\n\nReturn JSON now.'
    )
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1600,
            system=_HUDDLE_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="huddle_parse",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return {"available": True, **json.loads(text)}
    except Exception as e:
        log.warning("huddle parse failed: %s", e)
        return {"available": False, "error": str(e)}
