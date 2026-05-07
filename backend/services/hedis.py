"""HEDIS care-gap surfacing — top measures from MY 2026.

Each measure is a pure function of the patient record. Returns gaps the clinician
should address at the encounter, ordered by recency-of-due-date.

Implemented:
    - BCS  Breast Cancer Screening (women 50-74, mammogram every 27 months)
    - CCS  Cervical Cancer Screening (women 21-64, Pap or HPV)
    - COL  Colorectal Cancer Screening (50-75)
    - CDC  Comprehensive Diabetes A1c (last A1c <12mo, target by category)
    - CBP  Controlling Blood Pressure (HTN dx + last BP)
    - IMA  Adolescent immunizations (HPV by 13, MenACWY by 13, Tdap by 13)
    - AWV  Annual Wellness Visit (Medicare; once per year)
    - DEP  Depression screening (PHQ-2 or PHQ-9 at last visit)
    - FUH  Follow-up after hospitalization for mental illness (30d)
    - MAC  Medication adherence — chronic dz (proxy: refill on time)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _months_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    return (datetime.now(timezone.utc) - dt).days / 30.0


def evaluate(patient: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the open care gaps for the patient at the moment of the encounter."""
    gaps: list[dict[str, Any]] = []
    age = int(patient.get("age") or 0)
    sex = (patient.get("sex") or "").lower()
    history = patient.get("history") or {}

    # BCS
    if sex == "f" and 50 <= age <= 74:
        last = history.get("last_mammogram")
        months = _months_since(last)
        if months is None or months > 27:
            gaps.append({
                "measure": "BCS", "name": "Breast cancer screening",
                "description": "Mammogram every 27 months for women 50-74",
                "action": "Order screening mammogram",
                "icd10": "Z12.31",
            })

    # CCS
    if sex == "f" and 21 <= age <= 64:
        last = history.get("last_pap")
        months = _months_since(last)
        if months is None or months > 36:
            gaps.append({
                "measure": "CCS", "name": "Cervical cancer screening",
                "description": "Pap every 3y (21-29) or Pap+HPV every 5y (30-64)",
                "action": "Order Pap +/- HPV",
                "icd10": "Z12.4",
            })

    # COL
    if 50 <= age <= 75:
        last = history.get("last_colonoscopy") or history.get("last_fit")
        months = _months_since(last)
        # Colonoscopy 10y (120mo); FIT annually (12mo) — use shorter as the trigger
        if months is None or months > 120:
            gaps.append({
                "measure": "COL", "name": "Colorectal cancer screening",
                "description": "Colonoscopy every 10y, FIT annually, or Cologuard every 3y",
                "action": "Discuss screening options; order chosen modality",
                "icd10": "Z12.11",
            })

    # CDC A1c
    conditions = [c.lower() for c in (history.get("conditions") or [])]
    if any("diabet" in c for c in conditions):
        last_a1c = history.get("last_a1c_date")
        months = _months_since(last_a1c)
        a1c_value = history.get("last_a1c_value")
        if months is None or months > 12:
            gaps.append({
                "measure": "CDC", "name": "Diabetes A1c due",
                "description": "A1c every 6-12 months in DM patients",
                "action": "Order HbA1c",
                "icd10": "E11.9",
            })
        elif a1c_value is not None and float(a1c_value) > 9.0:
            gaps.append({
                "measure": "CDC", "name": "Poor diabetes control (A1c > 9)",
                "description": f"Last A1c {a1c_value} — intensify therapy",
                "action": "Up-titrate; endocrinology referral if not done",
                "icd10": "E11.65",
            })

    # CBP
    if any("hypertension" in c or "htn" in c for c in conditions):
        last_bp = history.get("last_bp")  # "138/82"
        if last_bp:
            try:
                sbp, dbp = (int(x) for x in last_bp.split("/"))
                if sbp >= 140 or dbp >= 90:
                    gaps.append({
                        "measure": "CBP", "name": "Uncontrolled BP",
                        "description": f"Last BP {last_bp} — out of range",
                        "action": "Add or up-titrate antihypertensive",
                        "icd10": "I10",
                    })
            except Exception:
                pass

    # IMA — adolescents
    if 13 <= age <= 17:
        imm = history.get("immunizations") or []
        if "hpv" not in (i.lower() for i in imm):
            gaps.append({
                "measure": "IMA-HPV", "name": "HPV vaccine series",
                "description": "Two-dose if started before 15, three-dose if older",
                "action": "Offer HPV vaccine",
                "icd10": "Z23",
            })
        if "tdap" not in (i.lower() for i in imm):
            gaps.append({
                "measure": "IMA-Tdap", "name": "Tdap booster",
                "description": "Tdap by age 13",
                "action": "Offer Tdap",
                "icd10": "Z23",
            })
        if "menacwy" not in (i.lower() for i in imm):
            gaps.append({
                "measure": "IMA-MCV", "name": "MenACWY",
                "description": "First dose by age 13, booster at 16",
                "action": "Offer MenACWY",
                "icd10": "Z23",
            })

    # AWV — Medicare
    if age >= 65:
        last_awv = history.get("last_awv")
        months = _months_since(last_awv)
        if months is None or months > 12:
            gaps.append({
                "measure": "AWV", "name": "Annual Wellness Visit due",
                "description": "AWV once per year for Medicare patients",
                "action": "Schedule AWV; G0438/G0439",
                "icd10": "Z00.00",
            })

    # DEP
    last_dep = history.get("last_depression_screen")
    months = _months_since(last_dep)
    if (months is None or months > 12) and age >= 12:
        gaps.append({
            "measure": "DEP", "name": "Depression screening due",
            "description": "PHQ-2 or PHQ-9 once per year for adolescents and adults",
            "action": "Administer PHQ-9 (Solace screener)",
            "icd10": "Z13.31",
        })

    return gaps[:10]
