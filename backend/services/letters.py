"""Letter / form library — auto-fill from chart context, render PDF.

Templates are house-style prose templates with named slot fields. The LLM fills
the slots from the chart context; deterministic Jinja-style rendering produces
the final document. PDF render via reportlab so the output is signable.

Each registry entry carries a stable shape:
  - name        : human-readable title
  - audience    : who receives the document
  - category    : grouping key (see CATEGORIES) for UI filtering
  - slots       : every slot the body references
  - required    : the subset of slots that MUST be present for a complete doc
  - guidance    : LLM-facing instructions for conservative, accurate filling

~22 forms ship today; the registry is open for new ones. Public surface kept
stable for routers/clinical_ai.py: list_templates, render_text, ai_fill_slots,
to_pdf. New: generate_letter (one-shot fill + render + gap-check) and
generate_batch (parallel fan-out).
"""
from __future__ import annotations

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = settings.model_utility
_MAX_BATCH_WORKERS = 6


# Category vocabulary — keep keys stable; UI groups templates by these.
CATEGORIES: dict[str, str] = {
    "leave_certification": "Leave & FMLA certification",
    "absence_note": "School / work / camp absence notes",
    "activity_clearance": "Sports clearance & return-to-activity",
    "medical_necessity": "Medical necessity & payer appeals",
    "referral": "Referrals & care coordination",
    "disability": "Disability & accommodation",
    "travel": "Travel & controlled substances",
    "legal_civic": "Legal, civic & competency",
    "support_animal": "Emotional support animal",
}


TEMPLATES: dict[str, dict[str, Any]] = {
    # ---- Leave & FMLA certification ------------------------------------------------
    "fmla_who_certifies_health_provider": {
        "name": "FMLA WH-380-E (Health Care Provider Certification — Employee)",
        "audience": "Employer / DOL",
        "category": "leave_certification",
        "slots": [
            "patient_name", "patient_dob", "diagnosis", "icd10", "onset_date",
            "duration_estimate", "treatment_summary", "incapacity_episodic",
            "follow_up_frequency", "provider_name", "provider_credentials",
            "provider_signature_date",
        ],
        "required": [
            "patient_name", "diagnosis", "onset_date", "duration_estimate",
            "treatment_summary", "provider_name",
        ],
        "guidance": (
            "DOL form WH-380-E certifies an employee's own serious health condition. "
            "State the medical facts only; do not speculate about job functions. "
            "duration_estimate and follow_up_frequency must be concrete time spans. "
            "incapacity_episodic is yes/no plus frequency if the condition flares."
        ),
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
    "fmla_who_certifies_family_member": {
        "name": "FMLA WH-380-F (Health Care Provider Certification — Family Member)",
        "audience": "Employer / DOL",
        "category": "leave_certification",
        "slots": [
            "employee_name", "patient_name", "relationship", "patient_dob",
            "diagnosis", "icd10", "onset_date", "duration_estimate",
            "care_needed", "care_schedule", "provider_name",
            "provider_credentials", "provider_signature_date",
        ],
        "required": [
            "employee_name", "patient_name", "relationship", "diagnosis",
            "onset_date", "care_needed", "provider_name",
        ],
        "guidance": (
            "DOL form WH-380-F certifies that an EMPLOYEE needs leave to care for a "
            "FAMILY MEMBER (the patient). employee_name is the worker; patient_name "
            "is the relative being cared for. care_needed describes the hands-on or "
            "psychological care the employee must provide; care_schedule estimates "
            "frequency and duration. Do not conflate the two people."
        ),
        "body": (
            "FMLA Form WH-380-F - Care for a Family Member\n\n"
            "Employee requesting leave: {employee_name}\n"
            "Family member (patient): {patient_name}   DOB: {patient_dob}\n"
            "Relationship: {relationship}\n\n"
            "Approximate date condition began: {onset_date}\n"
            "Probable duration of condition: {duration_estimate}\n\n"
            "Diagnosis (ICD-10 {icd10}): {diagnosis}\n\n"
            "Care the employee is needed to provide:\n{care_needed}\n\n"
            "Estimated schedule of care: {care_schedule}\n\n"
            "Provider: {provider_name}, {provider_credentials}\n"
            "Signed: {provider_signature_date}\n"
        ),
    },
    "intermittent_leave_certification": {
        "name": "Intermittent / reduced-schedule leave certification",
        "audience": "Employer HR / leave administrator",
        "category": "leave_certification",
        "slots": [
            "patient_name", "patient_dob", "diagnosis_general", "flare_frequency",
            "episode_duration", "expected_period", "reduced_schedule_detail",
            "provider_name", "today",
        ],
        "required": [
            "patient_name", "diagnosis_general", "flare_frequency",
            "episode_duration", "expected_period", "provider_name",
        ],
        "guidance": (
            "Certifies a need for intermittent or reduced-schedule leave rather than "
            "a continuous block. flare_frequency and episode_duration must be "
            "quantitative estimates (e.g. '2-3 times per month, 1-2 days each'). "
            "Keep diagnosis_general non-specific unless the patient consents to detail."
        ),
        "body": (
            "{today}\n\n"
            "Re: Intermittent / Reduced-Schedule Leave Certification\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n\n"
            "{patient_name} is under my care for {diagnosis_general}. This condition "
            "causes episodic incapacity that warrants intermittent leave.\n\n"
            "Estimated flare frequency: {flare_frequency}\n"
            "Estimated duration per episode: {episode_duration}\n"
            "Expected period this certification covers: {expected_period}\n\n"
            "Reduced-schedule recommendation: {reduced_schedule_detail}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    # ---- School / work / camp absence notes ----------------------------------------
    "school_note": {
        "name": "School absence / return-to-school note",
        "audience": "School administration",
        "category": "absence_note",
        "slots": [
            "patient_name", "patient_dob", "absence_dates", "reason_lay",
            "return_date", "restrictions", "provider_name", "today",
        ],
        "required": ["patient_name", "absence_dates", "return_date", "provider_name"],
        "guidance": (
            "Brief excuse note for a school. Keep reason_lay non-diagnostic "
            "('a medical illness') unless the family asks for specifics. "
            "restrictions defaults to 'none' if the child returns at full activity."
        ),
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
        "category": "absence_note",
        "slots": [
            "patient_name", "absence_dates", "return_date", "restrictions",
            "provider_name", "today",
        ],
        "required": ["patient_name", "absence_dates", "return_date", "provider_name"],
        "guidance": (
            "Brief excuse note for an employer. Do not disclose a diagnosis — the "
            "employer is not entitled to it. restrictions defaults to 'none'."
        ),
        "body": (
            "{today}\n\n"
            "To Whom It May Concern:\n\n"
            "{patient_name} was under my care and is excused from work from {absence_dates}. "
            "The patient may return to work on {return_date}.\n\n"
            "Work restrictions: {restrictions}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "camp_note": {
        "name": "Camp participation / absence note",
        "audience": "Camp administration",
        "category": "absence_note",
        "slots": [
            "patient_name", "patient_dob", "camp_name", "absence_or_clearance",
            "activity_restrictions", "medication_notes", "return_date",
            "provider_name", "today",
        ],
        "required": ["patient_name", "absence_or_clearance", "provider_name"],
        "guidance": (
            "Covers either a camp absence or a clearance to attend. State activity "
            "restrictions plainly so a non-medical counselor can follow them. "
            "medication_notes lists any meds camp staff must administer or store."
        ),
        "body": (
            "{today}\n\n"
            "To the staff of {camp_name}:\n\n"
            "{patient_name} (DOB {patient_dob}) is under my care. {absence_or_clearance}\n\n"
            "Activity restrictions: {activity_restrictions}\n"
            "Medication notes: {medication_notes}\n"
            "Expected return / start date: {return_date}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "modified_duty_note": {
        "name": "Modified-duty / light-duty work note",
        "audience": "Employer / occupational health",
        "category": "absence_note",
        "slots": [
            "patient_name", "effective_dates", "lifting_limit", "standing_limit",
            "permitted_tasks", "restricted_tasks", "recheck_date",
            "provider_name", "today",
        ],
        "required": [
            "patient_name", "effective_dates", "restricted_tasks", "provider_name",
        ],
        "guidance": (
            "Specifies functional work restrictions, not a diagnosis. lifting_limit "
            "and standing_limit must be concrete (e.g. 'no lifting over 10 lb'). "
            "permitted_tasks and restricted_tasks describe job-function limits only."
        ),
        "body": (
            "{today}\n\n"
            "Re: Modified-Duty Work Restrictions\n"
            "Employee: {patient_name}\n"
            "Effective: {effective_dates}\n\n"
            "The following functional restrictions apply:\n"
            "- Lifting: {lifting_limit}\n"
            "- Standing / walking: {standing_limit}\n"
            "- Permitted tasks: {permitted_tasks}\n"
            "- Tasks to avoid: {restricted_tasks}\n\n"
            "Recommended recheck: {recheck_date}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    # ---- Sports clearance & return-to-activity -------------------------------------
    "sports_clearance_pre_participation": {
        "name": "Pre-Participation Physical Evaluation (PPE) clearance",
        "audience": "School athletics",
        "category": "activity_clearance",
        "slots": [
            "patient_name", "patient_dob", "exam_date", "cleared_status",
            "restrictions", "follow_up", "provider_name",
        ],
        "required": ["patient_name", "exam_date", "cleared_status", "provider_name"],
        "guidance": (
            "Standard PPE clearance. cleared_status must be one of: cleared without "
            "restriction; cleared with restriction; not cleared pending evaluation; "
            "not cleared. If anything other than full clearance, restrictions and "
            "follow_up must be specified."
        ),
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
    "return_to_activity": {
        "name": "Return-to-activity / return-to-play",
        "audience": "Athletic trainer / coach / employer",
        "category": "activity_clearance",
        "slots": [
            "patient_name", "injury", "stage", "permitted_activity",
            "restrictions", "next_recheck", "provider_name", "today",
        ],
        "required": ["patient_name", "injury", "stage", "permitted_activity", "provider_name"],
        "guidance": (
            "General graded return-to-activity note for an orthopedic or soft-tissue "
            "injury. stage names the current step in the progression; "
            "permitted_activity and restrictions must be unambiguous for a coach."
        ),
        "body": (
            "{today}\n\n"
            "Return-to-activity progression\n\n"
            "Patient: {patient_name}\nInjury: {injury}\nStage: {stage}\n\n"
            "Permitted activity: {permitted_activity}\nRestrictions: {restrictions}\nNext recheck: {next_recheck}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "return_to_play_concussion": {
        "name": "Return-to-play after concussion (graduated protocol)",
        "audience": "Athletic trainer / coach / school",
        "category": "activity_clearance",
        "slots": [
            "patient_name", "patient_dob", "injury_date", "current_step",
            "symptom_status", "next_step", "full_clearance_status",
            "academic_accommodations", "provider_name", "today",
        ],
        "required": [
            "patient_name", "injury_date", "current_step", "symptom_status",
            "provider_name",
        ],
        "guidance": (
            "Concussion-specific graduated return-to-play per current consensus "
            "(6-step progression). current_step names the present step; the athlete "
            "advances only if symptom-free for 24h. full_clearance_status states "
            "whether the athlete is cleared for full contact. Note any "
            "academic_accommodations (return-to-learn) still in effect."
        ),
        "body": (
            "{today}\n\n"
            "Return-to-Play — Concussion Protocol\n\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n"
            "Date of injury: {injury_date}\n\n"
            "Current graduated step: {current_step}\n"
            "Symptom status: {symptom_status}\n"
            "Next step (if symptom-free 24h): {next_step}\n\n"
            "Full-contact clearance: {full_clearance_status}\n"
            "Academic / return-to-learn accommodations: {academic_accommodations}\n\n"
            "The athlete must not advance steps while symptomatic and must stop "
            "activity if symptoms recur.\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    # ---- Medical necessity & payer appeals -----------------------------------------
    "letter_of_medical_necessity": {
        "name": "Letter of Medical Necessity (DME / off-label / specialty)",
        "audience": "Insurance company medical director",
        "category": "medical_necessity",
        "slots": [
            "patient_name", "patient_dob", "member_id", "diagnosis", "icd10",
            "requested_item_or_service", "cpt_or_hcpcs", "clinical_rationale",
            "alternatives_tried", "provider_name", "provider_credentials", "today",
        ],
        "required": [
            "patient_name", "diagnosis", "requested_item_or_service",
            "clinical_rationale", "provider_name",
        ],
        "guidance": (
            "Justifies medical necessity of a specific item or service. "
            "clinical_rationale must tie the request to the diagnosis and functional "
            "impact. alternatives_tried lists prior conservative or first-line "
            "options and why they failed. Do not overstate; payers verify."
        ),
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
        "category": "medical_necessity",
        "slots": [
            "patient_name", "patient_dob", "member_id", "claim_number",
            "denied_service", "denial_reason", "clinical_response", "guidelines_cited",
            "alternatives_tried", "provider_name", "today",
        ],
        "required": [
            "patient_name", "denied_service", "denial_reason",
            "clinical_response", "provider_name",
        ],
        "guidance": (
            "First-level internal appeal of a prior-authorization denial. "
            "clinical_response must directly rebut the stated denial_reason. "
            "guidelines_cited references payer policy or society guidelines that "
            "support the request."
        ),
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
        "category": "medical_necessity",
        "slots": [
            "patient_name", "patient_dob", "denied_service", "denial_basis",
            "clinical_summary", "outcome_request", "provider_name", "today",
        ],
        "required": [
            "patient_name", "denied_service", "denial_basis",
            "clinical_summary", "provider_name",
        ],
        "guidance": (
            "External / independent review request after internal appeals are "
            "exhausted. clinical_summary should be a complete, self-contained case "
            "narrative because the IRO reviewer has no prior context."
        ),
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
    # ---- Referrals & care coordination ---------------------------------------------
    "referral_letter": {
        "name": "Referral letter to specialist",
        "audience": "Receiving specialist",
        "category": "referral",
        "slots": [
            "patient_name", "patient_dob", "referring_provider", "specialty",
            "reason_for_referral", "relevant_history", "relevant_meds_allergies",
            "relevant_imaging_labs", "specific_question", "today",
        ],
        "required": [
            "patient_name", "referring_provider", "specialty",
            "reason_for_referral", "specific_question",
        ],
        "guidance": (
            "Standard outbound referral. specific_question states exactly what the "
            "referring provider wants answered. Include only history/meds/labs "
            "relevant to the referral question — not the whole chart."
        ),
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
    "urgent_referral_letter": {
        "name": "Urgent / expedited referral letter",
        "audience": "Receiving specialist or facility",
        "category": "referral",
        "slots": [
            "patient_name", "patient_dob", "referring_provider", "specialty",
            "urgency_reason", "red_flags", "requested_timeframe", "contact_info",
            "relevant_findings", "today",
        ],
        "required": [
            "patient_name", "referring_provider", "specialty",
            "urgency_reason", "requested_timeframe",
        ],
        "guidance": (
            "Expedited referral that flags clinical urgency up front. "
            "urgency_reason and red_flags justify the expedited timeframe. "
            "requested_timeframe must be concrete (e.g. 'within 48 hours'). "
            "Include direct contact_info so the specialist can reach the referrer."
        ),
        "body": (
            "{today}\n\n"
            "URGENT REFERRAL\n\n"
            "Dear {specialty} colleague,\n\n"
            "I am referring {patient_name} (DOB {patient_dob}) on an expedited basis.\n\n"
            "Reason for urgency: {urgency_reason}\n"
            "Red-flag findings: {red_flags}\n"
            "Relevant findings: {relevant_findings}\n\n"
            "Requested to be seen: {requested_timeframe}\n"
            "Please contact me directly: {contact_info}\n\n"
            "Sincerely,\n{referring_provider}\n"
        ),
    },
    # ---- Disability & accommodation ------------------------------------------------
    "disability_carrier_form": {
        "name": "Disability carrier attending-physician statement",
        "audience": "Short/long-term disability insurer",
        "category": "disability",
        "slots": [
            "patient_name", "patient_dob", "policy_or_claim_number", "diagnosis",
            "icd10", "date_of_disability", "objective_findings", "functional_limitations",
            "current_treatment", "prognosis", "estimated_return_date",
            "provider_name", "provider_credentials", "today",
        ],
        "required": [
            "patient_name", "diagnosis", "date_of_disability",
            "functional_limitations", "prognosis", "provider_name",
        ],
        "guidance": (
            "Attending-physician statement for a disability insurer. "
            "objective_findings should cite exam/imaging/lab evidence, not symptoms "
            "alone. functional_limitations must describe specific work-relevant "
            "limits. estimated_return_date may be 'undetermined' if genuinely unknown."
        ),
        "body": (
            "{today}\n\n"
            "Attending Physician Statement\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n"
            "Policy / Claim #: {policy_or_claim_number}\n\n"
            "Diagnosis (ICD-10 {icd10}): {diagnosis}\n"
            "Date patient became disabled: {date_of_disability}\n\n"
            "Objective findings:\n{objective_findings}\n\n"
            "Functional limitations:\n{functional_limitations}\n\n"
            "Current treatment: {current_treatment}\n"
            "Prognosis: {prognosis}\n"
            "Estimated return-to-work date: {estimated_return_date}\n\n"
            "Provider: {provider_name}, {provider_credentials}\n"
        ),
    },
    "disability_parking_placard": {
        "name": "Disability parking placard / plate certification",
        "audience": "Department of Motor Vehicles",
        "category": "disability",
        "slots": [
            "patient_name", "patient_dob", "qualifying_condition",
            "duration_type", "expiration_estimate", "provider_name",
            "provider_credentials", "license_number", "today",
        ],
        "required": [
            "patient_name", "qualifying_condition", "duration_type", "provider_name",
        ],
        "guidance": (
            "Certifies a mobility-limiting condition for a DMV disabled-parking "
            "placard. duration_type is 'permanent' or 'temporary'; if temporary, "
            "expiration_estimate gives an end date. State only the qualifying "
            "mobility limitation."
        ),
        "body": (
            "{today}\n\n"
            "Re: Disabled Parking Placard Certification\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n\n"
            "I certify that {patient_name} has a qualifying mobility-limiting "
            "condition: {qualifying_condition}.\n\n"
            "This disability is: {duration_type}\n"
            "If temporary, estimated expiration: {expiration_estimate}\n\n"
            "Provider: {provider_name}, {provider_credentials}\n"
            "License: {license_number}\n"
        ),
    },
    "accommodation_request_letter": {
        "name": "Reasonable accommodation support letter (ADA / Section 504)",
        "audience": "Employer HR / school disability services",
        "category": "disability",
        "slots": [
            "patient_name", "patient_dob", "setting", "functional_limitation",
            "recommended_accommodations", "duration_of_need", "provider_name",
            "provider_credentials", "today",
        ],
        "required": [
            "patient_name", "setting", "functional_limitation",
            "recommended_accommodations", "provider_name",
        ],
        "guidance": (
            "Supports a request for reasonable accommodations under the ADA or "
            "Section 504. Describe the functional_limitation and the "
            "recommended_accommodations; do not demand specific outcomes — the "
            "employer/school determines feasibility through the interactive process. "
            "setting is 'workplace' or 'school'."
        ),
        "body": (
            "{today}\n\n"
            "Re: Reasonable Accommodation Support — {patient_name}\n"
            "DOB: {patient_dob}\n\n"
            "{patient_name} is under my care and has a medical condition that "
            "produces the following functional limitation in the {setting} setting:\n"
            "{functional_limitation}\n\n"
            "To address this limitation, I recommend the following accommodations be "
            "considered through the interactive process:\n{recommended_accommodations}\n\n"
            "Anticipated duration of need: {duration_of_need}\n\n"
            "Sincerely,\n{provider_name}, {provider_credentials}\n"
        ),
    },
    # ---- Travel & controlled substances --------------------------------------------
    "controlled_substance_travel": {
        "name": "Controlled-substance travel letter",
        "audience": "Airport security / foreign customs",
        "category": "travel",
        "slots": [
            "patient_name", "patient_dob", "medications", "diagnosis_lay",
            "travel_dates", "provider_name", "dea_number", "today",
        ],
        "required": ["patient_name", "medications", "travel_dates", "provider_name"],
        "guidance": (
            "Confirms a patient legitimately carries controlled medications while "
            "traveling. List each medication with strength and quantity. "
            "diagnosis_lay stays general. Note meds are in original labeled bottles."
        ),
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
    "fitness_to_travel_letter": {
        "name": "Fitness-to-travel / fit-to-fly letter",
        "audience": "Airline / travel carrier",
        "category": "travel",
        "slots": [
            "patient_name", "patient_dob", "travel_dates", "destination",
            "clinical_status", "fitness_statement", "in_flight_needs",
            "provider_name", "today",
        ],
        "required": [
            "patient_name", "travel_dates", "fitness_statement", "provider_name",
        ],
        "guidance": (
            "States whether a patient is medically fit to fly or travel. "
            "fitness_statement is a clear yes/no with any conditions. "
            "in_flight_needs lists oxygen, medication storage, mobility aids, or "
            "'none'. Do not certify fitness beyond what the exam supports."
        ),
        "body": (
            "{today}\n\n"
            "Re: Fitness to Travel — {patient_name}\n"
            "DOB: {patient_dob}\n\n"
            "Travel dates: {travel_dates}   Destination: {destination}\n\n"
            "Current clinical status: {clinical_status}\n\n"
            "Fitness statement: {fitness_statement}\n\n"
            "In-flight / in-transit needs: {in_flight_needs}\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    # ---- Legal, civic & competency -------------------------------------------------
    "jury_duty_excuse": {
        "name": "Jury duty medical excuse",
        "audience": "Jury commissioner",
        "category": "legal_civic",
        "slots": [
            "patient_name", "patient_dob", "summons_date", "medical_reason_brief",
            "duration", "provider_name", "today",
        ],
        "required": ["patient_name", "summons_date", "medical_reason_brief", "provider_name"],
        "guidance": (
            "Requests excusal or deferral from jury service. medical_reason_brief "
            "stays high-level. duration states how long the patient cannot serve."
        ),
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
    "court_appearance_excuse": {
        "name": "Court appearance medical excuse / continuance request",
        "audience": "Court clerk / presiding judge",
        "category": "legal_civic",
        "slots": [
            "patient_name", "patient_dob", "case_or_hearing_reference",
            "scheduled_date", "medical_reason_brief", "unable_until",
            "provider_name", "today",
        ],
        "required": [
            "patient_name", "scheduled_date", "medical_reason_brief", "provider_name",
        ],
        "guidance": (
            "Supports a request to excuse a patient from a scheduled court "
            "appearance or to continue a hearing. Keep medical_reason_brief "
            "general. unable_until estimates when the patient can appear."
        ),
        "body": (
            "{today}\n\n"
            "To the Court:\n\n"
            "Re: {case_or_hearing_reference}\n\n"
            "{patient_name} (DOB {patient_dob}) is under my care and has a medical "
            "condition that prevents appearance at the proceeding scheduled for "
            "{scheduled_date}. Specifically: {medical_reason_brief}.\n\n"
            "The patient is anticipated to be unable to appear until: {unable_until}\n\n"
            "I respectfully request the Court excuse the appearance or grant a "
            "continuance.\n\n"
            "Sincerely,\n{provider_name}\n"
        ),
    },
    "competency_capacity_statement": {
        "name": "Decision-making capacity / competency statement",
        "audience": "Attorney / court / care facility",
        "category": "legal_civic",
        "slots": [
            "patient_name", "patient_dob", "evaluation_date", "capacity_question",
            "clinical_findings", "capacity_determination", "limitations_noted",
            "provider_name", "provider_credentials", "today",
        ],
        "required": [
            "patient_name", "evaluation_date", "capacity_question",
            "clinical_findings", "capacity_determination", "provider_name",
        ],
        "guidance": (
            "States a clinical opinion on decision-making CAPACITY for a specific "
            "question (medical, financial, etc.). Clarify that legal COMPETENCY is "
            "determined by a court; the clinician opines only on clinical capacity. "
            "capacity_question scopes the determination; clinical_findings cite the "
            "cognitive exam basis. Avoid global statements beyond what was assessed."
        ),
        "body": (
            "{today}\n\n"
            "Re: Decision-Making Capacity Statement\n"
            "Patient: {patient_name}   DOB: {patient_dob}\n"
            "Date of evaluation: {evaluation_date}\n\n"
            "Question addressed: {capacity_question}\n\n"
            "Clinical findings:\n{clinical_findings}\n\n"
            "Clinical determination of capacity: {capacity_determination}\n\n"
            "Noted limitations / qualifications: {limitations_noted}\n\n"
            "This statement reflects a clinical opinion on capacity at the time of "
            "evaluation. Legal competency is a determination for the court.\n\n"
            "Sincerely,\n{provider_name}, {provider_credentials}\n"
        ),
    },
    # ---- Emotional support animal --------------------------------------------------
    "esa_animal_letter": {
        "name": "Emotional Support Animal letter",
        "audience": "Housing provider",
        "category": "support_animal",
        "slots": [
            "patient_name", "diagnosis_general", "treatment_relationship",
            "esa_benefit_summary", "provider_name", "license_number", "today",
        ],
        "required": [
            "patient_name", "diagnosis_general", "treatment_relationship",
            "esa_benefit_summary", "provider_name", "license_number",
        ],
        "guidance": (
            "Supports a reasonable-accommodation request for an emotional support "
            "animal in housing. Must be written by the patient's own licensed "
            "treating mental-health provider. Keep diagnosis_general non-specific. "
            "Explicitly note this is NOT an ADA service-animal certification."
        ),
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
}


def list_templates() -> list[dict[str, Any]]:
    """Public registry view. Shape extended with category + required;
    existing keys (key, name, audience, slots) preserved for the router."""
    return [
        {
            "key": k,
            "name": v["name"],
            "audience": v["audience"],
            "category": v.get("category", "other"),
            "category_label": CATEGORIES.get(v.get("category", ""), "Other"),
            "slots": v["slots"],
            "required": v.get("required", v["slots"]),
            "guidance": v.get("guidance", ""),
        }
        for k, v in TEMPLATES.items()
    ]


def list_categories() -> list[dict[str, str]]:
    """Category vocabulary for UI grouping/filtering."""
    return [{"key": k, "label": label} for k, label in CATEGORIES.items()]


def render_text(template_key: str, slots: dict[str, str]) -> str:
    tpl = TEMPLATES.get(template_key)
    if not tpl:
        raise ValueError(f"unknown template '{template_key}'")
    body = tpl["body"]
    safe = {k: (slots.get(k) or "____") for k in tpl["slots"]}
    return body.format(**safe)


def gap_check(template_key: str, slots: dict[str, str]) -> dict[str, Any]:
    """Return which required slots are still unfilled. complete=True when none."""
    tpl = TEMPLATES.get(template_key)
    if not tpl:
        raise ValueError(f"unknown template '{template_key}'")
    required = tpl.get("required", tpl["slots"])
    missing = [s for s in required if not str(slots.get(s, "") or "").strip()]
    all_blank = [s for s in tpl["slots"] if not str(slots.get(s, "") or "").strip()]
    return {
        "complete": not missing,
        "missing_required": missing,
        "missing_optional": [s for s in all_blank if s not in missing],
    }


_AI_FILL_SYSTEM = """You fill medical-document slot variables from the supplied chart context. \
Be conservative — if a slot is genuinely not supported by the context, leave it blank (empty string).

Return JSON ONLY: a flat object mapping each requested slot name to its filled value (string).
No markdown, no preamble.

Tone: clinical, plain, never use markdown formatting in slot values, no extra commentary.
Honor the template's guidance: it tells you what each form is for and which facts are appropriate."""


def ai_fill_slots(
    template_key: str,
    chart_context: dict[str, Any],
) -> dict[str, str]:
    tpl = TEMPLATES.get(template_key)
    if not tpl or not claude.available():
        return {k: "" for k in (tpl or {}).get("slots", [])}
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    payload = {
        "template_key": template_key,
        "template_name": tpl["name"],
        "audience": tpl["audience"],
        "category": tpl.get("category", ""),
        "guidance": tpl.get("guidance", ""),
        "slots_required": tpl["slots"],
        "must_fill_if_possible": tpl.get("required", tpl["slots"]),
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


def generate_letter(
    template_key: str,
    chart_context: dict[str, Any] | None = None,
    slot_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One-shot: AI-fill slots from chart context, apply any clinician overrides,
    render text, and gap-check required slots.

    Returns a stable shape:
      {
        "template_key": str,
        "template_name": str,
        "category": str,
        "audience": str,
        "slots": {slot: value, ...},
        "rendered": str,                 # filled prose, blanks shown as ____
        "complete": bool,                # all required slots present
        "missing_required": [slot, ...],
        "missing_optional": [slot, ...],
        "error": str | None,             # only on unknown template / fill failure
      }
    """
    tpl = TEMPLATES.get(template_key)
    if not tpl:
        return {
            "template_key": template_key,
            "error": "unknown_template",
            "complete": False,
            "slots": {},
            "rendered": "",
            "missing_required": [],
            "missing_optional": [],
        }
    chart_context = chart_context or {}
    slots = ai_fill_slots(template_key, chart_context)
    if slot_overrides:
        for k, v in slot_overrides.items():
            if k in slots and v is not None:
                slots[k] = str(v)
    rendered = render_text(template_key, slots)
    gaps = gap_check(template_key, slots)
    return {
        "template_key": template_key,
        "template_name": tpl["name"],
        "category": tpl.get("category", "other"),
        "audience": tpl["audience"],
        "slots": slots,
        "rendered": rendered,
        "complete": gaps["complete"],
        "missing_required": gaps["missing_required"],
        "missing_optional": gaps["missing_optional"],
        "error": None,
    }


def generate_batch(
    requests: list[dict[str, Any]],
    chart_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate several letters in parallel for the same encounter.

    Each request item: {"template_key": str,
                         "chart_context": dict (optional, overrides shared),
                         "slot_overrides": dict (optional)}.
    A shared chart_context may be passed once and reused by every request.

    Returns a list aligned with the input order; each item is a
    generate_letter() result (errors are captured per item, never raised).
    """
    if not requests:
        return []
    shared = chart_context or {}

    def _one(req: dict[str, Any]) -> dict[str, Any]:
        key = req.get("template_key", "")
        try:
            ctx = {**shared, **(req.get("chart_context") or {})}
            return generate_letter(key, ctx, req.get("slot_overrides"))
        except Exception as e:  # defensive — keep batch resilient
            log.warning("generate_batch item failed (%s): %s", key, e)
            return {
                "template_key": key,
                "error": "generation_failed",
                "complete": False,
                "slots": {},
                "rendered": "",
                "missing_required": [],
                "missing_optional": [],
            }

    workers = min(_MAX_BATCH_WORKERS, len(requests))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one, requests))


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
