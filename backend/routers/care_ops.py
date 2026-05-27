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
from services import eligibility, fhir_writer, hedis, no_show, scheduling, screeners, sdoh

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
    try:
        full = eligibility.check(
            body.payer_name, body.member_id, body.patient_first, body.patient_last, body.patient_dob,
            service_type=body.service_type,
        )
        return {"raw_271": full, "summary": eligibility.summarize_for_clinician(full)}
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not run eligibility check: {e}")
    except Exception as e:  # noqa: BLE001
        log.exception("Eligibility check failed: %s", e)
        raise HTTPException(status_code=502, detail="eligibility service unavailable")


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
    audit(caller, "no_show.predict")
    try:
        return no_show.predict(
            body.appointment_iso,
            prior_no_shows=body.prior_no_shows,
            prior_completed=body.prior_completed,
            visit_type=body.visit_type,
            booking_lead_days=body.booking_lead_days,
            age=body.age,
            has_phone=body.has_phone,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid no-show prediction input: {e}")


class NoShowEquityBody(BaseModel):
    records: list[dict[str, Any]]
    group_key: str = "demographic_group"


@router.post("/no-show/equity-audit")
def no_show_equity_audit(
    hospital_id: str = Path(...),
    body: NoShowEquityBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Predicted-risk distribution sliced by demographic group, with a fairness
    flag when the largest between-group gap exceeds the review threshold."""
    audit(caller, "no_show.equity_audit")
    try:
        return no_show.equity_audit(body.records, group_key=body.group_key)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid no-show equity audit input: {e}")


class ReminderPlanBody(BaseModel):
    tier: str
    appointment_iso: str | None = None
    no_show_probability: float | None = None


@router.post("/no-show/reminder-plan")
def no_show_reminder_plan(
    hospital_id: str = Path(...),
    body: ReminderPlanBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Build a concrete tiered reminder plan (channels + send times) from a
    no-show risk tier produced by /no-show/predict."""
    audit(caller, "no_show.reminder_plan")
    try:
        return scheduling.reminder_plan(
            tier=body.tier,
            appointment_iso=body.appointment_iso,
            no_show_probability=body.no_show_probability,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid reminder plan input: {e}")


# ---- HEDIS care gaps -----------------------------------------------------------
@router.get("/care-gaps/{patient_id}")
def care_gaps(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "care_gaps.view", patient_id=patient_id)
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    try:
        return {"gaps": hedis.evaluate(p)}
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not evaluate care gaps: {e}")


class GapsAdHocBody(BaseModel):
    patient: dict[str, Any]


@router.post("/care-gaps/evaluate")
def care_gaps_adhoc(
    hospital_id: str = Path(...),
    body: GapsAdHocBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "care_gaps.evaluate")
    try:
        return {"gaps": hedis.evaluate(body.patient)}
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not evaluate care gaps: {e}")


@router.get("/care-gaps/{patient_id}/sidebar")
def care_gaps_sidebar(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    limit: int = 2,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Top-`limit` HEDIS care gaps ranked by impact for the encounter sidebar."""
    audit(caller, "care_gaps.sidebar", patient_id=patient_id)
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    try:
        return hedis.encounter_sidebar(p, limit=limit)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not build care-gap sidebar: {e}")


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
    try:
        return screeners.score("prapare", {"answers": body.answers})
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not score PRAPARE screener: {e}")


class SdohScreenBody(BaseModel):
    answers: dict[str, Any]
    instrument: str = "prapare"


@router.post("/sdoh/screen")
def sdoh_screen(
    hospital_id: str = Path(...),
    body: SdohScreenBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Score a social-needs screener (PRAPARE / AHC-HRSN): positive domains,
    risk level, ICD-10 Z-codes, and recommended referral categories."""
    audit(caller, "sdoh.screen")
    try:
        return sdoh.screen(body.answers, instrument=body.instrument)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not score SDoH screener: {e}")


class SdohReferralBody(BaseModel):
    domain: str
    patient_ref: str
    consent: bool = False
    organization: str | None = None
    note: str | None = None
    network: str = "findhelp"


@router.post("/sdoh/referral")
def sdoh_referral(
    hospital_id: str = Path(...),
    body: SdohReferralBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Build a closed-loop community-resource referral for one SDoH domain.

    Per SEC-004, the referral is only transmittable when consent is granted;
    without consent it is returned in status 'blocked_no_consent' (auditable
    but never sent to the community network)."""
    audit(caller, "sdoh.referral", patient_id=body.patient_ref)
    try:
        return sdoh.build_referral(
            domain=body.domain,
            patient_ref=body.patient_ref,
            consent=body.consent,
            organization=body.organization,
            note=body.note,
            network=body.network,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not build SDoH referral: {e}")


class SdohReferralsBody(BaseModel):
    screen_result: dict[str, Any]
    patient_ref: str
    consent: bool = False
    network: str = "findhelp"


@router.post("/sdoh/referrals")
def sdoh_referrals(
    hospital_id: str = Path(...),
    body: SdohReferralsBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Build one referral per positive domain from a /sdoh/screen result.

    Per SEC-004, referrals only transmit when consent is granted; without
    consent each is returned in status 'blocked_no_consent'."""
    audit(caller, "sdoh.referrals", patient_id=body.patient_ref)
    try:
        referrals = sdoh.build_referrals(
            body.screen_result,
            patient_ref=body.patient_ref,
            consent=body.consent,
            network=body.network,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not build SDoH referrals: {e}")
    return {"count": len(referrals), "referrals": referrals}


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

    def _write(resource_label: str, resource: dict[str, Any]) -> None:
        try:
            r = fhir_writer.write(resource)
        except Exception as e:  # noqa: BLE001
            log.exception("FHIR write failed for %s: %s", resource_label, e)
            raise HTTPException(status_code=502, detail=f"EHR write failed for {resource_label}")
        results.append({"resource": resource_label, "result": r})

    if body.note_text:
        _write("DocumentReference", fhir_writer.build_document_reference(patient_ref=body.patient_ref, note_text=body.note_text))
    for c in body.conditions:
        icd10 = c.get("icd10")
        if not icd10:
            raise HTTPException(status_code=400, detail="each condition requires an 'icd10' field")
        _write("Condition", fhir_writer.build_condition(patient_ref=body.patient_ref, icd10=icd10, display=c.get("display", icd10)))
    for a in body.allergies:
        substance = a.get("substance")
        if not substance:
            raise HTTPException(status_code=400, detail="each allergy requires a 'substance' field")
        _write("AllergyIntolerance", fhir_writer.build_allergy(patient_ref=body.patient_ref, substance_display=substance, reaction=a.get("reaction", ""), severity=a.get("severity", "moderate")))
    for v in body.vitals:
        loinc, display, raw_value, unit = v.get("loinc"), v.get("display"), v.get("value"), v.get("unit")
        if not loinc or display is None or raw_value is None or unit is None:
            raise HTTPException(status_code=400, detail="each vital requires 'loinc', 'display', 'value', and 'unit'")
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"vital value must be numeric, got: {raw_value!r}")
        _write("Observation(vital)", fhir_writer.build_observation_vital(patient_ref=body.patient_ref, code_loinc=loinc, display=display, value=value, unit=unit))
    for s in body.social:
        loinc, display, text = s.get("loinc"), s.get("display"), s.get("text")
        if not loinc or display is None or text is None:
            raise HTTPException(status_code=400, detail="each social entry requires 'loinc', 'display', and 'text'")
        _write("Observation(social)", fhir_writer.build_observation_social(patient_ref=body.patient_ref, code_loinc=loinc, display=display, value_text=text))
    for i in body.immunizations:
        cvx, display = i.get("cvx"), i.get("display")
        if not cvx or display is None:
            raise HTTPException(status_code=400, detail="each immunization requires 'cvx' and 'display'")
        _write("Immunization", fhir_writer.build_immunization(patient_ref=body.patient_ref, vaccine_cvx=cvx, vaccine_display=display))
    return {"writes": results}


@router.get("/ehr-write/local")
def ehr_local(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ehr.write.list_local")
    return {"resources": fhir_writer.list_local()}
