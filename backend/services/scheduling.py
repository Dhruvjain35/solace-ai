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

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from db import storage


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
