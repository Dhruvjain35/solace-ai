"""Clinician-facing patient endpoints: list, detail, mark-seen."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from db import storage
from db.constants import STATUS_SEEN, STATUS_WAITING
from lib.auth import audit, require_clinician

router = APIRouter()


def _minutes_since(iso_ts: str) -> int:
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds() // 60))


def _summary(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "patient_id": p["patient_id"],
        "name": p.get("name", ""),
        "esi_level": p.get("esi_level"),
        "esi_label": p.get("esi_label"),
        "esi_confidence": p.get("esi_confidence"),
        "confidence_band": p.get("confidence_band"),
        "clinician_prebrief": p.get("clinician_prebrief", ""),
        "language": p.get("language", "en"),
        "pain_flagged": bool(p.get("pain_flagged")),
        "pain_flagged_at": p.get("pain_flagged_at"),
        "status": p.get("status", STATUS_WAITING),
        "seen_by": p.get("seen_by"),
        "seen_at": p.get("seen_at"),
        "created_at": p.get("created_at"),
        "waited_minutes": _minutes_since(p.get("created_at", "")),
        "refined_esi_level": p.get("refined_esi_level"),
        "refined_confidence": p.get("refined_confidence"),
        "refined_at": p.get("refined_at"),
    }


@router.get("/patients")
def list_patients(
    hospital_id: str = Path(...),
    status: str = Query("waiting"),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "patients.list")
    rows = storage.list_patients_for_hospital(hospital_id, status=status)
    return {"patients": [_summary(p) for p in rows]}


@router.get("/patients/{patient_id}")
def get_patient_detail(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "patients.detail", patient_id=patient_id)
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    return {
        **_summary(p),
        "transcript": p.get("transcript", ""),
        "photo_url": _photo_url(p),
        "photo_analysis": _maybe_json(p.get("photo_analysis")),
        "shap_values": _maybe_json(p.get("shap_values")),
        "comfort_protocol": _maybe_json(p.get("comfort_protocol")) or [],
        "patient_explanation": p.get("patient_explanation", ""),
        "audio_url": _audio_url(p),
        "triage_source": p.get("triage_source"),
        "clinical_flags": _maybe_json(p.get("clinical_flags")) or [],
        "composites": _maybe_json(p.get("composites")) or {},
        "triage_recommendation": p.get("triage_recommendation", ""),
        "probabilities": _maybe_json(p.get("probabilities")) or [],
        "medical_info": _maybe_json(p.get("medical_info")),
        "followup_qa": _maybe_json(p.get("followup_qa")) or [],
        "insurance_info": _maybe_json(p.get("insurance_info")),
        "prescriptions": storage.list_prescriptions(patient_id),
        "clinical_scribe_note": p.get("clinical_scribe_note", ""),
        "notes": storage.list_notes(patient_id),
        "patient_education": _maybe_json(p.get("patient_education")),
        "patient_education_published_at": p.get("patient_education_published_at"),
        "refined_esi_level": p.get("refined_esi_level"),
        "refined_confidence": p.get("refined_confidence"),
        "refined_probabilities": p.get("refined_probabilities"),
        "refined_conformal_set": p.get("refined_conformal_set"),
        "refined_top_features": p.get("refined_top_features"),
        "refined_source": p.get("refined_source"),
        "refined_at": p.get("refined_at"),
        "measured_vitals": p.get("measured_vitals"),
        "consent_granted_at": p.get("consent_granted_at"),
        "consent_version": p.get("consent_version"),
        "ai_processing_log": _maybe_json(p.get("ai_processing_log")) or [],
    }


# Public patient endpoint — no clinician PIN. The patient's own phone polls this
# to see education updates published by the clinician. Returns only patient-safe fields.
@router.get("/public-patients/{patient_id}")
def get_public_patient(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
) -> dict:
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    # Compute a live wait-time estimate based on the current queue
    from services import wait_time as _wt  # noqa: PLC0415

    queue = storage.list_patients_for_hospital(hospital_id, status="waiting")
    queue = [q for q in queue if q.get("patient_id") != patient_id]
    est_minutes = _wt.estimate_minutes(int(p.get("esi_level") or 3), queue)
    return {
        "patient_id": p["patient_id"],
        "patient_explanation": p.get("patient_explanation", ""),
        "comfort_protocol": _maybe_json(p.get("comfort_protocol")) or [],
        "audio_url": _audio_url(p),
        "patient_education": _maybe_json(p.get("patient_education")),
        "patient_education_published_at": p.get("patient_education_published_at"),
        "status": p.get("status"),
        "wait_estimate_minutes": est_minutes,
        "wait_estimate_range": _wt.format_range(est_minutes),
    }


class ResolveBody(BaseModel):
    clinician_name: str


@router.patch("/patients/{patient_id}/resolve")
def resolve_patient(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: ResolveBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "patients.resolve", patient_id=patient_id)
    if body is None:
        raise HTTPException(status_code=400, detail="clinician_name required")
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    storage.update_patient(
        patient_id,
        {"status": STATUS_SEEN, "seen_by": body.clinician_name.strip(), "seen_at": now},
    )
    return {"success": True, "seen_at": now}


# --- helpers -------------------------------------------------------------------------
def _photo_url(p: dict[str, Any]) -> str | None:
    key = p.get("photo_s3_key")
    if not key:
        return None
    # key format: "photos/<filename>"
    _, _, filename = key.partition("/")
    from db import media

    return media.presigned_get("photos", filename)


def _audio_url(p: dict[str, Any]) -> str | None:
    """Regenerate a fresh presigned URL every read — the cached one in DDB
    expires after 15 min (S3 presign limit) but patients often don't open the
    result until much later."""
    if not p.get("audio_url"):
        return None
    from db import media

    return media.presigned_get("audio", f"{p['patient_id']}.mp3")


def _maybe_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
