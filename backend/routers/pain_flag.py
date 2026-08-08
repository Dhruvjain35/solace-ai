"""POST /api/{hospital_id}/pain-flag — patient self-escalation.

Lifecycle:
  - Patient taps "My pain got worse" -> POST /pain-flag (anonymous, no auth).
    Sets pain_flagged=True + pain_flagged_at, clears any prior acknowledgement.
  - Clinician dashboard polls /patients, detects an un-acknowledged flag, raises
    an audible alarm.
  - Clinician taps Acknowledge -> POST /pain-flag/acknowledge (clinician auth).
    Stamps pain_flag_acknowledged_at + pain_flag_acknowledged_by; the alarm
    silences across every connected dashboard.

Security:
  - Rate limited (30/hr per identity) to prevent alarm flooding
  - Blocklist enforced before any logic
  - Audit logged for both patient flag and clinician acknowledgement
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from db import storage
from lib import audit as _audit, tenancy
from lib import blocklist, quota
from lib.auth import audit, require_clinician

router = APIRouter()


class PainFlagBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., max_length=64)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@router.post("/pain-flag")
def flag(
    hospital_id: str = Path(...),
    body: PainFlagBody | None = None,
    request: Request = None,
) -> dict:
    # SEC-003: blocklist enforcement is the first action on patient-facing endpoints,
    # before any request parsing — abusive identities short-circuit immediately.
    source_ip = None
    user_agent = None
    if request:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "pain_flag", source_ip=source_ip)

    if body is None:
        raise HTTPException(status_code=400, detail="patient_id is required")

    patient = tenancy.require_patient(body.patient_id, hospital_id)
    now = _now_iso()
    # Re-pressing the button should re-arm the alarm even if a clinician already
    # acknowledged a previous escalation -- this is a NEW worsening event.
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

    # Audit log the patient action
    _audit.record(
        clinician_id=None,
        clinician_name=None,
        action="pain_flag.triggered",
        patient_id=body.patient_id,
        source_ip=source_ip,
        status_code=200,
    )

    return {"success": True, "pain_flagged_at": now}


class AcknowledgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., max_length=64)


@router.post("/pain-flag/acknowledge")
def acknowledge(
    hospital_id: str = Path(...),
    body: AcknowledgeBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    if body is None:
        raise HTTPException(status_code=400, detail="patient_id is required")
    patient = tenancy.require_patient(body.patient_id, hospital_id)
    if not patient.get("pain_flagged"):
        # No-op rather than 400 -- concurrent clinicians both ack'ing a flag is a
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
