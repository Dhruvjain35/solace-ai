"""POST /api/{hospital_id}/intake — the full magic loop, called after /transcribe."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Path, Request, UploadFile

from db import media, storage
from db.constants import STATUS_WAITING
from lib import ai_log, async_invoke, blocklist, content_guard, idempotency, quota, uploads

CONSENT_VERSION_CURRENT = "1.0"
from lib.fallbacks import ESI_LABELS, GENERIC_PATIENT_EXPLANATION
from services import (
    care_routing,
    intake_artifacts,
    transcription,
    triage,
    triage_rules,
    vision,
)
from services.workflows import engine as workflow_engine


def _source_ip(req: Request | None) -> str | None:
    if req is None:
        return None
    return req.headers.get("x-forwarded-for", req.client.host if req.client else None)

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/intake")
async def create_intake(
    hospital_id: str = Path(...),
    audio_file: UploadFile | None = File(None),
    image_file: UploadFile | None = File(None),
    patient_name: str = Form(..., max_length=200),
    pre_transcribed_text: str | None = Form(None, max_length=20_000),
    # New: structured fields (JSON-encoded arrays/objects)
    medical_info: str | None = Form(None, max_length=50_000),
    followup_qa: str | None = Form(None, max_length=50_000),
    insurance_info: str | None = Form(None, max_length=10_000),
    intake_token: str | None = Form(None, max_length=256),
    idempotency_key: str | None = Form(None, max_length=128),
    consent_granted: str | None = Form(None, max_length=16),
    consent_version: str | None = Form(None, max_length=16),
    preferred_language: str | None = Form(None, max_length=16),
    # EHR auto-pop carry-through: when the patient was matched to a FHIR Patient
    # at intake time, pass that id forward so the clinician-side EHR lookup can
    # fetch the same record by id rather than re-searching by name.
    ehr_fhir_id: str | None = Form(None, max_length=128),
    ehr_match_source: str | None = Form(None, max_length=64),
    request: Request = None,
) -> dict[str, Any]:
    src_ip = _source_ip(request)
    ua = request.headers.get("user-agent") if request else None
    identity = quota.identity_of(src_ip, ua)

    # Auto-block check FIRST — short-circuits identities flagged as abusive
    blocklist.enforce(identity, source_ip=src_ip)

    # HIPAA consent gate — §164.508 requires explicit authorization before PHI
    # flows to AI processors (AWS Bedrock / Transcribe / Polly).
    if str(consent_granted or "").lower() not in {"true", "1", "yes"}:
        from lib import audit as _audit  # noqa: PLC0415

        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.intake_no_consent",
            source_ip=src_ip, status_code=403,
            extra={"identity": identity},
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Consent required. You must agree to AI processing of your voice, symptoms,"
                " and photos before submitting intake."
            ),
        )

    # Start an AI-processing log for this patient's request. Services append to it;
    # we serialize onto the patient record at the end.
    ai_log.new_log()

    # Idempotency — network retries hitting with the same key return the cached response
    # instead of creating duplicate patients + re-running the Claude pipeline.
    if not idempotency_key and request is not None:
        idempotency_key = request.headers.get("idempotency-key")
    if idempotency_key:
        cached = idempotency.get_cached(idempotency_key, scope="intake")
        if cached:
            log.info("intake: idempotency replay for key %s", idempotency_key[:8])
            return cached

    # Intake nonce check — binds to caller IP + User-Agent (see lib/intake_nonce.py)
    from lib import intake_nonce  # noqa: PLC0415

    intake_nonce.require(hospital_id, intake_token, source_ip=src_ip, user_agent=ua)

    # Identity-bound request quota (second layer on top of API GW per-route throttle)
    quota.check_and_consume(identity, "intake.submit", source_ip=src_ip)

    hospital = storage.get_hospital(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail=f"Unknown hospital '{hospital_id}'")

    patient_id = str(uuid.uuid4())

    # 1. Resolve transcript (either pre-transcribed from /transcribe step or record fresh).
    # Honor the patient's selected language — Whisper will still auto-detect but the
    # patient's self-reported preference wins for downstream Claude + TTS responses.
    selected_lang = (preferred_language or "en").strip().lower()[:2] or "en"
    if pre_transcribed_text:
        transcript_text = pre_transcribed_text.strip()
        language = selected_lang
        # Pre-typed text path bypasses Whisper, but still needs abuse scanning
        ok, cleaned, findings = content_guard.scan(
            transcript_text, label="intake.pre_transcribed", source_ip=src_ip, user_agent=ua
        )
        if not ok:
            raise HTTPException(status_code=422, detail="content rejected by abuse scanner")
        transcript_text = cleaned
    else:
        if not audio_file:
            raise HTTPException(status_code=400, detail="audio_file or pre_transcribed_text is required")
        audio_bytes = await uploads.read_and_validate(audio_file, "audio", source_ip=src_ip)
        # Duration-based cost guard — prevents a valid user from queueing 2 min of audio
        # in an 8MB silent file and hammering Whisper.
        duration = getattr(audio_file, "duration_seconds", 0.0) or 0.0
        quota.check_audio_duration(duration, identity, source_ip=src_ip)
        try:
            t = transcription.transcribe(audio_bytes, filename=audio_file.filename or "audio.webm")
            transcript_text = t.text
            # Prefer the patient's selected language; fall back to Whisper detection
            language = selected_lang or t.language
        except transcription.TranscriptionError as e:
            # The exception text can carry transcript fragments / provider
            # diagnostics — log server-side, return a static client message.
            log.warning("intake: transcription failed: %s", e)
            raise HTTPException(status_code=503, detail="Voice transcription is temporarily unavailable. Please try again.")
        # Post-transcription abuse scan — catches prompt injection spoken into the mic
        ok, cleaned, findings = content_guard.scan(
            transcript_text, label="intake.whisper", source_ip=src_ip, user_agent=ua
        )
        if not ok:
            raise HTTPException(status_code=422, detail="content rejected by abuse scanner")
        transcript_text = cleaned

    # 2. Parse structured context
    info_dict = _parse_json_blob(medical_info)
    qa_list = _parse_json_blob(followup_qa) or []
    insurance_dict = _parse_json_blob(insurance_info)

    # 3. Photo upload (sync — needed before vision/triage start)
    photo_s3_key: str | None = None
    image_bytes: bytes | None = None
    image_mime = "image/jpeg"
    if image_file is not None:
        source_ip = _source_ip(request)
        # read_and_validate returns an EXIF-stripped, re-encoded JPEG — always image/jpeg now
        image_bytes = await uploads.read_and_validate(image_file, "image", source_ip=source_ip)
        image_mime = "image/jpeg"
        filename = f"{patient_id}-photo.jpg"
        media.save("photos", filename, image_bytes, content_type=image_mime)
        photo_s3_key = f"photos/{filename}"

    # 4. Parallel Claude vision + get the photo_analysis that feeds triage/prebrief/scribe/comfort.
    if image_bytes:
        photo_analysis = await asyncio.to_thread(vision.analyze_photo, image_bytes, image_mime)
    else:
        photo_analysis = {}

    # 5a. Deterministic shortcut — handles obvious cases (med refill, paperwork,
    # active resuscitation, suicidal ideation) without any LLM round-trip. Saves
    # ~$0.04-0.08 + 4-6s of Claude latency per matching encounter.
    shortcut = triage_rules.evaluate(transcript_text)

    # 5b. Standard triage runs regardless — the shortcut may agree with or
    # override the engine's ESI, and we keep the engine's SHAP / flags / composites
    # for the dashboard either way.
    triage_result = triage.predict(transcript_text, photo_analysis, medical_info=info_dict)
    if shortcut:
        # Shortcut wins on the visible ESI; engine stays as the explainability layer.
        esi_level = shortcut.esi_level
        triage_recommendation_override = shortcut.recommendation
        log.info("triage_rules shortcut applied: %s -> ESI %d", shortcut.reason, shortcut.esi_level)
    else:
        esi_level = triage_result.esi_level
        triage_recommendation_override = None
    esi_label = ESI_LABELS.get(esi_level, str(esi_level))
    patient_explanation = GENERIC_PATIENT_EXPLANATION.get(esi_level, "")

    # 6. NO synchronous Claude/TTS calls remain in this path. Everything the
    # patient sees IMMEDIATELY (ESI, label, explanation, confidence band, care
    # routing) is deterministic and computed above. The two slow Bedrock/Polly
    # calls that used to live here — comfort_protocol.generate (~8s Claude) and
    # tts.generate_and_upload (~6-14s Polly) — are now DEFERRED alongside the
    # clinician-only artifacts (see step 8b). Combined with the clinician
    # artifacts they overflowed API Gateway's 30s hard integration timeout
    # (reproduced live: text-only intake → HTTP 503 at 30.07s), so the sync path
    # keeps zero AI round-trips and returns in a few seconds even on a cold start.
    #
    # The result screen polls GET /public-patients/{id} for comfort_protocol +
    # audio_url once the deferred worker has generated them.

    # Patient-facing care routing recommendation. Pure deterministic — runs on the
    # ESI we just computed. Surfaced as the primary CTA on the patient result page.
    care_rec = care_routing.recommend(
        esi_level=esi_level,
        transcript=transcript_text,
        patient_age=(info_dict or {}).get("age"),
    )

    # 8. Persist
    patient: dict[str, Any] = {
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "name": patient_name.strip(),
        "language": language,
        "transcript": transcript_text,
        "medical_info": json.dumps(info_dict) if info_dict else None,
        "followup_qa": json.dumps(qa_list) if qa_list else None,
        "insurance_info": json.dumps(insurance_dict) if insurance_dict else None,
        "photo_s3_key": photo_s3_key,
        "photo_analysis": json.dumps(photo_analysis) if photo_analysis else None,
        "esi_level": esi_level,
        "esi_label": esi_label,
        "esi_confidence": float(triage_result.confidence),
        "confidence_band": triage_result.confidence_band,
        "shap_values": json.dumps(triage_result.shap_values),
        "triage_source": triage_result.source,
        "clinical_flags": json.dumps(triage_result.clinical_flags),
        "composites": json.dumps(triage_result.composites),
        "triage_recommendation": triage_recommendation_override or triage_result.recommendation,
        "triage_shortcut_reason": shortcut.reason if shortcut else None,
        "probabilities": json.dumps(triage_result.probabilities),
        # Deferred artifacts (clinician-only AND patient comfort/audio) are
        # generated out-of-band (see step 8b). empty_artifacts() seeds
        # empty-but-valid placeholders — comfort_protocol=[] and audio_url=None
        # included — so both the dashboard poll and the patient-result poll that
        # land before generation finishes render cleanly; artifacts_status drives
        # the loading→loaded transition on the patient result screen.
        **intake_artifacts.empty_artifacts(),
        "artifacts_status": intake_artifacts.STATUS_PENDING,
        "patient_explanation": patient_explanation,
        "care_recommendation": json.dumps(care_routing.serialize(care_rec)),
        "pain_flagged": False,
        "status": STATUS_WAITING,
        # HIPAA consent record — who consented, when, to what version
        "consent_granted_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "consent_version": consent_version or CONSENT_VERSION_CURRENT,
        # AI-provider attribution — every Claude/Whisper/ElevenLabs call for this patient
        "ai_processing_log": json.dumps((ai_log.current() or ai_log.AILog()).serialize()),
        "ai_cost_usd": float((ai_log.current() or ai_log.AILog()).total_cost_usd()),
        "ai_cost_breakdown": json.dumps((ai_log.current() or ai_log.AILog()).cost_breakdown()),
    }
    if ehr_fhir_id:
        patient["ehr_fhir_id"] = ehr_fhir_id.strip()
        patient["ehr_match_source"] = (ehr_match_source or "fhir").strip()
    storage.put_patient(patient)

    # 8b. Defer the slow clinician-only artifact generation. In AWS mode this is an
    # async Lambda self-invoke (InvocationType='Event') that re-enters via
    # main.handler()'s deferred-artifacts branch; in local/test mode it runs in a
    # daemon thread. Fire-and-forget — never blocks or fails the patient response.
    # Consent (SEC-004) + content_guard (SEC-005) already ran above; the deferred
    # path operates on the already-scanned, already-consented stored record.
    async_invoke.dispatch_deferred_artifacts(hospital_id, patient_id)

    response = {
        "patient_id": patient_id,
        "esi_level": esi_level,
        "esi_label": esi_label,
        "patient_explanation": patient_explanation,
        # comfort_protocol + audio are DEFERRED — seed them pending so the result
        # screen renders ESI/explanation/care routing immediately and polls
        # GET /public-patients/{id} for these two once the worker fills them in.
        "comfort_protocol": [],
        "audio_url": None,
        "artifacts_status": intake_artifacts.STATUS_PENDING,
        "confidence_band": triage_result.confidence_band,
        "language": language,
        "care_recommendation": care_routing.serialize(care_rec),
    }
    # Cache the successful response so a network retry with the same key is idempotent
    if idempotency_key:
        idempotency.save(idempotency_key, scope="intake", response=response)

    # Fire the workflow trigger — admins may have wired this to SMS, Slack, etc.
    # Runs in a daemon thread inside `engine.fire`, so a slow webhook doesn't
    # delay the response to the patient.
    workflow_engine.fire(
        "patient.checked_in",
        hospital_id,
        {
            "patient": {
                "id": patient_id,
                "patient_id": patient_id,
                "name": patient_name.strip(),
                # Raw phone is PHI (HIPAA §164.514) — never expose in workflow context.
                # Workflows that need to send SMS should use the patient's self-entered
                # phone from the booking flow, where it is used in-flight then hashed.
                "language": language,
                "esi_level": esi_level,
                "esi_label": esi_label,
                "transcript": transcript_text,
            },
            "hospital": {"id": hospital_id, "name": hospital.get("name", "")},
        },
    )

    return response


def _parse_json_blob(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Failed to parse JSON blob (len=%d, content redacted)", len(raw))
        return None
