"""HCC capture for Medicare Advantage recapture.

Risk-adjustment for MA plans uses CMS-HCC v28 (2025+ hybrid 67/33 with v24).
A condition only counts if it's documented WITH the **MEAT criteria** (Monitor,
Evaluate, Assess, Treat) at least once per calendar year. Conditions that "fall
off" the chart for a year lose their RAF contribution — millions of dollars per
practice.

This module:
  - Scans prior notes + the active problem list to find documented HCCs
  - Flags HCCs that need annual re-attestation in the current calendar year
  - Surfaces a MEAT-criteria checklist for each suspected HCC the clinician
    can fill at the encounter
  - Applies hierarchical category logic (HCC trumps lower in the same category;
    e.g. only the highest diabetes HCC counts)

Production-grade: integrate with claims data + lab data for stronger suspecting.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


# Curated subset of v28 HCCs by category. Real implementation pulls full table.
# Each entry: (icd10_pattern, hcc_code, description, raf_weight, hierarchy_group)
HCC_TABLE = [
    # Diabetes — hierarchy: 38 (with chronic comp) > 37 (with acute comp) > 36 (without)
    (r"^E10\.6.|^E11\.6.|^E13\.6.", "HCC36", "Diabetes with severe acute complication", 0.302, "DM"),
    (r"^E10\.[2-5].|^E11\.[2-5].|^E13\.[2-5].", "HCC37", "Diabetes with chronic complications", 0.302, "DM"),
    (r"^E11\.9$|^E10\.9$|^E13\.9$", "HCC38", "Diabetes without complications", 0.105, "DM"),
    # Heart failure — combined HCC222
    (r"^I50\.", "HCC222", "Heart failure", 0.331, "HF"),
    # CKD — hierarchy: 138 > 137 > 136
    (r"^N18\.6$", "HCC138", "ESRD / CKD stage 5", 1.011, "CKD"),
    (r"^N18\.5$", "HCC137", "CKD stage 4", 0.205, "CKD"),
    (r"^N18\.4$", "HCC136", "CKD stage 3b", 0.139, "CKD"),
    # COPD — HCC280
    (r"^J44\.", "HCC280", "COPD", 0.319, "COPD"),
    # CAD — HCC241 / 242
    (r"^I25\.10|^I25\.11", "HCC241", "Coronary atherosclerosis", 0.135, "CAD"),
    # Major depressive disorder
    (r"^F32\.[1-9]|^F33\.", "HCC151", "Major depression, recurrent", 0.309, "DEP"),
    # Bipolar
    (r"^F31\.", "HCC152", "Bipolar disorders", 0.309, "BPD"),
    # Schizophrenia
    (r"^F20\.", "HCC152", "Schizophrenia", 0.578, "SCZ"),
    # Alcohol use disorder, severe / dependence
    (r"^F10\.2", "HCC135", "Alcohol use disorder, severe", 0.309, "AUD"),
    # Atrial fibrillation
    (r"^I48\.", "HCC239", "Atrial fibrillation", 0.190, "AFIB"),
    # Active cancer (varies; pattern is broad)
    (r"^C[0-9]{2}", "HCC008-022", "Active malignancy (varies by site)", 0.350, "CA"),
    # Stroke / cerebrovascular sequelae
    (r"^I69\.", "HCC100", "Stroke late effects", 0.221, "CVA"),
    # Vascular disease
    (r"^I70\.", "HCC264", "Atherosclerosis of arteries", 0.288, "VASC"),
]


def _meat_checklist() -> list[str]:
    return [
        "Monitor: signs/symptoms or labs reviewed",
        "Evaluate: response to therapy or status assessed",
        "Assess: order, test, prescription, or referral",
        "Treat: medication started, continued, or adjusted",
    ]


def evaluate_chart(*, conditions: list[dict[str, str]], prior_notes: list[str], current_year: int | None = None) -> dict[str, Any]:
    """conditions: [{icd10, display, last_documented_year}]; prior_notes: free-text history."""
    year = current_year or datetime.now(timezone.utc).year

    matches: dict[str, dict[str, Any]] = {}  # hierarchy_group -> best HCC
    for c in conditions:
        icd = (c.get("icd10") or "").upper()
        last_year = int(c.get("last_documented_year") or year - 1)
        for pat, hcc_code, desc, raf, group in HCC_TABLE:
            if re.match(pat, icd):
                # Hierarchy: keep the highest-RAF HCC per group
                if group not in matches or matches[group]["raf"] < raf:
                    matches[group] = {
                        "hcc_code": hcc_code,
                        "description": desc,
                        "raf": raf,
                        "icd10": icd,
                        "icd_display": c.get("display", icd),
                        "last_documented_year": last_year,
                        "needs_recapture": last_year < year,
                        "group": group,
                    }

    suspected_from_notes = _suspect_from_notes(prior_notes, conditions)

    raf_total = sum(m["raf"] for m in matches.values())
    return {
        "current_year": year,
        "documented_hccs": list(matches.values()),
        "raf_total": round(raf_total, 3),
        "needs_recapture": [m for m in matches.values() if m["needs_recapture"]],
        "suspected_undocumented": suspected_from_notes,
        "meat_checklist": _meat_checklist(),
    }


def _suspect_from_notes(prior_notes: list[str], known_conditions: list[dict[str, str]]) -> list[dict[str, str]]:
    """Best-effort LLM scan for conditions mentioned but not on the active problem list."""
    if not settings.anthropic_api_key or not prior_notes:
        return []
    known_codes = ",".join(c.get("icd10", "") for c in known_conditions)
    user = (
        f"Already-documented ICD-10 codes: {known_codes}\n\n"
        f"Prior notes:\n\"\"\"\n{(' '.join(prior_notes))[:6000]}\n\"\"\"\n\n"
        "Identify clinical conditions clearly mentioned in the prior notes that are NOT in the "
        "documented ICD-10 list and that ARE Medicare HCC-relevant. "
        "Return JSON only: {\"suspected\": [{\"icd10\": \"...\", \"display\": \"...\", \"evidence_quote\": \"...\"}]}"
    )
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system="You are an HCC suspecting NLP. Only flag conditions explicitly supported by the notes.",
            messages=[{"role": "user", "content": user}],
            purpose="hcc_suspect",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(text)
        return out.get("suspected", [])[:8]
    except Exception as e:
        log.warning("hcc_suspect failed: %s", e)
        return []
