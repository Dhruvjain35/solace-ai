"""SMS endpoints — discharge plans + appointment reminders.

Auth model:
  POST /sms/discharge        — clinician PIN required (sends to patient on file)
  POST /sms/care-instructions — public, but requires the patient_id (anonymous
                                patient asks for a copy of their own care plan)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from db import storage
from lib import audit as _audit
from lib import blocklist, quota
from lib.auth import audit, require_clinician
from services import sms

log = logging.getLogger(__name__)

router = APIRouter()


def _sanitized_sms_result(result: dict[str, Any]) -> dict[str, Any]:
    """Strip PHI from sms.send()'s raw dict before returning it to a caller.

    sms.send() echoes the full E.164 phone number (`to`) on success and the
    caller-supplied phone inside `message` on an invalid-number failure. A
    phone number is a HIPAA Safe Harbor identifier (§164.514) — it must never
    be reflected back to an anonymous caller. Return only success + reason.
    """
    return {
        "success": bool(result.get("success")),
        "reason": result.get("reason", "" if result.get("success") else "send_failed"),
    }


class DischargeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., max_length=64)
    # override the on-file phone if needed
    phone: str | None = Field(None, max_length=32)


@router.post("/sms/discharge")
def send_discharge(
    hospital_id: str = Path(...),
    body: DischargeBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Clinician triggers an SMS to the patient with their discharge plan.

    Composes the message from the published patient_education + comfort_protocol
    on the patient row. Falls back to a generic template if no education has
    been published yet."""
    if body is None or not body.patient_id:
        raise HTTPException(status_code=400, detail="patient_id required")
    audit(caller, "sms.discharge", patient_id=body.patient_id)

    patient = storage.get_patient(body.patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    hospital = storage.get_hospital(hospital_id) or {}
    name = patient.get("name") or ""
    care_instructions = _care_steps_from_patient(patient)
    when_to_return = _when_to_return_from_patient(patient)

    text = sms.render_discharge_template(
        patient_name=name,
        hospital_name=hospital.get("name", "the clinic"),
        care_instructions=care_instructions,
        when_to_return=when_to_return,
    )
    phone = body.phone or _patient_phone(patient)
    result = sms.send(to=phone, body=text)

    # Audit BOTH the request and the outcome — required for HIPAA §164.312(b).
    _audit.record(
        clinician_id=caller.get("clinician_id"),
        clinician_name=caller.get("name"),
        action="sms.discharge.sent" if result.get("success") else "sms.discharge.failed",
        source_ip=None,
        status_code=200 if result.get("success") else 422,
        extra={
            "patient_id": body.patient_id,
            "to_last4": (phone or "")[-4:],
            "reason": result.get("reason", ""),
        },
        patient_id=body.patient_id,
    )
    return _sanitized_sms_result(result)


class CareInstructionsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., max_length=64)
    # patient supplies their own phone
    phone: str = Field(..., max_length=32)


@router.post("/sms/care-instructions")
def send_self_serve_instructions(
    hospital_id: str = Path(...),
    body: CareInstructionsBody | None = None,
    request: Request = None,
) -> dict[str, Any]:
    """Patient self-serve — sends their own care plan to their own phone.

    Two controls, both of which this route claimed and did not have. The
    docstring said "Throttled by the existing identity-based quota" and no quota
    was consumed: 25 requests in a row all sent, each one billed to the clinic's
    Twilio account. And the destination was whatever the request named, so
    anyone holding a patient_id could forward that patient's discharge plan,
    with their name on it, to any handset.
    """
    source_ip, user_agent, identity = _identity(request)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "sms.care_instructions", source_ip=source_ip)

    if body is None or not body.patient_id or not body.phone:
        raise HTTPException(status_code=400, detail="patient_id + phone required")
    patient = storage.get_patient(body.patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    # The message carries the patient's name and their medications, so it goes
    # to the number already on their record. When intake captured no number
    # there is nothing to check against and the supplied one is used, which is
    # the case this is a match rather than a lookup.
    on_file = _patient_phone(patient)
    if on_file and _digits(on_file) != _digits(body.phone):
        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.sms_care_instructions_phone_mismatch",
            source_ip=source_ip, status_code=403,
            extra={"identity": identity, "patient_id": body.patient_id},
        )
        raise HTTPException(
            status_code=403,
            detail="That number doesn't match the one on file. Ask the front desk.",
        )

    hospital = storage.get_hospital(hospital_id) or {}
    text = sms.render_discharge_template(
        patient_name=patient.get("name", ""),
        hospital_name=hospital.get("name", "the clinic"),
        care_instructions=_care_steps_from_patient(patient),
        when_to_return=_when_to_return_from_patient(patient),
    )
    result = sms.send(to=body.phone, body=text)
    return _sanitized_sms_result(result)


# --- helpers ----------------------------------------------------------------


def _care_steps_from_patient(p: dict) -> list[str]:
    """Pull a 3-4 step home-care list from the patient's published education
    (preferred) or comfort_protocol (fallback)."""
    edu = _maybe_json(p.get("patient_education"))
    if isinstance(edu, dict):
        steps = edu.get("things_to_do_at_home")
        if isinstance(steps, list) and steps:
            return [str(s) for s in steps[:4]]
    proto = _maybe_json(p.get("comfort_protocol"))
    if isinstance(proto, list):
        out = []
        for item in proto[:4]:
            if isinstance(item, dict):
                title = str(item.get("title", "")).strip()
                inst = str(item.get("instruction", "")).strip()
                if title and inst:
                    out.append(f"{title}: {inst}")
        if out:
            return out
    return ["Rest and stay hydrated.", "Take medications as prescribed."]


def _when_to_return_from_patient(p: dict) -> str:
    edu = _maybe_json(p.get("patient_education"))
    if isinstance(edu, dict):
        wtr = edu.get("when_to_come_back")
        if wtr:
            return str(wtr)
    return "symptoms get worse, you can't keep fluids down, or new symptoms appear"


def _identity(request: Request | None) -> tuple[str | None, str | None, str]:
    source_ip = user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")
    return source_ip, user_agent, quota.identity_of(source_ip, user_agent)


def _digits(phone: str) -> str:
    """Compare phone numbers by their digits, ignoring how they were typed.

    A patient reading their own number off a card writes "(512) 555-0100";
    intake stored "+15125550100". Refusing someone their own discharge plan over
    punctuation is how a check like this gets deleted within a week.

    The last ten digits, so a number stored with a country code still matches
    one typed without it.
    """
    return "".join(c for c in str(phone or "") if c.isdigit())[-10:]


def _patient_phone(p: dict) -> str:
    """Look for a phone number on insurance_info or directly on the patient row."""
    insurance = _maybe_json(p.get("insurance_info"))
    if isinstance(insurance, dict) and insurance.get("phone"):
        return str(insurance["phone"])
    return str(p.get("phone") or "")


def _maybe_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
