"""Available workflow triggers.

Each trigger is a string event name that route handlers `fire()` with a
context dict. The frontend reads this registry to populate the trigger
dropdown so admins only see real options.
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
            "patient": {"id": "abc", "name": "Marcus Johnson", "phone": "+15125550177",
                        "esi_level": 3, "language": "en"},
            "hospital": {"id": "demo", "name": "St. David's Medical Center"},
        },
    ),
    TriggerDef(
        name="patient.discharged",
        label="Patient marked seen / discharged",
        description="Fires when a clinician taps Mark Seen on the dashboard.",
        sample_context={
            "patient": {"id": "abc", "name": "Marcus Johnson", "phone": "+15125550177",
                        "esi_level": 3, "seen_by": "Dr. Chen"},
            "hospital": {"id": "demo", "name": "St. David's Medical Center"},
        },
    ),
    TriggerDef(
        name="pain.flagged",
        label="Patient escalates pain",
        description="Fires the moment a patient taps 'My pain got worse'. Use for paging staff.",
        sample_context={
            "patient": {"id": "abc", "name": "Priya Patel", "esi_level": 3,
                        "waited_minutes": 32},
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="appointment.booked",
        label="Appointment booked",
        description="Fires when a patient self-schedules a new appointment.",
        sample_context={
            "appointment": {"confirmation_code": "AB2X7K", "slot_iso": "2026-05-04T14:30:00Z",
                            "patient_name": "Marcus Johnson", "patient_phone": "+15125550177"},
            "hospital": {"id": "demo"},
        },
    ),
    TriggerDef(
        name="esi.refined",
        label="Bedside ESI refined",
        description="Fires after vitals are entered and the ML ensemble updates the ESI.",
        sample_context={
            "patient": {"id": "abc", "name": "Marcus Johnson",
                        "previous_esi_level": 3, "esi_level": 2},
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
