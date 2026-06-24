"""Deferred artifact generation for intake.

The patient-facing intake path (routers/intake.py) returns fast — transcription,
content_guard, deterministic triage/ESI, patient explanation and care routing —
and persists the patient with ``artifacts_status="pending"`` plus empty
placeholders for every deferred artifact. The sync path now runs ZERO AI
round-trips, so it returns in a few seconds even on a cold start.

This module produces all the slow Bedrock/Polly artifacts out-of-band:
  * clinician-only: the **prebrief**, **clinical scribe note**, **differential**,
    **workup orders** and **disposition** (the clinician dashboard polls these;
    the patient never sees them);
  * patient-facing: the **comfort protocol** the patient reads and the **TTS
    audio** they hear on the result screen.

Moving comfort_protocol + TTS here (they were the last two synchronous Claude/
Polly calls in intake.py) is the actual fix for the intake 503: combined with
the clinician artifacts they overflowed API Gateway's 30s hard integration
timeout. The patient-result screen polls GET /public-patients/{id} and shows a
loading state for comfort + audio until ``artifacts_status`` flips to "ready".

Layering (ARCH-001/002/003): this is a *service*. It calls AI adapters via the
``services.*`` generation modules (which themselves live behind ``lib/``) and
persists via ``db.storage`` — it never touches boto3 or DynamoDB directly.

SEC-004/005: consent and content_guard already ran in the synchronous intake path
*before* the patient was persisted. This module operates only on already-consented,
already-scanned, stored data — it introduces no new patient-supplied text into the
AI pipeline.

Both the deferred Lambda self-invoke path and any future "regenerate artifacts"
endpoint call ``generate_clinician_artifacts`` so the generation logic lives once.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from db import storage
from services import (
    comfort_protocol,
    differential,
    disposition,
    prebrief,
    scribe,
    tts,
    workup,
)

log = logging.getLogger(__name__)

# Artifact-status lifecycle stored on the patient record.
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# The clinician-artifact field names this module owns on the patient record.
# intake.py seeds these as empty placeholders; we overwrite them here.
ARTIFACT_FIELDS = (
    "clinician_prebrief",
    "clinical_scribe_note",
    "differential",
    "workup_orders",
    "disposition",
)


def empty_artifacts() -> dict[str, Any]:
    """Placeholder values intake.py persists alongside artifacts_status="pending".

    Mirrors the JSON-encoded shapes the dashboard expects so a poll that lands
    before generation finishes renders an empty-but-valid record instead of
    erroring on a missing key.

    Includes the patient-facing comfort_protocol (empty list) and audio_url
    (None) too — these are now generated in the deferred worker alongside the
    clinician artifacts, so the patient-result poll sees a clean pending shape
    until the worker fills them in.
    """
    return {
        "clinician_prebrief": "",
        "clinical_scribe_note": "",
        "differential": json.dumps([]),
        "workup_orders": json.dumps({}),
        "disposition": json.dumps({}),
        # Patient-facing deferred artifacts (pending placeholders).
        "comfort_protocol": json.dumps([]),
        "audio_url": None,
    }


def _parse_json(raw: Any, default: Any) -> Any:
    """Decode a JSON-string field off the stored patient record, tolerating
    already-decoded values (local mode keeps native dicts/lists in memory)."""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def generate_clinician_artifacts(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Generate the deferred clinician artifacts for one stored patient and patch
    them onto the record, flipping ``artifacts_status`` to "ready".

    Loads the patient, reconstructs the generation inputs from the persisted
    fields (transcript, photo_analysis, esi_level, medical_info, followup_qa) —
    the SAME inputs intake.py used — and runs the EXACT generation calls intake.py
    previously ran inline.

    Failure-safe: on ANY error the patient's ``artifacts_status`` is set to
    "failed" (best-effort) and the error is logged WITHOUT PHI (hospital_id only).
    Never raises — the deferred Lambda must not crash, and the patient-facing
    response has already been returned.

    Returns the artifact dict that was written (or the failure marker).
    """
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        # Cross-hospital / missing patient — refuse silently (no PHI in log).
        log.warning(
            "deferred artifacts: patient not found or hospital mismatch for hospital=%s",
            hospital_id,
        )
        return {"artifacts_status": STATUS_FAILED}

    try:
        transcript_text = patient.get("transcript") or ""
        esi_level = int(patient.get("esi_level") or 3)
        language = (patient.get("language") or "en")
        patient_name = patient.get("name") or ""
        patient_explanation = patient.get("patient_explanation") or ""
        photo_analysis = _parse_json(patient.get("photo_analysis"), {})
        info_dict = _parse_json(patient.get("medical_info"), None)
        qa_list = _parse_json(patient.get("followup_qa"), []) or []

        # Stage A (text-only): prebrief, scribe, differential. These mirror the
        # exact intake.py call signatures.
        clinician_prebrief = prebrief.generate(
            transcript_text, photo_analysis, esi_level,
            info_dict, qa_list,
        )
        clinical_scribe_note = scribe.generate_clinical_note(
            transcript_text, info_dict, qa_list, photo_analysis,
        )
        ddx_list = differential.generate(
            transcript_text, esi_level,
            info_dict, qa_list, photo_analysis, None,
        )

        # Stage B: workup + disposition consume the differential.
        workup_orders = workup.generate(
            transcript_text, esi_level, ddx_list, info_dict, None,
        )
        dispo = disposition.generate(
            transcript_text, esi_level, ddx_list, info_dict, None,
        )

        # Stage C (patient-facing, formerly synchronous in intake.py): the comfort
        # protocol the patient reads + the TTS audio they hear on the result
        # screen. These are the two calls that pushed the sync intake path over
        # API Gateway's 30s budget; deferring them is the actual 503 fix. EXACT
        # call signatures from the old intake.py. comfort runs first (TTS needs
        # the protocol), then TTS. Both reuse the already-consented, already-
        # scanned stored record (SEC-004/005) — no new patient text enters the
        # AI pipeline here.
        protocol = comfort_protocol.generate(
            transcript_text, photo_analysis, esi_level, language,
            info_dict, qa_list,
        )
        audio_script = tts.compose_script(
            patient_explanation, protocol, patient_name=patient_name,
        )
        audio_url = tts.generate_and_upload(audio_script, language, patient_id)

        artifacts = {
            "clinician_prebrief": clinician_prebrief,
            "clinical_scribe_note": clinical_scribe_note,
            "differential": json.dumps(ddx_list),
            "workup_orders": json.dumps(workup_orders),
            "disposition": json.dumps(dispo),
            # Patient-facing deferred artifacts.
            "comfort_protocol": json.dumps(protocol),
            "audio_url": audio_url,
            "artifacts_status": STATUS_READY,
        }
        storage.update_patient(patient_id, artifacts)
        log.info("deferred artifacts ready for hospital=%s", hospital_id)
        return artifacts
    except Exception as e:  # noqa: BLE001 — deferred worker must never crash
        # SEC-002: log the failure + hospital_id only, never transcript/patient_id.
        log.exception("deferred artifacts failed for hospital=%s: %s", hospital_id, e)
        try:
            storage.update_patient(patient_id, {"artifacts_status": STATUS_FAILED})
        except Exception:  # noqa: BLE001 — status write is best-effort
            log.warning("could not mark artifacts_status=failed for hospital=%s", hospital_id)
        return {"artifacts_status": STATUS_FAILED}
