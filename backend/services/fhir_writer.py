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
# Solace-AI agent identity — referenced by Provenance and Device builders.
_SOLACE_DEVICE_ID = "solace-ai-scribe"
_SOLACE_DEVICE_REF = f"Device/{_SOLACE_DEVICE_ID}"
_SOLACE_DEVICE_DISPLAY = "Solace AI clinical scribe"

# DSI (Decision Support Intervention) source attribute extension — HTI-1 final rule
# §170.315(b)(11). Solace surfaces predictive output, so writes it authors must
# carry a traceable source attribute so downstream clinicians can audit the DSI.
_DSI_SOURCE_EXT_URL = "http://solace.health/fhir/StructureDefinition/dsi-source-attribute"


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
        # US Core DocumentReference requires a category; "clinical-note" is the
        # US Core DocumentReference Category value set entry for clinical notes.
        "category": [{"coding": [{
            "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
            "code": "clinical-note",
            "display": "Clinical Note",
        }]}],
        "type": {"coding": [{"system": "http://loinc.org", "code": type_code, "display": type_display}]},
        "subject": {"reference": patient_ref},
        "date": _now_iso(),
        "author": [{"display": author_display}],
        "content": content,
    }


def build_condition(*, patient_ref: str, icd10: str, display: str, clinical_status: str = "active") -> dict[str, Any]:
    return {
        "resourceType": "Condition",
        # US Core Condition requires a category; Solace problem-list write-back
        # lands on the problem list, so "problem-list-item".
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
            "code": "problem-list-item",
            "display": "Problem List Item",
        }]}],
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


# Display unit -> UCUM code map. UCUM `code` is machine-readable and required
# by US Core Vital Signs; `unit` stays the human-readable display string.
_UCUM_BY_UNIT: dict[str, str] = {
    "beats/minute": "/min",
    "bpm": "/min",
    "breaths/minute": "/min",
    "/min": "/min",
    "mmHg": "mm[Hg]",
    "%": "%",
    "C": "Cel",
    "Cel": "Cel",
    "°C": "Cel",
    "F": "[degF]",
    "°F": "[degF]",
    "kg": "kg",
    "g": "g",
    "lbs": "[lb_av]",
    "cm": "cm",
    "m": "m",
    "in": "[in_i]",
    "kg/m2": "kg/m2",
}


def build_observation_vital(*, patient_ref: str, code_loinc: str, display: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code_loinc, "display": display}]},
        "subject": {"reference": patient_ref},
        "effectiveDateTime": _now_iso(),
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
            # UCUM machine-readable code — falls back to the raw unit string if
            # unrecognized so the resource stays a valid Quantity either way.
            "code": _UCUM_BY_UNIT.get(unit, unit),
        },
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
        # primarySource=false: Solace captures immunization history from patient
        # report / chart reconciliation, not as the administering organization.
        # US Core Immunization requires this flag to be present.
        "primarySource": False,
    }


def build_medication_statement(
    *,
    patient_ref: str,
    rxnorm: str,
    display: str,
    status: str = "active",
    dosage_text: str = "",
) -> dict[str, Any]:
    """A FHIR R4 MedicationStatement framed as medication reconciliation.

    Deliberately NOT a MedicationRequest: Solace does not prescribe or order.
    A MedicationStatement records that a patient is (or reports being) on a
    medication — the correct resource for med-rec / home-medication capture.
    """
    resource: dict[str, Any] = {
        "resourceType": "MedicationStatement",
        "status": status,  # active | completed | entered-in-error | intended | stopped | on-hold
        "medicationCodeableConcept": {
            "coding": [{
                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                "code": rxnorm,
                "display": display,
            }],
            "text": display,
        },
        "subject": {"reference": patient_ref},
        "dateAsserted": _now_iso(),
        "effectiveDateTime": _now_iso(),
        # Category marks this as a reconciliation entry, not an inpatient order.
        "category": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/medication-statement-category",
            "code": "patientspecified",
            "display": "Patient Specified",
        }]},
    }
    if dosage_text:
        resource["dosage"] = [{"text": dosage_text}]
    return resource


def build_service_request(
    *,
    patient_ref: str,
    code: str,
    display: str,
    system: str = "http://loinc.org",
    intent: str = "order",
    priority: str = "routine",
    category_code: str = "108252007",  # SNOMED: Laboratory procedure
    category_display: str = "Laboratory procedure",
    reason_text: str = "",
    requester_display: str = "Solace AI scribe",
    encounter_ref: str | None = None,
) -> dict[str, Any]:
    """A FHIR R4 ServiceRequest — an order (lab, imaging, referral, procedure).

    USCDI v3 surfaces orders via ServiceRequest. Solace builds the order as a
    *proposal/order* that a clinician confirms before it is written back (see
    `confirm_and_write`). `code`+`system` is the orderable (LOINC for labs,
    CPT/SNOMED for procedures); `category_code` tags the order class so the EHR
    files it in the right queue.

    `intent` defaults to "order"; use "proposal" for an AI-suggested order that
    has not yet been signed. `status` is fixed to "active" for an order and
    "draft" for a proposal so an unconfirmed suggestion never looks live.
    """
    status = "draft" if intent == "proposal" else "active"
    resource: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "status": status,
        "intent": intent,
        "priority": priority,
        "category": [{"coding": [{
            "system": "http://snomed.info/sct",
            "code": category_code,
            "display": category_display,
        }]}],
        "code": {
            "coding": [{"system": system, "code": code, "display": display}],
            "text": display,
        },
        "subject": {"reference": patient_ref},
        "authoredOn": _now_iso(),
        "requester": {"display": requester_display},
    }
    if reason_text:
        resource["reasonCode"] = [{"text": reason_text}]
    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return resource


def build_procedure(
    *,
    patient_ref: str,
    code: str,
    display: str,
    system: str = "http://snomed.info/sct",
    status: str = "completed",
    performed: str | None = None,
    encounter_ref: str | None = None,
) -> dict[str, Any]:
    """A FHIR R4 Procedure — a performed clinical procedure (USCDI v3).

    Defaults to a completed SNOMED-coded procedure performed "now". Pass CPT via
    `system="http://www.ama-assn.org/go/cpt"` for billing-coded procedures.
    """
    resource: dict[str, Any] = {
        "resourceType": "Procedure",
        "status": status,
        "code": {
            "coding": [{"system": system, "code": code, "display": display}],
            "text": display,
        },
        "subject": {"reference": patient_ref},
        "performedDateTime": performed or _now_iso(),
    }
    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return resource


# ---- Provenance ------------------------------------------------------------------
def build_provenance(
    *,
    target_refs: list[str],
    signing_clinician_ref: str | None = None,
    signing_clinician_display: str = "",
    recorded: str | None = None,
    activity_code: str = "CREATE",
) -> dict[str, Any]:
    """A FHIR R4 Provenance attesting that Solace-AI authored the target resources.

    Carries:
      - a Device agent (the Solace-AI scribe) as the `author`,
      - an optional human verifier agent (the signing clinician) as `verifier`,
      - a `recorded` timestamp,
      - a DSI source-attribute extension (HTI-1 §170.315(b)(11)) so downstream
        clinicians can trace that the content originated from a predictive DSI.

    `target_refs` are relative references (e.g. "Condition/abc") or full URLs of
    the resources this Provenance covers.
    """
    agents: list[dict[str, Any]] = [
        {
            # Solace-AI Device — the assembling/authoring software agent.
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                "code": "assembler",
                "display": "Assembler",
            }]},
            "who": {"reference": _SOLACE_DEVICE_REF, "display": _SOLACE_DEVICE_DISPLAY},
        }
    ]
    if signing_clinician_ref:
        # Human verifier — the clinician who reviewed and signed off the AI output.
        agents.append({
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                "code": "verifier",
                "display": "Verifier",
            }]},
            "who": {
                "reference": signing_clinician_ref,
                **({"display": signing_clinician_display} if signing_clinician_display else {}),
            },
        })

    return {
        "resourceType": "Provenance",
        # DSI source-attribute extension — HTI-1 predictive DSI traceability.
        "extension": [{
            "url": _DSI_SOURCE_EXT_URL,
            "extension": [
                {"url": "sourceType", "valueCode": "predictive-dsi"},
                {"url": "sourceName", "valueString": "Solace AI triage"},
                {"url": "sourceDevice", "valueReference": {"reference": _SOLACE_DEVICE_REF}},
            ],
        }],
        "target": [{"reference": ref} for ref in target_refs],
        "recorded": recorded or _now_iso(),
        "activity": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-DataOperation",
            "code": activity_code,
        }]},
        "agent": agents,
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


# ---- Provenance-attaching orchestrators ------------------------------------------
def _result_ref(result: dict[str, Any]) -> str:
    """Build a FHIR reference string from a write() result."""
    rid = result.get("id") or ""
    rt = result.get("resourceType") or ""
    return f"{rt}/{rid}" if rt and rid else (result.get("url") or "")


def write_with_provenance(
    resource: dict[str, Any],
    *,
    fhir_base_url: str | None = None,
    access_token: str | None = None,
    signing_clinician_ref: str | None = None,
    signing_clinician_display: str = "",
) -> dict[str, Any]:
    """Write a single Solace-authored resource, then attach a Provenance to it.

    Returns {resource: <write result>, provenance: <write result>}. The
    Provenance is recorded even if the primary write fell back to local store,
    so every Solace-authored write is traceable.
    """
    res_result = write(resource, fhir_base_url=fhir_base_url, access_token=access_token)
    prov = build_provenance(
        target_refs=[_result_ref(res_result)],
        signing_clinician_ref=signing_clinician_ref,
        signing_clinician_display=signing_clinician_display,
    )
    prov_result = write(prov, fhir_base_url=fhir_base_url, access_token=access_token)
    return {"resource": res_result, "provenance": prov_result}


def write_bundle_with_provenance(
    resources: list[dict[str, Any]],
    *,
    fhir_base_url: str | None = None,
    access_token: str | None = None,
    signing_clinician_ref: str | None = None,
    signing_clinician_display: str = "",
) -> dict[str, Any]:
    """Write multiple Solace-authored resources, then attach one Provenance
    that targets all of them (a single attestation for the batch).

    Returns {resources: [<write results>], provenance: <write result>}.
    """
    res_results = [
        write(r, fhir_base_url=fhir_base_url, access_token=access_token)
        for r in resources
    ]
    targets = [_result_ref(r) for r in res_results if _result_ref(r)]
    prov = build_provenance(
        target_refs=targets,
        signing_clinician_ref=signing_clinician_ref,
        signing_clinician_display=signing_clinician_display,
    )
    prov_result = write(prov, fhir_base_url=fhir_base_url, access_token=access_token)
    return {"resources": res_results, "provenance": prov_result}


# ---- Confirm-before-write -------------------------------------------------------
# Every Solace-authored write to a patient's chart is clinician-confirmed: the
# UI first shows a preview of the exact resource, the clinician signs off, and
# only then does the write fire. These helpers make that contract explicit and
# uniform across resource types (ServiceRequest orders, clinical-note
# DocumentReference, problem-list Condition).


def preview_write(resource: dict[str, Any]) -> dict[str, Any]:
    """Describe a write WITHOUT performing any I/O (confirm-before-write step 1).

    Returns a small preview the router can surface to the clinician for sign-off
    — the resource type, a human label, and the resource itself — so nothing
    reaches the EHR until `confirm_and_write(..., confirmed=True)` is called.
    """
    rt = resource.get("resourceType") or "Resource"
    label = _preview_label(resource)
    return {
        "confirm_required": True,
        "resource_type": rt,
        "label": label,
        "resource": resource,
    }


def confirm_and_write(
    resource: dict[str, Any],
    *,
    confirmed: bool,
    fhir_base_url: str | None = None,
    access_token: str | None = None,
    signing_clinician_ref: str | None = None,
    signing_clinician_display: str = "",
) -> dict[str, Any]:
    """Write `resource` only when `confirmed` is True (confirm-before-write).

    When `confirmed` is False this performs NO external I/O and returns the
    `preview_write` payload so the caller can render the confirmation step.
    When True it writes the resource and attaches a Solace Provenance
    attestation (the signing clinician is recorded as the verifier).

    The router stays responsible for verifying clinician identity / consent and
    calling audit(); this helper only enforces the explicit confirmation gate so
    an unconfirmed suggestion can never be written by accident.
    """
    if not confirmed:
        return preview_write(resource)
    return write_with_provenance(
        resource,
        fhir_base_url=fhir_base_url,
        access_token=access_token,
        signing_clinician_ref=signing_clinician_ref,
        signing_clinician_display=signing_clinician_display,
    )


def _preview_label(resource: dict[str, Any]) -> str:
    """A short human label for a write preview (no raw identifiers)."""
    rt = resource.get("resourceType") or "Resource"
    code = resource.get("code") or {}
    text = code.get("text") if isinstance(code, dict) else ""
    if not text and isinstance(code, dict):
        coding = code.get("coding") or []
        if coding:
            text = coding[0].get("display") or coding[0].get("code") or ""
    if rt == "DocumentReference":
        type_cc = resource.get("type") or {}
        coding = type_cc.get("coding") or []
        text = (coding[0].get("display") if coding else "") or "Clinical note"
    return f"{rt}: {text}" if text else rt
