"""Clinician-side AI endpoints — scribe, Ddx v2, CDS calculators, screeners,
E&M coding, letters, inbox draft, refill triage, PA packets, drug check,
abnormal-result triage, multi-language discharge plan.

Every endpoint requires clinician auth. Every AI write logs an override entry
on the next clinician decision (accept/edit/reject) via /override.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

from db import storage
from lib import provenance
from lib.auth import audit, require_clinician
from services import (
    ambient_scribe,
    cds_calculators,
    ddx_v2,
    discharge_plan,
    drug_interactions,
    early_warning,
    evidence_rag,
    handoff,
    hcc_capture,
    redaction,
    em_coding,
    inbox_drafts,
    letters,
    pa_packets,
    patient_education,
    refills,
    screeners,
    specialty_packs,
)

log = logging.getLogger(__name__)

router = APIRouter()


# ---- Ambient scribe ---------------------------------------------------------------
class ScribeFromTranscriptBody(BaseModel):
    transcript: str = Field(..., min_length=10)
    refine: bool = True


@router.post("/scribe/from-transcript")
def scribe_from_transcript(
    hospital_id: str = Path(...),
    body: ScribeFromTranscriptBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.from_transcript")
    structured = ambient_scribe.synthesize_from_transcript(body.transcript)
    if body.refine and structured.get("sections"):
        structured = ambient_scribe.refine(structured)
    soap = ambient_scribe.to_soap_text(structured)
    return {"structured": structured, "soap_text": soap}


class HealthScribeStartBody(BaseModel):
    audio_s3_uri: str
    output_s3_bucket: str


@router.post("/scribe/healthscribe/start")
def scribe_healthscribe_start(
    hospital_id: str = Path(...),
    body: HealthScribeStartBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.healthscribe.start")
    return ambient_scribe.start_healthscribe_job(body.audio_s3_uri, f"s3://{body.output_s3_bucket}/")


@router.get("/scribe/healthscribe/poll/{job_name}")
def scribe_healthscribe_poll(
    hospital_id: str = Path(...),
    job_name: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.healthscribe.poll", patient_id=job_name)
    return ambient_scribe.poll_healthscribe_job(job_name)


# ---- Ddx v2 -----------------------------------------------------------------------
class DdxV2Body(BaseModel):
    transcript: str = Field(..., min_length=10)
    chief_complaint: str = ""
    specialty: str = "ed"
    medical_info: dict[str, Any] | None = None
    vitals: dict[str, Any] | None = None


@router.post("/ddx/v2")
def ddx_v2_endpoint(
    hospital_id: str = Path(...),
    body: DdxV2Body = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ddx.v2")
    return ddx_v2.generate(
        body.transcript,
        body.chief_complaint,
        medical_info=body.medical_info,
        specialty=body.specialty,
        vitals=body.vitals,
    )


# ---- CDS calculators -------------------------------------------------------------
@router.get("/cds/calculators")
def cds_list(hospital_id: str = Path(...), caller: dict = Depends(require_clinician)) -> dict[str, Any]:
    return {"calculators": cds_calculators.list_calculators()}


class CalcBody(BaseModel):
    key: str
    inputs: dict[str, Any]


@router.post("/cds/calculate")
def cds_calc(
    hospital_id: str = Path(...),
    body: CalcBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "cds.calculate", patient_id=body.key)
    return cds_calculators.calculate(body.key, body.inputs)


class CalcAutoBody(BaseModel):
    transcript: str
    chief_complaint: str = ""
    calc_keys: list[str] | None = None


@router.post("/cds/auto-extract")
def cds_auto(
    hospital_id: str = Path(...),
    body: CalcAutoBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "cds.auto_extract")
    return cds_calculators.auto_extract(body.transcript, body.chief_complaint, body.calc_keys)


# ---- Screeners --------------------------------------------------------------------
@router.get("/screeners")
def screeners_list(hospital_id: str = Path(...), caller: dict = Depends(require_clinician)) -> dict[str, Any]:
    return {"screeners": screeners.list_screeners()}


class ScreenBody(BaseModel):
    key: str
    items: list[int] | None = None
    answers: dict[str, Any] | None = None
    sex: str | None = None


@router.post("/screeners/score")
def screen_score(
    hospital_id: str = Path(...),
    body: ScreenBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "screener.score", patient_id=body.key)
    payload: dict[str, Any] = {}
    if body.items is not None:
        payload["items"] = body.items
    if body.answers is not None:
        payload["answers"] = body.answers
    if body.sex is not None:
        payload["sex"] = body.sex
    return screeners.score(body.key, payload)


class ScreenAutoBody(BaseModel):
    transcript: str
    keys: list[str]


@router.post("/screeners/auto-extract")
def screen_auto(
    hospital_id: str = Path(...),
    body: ScreenAutoBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "screener.auto_extract")
    return screeners.auto_extract(body.transcript, body.keys)


# ---- E&M + ICD-10 + CPT -----------------------------------------------------------
class CodingBody(BaseModel):
    note_text: str
    established_patient: bool = True


@router.post("/coding/suggest")
def coding_suggest(
    hospital_id: str = Path(...),
    body: CodingBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "coding.suggest")
    return em_coding.suggest(body.note_text, established_patient=body.established_patient)


# ---- Letters ----------------------------------------------------------------------
@router.get("/letters/templates")
def letters_list(hospital_id: str = Path(...), caller: dict = Depends(require_clinician)) -> dict[str, Any]:
    return {"templates": letters.list_templates()}


class LetterFillBody(BaseModel):
    template_key: str
    chart_context: dict[str, Any] = {}


@router.post("/letters/auto-fill")
def letters_autofill(
    hospital_id: str = Path(...),
    body: LetterFillBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "letters.autofill", patient_id=body.template_key)
    slots = letters.ai_fill_slots(body.template_key, body.chart_context)
    text = letters.render_text(body.template_key, slots)
    return {"slots": slots, "rendered": text}


class LetterRenderBody(BaseModel):
    template_key: str
    slots: dict[str, str]


@router.post("/letters/render")
def letters_render(
    hospital_id: str = Path(...),
    body: LetterRenderBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    text = letters.render_text(body.template_key, body.slots)
    return {"rendered": text}


@router.post("/letters/pdf")
def letters_pdf(
    hospital_id: str = Path(...),
    body: LetterRenderBody = ...,
    caller: dict = Depends(require_clinician),
) -> Response:
    audit(caller, "letters.pdf", patient_id=body.template_key)
    pdf = letters.to_pdf(body.template_key, body.slots)
    return Response(content=pdf, media_type="application/pdf")


# ---- Inbox auto-draft & abnormal-result triage -----------------------------------
class InboxDraftBody(BaseModel):
    inbound_message: str
    patient_chart: dict[str, Any] | None = None
    hospital_name: str = "our clinic"


@router.post("/inbox/draft")
def inbox_draft(
    hospital_id: str = Path(...),
    body: InboxDraftBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "inbox.draft")
    return inbox_drafts.draft_reply(
        body.inbound_message,
        patient_chart=body.patient_chart,
        hospital_name=body.hospital_name,
    )


class AbnormalResultBody(BaseModel):
    lab_name: str
    value: float
    recommended_action: str = ""


@router.post("/inbox/result-draft")
def inbox_result(
    hospital_id: str = Path(...),
    body: AbnormalResultBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "inbox.result_draft")
    return inbox_drafts.draft_result_message(
        body.lab_name,
        body.value,
        recommended_action=body.recommended_action,
    )


# ---- Refill triage ---------------------------------------------------------------
class RefillBody(BaseModel):
    medication_canonical: str
    last_visit_iso: str | None = None
    relevant_lab_iso: str | None = None
    relevant_lab_value: float | None = None
    recent_hospitalization: bool = False


@router.post("/refills/triage")
def refills_triage(
    hospital_id: str = Path(...),
    body: RefillBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "refills.triage", patient_id=body.medication_canonical)
    return refills.triage(
        body.medication_canonical,
        last_visit_iso=body.last_visit_iso,
        relevant_lab_iso=body.relevant_lab_iso,
        relevant_lab_value=body.relevant_lab_value,
        recent_hospitalization=body.recent_hospitalization,
    )


# ---- Prior auth packet ----------------------------------------------------------
class PaBody(BaseModel):
    note_text: str
    diagnosis: str
    icd10: str
    requested_service: str
    cpt_or_hcpcs_or_ndc: str
    patient: dict[str, Any]
    payer: dict[str, Any]
    provider: dict[str, Any]


@router.post("/pa/packet")
def pa_packet(
    hospital_id: str = Path(...),
    body: PaBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "pa.packet")
    packet = pa_packets.assemble_packet(
        note_text=body.note_text,
        diagnosis=body.diagnosis,
        icd10=body.icd10,
        requested_service=body.requested_service,
        cpt_or_hcpcs_or_ndc=body.cpt_or_hcpcs_or_ndc,
        patient=body.patient,
        payer=body.payer,
        provider=body.provider,
    )
    claim = pa_packets.to_da_vinci_claim(packet)
    return {"packet": packet, "fhir_claim": claim}


# ---- Drug interaction check (encounter-gated) -----------------------------------
class DrugCheckBody(BaseModel):
    meds: list[str]
    allergies: list[str] = []
    egfr: float | None = None
    complaint: str = ""


@router.post("/drug-check")
def drug_check(
    hospital_id: str = Path(...),
    body: DrugCheckBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "drug.check")
    return drug_interactions.check(
        body.meds,
        allergies=body.allergies,
        egfr=body.egfr,
        complaint=body.complaint,
    )


# ---- Multi-language discharge plan ----------------------------------------------
class DischargeBody(BaseModel):
    clinician_note: str = ""
    scribe_note: str = ""
    transcript: str = ""
    assessment: str = ""
    patient_language: str = "en"
    follow_up: str = ""


@router.post("/discharge/build")
def discharge_build(
    hospital_id: str = Path(...),
    body: DischargeBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "discharge.build")
    hospital = storage.get_hospital(hospital_id) or {}
    return discharge_plan.build_discharge_plan(
        clinician_note=body.clinician_note,
        scribe_note=body.scribe_note,
        transcript=body.transcript,
        assessment=body.assessment,
        patient_language=body.patient_language,
        hospital_name=hospital.get("name", "your clinic"),
        follow_up=body.follow_up,
    )


# ---- Specialty packs ------------------------------------------------------------
@router.get("/specialty/packs")
def specialty_list(hospital_id: str = Path(...), caller: dict = Depends(require_clinician)) -> dict[str, Any]:
    return {"packs": specialty_packs.list_packs()}


@router.get("/specialty/pack/{key}")
def specialty_get(
    hospital_id: str = Path(...),
    key: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    pack = specialty_packs.get_pack(key)
    if not pack:
        raise HTTPException(status_code=404, detail="unknown specialty pack")
    return pack


# ---- AI override audit ----------------------------------------------------------
class OverrideBody(BaseModel):
    purpose: str
    model_name: str = "claude-sonnet-4-5"
    decision: str  # accepted | edited | rejected
    patient_id: str = ""
    diff_chars: int = 0
    notes: str = ""


@router.post("/ai-override")
def ai_override(
    hospital_id: str = Path(...),
    body: OverrideBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    provenance.record_override(
        purpose=body.purpose,
        model_name=body.model_name,
        decision=body.decision,
        clinician_id=caller.get("clinician_id", "unknown"),
        patient_id=body.patient_id,
        hospital_id=hospital_id,
        diff_chars=body.diff_chars,
        notes=body.notes,
    )
    return {"ok": True}


@router.get("/ai-override/metrics")
def ai_override_metrics(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    return provenance.metrics(hospital_id)


# ---- Evidence-grounded RAG -------------------------------------------------------
class EvidenceBody(BaseModel):
    question: str
    k: int = 6


@router.post("/evidence/answer")
def evidence_answer(
    hospital_id: str = Path(...),
    body: EvidenceBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "evidence.answer")
    return evidence_rag.answer(body.question, k=body.k)


@router.get("/evidence/search")
def evidence_search(
    hospital_id: str = Path(...),
    q: str = "",
    k: int = 6,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "evidence.search")
    return {"snippets": evidence_rag.search(q, k=k)}


# ---- Sepsis EWS + Deterioration Index -------------------------------------------
class SepsisBody(BaseModel):
    hr: float | None = None
    rr: float | None = None
    temp_c: float | None = None
    sbp: float | None = None
    map_mm_hg: float | None = None
    mental_status: str | None = None
    spo2: float | None = None
    on_oxygen: bool = False
    wbc: float | None = None
    lactate: float | None = None
    suspected_infection: bool = False


@router.post("/ews/sepsis")
def ews_sepsis(
    hospital_id: str = Path(...),
    body: SepsisBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ews.sepsis")
    return early_warning.sepsis_ews(**body.model_dump())


class DeteriorationBody(BaseModel):
    vitals_now: dict[str, float]
    vitals_4h_ago: dict[str, float] | None = None
    new_oxygen_requirement: bool = False
    gcs_drop_at_least_2: bool = False
    new_arrhythmia: bool = False
    wbc_now: float | None = None
    wbc_baseline: float | None = None


@router.post("/ews/deterioration")
def ews_deterioration(
    hospital_id: str = Path(...),
    body: DeteriorationBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ews.deterioration")
    return early_warning.deterioration_index(**body.model_dump())


# ---- HCC capture (MA recapture) -------------------------------------------------
class HccBody(BaseModel):
    conditions: list[dict[str, str]]
    prior_notes: list[str] = []
    current_year: int | None = None


@router.post("/hcc/evaluate")
def hcc_evaluate(
    hospital_id: str = Path(...),
    body: HccBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "hcc.evaluate")
    return hcc_capture.evaluate_chart(
        conditions=body.conditions,
        prior_notes=body.prior_notes,
        current_year=body.current_year,
    )


# ---- I-PASS / SBAR handoffs ----------------------------------------------------
class HandoffBody(BaseModel):
    chart_context: dict[str, Any]


@router.post("/handoff/ipass")
def handoff_ipass(
    hospital_id: str = Path(...),
    body: HandoffBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "handoff.ipass")
    return handoff.ipass(body.chart_context)


class SbarBody(BaseModel):
    chart_context: dict[str, Any]
    consult_specialty: str = "cardiology"
    reason: str = ""


@router.post("/handoff/sbar")
def handoff_sbar(
    hospital_id: str = Path(...),
    body: SbarBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "handoff.sbar")
    return handoff.sbar(body.chart_context, consult_specialty=body.consult_specialty, reason=body.reason)


# ---- Auto-redaction + closed-loop result tracking ------------------------------
class RedactBody(BaseModel):
    segments: list[dict[str, Any]]


@router.post("/scribe/redact")
def scribe_redact(
    hospital_id: str = Path(...),
    body: RedactBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.redact")
    return redaction.redact_segments(body.segments)


class OpenLoopBody(BaseModel):
    patient_id: str
    test_name: str
    value: str
    severity: str = "abnormal"  # abnormal | critical
    sla_days: int = 7


@router.post("/result-loop/open")
def result_loop_open(
    hospital_id: str = Path(...),
    body: OpenLoopBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "result_loop.open", patient_id=body.patient_id)
    return redaction.open_loop(
        patient_id=body.patient_id,
        clinician_id=caller.get("clinician_id", "unknown"),
        hospital_id=hospital_id,
        test_name=body.test_name,
        value=body.value,
        severity=body.severity,
        sla_days=body.sla_days,
    )


class CloseLoopBody(BaseModel):
    tracking_id: str
    action: str


@router.post("/result-loop/close")
def result_loop_close(
    hospital_id: str = Path(...),
    body: CloseLoopBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "result_loop.close", patient_id=body.tracking_id)
    return redaction.close_loop(body.tracking_id, closed_by=caller.get("clinician_id", "unknown"), action=body.action)


@router.get("/result-loop/overdue")
def result_loop_overdue(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    return {"items": redaction.overdue_worklist(hospital_id)}


# ---- Ambient scribe — chunked pause/resume recording sessions -------------------
class ScribeSessionStartBody(BaseModel):
    specialty: str | None = None
    session_id: str | None = None


@router.post("/scribe/session/start")
def scribe_session_start(
    hospital_id: str = Path(...),
    body: ScribeSessionStartBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.session.start")
    return ambient_scribe.start_session(specialty=body.specialty, session_id=body.session_id)


class ScribeChunkBody(BaseModel):
    session_id: str
    chunk: str = Field(..., min_length=1)


@router.post("/scribe/session/append")
def scribe_session_append(
    request: Request,
    hospital_id: str = Path(...),
    body: ScribeChunkBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.session.append", patient_id=body.session_id)
    result = ambient_scribe.append_transcript_chunk(body.session_id, body.chunk)
    if result.get("status") == "unknown_session":
        raise HTTPException(status_code=404, detail="unknown scribe session")
    return result


class ScribeSessionBody(BaseModel):
    session_id: str


@router.post("/scribe/session/pause")
def scribe_session_pause(
    hospital_id: str = Path(...),
    body: ScribeSessionBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.session.pause", patient_id=body.session_id)
    result = ambient_scribe.pause_session(body.session_id)
    if result.get("status") == "unknown_session":
        raise HTTPException(status_code=404, detail="unknown scribe session")
    return result


@router.post("/scribe/session/resume")
def scribe_session_resume(
    hospital_id: str = Path(...),
    body: ScribeSessionBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.session.resume", patient_id=body.session_id)
    result = ambient_scribe.resume_session(body.session_id)
    if result.get("status") == "unknown_session":
        raise HTTPException(status_code=404, detail="unknown scribe session")
    return result


class ScribeFinalizeBody(BaseModel):
    session_id: str
    refine_note: bool = True


@router.post("/scribe/session/finalize")
def scribe_session_finalize(
    request: Request,
    hospital_id: str = Path(...),
    body: ScribeFinalizeBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.session.finalize", patient_id=body.session_id)
    structured = ambient_scribe.finalize_session(
        body.session_id,
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        refine_note=body.refine_note,
    )
    error = structured.get("error")
    if error == "unknown_session":
        raise HTTPException(status_code=404, detail="unknown scribe session")
    if error == "empty_session":
        raise HTTPException(status_code=400, detail="scribe session has no transcript")
    soap = ambient_scribe.to_soap_text(structured)
    return {"structured": structured, "soap_text": soap}


class ScribeRegenerateBody(BaseModel):
    structured: dict[str, Any]
    section_name: str = Field(..., min_length=1)
    specialty: str | None = None


@router.post("/scribe/regenerate-section")
def scribe_regenerate_section(
    hospital_id: str = Path(...),
    body: ScribeRegenerateBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.regenerate_section")
    structured = ambient_scribe.regenerate_section(
        body.structured, body.section_name, specialty=body.specialty
    )
    soap = ambient_scribe.to_soap_text(structured)
    return {"structured": structured, "soap_text": soap}


# ---- Prior auth — Da Vinci bundle, human packet, appeal, completeness -----------
class PaPacketBody(BaseModel):
    packet: dict[str, Any]


@router.post("/pa/da-vinci-bundle")
def pa_da_vinci_bundle(
    hospital_id: str = Path(...),
    body: PaPacketBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "pa.da_vinci_bundle")
    return pa_packets.to_da_vinci_bundle(body.packet)


@router.post("/pa/human-packet")
def pa_human_packet(
    hospital_id: str = Path(...),
    body: PaPacketBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "pa.human_packet")
    return pa_packets.to_human_packet(body.packet)


@router.post("/pa/completeness")
def pa_completeness(
    hospital_id: str = Path(...),
    body: PaPacketBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "pa.completeness")
    return pa_packets.check_completeness(body.packet)


class PaAppealBody(BaseModel):
    packet: dict[str, Any]
    denial_reason: str = Field(..., min_length=1)
    denial_category: str | None = None
    denial_date: str | None = None
    appeal_level: str = "first"
    additional_context: str = ""


@router.post("/pa/appeal")
def pa_appeal(
    hospital_id: str = Path(...),
    body: PaAppealBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "pa.appeal")
    return pa_packets.generate_appeal(
        body.packet,
        denial_reason=body.denial_reason,
        denial_category=body.denial_category,
        denial_date=body.denial_date,
        appeal_level=body.appeal_level,
        additional_context=body.additional_context,
    )


# ---- Letters — categories, one-shot generate, batch -----------------------------
@router.get("/letters/categories")
def letters_categories(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    return {"categories": letters.list_categories()}


class LetterGenerateBody(BaseModel):
    template_key: str
    chart_context: dict[str, Any] = {}
    slot_overrides: dict[str, str] | None = None


@router.post("/letters/generate")
def letters_generate(
    hospital_id: str = Path(...),
    body: LetterGenerateBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "letters.generate", patient_id=body.template_key)
    return letters.generate_letter(
        body.template_key, body.chart_context, body.slot_overrides
    )


class LetterBatchBody(BaseModel):
    requests: list[dict[str, Any]]
    chart_context: dict[str, Any] = {}


@router.post("/letters/batch")
def letters_batch(
    hospital_id: str = Path(...),
    body: LetterBatchBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "letters.batch")
    return {"letters": letters.generate_batch(body.requests, body.chart_context)}


# ---- Patient education handouts -------------------------------------------------
class HandoutBody(BaseModel):
    condition: str = Field(..., min_length=1)
    patient_context: str = ""
    reading_level: str = "standard"
    patient_language: str = "en"


@router.post("/education/handout")
def education_handout(
    hospital_id: str = Path(...),
    body: HandoutBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "education.handout", patient_id=body.condition)
    return patient_education.generate_handout(
        body.condition,
        patient_context=body.patient_context,
        reading_level=body.reading_level,
        patient_language=body.patient_language,
    )


class HandoutBatchBody(BaseModel):
    conditions: list[Any]
    reading_level: str = "standard"
    patient_language: str = "en"


@router.post("/education/handout-batch")
def education_handout_batch(
    hospital_id: str = Path(...),
    body: HandoutBatchBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "education.handout_batch")
    return {
        "handouts": patient_education.generate_handout_batch(
            body.conditions,
            reading_level=body.reading_level,
            patient_language=body.patient_language,
        )
    }


# ---- Evidence-grounded recommendation verification ------------------------------
class EvidenceGroundBody(BaseModel):
    recommendation: str = Field(..., min_length=1)
    context: str = ""
    k: int = 6


@router.post("/evidence/ground")
def evidence_ground(
    hospital_id: str = Path(...),
    body: EvidenceGroundBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "evidence.ground")
    return evidence_rag.ground(body.recommendation, body.context, k=body.k)
