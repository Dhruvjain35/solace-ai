"""The one consent gate for patient-facing AI calls (CONSTITUTION SEC-004).

SEC-004 requires that no AI provider sees patient data before consent is
recorded. Until now the check was copy-pasted inline in three routers and absent
from everything written afterwards, which is what a rule enforced by convention
always converges to. ``tests/services/test_consent_gate.py`` now derives the set
of routes that need a gate from the import graph and fails if one is missing, so
the next person to add a patient-facing AI route gets told rather than trusted.

**Two legal bases, deliberately kept apart.**

Patient-facing capture (intake, phone, uploads, ID scans) needs the patient's
own authorization under HIPAA §164.508. ``require()`` enforces that.

Clinician-facing tools acting on a chart the clinician is already treating from
run under treatment and operations, not under a fresh authorization. Those are
recognised by their auth dependency and are not gated here. Forcing them through
a patient-authorization check would describe the wrong thing, and a gate that
describes the wrong thing is one people learn to route around.

**Direct and indirect paths.** A route that hands patient-supplied content to a
provider gates at the route. Everything reaching a provider through the workflow
engine gates once, inside ``services.workflows.actions.run``, because fifteen
routers can trigger a workflow and fifteen copies of a check is how this problem
started.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

log = logging.getLogger(__name__)

# The version of the authorization text currently shown to patients. §164.508
# asks what someone agreed to, not merely that they agreed, so this is recorded
# alongside every grant.
#
# "1.0" is what routers/intake.py has been writing to patient rows, and this
# stays equal to it deliberately. Consolidating two constants into one is a
# refactor; changing the value would silently make new records claim a different
# authorization than the one the patient actually saw. Bump it when the text
# changes, not when the code moves.
CURRENT_VERSION = "1.0"

# What counts as a yes. Identical to the values the three original inline copies
# accepted, so consolidating them changes no behaviour for existing clients.
_AFFIRMATIVE = {"true", "1", "yes"}


def granted(value: Any) -> bool:
    """Whether a consent field carries an affirmative answer.

    Anything absent, empty, malformed or unrecognised is a no. Consent is the
    one field where a parsing ambiguity must never resolve in our favour, so
    this reads the value rather than testing it for truthiness: a JSON ``true``
    is a real answer, but a non-empty list is not, and bare truthiness would let
    ``["maybe"]`` through.

    ``"on"`` is deliberately excluded. It is what an unchecked-then-checked HTML
    checkbox posts and carries no evidence that anyone read anything.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    if not isinstance(value, str):
        return False
    return value.strip().lower() in _AFFIRMATIVE


def record_of(value: Any, *, version: str | None = None) -> dict[str, Any]:
    """The consent record to persist on a patient row.

    "They consented" is not defensible on its own. A reviewer asks what the
    patient was shown and when, so the version of the authorization text and the
    timestamp are part of the record and default rather than going missing.
    """
    ok = granted(value)
    return {
        "granted": ok,
        "version": (version or CURRENT_VERSION) if ok else (version or None),
        "granted_at": _now() if ok else None,
    }


def for_patient(patient: dict[str, Any] | None) -> bool:
    """Whether a stored patient row carries a recorded consent.

    Used on paths where the patient is not present to answer, such as a workflow
    firing hours after an intake. The row is the only evidence available, and
    absence of evidence is a no.
    """
    if not isinstance(patient, dict):
        return False
    return bool(str(patient.get("consent_granted_at") or "").strip())


def require(
    value: Any,
    *,
    action: str,
    identity: str | None = None,
    source_ip: str | None = None,
    detail: str = "Consent required before this information can be processed by AI.",
) -> None:
    """Raise 403 unless consent is affirmative, and record the refusal.

    ``action`` names the path being refused, e.g. ``"abuse.scan_id_no_consent"``,
    and is written to the audit log so a compliance review can see both that the
    gate exists and that it fires.
    """
    if granted(value):
        return
    audit_refusal(action, identity=identity, source_ip=source_ip)
    raise HTTPException(status_code=403, detail=detail)


def for_call(session_record: dict[str, Any] | None) -> bool:
    """Whether a voice session may send caller audio or text to a provider.

    A phone call has no form field to tick, so consent here is the disclosure
    the caller heard before they said anything: an automated assistant, recorded
    and transcribed, a person on request. ``routers/voice.py`` records that the
    disclosure was played, and this reads it back.

    A session with no recorded disclosure is a no. That case is not theoretical:
    sessions created before this shipped have no such field, and their callers
    genuinely were never told.

    **This is a policy the deployment owns, not one this file decides.**
    Continuing to speak after a disclosure is the standard basis for healthcare
    IVR, and is what ``VOICE_CONSENT_MODE=disclosure`` implements. Whether that
    is sufficient authorization depends on the state and on the hospital's own
    counsel, so ``VOICE_CONSENT_MODE=explicit`` requires the caller to answer
    yes before anything they say reaches a provider. Neither is the safe default
    in every jurisdiction, which is exactly why it is a setting.
    """
    if not isinstance(session_record, dict):
        return False
    if not str(session_record.get("disclosure_played_at") or "").strip():
        return False
    if _voice_mode() == "explicit":
        return granted(session_record.get("consent_affirmed"))
    return True


def record_disclosure(version: str) -> dict[str, Any]:
    """The fields to store on a call session once the disclosure has played."""
    return {
        "disclosure_played_at": _now(),
        "disclosure_version": version,
        "consent_mode": _voice_mode(),
    }


def _voice_mode() -> str:
    from lib.config import settings  # noqa: PLC0415

    mode = str(getattr(settings, "voice_consent_mode", "") or "disclosure").strip().lower()
    return mode if mode in {"disclosure", "explicit"} else "disclosure"


def audit_refusal(
    action: str,
    *,
    identity: str | None = None,
    source_ip: str | None = None,
) -> None:
    """Write the refusal line. Separate from ``require`` because not every
    refusal is an HTTP one: a workflow action returns a blocked result instead
    of raising, and still has to be recorded."""
    # Imported here rather than at module scope: lib.audit pulls in storage, and
    # a consent check must not be the thing that creates an import cycle.
    from lib import audit as _audit  # noqa: PLC0415

    try:
        _audit.record(
            clinician_id=None,
            clinician_name=None,
            action=action,
            source_ip=source_ip,
            status_code=403,
            extra={"identity": identity},
        )
    except Exception:  # noqa: BLE001
        # A failure to write the audit line must never convert a refusal into an
        # allow. Log it and let the caller still refuse.
        log.exception("consent refusal could not be audited: %s", action)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
