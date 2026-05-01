"""Claude-generated differential diagnosis. Returns 2-4 ranked Ddx with reasoning.

Always shown to clinicians as an "AI draft" — never as ground truth. The clinician
verifies, narrows, or rejects each entry before workup orders go in.
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


_SYSTEM = """You are an experienced ED attending generating a differential diagnosis (Ddx) \
draft from a patient intake. The clinician will verify before acting.

Output JSON ONLY (no preamble, no markdown fence):
[
  {
    "diagnosis": "short Dx name (e.g. 'Acute appendicitis')",
    "icd10": "best-guess ICD-10 code (e.g. K35.80) or empty",
    "likelihood": "high | moderate | low",
    "rule_in": ["positive feature 1", "positive feature 2"],
    "rule_out": ["what's missing or argues against"],
    "must_not_miss": true
  }
]

Rules:
- Return 2-4 entries, ordered by likelihood (highest first).
- "must_not_miss" = true ONLY for life/limb-threatening Dx (MI, PE, AAA, sepsis, stroke, ectopic, etc).
- rule_in / rule_out arrays: 1-3 short clinical phrases each, drawn DIRECTLY from the transcript / vitals / hx given.
- Use the chief complaint as anchor. Don't list every plausible Dx — only those with at least one supporting feature.
- If the visit is clearly low-acuity non-pharmacologic (med refill, paperwork), return [].
"""


def generate(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
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
        if vitals:
            v = ", ".join(f"{k}={v}" for k, v in vitals.items() if v is not None)
            if v:
                parts.append(f"Bedside vitals: {v}")
        parts.append("Return the JSON array now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="differential",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw)
    except Exception as e:
        log.exception("Differential generation failed: %s", e)
        return []


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
        dx = str(item.get("diagnosis", "")).strip()
        if not dx:
            continue
        cleaned.append({
            "diagnosis": dx,
            "icd10": str(item.get("icd10", "")).strip(),
            "likelihood": str(item.get("likelihood", "low")).strip().lower(),
            "rule_in": [str(x).strip() for x in (item.get("rule_in") or []) if str(x).strip()][:4],
            "rule_out": [str(x).strip() for x in (item.get("rule_out") or []) if str(x).strip()][:4],
            "must_not_miss": bool(item.get("must_not_miss")),
        })
        if len(cleaned) >= 4:
            break
    return cleaned


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
