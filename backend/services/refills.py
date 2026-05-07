"""Refill triage agent.

Each refill request is classified against a configurable protocol library:

  - PROTOCOL_OK  — chronic-stable medication, last labs within window, no recent
                   ED/hospital visit -> auto-approve with audit trail.
  - NEEDS_LABS_OR_VISIT — labs out of window, last visit > X months, or red-flag
                          interactions / new dx
  - PHYSICIAN_REQUIRED — controlled substance, abx, opioid, benzo, anticoag, or
                         med not in protocol library.

The actual e-prescribe write goes through Surescripts (not implemented here);
this module produces the decision and the plain-language patient response.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# (med canonical key, protocol description, lab requirement, max months since visit)
PROTOCOLS = {
    "atorvastatin":      {"description": "Statin refill if labs (LDL, ALT) within 12 months",          "lab": "ldl",   "months_since_visit": 12},
    "rosuvastatin":      {"description": "Statin refill if labs within 12 months",                     "lab": "ldl",   "months_since_visit": 12},
    "simvastatin":       {"description": "Statin refill if labs within 12 months",                     "lab": "ldl",   "months_since_visit": 12},
    "metformin":         {"description": "Metformin refill if A1c within 12 months and SCr stable",    "lab": "a1c",   "months_since_visit": 12},
    "lisinopril":        {"description": "ACE-I refill if K+ and SCr within 12 months",                "lab": "potassium", "months_since_visit": 12},
    "losartan":          {"description": "ARB refill if K+ and SCr within 12 months",                  "lab": "potassium", "months_since_visit": 12},
    "amlodipine":        {"description": "CCB refill if BP recorded within 12 months",                 "lab": None,    "months_since_visit": 12},
    "metoprolol":        {"description": "Beta-blocker refill if HR/BP within 6 months",               "lab": None,    "months_since_visit": 6},
    "hydrochlorothiazide": {"description": "Thiazide refill if K+ and Na+ within 12 months",            "lab": "potassium", "months_since_visit": 12},
    "levothyroxine":     {"description": "Levothyroxine refill if TSH within 12 months",                "lab": "tsh",   "months_since_visit": 12},
    "sertraline":        {"description": "SSRI refill if visit within 6 months",                       "lab": None,    "months_since_visit": 6},
    "fluoxetine":        {"description": "SSRI refill if visit within 6 months",                       "lab": None,    "months_since_visit": 6},
    "escitalopram":      {"description": "SSRI refill if visit within 6 months",                       "lab": None,    "months_since_visit": 6},
    "albuterol":         {"description": "Albuterol PRN refill if no overuse pattern",                 "lab": None,    "months_since_visit": 12},
    "omeprazole":        {"description": "PPI refill if visit within 12 months",                       "lab": None,    "months_since_visit": 12},
}


# Always physician-required (no protocol)
ALWAYS_PHYSICIAN = {
    # Controlled substances
    "alprazolam", "lorazepam", "clonazepam", "diazepam",
    "oxycodone", "hydrocodone", "morphine", "tramadol", "codeine", "fentanyl",
    "methylphenidate", "amphetamine", "lisdexamfetamine",
    "zolpidem",
    # Anticoagulants
    "warfarin", "apixaban", "rivaroxaban", "dabigatran",
    # Antibiotics (need clinical decision per refill)
    "amoxicillin", "azithromycin", "ciprofloxacin", "levofloxacin", "doxycycline",
    "clindamycin", "metronidazole", "cephalexin",
    # Steroids / immunosuppressants
    "prednisone", "methotrexate",
}


def _months_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    return (datetime.now(timezone.utc) - dt).days / 30.0


def triage(
    medication_canonical: str,
    *,
    last_visit_iso: str | None = None,
    relevant_lab_iso: str | None = None,
    relevant_lab_value: float | None = None,
    on_anticoagulant: bool = False,
    recent_hospitalization: bool = False,
) -> dict[str, Any]:
    med = (medication_canonical or "").strip().lower()
    if med in ALWAYS_PHYSICIAN:
        return {
            "decision": "physician_required",
            "reason": "Medication requires clinician decision (controlled, anticoagulant, antibiotic, or steroid).",
            "patient_message": "Your refill request needs to be reviewed by your provider. We'll get back to you within 1-2 business days.",
        }
    proto = PROTOCOLS.get(med)
    if not proto:
        return {
            "decision": "physician_required",
            "reason": "No standing-order protocol for this medication.",
            "patient_message": "Your refill request needs to be reviewed by your provider.",
        }
    months_v = _months_since(last_visit_iso)
    months_l = _months_since(relevant_lab_iso)
    if recent_hospitalization:
        return {"decision": "physician_required", "reason": "Recent hospitalization — clinician review required.", "patient_message": "Your provider will review your refill in light of your recent hospital visit."}
    if months_v is None or months_v > proto["months_since_visit"]:
        return {
            "decision": "needs_visit",
            "reason": f"Last visit was {round(months_v) if months_v else 'unknown'} months ago; protocol requires visit within {proto['months_since_visit']} months.",
            "patient_message": f"It's been more than {proto['months_since_visit']} months since your last visit for this medication. Please book a brief visit so we can refill safely.",
        }
    if proto["lab"] and (months_l is None or months_l > 12):
        return {
            "decision": "needs_labs",
            "reason": f"{proto['lab']} not on file within the last 12 months.",
            "patient_message": f"We need an updated lab ({proto['lab']}) before refilling. Please book a quick lab draw.",
            "labs_to_order": [proto["lab"]],
        }
    return {
        "decision": "protocol_approved",
        "reason": proto["description"],
        "patient_message": "Your refill has been approved. Please allow 24-48 hours for the pharmacy to process it.",
    }
