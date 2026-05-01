"""Claude-generated disposition recommendation: admit / observe / discharge.

The clinician sees this alongside the differential + workup as the third pillar of the
decision-support panel. As with all Claude output, it's an AI draft.
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


_SYSTEM = """You are an ED attending writing a disposition recommendation draft.

Output JSON ONLY (no preamble, no markdown fence):
{
  "disposition": "admit | observe | discharge | transfer",
  "level_of_care": "ICU | step-down | floor | obs unit | home" or empty if N/A,
  "expected_los_hours": integer,
  "rationale": "1-2 short sentences referencing the strongest Dx",
  "discharge_criteria": ["criterion 1", "criterion 2"],
  "return_precautions": ["come back if X", "come back if Y"]
}

Rules:
- ESI 1: almost always admit (often ICU). ESI 2: admit/observe. ESI 3: observe or discharge with workup. ESI 4-5: discharge.
- "discharge_criteria" only populated when disposition is observe or discharge.
- "return_precautions" mandatory when disposition is discharge.
- "expected_los_hours": realistic ED length-of-stay (admit may say 4-6 hours for boarding).
- Use the patient's vitals + Ddx + ESI together. Don't override the ESI without explicit reasoning.
"""


def generate(
    transcript: str,
    esi_level: int,
    differential: list[dict],
    medical_info: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
) -> dict:
    if not settings.anthropic_api_key:
        return _empty(esi_level)
    try:
        parts = [
            f'Transcript:\n"""\n{transcript.strip()}\n"""',
            f"ESI: {esi_level}",
        ]
        if differential:
            ddx_lines = [f"- {d['diagnosis']} ({d.get('likelihood','low')})" for d in differential]
            parts.append("Differential:\n" + "\n".join(ddx_lines))
        if medical_info:
            parts.append(f"Medical info: {_fmt(medical_info)}")
        if vitals:
            v = ", ".join(f"{k}={val}" for k, val in vitals.items() if val is not None)
            if v:
                parts.append(f"Vitals: {v}")
        parts.append("Return the JSON object now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="disposition",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw, esi_level)
    except Exception as e:
        log.exception("Disposition generation failed: %s", e)
        return _empty(esi_level)


_VALID_DISPO = {"admit", "observe", "discharge", "transfer"}


def _parse(raw: str, esi_level: int) -> dict:
    raw = raw.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return _empty(esi_level)
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _empty(esi_level)
    if not isinstance(obj, dict):
        return _empty(esi_level)
    dispo = str(obj.get("disposition", "")).strip().lower()
    if dispo not in _VALID_DISPO:
        dispo = _default_dispo(esi_level)
    try:
        los = int(obj.get("expected_los_hours") or 0)
    except (TypeError, ValueError):
        los = 0
    return {
        "disposition": dispo,
        "level_of_care": str(obj.get("level_of_care", "")).strip(),
        "expected_los_hours": max(0, min(los, 168)),
        "rationale": str(obj.get("rationale", "")).strip(),
        "discharge_criteria": [str(x).strip() for x in (obj.get("discharge_criteria") or []) if str(x).strip()][:4],
        "return_precautions": [str(x).strip() for x in (obj.get("return_precautions") or []) if str(x).strip()][:5],
    }


def _default_dispo(esi_level: int) -> str:
    if esi_level <= 2:
        return "admit"
    if esi_level == 3:
        return "observe"
    return "discharge"


def _empty(esi_level: int) -> dict:
    return {
        "disposition": _default_dispo(esi_level),
        "level_of_care": "",
        "expected_los_hours": 0,
        "rationale": "",
        "discharge_criteria": [],
        "return_precautions": [],
    }


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
