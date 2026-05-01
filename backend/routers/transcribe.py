"""POST /api/{hospital_id}/transcribe — transcribes audio AND generates follow-up questions.

Split from /intake so the patient can answer the AI's clarifying questions before we
finalize the record. Caller flow:
  1. POST /transcribe  → { transcript, language, followups }
  2. Patient answers follow-ups in UI
  3. POST /intake      → full pipeline with transcript + answers + medical info + photo
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, Path, Request, UploadFile

from db import storage
from lib import blocklist, content_guard, quota, uploads
from services import followups, transcription

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/transcribe")
async def transcribe_and_ask(
    hospital_id: str = Path(...),
    audio_file: UploadFile | None = File(None),
    pre_transcribed_text: str | None = Form(None),
    medical_info: str | None = Form(None),
    preferred_language: str | None = Form(None),
    request: Request = None,
) -> dict:
    if not storage.get_hospital(hospital_id):
        raise HTTPException(status_code=404, detail=f"Unknown hospital '{hospital_id}'")

    source_ip = request.headers.get("x-forwarded-for", request.client.host if request and request.client else None) if request else None
    user_agent = request.headers.get("user-agent") if request else None
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "transcribe", source_ip=source_ip)

    selected_lang = (preferred_language or "").strip().lower()[:2] or None

    # 1. Transcribe (or accept prepared text)
    if pre_transcribed_text:
        transcript = pre_transcribed_text.strip()
        # Trust the patient's language pick when they typed instead of recorded;
        # Whisper isn't in the loop so we have nothing better to use.
        language = selected_lang or "en"
        ok, cleaned, _ = content_guard.scan(transcript, label="transcribe.pre_transcribed", source_ip=source_ip, user_agent=user_agent)
        if not ok:
            raise HTTPException(status_code=422, detail="content rejected by abuse scanner")
        transcript = cleaned
    else:
        if not audio_file:
            raise HTTPException(status_code=400, detail="audio_file or pre_transcribed_text required")
        audio_bytes = await uploads.read_and_validate(audio_file, "audio", source_ip=source_ip)
        duration = getattr(audio_file, "duration_seconds", 0.0) or 0.0
        quota.check_audio_duration(duration, identity, source_ip=source_ip)
        try:
            t = transcription.transcribe(audio_bytes, filename=audio_file.filename or "audio.webm")
            transcript = t.text
            # Patient's explicit language pick wins over Whisper auto-detect.
            language = selected_lang or t.language
        except transcription.TranscriptionError as e:
            raise HTTPException(status_code=503, detail=f"Voice transcription unavailable: {e}")
        ok, cleaned, _ = content_guard.scan(transcript, label="transcribe.whisper", source_ip=source_ip, user_agent=user_agent)
        if not ok:
            raise HTTPException(status_code=422, detail="content rejected by abuse scanner")
        transcript = cleaned

    # 2. Generate follow-up questions in the patient's language
    info_dict = None
    if medical_info:
        try:
            info_dict = json.loads(medical_info)
        except json.JSONDecodeError:
            log.warning("medical_info JSON parse failed; ignoring")
    questions = followups.generate_questions(transcript, info_dict, language=language)

    return {"transcript": transcript, "language": language, "followups": questions}
