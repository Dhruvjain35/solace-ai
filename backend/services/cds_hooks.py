"""CDS Hooks 2.0 service — discovery + handlers.

Implements a spec-compliant CDS Hooks service (HL7 CDS Hooks 2.0) with:

  - A discovery document describing every service Solace offers.
  - Four hook handlers: patient-view, order-select, order-sign,
    encounter-discharge.
  - Strict validation of the incoming hook request envelope and per-hook
    context. Invalid requests raise HookValidationError, which the router
    maps to HTTP 400.
  - Spec-compliant Cards: every card carries a uuid, a <=140-char summary,
    an indicator (info|warning|critical), a source object, optional
    suggestions (with FHIR `create` actions), and SMART links (link.type
    == "smart").
  - order-sign returns a `system` card with `indicator: critical` plus a
    `Cancel order` suggestion when a hard-stop interaction is found.

Cards wire back to real Solace capabilities:
  - differential.match_red_flags — must-not-miss red flags from complaint text
    (the same shared red-flag canon ddx_v2 consumes).
  - drug_interactions.check — drug-drug, drug-allergy, renal-dose alerts.
  - hedis.evaluate — open HEDIS care gaps.

This is decision support only. It never auto-acts; suggestions are
proposed actions the EHR user must accept.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from services import differential, drug_interactions, hedis

log = logging.getLogger(__name__)


SOLACE_BASE = "https://solace.d2gsbjipp9quan.amplifyapp.com"

# CDS Hooks 2.0 card indicator vocabulary.
_INDICATORS = ("info", "warning", "critical")

# Hook points this service implements, with the service id used in the URL.
_SERVICE_IDS = {
    "patient-view": "solace-patient-view",
    "order-select": "solace-order-select",
    "order-sign": "solace-order-sign",
    "encounter-discharge": "solace-encounter-discharge",
}

# Required context fields per hook (per the CDS Hooks 2.0 spec).
_REQUIRED_CONTEXT: dict[str, tuple[str, ...]] = {
    "patient-view": ("userId", "patientId"),
    "order-select": ("userId", "patientId", "selections", "draftOrders"),
    "order-sign": ("userId", "patientId", "draftOrders"),
    "encounter-discharge": ("userId", "patientId", "encounterId"),
}


class HookValidationError(ValueError):
    """Raised when an incoming CDS Hooks request is malformed.

    The router catches this and returns HTTP 400 so the EHR gets a clear,
    spec-aligned error instead of a 500.
    """


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------
def discovery() -> dict[str, Any]:
    """CDS Hooks discovery document served at GET /cds-services."""
    return {
        "services": [
            {
                "hook": "patient-view",
                "id": _SERVICE_IDS["patient-view"],
                "title": "Solace patient view — care gaps & red flags",
                "description": (
                    "Surfaces open HEDIS care gaps and must-not-miss red flags "
                    "when a clinician opens a patient's chart."
                ),
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                    "conditions": "Condition?patient={{context.patientId}}",
                },
            },
            {
                "hook": "order-select",
                "id": _SERVICE_IDS["order-select"],
                "title": "Solace order select — interaction check",
                "description": (
                    "Checks drug-drug, drug-allergy, and renal dosing for the "
                    "order being selected."
                ),
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                    "medications": "MedicationRequest?patient={{context.patientId}}&status=active",
                    "allergies": "AllergyIntolerance?patient={{context.patientId}}",
                },
            },
            {
                "hook": "order-sign",
                "id": _SERVICE_IDS["order-sign"],
                "title": "Solace order sign — hard-stop safety check",
                "description": (
                    "Final safety check at order signing. Hard-stops a sign-off "
                    "on a high-severity drug-drug or drug-allergy interaction."
                ),
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                    "medications": "MedicationRequest?patient={{context.patientId}}&status=active",
                    "allergies": "AllergyIntolerance?patient={{context.patientId}}",
                },
            },
            {
                "hook": "encounter-discharge",
                "id": _SERVICE_IDS["encounter-discharge"],
                "title": "Solace encounter discharge — safe-discharge review",
                "description": (
                    "Reviews open care gaps and unresolved red flags before an "
                    "encounter is discharged."
                ),
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                    "conditions": "Condition?patient={{context.patientId}}",
                },
            },
        ]
    }


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------
def _validate_request(hook_request: dict[str, Any], expected_hook: str) -> dict[str, Any]:
    """Validate the CDS Hooks request envelope and return its context.

    Per CDS Hooks 2.0 a request MUST carry `hook`, `hookInstance`, and
    `context`. We additionally require the per-hook context fields the
    handler relies on. Anything missing raises HookValidationError.
    """
    if not isinstance(hook_request, dict):
        raise HookValidationError("Request body must be a JSON object.")

    hook = hook_request.get("hook")
    if hook != expected_hook:
        raise HookValidationError(
            f"hook must be '{expected_hook}' for this endpoint, got '{hook}'."
        )

    hook_instance = hook_request.get("hookInstance")
    if not hook_instance or not isinstance(hook_instance, str):
        raise HookValidationError("hookInstance is required and must be a string.")

    context = hook_request.get("context")
    if not isinstance(context, dict):
        raise HookValidationError("context is required and must be a JSON object.")

    missing = [
        field
        for field in _REQUIRED_CONTEXT.get(expected_hook, ())
        if context.get(field) in (None, "")
    ]
    if missing:
        raise HookValidationError(
            f"context is missing required field(s) for {expected_hook}: "
            + ", ".join(missing)
        )
    return context


# --------------------------------------------------------------------------
# Card construction
# --------------------------------------------------------------------------
def _truncate_summary(summary: str) -> str:
    """CDS Hooks caps a card summary at 140 characters."""
    summary = " ".join((summary or "").split())
    if len(summary) <= 140:
        return summary
    return summary[:137].rstrip() + "..."


def _smart_link(label: str, path: str) -> dict[str, Any]:
    """A SMART app launch link back into Solace (link.type == 'smart')."""
    return {"label": label, "url": f"{SOLACE_BASE}{path}", "type": "smart"}


def _card(
    *,
    summary: str,
    detail: str,
    indicator: str = "info",
    link_label: str = "Open in Solace",
    link_path: str = "/",
    suggestions: list[dict[str, Any]] | None = None,
    selection_behavior: str | None = None,
) -> dict[str, Any]:
    """Build a spec-compliant CDS Hooks card."""
    if indicator not in _INDICATORS:
        indicator = "info"
    card: dict[str, Any] = {
        "uuid": str(uuid.uuid4()),
        "summary": _truncate_summary(summary),
        "indicator": indicator,
        "detail": detail,
        "source": {
            "label": "Solace AI",
            "url": SOLACE_BASE,
        },
        "links": [_smart_link(link_label, link_path)],
    }
    if suggestions:
        card["suggestions"] = suggestions
        # selectionBehavior is required by the spec whenever suggestions exist.
        card["selectionBehavior"] = selection_behavior or "any"
    return card


def _create_suggestion(label: str, resource: dict[str, Any]) -> dict[str, Any]:
    """A suggestion whose action proposes creating a FHIR resource."""
    return {
        "uuid": str(uuid.uuid4()),
        "label": label,
        "actions": [
            {
                "type": "create",
                "description": label,
                "resource": resource,
            }
        ],
    }


def _service_request(*, patient_id: str, code_text: str, icd10: str, reason: str) -> dict[str, Any]:
    """A minimal FHIR ServiceRequest resource for an order suggestion."""
    return {
        "resourceType": "ServiceRequest",
        "status": "draft",
        "intent": "order",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"text": code_text},
        "reasonCode": [
            {
                "coding": [
                    {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": icd10}
                ],
                "text": reason,
            }
        ],
    }


# --------------------------------------------------------------------------
# Shared extraction helpers
# --------------------------------------------------------------------------
def _patient_from_prefetch(hook_request: dict[str, Any]) -> dict[str, Any]:
    """Read the prefetched FHIR Patient resource, unwrapping a Bundle entry."""
    prefetch = hook_request.get("prefetch") or {}
    patient = prefetch.get("patient") or {}
    if isinstance(patient, dict) and patient.get("resourceType") == "Bundle":
        entries = patient.get("entry") or []
        if entries:
            patient = entries[0].get("resource") or {}
    return patient if isinstance(patient, dict) else {}


def _conditions_from_prefetch(hook_request: dict[str, Any]) -> list[str]:
    """Read condition display text from a prefetched Condition Bundle."""
    prefetch = hook_request.get("prefetch") or {}
    bundle = prefetch.get("conditions") or {}
    out: list[str] = []
    for entry in (bundle.get("entry") or []) if isinstance(bundle, dict) else []:
        resource = (entry or {}).get("resource") or {}
        code = resource.get("code") or {}
        text = code.get("text")
        if not text:
            for coding in code.get("coding") or []:
                text = coding.get("display")
                if text:
                    break
        if text:
            out.append(text)
    return out


def _demographics(patient: dict[str, Any]) -> tuple[int, str]:
    """Derive (age, sex) from a FHIR Patient resource."""
    age = 0
    birth = patient.get("birthDate")
    if birth:
        try:
            born = datetime.strptime(birth[:10], "%Y-%m-%d").date()
            today = date.today()
            age = today.year - born.year - (
                (today.month, today.day) < (born.month, born.day)
            )
            age = max(0, age)
        except Exception:  # noqa: BLE001 - malformed birthDate, treat as unknown
            age = 0
    sex = (patient.get("gender") or "").lower()[:1]
    return age, sex


def _build_solace_patient(hook_request: dict[str, Any]) -> dict[str, Any]:
    """Assemble the patient dict shape that hedis.evaluate expects."""
    patient = _patient_from_prefetch(hook_request)
    age, sex = _demographics(patient)
    conditions = _conditions_from_prefetch(hook_request)
    return {"age": age, "sex": sex, "history": {"conditions": conditions}}


def _medication_text(resource: dict[str, Any]) -> str:
    """Pull a human-readable medication name out of a FHIR resource."""
    if not isinstance(resource, dict):
        return ""
    concept = (
        resource.get("medicationCodeableConcept")
        or resource.get("code")
        or {}
    )
    text = concept.get("text") or ""
    if not text:
        for coding in concept.get("coding") or []:
            text = coding.get("display") or ""
            if text:
                break
    return text


def _orders_to_meds(draft_orders: Any, selections: Any) -> list[str]:
    """Resolve the medications referenced by draftOrders + selections."""
    entries = []
    if isinstance(draft_orders, dict):
        entries = draft_orders.get("entry") or []
    by_full_url: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        resource = entry.get("resource") or {}
        if entry.get("fullUrl"):
            by_full_url[entry["fullUrl"]] = resource
        ref = resource.get("id")
        if ref:
            res_type = resource.get("resourceType", "MedicationRequest")
            by_full_url[f"{res_type}/{ref}"] = resource

    meds: list[str] = []
    # selections is a list of references into draftOrders; if a selection does
    # not resolve, fall back to treating it as a free-text medication name.
    sel_list = selections if isinstance(selections, list) else []
    if sel_list:
        for sel in sel_list:
            resource = by_full_url.get(sel)
            text = _medication_text(resource) if resource else ""
            meds.append(text or str(sel))
    else:
        for entry in entries:
            resource = (entry or {}).get("resource") or {}
            text = _medication_text(resource)
            if text:
                meds.append(text)
    return [m for m in meds if m]


def _allergies_from_request(hook_request: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Collect allergy substance names from prefetch or context."""
    out: list[str] = []
    prefetch = hook_request.get("prefetch") or {}
    bundle = prefetch.get("allergies") or {}
    for entry in (bundle.get("entry") or []) if isinstance(bundle, dict) else []:
        resource = (entry or {}).get("resource") or {}
        code = resource.get("code") or {}
        text = code.get("text")
        if not text:
            for coding in code.get("coding") or []:
                text = coding.get("display")
                if text:
                    break
        if text:
            out.append(text)
    # Some EHRs pass a simple list in context for demo flows.
    ctx_allergies = context.get("patientAllergies")
    if isinstance(ctx_allergies, list):
        out.extend(str(a) for a in ctx_allergies if a)
    return out


def _current_meds_from_request(hook_request: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Collect the patient's active medications from prefetch or context."""
    out: list[str] = []
    prefetch = hook_request.get("prefetch") or {}
    bundle = prefetch.get("medications") or {}
    for entry in (bundle.get("entry") or []) if isinstance(bundle, dict) else []:
        resource = (entry or {}).get("resource") or {}
        text = _medication_text(resource)
        if text:
            out.append(text)
    ctx_meds = context.get("patientMedications")
    if isinstance(ctx_meds, list):
        out.extend(str(m) for m in ctx_meds if m)
    return out


# --------------------------------------------------------------------------
# Hook handlers
# --------------------------------------------------------------------------
def patient_view(*, hook_request: dict[str, Any], hospital_id: str = "demo") -> dict[str, Any]:
    """patient-view: surface open HEDIS care gaps for the patient."""
    context = _validate_request(hook_request, "patient-view")
    patient_id = str(context["patientId"])
    solace_patient = _build_solace_patient(hook_request)

    cards: list[dict[str, Any]] = []
    for gap in hedis.evaluate(solace_patient)[:4]:
        suggestion = _create_suggestion(
            label=gap["action"],
            resource=_service_request(
                patient_id=patient_id,
                code_text=gap["action"],
                icd10=gap.get("icd10", ""),
                reason=f"{gap['measure']} care gap: {gap['name']}",
            ),
        )
        cards.append(
            _card(
                summary=f"Care gap [{gap['measure']}]: {gap['name']}",
                detail=f"{gap['description']}\n\nRecommended action: {gap['action']}",
                indicator="warning",
                link_label="Review in Solace",
                link_path=f"/{hospital_id}/clinician",
                suggestions=[suggestion],
            )
        )

    if not cards:
        cards.append(
            _card(
                summary="No open Solace care gaps",
                detail="All tracked HEDIS measures are up to date for this patient.",
                indicator="info",
                link_path=f"/{hospital_id}/clinician",
            )
        )
    return {"cards": cards}


def _interaction_cards(
    *,
    result: dict[str, Any],
    hospital_id: str,
    high_severity_indicator: str = "critical",
) -> list[dict[str, Any]]:
    """Render drug-drug, drug-allergy, and renal alerts as cards."""
    cards: list[dict[str, Any]] = []
    for alert in result.get("drug_drug", []):
        is_high = alert.get("severity") == "high"
        cards.append(
            _card(
                summary=(
                    f"Drug interaction ({alert.get('severity')}): "
                    f"{alert['a']} + {alert['b']}"
                ),
                detail=alert.get("reason", ""),
                indicator=high_severity_indicator if is_high else "warning",
                link_label="Review interaction",
                link_path=f"/{hospital_id}/clinician",
            )
        )
    for alert in result.get("drug_allergy", []):
        cards.append(
            _card(
                summary=f"Drug-allergy conflict: {alert['med']}",
                detail=alert.get("reason", ""),
                indicator=high_severity_indicator,
                link_label="Review allergy",
                link_path=f"/{hospital_id}/clinician",
            )
        )
    for alert in result.get("renal", []):
        cards.append(
            _card(
                summary=f"Renal dose alert: {alert['med']} (eGFR {alert['egfr']})",
                detail=alert.get("guidance", ""),
                indicator="warning",
                link_label="Review dosing",
                link_path=f"/{hospital_id}/clinician",
            )
        )
    return cards


def order_select(*, hook_request: dict[str, Any], hospital_id: str = "demo") -> dict[str, Any]:
    """order-select: advisory drug-interaction check on the order in progress."""
    context = _validate_request(hook_request, "order-select")

    new_meds = _orders_to_meds(context.get("draftOrders"), context.get("selections"))
    current_meds = _current_meds_from_request(hook_request, context)
    allergies = _allergies_from_request(hook_request, context)
    all_meds = list(dict.fromkeys([*new_meds, *current_meds]))

    result = drug_interactions.check(all_meds, allergies)
    cards = _interaction_cards(
        result=result, hospital_id=hospital_id, high_severity_indicator="critical"
    )

    if not cards:
        cards.append(
            _card(
                summary="No interactions detected",
                detail=(
                    "Solace found no drug-drug, drug-allergy, or renal-dose "
                    "alerts for this order combination."
                ),
                indicator="info",
                link_path=f"/{hospital_id}/clinician",
            )
        )
    return {"cards": cards}


def order_sign(*, hook_request: dict[str, Any], hospital_id: str = "demo") -> dict[str, Any]:
    """order-sign: final safety check; hard-stops a high-severity interaction.

    On a high-severity drug-drug or any drug-allergy conflict this returns a
    `system` card with indicator `critical` and a `Cancel order` suggestion,
    which the EHR surfaces as a blocking hard-stop at sign time.
    """
    context = _validate_request(hook_request, "order-sign")

    new_meds = _orders_to_meds(context.get("draftOrders"), context.get("selections"))
    current_meds = _current_meds_from_request(hook_request, context)
    allergies = _allergies_from_request(hook_request, context)
    all_meds = list(dict.fromkeys([*new_meds, *current_meds]))

    result = drug_interactions.check(all_meds, allergies)
    hard_stop = bool(result.get("any_high")) or bool(result.get("drug_allergy"))

    cards = _interaction_cards(
        result=result, hospital_id=hospital_id, high_severity_indicator="critical"
    )

    if hard_stop:
        cancel = {
            "uuid": str(uuid.uuid4()),
            "label": "Cancel this order",
            "actions": [
                {
                    "type": "delete",
                    "description": "Remove the conflicting order from the draft",
                }
            ],
        }
        cards.insert(
            0,
            {
                "uuid": str(uuid.uuid4()),
                "summary": _truncate_summary(
                    "Hard stop: high-severity interaction on the order being signed"
                ),
                "indicator": "critical",
                "detail": (
                    "Solace detected a high-severity drug-drug or drug-allergy "
                    "conflict. Resolve the conflict or document an override "
                    "reason before signing."
                ),
                "source": {"label": "Solace AI", "url": SOLACE_BASE},
                "links": [_smart_link("Resolve in Solace", f"/{hospital_id}/clinician")],
                "suggestions": [cancel],
                "selectionBehavior": "any",
                # `system` indicatorType cards are not user-dismissable.
                "indicatorType": "system",
            },
        )

    if not cards:
        cards.append(
            _card(
                summary="Order cleared for signing",
                detail="Solace found no blocking interactions for this order.",
                indicator="info",
                link_path=f"/{hospital_id}/clinician",
            )
        )

    response: dict[str, Any] = {"cards": cards}
    if hard_stop:
        # systemActions array is part of the CDS Hooks 2.0 response shape.
        response["systemActions"] = []
    return response


def encounter_discharge(*, hook_request: dict[str, Any], hospital_id: str = "demo") -> dict[str, Any]:
    """encounter-discharge: safe-discharge review of red flags + care gaps."""
    context = _validate_request(hook_request, "encounter-discharge")
    patient_id = str(context["patientId"])

    cards: list[dict[str, Any]] = []

    # 1. Must-not-miss red flags inferred from the discharge reason / dx text.
    reason_text = " ".join(
        str(part)
        for part in (
            context.get("dischargeDisposition"),
            context.get("reason"),
            context.get("chiefComplaint"),
        )
        if part
    )
    conditions = _conditions_from_prefetch(hook_request)
    red_flag_text = " ".join([reason_text, *conditions])
    for flag in differential.match_red_flags(red_flag_text):
        cards.append(
            _card(
                summary=f"Red flag before discharge: rule out {flag['diagnosis']}",
                detail=(
                    f"The encounter context matches a must-not-miss pattern for "
                    f"{flag['diagnosis']} ({flag['icd10']}). Confirm this has "
                    f"been excluded per institutional pathway before discharge."
                ),
                indicator="critical",
                link_label="Review red flag",
                link_path=f"/{hospital_id}/clinician",
            )
        )

    # 2. Open HEDIS care gaps worth closing at discharge.
    solace_patient = _build_solace_patient(hook_request)
    for gap in hedis.evaluate(solace_patient)[:3]:
        suggestion = _create_suggestion(
            label=gap["action"],
            resource=_service_request(
                patient_id=patient_id,
                code_text=gap["action"],
                icd10=gap.get("icd10", ""),
                reason=f"{gap['measure']} care gap: {gap['name']}",
            ),
        )
        cards.append(
            _card(
                summary=f"Open care gap at discharge [{gap['measure']}]: {gap['name']}",
                detail=(
                    f"{gap['description']}\n\nClose at discharge if appropriate: "
                    f"{gap['action']}"
                ),
                indicator="warning",
                link_label="Review in Solace",
                link_path=f"/{hospital_id}/clinician",
                suggestions=[suggestion],
            )
        )

    if not cards:
        cards.append(
            _card(
                summary="No discharge concerns flagged",
                detail=(
                    "Solace found no unresolved red flags or open care gaps for "
                    "this encounter."
                ),
                indicator="info",
                link_path=f"/{hospital_id}/clinician",
            )
        )
    return {"cards": cards}
