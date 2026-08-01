"""Patient identity scan endpoints.

Powers the optional first-step ID scan in the patient flow:
  - POST /api/{hospital_id}/scan-id           — OCR a driver's license image
  - POST /api/{hospital_id}/identity/lookup   — match name+DOB+license against
                                                the connected EHR; returns
                                                medical info for prefill if hit

Both endpoints are unauthenticated — patients use them, no clinician PIN.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Path, Request, UploadFile
from pydantic import BaseModel

from db import storage
from lib import blocklist, consent, quota, uploads
from lib.config import settings
from services import fhir_patient_search, id_ocr

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/scan-id")
async def scan_id(
    hospital_id: str = Path(...),
    image_file: UploadFile = File(...),
    consent_granted: str | None = Form(None, max_length=16),
    request: Request = None,
) -> dict:
    """OCR a US driver's license / state ID via Claude vision."""
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
    identity_hash = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    quota.check_and_consume(identity_hash, "scan_insurance", source_ip=source_ip)
    # SEC-004 / HIPAA §164.508. This endpoint is unauthenticated and sends a
    # photograph of a government ID — name, address, date of birth, licence
    # number, face — to a third-party model. Of everything the patient hands us
    # this is the most identifying, and it was the last thing to get a gate.
    consent.require(
        consent_granted,
        action="abuse.scan_id_no_consent",
        identity=identity_hash,
        source_ip=source_ip,
        detail="Consent required before an ID photo can be read by AI.",
    )
    raw_bytes = await uploads.read_and_validate(image_file, "image", source_ip=source_ip)
    fields = id_ocr.extract(raw_bytes, mime_type="image/jpeg")
    if "error" in fields:
        return {"success": False, **fields}
    return {"success": True, "fields": fields}


class IdentityLookupBody(BaseModel):
    first_name: str = ""
    last_name: str = ""
    dob: str = ""              # YYYY-MM-DD
    license_number: str = ""
    issuing_state: str = ""
    insurance_member_id: str = ""
    insurance_provider: str = ""


@router.post("/identity/lookup")
def identity_lookup(
    hospital_id: str = Path(...),
    body: IdentityLookupBody | None = None,
    request: Request = None,
) -> dict[str, Any]:
    """Best-effort EHR lookup by ID-derived identity. Returns the patient's
    EHR record + a prefill payload so the intake form can pre-populate.

    Match priority (most specific first):
      1. license_number + issuing_state (rare in EHR but exact when present)
      2. last_name + dob (most reliable common path)
      3. first_name + last_name + dob (fuzzy fallback)

    No match: returns `{"matched": false}` so the UI can continue normal flow.
    """
    # SEC-003 pattern (same as scan_id above): this endpoint is unauthenticated
    # and returns PHI from the EHR, so it is a prime PHI-enumeration surface.
    # Enforce the blocklist + per-identity quota before any request parsing or
    # EHR query, exactly as scan_id does.
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")
    identity_hash = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    quota.check_and_consume(identity_hash, "identity.lookup", source_ip=source_ip)

    if body is None:
        raise HTTPException(status_code=400, detail="request body required")
    has_name = bool(body.first_name and body.last_name)
    has_member_id = bool(body.insurance_member_id)
    if not (has_name or has_member_id):
        raise HTTPException(
            status_code=400,
            detail="provide either first_name+last_name or insurance_member_id",
        )

    # Backend selection — controlled by EHR_BACKEND env var:
    #   "fhir"    → hit the real FHIR sandbox / production endpoint only (default)
    #   "mock"    → only the DDB-seeded fake EHR records (legacy demo)
    #   "auto"    → FHIR first, mock as fallback if FHIR misses
    backend_choice = (os.environ.get("EHR_BACKEND") or "fhir").lower()

    record: dict | None = None
    method = ""

    if backend_choice in {"fhir", "auto"}:
        # Path 1: name + DOB (most reliable when both present)
        if has_name:
            try:
                record = fhir_patient_search.match_by_demographics(
                    given=body.first_name,
                    family=body.last_name,
                    birth_date=body.dob,
                )
                if record:
                    method = "fhir_demographics"
            except Exception as e:  # noqa: BLE001
                log.warning("FHIR identity lookup (demographics) failed: %s", e)
        # Path 2: insurance member_id (when ID didn't match or wasn't scanned)
        if (not record) and has_member_id:
            try:
                record = fhir_patient_search.match_by_member_id(
                    body.insurance_member_id, provider_hint=body.insurance_provider,
                )
                if record:
                    method = "fhir_member_id"
            except Exception as e:  # noqa: BLE001
                log.warning("FHIR identity lookup (member_id) failed: %s", e)

    if (not record) and backend_choice in {"mock", "auto"} and settings.solace_mode == "aws":
        record = _ehr_match(hospital_id, body)
        if record:
            method = record.pop("_match_method", "name+dob")

    if not record:
        return {"matched": False, "reason": "no EHR record matched"}

    prefill = _record_to_prefill(record)
    return {
        "matched": True,
        "match_method": method or "fhir_demographics",
        "ehr_record": record,
        "prefill": prefill,
    }


# --- helpers -------------------------------------------------------------------


def _ehr_match(hospital_id: str, body: IdentityLookupBody) -> dict | None:
    """Walk the EHR table looking for a match. Falls through gracefully if
    a GSI is missing — older deployments may not have indexed dob."""
    import boto3  # noqa: PLC0415
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    table = boto3.resource("dynamodb", region_name=settings.aws_region).Table("solace-ehr-patients")
    name_lower = f"{body.first_name} {body.last_name}".strip().lower()

    try:
        resp = table.query(
            IndexName="hospital_name-index",
            KeyConditionExpression=Key("hospital_id").eq(hospital_id) & Key("name_lower").eq(name_lower),
            Limit=5,
        )
        items = [_from_ddb(it) for it in resp.get("Items", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("EHR identity lookup failed: %s", e)
        return None

    if not items:
        return None

    # Narrow further by DOB if we have one — same name multiple records is common.
    if body.dob:
        for it in items:
            if (it.get("dob") or "") == body.dob:
                it["_match_method"] = "name+dob"
                return it
    # Fall back to first match — name alone, single result.
    if len(items) == 1:
        items[0]["_match_method"] = "name_only"
        return items[0]
    return None


def _record_to_prefill(record: dict) -> dict:
    """Map the EHR record into the medical_info shape the patient intake form
    expects. Lets the form arrive pre-filled with the patient's known
    allergies / meds / conditions."""
    def _filter_none(arr):
        return [str(x) for x in (arr or []) if x and str(x).lower() != "none"]

    age = None
    dob = record.get("dob") or ""
    if dob:
        try:
            from datetime import date  # noqa: PLC0415
            y, m, d = (int(x) for x in dob.split("-"))
            today = date.today()
            age = today.year - y - ((today.month, today.day) < (m, d))
        except Exception:  # noqa: BLE001
            age = None

    return {
        "age": age,
        "sex": _normalize_sex(record.get("sex", "")),
        "allergies": _filter_none(record.get("allergies")),
        "medications": _filter_none(record.get("medications")),
        "conditions": _filter_none(record.get("conditions")),
        "insurance_hint": record.get("insurance", ""),
        "emergency_contact": record.get("emergency_contact", ""),
        "primary_care_provider": record.get("primary_care_provider", ""),
        "prior_visits_count": len(record.get("prior_visits") or []),
    }


def _normalize_sex(s: str) -> str | None:
    if not s:
        return None
    s = s.lower()
    if s in ("m", "male"):
        return "male"
    if s in ("f", "female"):
        return "female"
    return "other"


def _from_ddb(obj):
    from decimal import Decimal  # noqa: PLC0415

    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


# Placate linter — storage import currently unused but we may want hospital validation
_ = storage
