"""Clinician login + token introspection."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel

from lib import audit as _audit
from lib import jwt_auth
from lib.auth import require_clinician

log = logging.getLogger(__name__)

router = APIRouter()


class LoginBody(BaseModel):
    clinician_name: str
    pin: str


@router.post("/auth/login")
def login(
    hospital_id: str = Path(...),
    body: LoginBody | None = None,
    request: Request = None,
) -> dict:
    if body is None or not body.clinician_name.strip() or not body.pin:
        raise HTTPException(status_code=400, detail="clinician_name + pin required")

    clinician = jwt_auth.find_clinician(hospital_id, body.clinician_name)
    if not clinician:
        # Don't leak which field was wrong — both 'unknown clinician' and 'bad pin' = same 401
        _audit.record(
            clinician_id=None,
            clinician_name=body.clinician_name,
            action="auth.login_failed",
            source_ip=(request.headers.get("x-forwarded-for") if request else None),
            status_code=401,
            extra={"reason": "unknown_clinician"},
        )
        raise HTTPException(status_code=401, detail="incorrect name or PIN")

    if not jwt_auth.verify_pin(body.pin, clinician.get("pin_hash", "")):
        _audit.record(
            clinician_id=clinician["clinician_id"],
            clinician_name=clinician["name"],
            action="auth.login_failed",
            source_ip=(request.headers.get("x-forwarded-for") if request else None),
            status_code=401,
            extra={"reason": "bad_pin"},
        )
        raise HTTPException(status_code=401, detail="incorrect name or PIN")

    token, sess = jwt_auth.issue_token(clinician)
    jwt_auth.update_last_login(clinician["clinician_id"])
    _audit.record(
        clinician_id=clinician["clinician_id"],
        clinician_name=clinician["name"],
        action="auth.login_success",
        source_ip=(request.headers.get("x-forwarded-for") if request else None),
        status_code=200,
    )
    return {
        "token": token,
        "clinician_id": sess.clinician_id,
        "name": sess.name,
        "role": sess.role,
        "hospital_id": sess.hospital_id,
        "expires_at": sess.exp,
    }


@router.get("/auth/whoami")
def whoami(hospital_id: str = Path(...), caller: dict = Depends(require_clinician)) -> dict:
    """Let the frontend verify its stored token is still valid without doing a full API call."""
    return {
        "clinician_id": caller.get("clinician_id"),
        "name": caller.get("name"),
        "role": caller.get("role"),
        "hospital_id": caller.get("hospital_id"),
        "auth_method": caller.get("auth_method"),
    }
