"""Clinician auth — accepts JWT (Bearer) or legacy X-Clinician-PIN during transition.

The new path (JWT) is preferred and carries a clinician identity; legacy path is a
hospital-wide shared PIN and logs as `anonymous` in the audit trail.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, Path, Request

from db import storage
from lib import audit as _audit
from lib import jwt_auth

log = logging.getLogger(__name__)


def _legacy_pin_check(hospital_id: str, pin: str) -> dict:
    hospital = storage.get_hospital(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail="hospital not found")
    stored = hospital.get("clinician_pin", "")
    if not hmac.compare_digest(str(pin), str(stored)):
        raise HTTPException(status_code=401, detail="incorrect PIN")
    return hospital


def verify_clinician(
    hospital_id: str,
    pin: str | None = None,
    *,
    authorization: str | None = None,
    request: Request | None = None,
) -> dict:
    """Authenticate the caller. Returns a dict with at least `clinician_id` + `name`.

    Preferred: `Authorization: Bearer <jwt>` header.
    Fallback: legacy `X-Clinician-PIN: <pin>` header for the last release.
    """
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()

    if bearer:
        try:
            sess = jwt_auth.verify_token(bearer)
        except jwt_auth.AuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        if sess.hospital_id != hospital_id:
            raise HTTPException(status_code=403, detail="hospital mismatch")
        return {
            "clinician_id": sess.clinician_id,
            "name": sess.name,
            "role": sess.role,
            "hospital_id": sess.hospital_id,
            "auth_method": "jwt",
        }

    if pin:
        hospital = _legacy_pin_check(hospital_id, pin)
        return {
            "clinician_id": "legacy-pin",
            "name": "Legacy PIN user",
            "role": "clinician",
            "hospital_id": hospital_id,
            "hospital": hospital,
            "auth_method": "legacy_pin",
        }

    raise HTTPException(status_code=401, detail="Authorization required (Bearer token or X-Clinician-PIN)")


def audit(
    caller: dict,
    action: str,
    *,
    patient_id: str | None = None,
    request: Request | None = None,
    status_code: int | None = None,
    extra: dict | None = None,
) -> None:
    """Record an audit entry for the given authenticated call. Safe-by-default."""
    source_ip = None
    request_id = None
    if request is not None:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        request_id = request.headers.get("x-amzn-trace-id") or request.headers.get("x-request-id")
    _audit.record(
        clinician_id=caller.get("clinician_id"),
        clinician_name=caller.get("name"),
        action=action,
        patient_id=patient_id,
        source_ip=source_ip,
        request_id=request_id,
        status_code=status_code,
        extra=extra,
    )


# ---- FastAPI dependency for authenticated routes ----
async def require_clinician(
    request: Request,
    hospital_id: str = Path(...),
    authorization: str | None = Header(None, alias="Authorization"),
    x_clinician_pin: str | None = Header(None, alias="X-Clinician-PIN"),
) -> dict:
    caller = verify_clinician(
        hospital_id, x_clinician_pin, authorization=authorization, request=request
    )
    request.state.caller = caller
    return caller


# Backward-compat shim — lets existing routers that imported `verify_clinician as _auth`
# with the old 2-arg signature keep working until we refactor them to Depends().
def verify_clinician_legacy(hospital_id: str, pin: str | None) -> dict:
    """Old signature: (hospital_id, pin) → hospital dict. No JWT support."""
    return verify_clinician(hospital_id, pin)
