"""Specialty packs.

Each pack tunes downstream behavior for a specialty:
  - Section schema for the scribe note
  - Default screeners surfaced at intake
  - Default CDS calculators surfaced at the encounter
  - Ddx priors (which dx categories to over/under-weight)
"""
from __future__ import annotations

from typing import Any


PACKS: dict[str, dict[str, Any]] = {
    "ed": {
        "name": "Emergency Department",
        "scribe_sections": ["CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY", "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN", "DISPOSITION"],
        "default_screeners": ["audit_c"],
        "default_calculators": ["heart", "wells_pe", "perc", "nihss", "qsofa", "news2"],
        "ddx_priors": {
            "weight_more": ["acute coronary syndrome", "pulmonary embolism", "stroke", "sepsis", "appendicitis", "ectopic pregnancy"],
            "weight_less": ["chronic disease management", "preventive care"],
        },
    },
    "primary_care": {
        "name": "Primary Care",
        "scribe_sections": ["CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY", "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN"],
        "default_screeners": ["phq9", "gad7", "audit_c", "prapare"],
        "default_calculators": ["centor", "curb65"],
        "ddx_priors": {
            "weight_more": ["URI", "uncomplicated UTI", "anxiety", "depression", "chronic disease exacerbation"],
            "weight_less": ["acute coronary syndrome", "stroke"],
        },
    },
    "peds": {
        "name": "Pediatrics",
        "scribe_sections": ["CHIEF_COMPLAINT", "HPI", "BIRTH_HISTORY", "DEVELOPMENT", "IMMUNIZATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN", "ANTICIPATORY_GUIDANCE"],
        "default_screeners": ["crafft"],
        "default_calculators": ["centor", "qsofa"],
        "ddx_priors": {
            "weight_more": ["viral URI", "AOM", "bronchiolitis", "asthma exacerbation", "gastroenteritis"],
            "weight_less": ["acute coronary syndrome", "PE"],
        },
    },
    "psych": {
        "name": "Psychiatry / Behavioral Health",
        "scribe_sections": ["CHIEF_COMPLAINT", "HPI", "PAST_PSYCHIATRIC_HISTORY", "MEDICATIONS", "SUBSTANCE_USE", "MENTAL_STATUS_EXAM", "RISK_ASSESSMENT", "ASSESSMENT", "PLAN"],
        "default_screeners": ["phq9", "gad7", "audit_c", "pcl5", "ace", "epds"],
        "default_calculators": [],
        "ddx_priors": {
            "weight_more": ["MDD", "GAD", "PTSD", "bipolar disorder", "substance use disorder"],
            "weight_less": ["acute medical emergencies (route to ED)"],
        },
    },
    "cardiology": {
        "name": "Cardiology",
        "scribe_sections": ["CHIEF_COMPLAINT", "HPI", "CARDIAC_HISTORY", "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "EKG_INTERPRETATION", "ASSESSMENT", "PLAN"],
        "default_screeners": [],
        "default_calculators": ["heart", "wells_pe"],
        "ddx_priors": {"weight_more": ["ACS", "heart failure", "atrial fibrillation", "valvular dz"], "weight_less": []},
    },
    "ortho": {
        "name": "Orthopedics",
        "scribe_sections": ["CHIEF_COMPLAINT", "HPI", "MECHANISM", "PRIOR_INJURIES", "PHYSICAL_EXAM", "IMAGING", "ASSESSMENT", "PLAN"],
        "default_screeners": [],
        "default_calculators": ["wells_dvt"],
        "ddx_priors": {"weight_more": ["fracture", "tendon injury", "joint effusion", "DVT"], "weight_less": []},
    },
}


def list_packs() -> list[dict[str, Any]]:
    return [{"key": k, "name": v["name"]} for k, v in PACKS.items()]


def get_pack(key: str) -> dict[str, Any] | None:
    return PACKS.get(key)
