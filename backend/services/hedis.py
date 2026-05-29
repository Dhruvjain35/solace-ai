"""HEDIS care-gap surfacing — top-10 measures from MY 2026.

Each measure is a pure function of the patient record. `evaluate()` returns the
open care gaps a clinician should address at the encounter; `encounter_sidebar()`
ranks those gaps by clinical + quality impact for the right-rail encounter view.

All look-backs are computed against last-12-months data unless the measure
specification mandates a longer window (BCS 27mo, COL 120mo, CCS 36/60mo).

Implemented (top-10 MY 2026 measures):
    - BCS     Breast Cancer Screening (women 50-74, mammogram every 27 months)
    - CCS     Cervical Cancer Screening (women 21-64, Pap 3y / Pap+HPV 5y)
    - COL     Colorectal Cancer Screening (50-75)
    - CDC-A1c Comprehensive Diabetes A1c (last A1c <12mo; control target <9)
    - CBP     Controlling High Blood Pressure (HTN dx + last BP <140/90)
    - IMA     Immunizations for Adolescents (HPV, Tdap, MenACWY by 13)
    - MAC     Medication Adherence — chronic disease (PDC proxy from refills)
    - AWV     Annual Wellness Visit (Medicare; once per year)
    - DEP     Depression Screening + follow-up (PHQ-2/PHQ-9 annually)
    - FUH     Follow-Up after Hospitalization for mental illness (7d / 30d)

Each gap dict carries a stable contract for downstream consumers:
    measure, name, description, action, icd10   (legacy keys — do not rename)
    last_done                                   (ISO date or None)
    months_since                                (float or None)
    priority                                    ("high" | "medium" | "low")
    impact_score                                (int 0-100, used for ranking)
    domain                                      ("preventive" | "chronic" | "behavioral")
    overdue_by_months                           (float >= 0, or None if never done)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Twelve-month measurement-year look-back used by every non-screening measure.
MEASUREMENT_WINDOW_MONTHS = 12

_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _months_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days / 30.0


def _overdue_by(months: float | None, window: float) -> float | None:
    """Months a measure is past due. None when never done (treated as max-overdue)."""
    if months is None:
        return None
    return max(0.0, months - window)


def _gap(
    *,
    measure: str,
    name: str,
    description: str,
    action: str,
    icd10: str,
    domain: str,
    priority: str,
    impact_score: int,
    last_done: str | None,
    window: float,
) -> dict[str, Any]:
    months = _months_since(last_done)
    return {
        "measure": measure,
        "name": name,
        "description": description,
        "action": action,
        "icd10": icd10,
        "domain": domain,
        "priority": priority,
        "impact_score": impact_score,
        "last_done": last_done,
        "months_since": round(months, 1) if months is not None else None,
        "overdue_by_months": (
            round(_overdue_by(months, window), 1) if months is not None else None
        ),
    }


def evaluate(patient: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the open HEDIS care gaps for the patient at the encounter.

    Pure function. Ordered by priority then overdue magnitude (most overdue,
    never-done gaps first). Backward-compatible: every legacy key is preserved.
    """
    gaps: list[dict[str, Any]] = []
    age = int(patient.get("age") or 0)
    sex = (patient.get("sex") or "").lower()[:1]
    history = patient.get("history") or {}
    conditions = [str(c).lower() for c in (history.get("conditions") or [])]

    def has(*needles: str) -> bool:
        return any(n in c for c in conditions for n in needles)

    # ---- BCS — Breast Cancer Screening -------------------------------------------
    if sex == "f" and 50 <= age <= 74:
        last = history.get("last_mammogram")
        months = _months_since(last)
        if months is None or months > 27:
            gaps.append(_gap(
                measure="BCS", name="Breast cancer screening",
                description="Mammogram every 27 months for women aged 50-74.",
                action="Order screening mammogram",
                icd10="Z12.31", domain="preventive",
                priority="medium", impact_score=62,
                last_done=last, window=27,
            ))

    # ---- CCS — Cervical Cancer Screening -----------------------------------------
    if sex == "f" and 21 <= age <= 64:
        last = history.get("last_pap")
        months = _months_since(last)
        window = 36 if age < 30 else 60
        if months is None or months > window:
            gaps.append(_gap(
                measure="CCS", name="Cervical cancer screening",
                description="Pap every 3y (21-29) or Pap + HPV co-test every 5y (30-64).",
                action="Order Pap +/- HPV co-test",
                icd10="Z12.4", domain="preventive",
                priority="medium", impact_score=58,
                last_done=last, window=window,
            ))

    # ---- COL — Colorectal Cancer Screening ---------------------------------------
    if 45 <= age <= 75:
        last_col = history.get("last_colonoscopy")
        last_fit = history.get("last_fit")
        # Use whichever modality is still current; flag only if both lapsed.
        col_m = _months_since(last_col)
        fit_m = _months_since(last_fit)
        col_ok = col_m is not None and col_m <= 120
        fit_ok = fit_m is not None and fit_m <= 12
        if not (col_ok or fit_ok):
            last = last_col or last_fit
            gaps.append(_gap(
                measure="COL", name="Colorectal cancer screening",
                description="Colonoscopy every 10y, FIT annually, or stool-DNA every 3y.",
                action="Discuss screening options; order chosen modality",
                icd10="Z12.11", domain="preventive",
                priority="medium", impact_score=64,
                last_done=last, window=120,
            ))

    # ---- CDC-A1c — Comprehensive Diabetes A1c ------------------------------------
    if has("diabet"):
        last_a1c = history.get("last_a1c_date")
        months = _months_since(last_a1c)
        a1c_value = history.get("last_a1c_value")
        if months is None or months > MEASUREMENT_WINDOW_MONTHS:
            gaps.append(_gap(
                measure="CDC-A1c", name="Diabetes A1c testing due",
                description="HbA1c at least once in the measurement year for DM patients.",
                action="Order HbA1c",
                icd10="E11.9", domain="chronic",
                priority="high", impact_score=80,
                last_done=last_a1c, window=MEASUREMENT_WINDOW_MONTHS,
            ))
        elif a1c_value is not None:
            try:
                val = float(a1c_value)
            except (TypeError, ValueError):
                val = None
            if val is not None and val > 9.0:
                gaps.append(_gap(
                    measure="CDC-A1c", name="Poor diabetes control (A1c > 9)",
                    description=f"Last A1c {a1c_value} — above the HEDIS poor-control threshold.",
                    action="Intensify therapy; endocrinology referral if not already in place",
                    icd10="E11.65", domain="chronic",
                    priority="high", impact_score=88,
                    last_done=last_a1c, window=MEASUREMENT_WINDOW_MONTHS,
                ))

    # ---- CBP — Controlling High Blood Pressure -----------------------------------
    if has("hypertension", "htn"):
        last_bp = history.get("last_bp")  # e.g. "138/82"
        bp_date = history.get("last_bp_date")
        bp_m = _months_since(bp_date)
        if not last_bp or bp_m is None or bp_m > MEASUREMENT_WINDOW_MONTHS:
            gaps.append(_gap(
                measure="CBP", name="Blood pressure reading due",
                description="A BP reading in the measurement year is required to close CBP.",
                action="Capture an in-office BP this visit",
                icd10="I10", domain="chronic",
                priority="medium", impact_score=66,
                last_done=bp_date, window=MEASUREMENT_WINDOW_MONTHS,
            ))
        else:
            try:
                sbp, dbp = (int(x) for x in str(last_bp).split("/"))
                if sbp >= 140 or dbp >= 90:
                    gaps.append(_gap(
                        measure="CBP", name="Uncontrolled blood pressure",
                        description=f"Last BP {last_bp} — above the <140/90 control target.",
                        action="Add or up-titrate antihypertensive; recheck in 2-4 weeks",
                        icd10="I10", domain="chronic",
                        priority="high", impact_score=78,
                        last_done=bp_date, window=MEASUREMENT_WINDOW_MONTHS,
                    ))
            except (ValueError, AttributeError):
                pass

    # ---- IMA — Immunizations for Adolescents -------------------------------------
    if 13 <= age <= 17:
        imm = [str(i).lower() for i in (history.get("immunizations") or [])]
        last_imm = history.get("last_immunization_date")
        if "hpv" not in imm:
            gaps.append(_gap(
                measure="IMA-HPV", name="HPV vaccine series",
                description="2-dose series if started before 15, otherwise 3-dose.",
                action="Offer HPV vaccine",
                icd10="Z23", domain="preventive",
                priority="medium", impact_score=54,
                last_done=last_imm, window=0,
            ))
        if "tdap" not in imm:
            gaps.append(_gap(
                measure="IMA-Tdap", name="Tdap booster",
                description="One Tdap dose by the 13th birthday.",
                action="Offer Tdap",
                icd10="Z23", domain="preventive",
                priority="medium", impact_score=52,
                last_done=last_imm, window=0,
            ))
        if "menacwy" not in imm:
            gaps.append(_gap(
                measure="IMA-MCV", name="Meningococcal (MenACWY)",
                description="First dose by age 13, booster at 16.",
                action="Offer MenACWY",
                icd10="Z23", domain="preventive",
                priority="medium", impact_score=52,
                last_done=last_imm, window=0,
            ))

    # ---- MAC — Medication Adherence for chronic disease --------------------------
    # PDC proxy: if a chronic Rx exists and the last refill is past the days-supply
    # window, the patient is likely below the 80% proportion-of-days-covered bar.
    if has("diabet", "hypertension", "htn", "hyperlipidemia", "cholesterol", "copd", "asthma"):
        last_refill = history.get("last_med_refill_date")
        days_supply = int(history.get("days_supply") or 30)
        refill_m = _months_since(last_refill)
        grace_months = (days_supply / 30.0) + 0.5  # half-month grace
        if last_refill and refill_m is not None and refill_m > grace_months:
            gaps.append(_gap(
                measure="MAC", name="Medication adherence gap",
                description=(
                    f"Last chronic-medication refill {round(refill_m, 1)} months ago "
                    f"({days_supply}-day supply) — proportion of days covered likely <80%."
                ),
                action="Reconcile meds; address barriers; sync refills / 90-day fill",
                icd10="Z91.14", domain="chronic",
                priority="high", impact_score=74,
                last_done=last_refill, window=grace_months,
            ))

    # ---- AWV — Annual Wellness Visit (Medicare) ----------------------------------
    if age >= 65:
        last_awv = history.get("last_awv")
        months = _months_since(last_awv)
        if months is None or months > MEASUREMENT_WINDOW_MONTHS:
            gaps.append(_gap(
                measure="AWV", name="Annual Wellness Visit due",
                description="One AWV per year for Medicare patients (G0438 initial / G0439 subsequent).",
                action="Schedule AWV; bill G0438 or G0439",
                icd10="Z00.00", domain="preventive",
                priority="medium", impact_score=60,
                last_done=last_awv, window=MEASUREMENT_WINDOW_MONTHS,
            ))

    # ---- DEP — Depression Screening + follow-up ----------------------------------
    if age >= 12:
        last_dep = history.get("last_depression_screen")
        months = _months_since(last_dep)
        if months is None or months > MEASUREMENT_WINDOW_MONTHS:
            gaps.append(_gap(
                measure="DEP", name="Depression screening due",
                description="PHQ-2 or PHQ-9 once per measurement year for adolescents and adults.",
                action="Administer PHQ-9 (Solace screener)",
                icd10="Z13.31", domain="behavioral",
                priority="medium", impact_score=56,
                last_done=last_dep, window=MEASUREMENT_WINDOW_MONTHS,
            ))

    # ---- FUH — Follow-Up after Hospitalization for mental illness ----------------
    # Triggered by a recent acute psychiatric discharge with no follow-up logged.
    psych_dc = history.get("psych_discharge_date")
    if psych_dc:
        dc_m = _months_since(psych_dc)
        followup = history.get("psych_followup_date")
        fu_m = _months_since(followup)
        # FUH closes if a follow-up visit occurred on/after discharge within 30 days.
        followed_up = (
            followup is not None
            and fu_m is not None
            and dc_m is not None
            and fu_m <= dc_m  # follow-up is more recent than discharge
            and (dc_m - fu_m) * 30.0 <= 30.0
        )
        if dc_m is not None and dc_m <= 1.0 and not followed_up:
            within_7d = dc_m * 30.0 <= 7.0
            gaps.append(_gap(
                measure="FUH", name="Follow-up after psychiatric hospitalization",
                description=(
                    "Outpatient behavioral-health follow-up required within 7 and 30 days "
                    "of an acute psychiatric discharge."
                ),
                action=(
                    "Schedule behavioral-health follow-up within 7 days"
                    if within_7d else
                    "Schedule behavioral-health follow-up before the 30-day window closes"
                ),
                icd10="Z51.89", domain="behavioral",
                priority="high", impact_score=90,
                last_done=psych_dc, window=0,
            ))

    return _rank(gaps)


def _rank(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order gaps: priority, then overdue magnitude, then impact. Never-done = most overdue."""
    def key(g: dict[str, Any]) -> tuple[int, float, int]:
        overdue = g.get("overdue_by_months")
        # Never-done (None) sorts ahead of any finite overdue value.
        overdue_rank = float("inf") if overdue is None else overdue
        return (
            _PRIORITY_RANK.get(g.get("priority", "low"), 2),
            -overdue_rank,
            -int(g.get("impact_score") or 0),
        )

    return sorted(gaps, key=key)[:10]


def encounter_sidebar(patient: dict[str, Any], limit: int = 2) -> dict[str, Any]:
    """Top-`limit` care gaps for the encounter sidebar, ranked by impact.

    The sidebar is intentionally short — it surfaces only what the clinician
    should reasonably act on during *this* visit. Ranking favors high clinical
    risk (FUH, poor diabetes control) and then quality-measure impact.

    Returns:
        {
          "patient_age": int,
          "total_open_gaps": int,
          "shown": int,
          "gaps": [ <gap dict>, ... ],          # length <= limit
          "more_gaps": int,                      # gaps not shown
          "headline": str,                       # one-line summary for the rail
        }
    """
    all_gaps = evaluate(patient)
    # encounter ranking: impact_score first, then priority as a tiebreaker.
    ranked = sorted(
        all_gaps,
        key=lambda g: (
            -int(g.get("impact_score") or 0),
            _PRIORITY_RANK.get(g.get("priority", "low"), 2),
        ),
    )
    shown = ranked[: max(0, limit)]
    total = len(all_gaps)

    if total == 0:
        headline = "No open HEDIS gaps — all measures current."
    elif len(shown) == 1 or limit == 1:
        headline = f"{shown[0]['measure']}: {shown[0]['name']}"
    else:
        lead = ", ".join(g["measure"] for g in shown)
        extra = total - len(shown)
        headline = f"{total} open care gap{'s' if total != 1 else ''} — address {lead}"
        if extra > 0:
            headline += f" ({extra} more)"

    return {
        "patient_age": int(patient.get("age") or 0),
        "total_open_gaps": total,
        "shown": len(shown),
        "gaps": shown,
        "more_gaps": max(0, total - len(shown)),
        "headline": headline,
    }
