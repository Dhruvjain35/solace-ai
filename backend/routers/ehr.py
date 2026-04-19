"""Clinician-only EHR lookup.

Simulates an EHR system with 7 seeded records. Real deployment would swap the
DDB backend for a FHIR client (Epic sandbox, Cerner, Athena) — the router's
return shape maps 1:1 onto the FHIR `Patient` + `Condition` + `MedicationStatement`
+ `AllergyIntolerance` + `Encounter` bundle.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from db import storage
from lib.auth import audit, require_clinician
from lib.config import settings

log = logging.getLogger(__name__)

router = APIRouter()

EHR_TABLE = "solace-ehr-patients"


def _table():
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(EHR_TABLE)


def _from_ddb(obj):
    from decimal import Decimal  # noqa: PLC0415

    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


@router.get("/ehr/search")
def search(
    hospital_id: str = Path(...),
    name: str = Query("", min_length=0, max_length=80),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Fuzzy lookup: matches `name` against `name_lower` prefix on the GSI.

    Returns at most 5 records. Clinician's view, not the patient's.
    """
    audit(caller, "ehr.search", extra={"q": name})
    q = name.strip().lower()
    try:
        if not q:
            return {"results": []}
        resp = _table().query(
            IndexName="hospital_name-index",
            KeyConditionExpression="hospital_id = :h AND begins_with(name_lower, :q)",
            ExpressionAttributeValues={":h": hospital_id, ":q": q},
            Limit=5,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ehr search failed: %s", e)
        raise HTTPException(status_code=500, detail="EHR search unavailable")
    return {"results": [_from_ddb(r) for r in resp.get("Items", [])]}


@router.get("/ehr/lookup-by-patient/{patient_id}")
def lookup_by_patient(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Best-effort EHR match for a Solace patient — looks up by display name.

    If no match, returns `{"record": null, "reason": "..."}`. Clinician UI can show
    a "not in EHR" pill so the absence is surfaced, not hidden.
    """
    audit(caller, "ehr.lookup_by_patient", patient_id=patient_id)
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    name = (p.get("name") or "").strip().lower()
    if not name:
        return {"record": None, "reason": "patient has no name on file"}

    try:
        resp = _table().query(
            IndexName="hospital_name-index",
            KeyConditionExpression="hospital_id = :h AND name_lower = :n",
            ExpressionAttributeValues={":h": hospital_id, ":n": name},
            Limit=1,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ehr lookup_by_patient failed: %s", e)
        raise HTTPException(status_code=500, detail="EHR lookup unavailable")

    items = resp.get("Items", [])
    if not items:
        return {"record": None, "reason": f"no EHR record matching '{name}'"}
    return {"record": _from_ddb(items[0])}


@router.get("/ehr/{mrn}")
def get_by_mrn(
    hospital_id: str = Path(...),
    mrn: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ehr.get_by_mrn", extra={"mrn": mrn})
    resp = _table().get_item(Key={"mrn": mrn})
    item = resp.get("Item")
    if not item or item.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="EHR record not found")
    return _from_ddb(item)
