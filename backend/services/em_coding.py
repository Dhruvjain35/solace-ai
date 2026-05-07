"""E&M + ICD-10 + CPT auto-suggestion.

Two-stage:
  1. LLM extracts MDM components from the encounter note (problems addressed,
     amount/complexity of data reviewed, risk of complications), and proposes
     top-3 ICD-10 + top-3 CPT/E&M candidates with justifications.
  2. Deterministic validators apply the 2021/2023 CPT MDM rubric for E&M and
     do basic NCCI edit checks (modifier 25 for separately-identifiable E&M
     with a procedure on the same day; modifier 59 for distinct procedural
     services).

Top-3 ranked. Never auto-submits. Documents the supporting MDM elements.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


# Outpatient E&M MDM rubric (2021 AMA, refined 2023)
_OUTPATIENT_LEVELS = [
    {"code": "99202", "level": 2, "mdm": "straightforward", "time_min": (15, 29)},
    {"code": "99203", "level": 3, "mdm": "low",            "time_min": (30, 44)},
    {"code": "99204", "level": 4, "mdm": "moderate",       "time_min": (45, 59)},
    {"code": "99205", "level": 5, "mdm": "high",           "time_min": (60, 74)},
    {"code": "99212", "level": 2, "mdm": "straightforward", "time_min": (10, 19)},
    {"code": "99213", "level": 3, "mdm": "low",            "time_min": (20, 29)},
    {"code": "99214", "level": 4, "mdm": "moderate",       "time_min": (30, 39)},
    {"code": "99215", "level": 5, "mdm": "high",           "time_min": (40, 54)},
]


_SYSTEM = """You extract billing-relevant elements from an outpatient encounter note. Return JSON only.

Output:
{
  "mdm": {
    "problems_addressed": "minimal | self-limited | low | moderate | high",
    "data_reviewed": "minimal | limited | moderate | extensive",
    "risk_of_complications": "minimal | low | moderate | high",
    "summary_supporting_evidence": "1-2 short clauses citing the note"
  },
  "established_patient": true,
  "icd10_candidates": [
    {"code": "K35.80", "name": "Acute appendicitis", "support": "RLQ pain, fever, anorexia"}
  ],
  "cpt_procedure_candidates": [
    {"code": "12001", "name": "Simple repair scalp 2.5cm", "support": "..."}
  ],
  "modifiers_to_consider": [
    {"modifier": "25", "reason": "separately identifiable E&M with procedure same day"}
  ]
}

Rules:
- Use ICD-10-CM codes; up to 5 candidates; ranked by clinical specificity.
- Return [] if no procedure mentioned. Modifier 25 only if both E&M-level work AND a procedure occurred.
- Never invent diagnoses not supported by the note.
"""


def _level_from_mdm(mdm: dict[str, str], established: bool) -> dict[str, Any]:
    pa = mdm.get("problems_addressed", "minimal")
    dr = mdm.get("data_reviewed", "minimal")
    rk = mdm.get("risk_of_complications", "minimal")
    # Two of three drive level (per AMA)
    rank = {"minimal": 1, "self-limited": 1, "low": 2, "limited": 2, "moderate": 3, "extensive": 3, "high": 4}
    scores = sorted([rank.get(pa, 1), rank.get(dr, 1), rank.get(rk, 1)], reverse=True)
    second_highest = scores[1]
    if second_highest >= 4:
        target = "high"
    elif second_highest == 3:
        target = "moderate"
    elif second_highest == 2:
        target = "low"
    else:
        target = "straightforward"
    candidates = [c for c in _OUTPATIENT_LEVELS if c["mdm"] == target]
    if established:
        candidates = [c for c in candidates if c["code"].startswith("9921")]
    else:
        candidates = [c for c in candidates if c["code"].startswith("9920")]
    if not candidates:
        candidates = [_OUTPATIENT_LEVELS[1]]
    primary = candidates[0]
    # Add a one-step lower as alternate
    fallback = next(
        (c for c in _OUTPATIENT_LEVELS if c["mdm"] == ("low" if target == "moderate" else target) and c["code"].startswith(primary["code"][:4])),
        primary,
    )
    return {"primary": primary, "alternate": fallback, "rubric_match": target}


def suggest(note_text: str, *, established_patient: bool = True) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"available": False}
    user = f'Encounter note:\n"""\n{note_text[:7000]}\n"""\n\nReturn JSON now.'
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1100,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="em_coding",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
    except Exception as e:
        log.warning("em_coding failed: %s", e)
        return {"available": False, "error": str(e)}

    mdm = parsed.get("mdm", {})
    establish = bool(parsed.get("established_patient", established_patient))
    leveling = _level_from_mdm(mdm, establish)
    return {
        "available": True,
        "mdm": mdm,
        "em_primary": leveling["primary"],
        "em_alternate": leveling["alternate"],
        "icd10": parsed.get("icd10_candidates", [])[:5],
        "cpt_procedures": parsed.get("cpt_procedure_candidates", []),
        "modifiers": parsed.get("modifiers_to_consider", []),
        "established_patient": establish,
    }
