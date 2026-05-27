"""Specialty packs — a typed registry that tunes downstream behavior per specialty.

Each pack carries four things that change how Solace behaves for a given setting:

  1. **Section schema** — the ordered scribe-note sections, each section typed
     (required/optional, prose vs. list vs. structured) so the scribe can shape
     and validate its output instead of free-forming.
  2. **Few-shot exemplars** — short, redacted gold snippets the scribe can be
     primed with so a section reads the way that specialty actually documents.
  3. **Ddx priors** — specialty-aware weighting for the differential:
       - ``weight_more`` / ``weight_less`` nudge prior probability,
       - ``must_not_miss`` are the can't-miss diagnoses that must always be
         carried on the differential (or explicitly excluded) regardless of
         how unlikely they look, because the cost of a miss is catastrophic.
  4. **Default screeners / calculators** — what to surface at intake and at
     the encounter for that specialty.

Public interface (consumed by routers/clinical_ai.py):
  - ``list_packs()``  -> list[{"key", "name", ...}]
  - ``get_pack(key)`` -> dict | None  (JSON-serializable, returned as endpoint body)

``PACKS`` is kept as a legacy alias for the registry.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


# ---- Typed schema ---------------------------------------------------------------

SectionKind = Literal["prose", "list", "structured"]


class SectionSchema(TypedDict):
    """One scribe-note section."""
    key: str            # canonical section identifier (e.g. "HPI")
    label: str          # human-readable label
    kind: SectionKind   # how the scribe should shape the content
    required: bool      # whether the note is incomplete without it
    hint: str           # one-line guidance for the scribe


class DdxPriors(TypedDict):
    """Specialty-aware differential priors."""
    weight_more: list[str]    # over-weight these dx categories
    weight_less: list[str]    # under-weight these dx categories
    must_not_miss: list[str]  # carry-or-explicitly-exclude, always


class Pack(TypedDict):
    """A fully typed specialty pack."""
    key: str
    name: str
    sections: list[SectionSchema]
    exemplars: dict[str, str]        # section key -> redacted gold snippet
    default_screeners: list[str]
    default_calculators: list[str]
    ddx_priors: DdxPriors


# ---- Section builder ------------------------------------------------------------

def _sec(key: str, label: str, kind: SectionKind, required: bool, hint: str) -> SectionSchema:
    return {"key": key, "label": label, "kind": kind, "required": required, "hint": hint}


# Common sections reused across packs so schemas stay consistent.
_CC = _sec("CHIEF_COMPLAINT", "Chief Complaint", "prose", True, "Patient's reason for visit in their words, brief.")
_HPI = _sec("HPI", "History of Present Illness", "prose", True, "OPQRST narrative, chronological, pertinent positives/negatives.")
_ROS = _sec("REVIEW_OF_SYSTEMS", "Review of Systems", "list", False, "By system; note 'otherwise negative' when appropriate.")
_PMH = _sec("PAST_MEDICAL_HISTORY", "Past Medical History", "list", False, "Active and resolved problems with rough dates.")
_MEDS = _sec("MEDICATIONS", "Medications", "list", True, "Name, dose, route, frequency; flag recent changes.")
_ALLERGIES = _sec("ALLERGIES", "Allergies", "list", True, "Agent + reaction; explicitly state NKDA if none.")
_EXAM = _sec("PHYSICAL_EXAM", "Physical Exam", "structured", True, "Vitals then by system; objective findings only.")
_ASSESS = _sec("ASSESSMENT", "Assessment", "prose", True, "Problem-oriented; working dx with brief reasoning.")
_PLAN = _sec("PLAN", "Plan", "list", True, "Per problem: workup, treatment, disposition, follow-up.")


# ---- Registry -------------------------------------------------------------------

PACKS: dict[str, Pack] = {
    "ed": {
        "key": "ed",
        "name": "Emergency Department",
        "sections": [
            _CC, _HPI, _ROS, _PMH, _MEDS, _ALLERGIES, _EXAM, _ASSESS, _PLAN,
            _sec("DISPOSITION", "Disposition", "prose", True,
                 "Admit / discharge / observation / transfer, with the deciding reasoning."),
        ],
        "exemplars": {
            "HPI": ("52M with 2h substernal chest pressure radiating to left arm, "
                    "diaphoresis, started at rest. No prior cardiac hx. Took 1 ASA en route. "
                    "Pertinent negatives: no fever, no recent immobilization, no calf pain."),
            "ASSESSMENT": ("Undifferentiated chest pain, intermediate-risk by HEART (score 5). "
                           "ACS not excluded; PE less likely (Wells low, PERC pending)."),
            "DISPOSITION": ("Admit to obs for serial troponin + ECG; cardiology consulted. "
                            "Discharge contingent on negative serials and stress testing."),
        },
        "default_screeners": ["audit_c"],
        "default_calculators": ["heart", "wells_pe", "perc", "nihss", "qsofa", "news2"],
        "ddx_priors": {
            "weight_more": ["acute coronary syndrome", "pulmonary embolism", "stroke",
                            "sepsis", "appendicitis", "ectopic pregnancy"],
            "weight_less": ["chronic disease management", "preventive care"],
            "must_not_miss": ["acute coronary syndrome", "pulmonary embolism", "aortic dissection",
                              "stroke", "subarachnoid hemorrhage", "sepsis", "ectopic pregnancy",
                              "necrotizing fasciitis", "testicular/ovarian torsion"],
        },
    },
    "primary_care": {
        "key": "primary_care",
        "name": "Primary Care",
        "sections": [
            _CC, _HPI, _ROS, _PMH, _MEDS, _ALLERGIES, _EXAM, _ASSESS, _PLAN,
            _sec("HEALTH_MAINTENANCE", "Health Maintenance", "list", False,
                 "Screening, immunizations, and preventive care gaps due."),
        ],
        "exemplars": {
            "HPI": ("44F here for 3-week dry cough, worse at night, no fever, no dyspnea. "
                    "Recent URI in household. No tobacco. Pertinent negatives: no hemoptysis, "
                    "no weight loss, no reflux symptoms."),
            "ASSESSMENT": ("Post-viral cough, self-limited. HTN well controlled on current regimen. "
                           "Type 2 DM at goal (A1c 6.8%)."),
        },
        "default_screeners": ["phq9", "gad7", "audit_c", "prapare"],
        "default_calculators": ["centor", "curb65", "ascvd"],
        "ddx_priors": {
            "weight_more": ["URI", "uncomplicated UTI", "anxiety", "depression",
                            "chronic disease exacerbation"],
            "weight_less": ["acute coronary syndrome", "stroke"],
            "must_not_miss": ["acute coronary syndrome", "pulmonary embolism", "stroke",
                              "occult malignancy", "abdominal aortic aneurysm",
                              "meningitis", "suicidal ideation"],
        },
    },
    "cardiology": {
        "key": "cardiology",
        "name": "Cardiology",
        "sections": [
            _CC, _HPI,
            _sec("CARDIAC_HISTORY", "Cardiac History", "list", True,
                 "Prior MI/PCI/CABG, EF, arrhythmias, devices, last echo/cath."),
            _MEDS, _ALLERGIES, _EXAM,
            _sec("EKG_INTERPRETATION", "EKG Interpretation", "structured", True,
                 "Rate, rhythm, axis, intervals, ischemic changes vs. prior."),
            _ASSESS, _PLAN,
        ],
        "exemplars": {
            "CARDIAC_HISTORY": ("CAD s/p DES to LAD 2021, EF 40% (echo 3mo ago), "
                                "paroxysmal AF on apixaban. No ICD."),
            "EKG_INTERPRETATION": ("NSR 78, normal axis, QTc 430ms, no acute ST-T changes, "
                                   "unchanged from prior."),
        },
        "default_screeners": [],
        "default_calculators": ["heart", "wells_pe", "chadsvasc", "ascvd"],
        "ddx_priors": {
            "weight_more": ["acute coronary syndrome", "heart failure",
                            "atrial fibrillation", "valvular disease"],
            "weight_less": [],
            "must_not_miss": ["acute coronary syndrome", "aortic dissection",
                              "pulmonary embolism", "cardiac tamponade",
                              "high-grade AV block", "ventricular tachycardia"],
        },
    },
    "peds": {
        "key": "peds",
        "name": "Pediatrics",
        "sections": [
            _CC, _HPI,
            _sec("BIRTH_HISTORY", "Birth History", "structured", False,
                 "Gestational age, delivery mode, birth weight, nursery course."),
            _sec("DEVELOPMENT", "Development", "structured", False,
                 "Milestones by domain; flag any regression or delay."),
            _sec("IMMUNIZATIONS", "Immunizations", "list", True,
                 "Up-to-date vs. catch-up needed per ACIP schedule."),
            _ALLERGIES, _EXAM, _ASSESS, _PLAN,
            _sec("ANTICIPATORY_GUIDANCE", "Anticipatory Guidance", "list", False,
                 "Safety, nutrition, development counseling appropriate to age."),
        ],
        "exemplars": {
            "HPI": ("18-month-old with 2 days of fever to 39.4C, decreased oral intake, "
                    "pulling at right ear. Making fewer wet diapers. Pertinent negatives: "
                    "no rash, no lethargy, no respiratory distress, immunizations UTD."),
            "ASSESSMENT": ("Acute otitis media, right, in a well-appearing toddler. "
                           "Mild dehydration. No red-flag features for serious bacterial illness."),
        },
        "default_screeners": ["crafft", "mchat"],
        "default_calculators": ["centor", "qsofa"],
        "ddx_priors": {
            "weight_more": ["viral URI", "acute otitis media", "bronchiolitis",
                            "asthma exacerbation", "gastroenteritis"],
            "weight_less": ["acute coronary syndrome", "pulmonary embolism"],
            "must_not_miss": ["meningitis", "sepsis", "non-accidental trauma",
                              "intussusception", "testicular torsion",
                              "diabetic ketoacidosis", "myocarditis", "Kawasaki disease"],
        },
    },
    "psych": {
        "key": "psych",
        "name": "Psychiatry / Behavioral Health",
        "sections": [
            _CC, _HPI,
            _sec("PAST_PSYCHIATRIC_HISTORY", "Past Psychiatric History", "list", True,
                 "Prior dx, hospitalizations, suicide attempts, prior trials and response."),
            _MEDS,
            _sec("SUBSTANCE_USE", "Substance Use", "structured", True,
                 "Each substance: amount, frequency, last use, prior treatment."),
            _sec("MENTAL_STATUS_EXAM", "Mental Status Exam", "structured", True,
                 "Appearance, behavior, speech, mood/affect, thought, cognition, insight."),
            _sec("RISK_ASSESSMENT", "Risk Assessment", "structured", True,
                 "SI/HI ideation/intent/plan/means, protective factors, level of risk."),
            _ASSESS, _PLAN,
        ],
        "exemplars": {
            "MENTAL_STATUS_EXAM": ("Casually dressed, cooperative, normal psychomotor. Speech "
                                   "normal rate/rhythm. Mood 'down', affect constricted. Thought "
                                   "linear, no SI/HI, no psychosis. Insight/judgment fair."),
            "RISK_ASSESSMENT": ("Passive SI without intent, plan, or access to means. Protective: "
                                "children at home, engaged in treatment. Low acute risk; safety "
                                "plan completed."),
        },
        "default_screeners": ["phq9", "gad7", "audit_c", "pcl5", "ace", "epds", "cssrs"],
        "default_calculators": [],
        "ddx_priors": {
            "weight_more": ["major depressive disorder", "generalized anxiety disorder",
                            "PTSD", "bipolar disorder", "substance use disorder"],
            "weight_less": ["acute medical emergencies (route to ED)"],
            "must_not_miss": ["active suicidal ideation with plan", "homicidal ideation",
                              "delirium", "serotonin syndrome", "neuroleptic malignant syndrome",
                              "acute intoxication or withdrawal", "first-break psychosis"],
        },
    },
    "ortho": {
        "key": "ortho",
        "name": "Orthopedics",
        "sections": [
            _CC, _HPI,
            _sec("MECHANISM", "Mechanism of Injury", "prose", True,
                 "Energy, position, direction of force, time since injury."),
            _sec("PRIOR_INJURIES", "Prior Injuries", "list", False,
                 "Prior injuries or surgeries to the affected region."),
            _EXAM,
            _sec("IMAGING", "Imaging", "structured", False,
                 "Modality, views, findings; compare to prior if available."),
            _ASSESS, _PLAN,
        ],
        "exemplars": {
            "MECHANISM": ("Fall from standing onto outstretched right hand, immediate wrist "
                          "pain and deformity, ~1h ago. No head strike, no LOC."),
            "ASSESSMENT": ("Distal radius fracture, right, with dorsal angulation. "
                           "Neurovascularly intact. No open injury."),
        },
        "default_screeners": [],
        "default_calculators": ["wells_dvt", "ottawa_ankle"],
        "ddx_priors": {
            "weight_more": ["fracture", "tendon injury", "joint effusion",
                            "deep vein thrombosis"],
            "weight_less": [],
            "must_not_miss": ["compartment syndrome", "open fracture", "septic arthritis",
                              "cauda equina syndrome", "neurovascular injury",
                              "deep vein thrombosis"],
        },
    },
}


# ---- Public interface -----------------------------------------------------------

def list_packs() -> list[dict[str, Any]]:
    """Lightweight catalog: key + name + section/screener/calculator counts."""
    return [
        {
            "key": k,
            "name": v["name"],
            "section_count": len(v["sections"]),
            "screener_count": len(v["default_screeners"]),
            "calculator_count": len(v["default_calculators"]),
            "must_not_miss_count": len(v["ddx_priors"]["must_not_miss"]),
        }
        for k, v in PACKS.items()
    ]


def get_pack(key: str) -> dict[str, Any] | None:
    """Full pack by key, or None if unknown."""
    pack = PACKS.get(key)
    return dict(pack) if pack is not None else None


def pack_sections(key: str) -> list[SectionSchema]:
    """Ordered section schema for a pack; empty list if unknown."""
    pack = PACKS.get(key)
    return list(pack["sections"]) if pack else []


def must_not_miss(key: str) -> list[str]:
    """Can't-miss diagnoses for a pack; empty list if unknown."""
    pack = PACKS.get(key)
    return list(pack["ddx_priors"]["must_not_miss"]) if pack else []
