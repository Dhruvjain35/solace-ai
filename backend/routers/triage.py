"""Clinician-only ML triage refinement.

Called when a nurse has taken real vitals at the bedside. Runs the trained
LightGBM ensemble against the patient record + vitals and stores the refined
ESI + conformal set + top features on the patient.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from db import storage
from lib.auth import audit, require_clinician
from services import triage_ml

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class VitalsBody(BaseModel):
    systolic_bp: float | None = Field(None, ge=40, le=260)
    diastolic_bp: float | None = Field(None, ge=20, le=160)
    heart_rate: float | None = Field(None, ge=20, le=250)
    respiratory_rate: float | None = Field(None, ge=4, le=60)
    temperature_c: float | None = Field(None, ge=28, le=43)
    spo2: float | None = Field(None, ge=40, le=100)
    gcs_total: int | None = Field(None, ge=3, le=15)
    pain_score: int | None = Field(None, ge=0, le=10)
    weight_kg: float | None = Field(None, ge=1, le=500)
    height_cm: float | None = Field(None, ge=30, le=250)
    mental_status: str | None = None  # alert/confused/drowsy/agitated/unresponsive
    news2_score: int | None = None


@router.post("/patients/{patient_id}/refine-triage")
def refine_triage(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: VitalsBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "triage.refine", patient_id=patient_id)
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    if body is None:
        raise HTTPException(status_code=400, detail="vitals required")

    vitals = body.model_dump(exclude_none=False)
    result = triage_ml.predict(patient, vitals)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="ML triage model unavailable (artifacts not loaded)",
        )

    updates = {
        "refined_esi_level": result["esi_level"],
        "refined_confidence": result["confidence"],
        "refined_probabilities": json.dumps(result["probabilities"]),
        "refined_conformal_set": json.dumps(result["conformal_set"]),
        "refined_top_features": json.dumps(result["top_features"]),
        "refined_source": result["source"],
        "refined_at": _now_iso(),
        "measured_vitals": json.dumps({k: v for k, v in vitals.items() if v is not None}),
    }
    storage.update_patient(patient_id, updates)
    return {"success": True, "refinement": result, "applied_at": updates["refined_at"]}
