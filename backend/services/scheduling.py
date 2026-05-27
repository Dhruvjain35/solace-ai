"""Appointment slot availability + booking helpers.

For the demo there's no separate provider-availability table — we generate
slots deterministically from the hospital's business hours (8a-5p Mon-Fri,
30-minute slots) and subtract anything already in `solace-appointments`.

To go production:
  - Add a `solace-providers` table with per-provider hours + visit-type
    durations
  - Replace `_generate_open_slots` with a query that joins providers + holds
  - Plug in real EHR scheduling write-back via FHIR Appointment resource
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from db import storage

log = logging.getLogger(__name__)


SLOT_MINUTES = 30
DAY_START_HOUR = 8       # 8 AM local (UTC for demo simplicity)
DAY_END_HOUR = 17        # 5 PM
LOOKAHEAD_DAYS = 7
WORKDAYS = {0, 1, 2, 3, 4}  # Mon-Fri


@dataclass(frozen=True)
class Slot:
    iso: str          # "2026-05-04T14:30:00Z"
    label: str        # "Mon May 5 · 2:30 PM"
    duration_min: int


def open_slots(*, hospital_id: str, days: int = LOOKAHEAD_DAYS) -> list[Slot]:
    booked_iso = _booked_isos(hospital_id)
    out: list[Slot] = []
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for day_offset in range(days):
        day = (now + timedelta(days=day_offset)).date()
        if day.weekday() not in WORKDAYS:
            continue
        for hour in range(DAY_START_HOUR, DAY_END_HOUR):
            for minute in (0, SLOT_MINUTES):
                slot_dt = datetime(
                    day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc
                )
                if slot_dt < now + timedelta(minutes=15):
                    continue  # don't surface already-past slots
                iso = slot_dt.isoformat().replace("+00:00", "Z")
                if iso in booked_iso:
                    continue
                out.append(Slot(
                    iso=iso,
                    label=slot_dt.strftime("%a %b %-d · %-I:%M %p UTC"),
                    duration_min=SLOT_MINUTES,
                ))
    return out


def book(*, hospital_id: str, slot_iso: str,
         patient_name: str, patient_phone: str,
         reason: str, channel: str = "web") -> dict:
    """Reserve a slot. Returns the appointment dict + confirmation code.
    Caller checks that slot_iso is in `open_slots()` before calling.
    Phone is hashed before storage — HIPAA §164.514 (Safe Harbor identifier)."""
    from services.voice_agent.session import hash_phone  # noqa: PLC0415

    appt = {
        "appointment_id": secrets.token_urlsafe(12),
        "hospital_id": hospital_id,
        "slot_iso": slot_iso,
        "patient_name": patient_name.strip(),
        "patient_phone_hash": hash_phone(patient_phone.strip()),  # hashed, not raw
        "reason_short": reason.strip()[:200],
        "preferred_window": "",
        "status": "booked",
        "confirmation_code": _gen_code(),
        "created_via": channel,  # "web" | "voice"
    }
    storage.add_appointment(appt)
    return appt


def lookup(*, hospital_id: str, confirmation_code: str) -> dict | None:
    rows = storage.list_appointments(hospital_id=hospital_id)
    code = confirmation_code.strip().upper()
    for r in rows:
        if (r.get("confirmation_code") or "").upper() == code:
            return r
    return None


# --- internals -----------------------------------------------------------------


def _booked_isos(hospital_id: str) -> set[str]:
    rows = storage.list_appointments(hospital_id=hospital_id)
    return {
        str(r.get("slot_iso", ""))
        for r in rows
        if r.get("status") == "booked" and r.get("slot_iso")
    }


def _gen_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
    return "".join(secrets.choice(alphabet) for _ in range(6))


# --- risk-tiered reminders ------------------------------------------------------
#
# Reminder cadence is *tiered* by no-show risk so outreach effort tracks the
# patients most likely to miss. The tier comes from `services.no_show.predict`;
# this function turns a tier into a concrete, send-able channel plan.
#
#   low    — 1 SMS the day before. Cheapest touch; baseline-risk patients.
#   medium — 2-3 SMS, escalating in frequency as the slot nears.
#   high   — SMS + an outbound voice call + earlier first-touch, because a
#            single channel demonstrably under-reaches the highest-risk cohort.


# Per-tier reminder template: each entry is (offset_hours_before_appt, channel).
_REMINDER_TIERS: dict[str, list[tuple[int, str]]] = {
    "low": [
        (24, "sms"),
    ],
    "medium": [
        (72, "sms"),
        (24, "sms"),
        (4, "sms"),
    ],
    "high": [
        # Earlier first outreach — 7 days out — plus a voice escalation.
        (168, "sms"),
        (72, "sms"),
        (24, "voice"),
        (4, "voice"),
    ],
}


def reminder_plan(
    *,
    tier: str,
    appointment_iso: str | None = None,
    no_show_probability: float | None = None,
) -> dict:
    """Build a concrete reminder plan for an appointment from its risk tier.

    `tier` is "low" | "medium" | "high" (from `no_show.predict()["tier"]`).
    An unrecognized tier falls back to "medium" so a plan is always produced.

    When `appointment_iso` is given, each reminder gets a concrete `send_iso`
    scheduled `offset_hours` before the appointment. Past-due offsets are kept
    but marked `due=True` so the caller can fire them immediately or skip.

    Returns a dict with the tier, a flat ordered `reminders` list, and a short
    human-readable `summary` for clinician-facing UI.
    """
    norm = (tier or "").strip().lower()
    if norm not in _REMINDER_TIERS:
        log.warning("reminder_plan: unknown tier %r — defaulting to 'medium'", tier)
        norm = "medium"

    template = _REMINDER_TIERS[norm]

    appt_dt: datetime | None = None
    if appointment_iso:
        try:
            appt_dt = datetime.fromisoformat(appointment_iso.replace("Z", "+00:00"))
            if appt_dt.tzinfo is None:
                appt_dt = appt_dt.replace(tzinfo=timezone.utc)
        except Exception:
            log.warning("reminder_plan: unparseable appointment_iso=%r", appointment_iso)

    now = datetime.now(timezone.utc)
    reminders: list[dict] = []
    for offset_hours, channel in template:
        entry: dict = {
            "offset_hours": offset_hours,
            "channel": channel,
            "send_iso": None,
            "due": False,
        }
        if appt_dt is not None:
            send_dt = appt_dt - timedelta(hours=offset_hours)
            entry["send_iso"] = send_dt.isoformat().replace("+00:00", "Z")
            entry["due"] = send_dt <= now
        reminders.append(entry)

    channels = sorted({r["channel"] for r in reminders})
    summary = (
        f"{norm} risk: {len(reminders)} reminder(s) via {', '.join(channels)}"
    )

    return {
        "tier": norm,
        "no_show_probability": no_show_probability,
        "reminders": reminders,
        "channels": channels,
        "summary": summary,
    }
