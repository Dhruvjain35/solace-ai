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
from lib import ai_log, blocklist, content_guard, idempotency, quota, uploads

CONSENT_VERSION_CURRENT = "1.0"
from lib.fallbacks import ESI_LABELS, GENERIC_PATIENT_EXPLANATION
from services import (
    comfort_protocol,
    differential,
    disposition,
    prebrief,
    scribe,
    transcription,
    triage,
    tts,
    vision,
    workup,
)


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
    patient_name: str = Form(...),
    pre_transcribed_text: str | None = Form(None),
    # New: structured fields (JSON-encoded arrays/objects)
    medical_info: str | None = Form(None),
    followup_qa: str | None = Form(None),
    insurance_info: str | None = Form(None),
    intake_token: str | None = Form(None),
    idempotency_key: str | None = Form(None),
    consent_granted: str | None = Form(None),
    consent_version: str | None = Form(None),
    preferred_language: str | None = Form(None),
    request: Request = None,
) -> dict[str, Any]:
    src_ip = _source_ip(request)
    ua = request.headers.get("user-agent") if request else None
    identity = quota.identity_of(src_ip, ua)

    # Auto-block check FIRST — short-circuits identities flagged as abusive
    blocklist.enforce(identity, source_ip=src_ip)

    # HIPAA consent gate — §164.508 requires explicit authorization before PHI
    # flows to third-party processors (OpenAI/Anthropic/ElevenLabs).
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
                "Consent required. You must agree to AI processing of your voice / symptoms"
                " / photos by OpenAI, Anthropic, and ElevenLabs before submitting intake."
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
            raise HTTPException(status_code=503, detail=f"Voice transcription unavailable: {e}")
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

    # 5. Triage is fast + local (no await needed)
    triage_result = triage.predict(transcript_text, photo_analysis, medical_info=info_dict)
    esi_level = triage_result.esi_level
    esi_label = ESI_LABELS.get(esi_level, str(esi_level))
    patient_explanation = GENERIC_PATIENT_EXPLANATION.get(esi_level, "")

    # 6. Fire the Claude calls in parallel — biggest latency win.
    # Stage A (text-only): prebrief, scribe, comfort, differential.
    # We run differential first because workup + disposition depend on its output.
    prebrief_task = asyncio.to_thread(
        prebrief.generate,
        transcript_text, photo_analysis, esi_level,
        info_dict, qa_list,
    )
    scribe_task = asyncio.to_thread(
        scribe.generate_clinical_note,
        transcript_text, info_dict, qa_list, photo_analysis,
    )
    comfort_task = asyncio.to_thread(
        comfort_protocol.generate,
        transcript_text, photo_analysis, esi_level, language,
        info_dict, qa_list,
    )
    differential_task = asyncio.to_thread(
        differential.generate,
        transcript_text, esi_level,
        info_dict, qa_list, photo_analysis, None,
    )
    clinician_prebrief, clinical_scribe_note, protocol, ddx_list = await asyncio.gather(
        prebrief_task, scribe_task, comfort_task, differential_task
    )

    # Stage B: workup + disposition consume the differential. Both run in parallel.
    workup_task = asyncio.to_thread(
        workup.generate,
        transcript_text, esi_level, ddx_list, info_dict, None,
    )
    disposition_task = asyncio.to_thread(
        disposition.generate,
        transcript_text, esi_level, ddx_list, info_dict, None,
    )
    workup_orders, dispo = await asyncio.gather(workup_task, disposition_task)

    # 7. TTS uses the comfort protocol, so it runs after. Still threaded so it doesn't block the event loop.
    audio_script = tts.compose_script(patient_explanation, protocol, patient_name=patient_name)
    audio_url = await asyncio.to_thread(tts.generate_and_upload, audio_script, language, patient_id)

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
        "triage_recommendation": triage_result.recommendation,
        "probabilities": json.dumps(triage_result.probabilities),
        "clinician_prebrief": clinician_prebrief,
        "clinical_scribe_note": clinical_scribe_note,
        "differential": json.dumps(ddx_list),
        "workup_orders": json.dumps(workup_orders),
        "disposition": json.dumps(dispo),
        "patient_explanation": patient_explanation,
        "comfort_protocol": json.dumps(protocol),
        "audio_url": audio_url,
        "pain_flagged": False,
        "status": STATUS_WAITING,
        # HIPAA consent record — who consented, when, to what version
        "consent_granted_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "consent_version": consent_version or CONSENT_VERSION_CURRENT,
        # AI-provider attribution — every Claude/Whisper/ElevenLabs call for this patient
        "ai_processing_log": json.dumps((ai_log.current() or ai_log.AILog()).serialize()),
    }
    storage.put_patient(patient)

    response = {
        "patient_id": patient_id,
        "esi_level": esi_level,
        "esi_label": esi_label,
        "patient_explanation": patient_explanation,
        "comfort_protocol": protocol,
        "audio_url": audio_url,
        "confidence_band": triage_result.confidence_band,
        "language": language,
    }
    # Cache the successful response so a network retry with the same key is idempotent
    if idempotency_key:
        idempotency.save(idempotency_key, scope="intake", response=response)
    return response


def _parse_json_blob(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Failed to parse JSON blob (len=%d, content redacted)", len(raw))
        return None
