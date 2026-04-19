"""Clinician-facing prescription endpoints.

- POST /patients/{id}/prescriptions            — clinician writes one
- POST /patients/{id}/prescriptions/suggest    — Claude suggests 1-3 options
- GET  /patients/{id}/prescriptions            — list for a patient
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from db import storage
from lib.auth import audit, require_clinician
from services import prescription

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class PrescriptionBody(BaseModel):
    drug: str
    dose: str = ""
    route: str = ""
    frequency: str = ""
    duration: str = ""
    indication: str = ""
    cautions: str = ""
    prescribed_by: str = "Clinician"
    source: str = "manual"  # "manual" | "ai_suggested_accepted"


@router.post("/patients/{patient_id}/prescriptions")
def create_prescription(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: PrescriptionBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "prescriptions.create", patient_id=patient_id)
    if body is None or not body.drug.strip():
        raise HTTPException(status_code=400, detail="drug is required")
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    record = {
        "prescription_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "prescribed_at": _now_iso(),
        "clinician_id": caller.get("clinician_id"),
        **body.model_dump(),
    }
    if caller.get("auth_method") == "jwt" and caller.get("name"):
        record["prescribed_by"] = caller["name"]
    storage.add_prescription(record)
    return {"success": True, "prescription": record}


@router.get("/patients/{patient_id}/prescriptions")
def list_prescriptions(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "prescriptions.list", patient_id=patient_id)
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    return {"prescriptions": storage.list_prescriptions(patient_id)}


@router.post("/patients/{patient_id}/prescriptions/suggest")
def suggest_prescriptions(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "prescriptions.suggest", patient_id=patient_id)
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    transcript = patient.get("transcript", "")
    esi = int(patient.get("esi_level") or 3)
    medical_info = _maybe_json(patient.get("medical_info")) or {}
    followup_qa = _maybe_json(patient.get("followup_qa")) or []
    photo_analysis = _maybe_json(patient.get("photo_analysis")) or {}

    suggestions = prescription.suggest(transcript, esi, medical_info, followup_qa, photo_analysis)
    return {"suggestions": suggestions}


def _maybe_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
