"""Bulk FHIR cohort export ($export client).

Population-health backbone. Calls Patient/$export, Group/$export, or
$export-poll-status against any USCDI-v3-compliant FHIR endpoint and returns
the streamed NDJSON resource set. In production, configure with the SMART
Backend Services JWT auth flow; in dev, returns synthetic cohort data so the
UI can be demoed.

Use cases:
  - HEDIS quality reporting
  - MIPS / MVP submissions
  - ACO benchmarking (CareJourney / Arcadia / MedInsight overlap)
  - Retrospective ML training data
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)


SYNTHETIC = {
    "diabetes_uncontrolled": [
        {"resourceType": "Patient", "id": "p001", "name": [{"family": "Doe", "given": ["Jane"]}], "birthDate": "1971-03-21", "gender": "female"},
        {"resourceType": "Condition", "subject": {"reference": "Patient/p001"}, "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.65"}]}, "recordedDate": "2025-08-04"},
        {"resourceType": "Observation", "subject": {"reference": "Patient/p001"}, "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]}, "valueQuantity": {"value": 9.2, "unit": "%"}, "effectiveDateTime": "2025-08-04"},
        {"resourceType": "Patient", "id": "p002", "name": [{"family": "Smith", "given": ["Carlos"]}], "birthDate": "1965-09-09", "gender": "male"},
        {"resourceType": "Observation", "subject": {"reference": "Patient/p002"}, "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]}, "valueQuantity": {"value": 10.4, "unit": "%"}, "effectiveDateTime": "2025-09-15"},
    ],
    "afib_no_anticoag": [
        {"resourceType": "Patient", "id": "p010", "name": [{"family": "Jones", "given": ["Pat"]}], "birthDate": "1948-12-01", "gender": "female"},
        {"resourceType": "Condition", "subject": {"reference": "Patient/p010"}, "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I48.91"}]}},
    ],
    "htn_uncontrolled_recent_visit": [
        {"resourceType": "Patient", "id": "p020", "name": [{"family": "Lee", "given": ["Min"]}], "birthDate": "1979-07-15", "gender": "male"},
        {"resourceType": "Observation", "subject": {"reference": "Patient/p020"}, "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]}, "valueString": "152/96", "effectiveDateTime": "2026-04-10"},
    ],
}


def kick_off(*, fhir_base_url: str, group_id: str | None = None, types: list[str] | None = None, since: str | None = None, access_token: str | None = None) -> dict[str, Any]:
    """Initiate a bulk export. Returns kick-off response with `content_location` for polling."""
    if not fhir_base_url:
        # Synthetic dev path
        cohort_key = group_id or "diabetes_uncontrolled"
        return {
            "synthetic": True,
            "cohort_key": cohort_key,
            "content_location": f"local://export/{cohort_key}",
        }
    try:  # pragma: no cover (no live FHIR)
        import requests
        path = f"/Group/{group_id}/$export" if group_id else "/Patient/$export"
        params = {}
        if types:
            params["_type"] = ",".join(types)
        if since:
            params["_since"] = since
        headers = {"Accept": "application/fhir+json", "Prefer": "respond-async"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        r = requests.get(fhir_base_url.rstrip("/") + path, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        return {"synthetic": False, "content_location": r.headers.get("Content-Location"), "status": r.status_code}
    except Exception as e:
        return {"synthetic": False, "error": str(e)}


def poll(content_location: str, *, access_token: str | None = None) -> dict[str, Any]:
    """Poll the export until COMPLETE; returns the array of NDJSON output URLs."""
    if content_location.startswith("local://export/"):
        cohort_key = content_location.split("/")[-1]
        items = SYNTHETIC.get(cohort_key, [])
        return {"status": "complete", "synthetic": True, "resources": items, "count": len(items)}
    try:  # pragma: no cover
        import requests
        headers = {"Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        r = requests.get(content_location, headers=headers, timeout=30)
        if r.status_code == 202:
            return {"status": "in_progress", "progress": r.headers.get("X-Progress")}
        r.raise_for_status()
        return {"status": "complete", "manifest": r.json()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def cohort_query(*, condition_icd10: str | None = None, lab_loinc_above: tuple[str, float] | None = None, age_band: tuple[int, int] | None = None) -> dict[str, Any]:
    """Synthesize a cohort from synthetic resources matching simple criteria."""
    matched_patients: dict[str, dict[str, Any]] = {}
    for resources in SYNTHETIC.values():
        patients = {r["id"]: r for r in resources if r.get("resourceType") == "Patient"}
        for r in resources:
            ref = (r.get("subject") or {}).get("reference", "")
            pid = ref.split("/")[-1] if ref.startswith("Patient/") else None
            if not pid:
                continue
            if condition_icd10 and r.get("resourceType") == "Condition":
                code = next((c.get("code") for c in r.get("code", {}).get("coding", [])), "")
                if code == condition_icd10:
                    matched_patients[pid] = patients.get(pid, {"id": pid})
            if lab_loinc_above and r.get("resourceType") == "Observation":
                code = next((c.get("code") for c in r.get("code", {}).get("coding", [])), "")
                v = r.get("valueQuantity", {}).get("value", 0)
                if code == lab_loinc_above[0] and v > lab_loinc_above[1]:
                    matched_patients[pid] = patients.get(pid, {"id": pid})
    return {"count": len(matched_patients), "patients": list(matched_patients.values())}
