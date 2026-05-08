"""Telehealth launch helpers — Zoom, Microsoft Teams, Doxy.me, Doximity Dialer.

Generates one-click jump links the clinician can email/SMS to the patient.
Each provider exposes a different URL shape; this module abstracts that. The
ambient scribe pipeline runs alongside the call (browser MediaRecorder OR
SDK plugin in Wave 3 for real Zoom/Teams app integration).

Meeting metadata is persisted onto the encounter so the scribe knows which
session the audio came from.
"""
from __future__ import annotations

import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def doxy_room(*, clinician_handle: str, patient_name: str = "") -> dict[str, Any]:
    """Doxy.me — clinician sets up a permanent room, patient just joins. The link is the room slug."""
    handle = (clinician_handle or "").strip().lower().replace(" ", "")
    url = f"https://doxy.me/{handle}"
    return {"provider": "doxy.me", "url": url, "patient_message": f"Click to join your visit with Dr. {clinician_handle.split()[-1] if clinician_handle else ''}: {url}"}


def zoom_personal_meeting(*, pmi: str, passcode: str | None = None) -> dict[str, Any]:
    """Zoom — clinician's PMI link. In production replace with Zoom Health API to spin up healthcare-tier rooms."""
    base = f"https://zoom.us/j/{pmi}"
    if passcode:
        base += f"?pwd={urllib.parse.quote(passcode)}"
    return {"provider": "zoom", "url": base, "passcode": passcode}


def teams_link(*, organizer_email: str, subject: str = "Solace visit") -> dict[str, Any]:
    """Teams — meeting deeplink. Production uses Microsoft Graph to schedule with the patient's email."""
    payload = urllib.parse.urlencode({"subject": subject, "attendees": "", "organizer": organizer_email})
    return {"provider": "teams", "url": f"https://teams.microsoft.com/l/meeting/new?{payload}"}


def doximity_dialer_invite(*, clinician_phone: str, patient_phone: str) -> dict[str, Any]:
    """Doximity Dialer — generates a HIPAA-compliant call link. Stub for real Doximity integration."""
    token = secrets.token_urlsafe(8)
    return {"provider": "doximity-dialer", "url": f"https://dialer.doximity.com/c/{token}", "from": clinician_phone, "to": patient_phone}


def make_session(*, provider: str, **kwargs) -> dict[str, Any]:
    p = (provider or "").lower()
    if p == "doxy" or p == "doxy.me":
        s = doxy_room(**kwargs)
    elif p == "zoom":
        s = zoom_personal_meeting(**kwargs)
    elif p == "teams":
        s = teams_link(**kwargs)
    elif p == "doximity":
        s = doximity_dialer_invite(**kwargs)
    else:
        return {"error": f"unknown provider '{provider}'"}
    s["session_id"] = secrets.token_urlsafe(8)
    s["created_at"] = _now()
    s["scribe_attach_recommended"] = True
    return s
