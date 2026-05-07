"""Letter / form library — auto-fill from chart context, render PDF.

Templates are house-style prose templates with named slot fields. The LLM fills
the slots from the chart context; deterministic Jinja-style rendering produces
the final document. PDF render via reportlab so the output is signable.

12 templates ship in v1; the registry is open for new ones.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


TEMPLATES: dict[str, dict[str, Any]] = {
    "fmla_who_certifies_health_provider": {
        "name": "FMLA WH-380-E (Health Care Provider Certification — Employee)",
        "audience": "Employer / DOL",
        "slots": [
            "patient_name", "patient_dob", "diagnosis", "icd10", "onset_date",
            "duration_estimate", "treatment_summary", "incapacity_episodic",
            "follow_up_frequency", "provider_name", "provider_credentials",
            "provider_signature_date",
        ],
        "body": (
            "FMLA Form WH-380-E - Health Care Provider Certification\n\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n\n"
            "Approximate date condition began: {onset_date}\n"
            "Probable duration of condition: {duration_estimate}\n\n"
            "Diagnosis (ICD-10 {icd10}): {diagnosis}\n\n"
            "Regimen of treatment to be prescribed:\n{treatment_summary}\n\n"
            "Episodic incapacity / flare-ups: {incapacity_episodic}\n"
            "Estimated frequency of follow-up: {follow_up_frequency}\n\n"
            "Provider: {provider_name}, {provider_credentials}\n"
            "Signed: {provider_signature_date}\n"
        ),
    },
    "school_note": {
        "name": "School absence / return-to-school note",
        "audience": "School administration",
        "slots": ["patient_name", "patient_dob", "absence_dates", "reason_lay", "return_date", "restrictions", "provider_name", "today"],
        "body": (
            "{today}\n\n"
            "To Whom It May Concern:\n\n"
            "{patient_name} (DOB {patient_dob}) was seen in our office and is excused from school "
            "from {absence_dates} due to {reason_lay}. The student may return to school on {return_date}.\n\n"
            "Restrictions: {restrictions}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "work_note": {
        "name": "Work absence / return-to-work note",
        "audience": "Employer",
        "slots": ["patient_name", "absence_dates", "return_date", "restrictions", "provider_name", "today"],
        "body": (
            "{today}\n\n"
            "To Whom It May Concern:\n\n"
            "{patient_name} was under my care and is excused from work from {absence_dates}. "
            "The patient may return to work on {return_date}.\n\n"
            "Work restrictions: {restrictions}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "sports_clearance_pre_participation": {
        "name": "Pre-Participation Physical Evaluation (PPE) clearance",
        "audience": "School athletics",
        "slots": ["patient_name", "patient_dob", "exam_date", "cleared_status", "restrictions", "follow_up", "provider_name"],
        "body": (
            "PPE Clearance\n\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n"
            "Exam date: {exam_date}\n\n"
            "Status: {cleared_status}\n"
            "Restrictions: {restrictions}\n"
            "Follow-up: {follow_up}\n\n"
            "Provider: {provider_name}\n"
        ),
    },
    "letter_of_medical_necessity": {
        "name": "Letter of Medical Necessity (DME / off-label / specialty)",
        "audience": "Insurance company medical director",
        "slots": [
            "patient_name", "patient_dob", "member_id", "diagnosis", "icd10",
            "requested_item_or_service", "cpt_or_hcpcs", "clinical_rationale",
            "alternatives_tried", "provider_name", "provider_credentials", "today",
        ],
        "body": (
            "{today}\n\n"
            "Re: Letter of Medical Necessity\n"
            "Patient: {patient_name}   DOB: {patient_dob}   Member ID: {member_id}\n"
            "Diagnosis: {diagnosis} (ICD-10 {icd10})\n"
            "Requested: {requested_item_or_service} ({cpt_or_hcpcs})\n\n"
            "Clinical rationale:\n{clinical_rationale}\n\n"
            "Previously tried / failed:\n{alternatives_tried}\n\n"
            "I attest the requested item/service is medically necessary. Please contact our office with questions.\n\n"
            "Sincerely,\n{provider_name}, {provider_credentials}\n"
        ),
    },
    "prior_auth_appeal": {
        "name": "Prior auth denial appeal",
        "audience": "Payer appeals committee",
        "slots": [
            "patient_name", "patient_dob", "member_id", "claim_number",
            "denied_service", "denial_reason", "clinical_response", "guidelines_cited",
            "alternatives_tried", "provider_name", "today",
        ],
        "body": (
            "{today}\n\n"
            "Re: Appeal of Prior Authorization Denial\n"
            "Patient: {patient_name} (DOB {patient_dob}, ID {member_id})\n"
            "Claim: {claim_number}\n\n"
            "Denied service: {denied_service}\n"
            "Denial reason: {denial_reason}\n\n"
            "Clinical response:\n{clinical_response}\n\n"
            "Supporting guidelines:\n{guidelines_cited}\n\n"
            "Previously tried / failed:\n{alternatives_tried}\n\n"
            "We respectfully request reconsideration.\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "denial_appeal_external": {
        "name": "External medical-necessity appeal",
        "audience": "Independent Review Organization",
        "slots": ["patient_name", "patient_dob", "denied_service", "denial_basis", "clinical_summary", "outcome_request", "provider_name", "today"],
        "body": (
            "{today}\n\n"
            "External Review Request\n\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n"
            "Denied service: {denied_service}\n"
            "Basis of denial: {denial_basis}\n\n"
            "Clinical summary:\n{clinical_summary}\n\n"
            "Requested outcome: {outcome_request}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "referral_letter": {
        "name": "Referral letter to specialist",
        "audience": "Receiving specialist",
        "slots": [
            "patient_name", "patient_dob", "referring_provider", "specialty",
            "reason_for_referral", "relevant_history", "relevant_meds_allergies",
            "relevant_imaging_labs", "specific_question", "today",
        ],
        "body": (
            "{today}\n\n"
            "Dear {specialty} colleague,\n\n"
            "Thank you for seeing {patient_name} (DOB {patient_dob}).\n\n"
            "Reason for referral: {reason_for_referral}\n\n"
            "Relevant history: {relevant_history}\n"
            "Medications / allergies: {relevant_meds_allergies}\n"
            "Recent imaging / labs: {relevant_imaging_labs}\n\n"
            "Specific question(s): {specific_question}\n\n"
            "Please copy me on your evaluation. I appreciate your input.\n\n"
            "Sincerely,\n{referring_provider}\n"
        ),
    },
    "esa_animal_letter": {
        "name": "Emotional Support Animal letter",
        "audience": "Housing / airline",
        "slots": ["patient_name", "diagnosis_general", "treatment_relationship", "esa_benefit_summary", "provider_name", "license_number", "today"],
        "body": (
            "{today}\n\n"
            "To Whom It May Concern:\n\n"
            "I am the licensed mental health provider treating {patient_name}. The patient has a "
            "diagnosed mental health condition ({diagnosis_general}) and is currently engaged in "
            "treatment ({treatment_relationship}). An emotional support animal would substantially "
            "reduce identified symptoms ({esa_benefit_summary}).\n\n"
            "This letter does not certify a service animal under the ADA.\n\n"
            "Sincerely,\n{provider_name}\nLicense: {license_number}\n"
        ),
    },
    "controlled_substance_travel": {
        "name": "Controlled-substance travel letter",
        "audience": "Airport security / foreign customs",
        "slots": ["patient_name", "patient_dob", "medications", "diagnosis_lay", "travel_dates", "provider_name", "dea_number", "today"],
        "body": (
            "{today}\n\n"
            "To Whom It May Concern:\n\n"
            "{patient_name} (DOB {patient_dob}) is under my care and requires the following "
            "medications during travel:\n\n{medications}\n\n"
            "These medications are clinically necessary for {diagnosis_lay} and are dispensed in "
            "their original pharmacy-labeled containers. Travel period: {travel_dates}.\n\n"
            "Sincerely,\n{provider_name}\nDEA: {dea_number}\n"
        ),
    },
    "jury_duty_excuse": {
        "name": "Jury duty medical excuse",
        "audience": "Jury commissioner",
        "slots": ["patient_name", "patient_dob", "summons_date", "medical_reason_brief", "duration", "provider_name", "today"],
        "body": (
            "{today}\n\n"
            "Jury Commissioner,\n\n"
            "{patient_name} (DOB {patient_dob}) is summoned for jury service on {summons_date}. The "
            "patient has a medical condition that prevents jury service for the next {duration}. "
            "Specifically: {medical_reason_brief}.\n\n"
            "Please excuse the patient.\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "return_to_activity": {
        "name": "Return-to-activity / return-to-play",
        "audience": "Athletic trainer / coach / employer",
        "slots": ["patient_name", "injury", "stage", "permitted_activity", "restrictions", "next_recheck", "provider_name", "today"],
        "body": (
            "{today}\n\n"
            "Return-to-activity progression\n\n"
            "Patient: {patient_name}\nInjury: {injury}\nStage: {stage}\n\n"
            "Permitted activity: {permitted_activity}\nRestrictions: {restrictions}\nNext recheck: {next_recheck}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [{"key": k, "name": v["name"], "audience": v["audience"], "slots": v["slots"]} for k, v in TEMPLATES.items()]


def render_text(template_key: str, slots: dict[str, str]) -> str:
    tpl = TEMPLATES.get(template_key)
    if not tpl:
        raise ValueError(f"unknown template '{template_key}'")
    body = tpl["body"]
    safe = {k: (slots.get(k) or "____") for k in tpl["slots"]}
    return body.format(**safe)


_AI_FILL_SYSTEM = """You fill medical-document slot variables from the supplied chart context. \
Be conservative — if a slot is genuinely not supported by the context, leave it blank (empty string).

Return JSON ONLY: a flat object mapping each requested slot name to its filled value (string).
No markdown, no preamble.

Tone: clinical, plain, never use markdown formatting in slot values, no extra commentary."""


def ai_fill_slots(
    template_key: str,
    chart_context: dict[str, Any],
) -> dict[str, str]:
    tpl = TEMPLATES.get(template_key)
    if not tpl or not settings.anthropic_api_key:
        return {k: "" for k in (tpl or {}).get("slots", [])}
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    payload = {
        "template_key": template_key,
        "template_name": tpl["name"],
        "audience": tpl["audience"],
        "slots_required": tpl["slots"],
        "today": today,
        "chart_context": chart_context,
    }
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_AI_FILL_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
            purpose="letter_fill",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(text)
    except Exception as e:
        log.warning("letter ai_fill failed: %s", e)
        out = {}
    out.setdefault("today", today)
    return {k: str(out.get(k, "") or "") for k in tpl["slots"]}


def to_pdf(template_key: str, slots: dict[str, str]) -> bytes:
    """Render to a single-page PDF (letter-size). Pure-python via reportlab."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:  # pragma: no cover
        return render_text(template_key, slots).encode("utf-8")
    text = render_text(template_key, slots)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=72, rightMargin=72, topMargin=54, bottomMargin=54)
    styles = getSampleStyleSheet()
    story = []
    for para in text.split("\n\n"):
        story.append(Paragraph(para.replace("\n", "<br/>"), styles["BodyText"]))
        story.append(Spacer(1, 8))
    doc.build(story)
    return buf.getvalue()
