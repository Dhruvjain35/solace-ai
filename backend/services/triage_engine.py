# Triage.ai — Clinical Decision Support System
# Copyright (c) 2026 Dhruv Jain & Sriyan Bodla. All rights reserved.
#
# Ported from triagegeist-live-demo/model.py into Solace. Same clinically-validated
# simulation heuristics that match the thresholds and feature engineering from the
# Triage.ai training notebook. Swap MODEL_MODE to "trained" once pickles are exported.

"""Clinical triage prediction engine for ESI level estimation."""
from __future__ import annotations

import logging
import math

_log = logging.getLogger("triage_engine")

MODEL_MODE = "simulation"

ESI_LABELS = {
    1: "RESUSCITATION",
    2: "EMERGENT",
    3: "URGENT",
    4: "LESS URGENT",
    5: "NON-URGENT",
}

import re as _re

# Regex-based keyword patterns — catch natural language variations patients actually use.
ESI_1_PATTERNS = [
    r"cardiac arrest|unresponsive|not breathing|pulseless|apneic|code blue|gsw.?head|hanging|no pulse|cpr",
    r"dying|going to die|i.?m dead|life.?threatening|fatal|near.?death",
]
ESI_2_PATTERNS = [
    r"chest.?pain|chest.?tight|chest.?pressure|angina|heart.?attack|mi\b|myocardial",
    r"chest.*hurt|chest.*crush|chest.*heavy|chest.*burn|heart.*rac|heart.*pound|heart.*stop|heart.*fail",
    r"stroke|facial.?droop|arm.?weakness|slurred.?speech|hemiparesis|aphasia|one.?side.*numb|paralyz|can.?t.?move|can.?t.?feel",
    r"seizure|convuls|postictal|shaking.?uncontrollab|epilep|fitting|fits",
    r"overdose|ingestion|poison|took.?too.?many|swallowed|od\b|drug.*too.*much",
    r"suicid|kill.?my|want.?to.?die|self.?harm|cutting.?my|end.?my.?life|don.?t.?want.?to.?live|hurt.?my",
    r"anaphylax|throat.?swell|can.?t.?swallow|allergic.?react|epipen|severe.?allerg|face.*swell|tongue.*swell|lip.*swell",
    r"severe.?bleed|hemorrhag|blood.?everywhere|won.?t.?stop.?bleed|hemoptysis|hematemesis|cough.*blood|blood.*cough|vomit.*blood|blood.*vomit",
    r"stab|gunshot|gsw|shot|penetrat.?wound|impale",
    r"altered.?mental|confused.*sudden|not.?making.?sense|disoriented|pass.?out|faint|unconscious|black.?out|collaps",
    r"can.?t.?breathe|shortness.?of.?breath|difficulty.?breath|dyspnea|resp.?distress|suffocating|gasping|struggling.?to.?breath|hard.?to.?breath|trouble.?breath|breath.*difficult|breath.*problem|breath.*hard|can.?t.?get.?air|choking",
    r"acute.?abdomen|testicular.?torsion|ectopic",
    r"blood.?pressure.*very|blood.?pressure.*dangerously|blood.?pressure.*extremely",
    r"vision.?loss|can.?t.?see|blind|sudden.*vision|blurr.*vision.*sudden",
    r"excruciating|unbearable|worst.?pain|agony|10.?out.?of.?10|severe.?pain|extreme.?pain|intense.?pain",
    r"emergency|life.?threaten|critical|urgent.*severe|very.*serious|really.*bad|really.*serious|seriously.*ill|seriously.*hurt|seriously.*injur",
    r"broken.*hip|broken.*skull|broken.*neck|broken.*spine|broken.*back|head.*injur|head.*trauma|concuss|brain.*bleed",
    r"diabetic.*emergency|blood.?sugar.*very|blood.?sugar.*dangerously|insulin.*shock|diabetic.*coma",
    r"asthma.*attack|asthma.*can.?t|asthma.*severe|asthma.*bad|asthma.*emergency",
    r"sepsis|septic|blood.?infect|organ.?fail",
    r"pregnant.*bleed|miscarriag|labor.*early|premature.*labor|water.*broke|contractions",
    r"burn.*severe|burn.*degree|burn.*face|burn.*large|chemical.*burn|electrical.*burn",
]
ESI_3_PATTERNS = [
    r"abdomin.?pain|stomach.?pain|belly.?hurts|cramp",
    r"fever|temperature|feel.?hot|burning.?up|chills",
    r"vomit|throwing.?up|nause|puking",
    r"diarrhea|loose.?stool|watery.?stool",
    r"headache|migraine|head.?hurts|worst.?headache",
    r"back.?pain|lower.?back|spine",
    r"fall|fell|tripped|slip",
    r"lacerat|cut.?my|gash|wound|bleeding",
    r"fracture|broke|broken.?bone|snapped",
    r"urinary|burning.?pee|uti|blood.?in.?urine|can.?t.?pee",
    r"asthma|wheez|inhaler.?not.?work",
    r"diabet|blood.?sugar|glucose|insulin",
    r"infect|cellulitis|abscess|pus|swollen.*red.*warm",
    r"pneumonia|lung.?infect",
]
ESI_4_PATTERNS = [
    r"sprain|strain|twist|rolled.?my",
    r"rash|hives|itch|skin.?break",
    r"ear.?pain|ear.?ache|ear.?infect",
    r"sore.?throat|throat.?hurts|tonsil|strep",
    r"cough|cold|congestion|runny.?nose|stuffy",
    r"minor.?burn|small.?burn",
    r"ankle|knee.?pain|shoulder.?pain|wrist|elbow",
    r"prescri|refill|suture.?remov",
]
ESI_5_PATTERNS = [
    r"medication.?refill|work.?note|clearance|suture.?check|routine|follow.?up|check.?up|normal.?visit",
]

# Legacy keyword lists (kept for backward compat with any code referencing them)
ESI_1_KEYWORDS = ["cardiac arrest", "unresponsive", "not breathing", "pulseless", "apneic", "code blue", "gsw head", "hanging"]
ESI_2_KEYWORDS = ["chest pain", "stroke", "seizure", "overdose", "suicidal", "anaphylaxis", "severe bleeding", "stab wound", "gunshot", "altered mental", "difficulty breathing", "shortness of breath", "acute abdomen", "testicular torsion", "ectopic"]
ESI_3_KEYWORDS = ["abdominal pain", "fever", "vomiting", "diarrhea", "headache", "back pain", "fall", "laceration", "fracture", "urinary", "asthma", "diabetes", "infection", "cellulitis", "pneumonia"]
ESI_4_KEYWORDS = ["sprain", "strain", "rash", "ear pain", "sore throat", "cough", "minor burn", "ankle", "knee pain", "shoulder pain", "wrist", "prescription", "refill", "suture removal"]
ESI_5_KEYWORDS = ["medication refill", "work note", "clearance", "suture check", "routine", "follow up"]


def _compute_vital_flags(
    heart_rate: float,
    sbp: float,
    dbp: float,
    o2_sat: float,
    resp_rate: float,
    temperature: float,
    gcs: int,
) -> dict[str, bool]:
    return {
        "hypotension": sbp < 90,
        "severe_hypotension": sbp < 70,
        "hypertensive": sbp > 180,
        "tachycardia": heart_rate > 100,
        "severe_tachycardia": heart_rate > 130,
        "bradycardia": heart_rate < 50,
        "hypoxia": o2_sat < 94,
        "severe_hypoxia": o2_sat < 88,
        "tachypnea": resp_rate > 22,
        "fever": temperature > 100.4,
        "hypothermia": temperature < 95.0,
        "severe_gcs": gcs <= 8,
        "altered_mental": gcs < 14,
        "shock_index_elevated": (heart_rate / max(sbp, 1)) > 1.0,
    }


def _compute_composites(
    heart_rate: float,
    sbp: float,
    resp_rate: float,
    temperature: float,
    gcs: int,
    flags: dict[str, bool],
) -> dict[str, float]:
    qsofa = int(sbp <= 100) + int(resp_rate >= 22) + int(gcs < 15)
    sirs = (
        int(temperature > 100.4 or temperature < 96.8)
        + int(heart_rate > 90)
        + int(resp_rate > 20)
    )
    shock_index = heart_rate / max(sbp, 1)
    cv_risk = (
        int(flags["hypotension"])
        + int(flags["tachycardia"])
        + int(flags["shock_index_elevated"])
        + int(flags["hypoxia"])
    )
    return {
        "qsofa": qsofa,
        "sirs": sirs,
        "shock_index": round(shock_index, 2),
        "cv_risk": cv_risk,
    }


def _parse_chief_complaint(text: str) -> tuple[int, float]:
    """Return (best matching ESI level, match confidence) using regex patterns.

    Clinical safety rule: the most critical (lowest) ESI level with ANY match
    always wins. A single "can't breathe" (ESI 2) must never be outranked by
    three ESI 3 symptoms. Multiple matches at the winning level boost confidence.
    """
    normalized = text.lower().strip()

    pattern_map = [
        (ESI_1_PATTERNS, 1, 0.92),
        (ESI_2_PATTERNS, 2, 0.78),
        (ESI_3_PATTERNS, 3, 0.68),
        (ESI_4_PATTERNS, 4, 0.72),
        (ESI_5_PATTERNS, 5, 0.85),
    ]

    _log.info("TRIAGE_PARSE complaint=%r", normalized[:200])

    # Scan from most critical to least — first level with a match wins
    for patterns, level, base_conf in pattern_map:
        matched = [pat for pat in patterns if _re.search(pat, normalized)]
        if matched:
            conf = min(base_conf + 0.03 * (len(matched) - 1), 0.95)
            _log.info("TRIAGE_MATCH level=%d conf=%.2f matches=%d first=%s", level, conf, len(matched), matched[0][:60])
            return level, conf

    _log.warning("TRIAGE_NO_MATCH complaint=%r — defaulting to ESI 3", normalized[:200])

    # Fallback: try legacy exact-substring matching (most critical first)
    legacy_map = [
        (ESI_1_KEYWORDS, 1, 0.90),
        (ESI_2_KEYWORDS, 2, 0.75),
        (ESI_3_KEYWORDS, 3, 0.60),
        (ESI_4_KEYWORDS, 4, 0.65),
        (ESI_5_KEYWORDS, 5, 0.80),
    ]
    for keywords, level, base_conf in legacy_map:
        for kw in keywords:
            if kw in normalized:
                return level, base_conf
    return 3, 0.40


def _softmax(scores: list[float]) -> list[float]:
    max_s = max(scores)
    exps = [math.exp(s - max_s) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def _compute_esi_scores(
    complaint_level: int,
    complaint_conf: float,
    flags: dict[str, bool],
    composites: dict[str, float],
    age: int,
    arrival_mode: str,
    n_comorbidities: int,
    gcs: int,
) -> tuple[int, list[float]]:
    """Compute ESI level and class probabilities."""
    if flags["severe_gcs"]:
        scores = [6.0, 1.0, 0.0, -2.0, -4.0]
        return 1, _softmax(scores)

    if complaint_level == 1 and complaint_conf > 0.8:
        scores = [5.5, 1.0, -0.5, -3.0, -5.0]
        return 1, _softmax(scores)

    if complaint_level == 2 and complaint_conf > 0.7:
        scores = [1.0, 5.0, 0.5, -2.0, -4.0]
        return 2, _softmax(scores)

    if flags["severe_hypotension"] and flags["severe_tachycardia"]:
        scores = [5.0, 2.0, 0.0, -3.0, -5.0]
        return 1, _softmax(scores)

    scores = [0.0, 0.0, 0.0, 0.0, 0.0]

    complaint_weight = 3.5
    for level in range(1, 6):
        distance = abs(level - complaint_level)
        scores[level - 1] += complaint_weight * (3.0 - distance) * complaint_conf

    num_abnormal = sum(1 for v in flags.values() if v)
    if num_abnormal >= 5:
        scores[0] += 3.0
        scores[1] += 2.0
    elif num_abnormal >= 3:
        scores[0] += 1.0
        scores[1] += 2.5
        scores[2] += 1.0
    elif num_abnormal >= 1:
        scores[1] += 1.0
        scores[2] += 1.5
    else:
        scores[3] += 1.5
        scores[4] += 1.0

    qsofa = composites["qsofa"]
    if qsofa >= 2:
        scores[0] += 2.0
        scores[1] += 1.5
    elif qsofa == 1:
        scores[1] += 0.8
        scores[2] += 0.5

    sirs = composites["sirs"]
    if sirs >= 2:
        scores[1] += 1.2
        scores[2] += 0.6

    cv_risk = composites["cv_risk"]
    if cv_risk >= 3:
        scores[0] += 1.5
        scores[1] += 1.0
    elif cv_risk >= 2:
        scores[1] += 1.2
    elif cv_risk >= 1:
        scores[2] += 0.8

    if age >= 75:
        scores[0] += 0.3
        scores[1] += 0.6
        scores[2] += 0.4
        scores[3] -= 0.3
        scores[4] -= 0.5
    elif age >= 65:
        scores[1] += 0.3
        scores[2] += 0.3
        scores[4] -= 0.3
    elif age <= 5:
        scores[1] += 0.4
        scores[2] += 0.3

    if arrival_mode == "Ambulance":
        scores[0] += 0.5
        scores[1] += 0.8
        scores[2] += 0.3
        scores[4] -= 0.5
    elif arrival_mode == "Police":
        scores[1] += 0.5
        scores[2] += 0.3
    elif arrival_mode == "Transfer":
        scores[1] += 0.4
        scores[2] += 0.4

    if n_comorbidities >= 5:
        scores[1] += 0.8
        scores[2] += 0.4
        scores[4] -= 0.5
    elif n_comorbidities >= 3:
        scores[1] += 0.3
        scores[2] += 0.4
        scores[4] -= 0.3
    elif n_comorbidities >= 1:
        scores[2] += 0.2

    if flags["hypotension"] and flags["tachycardia"]:
        scores[0] += 1.5
        scores[1] += 1.0

    if flags["severe_hypoxia"]:
        scores[0] += 2.0
        scores[1] += 1.0

    if flags["altered_mental"]:
        scores[0] += 1.0
        scores[1] += 1.5

    if flags["fever"] and flags["tachycardia"] and flags["hypotension"]:
        scores[0] += 1.5  # septic shock pattern

    if flags["shock_index_elevated"]:
        scores[0] += 0.5
        scores[1] += 0.8

    probs = _softmax(scores)
    predicted_level = probs.index(max(probs)) + 1
    return predicted_level, probs


def _generate_risk_factors(
    flags: dict[str, bool],
    composites: dict[str, float],
    complaint_level: int,
    age: int,
    n_comorbidities: int,
    arrival_mode: str,
) -> list[dict[str, object]]:
    """Return top 5 risk factors sorted by importance."""
    factors: list[dict[str, object]] = []

    flag_display = {
        "severe_gcs": ("Severe GCS impairment", 0.98),
        "severe_hypotension": ("Severe hypotension (SBP < 70)", 0.95),
        "severe_hypoxia": ("Severe hypoxia (SpO2 < 88%)", 0.94),
        "severe_tachycardia": ("Severe tachycardia (HR > 130)", 0.88),
        "hypotension": ("Hypotension (SBP < 90)", 0.82),
        "shock_index_elevated": ("Elevated shock index (> 1.0)", 0.80),
        "altered_mental": ("Altered mental status (GCS < 14)", 0.78),
        "hypoxia": ("Hypoxia (SpO2 < 94%)", 0.75),
        "tachycardia": ("Tachycardia (HR > 100)", 0.60),
        "hypertensive": ("Hypertensive crisis (SBP > 180)", 0.65),
        "tachypnea": ("Tachypnea (RR > 22)", 0.55),
        "bradycardia": ("Bradycardia (HR < 50)", 0.58),
        "fever": ("Fever (> 100.4F)", 0.45),
        "hypothermia": ("Hypothermia (< 95.0F)", 0.50),
    }

    for flag_name, (display, importance) in flag_display.items():
        if flags.get(flag_name):
            factors.append({"name": display, "importance": importance})

    if composites["qsofa"] >= 2:
        factors.append({"name": f"qSOFA score {composites['qsofa']}/3", "importance": 0.85})
    if composites["sirs"] >= 2:
        factors.append({"name": f"SIRS criteria met ({composites['sirs']}/3)", "importance": 0.70})
    if complaint_level <= 2:
        factors.append({"name": "High-acuity chief complaint", "importance": 0.75})
    if age >= 75:
        factors.append({"name": "Advanced age (>= 75)", "importance": 0.40})
    elif age >= 65:
        factors.append({"name": "Elderly patient (>= 65)", "importance": 0.30})
    if n_comorbidities >= 5:
        factors.append({"name": f"High comorbidity burden ({n_comorbidities})", "importance": 0.55})
    elif n_comorbidities >= 3:
        factors.append({"name": f"Multiple comorbidities ({n_comorbidities})", "importance": 0.35})
    if arrival_mode == "Ambulance":
        factors.append({"name": "Ambulance arrival", "importance": 0.30})

    factors.sort(key=lambda f: f["importance"], reverse=True)
    return factors[:5]


def _generate_clinical_flags(flags: dict[str, bool]) -> list[str]:
    flag_labels = {
        "hypotension": "hypotension",
        "severe_hypotension": "severe hypotension",
        "hypertensive": "hypertensive crisis",
        "tachycardia": "tachycardia",
        "severe_tachycardia": "severe tachycardia",
        "bradycardia": "bradycardia",
        "hypoxia": "hypoxia",
        "severe_hypoxia": "severe hypoxia",
        "tachypnea": "tachypnea",
        "fever": "fever",
        "hypothermia": "hypothermia",
        "severe_gcs": "severe GCS impairment",
        "altered_mental": "altered mental status",
        "shock_index_elevated": "elevated shock index",
    }
    return [label for key, label in flag_labels.items() if flags.get(key)]


def _generate_conformal_set(predicted: int, confidence: float) -> tuple[list[int], float]:
    if confidence > 0.85:
        conformal = [predicted]
    elif confidence >= 0.65:
        candidates = {predicted}
        if predicted > 1:
            candidates.add(predicted - 1)
        if predicted < 5:
            candidates.add(predicted + 1)
        conformal = sorted(candidates)
    else:
        candidates: set[int] = set()
        for offset in [-1, 0, 1]:
            lvl = predicted + offset
            if 1 <= lvl <= 5:
                candidates.add(lvl)
        conformal = sorted(candidates)
    return conformal, 0.90


def _generate_recommendation(
    esi_level: int,
    flags: dict[str, bool],
    composites: dict[str, float],
    chief_complaint: str,
) -> str:
    base_recs = {
        1: "Immediate life-saving intervention required. Activate trauma/resuscitation team.",
        2: "High-acuity presentation requiring immediate evaluation.",
        3: "Urgent evaluation recommended. Multiple resources likely needed. Monitor vitals q15min.",
        4: "Semi-urgent. Single resource expected. Standard workup per chief complaint.",
        5: "Non-urgent presentation. May be suitable for fast-track or urgent care referral.",
    }
    rec = base_recs[esi_level]
    addenda: list[str] = []

    if composites["qsofa"] >= 2:
        addenda.append("Consider sepsis workup -- qSOFA score elevated.")
    if composites["sirs"] >= 2 and flags.get("fever"):
        addenda.append("SIRS criteria met with fever -- obtain blood cultures and lactate.")
    if flags.get("shock_index_elevated") and flags.get("hypotension"):
        addenda.append("Hemodynamic instability present -- prepare for fluid resuscitation.")
    if flags.get("severe_hypoxia"):
        addenda.append("Severe hypoxia -- prepare supplemental O2 and consider intubation.")
    if flags.get("hypertensive") and esi_level <= 2:
        addenda.append("Hypertensive emergency -- obtain end-organ damage workup.")

    c = chief_complaint.lower()
    if esi_level == 2:
        if "chest pain" in c:
            addenda.append("Obtain 12-lead ECG and troponin within 10 minutes.")
        elif "stroke" in c:
            addenda.append("Activate stroke alert -- obtain CT head stat.")
        elif "overdose" in c:
            addenda.append("Contact Poison Control. Monitor airway and mental status closely.")
        elif "difficulty breathing" in c or "shortness of breath" in c:
            addenda.append("Obtain chest X-ray, ABG, and assess for intubation readiness.")

    if addenda:
        rec = rec + " " + " ".join(addenda)
    return rec


def predict_triage(patient: dict) -> dict:
    """Takes patient dict; returns prediction dict matching the Triage.ai response schema."""
    heart_rate = float(patient["heart_rate"])
    sbp = float(patient["sbp"])
    dbp = float(patient["dbp"])
    o2_sat = float(patient["o2_sat"])
    resp_rate = float(patient["resp_rate"])
    temperature = float(patient["temperature"])
    gcs = int(patient["gcs"])
    age = int(patient["age"])
    chief_complaint = patient["chief_complaint"]
    arrival_mode = patient["arrival_mode"]
    n_comorbidities = int(patient["n_comorbidities"])

    flags = _compute_vital_flags(heart_rate, sbp, dbp, o2_sat, resp_rate, temperature, gcs)
    composites = _compute_composites(heart_rate, sbp, resp_rate, temperature, gcs, flags)
    complaint_level, complaint_conf = _parse_chief_complaint(chief_complaint)

    esi_level, probabilities = _compute_esi_scores(
        complaint_level, complaint_conf, flags, composites,
        age, arrival_mode, n_comorbidities, gcs,
    )

    confidence = max(probabilities)
    probabilities_rounded = [round(p, 4) for p in probabilities]

    risk_factors = _generate_risk_factors(
        flags, composites, complaint_level, age, n_comorbidities, arrival_mode,
    )
    clinical_flags = _generate_clinical_flags(flags)
    conformal_set, coverage_level = _generate_conformal_set(esi_level, confidence)
    recommendation = _generate_recommendation(esi_level, flags, composites, chief_complaint)

    return {
        "esi_level": esi_level,
        "esi_label": ESI_LABELS[esi_level],
        "confidence": round(confidence, 4),
        "probabilities": probabilities_rounded,
        "conformal_set": conformal_set,
        "coverage_level": coverage_level,
        "risk_factors": risk_factors,
        "clinical_flags": clinical_flags,
        "composites": composites,
        "recommendation": recommendation,
    }
