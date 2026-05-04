"""Patient-facing scheduling endpoints (no auth — patients book themselves)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel

from db import storage
from lib import blocklist, quota
from services import scheduling, sms

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/appointments/availability")
def availability(
    hospital_id: str = Path(...),
    days: int = Query(7, ge=1, le=14),
) -> dict[str, Any]:
    if not storage.get_hospital(hospital_id):
        raise HTTPException(status_code=404, detail="hospital not found")
    slots = scheduling.open_slots(hospital_id=hospital_id, days=days)
    return {"slots": [{"iso": s.iso, "label": s.label, "duration_min": s.duration_min} for s in slots]}


class BookBody(BaseModel):
    slot_iso: str
    patient_name: str
    patient_phone: str
    reason: str = ""


@router.post("/appointments/book")
def book(
    hospital_id: str = Path(...),
    body: BookBody | None = None,
    request: Request = None,
) -> dict[str, Any]:
    if body is None or not body.slot_iso or not body.patient_name:
        raise HTTPException(status_code=400, detail="slot_iso + patient_name required")
    if not storage.get_hospital(hospital_id):
        raise HTTPException(status_code=404, detail="hospital not found")

    src_ip = (
        request.headers.get("x-forwarded-for", request.client.host if request and request.client else None)
        if request else None
    )
    ua = request.headers.get("user-agent") if request else None
    identity = quota.identity_of(src_ip, ua)
    blocklist.enforce(identity, source_ip=src_ip)
    quota.check_and_consume(identity, "intake.start", source_ip=src_ip)

    # Slot has to still be open. Cheap check — re-fetch availability set.
    open_isos = {s.iso for s in scheduling.open_slots(hospital_id=hospital_id, days=14)}
    if body.slot_iso not in open_isos:
        raise HTTPException(status_code=409, detail="slot is no longer available")

    appt = scheduling.book(
        hospital_id=hospital_id,
        slot_iso=body.slot_iso,
        patient_name=body.patient_name,
        patient_phone=body.patient_phone,
        reason=body.reason,
        channel="web",
    )

    # Best-effort SMS confirmation. Doesn't block the booking response.
    if body.patient_phone and sms.is_configured():
        hospital = storage.get_hospital(hospital_id) or {}
        text = sms.render_appointment_reminder(
            patient_name=body.patient_name,
            hospital_name=hospital.get("name", "the clinic"),
            when_human=appt["slot_iso"],
            confirmation_code=appt["confirmation_code"],
        )
        sms.send(to=body.patient_phone, body=text)

    # Fire the appointment.booked workflow trigger.
    from services.workflows import engine as _wf  # noqa: PLC0415
    _wf.fire(
        "appointment.booked",
        hospital_id,
        {"appointment": appt, "hospital": {"id": hospital_id}},
    )

    return {"success": True, "appointment": appt}


@router.get("/appointments/{confirmation_code}")
def lookup(
    hospital_id: str = Path(...),
    confirmation_code: str = Path(...),
) -> dict[str, Any]:
    appt = scheduling.lookup(hospital_id=hospital_id, confirmation_code=confirmation_code)
    if not appt:
        raise HTTPException(status_code=404, detail="appointment not found")
    return appt


class CancelBody(BaseModel):
    confirmation_code: str


@router.post("/appointments/cancel")
def cancel(
    hospital_id: str = Path(...),
    body: CancelBody | None = None,
) -> dict[str, Any]:
    if body is None or not body.confirmation_code:
        raise HTTPException(status_code=400, detail="confirmation_code required")
    ok = storage.cancel_appointment(body.confirmation_code, hospital_id=hospital_id)
    if not ok:
        raise HTTPException(status_code=404, detail="appointment not found or wrong hospital")
    return {"success": True}
