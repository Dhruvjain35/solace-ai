"""Available workflow triggers.

Each trigger is a string event name that route handlers `fire()` with a
context dict. The frontend reads this registry to populate the trigger
dropdown so admins only see real options.

PHI safety: every `sample_context` here is deliberately PHI-free. It uses
opaque ids, hashes, ESI levels, languages and counts only — never names,
phones, emails, DOB, addresses or transcripts. The live engine additionally
runs `phi.sanitize_context()` on the real event context before dispatch, so a
trigger payload can never carry a Safe Harbor identifier into an action.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriggerDef:
    name: str               # canonical event id, e.g. "patient.checked_in"
    label: str              # human display
    description: str        # tooltip / explainer
    sample_context: dict    # so admins know which {{vars}} are available


# Order = display order on the form.
TRIGGERS: list[TriggerDef] = [
    TriggerDef(
        name="patient.checked_in",
        label="Patient checks in",
        description="Fires after a patient submits the intake form (provisional ESI assigned).",
        sample_context={
            "patient": {"id": "abc", "esi_level": 3, "language": "en"},
            "hospital": {"id": "demo", "name": "St. David's Medical Center"},
        },
    ),
    TriggerDef(
        name="patient.discharged",
        label="Patient marked seen / discharged",
        description="Fires when a clinician taps Mark Seen on the dashboard.",
        sample_context={
            "patient": {"id": "abc", "esi_level": 3, "seen_by": "Dr. Chen"},
            "hospital": {"id": "demo", "name": "St. David's Medical Center"},
        },
    ),
    TriggerDef(
        name="pain.flagged",
        label="Patient escalates pain",
        description="Fires the moment a patient taps 'My pain got worse'. Use for paging staff.",
        sample_context={
            "patient": {"id": "abc", "esi_level": 3, "waited_minutes": 32},
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="appointment.booked",
        label="Appointment booked",
        description="Fires when a patient self-schedules a new appointment.",
        sample_context={
            "appointment": {
                "id": "appt-9f2", "confirmation_code": "AB2X7K",
                "slot_iso": "2026-05-04T14:30:00Z", "reason_short": "follow-up",
                "patient_id": "abc", "patient_phone_hash": "0177:a1b2c3d4e5f67890",
            },
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="esi.refined",
        label="Bedside ESI refined",
        description="Fires after vitals are entered and the ML ensemble updates the ESI.",
        sample_context={
            "patient": {"id": "abc", "previous_esi_level": 3, "esi_level": 2},
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="encounter.event",
        label="Encounter event (EHR)",
        description=(
            "Fires on an EHR encounter lifecycle event — admit, transfer, "
            "discharge or status change synced from the connected EHR."
        ),
        sample_context={
            "encounter": {
                "id": "enc-7c41", "event": "admit", "status": "in-progress",
                "department": "Emergency", "class": "EMER",
            },
            "patient": {"id": "abc", "esi_level": 3},
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="result.abnormal",
        label="Abnormal result posted",
        description=(
            "Fires when a lab or imaging result lands flagged abnormal or "
            "critical. Use to draft a patient message or open a follow-up task."
        ),
        sample_context={
            "result": {
                "id": "res-3a8e", "kind": "lab", "test_code": "POT",
                "test_name": "Potassium", "flag": "critical-high",
                "value_numeric": 6.4, "unit": "mmol/L", "reference_high": 5.2,
            },
            "patient": {"id": "abc", "esi_level": 3},
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="care_gap.detected",
        label="Care gap detected",
        description=(
            "Fires when a quality-measure scan finds an open care gap "
            "(overdue screening, missing immunization, uncontrolled metric)."
        ),
        sample_context={
            "care_gap": {
                "id": "gap-5d12", "measure": "HEDIS-CBP", "category": "screening",
                "description": "blood-pressure control follow-up overdue",
                "due_days_overdue": 21, "priority": "medium",
            },
            "patient": {"id": "abc"},
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="no_show.risk",
        label="No-show risk predicted",
        description=(
            "Fires when the no-show model scores an upcoming appointment as "
            "high risk. Use to send a reminder or open an outreach task."
        ),
        sample_context={
            "no_show": {
                "appointment_id": "appt-9f2", "risk_score": 0.82,
                "risk_band": "high", "slot_iso": "2026-05-20T09:00:00Z",
            },
            "patient": {"id": "abc"},
            "hospital": {"id": "demo"},
        },
    ),
]


def by_name(name: str) -> TriggerDef | None:
    return next((t for t in TRIGGERS if t.name == name), None)


def to_public_list() -> list[dict]:
    return [
        {
            "name": t.name,
            "label": t.label,
            "description": t.description,
            "sample_context": t.sample_context,
        }
        for t in TRIGGERS
    ]
