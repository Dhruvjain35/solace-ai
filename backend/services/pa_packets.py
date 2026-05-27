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
  - Conservative-care / step-therapy documentation
  - Supporting guidelines / evidence references
  - Letter of Medical Necessity (full prose, signature block)

Public surface:
  - assemble_packet(...)       -> full structured packet (signature stable)
  - to_da_vinci_claim(packet)  -> single FHIR Claim resource (signature stable)
  - to_da_vinci_bundle(packet) -> full PAS collection Bundle for Claim/$submit
  - to_human_packet(packet)    -> PDF-ready ordered human packet
  - check_completeness(...)    -> payer-reject-prone missing-field audit
  - generate_appeal(...)       -> evidence-grounded denial-appeal letter
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


# --------------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------------

_SYSTEM_NARRATIVE = """You assemble the clinical narrative for a prior-authorization packet \
from an encounter note + order details. Return JSON only. Ground every claim in the note; \
never invent facts. If the note lacks something, leave the field empty rather than fabricate.

Output:
{
  "diagnosis_summary": "1-2 line summary of the dx and severity",
  "service_summary": "1 line of what's being requested",
  "clinical_rationale": "2-4 paragraphs of medical necessity grounded in the note",
  "alternatives_tried": "bullet-style list of prior treatments and outcomes",
  "conservative_care": "documentation of conservative / step-therapy measures attempted, \
with dates/durations if present, and why they were insufficient",
  "guidelines_cited": [
    {"name": "ACR Appropriateness Criteria - low back pain", "year": 2023, "applies": "high"}
  ],
  "supporting_evidence_quotes": [
    "verbatim short snippet from the note"
  ],
  "urgency": "routine | urgent | emergent",
  "expected_outcome": "1 line on the clinical goal of the requested service"
}
"""

_SYSTEM_LMN = """You write a formal Letter of Medical Necessity for a prior-authorization \
submission. The letter is addressed to the payer's medical director. Return JSON only.

Tone: professional, concise, clinical. No emojis. Every clinical assertion must be \
traceable to the supplied note or request data; do not fabricate findings, dates or labs.

Output:
{
  "letter_body": "full letter prose, 4-7 paragraphs: (1) patient + payer + request line, \
(2) diagnosis and clinical findings, (3) prior/conservative care tried and failed, \
(4) why the requested service is medically necessary now, (5) supporting guidelines, \
(6) closing request for approval. Use \\n\\n between paragraphs. Do NOT include the \
date, salutation header, or signature block - those are added deterministically."
}
"""

_SYSTEM_APPEAL = """You write a formal appeal letter responding to a prior-authorization \
denial. The letter is addressed to the payer's appeals / medical-review department. \
Return JSON only.

You are given: the original PA packet, the payer's stated denial reason, and the denial \
category. Rebut the denial reason point by point, grounded ONLY in the documented clinical \
facts. Never invent new clinical evidence. If the denial is due to a documentation gap, \
state explicitly what is being supplied to close it. Cite guidelines already in the packet.

Tone: firm, professional, evidence-driven. No emojis.

Output:
{
  "appeal_body": "full appeal letter prose, 4-6 paragraphs: (1) reference the denial and \
the member/claim, (2) restate the clinical picture and why the service is necessary, \
(3) directly rebut each point of the denial reason, (4) cite supporting guidelines and \
prior-treatment failure, (5) closing request to overturn the denial. Use \\n\\n between \
paragraphs. Do NOT include the date, header, or signature block.",
  "rebuttal_points": ["short bullet rebutting one element of the denial reason"],
  "denial_category": "medical_necessity | step_therapy | non_covered | documentation | \
coding | eligibility | experimental | other",
  "additional_evidence_requested": ["clinical item that would strengthen the appeal if the \
clinician can supply it, e.g. 'imaging report dated within 90 days'"]
}
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _claude_json(*, system: str, payload: dict[str, Any], max_tokens: int, purpose: str) -> dict[str, Any]:
    """Call Claude expecting a JSON object back. Raises on failure (caller handles)."""
    resp = claude.messages_create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        purpose=purpose,
    )
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


# --------------------------------------------------------------------------------
# Packet assembly
# --------------------------------------------------------------------------------

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
    include_lmn: bool = True,
    prior_treatments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the full PA packet.

    Signature is backward compatible: the first eight args are unchanged; the two
    new keyword args are optional with defaults.

    - include_lmn:       also generate a full Letter of Medical Necessity (parallel call).
    - prior_treatments:  optional structured list of prior therapies, each e.g.
                         {"name": "physical therapy", "dates": "2025-09..2025-11",
                          "outcome": "no sustained relief"}. Folded into the prompt
                         and surfaced verbatim in the packet for the completeness check.
    """
    prior_treatments = prior_treatments or []

    narrative: dict[str, Any] = {}
    lmn: dict[str, Any] = {}

    if not settings.anthropic_api_key:
        narrative = {
            "diagnosis_summary": diagnosis,
            "service_summary": requested_service,
            "clinical_rationale": "(AI rationale unavailable; please complete manually)",
            "alternatives_tried": "",
            "conservative_care": "",
            "guidelines_cited": [],
            "supporting_evidence_quotes": [],
            "urgency": "routine",
            "expected_outcome": "",
        }
        lmn = {"letter_body": "(Letter of Medical Necessity unavailable; please complete manually)"}
    else:
        base_payload = {
            "note": note_text,
            "diagnosis": diagnosis,
            "icd10": icd10,
            "requested_service": requested_service,
            "cpt_or_hcpcs_or_ndc": cpt_or_hcpcs_or_ndc,
            "prior_treatments": prior_treatments,
        }

        def _do_narrative() -> dict[str, Any]:
            return _claude_json(
                system=_SYSTEM_NARRATIVE, payload=base_payload,
                max_tokens=1300, purpose="pa_packet",
            )

        def _do_lmn() -> dict[str, Any]:
            lmn_payload = dict(base_payload)
            lmn_payload["patient_name"] = (
                patient.get("name")
                or f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip()
            )
            lmn_payload["payer_name"] = payer.get("name", "")
            lmn_payload["provider_name"] = provider.get("name", "")
            return _claude_json(
                system=_SYSTEM_LMN, payload=lmn_payload,
                max_tokens=1400, purpose="pa_lmn",
            )

        tasks: dict[str, Any] = {"narrative": _do_narrative}
        if include_lmn:
            tasks["lmn"] = _do_lmn

        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = {key: pool.submit(fn) for key, fn in tasks.items()}
            for key, fut in futures.items():
                try:
                    results[key] = fut.result()
                except Exception as e:  # noqa: BLE001
                    log.warning("pa_packet %s generation failed: %s", key, e)
                    results[key] = None

        narrative = results.get("narrative") or {"clinical_rationale": "(rationale generation failed)"}
        if include_lmn:
            lmn = results.get("lmn") or {"letter_body": "(Letter of Medical Necessity generation failed)"}

    patient_name = (
        patient.get("name")
        or f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip()
    )

    packet: dict[str, Any] = {
        "packet_id": str(uuid.uuid4()),
        "submitted_at": _now_iso(),
        "patient": {
            "name": patient_name,
            "first_name": patient.get("first_name"),
            "last_name": patient.get("last_name"),
            "dob": patient.get("dob"),
            "sex": patient.get("sex") or patient.get("gender"),
            "member_id": patient.get("member_id"),
            "phone": patient.get("phone"),
            "address": patient.get("address"),
        },
        "payer": payer,
        "provider": provider,
        "request": {
            "diagnosis": diagnosis,
            "icd10": icd10,
            "service": requested_service,
            "code": cpt_or_hcpcs_or_ndc,
            "code_system": _code_system_label(cpt_or_hcpcs_or_ndc),
        },
        "prior_treatments": prior_treatments,
        "narrative": narrative,
        "letter_of_medical_necessity": lmn if include_lmn else {},
        "submission_channels": [
            {"channel": "da_vinci_pas", "status": "ready", "endpoint_hint": "FHIR Bundle POST to Claim/$submit"},
            {"channel": "surescripts_completepa", "status": "ready" if _is_ndc(cpt_or_hcpcs_or_ndc) else "n/a"},
            {"channel": "payer_portal_pdf", "status": "ready"},
        ],
    }
    # Self-audit: attach the completeness check so callers always see reject risk.
    packet["completeness"] = check_completeness(packet)
    return packet


def _is_ndc(code: str | None) -> bool:
    """NDC codes are 10-11 digits, often hyphenated 5-4-2 / 5-3-2 / 4-4-2."""
    if not code:
        return False
    digits = code.replace("-", "").strip()
    return digits.isdigit() and 10 <= len(digits) <= 11


def _code_system_label(code: str | None) -> str:
    if _is_ndc(code):
        return "NDC"
    c = (code or "").strip().upper()
    if len(c) == 5 and c.isdigit():
        return "CPT"
    if len(c) == 5 and c[0].isalpha() and c[1:].isdigit():
        return "HCPCS"
    return "unknown"


# --------------------------------------------------------------------------------
# Completeness check — flags payer-reject-prone missing fields
# --------------------------------------------------------------------------------

# Each rule: (severity, field-path getter, human label, why-it-rejects hint).
def check_completeness(packet: dict[str, Any]) -> dict[str, Any]:
    """Audit a packet for the fields payers most often reject PA requests over.

    Returns:
      {
        "ready_to_submit": bool,     # False if any blocker
        "blockers":  [ {field, message, fix} ],   # will be rejected without these
        "warnings":  [ {field, message, fix} ],   # commonly cause RFI / pend
        "score": 0..100,             # rough submission-readiness score
      }
    """
    patient = packet.get("patient") or {}
    payer = packet.get("payer") or {}
    provider = packet.get("provider") or {}
    request = packet.get("request") or {}
    narrative = packet.get("narrative") or {}
    lmn = packet.get("letter_of_medical_necessity") or {}
    prior = packet.get("prior_treatments") or []

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def blk(field: str, message: str, fix: str) -> None:
        blockers.append({"field": field, "message": message, "fix": fix})

    def wrn(field: str, message: str, fix: str) -> None:
        warnings.append({"field": field, "message": message, "fix": fix})

    # --- Identity / eligibility (top denial cause: member mismatch) ---
    if not (patient.get("name") or "").strip():
        blk("patient.name", "Patient name is missing.", "Add the patient's full legal name.")
    if not patient.get("dob"):
        blk("patient.dob", "Patient date of birth is missing.",
            "Add DOB; payers reject on member identity mismatch without it.")
    if not (patient.get("member_id") or "").strip():
        blk("patient.member_id", "Insurance member ID is missing.",
            "Add the subscriber/member ID exactly as printed on the card.")
    if not patient.get("sex"):
        wrn("patient.sex", "Patient sex/gender is missing.",
            "Add sex; some payer edits require it for the FHIR Patient resource.")

    # --- Payer ---
    if not (payer.get("name") or "").strip():
        blk("payer.name", "Payer name is missing.", "Add the insurer name.")
    if not (payer.get("payer_id") or payer.get("id")):
        wrn("payer.payer_id", "Payer ID / plan ID is missing.",
            "Add the payer ID so the Bundle routes to the correct insurer.")

    # --- Provider (NPI is a hard reject field) ---
    npi = str(provider.get("npi") or "").replace("-", "").strip()
    if not npi:
        blk("provider.npi", "Ordering provider NPI is missing.",
            "Add the 10-digit NPI; PA requests reject without an identifiable provider.")
    elif not (npi.isdigit() and len(npi) == 10):
        blk("provider.npi", f"Provider NPI '{npi}' is not a valid 10-digit NPI.",
            "Correct the NPI to exactly 10 digits.")
    if not (provider.get("name") or "").strip():
        blk("provider.name", "Ordering provider name is missing.", "Add the provider's name.")
    if not (provider.get("tax_id") or provider.get("tin")):
        wrn("provider.tax_id", "Billing Tax ID / TIN is missing.",
            "Add the group TIN; many payers pend the claim for it.")

    # --- Coding (mismatched / missing codes are a top-3 reject reason) ---
    if not (request.get("icd10") or "").strip():
        blk("request.icd10", "ICD-10 diagnosis code is missing.", "Add a specific ICD-10-CM code.")
    elif not _looks_like_icd10(request.get("icd10")):
        wrn("request.icd10", f"'{request.get('icd10')}' does not look like a valid ICD-10-CM code.",
            "Verify the code format (letter + digits, e.g. M54.50).")
    if not (request.get("code") or "").strip():
        blk("request.code", "Procedure/service code (CPT/HCPCS/NDC) is missing.",
            "Add the code for the requested service.")
    elif request.get("code_system") == "unknown":
        wrn("request.code", f"Service code '{request.get('code')}' is not a recognized CPT/HCPCS/NDC format.",
            "Verify the code; payer edits reject unrecognized code formats.")

    # --- Clinical narrative / medical necessity ---
    rationale = (narrative.get("clinical_rationale") or "").strip()
    if not rationale or rationale.startswith("("):
        blk("narrative.clinical_rationale", "Clinical rationale / medical necessity is missing.",
            "Generate or write the medical-necessity rationale; payers auto-deny without it.")
    elif len(rationale) < 200:
        wrn("narrative.clinical_rationale", "Clinical rationale is very short.",
            "Expand the rationale; thin documentation triggers requests for information.")

    conservative = (narrative.get("conservative_care") or "").strip()
    alternatives = (narrative.get("alternatives_tried") or "").strip()
    if not conservative and not alternatives and not prior:
        wrn("narrative.conservative_care", "No conservative-care or prior-treatment documentation.",
            "Document step-therapy / conservative measures tried; step-therapy denials are common.")

    if not narrative.get("guidelines_cited"):
        wrn("narrative.guidelines_cited", "No clinical guidelines cited.",
            "Cite an applicable guideline (e.g. ACR, NCCN) to support medical necessity.")

    if not narrative.get("supporting_evidence_quotes"):
        wrn("narrative.supporting_evidence_quotes", "No verbatim evidence quotes from the note.",
            "Include short note excerpts; payers value traceable documentation.")

    # --- Letter of Medical Necessity ---
    lmn_body = (lmn.get("letter_body") or "").strip()
    if lmn and (not lmn_body or lmn_body.startswith("(")):
        wrn("letter_of_medical_necessity", "Letter of Medical Necessity is missing or failed.",
            "Regenerate the LMN; many payers require a signed LMN attachment.")

    score = max(0, 100 - 25 * len(blockers) - 6 * len(warnings))
    return {
        "ready_to_submit": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "score": score,
        "checked_at": _now_iso(),
    }


def _looks_like_icd10(code: str | None) -> bool:
    """ICD-10-CM: a letter, two alphanumerics, optional dot + up to 4 more chars."""
    if not code:
        return False
    c = code.strip().upper().replace(".", "")
    if len(c) < 3 or len(c) > 7:
        return False
    return c[0].isalpha() and c[1].isalnum() and c[2].isalnum()


# --------------------------------------------------------------------------------
# FHIR — Da Vinci PAS
# --------------------------------------------------------------------------------

def to_da_vinci_claim(packet: dict[str, Any]) -> dict[str, Any]:
    """Build the FHIR R4 Claim resource for Da Vinci PAS submission.

    Signature unchanged. When called standalone the Claim uses display-only
    references; when called via to_da_vinci_bundle() it is given resolvable
    references through the optional internal kwargs below.
    """
    return _build_claim(packet)


def _build_claim(
    packet: dict[str, Any],
    *,
    patient_ref: str | None = None,
    provider_ref: str | None = None,
    insurer_ref: str | None = None,
    coverage_ref: str | None = None,
    doc_ref: str | None = None,
) -> dict[str, Any]:
    request = packet.get("request") or {}
    narrative = packet.get("narrative") or {}
    submitted = packet.get("submitted_at") or _now_iso()
    code = request.get("code") or ""
    code_system = {
        "CPT": "http://www.ama-assn.org/go/cpt",
        "HCPCS": "https://bluebutton.cms.gov/resources/codesystem/hcpcs",
        "NDC": "http://hl7.org/fhir/sid/ndc",
    }.get(request.get("code_system"), "http://www.ama-assn.org/go/cpt")

    urgency = (narrative.get("urgency") or "routine").lower()
    priority_code = {"emergent": "stat", "urgent": "asap"}.get(urgency, "normal")

    claim: dict[str, Any] = {
        "resourceType": "Claim",
        "id": f"claim-{(packet.get('packet_id') or 'pa')[:8]}",
        "meta": {"profile": [
            "http://hl7.org/fhir/us/davinci-pas/StructureDefinition/profile-claim"
        ]},
        "status": "active",
        "type": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/claim-type",
            "code": "professional",
        }]},
        "use": "preauthorization",
        "patient": ({"reference": patient_ref} if patient_ref
                    else {"display": (packet.get("patient") or {}).get("name", "")}),
        "billablePeriod": {"start": submitted[:10]},
        "created": submitted,
        "insurer": ({"reference": insurer_ref} if insurer_ref
                    else {"display": (packet.get("payer") or {}).get("name", "")}),
        "provider": ({"reference": provider_ref} if provider_ref
                     else {"display": (packet.get("provider") or {}).get("name", "")}),
        "priority": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/processpriority",
            "code": priority_code,
        }]},
        "diagnosis": [{
            "sequence": 1,
            "diagnosisCodeableConcept": {"coding": [{
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "code": request.get("icd10", ""),
                "display": request.get("diagnosis", ""),
            }]},
        }],
        "insurance": [{
            "sequence": 1,
            "focal": True,
            "coverage": ({"reference": coverage_ref} if coverage_ref
                         else {"display": (packet.get("payer") or {}).get("name", "Coverage")}),
        }],
        "item": [{
            "sequence": 1,
            "productOrService": {"coding": [{
                "system": code_system,
                "code": code,
                "display": request.get("service", ""),
            }]},
            "servicedDate": submitted[:10],
        }],
        "supportingInfo": [],
    }

    seq = 1
    rationale = (narrative.get("clinical_rationale") or "")[:5000]
    if rationale:
        claim["supportingInfo"].append({
            "sequence": seq,
            "category": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/claiminformationcategory",
                "code": "info",
            }]},
            "valueString": rationale,
        })
        seq += 1
    if doc_ref:
        claim["supportingInfo"].append({
            "sequence": seq,
            "category": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/claiminformationcategory",
                "code": "attachment",
            }]},
            "valueReference": {"reference": doc_ref},
        })
    return claim


def to_da_vinci_bundle(packet: dict[str, Any]) -> dict[str, Any]:
    """Build a FHIR R4 'collection' Bundle for the Da Vinci PAS Claim/$submit operation.

    Contains: Claim + Patient + Coverage + Practitioner + Organization (payer)
    + Organization (provider org) + DocumentReference (LMN attachment).
    All cross-references are resolvable urn:uuid: references.
    """
    patient = packet.get("patient") or {}
    payer = packet.get("payer") or {}
    provider = packet.get("provider") or {}
    lmn = packet.get("letter_of_medical_necessity") or {}
    submitted = packet.get("submitted_at") or _now_iso()

    pid = f"urn:uuid:{uuid.uuid4()}"
    cov_id = f"urn:uuid:{uuid.uuid4()}"
    pract_id = f"urn:uuid:{uuid.uuid4()}"
    payer_org_id = f"urn:uuid:{uuid.uuid4()}"
    prov_org_id = f"urn:uuid:{uuid.uuid4()}"
    doc_id = f"urn:uuid:{uuid.uuid4()}"
    claim_id = f"urn:uuid:{uuid.uuid4()}"

    # --- Patient ---
    patient_res: dict[str, Any] = {
        "resourceType": "Patient",
        "name": [{
            "family": patient.get("last_name") or "",
            "given": [g for g in [patient.get("first_name")] if g] or _split_name(patient.get("name")),
            "text": patient.get("name") or "",
        }],
    }
    if patient.get("dob"):
        patient_res["birthDate"] = str(patient["dob"])[:10]
    if patient.get("sex"):
        sex = str(patient["sex"]).lower()
        patient_res["gender"] = {"m": "male", "f": "female"}.get(sex[:1], sex) if sex else None
        if patient_res["gender"] is None:
            patient_res.pop("gender")
    if patient.get("member_id"):
        patient_res["identifier"] = [{
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                "code": "MB", "display": "Member Number",
            }]},
            "value": str(patient["member_id"]),
        }]
    if patient.get("phone"):
        patient_res["telecom"] = [{"system": "phone", "value": str(patient["phone"])}]

    # --- Coverage ---
    coverage_res = {
        "resourceType": "Coverage",
        "status": "active",
        "beneficiary": {"reference": pid},
        "payor": [{"reference": payer_org_id}],
    }
    if patient.get("member_id"):
        coverage_res["subscriberId"] = str(patient["member_id"])
    if payer.get("plan") or payer.get("group"):
        coverage_res["class"] = [{
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/coverage-class",
                "code": "plan",
            }]},
            "value": str(payer.get("plan") or payer.get("group")),
        }]

    # --- Practitioner (ordering provider) ---
    practitioner_res: dict[str, Any] = {
        "resourceType": "Practitioner",
        "name": [{"text": provider.get("name") or ""}],
    }
    npi = str(provider.get("npi") or "").replace("-", "").strip()
    if npi:
        practitioner_res["identifier"] = [{
            "system": "http://hl7.org/fhir/sid/us-npi",
            "value": npi,
        }]
    if provider.get("credentials"):
        practitioner_res["qualification"] = [{
            "code": {"text": str(provider["credentials"])}
        }]

    # --- Organization: payer ---
    payer_org_res: dict[str, Any] = {
        "resourceType": "Organization",
        "name": payer.get("name") or "",
        "type": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/organization-type",
            "code": "ins", "display": "Insurance Company",
        }]}],
    }
    if payer.get("payer_id") or payer.get("id"):
        payer_org_res["identifier"] = [{
            "system": "http://hl7.org/fhir/sid/us-npi" if False else "urn:oid:payer-id",
            "value": str(payer.get("payer_id") or payer.get("id")),
        }]

    # --- Organization: provider billing org ---
    prov_org_res: dict[str, Any] = {
        "resourceType": "Organization",
        "name": provider.get("organization") or provider.get("org_name") or provider.get("name") or "",
        "type": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/organization-type",
            "code": "prov", "display": "Healthcare Provider",
        }]}],
    }
    tin = provider.get("tax_id") or provider.get("tin")
    if tin:
        prov_org_res["identifier"] = [{
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                "code": "TAX",
            }]},
            "value": str(tin),
        }]

    # --- DocumentReference: Letter of Medical Necessity ---
    lmn_body = (lmn.get("letter_body") or "").strip()
    doc_res = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"coding": [{
            "system": "http://loinc.org",
            "code": "57133-1",
            "display": "Referral note",
        }]},
        "description": "Letter of Medical Necessity",
        "subject": {"reference": pid},
        "date": submitted,
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data": base64.b64encode(lmn_body.encode("utf-8")).decode("ascii") if lmn_body else "",
                "title": "Letter of Medical Necessity",
            }
        }],
    }

    claim_res = _build_claim(
        packet,
        patient_ref=pid,
        provider_ref=pract_id,
        insurer_ref=payer_org_id,
        coverage_ref=cov_id,
        doc_ref=doc_id,
    )

    return {
        "resourceType": "Bundle",
        "id": f"pas-bundle-{(packet.get('packet_id') or 'pa')[:8]}",
        "meta": {"profile": [
            "http://hl7.org/fhir/us/davinci-pas/StructureDefinition/profile-pas-request-bundle"
        ]},
        "type": "collection",
        "timestamp": submitted,
        "entry": [
            {"fullUrl": claim_id, "resource": claim_res},
            {"fullUrl": pid, "resource": patient_res},
            {"fullUrl": cov_id, "resource": coverage_res},
            {"fullUrl": pract_id, "resource": practitioner_res},
            {"fullUrl": payer_org_id, "resource": payer_org_res},
            {"fullUrl": prov_org_id, "resource": prov_org_res},
            {"fullUrl": doc_id, "resource": doc_res},
        ],
    }


def _split_name(name: str | None) -> list[str]:
    if not name:
        return []
    return name.strip().split()[:1] or []


# --------------------------------------------------------------------------------
# Human / PDF-ready packet
# --------------------------------------------------------------------------------

def to_human_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Render the packet as an ordered set of sections ready for PDF layout.

    Returns:
      {
        "title": str,
        "generated_at": iso,
        "sections": [ {"heading": str, "body": str} ... ],   # in print order
        "signature_block": {...},
        "completeness": {...},   # copied so the PDF can show a readiness banner
      }
    """
    patient = packet.get("patient") or {}
    payer = packet.get("payer") or {}
    provider = packet.get("provider") or {}
    request = packet.get("request") or {}
    narrative = packet.get("narrative") or {}
    lmn = packet.get("letter_of_medical_necessity") or {}
    prior = packet.get("prior_treatments") or []
    submitted = packet.get("submitted_at") or _now_iso()
    today = submitted[:10]

    sections: list[dict[str, str]] = []

    # 1. Cover / request summary
    sections.append({
        "heading": "Prior Authorization Request",
        "body": (
            f"Date: {today}\n"
            f"Patient: {patient.get('name', '')}    DOB: {patient.get('dob', '')}\n"
            f"Member ID: {patient.get('member_id', '')}\n"
            f"Payer: {payer.get('name', '')}\n"
            f"Ordering Provider: {provider.get('name', '')}"
            f"{', NPI ' + str(provider.get('npi')) if provider.get('npi') else ''}\n\n"
            f"Diagnosis ({request.get('icd10', '')}): {request.get('diagnosis', '')}\n"
            f"Requested Service ({request.get('code_system', '')} "
            f"{request.get('code', '')}): {request.get('service', '')}\n"
            f"Urgency: {narrative.get('urgency', 'routine')}"
        ),
    })

    # 2. Clinical summary
    sections.append({
        "heading": "Clinical Summary",
        "body": "\n\n".join(filter(None, [
            narrative.get("diagnosis_summary"),
            narrative.get("service_summary"),
            ("Expected clinical outcome: " + narrative["expected_outcome"])
            if narrative.get("expected_outcome") else None,
        ])) or "(no clinical summary)",
    })

    # 3. Medical necessity rationale
    sections.append({
        "heading": "Medical Necessity Rationale",
        "body": narrative.get("clinical_rationale") or "(no rationale)",
    })

    # 4. Prior treatments / conservative care
    prior_lines: list[str] = []
    for t in prior:
        if isinstance(t, dict):
            line = "- " + " | ".join(
                str(v) for v in [t.get("name"), t.get("dates"), t.get("outcome")] if v
            )
        else:
            line = f"- {t}"
        prior_lines.append(line)
    conservative_body = "\n\n".join(filter(None, [
        narrative.get("conservative_care"),
        narrative.get("alternatives_tried"),
        ("\n".join(prior_lines)) if prior_lines else None,
    ])) or "(no prior-treatment or conservative-care documentation)"
    sections.append({
        "heading": "Prior Treatment & Conservative Care",
        "body": conservative_body,
    })

    # 5. Supporting guidelines
    guideline_lines = []
    for g in narrative.get("guidelines_cited") or []:
        if isinstance(g, dict):
            yr = f" ({g['year']})" if g.get("year") else ""
            applies = f" - applicability: {g['applies']}" if g.get("applies") else ""
            guideline_lines.append(f"- {g.get('name', '')}{yr}{applies}")
        else:
            guideline_lines.append(f"- {g}")
    sections.append({
        "heading": "Supporting Clinical Guidelines",
        "body": "\n".join(guideline_lines) or "(no guidelines cited)",
    })

    # 6. Supporting evidence quotes
    quotes = narrative.get("supporting_evidence_quotes") or []
    sections.append({
        "heading": "Supporting Documentation Excerpts",
        "body": "\n".join(f'"{q}"' for q in quotes) or "(no excerpts)",
    })

    # 7. Letter of Medical Necessity
    lmn_body = (lmn.get("letter_body") or "").strip()
    if lmn_body and not lmn_body.startswith("("):
        full_letter = (
            f"{today}\n\n"
            f"To the Medical Director, {payer.get('name', '')}:\n\n"
            f"RE: {patient.get('name', '')}, Member ID {patient.get('member_id', '')}\n"
            f"Prior Authorization for {request.get('service', '')} "
            f"({request.get('code', '')})\n\n"
            f"{lmn_body}\n\n"
            f"Sincerely,\n\n"
            f"{provider.get('name', '')}"
            f"{', ' + str(provider.get('credentials')) if provider.get('credentials') else ''}\n"
            f"{'NPI: ' + str(provider.get('npi')) if provider.get('npi') else ''}"
        )
    else:
        full_letter = lmn_body or "(Letter of Medical Necessity not generated)"
    sections.append({
        "heading": "Letter of Medical Necessity",
        "body": full_letter,
    })

    return {
        "title": f"Prior Authorization Packet - {patient.get('name', '')}",
        "generated_at": _now_iso(),
        "sections": sections,
        "signature_block": {
            "provider_name": provider.get("name"),
            "credentials": provider.get("credentials"),
            "npi": provider.get("npi"),
            "date": today,
        },
        "completeness": packet.get("completeness") or check_completeness(packet),
    }


# --------------------------------------------------------------------------------
# Denial appeal
# --------------------------------------------------------------------------------

def generate_appeal(
    packet: dict[str, Any],
    *,
    denial_reason: str,
    denial_category: str | None = None,
    denial_date: str | None = None,
    appeal_level: str = "first",
    additional_context: str = "",
) -> dict[str, Any]:
    """Generate an evidence-grounded denial-appeal letter from a denial reason.

    Args:
      packet:             a packet previously produced by assemble_packet().
      denial_reason:      the payer's verbatim stated reason for denial.
      denial_category:    optional payer-supplied category; if absent the model classifies it.
      denial_date:        optional ISO date of the denial notice.
      appeal_level:       "first" | "second" | "external" (peer-to-peer / IRO).
      additional_context: optional extra clinical facts the clinician wants considered
                          (must still be true; the model is told not to fabricate).

    Returns:
      {
        "appeal_id": uuid,
        "generated_at": iso,
        "appeal_level": str,
        "denial_reason": str,
        "denial_category": str,
        "letter": {           # PDF-ready, with deterministic header + signature block
          "header": str, "body": str, "signature": str, "full_text": str
        },
        "rebuttal_points": [...],
        "additional_evidence_requested": [...],
      }
    """
    patient = packet.get("patient") or {}
    payer = packet.get("payer") or {}
    provider = packet.get("provider") or {}
    request = packet.get("request") or {}
    narrative = packet.get("narrative") or {}
    today = _now_iso()[:10]

    ai: dict[str, Any] = {}
    if not settings.anthropic_api_key:
        ai = {
            "appeal_body": "(AI appeal unavailable; please draft the appeal manually based on "
                           "the documented clinical findings and the payer's stated denial reason.)",
            "rebuttal_points": [],
            "denial_category": denial_category or "other",
            "additional_evidence_requested": [],
        }
    else:
        payload = {
            "denial_reason": denial_reason,
            "denial_category": denial_category or "",
            "denial_date": denial_date or "",
            "appeal_level": appeal_level,
            "additional_context": additional_context,
            "original_request": request,
            "clinical_rationale": narrative.get("clinical_rationale", ""),
            "conservative_care": narrative.get("conservative_care", ""),
            "alternatives_tried": narrative.get("alternatives_tried", ""),
            "guidelines_cited": narrative.get("guidelines_cited", []),
            "supporting_evidence_quotes": narrative.get("supporting_evidence_quotes", []),
            "prior_treatments": packet.get("prior_treatments", []),
        }
        try:
            ai = _claude_json(
                system=_SYSTEM_APPEAL, payload=payload,
                max_tokens=1600, purpose="pa_appeal",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("pa appeal generation failed: %s", e)
            ai = {
                "appeal_body": "(Appeal generation failed; please draft manually.)",
                "rebuttal_points": [],
                "denial_category": denial_category or "other",
                "additional_evidence_requested": [],
            }

    level_label = {
        "first": "First-Level Appeal",
        "second": "Second-Level Appeal",
        "external": "External / Independent Review Appeal",
    }.get(appeal_level, "Appeal")

    header = (
        f"{today}\n\n"
        f"{payer.get('name', '')} - Appeals & Grievances Department\n\n"
        f"RE: {level_label} of Prior Authorization Denial\n"
        f"Patient: {patient.get('name', '')}    DOB: {patient.get('dob', '')}\n"
        f"Member ID: {patient.get('member_id', '')}\n"
        f"Requested Service: {request.get('service', '')} ({request.get('code', '')})\n"
        f"Diagnosis: {request.get('diagnosis', '')} ({request.get('icd10', '')})\n"
        + (f"Denial Notice Date: {denial_date}\n" if denial_date else "")
        + f"Stated Denial Reason: {denial_reason}"
    )
    signature = (
        f"Sincerely,\n\n"
        f"{provider.get('name', '')}"
        f"{', ' + str(provider.get('credentials')) if provider.get('credentials') else ''}\n"
        f"{'NPI: ' + str(provider.get('npi')) if provider.get('npi') else ''}"
    )
    body = ai.get("appeal_body") or "(no appeal body)"
    full_text = f"{header}\n\n{body}\n\n{signature}"

    return {
        "appeal_id": str(uuid.uuid4()),
        "generated_at": _now_iso(),
        "appeal_level": appeal_level,
        "denial_reason": denial_reason,
        "denial_category": ai.get("denial_category") or denial_category or "other",
        "letter": {
            "header": header,
            "body": body,
            "signature": signature,
            "full_text": full_text,
        },
        "rebuttal_points": ai.get("rebuttal_points") or [],
        "additional_evidence_requested": ai.get("additional_evidence_requested") or [],
        "references_packet_id": packet.get("packet_id"),
    }
