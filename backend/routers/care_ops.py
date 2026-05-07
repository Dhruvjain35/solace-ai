"""Care operations endpoints — eligibility (270/271), no-show prediction,
HEDIS care-gap surfacing, SDoH PRAPARE screener, FHIR write-back, governance.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from db import storage
from lib.auth import audit, require_clinician
from services import eligibility, fhir_writer, hedis, no_show, screeners

log = logging.getLogger(__name__)

router = APIRouter()


# ---- Eligibility ---------------------------------------------------------------
class EligibilityBody(BaseModel):
    payer_name: str
    member_id: str
    patient_first: str
    patient_last: str
    patient_dob: str
    service_type: str = "30"


@router.post("/eligibility/check")
def elig_check(
    hospital_id: str = Path(...),
    body: EligibilityBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "eligibility.check", patient_id=body.member_id)
    full = eligibility.check(
        body.payer_name, body.member_id, body.patient_first, body.patient_last, body.patient_dob,
        service_type=body.service_type,
    )
    return {"raw_271": full, "summary": eligibility.summarize_for_clinician(full)}


# ---- No-show prediction --------------------------------------------------------
class NoShowBody(BaseModel):
    appointment_iso: str
    prior_no_shows: int = 0
    prior_completed: int = 0
    visit_type: str = "follow_up"
    booking_lead_days: int = 7
    age: int | None = None
    has_phone: bool = True


@router.post("/no-show/predict")
def no_show_predict(
    hospital_id: str = Path(...),
    body: NoShowBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    return no_show.predict(
        body.appointment_iso,
        prior_no_shows=body.prior_no_shows,
        prior_completed=body.prior_completed,
        visit_type=body.visit_type,
        booking_lead_days=body.booking_lead_days,
        age=body.age,
        has_phone=body.has_phone,
    )


# ---- HEDIS care gaps -----------------------------------------------------------
@router.get("/care-gaps/{patient_id}")
def care_gaps(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    return {"gaps": hedis.evaluate(p)}


class GapsAdHocBody(BaseModel):
    patient: dict[str, Any]


@router.post("/care-gaps/evaluate")
def care_gaps_adhoc(
    hospital_id: str = Path(...),
    body: GapsAdHocBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    return {"gaps": hedis.evaluate(body.patient)}


# ---- SDoH PRAPARE --------------------------------------------------------------
class PrapareBody(BaseModel):
    answers: dict[str, Any]


@router.post("/sdoh/prapare")
def sdoh_prapare(
    hospital_id: str = Path(...),
    body: PrapareBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "sdoh.prapare")
    return screeners.score("prapare", {"answers": body.answers})


# ---- FHIR write-back -----------------------------------------------------------
class FhirWriteBody(BaseModel):
    patient_ref: str  # e.g. "Patient/abc"
    note_text: str | None = None
    conditions: list[dict[str, str]] = []  # [{icd10, display}]
    allergies: list[dict[str, str]] = []   # [{substance, reaction, severity}]
    vitals: list[dict[str, Any]] = []      # [{loinc, display, value, unit}]
    social: list[dict[str, str]] = []      # [{loinc, display, text}]
    immunizations: list[dict[str, str]] = []  # [{cvx, display}]


@router.post("/ehr-write")
def ehr_write(
    hospital_id: str = Path(...),
    body: FhirWriteBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ehr.write", patient_id=body.patient_ref)
    results: list[dict[str, Any]] = []
    if body.note_text:
        r = fhir_writer.write(fhir_writer.build_document_reference(patient_ref=body.patient_ref, note_text=body.note_text))
        results.append({"resource": "DocumentReference", "result": r})
    for c in body.conditions:
        r = fhir_writer.write(fhir_writer.build_condition(patient_ref=body.patient_ref, icd10=c["icd10"], display=c.get("display", c["icd10"])))
        results.append({"resource": "Condition", "result": r})
    for a in body.allergies:
        r = fhir_writer.write(fhir_writer.build_allergy(patient_ref=body.patient_ref, substance_display=a["substance"], reaction=a.get("reaction", ""), severity=a.get("severity", "moderate")))
        results.append({"resource": "AllergyIntolerance", "result": r})
    for v in body.vitals:
        r = fhir_writer.write(fhir_writer.build_observation_vital(patient_ref=body.patient_ref, code_loinc=v["loinc"], display=v["display"], value=float(v["value"]), unit=v["unit"]))
        results.append({"resource": "Observation(vital)", "result": r})
    for s in body.social:
        r = fhir_writer.write(fhir_writer.build_observation_social(patient_ref=body.patient_ref, code_loinc=s["loinc"], display=s["display"], value_text=s["text"]))
        results.append({"resource": "Observation(social)", "result": r})
    for i in body.immunizations:
        r = fhir_writer.write(fhir_writer.build_immunization(patient_ref=body.patient_ref, vaccine_cvx=i["cvx"], vaccine_display=i["display"]))
        results.append({"resource": "Immunization", "result": r})
    return {"writes": results}


@router.get("/ehr-write/local")
def ehr_local(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    return {"resources": fhir_writer.list_local()}
