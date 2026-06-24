"""Vision OCR endpoint — clinician-only document/image text extraction.

POST /api/{hospital_id}/vision
    {"image_base64": str, "mime_type": str} -> {"text": str}

Backed by Azure Document Intelligence prebuilt-read (services/azure_ocr.py).
Quota'd per identity ("vision.ocr"), audited, and capped at 8MB decoded. When
Azure DI is not configured the endpoint answers 503 with a clear message.
"""
from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from lib import quota
from lib.auth import audit, require_clinician
from services import azure_ocr

log = logging.getLogger(__name__)

router = APIRouter()

MAX_DECODED_BYTES = 8 * 1024 * 1024  # 8MB per document

ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/webp", "image/tiff",
    "image/bmp", "image/heif", "application/pdf",
}


class VisionBody(BaseModel):
    image_base64: str = Field(..., min_length=1)
    mime_type: str = Field(..., min_length=3, max_length=100)


def _decode_image(image_base64: str) -> bytes:
    """Decode the payload, enforcing the 8MB cap BEFORE materializing it."""
    payload = image_base64
    if payload.startswith("data:") and "," in payload:  # tolerate data URLs
        payload = payload.split(",", 1)[1]
    # base64 inflates by 4/3 — a cheap pre-check rejects oversize input early.
    if len(payload) * 3 // 4 > MAX_DECODED_BYTES + 4:
        raise HTTPException(
            status_code=413,
            detail=f"document exceeds the {MAX_DECODED_BYTES // (1024 * 1024)}MB limit",
        )
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="image_base64 is not valid base64") from None
    if not data:
        raise HTTPException(status_code=400, detail="empty document")
    if len(data) > MAX_DECODED_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"document exceeds the {MAX_DECODED_BYTES // (1024 * 1024)}MB limit",
        )
    return data


@router.post("/vision")
def vision_ocr(
    request: Request,
    hospital_id: str = Path(...),
    body: VisionBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    mime = body.mime_type.strip().lower()
    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported mime_type '{mime}' — allowed: {sorted(ALLOWED_MIME_TYPES)}",
        )
    data = _decode_image(body.image_base64)

    source_ip = request.headers.get("x-forwarded-for",
                                    request.client.host if request.client else None)
    user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    quota.check_and_consume(identity, "vision.ocr", source_ip=source_ip)

    audit(caller, "vision.ocr", request=request,
          extra={"bytes": len(data), "mime_type": mime})

    if not azure_ocr.configured():
        raise HTTPException(
            status_code=503,
            detail=("Vision OCR is not configured on this deployment — set "
                    "AZURE_DI_ENDPOINT and AZURE_DI_KEY to enable it."),
        )
    try:
        text = azure_ocr.read_text(data, mime)
    except azure_ocr.AzureOcrNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except azure_ocr.AzureOcrError as e:
        log.warning("vision OCR failed: %s", e)
        raise HTTPException(status_code=502, detail=f"OCR failed: {e}") from e
    return {"text": text}
