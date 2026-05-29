"""CDS calculator library.

Each calculator is pure-Python deterministic scoring with the canonical published
rubric. Inputs are validated; missing inputs surface as a structured `missing`
list so the UI can prompt for them rather than the calc silently producing a
wrong answer (or raising a raw TypeError).

Auto-extraction (LLM-driven) lives in `auto_extract()` — given a transcript +
encounter context, it tries to fill in inputs for the calculators most relevant
to the chief complaint, and returns the calculator results inline. Inputs the
model could not determine are flagged in `unknown`, never guessed.

Calculators implemented:
    - HEART score (chest pain risk)            — Six AJ et al., Neth Heart J 2008
    - Wells score for PE                       — Wells PS et al., Ann Intern Med 2001
    - Wells score for DVT                      — Wells PS et al., NEJM 2003
    - PERC rule (PE rule-out)                  — Kline JA et al., J Thromb Haemost 2004
    - CHA2DS2-VASc (AF stroke risk)            — Lip GYH et al., Chest 2010
    - NIHSS (stroke severity)                  — Brott T et al., Stroke 1989
    - CURB-65 (pneumonia severity)             — Lim WS et al., Thorax 2003
    - qSOFA (sepsis screen)                    — Seymour CW et al., JAMA 2016 (Sepsis-3)
    - MEWS (deterioration)                     — Subbe CP et al., QJM 2001
    - NEWS2 (deterioration)                    — RCP, National Early Warning Score 2, 2017
    - Centor + McIsaac (strep pharyngitis)     — Centor RM 1981; McIsaac WJ, CMAJ 1998
    - GCS (Glasgow Coma)                       — Teasdale G, Jennett B, Lancet 1974
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _bool(v: Any) -> int:
    return 1 if v else 0


def _clamp(v: Any, lo: int, hi: int) -> int:
    """Coerce to int and clamp to [lo, hi]. Non-numeric -> lo."""
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return lo


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
    Six AJ, Backus BE, Kelder JC. Neth Heart J 2008;16(6):191-6.
    """
    history, ekg, age = _clamp(history, 0, 2), _clamp(ekg, 0, 2), _clamp(age, 0, 2)
    risk_factors, troponin = _clamp(risk_factors, 0, 2), _clamp(troponin, 0, 2)
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
        "citation": "Six AJ et al., Neth Heart J 2008;16(6):191-6.",
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
    """Wells criteria for pulmonary embolism (original 3-tier and dichotomized cutoffs).
    Wells PS et al., Ann Intern Med 2001;135(2):98-107.
    """
    pts = (
        3 * _bool(clinical_signs_dvt)
        + 3 * _bool(pe_most_likely)
        + 1.5 * _bool(hr_over_100)
        + 1.5 * _bool(immobilization_or_surgery_4wk)
        + 1.5 * _bool(prior_pe_or_dvt)
        + 1 * _bool(hemoptysis)
        + 1 * _bool(malignancy)
    )
    # Three-tier interpretation
    if pts < 2:
        tier = "low"
    elif pts <= 6:
        tier = "moderate"
    else:
        tier = "high"
    # Dichotomized (modified Wells) interpretation
    if pts <= 4:
        risk, action = "PE unlikely", "D-dimer; if negative, PE excluded"
    else:
        risk, action = "PE likely", "CTPA (or V/Q if contrast contraindicated)"
    return {
        "score": pts,
        "risk": risk,
        "tier": tier,
        "action": action,
        "citation": "Wells PS et al., Ann Intern Med 2001;135(2):98-107.",
    }


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
    """Wells criteria for deep vein thrombosis.
    Wells PS et al., NEJM 2003;349(13):1227-35.
    """
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
    return {
        "score": pts,
        "risk": risk,
        "action": action,
        "citation": "Wells PS et al., NEJM 2003;349(13):1227-35.",
    }


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
    """PERC: 8 criteria; PERC-negative only valid in a low-pretest-probability patient.
    Kline JA et al., J Thromb Haemost 2004;2(8):1247-55.
    """
    criteria = {
        "age_under_50": bool(age_under_50),
        "hr_under_100": bool(hr_under_100),
        "spo2_at_least_95": bool(spo2_at_least_95),
        "no_unilateral_leg_swelling": bool(no_unilateral_leg_swelling),
        "no_hemoptysis": bool(no_hemoptysis),
        "no_recent_surgery_trauma": bool(no_recent_surgery_trauma),
        "no_prior_pe_dvt": bool(no_prior_pe_dvt),
        "no_estrogen": bool(no_estrogen),
    }
    failed = [k for k, v in criteria.items() if not v]
    all_negative = not failed
    if all_negative:
        return {
            "perc_negative": True,
            "failed_criteria": [],
            "action": "PE excluded clinically (valid only in low-pretest-probability patient)",
            "citation": "Kline JA et al., J Thromb Haemost 2004;2(8):1247-55.",
        }
    return {
        "perc_negative": False,
        "failed_criteria": failed,
        "action": "Cannot rule out PE; pursue D-dimer or imaging per Wells",
        "citation": "Kline JA et al., J Thromb Haemost 2004;2(8):1247-55.",
    }


# ---- CHA2DS2-VASc -----------------------------------------------------------------
def cha2ds2_vasc(
    age: int,
    sex: str,
    chf: bool = False,
    hypertension: bool = False,
    diabetes: bool = False,
    stroke_tia_thromboembolism: bool = False,
    vascular_disease: bool = False,
) -> dict[str, Any]:
    """CHA2DS2-VASc stroke risk in non-valvular atrial fibrillation.
    Age 65-74 = 1, >=75 = 2. Female sex = 1. Prior stroke/TIA/TE = 2. Each other = 1.
    Lip GYH et al., Chest 2010;137(2):263-72.
    """
    try:
        age_n = int(round(float(age)))
    except (TypeError, ValueError):
        age_n = 0
    age_pts = 2 if age_n >= 75 else (1 if age_n >= 65 else 0)
    sex_pts = 1 if str(sex).strip().upper().startswith("F") else 0
    components = {
        "chf": _bool(chf),
        "hypertension": _bool(hypertension),
        "age": age_pts,
        "diabetes": _bool(diabetes),
        "stroke_tia_thromboembolism": 2 * _bool(stroke_tia_thromboembolism),
        "vascular_disease": _bool(vascular_disease),
        "sex_female": sex_pts,
    }
    total = sum(components.values())
    # Annualized adjusted stroke rate (Friberg L et al., Eur Heart J 2012)
    rates = {
        0: "0.2%", 1: "0.6%", 2: "2.2%", 3: "3.2%", 4: "4.8%",
        5: "7.2%", 6: "9.7%", 7: "11.2%", 8: "10.8%", 9: "12.2%",
    }
    if total == 0 or (total == 1 and sex_pts == 1):
        recommendation = "No anticoagulation recommended (low risk; female sex alone does not count)"
    elif total == 1:
        recommendation = "Consider anticoagulation (clinical judgment; oral anticoagulant may be offered)"
    else:
        recommendation = "Oral anticoagulation recommended"
    return {
        "score": total,
        "annual_stroke_risk": rates.get(total, ">12%"),
        "recommendation": recommendation,
        "components": components,
        "citation": "Lip GYH et al., Chest 2010;137(2):263-72; rates Friberg L et al., Eur Heart J 2012.",
    }


# ---- NIHSS (15 items) -------------------------------------------------------------
# Per-item maximum scores per the official NIH Stroke Scale.
_NIHSS_MAX = {
    "loc": 3,
    "loc_questions": 2,
    "loc_commands": 2,
    "best_gaze": 2,
    "visual": 3,
    "facial_palsy": 3,
    "motor_arm_left": 4,
    "motor_arm_right": 4,
    "motor_leg_left": 4,
    "motor_leg_right": 4,
    "limb_ataxia": 2,
    "sensory": 2,
    "best_language": 3,
    "dysarthria": 2,
    "extinction_inattention": 2,
}


def nihss(items: dict[str, int]) -> dict[str, Any]:
    """NIH Stroke Scale, 15 items. Each item is clamped to its published per-item
    maximum so an out-of-range entry cannot inflate the total.
    Brott T et al., Stroke 1989;20(7):864-70.
    """
    items = items or {}
    clamped: dict[str, int] = {}
    for k, hi in _NIHSS_MAX.items():
        clamped[k] = _clamp(items.get(k, 0), 0, hi)
    total = sum(clamped.values())
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
    return {
        "score": total,
        "severity": sev,
        "components": clamped,
        "citation": "Brott T et al., Stroke 1989;20(7):864-70.",
    }


# ---- CURB-65 ---------------------------------------------------------------------
def curb65(
    confusion: bool,
    bun_over_19: bool,
    rr_at_least_30: bool,
    sbp_under_90_or_dbp_at_most_60: bool,
    age_at_least_65: bool,
) -> dict[str, Any]:
    """CURB-65 community-acquired pneumonia severity.
    Lim WS et al., Thorax 2003;58(5):377-82.
    """
    pts = sum(
        _bool(x)
        for x in [confusion, bun_over_19, rr_at_least_30, sbp_under_90_or_dbp_at_most_60, age_at_least_65]
    )
    if pts <= 1:
        action = "Low severity — outpatient management"
        mortality_30d = "0.6-2.7%"
    elif pts == 2:
        action = "Moderate severity — short inpatient or close outpatient observation"
        mortality_30d = "6.8-9.2%"
    else:
        action = "Severe — inpatient; consider ICU if score >=3"
        mortality_30d = "14-57%"
    return {
        "score": pts,
        "action": action,
        "mortality_30d": mortality_30d,
        "citation": "Lim WS et al., Thorax 2003;58(5):377-82.",
    }


# ---- qSOFA -----------------------------------------------------------------------
def qsofa(rr_at_least_22: bool, altered_mental: bool, sbp_at_most_100: bool) -> dict[str, Any]:
    """quick SOFA — bedside sepsis screen (Sepsis-3).
    Seymour CW et al., JAMA 2016;315(8):762-74.
    """
    pts = _bool(rr_at_least_22) + _bool(altered_mental) + _bool(sbp_at_most_100)
    flag = pts >= 2
    return {
        "score": pts,
        "high_risk": flag,
        "action": (
            "Sepsis workup, lactate, blood cultures, broad-spectrum abx, fluids"
            if flag
            else "Continue assessment; qSOFA <2 does not exclude sepsis"
        ),
        "citation": "Seymour CW et al., JAMA 2016;315(8):762-74.",
    }


# ---- MEWS ------------------------------------------------------------------------
def mews(rr: float, hr: float, sbp: float, temp_c: float, avpu: str) -> dict[str, Any]:
    """Modified Early Warning Score. Five physiological parameters, each 0-3.
    avpu: one of 'alert', 'voice', 'pain', 'unresponsive'.
    Subbe CP et al., QJM 2001;94(10):521-6.
    """
    def num(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    score = 0
    components: dict[str, int] = {}

    rr_v = num(rr)
    if rr_v is None:
        rr_pts = 0
    elif rr_v < 9:
        rr_pts = 2
    elif rr_v <= 14:
        rr_pts = 0
    elif rr_v <= 20:
        rr_pts = 1
    elif rr_v <= 29:
        rr_pts = 2
    else:
        rr_pts = 3
    components["respiratory_rate"] = rr_pts

    hr_v = num(hr)
    if hr_v is None:
        hr_pts = 0
    elif hr_v < 40:
        hr_pts = 2
    elif hr_v <= 50:
        hr_pts = 1
    elif hr_v <= 100:
        hr_pts = 0
    elif hr_v <= 110:
        hr_pts = 1
    elif hr_v <= 129:
        hr_pts = 2
    else:
        hr_pts = 3
    components["heart_rate"] = hr_pts

    sbp_v = num(sbp)
    if sbp_v is None:
        sbp_pts = 0
    elif sbp_v <= 70:
        sbp_pts = 3
    elif sbp_v <= 80:
        sbp_pts = 2
    elif sbp_v <= 100:
        sbp_pts = 1
    elif sbp_v <= 199:
        sbp_pts = 0
    else:
        sbp_pts = 2
    components["systolic_bp"] = sbp_pts

    temp_v = num(temp_c)
    if temp_v is None:
        temp_pts = 0
    elif temp_v < 35:
        temp_pts = 2
    elif temp_v <= 38.4:
        temp_pts = 0
    else:
        temp_pts = 2
    components["temperature"] = temp_pts

    avpu_map = {"alert": 0, "voice": 1, "pain": 2, "unresponsive": 3}
    avpu_pts = avpu_map.get(str(avpu).strip().lower(), 0)
    components["avpu"] = avpu_pts

    score = sum(components.values())
    if score >= 5:
        risk = "high — urgent medical review, consider critical care outreach"
    elif score >= 3:
        risk = "medium — increase observation frequency, nurse-in-charge review"
    else:
        risk = "low — routine monitoring"
    return {
        "score": score,
        "risk": risk,
        "components": components,
        "citation": "Subbe CP et al., QJM 2001;94(10):521-6.",
    }


# ---- NEWS2 -----------------------------------------------------------------------
def news2(rr: float, spo2: float, on_oxygen: bool, sbp: float, hr: float, temp_c: float, alert: bool) -> dict[str, Any]:
    """National Early Warning Score 2 (Scale 1 SpO2).
    Royal College of Physicians, NEWS2, 2017.
    """
    def num(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    components: dict[str, int] = {}

    # Respiratory rate
    rr_v = num(rr)
    if rr_v is None:
        rr_pts = 0
    elif rr_v <= 8:
        rr_pts = 3
    elif rr_v <= 11:
        rr_pts = 1
    elif rr_v <= 20:
        rr_pts = 0
    elif rr_v <= 24:
        rr_pts = 2
    else:
        rr_pts = 3
    components["respiratory_rate"] = rr_pts

    # SpO2 (Scale 1)
    spo2_v = num(spo2)
    if spo2_v is None:
        spo2_pts = 0
    elif spo2_v <= 91:
        spo2_pts = 3
    elif spo2_v <= 93:
        spo2_pts = 2
    elif spo2_v <= 95:
        spo2_pts = 1
    else:
        spo2_pts = 0
    components["spo2"] = spo2_pts

    # Air vs supplemental oxygen
    components["supplemental_oxygen"] = 2 if on_oxygen else 0

    # Systolic BP — ascending bands, evaluated low-to-high
    sbp_v = num(sbp)
    if sbp_v is None:
        sbp_pts = 0
    elif sbp_v <= 90:
        sbp_pts = 3
    elif sbp_v <= 100:
        sbp_pts = 2
    elif sbp_v <= 110:
        sbp_pts = 1
    elif sbp_v <= 219:
        sbp_pts = 0
    else:
        sbp_pts = 3
    components["systolic_bp"] = sbp_pts

    # Heart rate — strict ascending bands (fixes prior ordering bug where the
    # `hr >= 91 or hr <= 50` branch swallowed the 51-90 normal range and the
    # 41-50 bradycardia band).
    hr_v = num(hr)
    if hr_v is None:
        hr_pts = 0
    elif hr_v <= 40:
        hr_pts = 3
    elif hr_v <= 50:
        hr_pts = 1
    elif hr_v <= 90:
        hr_pts = 0
    elif hr_v <= 110:
        hr_pts = 1
    elif hr_v <= 130:
        hr_pts = 2
    else:
        hr_pts = 3
    components["heart_rate"] = hr_pts

    # Temperature
    temp_v = num(temp_c)
    if temp_v is None:
        temp_pts = 0
    elif temp_v <= 35.0:
        temp_pts = 3
    elif temp_v <= 36.0:
        temp_pts = 1
    elif temp_v <= 38.0:
        temp_pts = 0
    elif temp_v <= 39.0:
        temp_pts = 1
    else:
        temp_pts = 2
    components["temperature"] = temp_pts

    # Consciousness (AVPU): new confusion or not alert = 3
    components["consciousness"] = 0 if alert else 3

    score = sum(components.values())
    # Any single parameter scoring 3 triggers the "low-medium" escalation band.
    any_param_3 = any(v == 3 for v in components.values())
    if score >= 7:
        risk = "high — emergency assessment by critical care, continuous monitoring"
        clinical_response = "emergency"
    elif score >= 5 or any_param_3:
        risk = "medium — urgent review by clinician able to escalate to critical care"
        clinical_response = "urgent"
    elif score >= 1:
        risk = "low — assessment by registered nurse, monitoring at least 4-6 hourly"
        clinical_response = "routine"
    else:
        risk = "low — routine monitoring at least 12 hourly"
        clinical_response = "routine"
    return {
        "score": score,
        "risk": risk,
        "clinical_response": clinical_response,
        "any_parameter_3": any_param_3,
        "components": components,
        "citation": "Royal College of Physicians, National Early Warning Score 2 (NEWS2), 2017.",
    }


# ---- Centor + McIsaac -------------------------------------------------------------
def centor(
    age: int,
    tonsillar_exudate: bool,
    tender_anterior_cervical_nodes: bool,
    fever_history: bool,
    cough_absent: bool,
) -> dict[str, Any]:
    """Centor criteria with the McIsaac age modifier for group-A strep pharyngitis.
    Centor RM et al., Med Decis Making 1981;1(3):239-46;
    McIsaac WJ et al., CMAJ 1998;158(1):75-83.
    """
    try:
        age_n = int(round(float(age)))
    except (TypeError, ValueError):
        age_n = 30
    pts = (
        _bool(tonsillar_exudate)
        + _bool(tender_anterior_cervical_nodes)
        + _bool(fever_history)
        + _bool(cough_absent)
    )
    if age_n < 15:
        pts += 1
    elif age_n >= 45:
        pts -= 1
    if pts <= 0:
        action = "GAS risk 1-2.5% — no testing or antibiotics"
    elif pts == 1:
        action = "GAS risk ~5-10% — no testing; symptomatic care"
    elif pts in (2, 3):
        action = "GAS risk ~11-35% — rapid antigen test; treat if positive"
    else:
        action = "GAS risk ~51% — test; consider empiric antibiotics"
    return {
        "score": pts,
        "action": action,
        "citation": "Centor RM 1981; McIsaac WJ et al., CMAJ 1998;158(1):75-83.",
    }


# ---- GCS --------------------------------------------------------------------------
def gcs(eye: int, verbal: int, motor: int) -> dict[str, Any]:
    """Glasgow Coma Scale. Eye 1-4, Verbal 1-5, Motor 1-6 (each clamped to its
    valid range — minimum subscale value is 1, not 0).
    Teasdale G, Jennett B. Lancet 1974;2(7872):81-4.
    """
    eye_c = _clamp(eye, 1, 4)
    verbal_c = _clamp(verbal, 1, 5)
    motor_c = _clamp(motor, 1, 6)
    total = eye_c + verbal_c + motor_c
    if total >= 13:
        sev = "minor"
    elif total >= 9:
        sev = "moderate"
    else:
        sev = "severe"
    return {
        "score": total,
        "severity": sev,
        "components": {"eye": eye_c, "verbal": verbal_c, "motor": motor_c},
        "citation": "Teasdale G, Jennett B. Lancet 1974;2(7872):81-4.",
    }


# ---- Registry --------------------------------------------------------------------
CALCULATORS: dict[str, dict[str, Any]] = {
    "heart": {
        "name": "HEART score (chest pain)",
        "fn": heart,
        "inputs": ["history (0-2)", "ekg (0-2)", "age (0-2)", "risk_factors (0-2)", "troponin (0-2)"],
        "applies_when": ["chest pain", "chest pressure", "angina"],
        "citation": "Six AJ et al., Neth Heart J 2008;16(6):191-6.",
    },
    "wells_pe": {
        "name": "Wells score for PE",
        "fn": wells_pe,
        "inputs": [
            "clinical_signs_dvt", "pe_most_likely", "hr_over_100",
            "immobilization_or_surgery_4wk", "prior_pe_or_dvt", "hemoptysis", "malignancy",
        ],
        "applies_when": ["dyspnea", "pleuritic chest pain", "hemoptysis", "leg swelling"],
        "citation": "Wells PS et al., Ann Intern Med 2001;135(2):98-107.",
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
        "citation": "Wells PS et al., NEJM 2003;349(13):1227-35.",
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
        "citation": "Kline JA et al., J Thromb Haemost 2004;2(8):1247-55.",
    },
    "cha2ds2_vasc": {
        "name": "CHA2DS2-VASc (AF stroke risk)",
        "fn": cha2ds2_vasc,
        "inputs": [
            "age (years, int)", "sex (M/F)", "chf", "hypertension", "diabetes",
            "stroke_tia_thromboembolism", "vascular_disease",
        ],
        "applies_when": ["atrial fibrillation", "palpitations", "irregular heartbeat", "afib"],
        "citation": "Lip GYH et al., Chest 2010;137(2):263-72.",
    },
    "nihss": {
        "name": "NIH Stroke Scale",
        "fn": nihss,
        "inputs": ["items (dict of 15 component scores)"],
        "applies_when": ["weakness", "speech change", "facial droop", "stroke"],
        "citation": "Brott T et al., Stroke 1989;20(7):864-70.",
    },
    "curb65": {
        "name": "CURB-65 (pneumonia severity)",
        "fn": curb65,
        "inputs": ["confusion", "bun_over_19", "rr_at_least_30", "sbp_under_90_or_dbp_at_most_60", "age_at_least_65"],
        "applies_when": ["pneumonia", "cough with fever", "shortness of breath with fever"],
        "citation": "Lim WS et al., Thorax 2003;58(5):377-82.",
    },
    "qsofa": {
        "name": "qSOFA (sepsis screen)",
        "fn": qsofa,
        "inputs": ["rr_at_least_22", "altered_mental", "sbp_at_most_100"],
        "applies_when": ["fever", "sepsis suspected", "hypotension", "altered mentation"],
        "citation": "Seymour CW et al., JAMA 2016;315(8):762-74.",
    },
    "mews": {
        "name": "MEWS (deterioration)",
        "fn": mews,
        "inputs": ["rr", "hr", "sbp", "temp_c", "avpu (alert/voice/pain/unresponsive)"],
        "applies_when": ["any acutely ill patient with vitals"],
        "citation": "Subbe CP et al., QJM 2001;94(10):521-6.",
    },
    "news2": {
        "name": "NEWS2 (deterioration)",
        "fn": news2,
        "inputs": ["rr", "spo2", "on_oxygen", "sbp", "hr", "temp_c", "alert"],
        "applies_when": ["any acutely ill patient with vitals"],
        "citation": "Royal College of Physicians, NEWS2, 2017.",
    },
    "centor": {
        "name": "Centor + McIsaac (strep)",
        "fn": centor,
        "inputs": ["age", "tonsillar_exudate", "tender_anterior_cervical_nodes", "fever_history", "cough_absent"],
        "applies_when": ["sore throat", "pharyngitis"],
        "citation": "Centor RM 1981; McIsaac WJ et al., CMAJ 1998;158(1):75-83.",
    },
    "gcs": {
        "name": "Glasgow Coma Scale",
        "fn": gcs,
        "inputs": ["eye (1-4)", "verbal (1-5)", "motor (1-6)"],
        "applies_when": ["altered mental status", "head injury", "coma"],
        "citation": "Teasdale G, Jennett B. Lancet 1974;2(7872):81-4.",
    },
}


def list_calculators() -> list[dict[str, Any]]:
    return [
        {
            "key": k,
            "name": v["name"],
            "inputs": v["inputs"],
            "applies_when": v["applies_when"],
            "citation": v.get("citation", ""),
        }
        for k, v in CALCULATORS.items()
    ]


def _required_params(fn: Any) -> list[str]:
    """Parameter names of `fn` that have no default value."""
    sig = inspect.signature(fn)
    return [
        name
        for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]


def calculate(key: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Run a calculator. Returns a structured payload.

    Shapes:
      unknown calculator -> {"error": "..."}
      missing inputs     -> {"calculator", "result": None, "missing": [...], "error": "..."}
      extra inputs only  -> ignored (dropped) so callers cannot crash the calc
      success            -> {"calculator", "result": {...}}
    """
    if key not in CALCULATORS:
        return {"error": f"unknown calculator '{key}'"}
    fn = CALCULATORS[key]["fn"]
    inputs = dict(inputs or {})

    sig = inspect.signature(fn)
    valid = set(sig.parameters)
    required = _required_params(fn)

    missing = [p for p in required if p not in inputs or inputs[p] is None]
    if missing:
        return {
            "calculator": key,
            "result": None,
            "missing": missing,
            "error": f"missing required input(s): {', '.join(missing)}",
        }

    # Drop any extra keys rather than letting fn(**inputs) raise a TypeError.
    cleaned = {k: v for k, v in inputs.items() if k in valid}
    try:
        return {"calculator": key, "result": fn(**cleaned)}
    except (TypeError, ValueError) as e:
        return {"calculator": key, "result": None, "missing": [], "error": f"calculation error: {e}"}


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
    """Best-effort LLM auto-extraction of inputs for the relevant calculators.

    Each returned calculator carries a `missing` list — either inputs the model
    flagged as `unknown`, or required inputs absent from the model's `inputs`
    object. A calculator is only scored when nothing is missing.
    """
    from lib import claude
    from lib.config import settings

    if not claude.available():
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
            model=settings.model_clinical,
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
        unknown = list(payload.get("unknown") or [])
        inputs = payload.get("inputs") or {}
        fn = CALCULATORS[k]["fn"]
        required = _required_params(fn)
        missing_required = [
            p for p in required
            if (p not in inputs or inputs[p] is None) and p not in unknown
        ]
        missing = sorted(set(unknown) | set(missing_required))
        if missing:
            out.append({
                "key": k,
                "name": CALCULATORS[k]["name"],
                "result": None,
                "missing": missing,
                "citation": CALCULATORS[k].get("citation", ""),
            })
            continue
        result = calculate(k, inputs)
        out.append({
            "key": k,
            "name": CALCULATORS[k]["name"],
            "result": result.get("result"),
            "missing": result.get("missing", []),
            "citation": CALCULATORS[k].get("citation", ""),
        })
    return {"calculators": out}
