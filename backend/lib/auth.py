"""Clinician auth — JWT Bearer tokens only.

Legacy X-Clinician-PIN header support has been removed. All clinician
endpoints require `Authorization: Bearer <jwt>`. Tokens are issued via
POST /auth/login with clinician_name + bcrypt-hashed PIN.
"""
from __future__ import annotations

import logging

from fastapi import Header, HTTPException, Path, Request

from lib import audit as _audit
from lib import jwt_auth

log = logging.getLogger(__name__)


def verify_clinician(
    hospital_id: str,
    *,
    authorization: str | None = None,
    request: Request | None = None,
) -> dict:
    """Authenticate the caller via JWT Bearer token.

    Returns a dict with `clinician_id`, `name`, `role`, `hospital_id`, `auth_method`.
    """
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()

    if not bearer:
        raise HTTPException(
            status_code=401,
            detail="Authorization required (Bearer token)",
        )

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
) -> dict:
    caller = verify_clinician(
        hospital_id, authorization=authorization, request=request
    )
    request.state.caller = caller
    return caller


# Backward-compat shim — lets existing routers that imported `verify_clinician as _auth`
# with the old 2-arg signature keep working until we refactor them to Depends().
def verify_clinician_legacy(hospital_id: str, pin: str | None) -> dict:
    """Old signature shim. Raises 401 — forces callers to upgrade to JWT."""
    raise HTTPException(
        status_code=401,
        detail="Legacy PIN authentication has been removed. Use Bearer token.",
    )
