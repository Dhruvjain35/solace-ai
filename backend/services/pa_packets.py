"""Prior authorization packet generator.

Given the encounter note + the proposed order, produce a structured PA packet
ready for either:
  - Da Vinci PAS FHIR submission (CMS-0057-F mandate, live Jan 1 2026).
  - Surescripts CompletEPA for medications.
  - Payer portal upload (PDF) for legacy.

The packet contains:
  - Patient demographics + member ID + payer
  - Diagnosis (ICD-10) + service requested (CPT/HCPCS or NDC)
  - Clinical rationale grounded in the encounter note
  - Alternative therapies tried + outcomes
  - Supporting guidelines / evidence references
  - Letter of Medical Necessity (re-uses services.letters)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_SYSTEM = """You assemble a prior-authorization packet from an encounter note + order details. \
Return JSON only.

Output:
{
  "diagnosis_summary": "1-2 line summary of the dx and severity",
  "service_summary": "1 line of what's being requested",
  "clinical_rationale": "2-4 paragraphs of medical necessity grounded in the note",
  "alternatives_tried": "bullet-style list of prior treatments and outcomes",
  "guidelines_cited": [
    {"name": "ACR Appropriateness Criteria - low back pain", "year": 2023, "applies": "high"}
  ],
  "supporting_evidence_quotes": [
    "verbatim short snippet from the note"
  ]
}
"""


def assemble_packet(
    *,
    note_text: str,
    diagnosis: str,
    icd10: str,
    requested_service: str,
    cpt_or_hcpcs_or_ndc: str,
    patient: dict[str, Any],
    payer: dict[str, Any],
    provider: dict[str, Any],
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        narrative = {
            "diagnosis_summary": diagnosis,
            "service_summary": requested_service,
            "clinical_rationale": "(AI rationale unavailable; please complete manually)",
            "alternatives_tried": "",
            "guidelines_cited": [],
            "supporting_evidence_quotes": [],
        }
    else:
        payload = {
            "note": note_text,
            "diagnosis": diagnosis,
            "icd10": icd10,
            "requested_service": requested_service,
            "cpt_or_hcpcs_or_ndc": cpt_or_hcpcs_or_ndc,
        }
        try:
            resp = claude.messages_create(
                model=_MODEL,
                max_tokens=1100,
                system=_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload)}],
                purpose="pa_packet",
            )
            text = "".join(getattr(b, "text", "") for b in resp.content).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            narrative = json.loads(text)
        except Exception as e:
            log.warning("pa_packet failed: %s", e)
            narrative = {"clinical_rationale": "(rationale generation failed)"}

    return {
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "patient": {
            "name": patient.get("name") or f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip(),
            "dob": patient.get("dob"),
            "member_id": patient.get("member_id"),
            "phone": patient.get("phone"),
        },
        "payer": payer,
        "provider": provider,
        "request": {
            "diagnosis": diagnosis,
            "icd10": icd10,
            "service": requested_service,
            "code": cpt_or_hcpcs_or_ndc,
        },
        "narrative": narrative,
        "submission_channels": [
            {"channel": "da_vinci_pas", "status": "ready", "endpoint_hint": "FHIR /Claim with $submit operation"},
            {"channel": "surescripts_completepa", "status": "ready" if "ndc" in (cpt_or_hcpcs_or_ndc or "").lower() else "n/a"},
            {"channel": "payer_portal_pdf", "status": "ready"},
        ],
    }


def to_da_vinci_claim(packet: dict[str, Any]) -> dict[str, Any]:
    """Build the FHIR R4 Claim resource for Da Vinci PAS submission. (Sketched shape.)"""
    return {
        "resourceType": "Claim",
        "status": "active",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "professional"}]},
        "use": "preauthorization",
        "patient": {"display": packet["patient"]["name"]},
        "billablePeriod": {"start": packet["submitted_at"][:10]},
        "created": packet["submitted_at"],
        "insurer": {"display": packet["payer"].get("name", "")},
        "provider": {"display": packet["provider"].get("name", "")},
        "diagnosis": [{
            "sequence": 1,
            "diagnosisCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": packet["request"]["icd10"]}]},
        }],
        "item": [{
            "sequence": 1,
            "productOrService": {"coding": [{"system": "http://www.ama-assn.org/go/cpt", "code": packet["request"]["code"]}]},
            "servicedDate": packet["submitted_at"][:10],
        }],
        "supportingInfo": [{
            "sequence": 1,
            "category": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claiminformationcategory", "code": "info"}]},
            "valueString": packet["narrative"].get("clinical_rationale", "")[:5000],
        }],
    }
