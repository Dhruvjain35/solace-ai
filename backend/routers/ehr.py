"""Clinician-only EHR lookup.

Simulates an EHR system with 7 seeded records. Real deployment would swap the
DDB backend for a FHIR client (Epic sandbox, Cerner, Athena) — the router's
return shape maps 1:1 onto the FHIR `Patient` + `Condition` + `MedicationStatement`
+ `AllergyIntolerance` + `Encounter` bundle.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from db import storage
from lib.auth import audit, require_clinician
from lib.config import settings
from services import ehr_gateway, fhir_patient_search

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
    """Best-effort EHR match for a Solace patient.

    Match priority — most reliable first, since patients reliably misspell names
    and use nicknames but rarely fake their insurance card:
      1. Insurance member_id (exact, scoped by provider when available)
      2. Insurance member_id alone
      3. Display name (lowercased, exact)
      4. Display name (lowercased, prefix)

    If no match, returns `{"record": null, "reason": "..."}` so the UI can show
    a "not in EHR" pill instead of silently hiding the gap.
    """
    audit(caller, "ehr.lookup_by_patient", patient_id=patient_id)
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    # 0. Fast-path: patient was already matched to a FHIR Patient at intake.
    # Fetch that exact resource by id — no name/DOB ambiguity.
    backend_choice = (os.environ.get("EHR_BACKEND") or "fhir").lower()
    if backend_choice in {"fhir", "auto"}:
        stored_fhir_id = (p.get("ehr_fhir_id") or "").strip()
        if stored_fhir_id:
            try:
                bundle = fhir_patient_search._search("Patient", {"_id": stored_fhir_id})
                entries = (bundle or {}).get("entry", []) or []
                if entries:
                    fhir_record = fhir_patient_search._enrich_patient(entries[0].get("resource") or {})
                    if fhir_record:
                        return {"record": fhir_record, "match_method": "fhir_stored_id"}
            except Exception as e:  # noqa: BLE001
                log.warning("FHIR stored-id lookup failed: %s", e)

    insurance_blob = p.get("insurance_info")
    member_id = ""
    provider = ""
    try:
        import json as _json  # noqa: PLC0415
        if isinstance(insurance_blob, str) and insurance_blob:
            ins = _json.loads(insurance_blob)
        elif isinstance(insurance_blob, dict):
            ins = insurance_blob
        else:
            ins = {}
        member_id = (ins.get("member_id") or "").strip()
        provider = (ins.get("provider") or "").strip()
    except Exception:  # noqa: BLE001
        ins = {}

    name = (p.get("name") or "").strip().lower()

    # 1+2. Try insurance member_id matching first — by far the most reliable key.
    if member_id:
        try:
            resp = _table().query(
                IndexName="hospital_member-index",
                KeyConditionExpression="hospital_id = :h AND insurance_member_id = :m",
                ExpressionAttributeValues={":h": hospital_id, ":m": member_id},
                Limit=5,
            )
            items = [_from_ddb(it) for it in resp.get("Items", [])]
            # If multiple share a member_id (rare, family plans), prefer matching provider.
            if items and provider:
                preferred = [it for it in items if (it.get("insurance") or "").lower().find(provider.lower()) != -1]
                if preferred:
                    return {"record": preferred[0], "match_method": "insurance_member_id+provider"}
            if items:
                return {"record": items[0], "match_method": "insurance_member_id"}
        except Exception as e:  # noqa: BLE001
            # GSI may not exist on older deployments — fall through to name match.
            log.debug("ehr insurance lookup failed (may be pre-GSI deploy): %s", e)

    # 3. Real FHIR sandbox lookup by first+last+dob (the default backend).
    # This is the path that powers the demo against real Synthea-generated patients.
    backend_choice = (os.environ.get("EHR_BACKEND") or "fhir").lower()
    if backend_choice in {"fhir", "auto"} and name:
        try:
            parts = name.split()
            given = parts[0] if parts else ""
            family = parts[-1] if len(parts) > 1 else ""
            dob = str(p.get("dob") or "")
            fhir_record = fhir_patient_search.match_by_demographics(
                given=given, family=family, birth_date=dob,
            )
            if fhir_record:
                return {"record": fhir_record, "match_method": "fhir_demographics"}
        except Exception as e:  # noqa: BLE001
            log.warning("FHIR lookup_by_patient failed, falling through: %s", e)

    # 4. DDB-mock name match (legacy demo path).
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
        return {"record": None, "reason": f"no EHR record matching '{name}'"}

    items = resp.get("Items", [])
    if not items:
        return {"record": None, "reason": f"no EHR record matching '{name}'"}
    return {"record": _from_ddb(items[0]), "match_method": "name_exact"}


# ----------------------------------------------------------------------------------
# EHR gateway write-back + diagnostics
#
# The fixed-path routes below MUST stay declared before the `/ehr/{mrn}` catch-all
# or FastAPI would route e.g. /ehr/vendor-status to get_by_mrn(mrn="vendor-status").
# ----------------------------------------------------------------------------------


def _ehr_config(hospital_id: str) -> dict[str, Any]:
    """Build the gateway `ehr_config` dict from a hospital's stored EHR settings.

    Looks the hospital up via db.storage and maps whatever EHR fields it carries
    onto the gateway routing contract (vendor / base_url / access_token / hl7).
    A hospital with no EHR config resolves to the generic mock back end so a
    write still lands somewhere demoable instead of hard-failing.
    """
    hospital = storage.get_hospital(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail="hospital not found")

    hl7_host = hospital.get("ehr_hl7_host") or ""
    hl7_port = hospital.get("ehr_hl7_port") or 0
    cfg: dict[str, Any] = {
        "vendor": hospital.get("ehr_vendor") or "",
        "base_url": hospital.get("ehr_base_url") or hospital.get("fhir_base_url") or "",
        "access_token": hospital.get("ehr_access_token") or "",
    }
    if hl7_host and hl7_port:
        cfg["hl7"] = {"host": hl7_host, "port": int(hl7_port)}
    return cfg


@router.get("/ehr/vendor-status")
def vendor_status(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Describe how this hospital's EHR write/read traffic will be routed.

    No external I/O — reports the resolved vendor, the back-end kind, whether the
    vendor adapter module is importable, and whether the path is `online` (real
    endpoint) or will land in the local mock store.
    """
    audit(caller, "ehr.vendor_status")
    cfg = _ehr_config(hospital_id)
    return ehr_gateway.vendor_status(cfg)


class EhrWriteBody(BaseModel):
    """Write-back request — a FHIR resource (or HL7-shaped resource) to push to
    the hospital's EHR. `dry_run` performs no external I/O and previews routing."""

    resource: dict[str, Any] = Field(..., description="FHIR resource dict with a resourceType")
    dry_run: bool = Field(False, description="Preview routing without external I/O")


@router.post("/ehr/write-back")
def write_back(
    hospital_id: str = Path(...),
    body: EhrWriteBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Push a FHIR resource into the hospital's EHR via the unified gateway.

    Routes by the hospital's configured vendor (epic / oracle / athena adapters,
    HL7 v2, or the generic FHIR writer). Transient transport failures are retried
    inside the gateway; a hard failure surfaces as HTTP 502.
    """
    resource = body.resource or {}
    resource_type = resource.get("resourceType")
    if not resource_type:
        raise HTTPException(
            status_code=400, detail="resource must include a resourceType",
        )
    audit(
        caller, "ehr.write_back",
        extra={"resource_type": resource_type, "dry_run": body.dry_run},
    )
    cfg = _ehr_config(hospital_id)
    try:
        result = ehr_gateway.write_resource(
            resource, ehr_config=cfg, dry_run=body.dry_run,
        )
    except ehr_gateway.EhrGatewayError as e:
        log.warning("EHR write-back failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"EHR write-back failed: {e.message}",
        ) from e
    except Exception as e:  # noqa: BLE001
        log.warning("EHR write-back error: %s", e)
        raise HTTPException(
            status_code=502, detail="EHR write-back failed",
        ) from e
    return result


class PatientMatchBody(BaseModel):
    """Demographics to match against a set of FHIR Patient candidate resources."""

    query: dict[str, Any] = Field(
        ..., description="given / family / birth_date / gender / phone / mrn",
    )
    candidates: list[dict[str, Any]] = Field(
        ..., description="Raw FHIR Patient resources to score against the query",
    )


@router.post("/ehr/patient-match")
def patient_match(
    hospital_id: str = Path(...),
    body: PatientMatchBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Score FHIR Patient candidates against supplied demographics.

    Surfaces the identity decision engine: returns the chosen status
    (`matched` / `needs_review` / `no_match`), a 0.0-1.0 confidence, a
    human-readable reason, and the winning Patient resource (or null).
    """
    audit(caller, "ehr.patient_match")
    try:
        return fhir_patient_search.match_status(body.query, body.candidates)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(
            status_code=400, detail=f"invalid patient-match input: {e}",
        ) from e


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
