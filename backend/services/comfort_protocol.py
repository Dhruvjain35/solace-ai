"""Claude-generated patient comfort protocol. Returns 2-4 action cards."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings
from lib.fallbacks import FALLBACK_PROTOCOLS

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_SYSTEM = """You are Solace, a compassionate ER companion. Generate comfort guidance for a waiting ER patient.

Rules:
- ESI 1-2: Focus on staying calm and still. NO physical exercises. Reassure help is coming.
- ESI 3: Gentle positional comfort, breathing, pain management.
- ESI 4-5: Active comfort — elevation, ice/heat, reasonable mobility.
- Always 3 actions (not 2, not 4). Each has: title (1-3 words), instruction (1 short sentence, <25 words), icon (one emoji).
- Tailor to the patient's symptoms and known allergies/medications/conditions.
- NEVER suggest something that could interact with their meds or conditions.
- Respond ONLY in language code: {language}.
- Return JSON array only. No preamble, no markdown fence.

JSON schema:
[{{"title": "...", "instruction": "...", "icon": "..."}}]"""


def generate(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    language: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
) -> list[dict]:
    if not settings.anthropic_api_key:
        return FALLBACK_PROTOCOLS.get(esi_level, FALLBACK_PROTOCOLS[3])
    try:
        user_parts = [
            f'Patient transcript:\n"""\n{transcript.strip()}\n"""',
            f"Photo analysis: {(photo_analysis or {}).get('description') or 'none'}",
            f"ESI level: {esi_level}",
        ]
        if medical_info:
            user_parts.append(f"Medical history: {_fmt(medical_info)}")
        if followup_qa:
            from services.followups import format_qa_for_prompts

            qa = format_qa_for_prompts(followup_qa)
            if qa:
                user_parts.append(f"Follow-up answers:\n{qa}")
        user_parts.append("Return the JSON array now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_SYSTEM.format(language=language),
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            purpose="comfort_protocol",
        )
        raw = "".join(b.text for b in resp.content)
        parsed = _parse(raw)
        if parsed:
            return parsed
        log.warning("Comfort protocol parse failed; using fallback (len=%d, content redacted)", len(raw))
    except Exception as e:
        log.exception("Comfort protocol generation failed: %s", e)
    return FALLBACK_PROTOCOLS.get(esi_level, FALLBACK_PROTOCOLS[3])


def _fmt(info: dict[str, Any]) -> str:
    parts = []
    for key in ("allergies", "medications", "conditions"):
        arr = info.get(key) or []
        if arr and not (len(arr) == 1 and str(arr[0]).lower() == "none"):
            parts.append(f"{key}: {', '.join(str(x) for x in arr)}")
    return "; ".join(parts) or "none relevant"


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
    for item in arr if isinstance(arr, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        instruction = str(item.get("instruction", "")).strip()
        icon = str(item.get("icon", "")).strip() or "•"
        if title and instruction:
            cleaned.append({"title": title, "instruction": instruction, "icon": icon})
    return cleaned[:4]
