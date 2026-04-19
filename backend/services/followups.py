"""Claude generates 2-3 short follow-up questions based on the patient's transcript.

Returned to the patient as quick-tap chips or short text inputs. The answers feed
back into the pre-brief + triage.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_SYSTEM = """You are a triage nurse asking brief follow-up questions. \
Given a patient's self-description, generate 2-3 short clarifying questions that a triage nurse would ask. \
Each question must be answerable in <10 seconds.

Return JSON ONLY, no preamble or markdown fence, in this exact shape:
[
  {"id": "q1", "question": "...", "type": "boolean"},
  {"id": "q2", "question": "...", "type": "choice", "options": ["option1", "option2", "option3"]},
  {"id": "q3", "question": "...", "type": "text"}
]

Rules:
- Use "boolean" for yes/no questions.
- Use "choice" when there are clear categorical answers (2-5 options max, very short).
- Use "text" only for quantities/qualities that need a phrase (e.g. "how many hours?").
- Max 3 questions. Prefer 2 if fewer are clearly useful.
- Focus on: duration, severity escalation, associated symptoms, prior history, triggers.
- Questions must be plain-language, no clinical jargon ("shortness of breath" OK, "dyspnea" not OK).
- Do NOT repeat what the patient already said in the transcript.
- If the transcript already contains a duration, severity, and key associated symptoms, return []."""


_FALLBACK: list[dict] = [
    {
        "id": "duration",
        "question": "How long has this been going on?",
        "type": "choice",
        "options": ["< 1 hour", "1-6 hours", "6-24 hours", "> 1 day"],
    },
    {
        "id": "worsening",
        "question": "Is it getting worse?",
        "type": "boolean",
    },
]


def generate_questions(transcript: str, medical_info: dict[str, Any] | None = None) -> list[dict]:
    """Return 0-3 follow-up questions. Falls back to generic questions on failure."""
    if not settings.anthropic_api_key:
        return _FALLBACK
    try:
        info_blob = _summarize_medical_info(medical_info) if medical_info else "not provided"
        user = f"""Patient transcript:
\"\"\"
{transcript.strip()}
\"\"\"

Known medical info: {info_blob}

Return the JSON array now."""
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=500,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="followups",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw) or []
    except Exception as e:
        log.exception("Follow-up generation failed: %s", e)
        return _FALLBACK


def _parse(raw: str) -> list[dict]:
    raw = raw.strip()
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        arr = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    cleaned: list[dict] = []
    for idx, item in enumerate(arr if isinstance(arr, list) else []):
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        t = str(item.get("type", "text")).strip().lower()
        if not q or t not in ("boolean", "choice", "text"):
            continue
        entry: dict = {"id": item.get("id") or f"q{idx+1}", "question": q, "type": t}
        if t == "choice":
            opts = item.get("options") or []
            entry["options"] = [str(o) for o in opts if str(o).strip()][:5]
            if not entry["options"]:
                continue
        cleaned.append(entry)
        if len(cleaned) >= 3:
            break
    return cleaned


def _summarize_medical_info(info: dict[str, Any]) -> str:
    """Compact text summary for prompt context."""
    parts = []
    if info.get("age"):
        parts.append(f"{info['age']}yo")
    if info.get("sex"):
        parts.append(str(info["sex"]))
    if info.get("pregnant"):
        parts.append("pregnant")
    for key in ("allergies", "medications", "conditions"):
        arr = info.get(key) or []
        if arr and not (len(arr) == 1 and str(arr[0]).lower() == "none"):
            parts.append(f"{key}: {', '.join(str(x) for x in arr)}")
    return "; ".join(parts) if parts else "none reported"


def format_qa_for_prompts(followup_qa: list[dict]) -> str:
    """Format Q/A pairs for inclusion in downstream Claude prompts."""
    if not followup_qa:
        return ""
    lines = []
    for qa in followup_qa:
        q = str(qa.get("question", "")).strip()
        a = str(qa.get("answer", "")).strip()
        if q and a:
            lines.append(f"- {q} → {a}")
    return "\n".join(lines)
