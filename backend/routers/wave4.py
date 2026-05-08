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
    fax_intake,
    fhir_writer,
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
    result = hl7_v2.send_mllp(body.host, body.port, s)
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
    return multi_encounter.stitch(body.notes)


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
    return multi_encounter.parse_huddle(body.transcript, ward_context=body.ward_context)


# ---- Fax intake -----------------------------------------------------------------
@router.post("/fax/intake")
async def fax_intake_endpoint(
    hospital_id: str = Path(...),
    file: UploadFile = File(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "fax.intake")
    blob = await file.read()
    ct = file.content_type or "application/octet-stream"
    if "pdf" in ct.lower():
        return fax_intake.parse_pdf_bytes(blob)
    if ct.lower().startswith("image/"):
        return fax_intake.parse_image_b64(base64.b64encode(blob).decode("ascii"), content_type=ct)
    # text fallback
    try:
        text = blob.decode("utf-8", errors="ignore")
        return fax_intake.parse_text(text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"unrecognized content type: {e}")


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
    return sepsis_bundle.evaluate_encounter(**body.model_dump())


class SepsisCohortBody(BaseModel):
    evaluations: list[dict[str, Any]]


@router.post("/sepsis/bundle/cohort")
def sepsis_bundle_cohort(
    hospital_id: str = Path(...),
    body: SepsisCohortBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    return sepsis_bundle.cohort_summary(body.evaluations)


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
    return cohort_export.poll(content_location)


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
    return cohort_export.cohort_query(
        condition_icd10=body.condition_icd10,
        lab_loinc_above=body.lab_loinc_above,
        age_band=body.age_band,
    )


# ---- Insurance OCR -> eligibility chain -----------------------------------------
@router.post("/insurance/ocr-to-eligibility")
async def insurance_chain(
    hospital_id: str = Path(...),
    file: UploadFile = File(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "insurance.ocr_to_eligibility")
    blob = await file.read()
    return insurance_to_eligibility.chain(image_bytes=blob)


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
        r = fhir_writer.write(resource)
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
    return style_learning.style_profile(caller.get("clinician_id", "unknown"))


@router.get("/style/training-jsonl")
def style_export_jsonl(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
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
    return {"threads": portal_messages.list_threads(hospital_id, only_unread=only_unread)}


@router.get("/portal/thread/{thread_key}")
def portal_thread(
    hospital_id: str = Path(...),
    thread_key: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
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
    audit(caller, "portal.respond")
    return portal_messages.respond(
        body.message_id,
        clinician_id=caller.get("clinician_id", "unknown"),
        body=body.body,
        ai_draft_status=body.ai_draft_status,
    ) or {"error": "message not found"}


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
    return nurse_triage.evaluate(body.protocol_key, body.answers)


@router.get("/nurse-triage/protocols")
def nurse_triage_list(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
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
    return tefca_qhin.query(
        patient_name=body.patient_name,
        patient_dob=body.patient_dob,
        consent_attestation=body.consent_attestation,
    )


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
    provider = payload.pop("provider")
    return telehealth.make_session(provider=provider, **payload)
