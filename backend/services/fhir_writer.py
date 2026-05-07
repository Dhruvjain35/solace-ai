"""FHIR write-back foundation.

A vendor-abstract write client that builds DocumentReference, Condition,
AllergyIntolerance, Observation, and Immunization resources from Solace's
internal data shapes, then dispatches to a configurable FHIR base URL via
SMART-on-FHIR access token.

Local fallback: when no FHIR_BASE_URL is configured, writes are persisted to a
local "FHIR mock store" that the dashboard can render exactly like a real EHR
view. This means the demo experience is end-to-end without external accounts.

Vendor adapters extend this with the vendor-specific quirks:
  - Epic: Condition.$add operation on the problem list
  - Athena: proprietary REST API for problems (`/chart/{patientid}/problems`)
  - Oracle Health: standard FHIR with permission-gated writes
  - OpenEMR: open FHIR R4
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# ---- Local FHIR mock store (for demo / dev) --------------------------------------
_MOCK: dict[str, list[dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _store_local(resource_type: str, resource: dict[str, Any]) -> dict[str, Any]:
    bucket = _MOCK.setdefault(resource_type, [])
    rid = resource.get("id") or str(uuid.uuid4())
    resource["id"] = rid
    resource.setdefault("meta", {})["lastUpdated"] = _now_iso()
    bucket.append(resource)
    return {
        "resourceType": resource_type,
        "id": rid,
        "url": f"local://{resource_type}/{rid}",
        "stored": "mock",
    }


def list_local(resource_type: str | None = None) -> list[dict[str, Any]]:
    if resource_type:
        return list(_MOCK.get(resource_type, []))
    out = []
    for rt, items in _MOCK.items():
        for r in items:
            out.append({"resourceType": rt, **r})
    return out


def clear_local() -> None:
    _MOCK.clear()


# ---- Resource builders -----------------------------------------------------------
def build_document_reference(
    *,
    patient_ref: str,
    note_text: str,
    note_pdf_bytes: bytes | None = None,
    type_code: str = "11506-3",  # LOINC: Progress note
    type_display: str = "Progress note",
    author_display: str = "Solace AI scribe",
) -> dict[str, Any]:
    content = []
    if note_pdf_bytes:
        content.append({
            "attachment": {
                "contentType": "application/pdf",
                "data": base64.b64encode(note_pdf_bytes).decode("ascii"),
                "creation": _now_iso(),
            }
        })
    content.append({
        "attachment": {
            "contentType": "text/plain",
            "data": base64.b64encode(note_text.encode("utf-8")).decode("ascii"),
            "creation": _now_iso(),
        }
    })
    return {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": type_code, "display": type_display}]},
        "subject": {"reference": patient_ref},
        "date": _now_iso(),
        "author": [{"display": author_display}],
        "content": content,
    }


def build_condition(*, patient_ref: str, icd10: str, display: str, clinical_status: str = "active") -> dict[str, Any]:
    return {
        "resourceType": "Condition",
        "subject": {"reference": patient_ref},
        "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": clinical_status}]},
        "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "provisional"}]},
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": icd10, "display": display}]},
        "recordedDate": _now_iso(),
    }


def build_allergy(*, patient_ref: str, substance_display: str, reaction: str = "", severity: str = "moderate") -> dict[str, Any]:
    return {
        "resourceType": "AllergyIntolerance",
        "patient": {"reference": patient_ref},
        "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]},
        "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed"}]},
        "code": {"text": substance_display},
        "recordedDate": _now_iso(),
        "reaction": [{"manifestation": [{"text": reaction}], "severity": severity}] if reaction else [],
    }


def build_observation_vital(*, patient_ref: str, code_loinc: str, display: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code_loinc, "display": display}]},
        "subject": {"reference": patient_ref},
        "effectiveDateTime": _now_iso(),
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org"},
    }


def build_observation_social(*, patient_ref: str, code_loinc: str, display: str, value_text: str) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "social-history"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code_loinc, "display": display}]},
        "subject": {"reference": patient_ref},
        "effectiveDateTime": _now_iso(),
        "valueString": value_text,
    }


def build_immunization(*, patient_ref: str, vaccine_cvx: str, vaccine_display: str) -> dict[str, Any]:
    return {
        "resourceType": "Immunization",
        "status": "completed",
        "vaccineCode": {"coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": vaccine_cvx, "display": vaccine_display}]},
        "patient": {"reference": patient_ref},
        "occurrenceDateTime": _now_iso(),
    }


# ---- Dispatcher ------------------------------------------------------------------
def write(resource: dict[str, Any], *, fhir_base_url: str | None = None, access_token: str | None = None) -> dict[str, Any]:
    """Send a FHIR resource. Returns {ok, id, url, stored}."""
    rt = resource.get("resourceType")
    base = fhir_base_url or os.getenv("FHIR_BASE_URL") or ""
    if not base:
        return _store_local(rt, resource)
    try:  # pragma: no cover (no remote in unit tests)
        import requests
        headers = {"Content-Type": "application/fhir+json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        url = f"{base.rstrip('/')}/{rt}"
        r = requests.post(url, headers=headers, json=resource, timeout=10)
        r.raise_for_status()
        body = r.json()
        return {"ok": True, "id": body.get("id"), "url": r.headers.get("Location") or url, "stored": "remote"}
    except Exception as e:
        log.warning("FHIR write failed (%s): %s — falling back to local store", rt, e)
        return _store_local(rt, resource)
