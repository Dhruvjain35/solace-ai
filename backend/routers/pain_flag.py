"""POST /api/{hospital_id}/pain-flag — patient self-escalation.

Lifecycle:
  - Patient taps "My pain got worse" → POST /pain-flag (anonymous, no auth).
    Sets pain_flagged=True + pain_flagged_at, clears any prior acknowledgement.
  - Clinician dashboard polls /patients, detects an un-acknowledged flag, raises
    an audible alarm.
  - Clinician taps Acknowledge → POST /pain-flag/acknowledge (clinician auth).
    Stamps pain_flag_acknowledged_at + pain_flag_acknowledged_by; the alarm
    silences across every connected dashboard.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from db import storage
from lib.auth import audit, require_clinician

router = APIRouter()


class PainFlagBody(BaseModel):
    patient_id: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@router.post("/pain-flag")
def flag(hospital_id: str = Path(...), body: PainFlagBody | None = None) -> dict:
    if body is None:
        raise HTTPException(status_code=400, detail="patient_id is required")
    patient = storage.get_patient(body.patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    now = _now_iso()
    # Re-pressing the button should re-arm the alarm even if a clinician already
    # acknowledged a previous escalation — this is a NEW worsening event.
    storage.update_patient(
        body.patient_id,
        {
            "pain_flagged": True,
            "pain_flagged_at": now,
            "pain_flag_acknowledged_at": None,
            "pain_flag_acknowledged_by": None,
        },
    )
    # Fire the pain.flagged workflow trigger — admins commonly wire this to Slack
    # so the on-floor team gets pinged before the dashboard alarm goes off.
    from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415
    from services.workflows import engine as _wf  # noqa: PLC0415
    waited_minutes = 0
    if patient.get("created_at"):
        try:
            ts = _dt.fromisoformat(patient["created_at"].replace("Z", "+00:00"))
            waited_minutes = max(0, int((_dt.now(_tz.utc) - ts).total_seconds() // 60))
        except Exception:  # noqa: BLE001
            pass
    _wf.fire(
        "pain.flagged",
        hospital_id,
        {
            "patient": {
                "id": body.patient_id,
                "patient_id": body.patient_id,
                "name": patient.get("name", ""),
                "esi_level": patient.get("esi_level"),
                "waited_minutes": waited_minutes,
            },
            "hospital": {"id": hospital_id},
        },
    )
    return {"success": True, "pain_flagged_at": now}


class AcknowledgeBody(BaseModel):
    patient_id: str


@router.post("/pain-flag/acknowledge")
def acknowledge(
    hospital_id: str = Path(...),
    body: AcknowledgeBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    if body is None:
        raise HTTPException(status_code=400, detail="patient_id is required")
    patient = storage.get_patient(body.patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")
    if not patient.get("pain_flagged"):
        # No-op rather than 400 — concurrent clinicians both ack'ing a flag is a
        # normal race and shouldn't surface a scary error in either UI.
        return {"success": True, "already_clear": True}
    now = _now_iso()
    storage.update_patient(
        body.patient_id,
        {
            "pain_flag_acknowledged_at": now,
            "pain_flag_acknowledged_by": caller.get("name") or caller.get("clinician_id") or "clinician",
        },
    )
    audit(caller, "pain_flag.acknowledge", patient_id=body.patient_id)
    return {"success": True, "pain_flag_acknowledged_at": now}
