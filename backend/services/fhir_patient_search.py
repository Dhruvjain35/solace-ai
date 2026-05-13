"""Real FHIR patient search against a public SMART-on-FHIR sandbox.

Default backend is the SMART Health IT public sandbox at
https://launch.smarthealthit.org/v/r4/fhir — no registration, no auth,
Synthea-generated realistic patient population. Free for demos and
integration testing.

Production swap: set EHR_FHIR_BASE_URL + EHR_FHIR_ACCESS_TOKEN to point at
Epic / Cerner / Athena once SMART backend services + client-credentials grant
is configured. The function signatures here don't change.

Why this is the right call for Solace today:
  - Real FHIR R4 wire format (not a mock proxy) — proves the integration story
  - Synthea data has full longitudinal records: 5-10 years of encounters,
    realistic problem lists, med history, allergies — so a demo lookup actually
    pre-fills meaningful data
  - Zero ops setup — no client_id registration, no JWKS hosting, just HTTP

Operations:
  - Hard timeout: 6s for primary Patient search, 4s for each follow-on resource
  - Falls back to {} on any error — the patient intake flow continues regardless
  - Each fetch is logged with response time so we can spot sandbox latency
"""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_FHIR_BASE = "https://launch.smarthealthit.org/v/r4/fhir"
SEARCH_TIMEOUT_S = 6.0
RESOURCE_TIMEOUT_S = 4.0


def _base_url() -> str:
    return os.environ.get("EHR_FHIR_BASE_URL", DEFAULT_FHIR_BASE).rstrip("/")


def _auth_header() -> dict[str, str]:
    """Token comes from the SMART backend-services flow when wired against
    Epic/Cerner. Public SMART Health IT sandbox needs no auth, so empty dict is fine."""
    tok = os.environ.get("EHR_FHIR_ACCESS_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _client() -> httpx.Client:
    headers = {"Accept": "application/fhir+json", **_auth_header()}
    return httpx.Client(timeout=SEARCH_TIMEOUT_S, headers=headers)


# ----------------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------------


def match_by_demographics(
    *,
    given: str,
    family: str,
    birth_date: str = "",
    gender: str = "",
) -> dict[str, Any] | None:
    """Search FHIR Patient by name + birthDate. Returns the normalized record
    on hit (with allergies, meds, conditions, prior visits already fetched) or
    None on miss/error.

    `birth_date` should be YYYY-MM-DD when known. The sandbox supports partial
    dates but we prefer exact matches.
    """
    given = (given or "").strip()
    family = (family or "").strip()
    if not given and not family:
        return None

    params: dict[str, str] = {"_count": "5"}
    if family:
        params["family"] = family
    if given:
        params["given"] = given
    if birth_date:
        params["birthdate"] = birth_date
    if gender:
        params["gender"] = gender.lower()

    bundle = _search("Patient", params)
    if not bundle:
        return None

    candidates = bundle.get("entry", []) or []
    if not candidates:
        return None

    # If we got back multiple, prefer the one whose birthdate matches exactly.
    chosen = _pick_best_candidate(candidates, birth_date)
    patient_resource = (chosen or {}).get("resource") or {}
    if not patient_resource:
        return None

    return _enrich_patient(patient_resource)


def match_by_member_id(member_id: str, provider_hint: str = "") -> dict[str, Any] | None:
    """Search FHIR Patient by insurance identifier. Less reliable than name+DOB
    because not every EHR indexes insurance member_id as a Patient.identifier,
    but a free win when it's there."""
    member_id = (member_id or "").strip()
    if not member_id:
        return None
    bundle = _search("Patient", {"identifier": member_id, "_count": "3"})
    if not bundle:
        return None
    entries = bundle.get("entry", []) or []
    if not entries:
        return None
    patient_resource = (entries[0] or {}).get("resource") or {}
    if not patient_resource:
        return None
    return _enrich_patient(patient_resource)


# ----------------------------------------------------------------------------------
# Internal — Patient enrichment + FHIR fetch
# ----------------------------------------------------------------------------------


def _enrich_patient(patient: dict[str, Any]) -> dict[str, Any]:
    """Given a FHIR Patient, fetch allergies + meds + problems + encounters in
    parallel and return the normalized Solace record shape."""
    patient_id = patient.get("id")
    if not patient_id:
        return _normalize_patient(patient, {}, {}, {}, {})

    fetches = {
        "allergies": ("AllergyIntolerance", {"patient": patient_id, "_count": "20"}),
        "meds": ("MedicationRequest", {"patient": patient_id, "status": "active", "_count": "20"}),
        "conditions": ("Condition", {"patient": patient_id, "clinical-status": "active", "_count": "20"}),
        "encounters": ("Encounter", {"patient": patient_id, "_count": "5", "_sort": "-date"}),
    }
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_key = {pool.submit(_search, kind, params): key for key, (kind, params) in fetches.items()}
        for fut in as_completed(future_to_key):
            key = future_to_key[fut]
            try:
                results[key] = fut.result() or {}
            except Exception as e:  # noqa: BLE001
                log.info("FHIR enrich %s failed: %s", key, e)
                results[key] = {}

    return _normalize_patient(
        patient,
        results.get("allergies", {}),
        results.get("meds", {}),
        results.get("conditions", {}),
        results.get("encounters", {}),
    )


def _search(resource_type: str, params: dict[str, str]) -> dict[str, Any] | None:
    url = f"{_base_url()}/{resource_type}"
    try:
        with _client() as c:
            resp = c.get(url, params=params, timeout=RESOURCE_TIMEOUT_S if resource_type != "Patient" else SEARCH_TIMEOUT_S)
            if resp.status_code != 200:
                log.info("FHIR %s -> %d (%s)", resource_type, resp.status_code, resp.text[:160])
                return None
            return resp.json()
    except httpx.TimeoutException:
        log.info("FHIR %s timed out", resource_type)
        return None
    except Exception as e:  # noqa: BLE001
        log.info("FHIR %s error: %s", resource_type, e)
        return None


# ----------------------------------------------------------------------------------
# Candidate scoring + normalization
# ----------------------------------------------------------------------------------


def _pick_best_candidate(entries: list[dict], birth_date: str) -> dict | None:
    """When the search returns multiple matches, prefer the one whose birthdate
    matches exactly. If no birthdate was supplied or none matches, return the
    first entry."""
    if not entries:
        return None
    if birth_date:
        for e in entries:
            r = e.get("resource") or {}
            if (r.get("birthDate") or "") == birth_date:
                return e
    return entries[0]


def _normalize_patient(
    patient: dict[str, Any],
    allergies_bundle: dict[str, Any],
    meds_bundle: dict[str, Any],
    conds_bundle: dict[str, Any],
    encounters_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Reshape a FHIR Patient + related resources into Solace's EHR record shape.

    Solace's internal shape matches what the dashboard EHRPanel + intake prefill
    expect: a flat dict with allergies/medications/conditions/prior_visits arrays.
    """
    name = _hn_to_string(_first_name(patient.get("name") or []))
    dob = patient.get("birthDate") or ""
    gender = patient.get("gender") or ""
    mrn = _find_mrn(patient.get("identifier") or [])
    phone = _first_telecom(patient.get("telecom") or [], "phone")

    record = {
        "mrn": mrn or patient.get("id", ""),
        "fhir_id": patient.get("id", ""),
        "name": name,
        "dob": dob,
        "age": _age_from_dob(dob),
        "sex": _normalize_sex(gender),
        "phone": phone,
        "blood_type": "—",
        "height_cm": None,
        "weight_kg": None,
        "bmi": None,
        "primary_care_provider": _pcp_from_general_practitioner(patient.get("generalPractitioner") or []),
        "insurance": "",
        "emergency_contact": _emergency_contact(patient.get("contact") or []),
        "allergies": _allergies(allergies_bundle),
        "medications": _medications(meds_bundle),
        "conditions": _conditions(conds_bundle),
        "family_history": [],
        "social_history": "",
        "immunizations": [],
        "prior_visits": _prior_visits(encounters_bundle),
        "source": "fhir_sandbox",
    }
    return record


# ----------------------------------------------------------------------------------
# FHIR field helpers
# ----------------------------------------------------------------------------------


def _first_name(names: list[dict]) -> dict:
    if not names:
        return {}
    for n in names:
        if (n.get("use") or "").lower() == "official":
            return n
    return names[0]


def _hn_to_string(n: dict) -> str:
    if not isinstance(n, dict):
        return ""
    if n.get("text"):
        return str(n["text"])
    given = " ".join(n.get("given") or [])
    family = n.get("family") or ""
    parts = [p for p in (given, family) if p]
    return " ".join(parts).strip()


def _find_mrn(identifiers: list[dict]) -> str:
    for ident in identifiers:
        type_codings = ((ident.get("type") or {}).get("coding") or [])
        for c in type_codings:
            if c.get("code") in {"MR", "MRN"} or "medical record" in str(c.get("display", "")).lower():
                return str(ident.get("value", ""))
    return identifiers[0].get("value", "") if identifiers else ""


def _first_telecom(telecoms: list[dict], system: str) -> str:
    for t in telecoms:
        if (t.get("system") or "").lower() == system:
            return str(t.get("value", ""))
    return ""


def _pcp_from_general_practitioner(gps: list[dict]) -> str:
    if not gps:
        return ""
    return str(gps[0].get("display") or gps[0].get("reference") or "")


def _emergency_contact(contacts: list[dict]) -> str:
    for c in contacts:
        relationship = ((c.get("relationship") or [{}])[0].get("coding") or [{}])[0].get("display", "")
        name = _hn_to_string(c.get("name") or {})
        phone = _first_telecom(c.get("telecom") or [], "phone")
        if name:
            parts = [name]
            if relationship:
                parts.append(f"({relationship})")
            if phone:
                parts.append(phone)
            return " ".join(parts)
    return ""


def _age_from_dob(dob: str) -> int | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", dob)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        today = date.today()
        return today.year - y - ((today.month, today.day) < (mo, d))
    except Exception:  # noqa: BLE001
        return None


def _normalize_sex(g: str) -> str:
    g = (g or "").lower()
    if g in {"m", "male"}:
        return "male"
    if g in {"f", "female"}:
        return "female"
    return g or "other"


def _allergies(bundle: dict) -> list[str]:
    out: list[str] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        substance = (r.get("code") or {}).get("text") or _coding_display(r.get("code") or {})
        if substance and substance.lower() not in {"none", "nka", "nkda"}:
            out.append(substance)
    return out or []


def _medications(bundle: dict) -> list[str]:
    out: list[str] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        med = (r.get("medicationCodeableConcept") or {}).get("text") or _coding_display(r.get("medicationCodeableConcept") or {})
        if med:
            out.append(med)
    return out


def _conditions(bundle: dict) -> list[str]:
    out: list[str] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        cond = (r.get("code") or {}).get("text") or _coding_display(r.get("code") or {})
        if cond:
            out.append(cond)
    return out


def _prior_visits(bundle: dict) -> list[dict]:
    out: list[dict] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        period = r.get("period") or {}
        type_text = ""
        if r.get("type"):
            type_text = (r["type"][0] or {}).get("text") or _coding_display((r["type"][0] or {}))
        reason = ""
        rc = r.get("reasonCode") or []
        if rc:
            reason = rc[0].get("text") or _coding_display(rc[0])
        out.append({
            "date": (period.get("start") or "")[:10],
            "type": type_text or "Encounter",
            "facility": _ref_display(r.get("serviceProvider")),
            "chief_complaint": reason or "—",
            "disposition": str(r.get("status") or ""),
            "note": "",
        })
    return out


def _coding_display(field: dict) -> str:
    coding = (field.get("coding") or [])
    if coding:
        return str(coding[0].get("display") or coding[0].get("code") or "")
    return ""


def _ref_display(ref: dict | None) -> str:
    if not ref:
        return ""
    return str(ref.get("display") or ref.get("reference") or "")
