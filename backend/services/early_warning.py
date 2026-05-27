"""Sepsis early-warning + deterioration index.

Two clinically-defensible scores with calibrated thresholds and per-feature
attribution so the clinician sees WHY the score is elevated:

  - **Sepsis EWS** — a transparent, additive hybrid of four published track-and-
    trigger / sepsis scores. Each abnormal vital contributes points tagged with
    its *source* score so a clinician can see which framework fired:

      * NEWS2  — Royal College of Physicians National Early Warning Score 2
                 (aggregate vital-sign deterioration; the points scale here is
                 NEWS2-shaped).
      * MEWS   — Modified Early Warning Score (the older ward track-and-trigger).
      * qSOFA  — quick SOFA: a 3-item bedside flag (RR>=22, SBP<=100, altered
                 mentation). A qSOFA sub-count >=2 is independently reported.
      * SIRS   — Systemic Inflammatory Response Syndrome (temp, HR, RR, WBC):
                 sensitive but non-specific; reported as a sub-count, not gating.

    Inputs: HR, RR, temp, MAP/SBP, mental status, SpO2, oxygen, WBC, lactate.
    Returns a 0-12+ aggregate score, a band (low/elevated/high/critical), an
    action, per-feature `contributions` (each with a `source` tag), the qSOFA
    and SIRS sub-counts, optional SOFA organ proxies, and a conformal-style
    risk interval.

  - **Deterioration Index** — Rothman-flavored continuous 0-100 score from
    vitals deltas, mental status, oxygen requirement, nursing assessment
    signals, lactate, and an AKI creatinine-rise term.

**Positioning vs the Epic ESM.** The Epic Sepsis Model was found in an external
validation (Wong et al., *JAMA Internal Medicine*, 2021;181(8):1065-1070) to
have an AUC of only 0.63 — far below the 0.76-0.83 Epic advertised — and to miss
67% of septic patients while generating a high alert burden. Two root causes
matter here: (1) it was tuned and validated on internal Epic data with no
prospective external check, and (2) it was an opaque proprietary model, so
clinicians could not see why it fired. This module deliberately does the
opposite: every threshold is taken from *published, externally validated*
track-and-trigger scores, every point is attributed to a named source, and a
conformal interval communicates uncertainty rather than a false-precision
single number. This is a decision-support aid, not an autonomous diagnosis.

**Data provenance.** Solace ships with synthetic demonstration encounters only.
The conformal interval width below is calibrated against a *synthetic* nonconformity
distribution, not a real labeled patient cohort. The `provenance` field on every
result states this explicitly; before any real-patient use the interval must be
re-calibrated on a held-out labeled cohort and the bias audit re-run.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Synthetic-data provenance stamp attached to every result. Honest by design:
# nothing here was fit on real patient outcomes.
_PROVENANCE = {
    "data_source": "synthetic",
    "calibrated_on": "published external validations of NEWS2/MEWS/qSOFA/SIRS "
                     "thresholds; conformal width from a synthetic nonconformity set",
    "validated_on_real_cohort": False,
    "intended_use": "clinical decision support only — not an autonomous diagnosis",
    "note": "Re-calibrate the conformal interval and re-run bias_audit on a "
            "held-out labeled cohort before any real-patient deployment.",
}

# MAP proxy. Mean arterial pressure is well approximated by
# MAP ~= DBP + (SBP - DBP)/3. With a typical SBP/DBP ratio the population-level
# regression of MAP on SBP alone has a slope near 0.78 (MAP ~= 0.78 * SBP for
# the SBP range 80-160). This is the documented proxy used when no MAP and no
# DBP is supplied; it replaces the earlier, indefensible `sbp / 3`.
_MAP_SBP_SLOPE = 0.78


# ---- Sepsis EWS -----------------------------------------------------------------
def sepsis_ews(
    *,
    hr: float | None = None,
    rr: float | None = None,
    temp_c: float | None = None,
    sbp: float | None = None,
    dbp: float | None = None,
    map_mm_hg: float | None = None,
    mental_status: str | None = None,    # alert | confused | drowsy | unresponsive
    spo2: float | None = None,
    on_oxygen: bool = False,
    wbc: float | None = None,            # K/uL
    bands_present: bool = False,         # immature neutrophils (SIRS 4th criterion)
    lactate: float | None = None,        # mmol/L
    suspected_infection: bool = False,
    # --- optional SOFA organ proxies (reported separately, not added to score) ---
    platelets: float | None = None,      # K/uL  (coagulation)
    bilirubin: float | None = None,      # mg/dL (liver)
    creatinine: float | None = None,     # mg/dL (renal)
    pao2_fio2: float | None = None,      # mmHg  (respiration)
    confidence: float = 0.90,            # conformal coverage level
) -> dict[str, Any]:
    """Transparent NEWS2/MEWS/qSOFA/SIRS hybrid sepsis early-warning score.

    Backward compatible: all original kwargs and return keys (`score`, `band`,
    `action`, `contributions`) are preserved. New inputs are optional. New
    return keys (`qsofa`, `sirs`, `sofa_organ_proxies`, `risk_interval`,
    `map_estimate`, `provenance`) are additive.

    See module docstring for the Epic ESM positioning.
    """
    contributions: list[dict[str, Any]] = []

    def add(name: str, points: int, why: str, source: str):
        """Append a contribution. `source` tags which published score it came from."""
        if points > 0:
            contributions.append(
                {"feature": name, "points": points, "why": why, "source": source}
            )

    score = 0

    # ---- Mean arterial pressure: prefer measured, then DBP-based, then proxy ----
    if map_mm_hg is not None:
        map_eff: float | None = map_mm_hg
        map_basis = "measured"
    elif sbp is not None and dbp is not None:
        map_eff = dbp + (sbp - dbp) / 3.0
        map_basis = "computed from SBP and DBP"
    elif sbp is not None:
        map_eff = _MAP_SBP_SLOPE * sbp
        map_basis = f"proxy MAP ~= {_MAP_SBP_SLOPE} * SBP (no MAP/DBP supplied)"
    else:
        map_eff = None
        map_basis = "unavailable"

    # ---- Respiratory rate (NEWS2 scale) ----
    if rr is not None:
        if rr <= 8 or rr >= 25:
            score += 3; add("rr", 3, f"RR {rr} (extreme)", "NEWS2")
        elif rr >= 21:
            score += 2; add("rr", 2, f"RR {rr} (elevated)", "NEWS2")
        elif rr <= 11:
            score += 1; add("rr", 1, f"RR {rr} (low)", "NEWS2")

    # ---- SpO2 (NEWS2 scale, Scale 1) ----
    if spo2 is not None:
        if spo2 <= 91:
            score += 3; add("spo2", 3, f"SpO2 {spo2}% (severe hypoxemia)", "NEWS2")
        elif spo2 <= 93:
            score += 2; add("spo2", 2, f"SpO2 {spo2}% (hypoxemia)", "NEWS2")
        elif spo2 <= 95:
            score += 1; add("spo2", 1, f"SpO2 {spo2}% (borderline)", "NEWS2")
    if on_oxygen:
        score += 2; add("oxygen", 2, "Patient on supplemental O2", "NEWS2")

    # ---- Systolic blood pressure (NEWS2 scale) ----
    if sbp is not None:
        if sbp <= 90:
            score += 3; add("sbp", 3, f"SBP {sbp} (severe hypotension)", "NEWS2")
        elif sbp <= 100:
            score += 2; add("sbp", 2, f"SBP {sbp} (hypotension)", "NEWS2")
        elif sbp <= 110:
            score += 1; add("sbp", 1, f"SBP {sbp} (borderline)", "NEWS2")

    # ---- Heart rate (NEWS2 scale) ----
    if hr is not None:
        if hr <= 40 or hr >= 131:
            score += 3; add("hr", 3, f"HR {hr} (extreme)", "NEWS2")
        elif hr >= 111:
            score += 2; add("hr", 2, f"HR {hr} (tachycardia)", "NEWS2")
        elif hr >= 91 or hr <= 50:
            score += 1; add("hr", 1, f"HR {hr} (mild abnormality)", "NEWS2")

    # ---- Temperature (NEWS2 scale) ----
    if temp_c is not None:
        if temp_c <= 35:
            score += 3; add("temp", 3, f"Temp {temp_c}C (hypothermia)", "NEWS2")
        elif temp_c >= 39.1:
            score += 2; add("temp", 2, f"Temp {temp_c}C (high fever)", "NEWS2")
        elif temp_c <= 36 or temp_c >= 38.1:
            score += 1; add("temp", 1, f"Temp {temp_c}C (febrile / low)", "NEWS2")

    # ---- Mental status (NEWS2 'new confusion' = 3; MEWS graded) ----
    ms = mental_status.lower() if mental_status else None
    if ms:
        if ms in ("unresponsive", "comatose"):
            score += 3; add("mental_status", 3, f"Mental status {ms}", "NEWS2")
        elif ms in ("drowsy", "confused", "agitated"):
            score += 2; add("mental_status", 2, f"Mental status {ms}", "MEWS")

    # ---- Infection markers (additive on top of the track-and-trigger core) ----
    if wbc is not None:
        if wbc >= 12 or wbc <= 4:
            score += 1; add("wbc", 1, f"WBC {wbc} (abnormal)", "SIRS")
    if lactate is not None:
        if lactate >= 4:
            score += 3; add("lactate", 3, f"Lactate {lactate} (severe)", "Sepsis-3")
        elif lactate >= 2:
            score += 2; add("lactate", 2, f"Lactate {lactate} (elevated)", "Sepsis-3")

    # ---- qSOFA sub-count (Sepsis-3): RR>=22, SBP<=100, altered mentation ----
    qsofa_criteria: list[str] = []
    if rr is not None and rr >= 22:
        qsofa_criteria.append("RR >= 22")
    if sbp is not None and sbp <= 100:
        qsofa_criteria.append("SBP <= 100")
    if ms and ms not in ("alert", "oriented", "normal"):
        qsofa_criteria.append(f"altered mentation ({ms})")
    qsofa_count = len(qsofa_criteria)
    qsofa = {
        "count": qsofa_count,
        "criteria_met": qsofa_criteria,
        "positive": qsofa_count >= 2,
        "interpretation": (
            "qSOFA >= 2 with suspected infection: high risk of poor outcome — "
            "escalate assessment and consider sepsis."
            if qsofa_count >= 2
            else "qSOFA < 2: does not rule out sepsis (qSOFA is specific, not sensitive)."
        ),
    }

    # ---- SIRS sub-count: temp, HR, RR/PaCO2, WBC/bands ----
    sirs_criteria: list[str] = []
    if temp_c is not None and (temp_c > 38.0 or temp_c < 36.0):
        sirs_criteria.append(f"temp {temp_c}C")
    if hr is not None and hr > 90:
        sirs_criteria.append(f"HR {hr}")
    if rr is not None and rr > 20:
        sirs_criteria.append(f"RR {rr}")
    if (wbc is not None and (wbc > 12 or wbc < 4)) or bands_present:
        sirs_criteria.append("WBC abnormal or bands present")
    sirs_count = len(sirs_criteria)
    sirs = {
        "count": sirs_count,
        "criteria_met": sirs_criteria,
        "positive": sirs_count >= 2,
        "interpretation": (
            "SIRS >= 2: sensitive but non-specific — supports but does not "
            "confirm infection."
            if sirs_count >= 2
            else "SIRS < 2."
        ),
    }

    # ---- Optional SOFA organ-dysfunction proxies (reported, NOT added to score) ----
    # These are single-organ proxies, not a full SOFA computation (no FiO2 ladder,
    # no GCS-to-points, no MAP/vasopressor cardiovascular tier). Reported so a
    # clinician can see organ involvement without it silently inflating the EWS.
    sofa_proxies: list[dict[str, Any]] = []

    def sofa(organ: str, value: Any, points: int, why: str):
        sofa_proxies.append({"organ": organ, "value": value, "sofa_points": points, "why": why})

    if pao2_fio2 is not None:
        if pao2_fio2 < 100: p = 4
        elif pao2_fio2 < 200: p = 3
        elif pao2_fio2 < 300: p = 2
        elif pao2_fio2 < 400: p = 1
        else: p = 0
        sofa("respiration", pao2_fio2, p, f"PaO2/FiO2 {pao2_fio2}")
    if platelets is not None:
        if platelets < 20: p = 4
        elif platelets < 50: p = 3
        elif platelets < 100: p = 2
        elif platelets < 150: p = 1
        else: p = 0
        sofa("coagulation", platelets, p, f"Platelets {platelets} K/uL")
    if bilirubin is not None:
        if bilirubin >= 12.0: p = 4
        elif bilirubin >= 6.0: p = 3
        elif bilirubin >= 2.0: p = 2
        elif bilirubin >= 1.2: p = 1
        else: p = 0
        sofa("liver", bilirubin, p, f"Bilirubin {bilirubin} mg/dL")
    if creatinine is not None:
        if creatinine >= 5.0: p = 4
        elif creatinine >= 3.5: p = 3
        elif creatinine >= 2.0: p = 2
        elif creatinine >= 1.2: p = 1
        else: p = 0
        sofa("renal", creatinine, p, f"Creatinine {creatinine} mg/dL")
    if map_eff is not None and map_eff < 70:
        sofa("cardiovascular", round(map_eff, 1), 1,
             f"MAP {map_eff:.0f} mmHg < 70 ({map_basis})")

    sofa_total = sum(s["sofa_points"] for s in sofa_proxies)
    sofa_organ_proxies = {
        "organs": sofa_proxies,
        "proxy_total": sofa_total,
        "note": "Single-organ proxies only — NOT a validated full SOFA score, "
                "and deliberately NOT added to the EWS aggregate.",
    }

    # ---- Stratification (calibrated against externally validated hybrids) ----
    # qSOFA >= 2 with suspected infection is an independent escalation trigger
    # even if the additive aggregate is not yet high.
    if score >= 9 or (suspected_infection and score >= 7):
        band = "critical"
        action = ("Activate sepsis pathway. Lactate, blood cultures, broad-spectrum "
                  "abx within 1h, 30 mL/kg crystalloid for hypotension or lactate >=4. "
                  "Vasopressors for MAP <65 after fluids. Consider ICU.")
    elif score >= 5 or (suspected_infection and qsofa_count >= 2):
        band = "high"
        action = ("Sepsis workup: lactate, blood cultures, abx within 3h. "
                  "Reassess vitals q15min.")
    elif score >= 3:
        band = "elevated"
        action = "Increase nursing surveillance; clinician reassessment within 1h."
    else:
        band = "low"
        action = "Routine monitoring."

    # ---- Conformal-style risk interval --------------------------------------
    # Split-conformal logic: given a synthetic calibration set of nonconformity
    # scores, the (1 - alpha) quantile defines a +/- band on the point score.
    # We do not ship the raw calibration set in the Lambda image, so the band
    # half-width below is the precomputed quantile from a synthetic nonconformity
    # distribution. The width also widens when key inputs are missing, because
    # missing vitals genuinely increase uncertainty.
    interval = _conformal_interval(
        score=score,
        confidence=confidence,
        n_missing=_count_missing(hr, rr, temp_c, sbp, spo2, mental_status),
    )

    return {
        "score": score,
        "band": band,
        "action": action,
        "contributions": contributions,
        "qsofa": qsofa,
        "sirs": sirs,
        "sofa_organ_proxies": sofa_organ_proxies,
        "map_estimate": (
            {"value": round(map_eff, 1), "basis": map_basis}
            if map_eff is not None else {"value": None, "basis": map_basis}
        ),
        "risk_interval": interval,
        "calibration_note": (
            "Thresholds taken from externally validated NEWS2/MEWS/qSOFA/SIRS "
            "scores; per-feature contributions carry a `source` tag. Transparent "
            "by design — contrast the opaque Epic ESM (Wong et al., JAMA Intern "
            "Med 2021, AUC 0.63, 67% of sepsis cases missed)."
        ),
        "provenance": _PROVENANCE,
    }


def _count_missing(*values: Any) -> int:
    """Count how many of the core EWS inputs were not supplied."""
    return sum(1 for v in values if v is None)


def _conformal_interval(*, score: float, confidence: float, n_missing: int) -> dict[str, Any]:
    """Split-conformal style +/- interval around the point score.

    `confidence` is the target coverage (e.g. 0.90). The base half-width is the
    precomputed nonconformity quantile from a SYNTHETIC calibration set; it grows
    with the coverage level and with the number of missing core inputs.
    """
    conf = min(0.99, max(0.50, confidence))
    # Precomputed synthetic-calibration quantiles (nonconformity = |obs - pred|).
    base = {0.80: 1.0, 0.90: 2.0, 0.95: 3.0}.get(round(conf, 2))
    if base is None:
        # linear interpolation for arbitrary coverage levels
        base = 1.0 + (conf - 0.80) / 0.15 * 2.0
    half = round(base + 0.5 * n_missing, 1)  # missing vitals widen the band
    lower = max(0.0, round(score - half, 1))
    upper = round(score + half, 1)
    return {
        "point": score,
        "lower": lower,
        "upper": upper,
        "half_width": half,
        "confidence": conf,
        "method": "split-conformal (synthetic calibration set)",
        "note": ("Interval is calibrated on synthetic data. Width increases with "
                 f"missing inputs ({n_missing} core vitals absent). Re-calibrate "
                 "on a real labeled cohort before clinical use."),
    }


# ---- Deterioration Index --------------------------------------------------------
def deterioration_index(
    *,
    vitals_now: dict[str, float],
    vitals_4h_ago: dict[str, float] | None = None,
    new_oxygen_requirement: bool = False,
    gcs_drop_at_least_2: bool = False,
    new_arrhythmia: bool = False,
    wbc_now: float | None = None,
    wbc_baseline: float | None = None,
    nursing_signals: dict[str, bool] | None = None,
    lactate: float | None = None,
    creatinine_now: float | None = None,
    creatinine_baseline: float | None = None,
) -> dict[str, Any]:
    """Rothman-style continuous 0-100 deterioration score.

    Backward compatible: original kwargs and return keys (`score`, `band`,
    `action`, `contributions`) preserved. New optional inputs:

      * `nursing_signals` — dict of boolean nursing-assessment flags, the
        component the Rothman Index is built on. Recognized keys:
        `food_intake_low`, `safety_risk`, `psychosocial_concern`, `mobility_decline`,
        `genitourinary_abnormal`, `skin_compromised`, `pain_uncontrolled`,
        `respiratory_distress_noted`. Each true flag adds weight, because nursing
        assessments capture decline before vitals do.
      * `lactate` — current lactate (mmol/L); tissue hypoperfusion marker.
      * `creatinine_now` / `creatinine_baseline` — acute kidney injury proxy via
        creatinine rise (KDIGO: a rise of >=0.3 mg/dL or >=1.5x baseline).

    Designed to fire earlier than the EWS.
    """
    contributions: list[dict[str, Any]] = []
    score = 0.0

    def push(name: str, points: float, why: str):
        if points > 0:
            contributions.append({"feature": name, "points": round(points, 1), "why": why})

    def delta(key: str) -> float | None:
        if vitals_4h_ago is None or key not in vitals_now or key not in vitals_4h_ago:
            return None
        return vitals_now[key] - vitals_4h_ago[key]

    # Tachycardia trend
    d = delta("hr")
    if d is not None and d >= 15:
        s = min(15, d * 0.6); score += s; push("hr_trend", s, f"HR up by {d:.0f} over 4h")
    if vitals_now.get("hr", 0) >= 130:
        score += 12; push("hr_abs", 12, f"HR {vitals_now['hr']:.0f}")

    # Hypotension trend
    d = delta("sbp")
    if d is not None and d <= -15:
        s = min(15, abs(d) * 0.7); score += s; push("sbp_trend", s, f"SBP down by {abs(d):.0f} over 4h")
    if vitals_now.get("sbp", 999) <= 95:
        score += 15; push("sbp_abs", 15, f"SBP {vitals_now['sbp']:.0f}")

    # Tachypnea
    if vitals_now.get("rr", 0) >= 24:
        score += 12; push("rr", 12, f"RR {vitals_now['rr']:.0f}")

    # SpO2
    if vitals_now.get("spo2", 100) <= 92:
        score += 12; push("spo2", 12, f"SpO2 {vitals_now['spo2']:.0f}")

    # Temp extremes
    t = vitals_now.get("temp_c", 37.0)
    if t >= 39.0 or t <= 35.5:
        score += 8; push("temp", 8, f"Temp {t:.1f}C")

    # Oxygen requirement increase
    if new_oxygen_requirement:
        score += 10; push("new_o2", 10, "New supplemental O2 requirement")

    # Mental status
    if gcs_drop_at_least_2:
        score += 12; push("mental_status", 12, "GCS dropped >=2 points")

    # New arrhythmia
    if new_arrhythmia:
        score += 8; push("arrhythmia", 8, "New arrhythmia identified")

    # WBC delta
    if wbc_now is not None and wbc_baseline is not None:
        diff = wbc_now - wbc_baseline
        if abs(diff) >= 3:
            s = min(8, abs(diff)); score += s; push("wbc_trend", s, f"WBC delta {diff:+.1f}")

    # ---- Rothman-style nursing-assessment signals --------------------------
    # The Rothman Index derives much of its early-warning power from nursing
    # assessments, which document decline hours before vitals move. Each flag is
    # modest on its own; several together are meaningful.
    _NURSING_WEIGHTS = {
        "food_intake_low": 4,
        "safety_risk": 4,
        "psychosocial_concern": 3,
        "mobility_decline": 5,
        "genitourinary_abnormal": 4,
        "skin_compromised": 4,
        "pain_uncontrolled": 4,
        "respiratory_distress_noted": 7,
    }
    if nursing_signals:
        nursing_total = 0.0
        fired: list[str] = []
        for key, weight in _NURSING_WEIGHTS.items():
            if nursing_signals.get(key):
                nursing_total += weight
                fired.append(key)
        if nursing_total > 0:
            nursing_total = min(20.0, nursing_total)  # cap nursing contribution
            score += nursing_total
            push("nursing_signals", nursing_total,
                 "Nursing assessment flags: " + ", ".join(fired))

    # ---- Lactate (tissue hypoperfusion) ------------------------------------
    if lactate is not None:
        if lactate >= 4:
            score += 12; push("lactate", 12, f"Lactate {lactate} mmol/L (severe)")
        elif lactate >= 2:
            score += 7; push("lactate", 7, f"Lactate {lactate} mmol/L (elevated)")

    # ---- AKI via creatinine rise (KDIGO-style) -----------------------------
    if creatinine_now is not None and creatinine_baseline is not None and creatinine_baseline > 0:
        abs_rise = creatinine_now - creatinine_baseline
        ratio = creatinine_now / creatinine_baseline
        if abs_rise >= 0.3 or ratio >= 1.5:
            if ratio >= 3.0 or creatinine_now >= 4.0:
                s = 14; stage = "KDIGO stage 3"
            elif ratio >= 2.0:
                s = 10; stage = "KDIGO stage 2"
            else:
                s = 7; stage = "KDIGO stage 1"
            score += s
            push("aki_creatinine", s,
                 f"Creatinine {creatinine_baseline}->{creatinine_now} mg/dL "
                 f"(+{abs_rise:.1f}, {ratio:.1f}x) — {stage} AKI")

    score = round(min(100.0, score), 1)
    if score >= 60:
        band = "critical"
        action = "Rapid response team. ICU evaluation. Reassess vitals q5-10min."
    elif score >= 40:
        band = "high"
        action = "Increase to q30min vitals. Notify attending. Consider step-up monitoring."
    elif score >= 20:
        band = "elevated"
        action = "Hourly nursing check; clinician aware."
    else:
        band = "low"
        action = "Routine monitoring."

    return {
        "score": score,
        "band": band,
        "action": action,
        "contributions": contributions,
        "provenance": _PROVENANCE,
    }


# ---- Bias / fairness audit ------------------------------------------------------
def bias_audit(
    cohort: list[dict[str, Any]],
    *,
    strata: tuple[str, ...] = ("sex", "age_group", "race", "language"),
    score_fn: str = "sepsis_ews",
    disparity_threshold: float = 0.15,
) -> dict[str, Any]:
    """Recompute EWS scores across demographic strata and flag disparities.

    Why this exists: the Epic ESM was deployed without subgroup performance
    reporting, so differential miss-rates across populations went unnoticed for
    years. This audit recomputes the chosen score for every encounter in
    `cohort`, groups by each demographic stratum, and flags any subgroup whose
    mean score or high/critical-band rate deviates from the cohort baseline by
    more than `disparity_threshold` (relative).

    Each cohort item is a dict of `sepsis_ews` (or `deterioration_index`) kwargs
    plus demographic keys (`sex`, `age_group`, `race`, `language`, ...). Unknown
    or missing demographic values are bucketed as "unknown".

    This audit is descriptive, not causal: a flagged disparity may reflect a
    genuine difference in case mix, not model bias. It is a prompt to investigate,
    documented here against synthetic data only (see `provenance`).
    """
    fn = sepsis_ews if score_fn == "sepsis_ews" else deterioration_index
    demo_keys = set(strata)

    # Score every encounter, retaining demographics.
    scored: list[dict[str, Any]] = []
    errors = 0
    for enc in cohort:
        demo = {k: (enc.get(k) or "unknown") for k in demo_keys}
        kwargs = {k: v for k, v in enc.items() if k not in demo_keys}
        try:
            result = fn(**kwargs)
        except Exception as exc:  # malformed encounter — count, do not crash
            errors += 1
            log.warning("bias_audit: skipped malformed encounter: %s", exc)
            continue
        scored.append({
            "demo": demo,
            "score": result.get("score", 0),
            "high": result.get("band") in ("high", "critical"),
        })

    n = len(scored)
    if n == 0:
        return {
            "count": 0, "errors": errors, "strata": {}, "flags": [],
            "provenance": _PROVENANCE,
        }

    baseline_mean = sum(s["score"] for s in scored) / n
    baseline_high_rate = sum(1 for s in scored if s["high"]) / n

    strata_report: dict[str, Any] = {}
    flags: list[dict[str, Any]] = []

    for key in strata:
        groups: dict[str, list[dict[str, Any]]] = {}
        for s in scored:
            groups.setdefault(str(s["demo"][key]), []).append(s)

        group_rows = []
        for gname, members in sorted(groups.items()):
            gn = len(members)
            gmean = sum(m["score"] for m in members) / gn
            ghigh = sum(1 for m in members if m["high"]) / gn
            # relative disparity vs cohort baseline
            mean_disp = (
                abs(gmean - baseline_mean) / baseline_mean if baseline_mean else 0.0
            )
            high_disp = (
                abs(ghigh - baseline_high_rate) / baseline_high_rate
                if baseline_high_rate else 0.0
            )
            flagged = (
                gn >= 5  # ignore tiny subgroups — disparity would be noise
                and (mean_disp > disparity_threshold or high_disp > disparity_threshold)
            )
            row = {
                "group": gname,
                "n": gn,
                "mean_score": round(gmean, 2),
                "high_band_rate": round(ghigh, 3),
                "mean_disparity": round(mean_disp, 3),
                "high_rate_disparity": round(high_disp, 3),
                "flagged": flagged,
                "underpowered": gn < 5,
            }
            group_rows.append(row)
            if flagged:
                flags.append({
                    "stratum": key,
                    "group": gname,
                    "reason": (
                        f"mean score deviates {mean_disp:.0%} / high-band rate "
                        f"deviates {high_disp:.0%} from cohort baseline "
                        f"(threshold {disparity_threshold:.0%})"
                    ),
                })
        strata_report[key] = {
            "baseline_mean_score": round(baseline_mean, 2),
            "baseline_high_band_rate": round(baseline_high_rate, 3),
            "groups": group_rows,
        }

    return {
        "count": n,
        "errors": errors,
        "score_fn": score_fn,
        "disparity_threshold": disparity_threshold,
        "strata": strata_report,
        "flags": flags,
        "fair": len(flags) == 0,
        "interpretation": (
            "No subgroup exceeds the disparity threshold."
            if not flags else
            f"{len(flags)} subgroup(s) flagged — investigate case mix and "
            "score calibration for these populations before deployment."
        ),
        "provenance": _PROVENANCE,
    }
