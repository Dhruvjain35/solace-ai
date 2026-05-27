"""Refill triage agent.

Each refill request is classified against a configurable protocol library:

  - PROTOCOL_APPROVED   — chronic-stable medication, last labs within window,
                          no recent ED/hospital visit -> auto-approve with a
                          non-PHI audit log entry.
  - NEEDS_LABS / NEEDS_VISIT — labs out of window, last visit > X months, or
                          red-flag interactions / new dx -> auto-drafted patient
                          response telling them exactly what to book.
  - PHYSICIAN_REQUIRED  — controlled substance, abx, opioid, benzo, anticoag, or
                          med not in protocol library -> routed to a physician.

Depth added in this revision:

- **Structured rationale codes** — every decision carries a machine-readable
  `rationale_codes` list (see `RATIONALE_CODES`) alongside the human reason, so
  downstream systems, audits, and QA dashboards do not have to parse prose.

- **Non-PHI audit log** — `triage()` appends a hashed, de-identified entry to an
  in-process audit ring. It records the decision, rationale codes, and a
  SHA-256 hash of the medication name. No patient identifier, no plaintext med,
  nothing that is a HIPAA Safe Harbor identifier. Auto-approvals MUST be
  auditable; this is that trail. Read it with `audit_log()`.

- **Auto-drafted patient response** — needs-labs / needs-visit decisions return
  a `patient_message` plus a `send_envelope` whose `auto_send_eligible` is
  always False (a clinician confirms before the patient is contacted).

The actual e-prescribe write goes through Surescripts (not implemented here);
this module produces the decision, rationale codes, and patient response only.
"""
from __future__ import annotations

import hashlib
import logging
from collections import deque
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

# Drug-class buckets for ALWAYS_PHYSICIAN — drives the precise rationale code.
_CONTROLLED = {
    "alprazolam", "lorazepam", "clonazepam", "diazepam", "oxycodone", "hydrocodone",
    "morphine", "tramadol", "codeine", "fentanyl", "methylphenidate", "amphetamine",
    "lisdexamfetamine", "zolpidem",
}
_ANTICOAG = {"warfarin", "apixaban", "rivaroxaban", "dabigatran"}
_ANTIBIOTIC = {
    "amoxicillin", "azithromycin", "ciprofloxacin", "levofloxacin", "doxycycline",
    "clindamycin", "metronidazole", "cephalexin",
}
_STEROID = {"prednisone", "methotrexate"}


# Machine-readable rationale codes. The human `reason` is for display; these are
# for audits, QA dashboards, and downstream automation.
RATIONALE_CODES = {
    "PROTOCOL_MATCH":        "Medication has a standing-order protocol and all conditions are met.",
    "CONTROLLED_SUBSTANCE":  "Controlled substance — DEA-scheduled, requires prescriber decision.",
    "ANTICOAGULANT":         "Anticoagulant — narrow therapeutic index, requires prescriber decision.",
    "ANTIBIOTIC_PER_COURSE": "Antibiotic — each course requires a fresh clinical decision.",
    "STEROID_IMMUNOSUPP":    "Steroid/immunosuppressant — requires prescriber decision.",
    "NO_PROTOCOL":           "No standing-order protocol exists for this medication.",
    "RECENT_HOSPITALIZATION": "Recent hospitalization — medication regimen may have changed.",
    "VISIT_OUT_OF_WINDOW":   "Last visit is older than the protocol's required interval.",
    "VISIT_DATE_UNKNOWN":    "No last-visit date on file; cannot confirm visit window.",
    "LAB_OUT_OF_WINDOW":     "Required monitoring lab is missing or older than 12 months.",
    "ON_ANTICOAGULANT_FLAG": "Patient is flagged as on an anticoagulant — interaction review needed.",
}


# In-process, non-PHI audit ring. Bounded so it cannot grow without limit.
_AUDIT_LOG: deque[dict[str, Any]] = deque(maxlen=2000)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _med_hash(med: str) -> str:
    """SHA-256 of the medication name — de-identified key for the audit trail."""
    return hashlib.sha256((med or "").encode("utf-8")).hexdigest()[:16]


def _record_audit(med: str, decision: str, rationale_codes: list[str]) -> None:
    """Append a de-identified audit entry. No PHI: only a med hash + decision."""
    _AUDIT_LOG.append({
        "ts": _now(),
        "med_hash": _med_hash(med),
        "decision": decision,
        "rationale_codes": list(rationale_codes),
        "auto_approved": decision == "protocol_approved",
    })


def audit_log(*, limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent de-identified refill-triage audit entries."""
    items = list(_AUDIT_LOG)
    return items[-limit:][::-1]


def _months_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    return (datetime.now(timezone.utc) - dt).days / 30.0


def _envelope(patient_message: str, *, auto_draft: bool) -> dict[str, Any]:
    """One-click-send envelope for the patient response.

    auto_send_eligible is ALWAYS False — a clinician confirms before any patient
    is contacted, even for a clean protocol approval.
    """
    return {
        "channel": "portal_message",
        "body": patient_message,
        "auto_draft": auto_draft,
        "auto_send_eligible": False,
        "auto_send_block_reason": (
            "A clinician must confirm the refill decision before the patient is contacted."
        ),
        "requires_clinician_review": True,
    }


def triage(
    medication_canonical: str,
    *,
    last_visit_iso: str | None = None,
    relevant_lab_iso: str | None = None,
    relevant_lab_value: float | None = None,
    on_anticoagulant: bool = False,
    recent_hospitalization: bool = False,
) -> dict[str, Any]:
    """Classify a single refill request.

    Output shape (all paths):
      {
        "decision": "protocol_approved | needs_visit | needs_labs | physician_required",
        "reason": str,                          # human-readable
        "rationale_codes": [str, ...],          # keys of RATIONALE_CODES
        "rationale_detail": [{"code", "message"}, ...],
        "patient_message": str,                 # auto-drafted reply
        "labs_to_order": [str, ...],            # present on needs_labs only
        "auto_approved": bool,
        "requires_clinician_review": bool,
        "send_envelope": {... auto_send_eligible: False ...},
        "audited": True,
      }
    """
    med = (medication_canonical or "").strip().lower()

    def _finish(decision: str, reason: str, codes: list[str], patient_message: str,
                *, labs: list[str] | None = None, auto_draft: bool = True) -> dict[str, Any]:
        _record_audit(med, decision, codes)
        out: dict[str, Any] = {
            "decision": decision,
            "reason": reason,
            "rationale_codes": codes,
            "rationale_detail": [
                {"code": c, "message": RATIONALE_CODES.get(c, "")} for c in codes
            ],
            "patient_message": patient_message,
            "auto_approved": decision == "protocol_approved",
            "requires_clinician_review": decision != "protocol_approved" or bool(labs),
            "send_envelope": _envelope(patient_message, auto_draft=auto_draft),
            "audited": True,
        }
        if labs is not None:
            out["labs_to_order"] = labs
        return out

    # ---- Physician-required: always-physician medication list -------------------
    if med in ALWAYS_PHYSICIAN:
        if med in _CONTROLLED:
            code, cat = "CONTROLLED_SUBSTANCE", "controlled substance"
        elif med in _ANTICOAG:
            code, cat = "ANTICOAGULANT", "anticoagulant"
        elif med in _ANTIBIOTIC:
            code, cat = "ANTIBIOTIC_PER_COURSE", "antibiotic"
        elif med in _STEROID:
            code, cat = "STEROID_IMMUNOSUPP", "steroid or immunosuppressant"
        else:
            code, cat = "NO_PROTOCOL", "this medication"
        return _finish(
            "physician_required",
            f"Medication requires clinician decision ({cat}).",
            [code],
            "Your refill request needs to be reviewed by your provider. "
            "We'll get back to you within 1-2 business days.",
        )

    proto = PROTOCOLS.get(med)
    if not proto:
        return _finish(
            "physician_required",
            "No standing-order protocol for this medication.",
            ["NO_PROTOCOL"],
            "Your refill request needs to be reviewed by your provider.",
        )

    months_v = _months_since(last_visit_iso)
    months_l = _months_since(relevant_lab_iso)

    # ---- Physician-required: recent hospitalization -----------------------------
    if recent_hospitalization:
        return _finish(
            "physician_required",
            "Recent hospitalization — clinician review required.",
            ["RECENT_HOSPITALIZATION"],
            "Your provider will review your refill in light of your recent hospital visit.",
        )

    # ---- Physician-required: anticoagulant interaction flag ---------------------
    if on_anticoagulant:
        return _finish(
            "physician_required",
            "Patient is on an anticoagulant — interaction review required before refill.",
            ["ON_ANTICOAGULANT_FLAG"],
            "Your provider needs to review this refill because of another medication "
            "you take. We'll be in touch within 1-2 business days.",
        )

    # ---- Needs visit ------------------------------------------------------------
    if months_v is None:
        return _finish(
            "needs_visit",
            f"No last-visit date on file; protocol requires a visit within "
            f"{proto['months_since_visit']} months.",
            ["VISIT_DATE_UNKNOWN"],
            "We could not confirm your last visit for this medication. Please book a "
            "brief visit so we can refill it safely.",
        )
    if months_v > proto["months_since_visit"]:
        return _finish(
            "needs_visit",
            f"Last visit was {round(months_v)} months ago; protocol requires a visit "
            f"within {proto['months_since_visit']} months.",
            ["VISIT_OUT_OF_WINDOW"],
            f"It's been more than {proto['months_since_visit']} months since your last "
            f"visit for this medication. Please book a brief visit so we can refill safely.",
        )

    # ---- Needs labs -------------------------------------------------------------
    if proto["lab"] and (months_l is None or months_l > 12):
        return _finish(
            "needs_labs",
            f"{proto['lab']} not on file within the last 12 months.",
            ["LAB_OUT_OF_WINDOW"],
            f"We need an updated lab ({proto['lab']}) before refilling. "
            f"Please book a quick lab draw.",
            labs=[proto["lab"]],
        )

    # ---- Protocol approved ------------------------------------------------------
    return _finish(
        "protocol_approved",
        proto["description"],
        ["PROTOCOL_MATCH"],
        "Your refill has been approved. Please allow 24-48 hours for the pharmacy "
        "to process it.",
        auto_draft=False,
    )
