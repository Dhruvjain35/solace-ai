"""Multi-encounter stitching + huddle mode.

Two related capabilities Solace ships that ambient-only competitors don't:

1. **Stitching** — combine related visits (same chief complaint, follow-ups)
   into a single longitudinal narrative. Visits are first grouped and ordered
   locally by chief-complaint similarity + date, so the model is handed an
   already-coherent timeline (one or more "threads") rather than a bag of
   notes. Useful for chronic-disease management and post-procedure follow-ups
   where the clinician wants "what happened between visits" surfaced.

2. **Huddle mode** — capture rounds with 3+ speakers (attending, resident,
   nurse, pharmacist, social work). Speakers are diarized: roles inferred from
   speech content + prior speaker labels, and a speaker roster is returned
   alongside the per-patient output. Output is per-patient I-PASS-shaped
   sign-out plus a team-decision log.

Public interface (consumed by routers/wave4.py):
  - ``stitch(notes)``                            -> dict
  - ``parse_huddle(transcript, ward_context=)``  -> dict
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

# Tokens that carry no signal when comparing chief complaints.
_STOP = {
    "the", "a", "an", "of", "for", "with", "and", "to", "in", "on", "at",
    "patient", "pt", "visit", "followup", "follow", "up", "f/u", "complaint",
    "c/o", "presents", "here", "today", "left", "right",
}


def _norm_tokens(text: str) -> set[str]:
    """Lowercased alphanumeric tokens with stopwords removed."""
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t and t not in _STOP}


def _cc_similar(a: str, b: str) -> bool:
    """Jaccard overlap of chief-complaint tokens; treats follow-ups as same thread."""
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / len(ta | tb)
    return overlap >= 0.34


def _parse_date(value: Any) -> datetime:
    """Best-effort date parse; unparseable dates sort last (recent-most)."""
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt)
        except ValueError:
            continue
    return datetime.max


def group_encounters(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group related visits into chief-complaint threads, each date-ordered.

    Returns: [{"thread_id", "chief_complaint", "visits": [...date-ordered...]}].
    This runs locally (no model call) so the result is deterministic and can be
    surfaced on its own, and so stitch() hands the model a coherent timeline.
    """
    threads: list[dict[str, Any]] = []
    for note in sorted(notes, key=lambda n: _parse_date(n.get("date"))):
        cc = str(note.get("chief_complaint", "")).strip()
        placed = False
        for thread in threads:
            if _cc_similar(cc, thread["chief_complaint"]):
                thread["visits"].append(note)
                placed = True
                break
        if not placed:
            threads.append({
                "thread_id": f"t{len(threads) + 1}",
                "chief_complaint": cc or "unspecified",
                "visits": [note],
            })
    for thread in threads:
        thread["visit_count"] = len(thread["visits"])
        dates = [str(v.get("date", "")) for v in thread["visits"] if v.get("date")]
        thread["span"] = {"first": dates[0], "last": dates[-1]} if dates else {}
    return threads


_STITCH_SYSTEM = """You synthesize a longitudinal narrative across multiple related encounters \
for the SAME patient. The encounters arrive pre-grouped into chief-complaint THREADS, each \
already ordered oldest-to-newest. Track problem evolution per thread: was the chief complaint \
the same? did the dx change? what worked, what failed?

Return JSON ONLY:
{
  "narrative_summary": "3-6 sentences. Cover trajectory across threads: chief complaints, key changes between visits, current status.",
  "threads": [
    {
      "thread_id": "t1",
      "chief_complaint": "...",
      "trajectory": "improving | stable | worsening | resolved | unclear",
      "summary": "2-3 sentences specific to this thread."
    }
  ],
  "active_problems": [
    {"problem": "...", "first_documented": "visit_index or date", "last_status": "improving | stable | worsening", "notes": "..."}
  ],
  "interventions_tried": [
    {"intervention": "...", "outcome": "effective | partial | failed | unknown", "thread_id": "t1"}
  ],
  "open_questions_for_clinician": ["..."]
}

Rules:
- Use clinical shorthand.
- Cite by thread_id and visit index ('v1', 'v2') when possible.
- Don't invent — only what's supported by the supplied notes.
"""


def stitch(notes: list[dict[str, Any]]) -> dict[str, Any]:
    """notes: [{'visit_index': int|str, 'date': str, 'note_text': str, 'chief_complaint': str}].

    Groups + orders the notes into chief-complaint threads first, then asks the
    model for a longitudinal narrative. The local grouping is always returned
    under 'encounter_threads' even if the model call is unavailable.
    """
    if not notes:
        return {"available": False, "reason": "no_input_or_key"}

    threads = group_encounters(notes)

    if not settings.anthropic_api_key:
        return {"available": False, "reason": "no_input_or_key", "encounter_threads": threads}

    payload = json.dumps({"threads": threads, "visit_count": len(notes)})[:14000]
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1300,
            system=_STITCH_SYSTEM,
            messages=[{"role": "user", "content": payload}],
            purpose="multi_encounter_stitch",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return {"available": True, "encounter_threads": threads, **json.loads(text)}
    except Exception as e:
        log.warning("multi_encounter stitch failed: %s", e)
        return {"available": False, "error": str(e), "encounter_threads": threads}


_HUDDLE_SYSTEM = """You parse a multi-speaker rounds / huddle transcript into a structured team \
decision log per patient. The transcript has 3+ speakers: attending, resident(s), nurse, \
pharmacist, social work, etc. Speaker roles may be inferred from content (orders and final \
calls -> attending; bedside/vitals reports -> nurse; med reconciliation/dosing -> pharmacist; \
disposition/placement -> social work).

First DIARIZE: build a roster of distinct speakers with your best-inferred role and the \
confidence of that inference. Then attribute decisions and action items to those speakers.

Return JSON ONLY:
{
  "speakers": [
    {"speaker_id": "S1", "inferred_role": "attending | resident | nurse | pharmacist | social work | unknown", "confidence": "high | medium | low", "evidence": "short phrase that justifies the role"}
  ],
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
        "patient_summary": "1-3 sentences: age, sex, hospital day, principal dx, key comorbidities",
        "action_list": [
          {"action": "imperative", "by_when": "shift / 6h / 24h", "responsible": "covering / day / night team"}
        ],
        "situation_awareness": "1-2 sentences: what could go wrong, contingency plans",
        "synthesis_prompt": "1 sentence directing the receiver to read back the critical item"
      }
    }
  ],
  "team_followups": ["unit-level decisions, e.g. M&M case to write up"]
}

Rules:
- Use clinical shorthand.
- Every patient gets a full I-PASS block; default illness_severity to 'watcher' if unclear.
- Don't invent speakers or patients not present in the transcript.
"""


def _speaker_label_count(transcript: str) -> int:
    """Count distinct speaker labels (e.g. 'Dr. Lee:', 'RN:', 'Speaker 2:')."""
    labels = re.findall(r"(?m)^\s*([A-Za-z][\w .,'/-]{0,40}?):", transcript)
    return len({lbl.strip().lower() for lbl in labels})


def parse_huddle(transcript: str, *, ward_context: str = "") -> dict[str, Any]:
    """Parse a 3+ speaker rounds transcript into per-patient I-PASS sign-outs.

    Returns 'speaker_count' (locally detected) and, on success, a model-built
    'speakers' roster with inferred roles plus per-patient 'ipass' blocks.
    """
    if not settings.anthropic_api_key or not transcript.strip():
        return {"available": False, "reason": "no_input_or_key"}

    speaker_count = _speaker_label_count(transcript)
    user = (
        (f"Ward context: {ward_context}\n\n" if ward_context else "")
        + (f"Detected ~{speaker_count} distinct speaker labels.\n\n" if speaker_count else "")
        + f'Rounds transcript:\n"""\n{transcript[:14000]}\n"""\n\nReturn JSON now.'
    )
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=2000,
            system=_HUDDLE_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="huddle_parse",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return {"available": True, "speaker_count": speaker_count, **json.loads(text)}
    except Exception as e:
        log.warning("huddle parse failed: %s", e)
        return {"available": False, "error": str(e), "speaker_count": speaker_count}
