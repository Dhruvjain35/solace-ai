"""Claude-generated workup order set. Labs + imaging + monitoring tied to the Ddx.

The clinician sees these as a one-click "order set accept" panel. They are AI suggestions —
the EHR commits when the clinician signs.
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


_SYSTEM = """You are an ED attending writing a workup order set for a patient about to be evaluated.

Output JSON ONLY (no preamble, no markdown fence):
{
  "labs":      ["short order text", ...],   // e.g. "CBC", "BMP", "Troponin (q3h x2)"
  "imaging":   ["short order text", ...],   // e.g. "ECG", "CXR PA/lateral", "CT abd/pelvis with IV contrast"
  "monitoring":["short order text", ...],   // e.g. "Continuous cardiac monitor", "SpO2 monitor"
  "consults":  ["short order text", ...],   // e.g. "Cards consult", "Surgery consult"
  "rationale": "1-2 sentences linking these orders to the differential"
}

Rules:
- Anchor each order to a Dx in the differential — don't shotgun.
- ESI 1-2: include monitoring + STAT labs/imaging.
- ESI 3: targeted labs + imaging only if clearly indicated.
- ESI 4-5: minimal — often just clinical exam, maybe a single lab.
- Use standard ED shorthand (CBC, BMP, LFTs, lipase, lactate, UA, hCG, troponin, D-dimer, BNP).
- If an order would be contraindicated by the patient's renal/hepatic/allergy history, skip it.
- Return empty arrays for sections that don't apply. Do not invent a diagnosis the Ddx didn't list.
- "rationale" is mandatory — keep it under 30 words.
"""


def generate(
    transcript: str,
    esi_level: int,
    differential: list[dict],
    medical_info: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
) -> dict:
    if not settings.anthropic_api_key:
        return _empty()
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
            max_tokens=700,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="workup",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw)
    except Exception as e:
        log.exception("Workup generation failed: %s", e)
        return _empty()


def _parse(raw: str) -> dict:
    raw = raw.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return _empty()
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _empty()
    if not isinstance(obj, dict):
        return _empty()
    return {
        "labs":       [str(x).strip() for x in (obj.get("labs") or []) if str(x).strip()][:8],
        "imaging":    [str(x).strip() for x in (obj.get("imaging") or []) if str(x).strip()][:6],
        "monitoring": [str(x).strip() for x in (obj.get("monitoring") or []) if str(x).strip()][:5],
        "consults":   [str(x).strip() for x in (obj.get("consults") or []) if str(x).strip()][:4],
        "rationale":  str(obj.get("rationale", "")).strip(),
    }


def _empty() -> dict:
    return {"labs": [], "imaging": [], "monitoring": [], "consults": [], "rationale": ""}


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
