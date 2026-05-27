"""HCC capture for Medicare Advantage recapture.

Risk-adjustment for MA plans uses CMS-HCC v28 (2025+ hybrid 67/33 with v24).
A condition only counts if it's documented WITH the **MEAT criteria** (Monitor,
Evaluate, Assess, Treat) at least once per calendar year. Conditions that "fall
off" the chart for a year lose their RAF contribution — millions of dollars per
practice.

This module:
  - Scans prior notes + the active problem list to find documented HCCs
  - Flags HCCs that need annual re-attestation in the current calendar year
  - Surfaces a MEAT-criteria checklist for each suspected HCC, and scores how
    much MEAT evidence the prior notes already supply per condition
  - Applies hierarchical category logic (a higher HCC in a hierarchy suppresses
    every lower HCC in the same group; e.g. only the highest diabetes HCC counts)
  - Rolls up a `raf_at_risk` summary: RAF currently captured, RAF that lapses if
    open recapture items are not re-attested this year, and the suspected upside.

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
# Each entry: (icd10_pattern, hcc_code, description, raf_weight, hierarchy_group, rank)
# `rank` orders severity inside a hierarchy_group: a higher rank suppresses every
# lower rank in the same group (CMS HCC hierarchy logic). Where two conditions in
# a group share a rank they are independent and both count.
HCC_TABLE = [
    # Diabetes — hierarchy: 36 (severe acute) > 37 (chronic comp) > 38 (no comp)
    (r"^E10\.6.|^E11\.6.|^E13\.6.", "HCC36", "Diabetes with severe acute complication", 0.302, "DM", 3),
    (r"^E10\.[2-5].|^E11\.[2-5].|^E13\.[2-5].", "HCC37", "Diabetes with chronic complications", 0.302, "DM", 2),
    (r"^E11\.9$|^E10\.9$|^E13\.9$", "HCC38", "Diabetes without complications", 0.105, "DM", 1),
    # Heart failure — combined HCC222
    (r"^I50\.", "HCC222", "Heart failure", 0.331, "HF", 1),
    # CKD — hierarchy: 138 (ESRD/5) > 137 (4) > 136 (3b)
    (r"^N18\.6$", "HCC138", "ESRD / CKD stage 5", 1.011, "CKD", 3),
    (r"^N18\.5$", "HCC137", "CKD stage 4", 0.205, "CKD", 2),
    (r"^N18\.4$", "HCC136", "CKD stage 3b", 0.139, "CKD", 1),
    # COPD — HCC280
    (r"^J44\.", "HCC280", "COPD", 0.319, "COPD", 1),
    # CAD — HCC241
    (r"^I25\.10|^I25\.11", "HCC241", "Coronary atherosclerosis", 0.135, "CAD", 1),
    # Major depressive disorder
    (r"^F32\.[1-9]|^F33\.", "HCC151", "Major depression, recurrent", 0.309, "DEP", 1),
    # Bipolar
    (r"^F31\.", "HCC152", "Bipolar disorders", 0.309, "BPD", 1),
    # Schizophrenia
    (r"^F20\.", "HCC152", "Schizophrenia", 0.578, "SCZ", 1),
    # Alcohol use disorder, severe / dependence
    (r"^F10\.2", "HCC135", "Alcohol use disorder, severe", 0.309, "AUD", 1),
    # Atrial fibrillation
    (r"^I48\.", "HCC239", "Atrial fibrillation", 0.190, "AFIB", 1),
    # Active cancer (varies; pattern is broad)
    (r"^C[0-9]{2}", "HCC008-022", "Active malignancy (varies by site)", 0.350, "CA", 1),
    # Stroke / cerebrovascular sequelae
    (r"^I69\.", "HCC100", "Stroke late effects", 0.221, "CVA", 1),
    # Vascular disease
    (r"^I70\.", "HCC264", "Atherosclerosis of arteries", 0.288, "VASC", 1),
]


# MEAT criteria. Each tuple: (key, label, regex of phrasing that satisfies it).
_MEAT_CRITERIA: list[tuple[str, str, str]] = [
    ("monitor", "Monitor: signs/symptoms or labs reviewed",
     r"\b(monitor|stable|worsen|improv|symptom|sign|review(ed)?|trend|"
     r"hba1c|a1c|bnp|egfr|creatinine|spirometry|ejection fraction)\b"),
    ("evaluate", "Evaluate: response to therapy or status assessed",
     r"\b(evaluat|response to|tolerat|controlled|uncontrolled|exam|"
     r"status|baseline|on exam|reassess)\b"),
    ("assess", "Assess: order, test, prescription, or referral",
     r"\b(assess|order(ed)?|test|lab|imaging|refer(ral|red)?|consult|"
     r"plan|differential|impression)\b"),
    ("treat", "Treat: medication started, continued, or adjusted",
     r"\b(treat|start(ed)?|continue[d]?|adjust|titrat|prescrib|increas|"
     r"decreas|medication|therapy|insulin|metformin|diuretic|statin)\b"),
]


def _meat_checklist() -> list[str]:
    return [label for _, label, _ in _MEAT_CRITERIA]


def _score_meat(text: str) -> dict[str, Any]:
    """Score how many MEAT criteria a slice of note text supports.

    A condition counts toward RAF only if at least one full MEAT element is
    documented; CMS auditors look for the strongest 2+ in practice, so we
    surface both the boolean and a 0-4 count for prioritization.
    """
    low = (text or "").lower()
    met = {key: bool(re.search(pat, low)) for key, _, pat in _MEAT_CRITERIA}
    count = sum(met.values())
    return {
        "criteria_met": met,
        "meat_count": count,
        "meat_complete": count >= 1,
        "audit_ready": count >= 2,
        "missing": [label for key, label, _ in _MEAT_CRITERIA if not met[key]],
    }


def _meat_evidence_for(icd: str, display: str, prior_notes: list[str]) -> dict[str, Any]:
    """Find the note context around a condition and score its MEAT coverage."""
    blob = " ".join(prior_notes or [])
    if not blob:
        return _score_meat("")
    # Look for the display term (or its first word) and grab a context window.
    needle = (display or icd).split()[0].lower() if (display or icd) else ""
    windows: list[str] = []
    if needle:
        for m in re.finditer(re.escape(needle), blob.lower()):
            windows.append(blob[max(0, m.start() - 240): m.end() + 240])
    context = " ".join(windows) if windows else blob[:1200]
    return _score_meat(context)


def _apply_hierarchy(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply CMS HCC hierarchy: within a group, the highest-rank HCC suppresses
    every lower-rank HCC. Returns (kept, suppressed)."""
    best_rank: dict[str, int] = {}
    for m in raw:
        g = m["group"]
        best_rank[g] = max(best_rank.get(g, 0), m["rank"])
    kept: dict[str, dict[str, Any]] = {}
    suppressed: list[dict[str, Any]] = []
    for m in raw:
        g = m["group"]
        if m["rank"] < best_rank[g]:
            suppressed.append({**m, "suppressed_by_hierarchy": True})
            continue
        # same (top) rank — keep highest RAF if a tie still collides
        if g not in kept or kept[g]["raf"] < m["raf"]:
            if g in kept:
                suppressed.append({**kept[g], "suppressed_by_hierarchy": True})
            kept[g] = m
        else:
            suppressed.append({**m, "suppressed_by_hierarchy": True})
    return list(kept.values()), suppressed


def evaluate_chart(*, conditions: list[dict[str, str]], prior_notes: list[str], current_year: int | None = None) -> dict[str, Any]:
    """conditions: [{icd10, display, last_documented_year}]; prior_notes: free-text history.

    Returns documented HCCs (post-hierarchy), a prioritized recapture worklist
    with per-condition MEAT evidence, suspected-but-undocumented HCCs, and a
    `raf_at_risk` rollup.
    """
    year = current_year or datetime.now(timezone.utc).year

    raw_matches: list[dict[str, Any]] = []
    for c in conditions:
        icd = (c.get("icd10") or "").upper()
        last_year = int(c.get("last_documented_year") or year - 1)
        for pat, hcc_code, desc, raf, group, rank in HCC_TABLE:
            if re.match(pat, icd):
                raw_matches.append({
                    "hcc_code": hcc_code,
                    "description": desc,
                    "raf": raf,
                    "icd10": icd,
                    "icd_display": c.get("display", icd),
                    "last_documented_year": last_year,
                    "needs_recapture": last_year < year,
                    "group": group,
                    "rank": rank,
                })

    documented, suppressed = _apply_hierarchy(raw_matches)
    documented.sort(key=lambda m: m["raf"], reverse=True)

    # Build the recapture worklist: each open HCC with MEAT evidence scored from
    # the prior notes, so the clinician sees what is already supportable and
    # what they still need to document at the encounter.
    worklist: list[dict[str, Any]] = []
    for m in documented:
        if not m["needs_recapture"]:
            continue
        meat = _meat_evidence_for(m["icd10"], m["icd_display"], prior_notes)
        worklist.append({
            "hcc_code": m["hcc_code"],
            "description": m["description"],
            "icd10": m["icd10"],
            "icd_display": m["icd_display"],
            "raf": m["raf"],
            "last_documented_year": m["last_documented_year"],
            "years_lapsed": year - m["last_documented_year"],
            "meat_evidence": meat,
            "action": (
                "Re-attest — MEAT evidence already in notes, confirm at encounter"
                if meat["audit_ready"]
                else "Document MEAT at encounter — insufficient evidence in prior notes"
            ),
            "meat_checklist": _meat_checklist(),
        })
    # Highest RAF first, then weakest MEAT support first (most urgent to capture).
    worklist.sort(key=lambda w: (-w["raf"], w["meat_evidence"]["meat_count"]))

    suspected = _suspect_from_notes(prior_notes, conditions)

    raf_captured = round(sum(m["raf"] for m in documented if not m["needs_recapture"]), 3)
    raf_open = round(sum(m["raf"] for m in documented if m["needs_recapture"]), 3)
    raf_total_documented = round(sum(m["raf"] for m in documented), 3)
    suspected_raf = round(sum(_lookup_raf(s.get("icd10", "")) for s in suspected), 3)

    return {
        "current_year": year,
        "documented_hccs": documented,
        "suppressed_hccs": suppressed,
        # raf_total kept for backward compatibility (sum of all documented HCCs).
        "raf_total": raf_total_documented,
        "needs_recapture": [m for m in documented if m["needs_recapture"]],
        "recapture_worklist": worklist,
        "suspected_undocumented": suspected,
        "meat_checklist": _meat_checklist(),
        "raf_at_risk": {
            "raf_captured_this_year": raf_captured,
            "raf_open_recapture": raf_open,
            "raf_total_if_recaptured": raf_total_documented,
            "raf_suspected_upside": suspected_raf,
            "raf_full_potential": round(raf_total_documented + suspected_raf, 3),
            "open_recapture_count": len(worklist),
            "suspected_count": len(suspected),
            "pct_captured": (
                round(100.0 * raf_captured / raf_total_documented, 1)
                if raf_total_documented else 100.0
            ),
        },
    }


def _lookup_raf(icd10: str) -> float:
    """Best-effort RAF weight for a suspected ICD-10 (for upside estimation)."""
    icd = (icd10 or "").upper()
    for pat, _hcc, _desc, raf, _group, _rank in HCC_TABLE:
        if re.match(pat, icd):
            return raf
    return 0.0


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
        suspected = out.get("suspected", [])[:8]
        # Enrich each with the RAF weight it would add if captured.
        for s in suspected:
            s["estimated_raf"] = _lookup_raf(s.get("icd10", ""))
        return suspected
    except Exception as e:
        log.warning("hcc_suspect failed: %s", e)
        return []
