"""Clinician login + token introspection.

Login flow: clinician_name + PIN -> bcrypt verify -> JWT issued.
Brute-force protection: 5 failed attempts in 15 minutes = 30-minute lockout.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel

from lib import accounts, audit as _audit
from lib import blocklist, jwt_auth, quota
from lib.auth import require_clinician
from lib.config import settings
from db import storage
from services import email as email_service

log = logging.getLogger(__name__)

router = APIRouter()


class LoginBody(BaseModel):
    clinician_name: str
    pin: str
    # Optional TOTP second factor. Required only for clinicians who have
    # confirmed MFA enrollment; clinicians without MFA log in as before
    # (backward compatible — the demo flow is unaffected).
    mfa_code: str | None = None


class MfaVerifyBody(BaseModel):
    code: str


class MagicRequestBody(BaseModel):
    email: str


class MagicVerifyBody(BaseModel):
    token: str


def _client_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    source_ip = request.headers.get(
        "x-forwarded-for", request.client.host if request.client else None
    )
    return source_ip, request.headers.get("user-agent")


def _frontend_base(request: Request | None) -> str:
    """Origin the emailed link points at: configured app_base_url, else request origin."""
    if settings.app_base_url:
        return settings.app_base_url.rstrip("/")
    if request is not None:
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            return origin.split("/h/")[0].rstrip("/")
    return ""


@router.post("/auth/login")
def login(
    hospital_id: str = Path(...),
    body: LoginBody | None = None,
    request: Request = None,
) -> dict:
    if body is None or not body.clinician_name.strip() or not body.pin:
        raise HTTPException(status_code=400, detail="clinician_name + pin required")

    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")

    # SEC-003 pattern: per-IP rate limiting BEFORE any DB lookup or bcrypt work.
    # The per-account brute-force lockout below only protects a known account;
    # this layer caps credential-stuffing / enumeration sweeps that rotate the
    # clinician_name across many accounts from one identity.
    identity_hash = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    quota.check_and_consume(identity_hash, "auth.login", source_ip=source_ip)

    clinician = jwt_auth.find_clinician(hospital_id, body.clinician_name)
    if not clinician:
        # Burn a bcrypt-equivalent slice of CPU so an attacker cannot tell an
        # unknown clinician from a bad-PIN-on-known-clinician via timing.
        jwt_auth.dummy_verify()
        # Tick the abuse counter — repeated unknown-clinician hits from one
        # identity trip the auto-blocklist.
        blocklist.record_abuse(identity_hash, "auth.login_unknown_clinician")
        # Don't leak which field was wrong — both 'unknown clinician' and 'bad pin' = same 401
        _audit.record(
            clinician_id=None,
            clinician_name=body.clinician_name,
            action="auth.login_failed",
            source_ip=source_ip,
            status_code=401,
            extra={"reason": "unknown_clinician"},
        )
        raise HTTPException(status_code=401, detail="incorrect name or PIN")

    # Brute-force lockout check
    if jwt_auth.check_lockout(clinician["clinician_id"]):
        _audit.record(
            clinician_id=clinician["clinician_id"],
            clinician_name=clinician["name"],
            action="auth.login_locked_out",
            source_ip=source_ip,
            status_code=429,
            extra={"reason": "brute_force_lockout"},
        )
        raise HTTPException(
            status_code=429,
            detail="Account temporarily locked due to too many failed attempts. Try again in 30 minutes.",
        )

    if not jwt_auth.verify_pin(body.pin, clinician.get("pin_hash", "")):
        # Record failed attempt (may trigger per-account lockout)
        jwt_auth.record_failed_attempt(clinician["clinician_id"])
        # Also tick the per-identity abuse counter so a stuffer spreading
        # guesses thinly across many accounts still trips the blocklist.
        blocklist.record_abuse(identity_hash, "auth.login_bad_pin")
        _audit.record(
            clinician_id=clinician["clinician_id"],
            clinician_name=clinician["name"],
            action="auth.login_failed",
            source_ip=source_ip,
            status_code=401,
            extra={"reason": "bad_pin"},
        )
        raise HTTPException(status_code=401, detail="incorrect name or PIN")

    # Second factor (TOTP), enforced only for clinicians who have confirmed
    # MFA enrollment. A wrong/absent code on an MFA-enabled account is a failed
    # login: it ticks the same per-account lockout + per-identity abuse counters
    # as a bad PIN, and NO token is issued. SEC-002: the code is never logged.
    if jwt_auth.mfa_enabled(clinician):
        if not jwt_auth.verify_mfa_code(clinician, body.mfa_code):
            jwt_auth.record_failed_attempt(clinician["clinician_id"])
            blocklist.record_abuse(identity_hash, "auth.login_bad_mfa")
            _audit.record(
                clinician_id=clinician["clinician_id"],
                clinician_name=clinician["name"],
                action="auth.login_failed",
                source_ip=source_ip,
                status_code=401,
                extra={"reason": "mfa_required" if not body.mfa_code else "bad_mfa_code"},
            )
            # 401 with a distinct detail so the frontend can prompt for a code,
            # but the audit reason above stays internal.
            raise HTTPException(
                status_code=401,
                detail="A valid authenticator code is required.",
            )

    # Success — clear any failed attempt counter and issue token
    jwt_auth.clear_failed_attempts(clinician["clinician_id"])
    token, sess = jwt_auth.issue_token(clinician)
    jwt_auth.update_last_login(clinician["clinician_id"])
    _audit.record(
        clinician_id=clinician["clinician_id"],
        clinician_name=clinician["name"],
        action="auth.login_success",
        source_ip=source_ip,
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


@router.post("/auth/magic/request")
def magic_request(
    hospital_id: str = Path(...),
    body: MagicRequestBody | None = None,
    request: Request = None,
) -> dict:
    """Email a single-use sign-in link to a known clinician.

    Always returns the same 200 envelope whether or not the email maps to a
    clinician — no account-enumeration oracle. A token is only minted + emailed
    when the (hospital, email) pair actually resolves to a clinician.
    """
    if body is None or not body.email.strip():
        raise HTTPException(status_code=400, detail="email required")

    source_ip, user_agent = _client_meta(request)
    identity_hash = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    quota.check_and_consume(identity_hash, "auth.magic_request", source_ip=source_ip)

    # Generic response — identical on hit and miss.
    response: dict = {"status": "sent", "message": "If that email is registered, a sign-in link is on its way."}

    clinician = accounts.find_clinician_by_email(hospital_id, body.email)
    if not clinician:
        blocklist.record_abuse(identity_hash, "auth.magic_unknown_email")
        _audit.record(
            clinician_id=None, clinician_name=None, action="auth.magic_request_unknown",
            source_ip=source_ip, status_code=200, extra={"hospital_id": hospital_id},
        )
        return response

    hospital = storage.get_hospital(hospital_id) or {}
    hospital_name = hospital.get("name", hospital_id)
    raw = accounts.issue_magic_token(hospital_id=hospital_id, email=body.email, purpose="login")
    link = f"{_frontend_base(request)}/h/{hospital_id}/auth/verify?token={raw}"
    send_result = email_service.send_magic_link(
        to=body.email, link=link, hospital_name=hospital_name, purpose="login"
    )
    _audit.record(
        clinician_id=clinician["clinician_id"], clinician_name=clinician.get("name"),
        action="auth.magic_request_sent", source_ip=source_ip, status_code=200,
        extra={"provider": send_result.get("provider"), "delivered": send_result.get("delivered")},
    )
    # email_dev_echo (local/sandbox only) surfaces the link so the flow is testable.
    if "dev_link" in send_result:
        response["dev_link"] = send_result["dev_link"]
    return response


@router.post("/auth/magic/verify")
def magic_verify(
    hospital_id: str = Path(...),
    body: MagicVerifyBody | None = None,
    request: Request = None,
) -> dict:
    """Redeem a single-use magic link → issue a JWT.

    Handles both `login` (clinician must exist) and `invite` (account is
    created on first redeem, carrying the invited role/name).
    """
    if body is None or not body.token.strip():
        raise HTTPException(status_code=400, detail="token required")

    source_ip, _ua = _client_meta(request)
    identity_hash = quota.identity_of(source_ip, request.headers.get("user-agent") if request else None)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    quota.check_and_consume(identity_hash, "auth.magic_verify", source_ip=source_ip)

    rec = accounts.consume_magic_token(body.token)
    if not rec or rec.get("hospital_id") != hospital_id:
        blocklist.record_abuse(identity_hash, "auth.magic_bad_token")
        _audit.record(
            clinician_id=None, clinician_name=None, action="auth.magic_verify_failed",
            source_ip=source_ip, status_code=401, extra={"reason": "invalid_or_expired"},
        )
        raise HTTPException(status_code=401, detail="This link is invalid or has expired. Request a new one.")

    if rec.get("purpose") == "invite":
        clinician = accounts.create_clinician(
            hospital_id=hospital_id,
            email=rec["email"],
            name=rec.get("name") or rec["email"].split("@")[0],
            role=rec.get("role", "clinician"),
        )
    else:
        clinician = accounts.find_clinician_by_email(hospital_id, rec["email"])
        if not clinician:
            raise HTTPException(status_code=401, detail="This link is invalid or has expired. Request a new one.")

    token, sess = jwt_auth.issue_token(clinician)
    jwt_auth.update_last_login(clinician["clinician_id"])
    _audit.record(
        clinician_id=clinician["clinician_id"], clinician_name=clinician.get("name"),
        action="auth.magic_verify_success", source_ip=source_ip, status_code=200,
        extra={"purpose": rec.get("purpose")},
    )
    return {
        "token": token,
        "clinician_id": sess.clinician_id,
        "name": sess.name,
        "role": sess.role,
        "hospital_id": sess.hospital_id,
        "expires_at": sess.exp,
    }


@router.post("/auth/mfa/enroll")
def mfa_enroll(
    hospital_id: str = Path(...),
    request: Request = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    """Provision a TOTP secret for the authenticated clinician.

    Returns the base32 secret + otpauth:// URI ONCE so the client can render a
    QR code. MFA is not active until POST /auth/mfa/verify confirms a live code.
    SEC-002: the secret / URI are returned to the caller but never logged; the
    audit entry records only that enrollment was initiated.
    """
    cid = caller["clinician_id"]
    account = caller.get("name") or cid
    enrollment = jwt_auth.enroll_mfa(cid, account=account, issuer="Solace")
    from lib.auth import audit as _audit_call  # noqa: PLC0415

    _audit_call(
        caller,
        "auth.mfa_enroll_initiated",
        request=request,
        status_code=200,
    )
    return {
        "secret": enrollment["secret"],
        "otpauth_uri": enrollment["otpauth_uri"],
        "issuer": "Solace",
        "account": account,
    }


@router.post("/auth/mfa/verify")
def mfa_verify(
    hospital_id: str = Path(...),
    body: MfaVerifyBody | None = None,
    request: Request = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    """Confirm a TOTP enrollment by validating a live code; enables MFA on success."""
    if body is None or not body.code.strip():
        raise HTTPException(status_code=400, detail="code required")

    cid = caller["clinician_id"]
    from lib.auth import audit as _audit_call  # noqa: PLC0415

    if not jwt_auth.confirm_mfa(cid, body.code.strip()):
        _audit_call(
            caller,
            "auth.mfa_verify_failed",
            request=request,
            status_code=400,
            extra={"reason": "bad_or_unprovisioned_code"},
        )
        raise HTTPException(status_code=400, detail="Incorrect authenticator code. Try again.")

    _audit_call(caller, "auth.mfa_enabled", request=request, status_code=200)
    return {"mfa_enabled": True}


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
