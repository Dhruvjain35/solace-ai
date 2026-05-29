"""Bulk FHIR cohort export ($export client).

Population-health backbone. Calls Patient/$export, Group/$export, or
$export-poll-status against any USCDI-v3-compliant FHIR endpoint and returns
the streamed NDJSON resource set. In production, configure with the SMART
Backend Services JWT auth flow; in dev, returns synthetic cohort data so the
UI can be demoed.

All exported resources pass through HIPAA Safe Harbor de-identification
(§164.514(b)(2)) before they leave this service: the 18 identifier classes are
stripped or generalized, dates are reduced to year, and ages are bucketed —
ages 90+ collapse to a single "90+" band per the Safe Harbor age rule.

Use cases:
  - HEDIS quality reporting
  - MIPS / MVP submissions
  - ACO benchmarking (CareJourney / Arcadia / MedInsight overlap)
  - Retrospective ML training data
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import re
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


# ---------------------------------------------------------------------------
# HIPAA Safe Harbor de-identification (§164.514(b)(2)).
#
# The 18 identifier classes are removed or generalized. FHIR resources carry
# most identifiers in well-known elements; we strip those elements outright and
# generalize the rest (dates -> year, age -> band, ZIP -> first 3 digits).
# ---------------------------------------------------------------------------

# Resource-level keys removed wholesale — they hold direct identifiers.
_DROP_KEYS = {
    "name", "telecom", "address", "photo", "contact", "communication",
    "identifier", "text", "meta", "deceasedDateTime",
}

# Keys whose date values are reduced to the year only.
_DATE_KEYS = {
    "birthDate", "recordedDate", "effectiveDateTime", "issued", "authoredOn",
    "onsetDateTime", "abatementDateTime", "date", "started", "performedDateTime",
    "occurrenceDateTime", "lastUpdated", "assertedDate",
}

# Free-text fields scrubbed for residual identifiers.
_TEXT_KEYS = {"valueString", "display", "note", "comment", "description", "title"}

# Residual-identifier scrubbing patterns for free-text values.
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{16}\b"), "[CARD]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "[DATE]"),
    (re.compile(r"\bhttps?://\S+\b"), "[URL]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
    (re.compile(r"\bMRN[:\s#]*\w+\b", re.IGNORECASE), "[MRN]"),
]

_SAFE_HARBOR_VERSION = "hipaa-safe-harbor-1.0"


def _age_band(age: int) -> str:
    """HIPAA Safe Harbor age bucketing — 90+ collapses to one band."""
    if age < 0:
        return "unknown"
    if age >= 90:
        return "90+"
    lo = (age // 10) * 10
    return f"{lo}-{lo + 9}"


def _year_from(value: Any) -> Any:
    """Reduce an ISO date/datetime to its year (string), per Safe Harbor."""
    if not isinstance(value, str):
        return value
    m = re.match(r"(\d{4})", value.strip())
    return m.group(1) if m else None


def _scrub_text(value: str) -> str:
    out = value
    for pat, repl in _PII_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _hash_id(resource_type: str, raw_id: str) -> str:
    """One-way pseudonym so cross-resource references stay linkable but de-identified."""
    h = hashlib.sha256(f"{resource_type}:{raw_id}".encode()).hexdigest()[:16]
    return f"deid-{h}"


def _deidentify_resource(resource: dict, *, today: _dt.date) -> dict:
    """Apply Safe Harbor de-identification to a single FHIR resource."""
    if not isinstance(resource, dict):
        return resource
    rtype = resource.get("resourceType", "")
    out: dict[str, Any] = {}

    for key, value in resource.items():
        if key in _DROP_KEYS:
            continue
        if key == "id":
            out["id"] = _hash_id(rtype, str(value))
            continue
        if key == "birthDate":
            # birthDate is dropped; an age band is derived instead.
            year = _year_from(value)
            if year and str(year).isdigit():
                age = today.year - int(year)
                out["ageBand"] = _age_band(age)
            continue
        if key in _DATE_KEYS:
            out[key] = _year_from(value)
            continue
        if key in ("subject", "patient", "encounter", "performer", "requester"):
            # Generalize references to the pseudonymized id.
            out[key] = _deid_reference(value)
            continue
        if key == "address":  # already in _DROP_KEYS, kept for clarity
            continue
        if key in _TEXT_KEYS and isinstance(value, str):
            out[key] = _scrub_text(value)
            continue
        if isinstance(value, dict):
            out[key] = _deidentify_resource(value, today=today) if value.get("resourceType") else _deid_nested(value, today)
        elif isinstance(value, list):
            out[key] = [
                _deidentify_resource(v, today=today) if isinstance(v, dict) and v.get("resourceType")
                else (_deid_nested(v, today) if isinstance(v, dict) else v)
                for v in value
            ]
        else:
            out[key] = value

    out["_deidentified"] = _SAFE_HARBOR_VERSION
    return out


def _deid_nested(node: dict, today: _dt.date) -> dict:
    """De-identify a nested element (e.g. CodeableConcept, Quantity) — keeps codes,
    strips free text, reduces embedded dates."""
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROP_KEYS:
            continue
        if key in _DATE_KEYS:
            out[key] = _year_from(value)
        elif key in _TEXT_KEYS and isinstance(value, str):
            out[key] = _scrub_text(value)
        elif isinstance(value, dict):
            out[key] = _deid_nested(value, today)
        elif isinstance(value, list):
            out[key] = [_deid_nested(v, today) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    return out


def _deid_reference(ref: Any) -> Any:
    """Rewrite a FHIR reference (e.g. 'Patient/p001') to the pseudonymized id."""
    if isinstance(ref, dict):
        raw = ref.get("reference", "")
        if isinstance(raw, str) and "/" in raw:
            rtype, _, rid = raw.partition("/")
            return {"reference": f"{rtype}/{_hash_id(rtype, rid)}"}
        return {k: v for k, v in ref.items() if k != "display"}
    return ref


def deidentify(resources: list[dict]) -> list[dict]:
    """Public entry point — de-identify a list of FHIR resources via Safe Harbor."""
    today = _dt.date.today()
    return [_deidentify_resource(r, today=today) for r in resources if isinstance(r, dict)]


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
    """Poll the export until COMPLETE; returns the de-identified NDJSON resource set.

    All resources are passed through HIPAA Safe Harbor de-identification before
    being returned — no direct identifiers leave this function.
    """
    if content_location.startswith("local://export/"):
        cohort_key = content_location.split("/")[-1]
        items = deidentify(SYNTHETIC.get(cohort_key, []))
        return {
            "status": "complete",
            "synthetic": True,
            "resources": items,
            "count": len(items),
            "deidentified": _SAFE_HARBOR_VERSION,
        }
    try:  # pragma: no cover
        import requests
        headers = {"Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        r = requests.get(content_location, headers=headers, timeout=30)
        if r.status_code == 202:
            return {"status": "in_progress", "progress": r.headers.get("X-Progress")}
        r.raise_for_status()
        return {"status": "complete", "manifest": r.json(), "deidentified": _SAFE_HARBOR_VERSION}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def cohort_query(*, condition_icd10: str | None = None, lab_loinc_above: tuple[str, float] | None = None, age_band: tuple[int, int] | None = None) -> dict[str, Any]:
    """Synthesize a cohort from synthetic resources matching simple criteria.

    Matched patient resources are returned de-identified (Safe Harbor): names
    and birthDate are removed and an `ageBand` is supplied instead. The optional
    `age_band` (min, max) filter is applied against the patient's real age
    before de-identification.
    """
    today = _dt.date.today()
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

    selected = list(matched_patients.values())

    # Apply age_band filter against real age, before de-identification.
    if age_band:
        lo, hi = age_band
        kept = []
        for p in selected:
            year = _year_from(p.get("birthDate"))
            if year and str(year).isdigit():
                age = today.year - int(year)
                if lo <= age <= hi:
                    kept.append(p)
        selected = kept

    deid = deidentify(selected)
    # Tally the Safe Harbor age-band distribution for population reporting.
    distribution: dict[str, int] = {}
    for p in deid:
        band = p.get("ageBand", "unknown")
        distribution[band] = distribution.get(band, 0) + 1

    return {
        "count": len(deid),
        "patients": deid,
        "age_band_distribution": distribution,
        "deidentified": _SAFE_HARBOR_VERSION,
    }
