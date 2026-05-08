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
]


def by_id(template_id: str) -> dict | None:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)
