"""POST /api/{hospital_id}/scan-insurance — OCR a patient's insurance card.

HIPAA §164.508: consent must be granted BEFORE the insurance card image is
sent to any third-party AI processor (Claude Vision / Bedrock).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Path, Request, UploadFile

from lib import blocklist, quota, uploads
from services import insurance_ocr

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/scan-insurance")
async def scan_insurance(
    hospital_id: str = Path(...),
    image_file: UploadFile = File(...),
    consent_granted: str | None = Form(None),
    request: Request = None,
) -> dict:
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)

    # HIPAA §164.508 consent gate — insurance card contains PHI (member name,
    # member ID, group number) that will be sent to Claude Vision for OCR.
    if str(consent_granted or "").lower() not in {"true", "1", "yes"}:
        from lib import audit as _audit  # noqa: PLC0415

        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.insurance_scan_no_consent",
            source_ip=source_ip, status_code=403,
            extra={"identity": identity},
        )
        raise HTTPException(
            status_code=403,
            detail="Consent required before insurance card can be processed by AI.",
        )

    quota.check_and_consume(identity, "scan_insurance", source_ip=source_ip)
    bytes_ = await uploads.read_and_validate(image_file, "image", source_ip=source_ip)
    # Always JPEG after sanitize (EXIF stripped, decoded + re-encoded)
    result = insurance_ocr.extract(bytes_, mime_type="image/jpeg")
    if result.get("error"):
        return {"success": False, **result}
    return {"success": True, "fields": result}
