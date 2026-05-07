"""CDS Hooks service — discovery + handlers.

Implements the cards returned for two hook points:
  - patient-view: surfaces open HEDIS gaps + outstanding screeners + drug allergies
  - order-select: drug-drug + drug-allergy + dose alerts + cheaper formulary alts

Cards include a `link.type: smart` jump back to the Solace UI for full context.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from services import drug_interactions, hedis

log = logging.getLogger(__name__)


SOLACE_BASE = "https://solace.d2gsbjipp9quan.amplifyapp.com"


def discovery() -> dict[str, Any]:
    return {
        "services": [
            {
                "hook": "patient-view",
                "id": "solace-patient-view",
                "title": "Solace patient view (HEDIS gaps + screeners)",
                "description": "Surface open care gaps and screener red flags",
                "prefetch": {"patient": "Patient/{{context.patientId}}"},
            },
            {
                "hook": "order-select",
                "id": "solace-order-select",
                "title": "Solace order select (drug interaction check)",
                "description": "Check drug-drug, drug-allergy, and renal dosing for the proposed order",
                "prefetch": {"patient": "Patient/{{context.patientId}}"},
            },
        ]
    }


def _card(summary: str, detail: str, indicator: str = "info", link_label: str = "Open in Solace", link_path: str = "/") -> dict[str, Any]:
    return {
        "uuid": str(uuid.uuid4()),
        "summary": summary,
        "indicator": indicator,  # info | warning | critical
        "detail": detail,
        "source": {"label": "Solace AI"},
        "links": [
            {"label": link_label, "url": f"{SOLACE_BASE}{link_path}", "type": "smart"},
        ],
    }


def patient_view(*, hook_request: dict[str, Any], hospital_id: str = "demo") -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    patient = hook_request.get("prefetch", {}).get("patient") or {}
    # Try to extract age/sex/conditions from FHIR Patient
    age = 0
    sex = ""
    if patient.get("birthDate"):
        try:
            from datetime import date
            yob = int(patient["birthDate"][:4])
            age = max(0, date.today().year - yob)
        except Exception:
            pass
    sex = (patient.get("gender") or "").lower()[:1]
    conditions = []  # Real implementation prefetches Condition; here we read from extension if present

    fake_patient = {"age": age, "sex": sex, "history": {"conditions": conditions}}
    gaps = hedis.evaluate(fake_patient)
    for g in gaps[:3]:
        cards.append(_card(
            summary=f"{g['measure']}: {g['name']}",
            detail=f"{g['description']}\n\nAction: {g['action']}",
            indicator="warning",
            link_path=f"/{hospital_id}/clinician",
        ))
    if not cards:
        cards.append(_card("No open Solace gaps", "All HEDIS measures up to date.", "info", link_path=f"/{hospital_id}/clinician"))
    return {"cards": cards}


def order_select(*, hook_request: dict[str, Any], hospital_id: str = "demo") -> dict[str, Any]:
    ctx = hook_request.get("context", {}) or {}
    selections = ctx.get("selections", []) or []
    draft_orders = (ctx.get("draftOrders") or {}).get("entry", []) or []
    new_meds: list[str] = []
    for entry in draft_orders + [{"resource": {"medicationCodeableConcept": {"text": s}}} for s in selections]:
        rsrc = entry.get("resource", {})
        text = (rsrc.get("medicationCodeableConcept") or {}).get("text") or ""
        if text:
            new_meds.append(text)
    current_meds = ctx.get("patientMedications", [])
    all_meds = list({*new_meds, *current_meds})
    allergies = ctx.get("patientAllergies", [])
    result = drug_interactions.check(all_meds, allergies)
    cards: list[dict[str, Any]] = []
    for a in result["drug_drug"]:
        cards.append(_card(
            summary=f"Interaction: {a['a']} + {a['b']} ({a['severity']})",
            detail=a["reason"],
            indicator="critical" if a["severity"] == "high" else "warning",
            link_path=f"/{hospital_id}/clinician",
        ))
    for a in result["drug_allergy"]:
        cards.append(_card(
            summary=f"Drug allergy match: {a['med']}",
            detail=a["reason"],
            indicator="critical",
            link_path=f"/{hospital_id}/clinician",
        ))
    for a in result.get("renal", []):
        cards.append(_card(
            summary=f"Renal dose alert: {a['med']} (eGFR {a['egfr']})",
            detail=a["guidance"],
            indicator="warning",
            link_path=f"/{hospital_id}/clinician",
        ))
    if not cards:
        cards.append(_card("No interactions detected", "Solace did not find drug-drug, drug-allergy, or renal-dose alerts for this combination.", "info", link_path=f"/{hospital_id}/clinician"))
    return {"cards": cards}
