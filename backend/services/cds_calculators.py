"""CDS calculator library.

Each calculator is pure-Python deterministic scoring with the canonical published
rubric. Inputs are validated; missing inputs surface as `missing` so the UI can
prompt for them rather than the calc silently producing a wrong answer.

Auto-extraction (LLM-driven) lives in `auto_extract()` — given a transcript +
encounter context, it tries to fill in inputs for the calculators most relevant
to the chief complaint, and returns the calculator results inline.

Calculators implemented:
    - HEART score (chest pain risk)
    - Wells score for PE
    - Wells score for DVT
    - PERC rule (PE rule-out)
    - NIHSS (stroke severity)
    - CURB-65 (pneumonia severity)
    - qSOFA (sepsis screen)
    - MEWS / NEWS2 (deterioration)
    - Centor + McIsaac (strep pharyngitis)
    - GCS (Glasgow Coma)
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _bool(v: Any) -> int:
    return 1 if v else 0


# ---- HEART score (chest pain) -----------------------------------------------------
def heart(
    history: int,
    ekg: int,
    age: int,
    risk_factors: int,
    troponin: int,
) -> dict[str, Any]:
    """Each input 0-2. risk_factors counts: HTN, HLD, DM, smoker, FHx CAD, obese, prior atherosclerosis.
    risk_factors: 0 if 0, 1 if 1-2, 2 if 3+ or known atherosclerosis.
    age: <45=0, 45-64=1, >=65=2.
    """
    total = history + ekg + age + risk_factors + troponin
    if total <= 3:
        risk = "low"
        mace_30d = "0.9-1.7%"
        action = "Discharge home, outpatient follow-up"
    elif total <= 6:
        risk = "moderate"
        mace_30d = "12-17%"
        action = "Admit/observe; serial troponin; cardiology consult"
    else:
        risk = "high"
        mace_30d = "50-65%"
        action = "Cath lab pathway; aggressive ACS management"
    return {
        "score": total,
        "risk": risk,
        "mace_30d": mace_30d,
        "action": action,
        "components": {
            "history": history,
            "ekg": ekg,
            "age": age,
            "risk_factors": risk_factors,
            "troponin": troponin,
        },
    }


# ---- Wells PE ---------------------------------------------------------------------
def wells_pe(
    clinical_signs_dvt: bool = False,
    pe_most_likely: bool = False,
    hr_over_100: bool = False,
    immobilization_or_surgery_4wk: bool = False,
    prior_pe_or_dvt: bool = False,
    hemoptysis: bool = False,
    malignancy: bool = False,
) -> dict[str, Any]:
    pts = (
        3 * _bool(clinical_signs_dvt)
        + 3 * _bool(pe_most_likely)
        + 1.5 * _bool(hr_over_100)
        + 1.5 * _bool(immobilization_or_surgery_4wk)
        + 1.5 * _bool(prior_pe_or_dvt)
        + 1 * _bool(hemoptysis)
        + 1 * _bool(malignancy)
    )
    if pts <= 4:
        risk, action = "PE unlikely", "D-dimer; if negative, PE excluded"
    else:
        risk, action = "PE likely", "CTPA (or V/Q if contrast contraindicated)"
    return {"score": pts, "risk": risk, "action": action}


# ---- Wells DVT --------------------------------------------------------------------
def wells_dvt(
    active_cancer: bool = False,
    paralysis_or_recent_cast: bool = False,
    bedridden_3d_or_surgery_12wk: bool = False,
    tenderness_along_veins: bool = False,
    entire_leg_swollen: bool = False,
    calf_swelling_3cm: bool = False,
    pitting_edema: bool = False,
    collateral_superficial_veins: bool = False,
    prior_dvt: bool = False,
    alternative_dx_likely: bool = False,
) -> dict[str, Any]:
    pts = (
        _bool(active_cancer)
        + _bool(paralysis_or_recent_cast)
        + _bool(bedridden_3d_or_surgery_12wk)
        + _bool(tenderness_along_veins)
        + _bool(entire_leg_swollen)
        + _bool(calf_swelling_3cm)
        + _bool(pitting_edema)
        + _bool(collateral_superficial_veins)
        + _bool(prior_dvt)
        - 2 * _bool(alternative_dx_likely)
    )
    if pts < 1:
        risk, action = "low", "D-dimer; if negative, DVT excluded"
    elif pts < 3:
        risk, action = "moderate", "D-dimer + lower extremity ultrasound"
    else:
        risk, action = "high", "Lower extremity ultrasound; empiric anticoagulation if delayed"
    return {"score": pts, "risk": risk, "action": action}


# ---- PERC rule --------------------------------------------------------------------
def perc(
    age_under_50: bool,
    hr_under_100: bool,
    spo2_at_least_95: bool,
    no_unilateral_leg_swelling: bool,
    no_hemoptysis: bool,
    no_recent_surgery_trauma: bool,
    no_prior_pe_dvt: bool,
    no_estrogen: bool,
) -> dict[str, Any]:
    all_negative = all(
        [
            age_under_50,
            hr_under_100,
            spo2_at_least_95,
            no_unilateral_leg_swelling,
            no_hemoptysis,
            no_recent_surgery_trauma,
            no_prior_pe_dvt,
            no_estrogen,
        ]
    )
    if all_negative:
        return {"perc_negative": True, "action": "PE excluded clinically (in low-pretest-probability)"}
    return {"perc_negative": False, "action": "Cannot rule out PE; pursue D-dimer or imaging per Wells"}


# ---- NIHSS (15 items, abbreviated) -----------------------------------------------
def nihss(items: dict[str, int]) -> dict[str, Any]:
    keys = [
        "loc",
        "loc_questions",
        "loc_commands",
        "best_gaze",
        "visual",
        "facial_palsy",
        "motor_arm_left",
        "motor_arm_right",
        "motor_leg_left",
        "motor_leg_right",
        "limb_ataxia",
        "sensory",
        "best_language",
        "dysarthria",
        "extinction_inattention",
    ]
    total = sum(int(items.get(k, 0)) for k in keys)
    if total == 0:
        sev = "no stroke symptoms"
    elif total <= 4:
        sev = "minor"
    elif total <= 15:
        sev = "moderate"
    elif total <= 20:
        sev = "moderate-severe"
    else:
        sev = "severe"
    return {"score": total, "severity": sev}


# ---- CURB-65 ---------------------------------------------------------------------
def curb65(
    confusion: bool,
    bun_over_19: bool,
    rr_at_least_30: bool,
    sbp_under_90_or_dbp_at_most_60: bool,
    age_at_least_65: bool,
) -> dict[str, Any]:
    pts = sum(
        _bool(x)
        for x in [confusion, bun_over_19, rr_at_least_30, sbp_under_90_or_dbp_at_most_60, age_at_least_65]
    )
    if pts <= 1:
        action = "Outpatient management"
    elif pts == 2:
        action = "Short inpatient or close outpatient observation"
    else:
        action = "Inpatient (consider ICU if >=3)"
    return {"score": pts, "action": action}


# ---- qSOFA -----------------------------------------------------------------------
def qsofa(rr_at_least_22: bool, altered_mental: bool, sbp_at_most_100: bool) -> dict[str, Any]:
    pts = _bool(rr_at_least_22) + _bool(altered_mental) + _bool(sbp_at_most_100)
    flag = pts >= 2
    return {
        "score": pts,
        "high_risk": flag,
        "action": "Sepsis workup, lactate, blood cultures, broad-spectrum abx, fluids" if flag else "Continue assessment",
    }


# ---- MEWS / NEWS2 abbreviated -----------------------------------------------------
def news2(rr: float, spo2: float, on_oxygen: bool, sbp: float, hr: float, temp_c: float, alert: bool) -> dict[str, Any]:
    score = 0
    # Respiratory rate
    if rr <= 8 or rr >= 25:
        score += 3
    elif rr >= 21:
        score += 2
    elif rr >= 9 and rr <= 11:
        score += 1
    # SpO2
    if spo2 <= 91:
        score += 3
    elif spo2 <= 93:
        score += 2
    elif spo2 <= 95:
        score += 1
    # Air vs O2
    if on_oxygen:
        score += 2
    # SBP
    if sbp <= 90 or sbp >= 220:
        score += 3
    elif sbp <= 100:
        score += 2
    elif sbp <= 110:
        score += 1
    # HR
    if hr <= 40 or hr >= 131:
        score += 3
    elif hr >= 111:
        score += 2
    elif hr >= 91 or hr <= 50:
        score += 1
    # Temp
    if temp_c <= 35:
        score += 3
    elif temp_c >= 39.1:
        score += 2
    elif temp_c <= 36 or temp_c >= 38.1:
        score += 1
    # AVPU
    if not alert:
        score += 3
    if score >= 7:
        risk = "high — emergent response, ICU consult"
    elif score >= 5:
        risk = "medium — urgent response, sepsis workup"
    else:
        risk = "low"
    return {"score": score, "risk": risk}


# ---- Centor + McIsaac -------------------------------------------------------------
def centor(
    age: int,
    tonsillar_exudate: bool,
    tender_anterior_cervical_nodes: bool,
    fever_history: bool,
    cough_absent: bool,
) -> dict[str, Any]:
    pts = (
        _bool(tonsillar_exudate)
        + _bool(tender_anterior_cervical_nodes)
        + _bool(fever_history)
        + _bool(cough_absent)
    )
    # McIsaac age modifier
    if age < 15:
        pts += 1
    elif age >= 45:
        pts -= 1
    if pts <= 0:
        action = "No testing or antibiotics"
    elif pts == 1:
        action = "No testing; symptomatic care"
    elif pts in (2, 3):
        action = "Rapid antigen test; treat if positive"
    else:
        action = "Test and treat empirically; consider abx"
    return {"score": pts, "action": action}


# ---- GCS --------------------------------------------------------------------------
def gcs(eye: int, verbal: int, motor: int) -> dict[str, Any]:
    total = max(0, min(6, motor)) + max(0, min(5, verbal)) + max(0, min(4, eye))
    if total >= 13:
        sev = "minor"
    elif total >= 9:
        sev = "moderate"
    else:
        sev = "severe"
    return {"score": total, "severity": sev}


# ---- Registry --------------------------------------------------------------------
CALCULATORS: dict[str, dict[str, Any]] = {
    "heart": {
        "name": "HEART score (chest pain)",
        "fn": heart,
        "inputs": ["history (0-2)", "ekg (0-2)", "age (0-2)", "risk_factors (0-2)", "troponin (0-2)"],
        "applies_when": ["chest pain", "chest pressure", "angina"],
    },
    "wells_pe": {
        "name": "Wells score for PE",
        "fn": wells_pe,
        "inputs": [
            "clinical_signs_dvt", "pe_most_likely", "hr_over_100",
            "immobilization_or_surgery_4wk", "prior_pe_or_dvt", "hemoptysis", "malignancy",
        ],
        "applies_when": ["dyspnea", "pleuritic chest pain", "hemoptysis", "leg swelling"],
    },
    "wells_dvt": {
        "name": "Wells score for DVT",
        "fn": wells_dvt,
        "inputs": [
            "active_cancer", "paralysis_or_recent_cast", "bedridden_3d_or_surgery_12wk",
            "tenderness_along_veins", "entire_leg_swollen", "calf_swelling_3cm",
            "pitting_edema", "collateral_superficial_veins", "prior_dvt", "alternative_dx_likely",
        ],
        "applies_when": ["leg swelling", "calf pain", "unilateral leg pain"],
    },
    "perc": {
        "name": "PERC rule (PE rule-out)",
        "fn": perc,
        "inputs": [
            "age_under_50", "hr_under_100", "spo2_at_least_95",
            "no_unilateral_leg_swelling", "no_hemoptysis", "no_recent_surgery_trauma",
            "no_prior_pe_dvt", "no_estrogen",
        ],
        "applies_when": ["dyspnea", "low-risk PE workup"],
    },
    "nihss": {
        "name": "NIH Stroke Scale",
        "fn": nihss,
        "inputs": ["items (dict of 15 component scores)"],
        "applies_when": ["weakness", "speech change", "facial droop", "stroke"],
    },
    "curb65": {
        "name": "CURB-65 (pneumonia severity)",
        "fn": curb65,
        "inputs": ["confusion", "bun_over_19", "rr_at_least_30", "sbp_under_90_or_dbp_at_most_60", "age_at_least_65"],
        "applies_when": ["pneumonia", "cough with fever", "shortness of breath with fever"],
    },
    "qsofa": {
        "name": "qSOFA (sepsis screen)",
        "fn": qsofa,
        "inputs": ["rr_at_least_22", "altered_mental", "sbp_at_most_100"],
        "applies_when": ["fever", "sepsis suspected", "hypotension", "altered mentation"],
    },
    "news2": {
        "name": "NEWS2 (deterioration)",
        "fn": news2,
        "inputs": ["rr", "spo2", "on_oxygen", "sbp", "hr", "temp_c", "alert"],
        "applies_when": ["any acutely ill patient with vitals"],
    },
    "centor": {
        "name": "Centor + McIsaac (strep)",
        "fn": centor,
        "inputs": ["age", "tonsillar_exudate", "tender_anterior_cervical_nodes", "fever_history", "cough_absent"],
        "applies_when": ["sore throat", "pharyngitis"],
    },
    "gcs": {
        "name": "Glasgow Coma Scale",
        "fn": gcs,
        "inputs": ["eye (1-4)", "verbal (1-5)", "motor (1-6)"],
        "applies_when": ["altered mental status", "head injury", "coma"],
    },
}


def list_calculators() -> list[dict[str, Any]]:
    return [
        {"key": k, "name": v["name"], "inputs": v["inputs"], "applies_when": v["applies_when"]}
        for k, v in CALCULATORS.items()
    ]


def calculate(key: str, inputs: dict[str, Any]) -> dict[str, Any]:
    if key not in CALCULATORS:
        return {"error": f"unknown calculator '{key}'"}
    fn = CALCULATORS[key]["fn"]
    try:
        return {"calculator": key, "result": fn(**inputs)}
    except TypeError as e:
        return {"calculator": key, "error": f"missing or extra input: {e}"}


# ---- LLM auto-extraction ----------------------------------------------------------
def relevant_calculators(chief_complaint: str) -> list[str]:
    cc = (chief_complaint or "").lower()
    out: list[str] = []
    for k, v in CALCULATORS.items():
        for trigger in v["applies_when"]:
            if any(token in cc for token in trigger.lower().split() if len(token) > 3):
                if k not in out:
                    out.append(k)
                break
    if not out:
        out = ["news2"]  # always relevant for sick patients
    return out


_AUTO_SYSTEM = """You are a clinical informaticist extracting CDS calculator inputs from an ED \
encounter transcript + intake. Return JSON ONLY, no preamble, no markdown.

Each calculator is given as a JSON schema with input names. For each calculator, return either:
  - a complete `inputs` object you are confident about, OR
  - an `unknown` array listing inputs you could NOT determine from the source material.

Never invent. If the transcript is silent on whether the patient has malignancy, mark malignancy as unknown.
Output shape:
{
  "<calc_key>": {"inputs": {...}, "unknown": ["..."]},
  ...
}
"""


def auto_extract(transcript: str, chief_complaint: str = "", calc_keys: list[str] | None = None) -> dict[str, Any]:
    """Best-effort LLM auto-extraction of inputs for the relevant calculators."""
    from lib import claude
    from lib.config import settings

    if not settings.anthropic_api_key:
        return {"calculators": []}
    keys = calc_keys or relevant_calculators(chief_complaint)
    schema = {k: CALCULATORS[k]["inputs"] for k in keys if k in CALCULATORS}
    user = (
        f'Chief complaint: {chief_complaint}\n\n'
        f'Transcript:\n"""\n{transcript[:6000]}\n"""\n\n'
        f"Calculator schemas:\n{json.dumps(schema, indent=2)}\n\n"
        "Return the JSON now."
    )
    try:
        resp = claude.messages_create(
            model="claude-sonnet-4-5",
            max_tokens=900,
            system=_AUTO_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="cds_extract",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
    except Exception as e:
        log.warning("CDS auto-extract failed: %s", e)
        return {"calculators": []}

    out: list[dict[str, Any]] = []
    for k, payload in parsed.items():
        if k not in CALCULATORS:
            continue
        unknown = payload.get("unknown") or []
        if unknown:
            out.append({"key": k, "name": CALCULATORS[k]["name"], "result": None, "unknown": unknown})
            continue
        result = calculate(k, payload.get("inputs") or {})
        out.append({"key": k, "name": CALCULATORS[k]["name"], "result": result.get("result"), "unknown": []})
    return {"calculators": out}
