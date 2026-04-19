"""POST /api/{hospital_id}/pain-flag — patient self-escalation."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from db import storage

router = APIRouter()


class PainFlagBody(BaseModel):
    patient_id: str


@router.post("/pain-flag")
def flag(hospital_id: str = Path(...), body: PainFlagBody | None = None) -> dict:
    if body is None:
        raise HTTPException(status_code=400, detail="patient_id is required")
    patient = storage.get_patient(body.patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    storage.update_patient(body.patient_id, {"pain_flagged": True, "pain_flagged_at": now})
    return {"success": True, "pain_flagged_at": now}
