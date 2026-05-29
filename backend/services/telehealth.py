"""Telehealth launch helpers — Zoom, Microsoft Teams, Doxy.me, Doximity Dialer.

Generates one-click jump links the clinician can email/SMS to the patient.
Each provider exposes a different URL shape; this module abstracts that. The
ambient scribe pipeline runs alongside the call (browser MediaRecorder OR
SDK plugin in Wave 3 for real Zoom/Teams app integration).

Meeting metadata is persisted onto the encounter so the scribe knows which
session the audio came from.

This module exposes two layers:

  * The original link-builder functions (``doxy_room`` ... ``make_session``)
    that ``routers/wave4.py`` already calls. Their signatures are unchanged.
  * A ``TelehealthEncounter`` model + ``open_encounter()`` factory + a
    ``capture_to_scribe()`` hook so the ambient scribe can record a
    telehealth visit. The real Zoom/Teams/Doximity audio integration is an
    injectable ``processor`` seam — production wires the SDK callback, tests
    pass a mock.
"""
from __future__ import annotations

import logging
import secrets
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Provider link builders (unchanged public surface — wave4.py depends on these)
# ---------------------------------------------------------------------------


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


# Provider key -> link builder. Aliases collapsed so callers can pass either form.
_PROVIDERS: dict[str, Callable[..., dict[str, Any]]] = {
    "doxy": doxy_room,
    "doxy.me": doxy_room,
    "zoom": zoom_personal_meeting,
    "teams": teams_link,
    "doximity": doximity_dialer_invite,
    "doximity-dialer": doximity_dialer_invite,
}


def make_session(*, provider: str, **kwargs) -> dict[str, Any]:
    """Build a one-off provider join link.

    Backward-compatible: ``routers/wave4.py`` calls this with ``provider`` plus
    the provider-specific kwargs and expects the same dict shape as before
    (link fields + ``session_id`` / ``created_at`` / ``scribe_attach_recommended``).
    Unknown providers still return ``{"error": ...}`` rather than raising.
    """
    p = (provider or "").lower().strip()
    builder = _PROVIDERS.get(p)
    if builder is None:
        return {"error": f"unknown provider '{provider}'"}
    s = builder(**kwargs)
    s["session_id"] = secrets.token_urlsafe(8)
    s["created_at"] = _now()
    s["scribe_attach_recommended"] = True
    return s


# ---------------------------------------------------------------------------
# Telehealth encounter model + ambient-scribe capture seam
# ---------------------------------------------------------------------------


class ScribeProcessor(Protocol):
    """Injectable seam for the ambient scribe.

    Production wires this to ``services.ambient_scribe`` (the HealthScribe /
    transcript-synthesis pipeline). Tests pass a mock so the telehealth
    capture path can be exercised without an AWS BAA or a Claude call.

    A processor receives the raw conversation transcript captured from the
    telehealth call (browser MediaRecorder export, Zoom cloud-recording
    transcript, Teams Graph transcript, or Doximity call audio that was run
    through Whisper) and returns a structured note dict.
    """

    def __call__(self, transcript: str, *, specialty: str | None = None) -> dict[str, Any]:
        ...


def _default_processor(transcript: str, *, specialty: str | None = None) -> dict[str, Any]:
    """Fallback processor — used when no scribe processor is injected.

    Imported lazily so this module stays importable even if the ambient
    scribe's heavier dependencies are unavailable, and so there is no
    top-level import cycle through the AI layer.
    """
    try:
        from services import ambient_scribe  # noqa: PLC0415

        return ambient_scribe.synthesize_from_transcript(transcript, specialty=specialty)
    except Exception as exc:  # noqa: BLE001 — scribe is decision-support, never a blocker
        log.warning("telehealth: default scribe processor unavailable: %s", exc)
        return {
            "status": "scribe_unavailable",
            "transcript_chars": len(transcript or ""),
            "sections": {},
        }


# Telehealth providers whose audio can be ambiently recorded for the scribe.
_SCRIBE_CAPABLE = {"zoom", "teams", "doxy.me", "doximity-dialer"}


@dataclass
class TelehealthEncounter:
    """A single telehealth visit.

    Wraps the provider join link with the metadata the ambient scribe needs
    to attribute captured audio to the right session. Persist this onto the
    patient/appointment row (via ``db.storage`` from the router layer) so a
    later poll can find the encounter.
    """

    encounter_id: str
    hospital_id: str
    provider: str
    join_url: str
    session: dict[str, Any]
    clinician_id: str | None = None
    patient_id: str | None = None
    specialty: str | None = None
    status: str = "open"  # open | capturing | scribed | closed | error
    created_at: str = field(default_factory=_now)
    scribe_note: dict[str, Any] | None = None
    capture_started_at: str | None = None
    captured_at: str | None = None

    @property
    def scribe_capable(self) -> bool:
        """True when this provider's audio can feed the ambient scribe."""
        return self.provider in _SCRIBE_CAPABLE

    def to_dict(self) -> dict[str, Any]:
        """Storage / API-safe view. The join URL is a capability token — only
        the clinician and the patient who receive it should ever see it, so
        callers returning this to a wider audience should drop ``join_url``."""
        return {
            "encounter_id": self.encounter_id,
            "hospital_id": self.hospital_id,
            "provider": self.provider,
            "join_url": self.join_url,
            "clinician_id": self.clinician_id,
            "patient_id": self.patient_id,
            "specialty": self.specialty,
            "status": self.status,
            "scribe_capable": self.scribe_capable,
            "created_at": self.created_at,
            "capture_started_at": self.capture_started_at,
            "captured_at": self.captured_at,
            "session_id": self.session.get("session_id"),
            "scribe_note": self.scribe_note,
        }

    def capture_to_scribe(
        self,
        transcript: str,
        *,
        processor: ScribeProcessor | None = None,
    ) -> dict[str, Any]:
        """Hand the telehealth conversation transcript to the ambient scribe.

        ``processor`` is the integration seam: production injects the real
        ambient-scribe pipeline (or an SDK callback wrapper for live Zoom /
        Teams / Doximity audio); tests inject a mock. When omitted, the
        default processor calls ``services.ambient_scribe``.

        The scribe output is a decision-support draft, not the patient chart.
        Never raises — a scribe failure marks the encounter ``error`` and the
        visit still stands.
        """
        self.status = "capturing"
        self.capture_started_at = _now()
        run = processor or _default_processor
        try:
            note = run(transcript or "", specialty=self.specialty)
        except Exception as exc:  # noqa: BLE001 — scribe must never break the visit
            log.warning("telehealth: scribe capture failed for %s: %s", self.encounter_id, exc)
            self.status = "error"
            self.scribe_note = {"status": "scribe_failed", "error": str(exc)[:200]}
            return self.scribe_note
        self.scribe_note = note
        self.captured_at = _now()
        self.status = "scribed"
        return note

    def close(self) -> None:
        """Mark the encounter finished. Idempotent."""
        if self.status != "error":
            self.status = "closed"


def open_encounter(
    *,
    provider: str,
    hospital_id: str,
    clinician_id: str | None = None,
    patient_id: str | None = None,
    specialty: str | None = None,
    **provider_kwargs: Any,
) -> TelehealthEncounter:
    """Factory — build a provider join link and wrap it in a TelehealthEncounter.

    Raises ``ValueError`` on an unknown provider (callers in the router layer
    should translate that into an HTTPException(400)). The link itself is
    produced by the same ``make_session`` path ``wave4.py`` uses, so the URL
    shape is identical.
    """
    session = make_session(provider=provider, **provider_kwargs)
    if "error" in session:
        raise ValueError(session["error"])
    return TelehealthEncounter(
        encounter_id=secrets.token_urlsafe(12),
        hospital_id=hospital_id,
        provider=session.get("provider", (provider or "").lower().strip()),
        join_url=session.get("url", ""),
        session=session,
        clinician_id=clinician_id,
        patient_id=patient_id,
        specialty=specialty,
    )
