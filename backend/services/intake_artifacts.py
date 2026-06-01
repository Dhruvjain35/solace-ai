"""Deferred clinician-artifact generation for intake.

The patient-facing intake path (routers/intake.py) returns fast — transcription,
content_guard, triage/ESI, comfort protocol, patient explanation, TTS audio and
care routing — and persists the patient with ``artifacts_status="pending"`` plus
empty placeholders for the clinician-only artifacts.

This module produces those clinician-only artifacts out-of-band: the **prebrief**,
the **clinical scribe note**, the **differential**, the **workup orders** and the
**disposition**. The clinician dashboard polls for them; the patient never sees
them, so a few extra seconds here is invisible to the waiting patient and keeps
the synchronous intake well under API Gateway's 30s hard integration timeout.

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
from services import differential, disposition, prebrief, scribe, workup

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
    """
    return {
        "clinician_prebrief": "",
        "clinical_scribe_note": "",
        "differential": json.dumps([]),
        "workup_orders": json.dumps({}),
        "disposition": json.dumps({}),
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
        photo_analysis = _parse_json(patient.get("photo_analysis"), {})
        info_dict = _parse_json(patient.get("medical_info"), None)
        qa_list = _parse_json(patient.get("followup_qa"), []) or []

        # Stage A (text-only): prebrief, scribe, differential. These mirror the
        # exact intake.py call signatures (comfort stays in the sync path).
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

        # Stage B: workup + disposition consume the differential (TTS stays sync).
        workup_orders = workup.generate(
            transcript_text, esi_level, ddx_list, info_dict, None,
        )
        dispo = disposition.generate(
            transcript_text, esi_level, ddx_list, info_dict, None,
        )

        artifacts = {
            "clinician_prebrief": clinician_prebrief,
            "clinical_scribe_note": clinical_scribe_note,
            "differential": json.dumps(ddx_list),
            "workup_orders": json.dumps(workup_orders),
            "disposition": json.dumps(dispo),
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
