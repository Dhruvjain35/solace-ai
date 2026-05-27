"""Workspace onboarding: admin setup wizard, teammate invites, request-to-join.

Mounted under `/api/{hospital_id}`. Admin-only endpoints require a clinician
JWT whose role is in accounts.ADMIN_ROLES. The request-to-join POST is public
(a clinician asking to be let in) but rate-limited; an admin approves it, which
mints a magic-link invite.

Two ways a clinician joins an existing workspace:
  1. Admin invites them directly  -> POST /invites
  2. They request access, admin approves -> POST /access-requests then /approve
Both converge on a single-use magic-link invite email (Phase 1 spine).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel

from db import storage
from lib import accounts, audit as _audit, blocklist, quota
from lib.auth import require_clinician
from lib.config import settings
from services import email as email_service

log = logging.getLogger(__name__)

router = APIRouter()

_ASSIGNABLE_ROLES = {"admin", "attending", "resident", "nurse", "clinician"}


def _require_admin(caller: dict) -> None:
    if caller.get("role") not in accounts.ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required.")


def _frontend_base(request: Request | None) -> str:
    if settings.app_base_url:
        return settings.app_base_url.rstrip("/")
    if request is not None:
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            return origin.split("/h/")[0].rstrip("/")
    return ""


def _send_invite(hospital_id: str, email: str, name: str, role: str, request: Request | None) -> dict:
    """Mint an invite magic token and email it. Returns the email send result."""
    raw = accounts.issue_magic_token(
        hospital_id=hospital_id, email=email, purpose="invite", role=role, name=name,
    )
    hospital = storage.get_hospital(hospital_id) or {}
    link = f"{_frontend_base(request)}/h/{hospital_id}/auth/verify?token={raw}"
    result = email_service.send_magic_link(
        to=email, link=link, hospital_name=hospital.get("name", hospital_id), purpose="invite",
    )
    if settings.email_dev_echo:
        result["dev_link"] = link
    return result


# ---- Teammate invites (admin) ------------------------------------------------------
class InviteBody(BaseModel):
    email: str
    name: str | None = None
    role: str = "clinician"


@router.post("/invites")
def create_invite(
    hospital_id: str = Path(...),
    body: InviteBody | None = None,
    request: Request = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    _require_admin(caller)
    if body is None or not body.email.strip():
        raise HTTPException(status_code=400, detail="email required")
    role = body.role if body.role in _ASSIGNABLE_ROLES else "clinician"
    email = body.email.strip()
    name = (body.name or email.split("@")[0]).strip()

    result = _send_invite(hospital_id, email, name, role, request)
    _audit.record(
        clinician_id=caller.get("clinician_id"), clinician_name=caller.get("name"),
        action="onboarding.invite_sent", status_code=200,
        extra={"hospital_id": hospital_id, "invited_email": email, "role": role,
               "delivered": result.get("delivered")},
    )
    resp = {"status": "invited", "email": email, "role": role}
    if "dev_link" in result:
        resp["dev_link"] = result["dev_link"]
    return resp


# ---- Care team listing (admin) -----------------------------------------------------
@router.get("/care-team")
def list_care_team(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    _require_admin(caller)
    members = [
        {
            "clinician_id": c.get("clinician_id"),
            "name": c.get("name"),
            "email": c.get("email"),
            "role": c.get("role"),
            "last_login_at": c.get("last_login_at"),
        }
        for c in accounts.list_clinicians(hospital_id)
    ]
    members.sort(key=lambda m: (m["role"] != "admin", (m.get("name") or "").lower()))
    return {"members": members, "count": len(members)}


# ---- Request to join (public) ------------------------------------------------------
class AccessRequestBody(BaseModel):
    email: str
    name: str
    note: str | None = None


@router.post("/access-requests")
def request_access(
    hospital_id: str = Path(...),
    body: AccessRequestBody | None = None,
    request: Request = None,
) -> dict:
    """A clinician asks to join a workspace. Public + rate-limited. Generic 200."""
    if body is None or not body.email.strip() or not body.name.strip():
        raise HTTPException(status_code=400, detail="name + email required")

    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "onboarding.access_request", source_ip=source_ip)

    # Only accept requests for a real workspace; respond generically either way.
    generic = {"status": "received", "message": "Your request was sent to the workspace admins."}
    if not storage.get_hospital(hospital_id):
        return generic

    accounts.create_access_request(
        hospital_id=hospital_id, email=body.email, name=body.name, note=body.note or "",
    )
    # Best-effort notify admins so they can approve.
    admins = accounts.list_admins(hospital_id)
    for admin in admins:
        if admin.get("email"):
            email_service.send_email(
                to=admin["email"],
                subject=f"Access request for {hospital_id} on Solace",
                html=f"<p>{body.name.strip()} ({body.email.strip()}) requested access to your "
                     f"Solace workspace. Review it in your onboarding panel.</p>",
                text=f"{body.name.strip()} ({body.email.strip()}) requested access. "
                     f"Approve or deny it in your Solace onboarding panel.",
            )
    _audit.record(
        clinician_id=None, clinician_name=body.name, action="onboarding.access_requested",
        source_ip=source_ip, status_code=200, extra={"hospital_id": hospital_id},
    )
    return generic


@router.get("/access-requests")
def list_requests(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    _require_admin(caller)
    return {"requests": accounts.list_access_requests(hospital_id, status="pending")}


@router.post("/access-requests/{request_id}/approve")
def approve_request(
    hospital_id: str = Path(...),
    request_id: str = Path(...),
    request: Request = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    _require_admin(caller)
    req = accounts.get_access_request(request_id)
    if not req or req.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"request already {req.get('status')}")

    result = _send_invite(hospital_id, req["email"], req.get("name", ""), "clinician", request)
    accounts.set_access_request_status(request_id, "approved", decided_by=caller.get("clinician_id"))
    _audit.record(
        clinician_id=caller.get("clinician_id"), clinician_name=caller.get("name"),
        action="onboarding.access_approved", status_code=200,
        extra={"hospital_id": hospital_id, "invited_email": req["email"]},
    )
    resp = {"status": "approved", "email": req["email"]}
    if "dev_link" in result:
        resp["dev_link"] = result["dev_link"]
    return resp


@router.post("/access-requests/{request_id}/deny")
def deny_request(
    hospital_id: str = Path(...),
    request_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    _require_admin(caller)
    req = accounts.get_access_request(request_id)
    if not req or req.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="request not found")
    accounts.set_access_request_status(request_id, "denied", decided_by=caller.get("clinician_id"))
    return {"status": "denied"}


# ---- Onboarding wizard state (admin) -----------------------------------------------
@router.get("/onboarding")
def onboarding_status(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    _require_admin(caller)
    hospital = storage.get_hospital(hospital_id) or {}
    team = accounts.list_clinicians(hospital_id)
    return {
        "hospital_id": hospital_id,
        "name": hospital.get("name", hospital_id),
        "onboarded": bool(hospital.get("onboarded", False)),
        "team_size": len(team),
        "pending_requests": len(accounts.list_access_requests(hospital_id, status="pending")),
        "patient_url": f"/h/{hospital_id}",
    }


@router.post("/onboarding/complete")
def complete_onboarding(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    _require_admin(caller)
    hospital = storage.get_hospital(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail="workspace not found")
    hospital["onboarded"] = True
    storage.put_hospital(hospital)
    _audit.record(
        clinician_id=caller.get("clinician_id"), clinician_name=caller.get("name"),
        action="onboarding.completed", status_code=200, extra={"hospital_id": hospital_id},
    )
    return {"status": "onboarded"}
