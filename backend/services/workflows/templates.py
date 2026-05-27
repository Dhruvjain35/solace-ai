"""Pre-built workflow templates.

Hospital admins click "Use this template" → instantiate gives them a working
workflow prefilled with sane defaults. Variables they need to provide
(webhook URLs, phone numbers) are clearly empty so the editor's form
validation forces them to fill those before enabling.
"""
from __future__ import annotations


TEMPLATES: list[dict] = [
    {
        "id": "discharge_sms",
        "label": "Text discharge plan when patient marked seen",
        "description": "Sends the patient an SMS recap of their care plan the moment a clinician taps Mark Seen.",
        "trigger": "patient.discharged",
        "filters": {},
        "steps": [
            {
                "type": "send_sms",
                "config": {
                    "to": "{{patient.phone}}",
                    "body": (
                        "Hi {{patient.name}}, here's your care plan from {{hospital.name}}: "
                        "Rest, hydrate, take meds as prescribed. Come back if symptoms get worse. "
                        "Reply CARE for the full instructions."
                    ),
                },
            }
        ],
    },
    {
        "id": "high_acuity_slack_ping",
        "label": "Slack the on-call when ESI 1-2 arrives",
        "description": "Posts to a Slack channel whenever a high-acuity patient checks in — keeps the attending in the loop.",
        "trigger": "patient.checked_in",
        "filters": {"patient.esi_level_lte": 2},
        "steps": [
            {
                "type": "send_slack_webhook",
                "config": {
                    "webhook_url": "",
                    "text": (
                        ":rotating_light: ESI {{patient.esi_level}} arrival: {{patient.name}} "
                        "({{patient.language}}). Pre-brief in the dashboard."
                    ),
                },
            }
        ],
    },
    {
        "id": "pain_alarm_slack",
        "label": "Slack the team when a patient escalates pain",
        "description": "Real-time alert when a waiting patient taps the pain button. Pairs with the dashboard alarm.",
        "trigger": "pain.flagged",
        "filters": {},
        "steps": [
            {
                "type": "send_slack_webhook",
                "config": {
                    "webhook_url": "",
                    "text": (
                        ":bell: Pain alarm: {{patient.name}} (ESI {{patient.esi_level}}) — "
                        "{{patient.waited_minutes}}m wait. Acknowledge on the dashboard."
                    ),
                },
            }
        ],
    },
    {
        "id": "appt_reminder_24h",
        "label": "Notify Slack when appointment is booked",
        "description": (
            "Posts a Slack message when a patient books a slot online. "
            "Note: appointment confirmation SMS is sent directly by the booking endpoint — "
            "the workflow context does not include the raw phone number (it is hashed per "
            "HIPAA §164.514 before storage). Use a Slack or webhook step here instead."
        ),
        "trigger": "appointment.booked",
        "filters": {},
        "steps": [
            {
                "type": "slack_message",
                "config": {
                    "channel": "#appointments",
                    "message": (
                        "New appointment: {{appointment.patient_name}} — "
                        "{{appointment.slot_iso}} — {{appointment.reason_short}}. "
                        "Confirmation: {{appointment.confirmation_code}}."
                    ),
                },
            }
        ],
    },
    {
        "id": "esi_uptick_audit",
        "label": "Audit-log every ESI uptick after vitals",
        "description": "Compliance-grade log entry whenever the bedside ML model upgrades a patient's ESI. Useful for retrospective triage-quality review.",
        "trigger": "esi.refined",
        "filters": {},
        "steps": [
            {
                "type": "audit_log",
                "config": {"action": "workflow.esi_refinement"},
            }
        ],
    },
    {
        "id": "abnormal_result_followup",
        "label": "Draft a patient message + open a task on abnormal results",
        "description": (
            "When a lab or imaging result is flagged abnormal, Claude drafts a "
            "plain-language patient message for clinician review and a follow-up "
            "task is opened on the chart. Nothing is sent automatically."
        ),
        "trigger": "result.abnormal",
        "filters": {},
        "steps": [
            {
                "id": "draft",
                "type": "draft_message",
                "config": {
                    "purpose": (
                        "a {{result.test_name}} result came back {{result.flag}}; "
                        "ask the patient to contact the clinic to discuss next steps"
                    ),
                    "tone": "warm, reassuring, plain-language",
                    "output_key": "abnormal_result_draft",
                },
            },
            {
                "type": "create_task",
                "config": {
                    "title": "Review abnormal {{result.test_name}} ({{result.flag}}) and approve patient message",
                    "priority": "high",
                    "assignee": "Ordering clinician",
                    "due_in_days": 1,
                },
            },
        ],
    },
    {
        "id": "critical_result_escalation",
        "label": "Escalate critical results to the on-call (branching)",
        "description": (
            "On an abnormal result, notify staff. If the result is critical, the "
            "chain branches to also queue an EHR flag. Demonstrates the per-step "
            "`if` condition and `goto` branching."
        ),
        "trigger": "result.abnormal",
        "filters": {},
        "steps": [
            {
                "id": "notify",
                "type": "notify",
                "config": {
                    "message": "Abnormal {{result.test_name}} for patient {{patient.id}} ({{result.flag}}).",
                    "channel": "charge_nurse",
                },
            },
            {
                "id": "flag",
                "type": "ehr_write",
                "if": {"result.flag": "critical-high"},
                "config": {
                    "resource": "flag",
                    "value": "Critical {{result.test_name}} = {{result.value_numeric}} {{result.unit}} — clinician review required.",
                },
            },
        ],
    },
    {
        "id": "encounter_admit_notify",
        "label": "Notify the team on EHR admit events",
        "description": "Posts an internal notification whenever an encounter is admitted in the connected EHR.",
        "trigger": "encounter.event",
        "filters": {"encounter.event": "admit"},
        "steps": [
            {
                "type": "notify",
                "config": {
                    "message": "Encounter {{encounter.id}} admitted to {{encounter.department}} (patient {{patient.id}}).",
                    "channel": "dashboard",
                },
            }
        ],
    },
    {
        "id": "care_gap_letter",
        "label": "Draft an outreach letter when a care gap is detected",
        "description": (
            "When the quality scan finds an open care gap, Claude drafts an "
            "outreach letter for clinician review and opens a task to send it."
        ),
        "trigger": "care_gap.detected",
        "filters": {},
        "steps": [
            {
                "type": "generate_letter",
                "config": {
                    "letter_type": "care_gap_outreach",
                    "instructions": (
                        "Invite the patient to schedule care for an open care gap: "
                        "{{care_gap.description}} ({{care_gap.measure}})."
                    ),
                    "output_key": "care_gap_letter_draft",
                },
            },
            {
                "type": "create_task",
                "config": {
                    "title": "Review and send care-gap letter ({{care_gap.measure}})",
                    "priority": "normal",
                    "assignee": "Care team",
                    "due_in_days": 7,
                },
            },
        ],
    },
    {
        "id": "no_show_reminder",
        "label": "Open an outreach task for high no-show-risk appointments",
        "description": (
            "When the no-show model scores an upcoming appointment as high risk, "
            "opens a reminder-outreach task for the front desk."
        ),
        "trigger": "no_show.risk",
        "filters": {"no_show.risk_band": "high"},
        "steps": [
            {
                "type": "create_task",
                "config": {
                    "title": "Call patient to confirm appointment {{no_show.appointment_id}} (no-show risk {{no_show.risk_score}})",
                    "priority": "normal",
                    "assignee": "Front desk",
                    "due_in_days": 1,
                },
            }
        ],
    },
]


def by_id(template_id: str) -> dict | None:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)
