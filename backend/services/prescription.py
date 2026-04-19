"""Claude-powered prescription suggestions. Clearly AI — every one is shown to the physician
with cautions from the patient's known allergies + medications. The physician writes the final Rx.
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


_SYSTEM = """You are an ER prescribing reference. Given a patient's symptoms, ESI, and history,
suggest 1-3 standard ER prescriptions a physician might consider.

Rules:
- NEVER present these as definitive. They are AI suggestions the physician will verify.
- Respect the patient's allergies — if a standard suggestion is contraindicated, SKIP it or substitute.
- Flag interactions with the patient's existing medications in the "cautions" field.
- Use generic drug names (ibuprofen, not Advil).
- Keep each suggestion to a standard ER dose + course. No exotic/off-label.
- If the complaint is clearly non-pharmacologic (sprain, minor cut, refill of unrelated med), return [].

Return JSON ONLY, no preamble, no markdown fence:
[
  {
    "drug": "generic name",
    "dose": "e.g. 600 mg",
    "route": "PO | IV | IM | SL | PR",
    "frequency": "e.g. q6h PRN",
    "duration": "e.g. 5 days",
    "indication": "one-line rationale",
    "cautions": "interaction or allergy note specific to this patient, else empty string"
  }
]"""


def suggest(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
) -> list[dict]:
    if not settings.anthropic_api_key:
        return []
    try:
        from services.followups import format_qa_for_prompts

        parts = [f'Transcript:\n"""\n{transcript.strip()}\n"""', f"ESI: {esi_level}"]
        if medical_info:
            parts.append(f"Medical info: {_fmt(medical_info)}")
        if followup_qa:
            qa = format_qa_for_prompts(followup_qa)
            if qa:
                parts.append(f"Follow-up Q&A:\n{qa}")
        if photo_analysis and photo_analysis.get("description"):
            parts.append(f"Photo: {photo_analysis['description']}")
        parts.append("Return the JSON array now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="prescription",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw)
    except Exception as e:
        log.exception("Prescription suggestion failed: %s", e)
        return []


def _fmt(info: dict[str, Any]) -> str:
    parts = []
    if info.get("age"):
        parts.append(f"{info['age']}yo")
    if info.get("sex"):
        parts.append(str(info["sex"]))
    if info.get("pregnant"):
        parts.append("pregnant")
    for key, label in (("allergies", "allergies"), ("medications", "meds"), ("conditions", "hx")):
        arr = info.get(key) or []
        if arr and not (len(arr) == 1 and str(arr[0]).lower() == "none"):
            parts.append(f"{label}: {', '.join(str(x) for x in arr)}")
    return "; ".join(parts) or "none reported"


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
        drug = str(item.get("drug", "")).strip()
        if not drug:
            continue
        cleaned.append(
            {
                "drug": drug,
                "dose": str(item.get("dose", "")).strip(),
                "route": str(item.get("route", "")).strip(),
                "frequency": str(item.get("frequency", "")).strip(),
                "duration": str(item.get("duration", "")).strip(),
                "indication": str(item.get("indication", "")).strip(),
                "cautions": str(item.get("cautions", "")).strip(),
            }
        )
        if len(cleaned) >= 3:
            break
    return cleaned
