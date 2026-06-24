"""The metadata catalog — controlled vocabulary + schema shape.

This is the ONLY description of the chart the planner model ever sees. It
describes the chart's *shape* and the value sets the planner may use as params.
It contains zero patient data. Every enum here is an allowlist: a plan param
that is not a member of one of these sets is rejected by the gate, which is what
structurally prevents the model from smuggling a raw value into a param.
"""
from __future__ import annotations

# --- Controlled vocabularies (plan params must be members of these) ---------

# Derived boolean features the executor can evaluate from the chart.
FEATURE_FLAGS = [
    "on_anticoagulant",
    "on_antiplatelet",
    "on_nsaid",
    "on_beta_blocker",
    "on_opioid",
    "on_insulin",
    "polypharmacy",            # >= 5 active meds
    "allergies_documented",
    "vitals_recorded",
    "abnormal_vitals_present",
    "has_linked_ehr",
]

# Categorical fields the executor can bucket.
CATEGORY_FIELDS = [
    "age_band",
    "sex",
    "esi_level",
    "chief_complaint_category",
    "medication_burden",
]

# Clinical problem categories used to slice the longitudinal record.
CONDITION_CATEGORIES = [
    "cardiac",
    "renal",
    "endocrine",
    "respiratory",
    "neurologic",
    "psychiatric",
    "gastrointestinal",
    "oncologic",
    "infectious",
    "musculoskeletal",
]

# Risk / operational models the planner may request (register adapters to light up).
RISK_MODELS = ["esi_refine", "early_warning", "sepsis"]
OPERATIONAL_MODELS = ["no_show", "disposition", "wait_time"]


def schema_card() -> dict:
    """The PHI-free schema description handed to the planner in Pass 1."""
    return {
        "fields": {
            "age_band": "coded age bucket (no exact DOB)",
            "sex": "coded",
            "esi_level": "triage acuity 1-5",
            "chief_complaint_category": "coded category of the presenting complaint",
            "problem_list": "conditions coded as ICD-10, queryable by category",
            "medications": "active meds, queryable as drug CLASS flags (not product names)",
            "allergies": "documented allergy classes",
            "vitals": "presence + abnormal flags only (no numeric values)",
            "linked_ehr": "boolean; longitudinal record queryable by category",
        },
        "vocab": {
            "feature_flags": FEATURE_FLAGS,
            "category_fields": CATEGORY_FIELDS,
            "condition_categories": CONDITION_CATEGORIES,
            "risk_models": RISK_MODELS,
            "operational_models": OPERATIONAL_MODELS,
        },
        "note": (
            "You never receive raw patient values — only coded outputs from the "
            "primitives. Real values (drug product names, numeric vitals, dates) "
            "are rendered to the clinician through deterministic slots you bind by "
            "reference."
        ),
    }
