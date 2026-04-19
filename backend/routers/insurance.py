"""POST /api/{hospital_id}/scan-insurance — OCR a patient's insurance card."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Path, Request, UploadFile

from lib import blocklist, quota, uploads
from services import insurance_ocr

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/scan-insurance")
async def scan_insurance(
    hospital_id: str = Path(...),
    image_file: UploadFile = File(...),
    request: Request = None,
) -> dict:
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "scan_insurance", source_ip=source_ip)
    bytes_ = await uploads.read_and_validate(image_file, "image", source_ip=source_ip)
    # Always JPEG after sanitize (EXIF stripped, decoded + re-encoded)
    result = insurance_ocr.extract(bytes_, mime_type="image/jpeg")
    if result.get("error"):
        return {"success": False, **result}
    return {"success": True, "fields": result}
