"""Wave 4 routes — HL7 v2, multi-encounter, fax intake, sepsis bundle, cohort
export, OCR-to-eligibility, MedicationStatement write, style learning, patient
portal messaging, nurse triage, TEFCA, telehealth.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile
from pydantic import BaseModel, ConfigDict

from lib.auth import audit, require_clinician
from services import (
    cohort_export,
    discharge_plan,
    early_warning,
    fax_intake,
    fhir_writer,
    followups,
    hl7_v2,
    insurance_to_eligibility,
    inbox_drafts,
    multi_encounter,
    nurse_triage,
    portal_messages,
    sepsis_bundle,
    style_learning,
    tefca_qhin,
    telehealth,
    workup,
)

log = logging.getLogger(__name__)

router = APIRouter()


# ---- HL7 v2 MDM^T02 -------------------------------------------------------------
class Hl7MdmBody(BaseModel):
    note_text: str
    mrn: str
    family_name: str
    given_name: str
    dob: str
    sex: str = "U"
    npi: str = "1234567890"
    provider_family: str = "Provider"
    provider_given: str = "Solace"
    receiving_app: str = "EHR"
    receiving_facility: str = "HOSPITAL"
    encounter_id: str = ""
    note_type_code: str = "PROG"
    note_type_display: str = "Progress note"
    visit_class: str = "O"


@router.post("/hl7/mdm/render")
def hl7_mdm_render(
    hospital_id: str = Path(...),
    body: Hl7MdmBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "hl7.mdm.render", patient_id=body.mrn)
    msg = hl7_v2.MdmMessage(
        note_text=body.note_text,
        encounter_id=body.encounter_id,
        receiving_app=body.receiving_app,
        receiving_facility=body.receiving_facility,
        note_type_code=body.note_type_code,
        note_type_display=body.note_type_display,
        visit_class=body.visit_class,
        patient=hl7_v2.Patient(mrn=body.mrn, family_name=body.family_name, given_name=body.given_name, dob=body.dob, sex=body.sex),
        provider=hl7_v2.Provider(npi=body.npi, family_name=body.provider_family, given_name=body.provider_given),
    )
    s = hl7_v2.render(msg)
    return {"hl7_message": s, "mllp_frame_b64": base64.b64encode(hl7_v2.to_mllp_frame(s)).decode("ascii")}


class Hl7MllpSendBody(Hl7MdmBody):
    host: str
    port: int = 6661


@router.post("/hl7/mdm/send")
def hl7_mdm_send(
    hospital_id: str = Path(...),
    body: Hl7MllpSendBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "hl7.mdm.send", patient_id=body.mrn)
    msg = hl7_v2.MdmMessage(
        note_text=body.note_text,
        encounter_id=body.encounter_id,
        receiving_app=body.receiving_app,
        receiving_facility=body.receiving_facility,
        note_type_code=body.note_type_code,
        note_type_display=body.note_type_display,
        visit_class=body.visit_class,
        patient=hl7_v2.Patient(mrn=body.mrn, family_name=body.family_name, given_name=body.given_name, dob=body.dob, sex=body.sex),
        provider=hl7_v2.Provider(npi=body.npi, family_name=body.provider_family, given_name=body.provider_given),
    )
    s = hl7_v2.render(msg)
    try:
        result = hl7_v2.send_mllp(body.host, body.port, s)
    except Exception as e:  # noqa: BLE001
        log.exception("HL7 MLLP send failed: %s", e)
        raise HTTPException(status_code=502, detail="HL7 MLLP delivery failed")
    return {"hl7_message": s, "result": result}


# ---- Multi-encounter ------------------------------------------------------------
class StitchBody(BaseModel):
    notes: list[dict[str, Any]]


@router.post("/encounter/stitch")
def encounter_stitch(
    hospital_id: str = Path(...),
    body: StitchBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "encounter.stitch")
    try:
        return multi_encounter.stitch(body.notes)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not stitch encounters: {e}")


class HuddleBody(BaseModel):
    transcript: str
    ward_context: str = ""


@router.post("/encounter/huddle")
def encounter_huddle(
    hospital_id: str = Path(...),
    body: HuddleBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "encounter.huddle")
    try:
        return multi_encounter.parse_huddle(body.transcript, ward_context=body.ward_context)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not parse huddle: {e}")


# ---- Fax intake -----------------------------------------------------------------
@router.post("/fax/intake")
async def fax_intake_endpoint(
    hospital_id: str = Path(...),
    file: UploadFile = File(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "fax.intake")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="empty file upload")
    ct = file.content_type or "application/octet-stream"
    try:
        if "pdf" in ct.lower():
            return fax_intake.parse_pdf_bytes(blob)
        if ct.lower().startswith("image/"):
            return fax_intake.parse_image_b64(base64.b64encode(blob).decode("ascii"), content_type=ct)
        # text fallback
        text = blob.decode("utf-8", errors="ignore")
        return fax_intake.parse_text(text)
    except Exception as e:  # noqa: BLE001
        log.exception("Fax intake parse failed (content_type=%s): %s", ct, e)
        raise HTTPException(status_code=400, detail="could not parse fax content")


# ---- Sepsis bundle --------------------------------------------------------------
class SepsisBundleBody(BaseModel):
    sepsis_recognition_iso: str
    lactate_drawn_iso: str | None = None
    initial_lactate_value: float | None = None
    blood_cultures_drawn_iso: str | None = None
    antibiotics_given_iso: str | None = None
    fluids_started_iso: str | None = None
    fluids_dose_ml_per_kg: float | None = None
    vasopressors_started_iso: str | None = None
    persistent_hypotension_after_fluids: bool = False
    bundle_window_minutes: int = 60


@router.post("/sepsis/bundle/evaluate")
def sepsis_bundle_evaluate(
    hospital_id: str = Path(...),
    body: SepsisBundleBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "sepsis.bundle.evaluate")
    try:
        return sepsis_bundle.evaluate_encounter(**body.model_dump())
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid sepsis bundle input: {e}")


class SepsisCohortBody(BaseModel):
    evaluations: list[dict[str, Any]]


@router.post("/sepsis/bundle/cohort")
def sepsis_bundle_cohort(
    hospital_id: str = Path(...),
    body: SepsisCohortBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "sepsis.bundle.cohort")
    try:
        return sepsis_bundle.cohort_summary(body.evaluations)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid sepsis cohort input: {e}")


# ---- Cohort export --------------------------------------------------------------
class CohortKickoffBody(BaseModel):
    fhir_base_url: str = ""
    group_id: str | None = None
    types: list[str] | None = None
    since: str | None = None


@router.post("/cohort/export/kickoff")
def cohort_kickoff(
    hospital_id: str = Path(...),
    body: CohortKickoffBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "cohort.export.kickoff")
    return cohort_export.kick_off(
        fhir_base_url=body.fhir_base_url,
        group_id=body.group_id,
        types=body.types,
        since=body.since,
    )


@router.get("/cohort/export/poll")
def cohort_poll(
    hospital_id: str = Path(...),
    content_location: str = "",
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "cohort.export.poll")
    if not content_location:
        raise HTTPException(status_code=400, detail="content_location is required")
    try:
        return cohort_export.poll(content_location)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not poll cohort export: {e}")


class CohortQueryBody(BaseModel):
    condition_icd10: str | None = None
    lab_loinc_above: tuple[str, float] | None = None
    age_band: tuple[int, int] | None = None


@router.post("/cohort/query")
def cohort_query(
    hospital_id: str = Path(...),
    body: CohortQueryBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "cohort.query")
    try:
        return cohort_export.cohort_query(
            condition_icd10=body.condition_icd10,
            lab_loinc_above=body.lab_loinc_above,
            age_band=body.age_band,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid cohort query: {e}")


# ---- Insurance OCR -> eligibility chain -----------------------------------------
@router.post("/insurance/ocr-to-eligibility")
async def insurance_chain(
    hospital_id: str = Path(...),
    file: UploadFile = File(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "insurance.ocr_to_eligibility")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="empty file upload")
    try:
        return insurance_to_eligibility.chain(image_bytes=blob)
    except Exception as e:  # noqa: BLE001
        log.exception("Insurance OCR-to-eligibility chain failed: %s", e)
        raise HTTPException(status_code=400, detail="could not process insurance card")


# ---- MedicationStatement write --------------------------------------------------
class MedReconBody(BaseModel):
    patient_ref: str
    medications: list[str]   # free-text or RxNorm display strings


@router.post("/ehr-write/medication-statements")
def med_reconciliation_write(
    hospital_id: str = Path(...),
    body: MedReconBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Write MedicationStatement resources (med reconciliation, NOT new prescriptions)."""
    audit(caller, "ehr.write.medication_statements", patient_id=body.patient_ref)
    if not body.medications:
        raise HTTPException(status_code=400, detail="at least one medication is required")
    results = []
    for med in body.medications:
        resource = {
            "resourceType": "MedicationStatement",
            "status": "active",
            "subject": {"reference": body.patient_ref},
            "medicationCodeableConcept": {"text": med},
            "dateAsserted": fhir_writer._now_iso(),
            "note": [{"text": "Reconciled via Solace — confirm before any new prescription."}],
        }
        try:
            r = fhir_writer.write(resource)
        except Exception as e:  # noqa: BLE001
            log.exception("MedicationStatement write failed: %s", e)
            raise HTTPException(status_code=502, detail="EHR write failed for a medication statement")
        results.append({"resource": "MedicationStatement", "input": med, "result": r})
    return {"writes": results}


# ---- Style learning -------------------------------------------------------------
class StylePairBody(BaseModel):
    ai_draft: str
    final: str
    section: str = "full_note"


@router.post("/style/record-pair")
def style_record_pair(
    hospital_id: str = Path(...),
    body: StylePairBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "style.record_pair")
    return style_learning.record_pair(
        clinician_id=caller.get("clinician_id", "unknown"),
        hospital_id=hospital_id,
        ai_draft=body.ai_draft,
        final=body.final,
        section=body.section,
    )


@router.get("/style/profile")
def style_profile(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "style.profile")
    return style_learning.style_profile(caller.get("clinician_id", "unknown"))


@router.get("/style/training-jsonl")
def style_export_jsonl(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "style.export_training_jsonl")
    text = style_learning.export_training_jsonl(caller.get("clinician_id", "unknown"))
    return {"format": "jsonl", "lines": text.count("\n") + (1 if text else 0), "preview": text[:1000]}


# ---- Portal messages -----------------------------------------------------------
class PortalInboundBody(BaseModel):
    patient_id: str
    body: str
    sender_name: str = "Patient"


@router.post("/portal/inbound")
def portal_inbound(
    hospital_id: str = Path(...),
    body: PortalInboundBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "portal.inbound", patient_id=body.patient_id)
    msg = portal_messages.post_inbound(hospital_id=hospital_id, patient_id=body.patient_id, body=body.body, sender_name=body.sender_name)
    # Auto-attach AI draft for the clinician to review
    draft = inbox_drafts.draft_reply(body.body, hospital_name="our clinic")
    portal_messages.attach_ai_draft(msg["id"], draft.get("draft", ""))
    msg["ai_draft"] = draft.get("draft")
    msg["ai_draft_red_flags"] = draft.get("red_flags")
    return msg


@router.get("/portal/threads")
def portal_thread_list(
    hospital_id: str = Path(...),
    only_unread: bool = False,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "portal.thread_list")
    return {"threads": portal_messages.list_threads(hospital_id, only_unread=only_unread)}


@router.get("/portal/thread/{thread_key}")
def portal_thread(
    hospital_id: str = Path(...),
    thread_key: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "portal.thread_view", patient_id=thread_key)
    return {"messages": portal_messages.get_thread(thread_key)}


class PortalRespondBody(BaseModel):
    message_id: str
    body: str
    ai_draft_status: str = "edited"


@router.post("/portal/respond")
def portal_respond(
    hospital_id: str = Path(...),
    body: PortalRespondBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "portal.respond", patient_id=body.message_id)
    result = portal_messages.respond(
        body.message_id,
        clinician_id=caller.get("clinician_id", "unknown"),
        body=body.body,
        ai_draft_status=body.ai_draft_status,
    )
    if not result:
        raise HTTPException(status_code=404, detail="message not found")
    return result


# ---- Nurse triage --------------------------------------------------------------
class NurseTriageBody(BaseModel):
    protocol_key: str
    answers: dict[str, Any]


@router.post("/nurse-triage/evaluate")
def nurse_triage_evaluate(
    hospital_id: str = Path(...),
    body: NurseTriageBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "nurse_triage.evaluate", patient_id=body.protocol_key)
    try:
        return nurse_triage.evaluate(body.protocol_key, body.answers)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not evaluate triage protocol: {e}")


@router.get("/nurse-triage/protocols")
def nurse_triage_list(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "nurse_triage.list_protocols")
    return {"protocols": nurse_triage.list_protocols()}


# ---- TEFCA QHIN ----------------------------------------------------------------
class TefcaQueryBody(BaseModel):
    patient_name: str
    patient_dob: str
    consent_attestation: bool = False


@router.post("/tefca/query")
def tefca_query(
    hospital_id: str = Path(...),
    body: TefcaQueryBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "tefca.query")
    try:
        return tefca_qhin.query(
            patient_name=body.patient_name,
            patient_dob=body.patient_dob,
            consent_attestation=body.consent_attestation,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not run TEFCA query: {e}")


# ---- Telehealth ----------------------------------------------------------------
class TelehealthBody(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: str  # doxy | zoom | teams | doximity


@router.post("/telehealth/session")
def telehealth_session(
    hospital_id: str = Path(...),
    body: TelehealthBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "telehealth.session")
    payload = body.model_dump()
    provider = payload.pop("provider", None)
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    try:
        return telehealth.make_session(provider=provider, **payload)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not create telehealth session: {e}")


# ---- Abnormal-result loop closure ----------------------------------------------
class AbnormalResultsBody(BaseModel):
    results: list[dict[str, Any]]


@router.post("/results/detect-abnormal")
def results_detect_abnormal(
    hospital_id: str = Path(...),
    body: AbnormalResultsBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Deterministically pick the abnormal results out of a lab/imaging panel."""
    audit(caller, "results.detect_abnormal")
    try:
        abnormal = followups.detect_abnormal_results(body.results)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not detect abnormal results: {e}")
    return {"count": len(abnormal), "abnormal_results": abnormal}


class ResultsReviewBody(BaseModel):
    abnormal_results: list[dict[str, Any]]
    reading_level: str = "standard"
    language: str = "en"


@router.post("/results/review")
def results_review(
    hospital_id: str = Path(...),
    body: ResultsReviewBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Draft plain-language patient messages for a batch of abnormal results."""
    audit(caller, "results.review")
    try:
        return followups.review_results(
            body.abnormal_results,
            reading_level=body.reading_level,
            language=body.language,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not review results: {e}")


class ClosureNewBody(BaseModel):
    patient_id: str
    result: dict[str, Any]
    detected_by: str = "system"


@router.post("/results/closures")
def results_closure_new(
    hospital_id: str = Path(...),
    body: ClosureNewBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Open a fresh loop closure (state 'outstanding') for one abnormal result."""
    audit(caller, "results.closure_new", patient_id=body.patient_id)
    try:
        return followups.new_closure(
            patient_id=body.patient_id,
            result=body.result,
            detected_by=body.detected_by,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not create closure: {e}")


class ClosureAdvanceBody(BaseModel):
    closure: dict[str, Any]
    to_state: str
    actor: str = "clinician"
    note: str = ""
    patient_message: str | None = None


@router.post("/results/closures/advance")
def results_closure_advance(
    hospital_id: str = Path(...),
    body: ClosureAdvanceBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Advance a loop closure to a new (forward-only) state. Returns the new
    closure snapshot the caller persists."""
    audit(caller, "results.closure_advance", patient_id=str(body.closure.get("closure_id", "")))
    try:
        return followups.advance_closure(
            body.closure,
            to_state=body.to_state,
            actor=body.actor,
            note=body.note,
            patient_message=body.patient_message,
        )
    except followups.ClosureTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not advance closure: {e}")


class ClosureSummaryBody(BaseModel):
    closures: list[dict[str, Any]]


@router.post("/results/closures/summary")
def results_closure_summary(
    hospital_id: str = Path(...),
    body: ClosureSummaryBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Roll a list of closures into dashboard counts plus the open work queue."""
    audit(caller, "results.closure_summary")
    try:
        return followups.closure_summary(body.closures)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not summarize closures: {e}")


# ---- Bias audits ---------------------------------------------------------------
class EwsBiasAuditBody(BaseModel):
    cohort: list[dict[str, Any]]
    strata: list[str] = ["sex", "age_group", "race", "language"]
    score_fn: str = "sepsis_ews"
    disparity_threshold: float = 0.15


@router.post("/early-warning/bias-audit")
def early_warning_bias_audit(
    hospital_id: str = Path(...),
    body: EwsBiasAuditBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Recompute early-warning scores across demographic strata and flag
    subgroup disparities for human review."""
    audit(caller, "early_warning.bias_audit")
    try:
        return early_warning.bias_audit(
            body.cohort,
            strata=tuple(body.strata),
            score_fn=body.score_fn,
            disparity_threshold=body.disparity_threshold,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid early-warning bias audit input: {e}")


class SepsisBiasAuditBody(BaseModel):
    encounters: list[dict[str, Any]]
    strata: list[str] = ["sex", "age_group", "race", "language"]
    disparity_threshold: float = 0.15


@router.post("/sepsis/bundle/bias-audit")
def sepsis_bundle_bias_audit(
    hospital_id: str = Path(...),
    body: SepsisBiasAuditBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Audit 1-hour sepsis-bundle compliance for disparities across demographic
    strata and flag flagged subgroups for investigation."""
    audit(caller, "sepsis.bundle.bias_audit")
    try:
        return sepsis_bundle.bias_audit(
            body.encounters,
            strata=tuple(body.strata),
            disparity_threshold=body.disparity_threshold,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid sepsis bias audit input: {e}")


# ---- Detailed discharge plan ---------------------------------------------------
class DetailedDischargeBody(BaseModel):
    condition: str = ""
    clinician_note: str = ""
    scribe_note: str = ""
    transcript: str = ""
    assessment: str = ""
    patient_language: str = "en"
    hospital_name: str = "your clinic"
    follow_up: str = ""


@router.post("/discharge/detailed-plan")
def discharge_detailed_plan(
    hospital_id: str = Path(...),
    body: DetailedDischargeBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Deep, condition-specific discharge plan with sectioned instructions and
    tiered (911 / ED / call-office) return precautions."""
    audit(caller, "discharge.detailed_plan")
    try:
        return discharge_plan.build_detailed_discharge_plan(
            condition=body.condition,
            clinician_note=body.clinician_note,
            scribe_note=body.scribe_note,
            transcript=body.transcript,
            assessment=body.assessment,
            patient_language=body.patient_language,
            hospital_name=body.hospital_name,
            follow_up=body.follow_up,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not build discharge plan: {e}")


# ---- Workup with safety check --------------------------------------------------
class WorkupSafetyBody(BaseModel):
    transcript: str
    esi_level: int
    differential: list[dict[str, Any]] = []
    medical_info: dict[str, Any] | None = None
    vitals: dict[str, Any] | None = None


@router.post("/workup/safety-check")
def workup_safety_check(
    hospital_id: str = Path(...),
    body: WorkupSafetyBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Generate a workup order set plus a deterministic contraindication pass."""
    audit(caller, "workup.safety_check")
    try:
        return workup.generate_with_safety_check(
            body.transcript,
            body.esi_level,
            body.differential,
            body.medical_info,
            body.vitals,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"could not generate workup: {e}")
