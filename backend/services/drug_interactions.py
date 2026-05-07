"""Drug-drug + drug-allergy + renal-dose interaction checker (MVP).

Production target is FDB or Medi-Span; this MVP uses a curated common-pair table
of high-frequency, high-severity interactions plus a small RxNorm-style alias map
so brand names and generics resolve to a canonical key.

Inline gating: callers pass an encounter context with the active complaint so
trivial alerts are filtered (e.g. don't fire SSRI-NSAID GI bleed risk for a
sprained ankle visit). Alert fatigue is the actual clinical risk here.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# Brand -> generic canonical key
_ALIASES: dict[str, str] = {
    "advil": "ibuprofen", "motrin": "ibuprofen", "ibuprofen": "ibuprofen",
    "tylenol": "acetaminophen", "acetaminophen": "acetaminophen", "paracetamol": "acetaminophen",
    "aspirin": "aspirin", "asa": "aspirin", "bayer": "aspirin",
    "warfarin": "warfarin", "coumadin": "warfarin",
    "eliquis": "apixaban", "apixaban": "apixaban",
    "xarelto": "rivaroxaban", "rivaroxaban": "rivaroxaban",
    "pradaxa": "dabigatran", "dabigatran": "dabigatran",
    "lipitor": "atorvastatin", "atorvastatin": "atorvastatin",
    "crestor": "rosuvastatin", "rosuvastatin": "rosuvastatin",
    "simvastatin": "simvastatin", "zocor": "simvastatin",
    "metformin": "metformin", "glucophage": "metformin",
    "lisinopril": "lisinopril", "zestril": "lisinopril", "prinivil": "lisinopril",
    "losartan": "losartan", "cozaar": "losartan",
    "metoprolol": "metoprolol", "lopressor": "metoprolol", "toprol": "metoprolol",
    "amlodipine": "amlodipine", "norvasc": "amlodipine",
    "hctz": "hydrochlorothiazide", "hydrochlorothiazide": "hydrochlorothiazide",
    "furosemide": "furosemide", "lasix": "furosemide",
    "spironolactone": "spironolactone", "aldactone": "spironolactone",
    "sertraline": "sertraline", "zoloft": "sertraline",
    "fluoxetine": "fluoxetine", "prozac": "fluoxetine",
    "citalopram": "citalopram", "celexa": "citalopram",
    "escitalopram": "escitalopram", "lexapro": "escitalopram",
    "trazodone": "trazodone",
    "tramadol": "tramadol", "ultram": "tramadol",
    "oxycodone": "oxycodone", "percocet": "oxycodone",
    "hydrocodone": "hydrocodone", "vicodin": "hydrocodone", "norco": "hydrocodone",
    "morphine": "morphine",
    "alprazolam": "alprazolam", "xanax": "alprazolam",
    "lorazepam": "lorazepam", "ativan": "lorazepam",
    "clonazepam": "clonazepam", "klonopin": "clonazepam",
    "diphenhydramine": "diphenhydramine", "benadryl": "diphenhydramine",
    "ondansetron": "ondansetron", "zofran": "ondansetron",
    "azithromycin": "azithromycin", "z-pak": "azithromycin",
    "ciprofloxacin": "ciprofloxacin", "cipro": "ciprofloxacin",
    "levofloxacin": "levofloxacin", "levaquin": "levofloxacin",
    "amiodarone": "amiodarone",
    "digoxin": "digoxin", "lanoxin": "digoxin",
    "potassium": "potassium chloride",
    "sildenafil": "sildenafil", "viagra": "sildenafil",
    "tadalafil": "tadalafil", "cialis": "tadalafil",
    "nitroglycerin": "nitroglycerin", "ntg": "nitroglycerin",
}


# (drug_a, drug_b, severity, reason)
_PAIRS: list[tuple[str, str, str, str]] = [
    ("warfarin", "aspirin", "high", "Increased bleeding risk; INR variability"),
    ("warfarin", "ibuprofen", "high", "GI bleeding + INR elevation"),
    ("warfarin", "ciprofloxacin", "high", "Major INR elevation via CYP inhibition"),
    ("warfarin", "azithromycin", "moderate", "INR elevation reported"),
    ("warfarin", "amiodarone", "high", "Marked INR rise; reduce warfarin ~50%"),
    ("apixaban", "aspirin", "moderate", "Additive bleeding risk"),
    ("apixaban", "ibuprofen", "moderate", "Additive bleeding risk"),
    ("rivaroxaban", "aspirin", "moderate", "Additive bleeding risk"),
    ("rivaroxaban", "ketoconazole", "high", "P-gp + CYP3A4 inhibition raises rivaroxaban levels"),
    ("dabigatran", "ketoconazole", "high", "P-gp inhibition raises dabigatran"),
    ("sildenafil", "nitroglycerin", "high", "Severe hypotension — CONTRAINDICATED"),
    ("tadalafil", "nitroglycerin", "high", "Severe hypotension — CONTRAINDICATED"),
    ("metformin", "iv contrast", "moderate", "Hold metformin 48h around contrast in CKD"),
    ("simvastatin", "amiodarone", "high", "Myopathy risk; max simva 20 mg"),
    ("simvastatin", "clarithromycin", "high", "Severe myopathy/rhabdo risk"),
    ("atorvastatin", "clarithromycin", "moderate", "Increased statin levels"),
    ("ssri", "tramadol", "moderate", "Serotonin syndrome risk"),
    ("sertraline", "tramadol", "moderate", "Serotonin syndrome risk"),
    ("fluoxetine", "tramadol", "moderate", "Serotonin syndrome risk"),
    ("citalopram", "tramadol", "moderate", "Serotonin syndrome risk"),
    ("escitalopram", "tramadol", "moderate", "Serotonin syndrome risk"),
    ("ssri", "nsaid", "moderate", "GI bleed risk"),
    ("sertraline", "ibuprofen", "moderate", "GI bleed risk"),
    ("fluoxetine", "ibuprofen", "moderate", "GI bleed risk"),
    ("citalopram", "azithromycin", "moderate", "QT prolongation"),
    ("escitalopram", "azithromycin", "moderate", "QT prolongation"),
    ("amiodarone", "azithromycin", "high", "Major QT prolongation; arrhythmia risk"),
    ("digoxin", "amiodarone", "high", "Digoxin toxicity; halve digoxin dose"),
    ("digoxin", "spironolactone", "moderate", "Digoxin toxicity risk"),
    ("digoxin", "furosemide", "moderate", "Hypokalemia potentiates digoxin toxicity"),
    ("lisinopril", "spironolactone", "moderate", "Hyperkalemia risk"),
    ("lisinopril", "potassium chloride", "moderate", "Hyperkalemia risk"),
    ("lisinopril", "ibuprofen", "moderate", "Reduced antihypertensive effect; AKI risk"),
    ("losartan", "spironolactone", "moderate", "Hyperkalemia risk"),
    ("losartan", "potassium chloride", "moderate", "Hyperkalemia risk"),
    ("benzodiazepine", "opioid", "high", "Respiratory depression — black box warning"),
    ("alprazolam", "oxycodone", "high", "Respiratory depression"),
    ("lorazepam", "morphine", "high", "Respiratory depression"),
    ("clonazepam", "hydrocodone", "high", "Respiratory depression"),
    ("ondansetron", "amiodarone", "moderate", "QT prolongation"),
    ("ondansetron", "citalopram", "moderate", "QT prolongation"),
    ("ondansetron", "azithromycin", "moderate", "QT prolongation"),
]

# Renal dose flags — drugs that need adjustment with eGFR threshold
_RENAL_FLAGS: dict[str, tuple[float, str]] = {
    "metformin": (30, "contraindicated if eGFR <30; reduce dose if 30-45"),
    "apixaban": (15, "use with caution; renal-adjusted dose if SCr >=1.5 + age >=80 + wt <=60kg"),
    "rivaroxaban": (15, "avoid if eGFR <15; reduced dose if 15-49"),
    "dabigatran": (30, "avoid if eGFR <30"),
    "gabapentin": (60, "renal dose adjustment required"),
    "ciprofloxacin": (30, "extend interval if eGFR <30"),
    "vancomycin": (60, "trough-guided dosing"),
}


def _canon(name: str) -> str:
    n = (name or "").strip().lower()
    return _ALIASES.get(n, n)


def check(meds: list[str], allergies: list[str] | None = None, *, egfr: float | None = None, complaint: str = "") -> dict[str, Any]:
    """Return drug-drug, drug-allergy, and renal flags relevant to this encounter."""
    canon_meds = [_canon(m) for m in meds if m]
    canon_allergies = [_canon(a) for a in (allergies or []) if a]

    pair_alerts: list[dict[str, Any]] = []
    for i, a in enumerate(canon_meds):
        for b in canon_meds[i + 1 :]:
            for da, db, sev, reason in _PAIRS:
                if {a, b} == {da, db} or (a == da and b == db) or (a == db and b == da):
                    pair_alerts.append({"a": a, "b": b, "severity": sev, "reason": reason})

    allergy_alerts: list[dict[str, Any]] = []
    for med in canon_meds:
        if med in canon_allergies:
            allergy_alerts.append({"med": med, "reason": f"patient-reported allergy to {med}"})

    renal_alerts: list[dict[str, Any]] = []
    if egfr is not None:
        for med in canon_meds:
            flag = _RENAL_FLAGS.get(med)
            if flag and egfr < flag[0]:
                renal_alerts.append({"med": med, "egfr": egfr, "guidance": flag[1]})

    # Suppress moderate alerts for clearly unrelated trivial visits.
    cc = (complaint or "").lower()
    trivial = any(t in cc for t in ["sprain", "rash", "school note", "physical exam", "wart"])
    if trivial:
        pair_alerts = [a for a in pair_alerts if a["severity"] == "high"]

    return {
        "drug_drug": pair_alerts,
        "drug_allergy": allergy_alerts,
        "renal": renal_alerts,
        "any_high": any(x["severity"] == "high" for x in pair_alerts),
    }
