"""Unauthenticated patient-facing endpoints that live outside /intake-proper.

- POST /start-intake — issues a one-use nonce the QR landing page must request
  before the patient can submit /intake.
"""
from __future__ import annotations

from fastapi import APIRouter, Path, Request

from lib import blocklist, intake_nonce, quota

router = APIRouter()


@router.post("/start-intake")
def start_intake(hospital_id: str = Path(...), request: Request = None) -> dict:
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "intake.start", source_ip=source_ip)
    return intake_nonce.issue(hospital_id, source_ip=source_ip, user_agent=user_agent)
