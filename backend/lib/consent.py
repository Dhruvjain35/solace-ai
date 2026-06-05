"""AI-processing consent gate (SEC-004, HIPAA §164.508).

A small, reusable, framework-agnostic helper that answers one question: *did this
patient authorize AI processing of their PHI?* Solace records consent at intake
(``routers/intake.py`` writes ``consent_granted_at`` + ``consent_version`` onto
the patient record only after the patient explicitly grants it). Any downstream
code path that is about to send PHI to — or derive a model prompt from — an AI
provider must confirm that authorization first.

This module is intentionally framework-agnostic: it raises a plain Python error
and NEVER imports FastAPI. Callers at the HTTP boundary translate the error into
a 403 (see ``routers/ehr_copilot.py``); deeper PHI-boundary code (the copilot
pipeline) calls :func:`assert_ai_consent` before the first model call.

Why a timestamp, not a boolean: the intake flow stores ``consent_granted_at`` as
an ISO-8601 instant (who/when/which version), so the presence of a non-empty
value is the durable, auditable proof of consent on the stored record. A patient
who never completed consented intake has no such field and is rejected.
"""
from __future__ import annotations

from typing import Any


class ConsentMissing(PermissionError):
    """Raised when a patient has not authorized AI processing of their PHI.

    Subclasses ``PermissionError`` so existing ``except PermissionError``
    handlers still catch it, while callers that want to distinguish a consent
    violation from a generic permission error can catch this type specifically.
    The message is safe to surface to a clinician (carries no PHI).
    """


def has_ai_consent(patient: dict[str, Any] | None) -> bool:
    """Return True iff ``patient`` carries a recorded AI-processing consent.

    Consent is proven by a non-empty ``consent_granted_at`` instant written at
    intake (the canonical SEC-004 field). A ``consent_revoked_at`` value that is
    set (truthy) withdraws it — HIPAA authorizations are revocable. Does not raise.
    """
    if not patient:
        return False
    if patient.get("consent_revoked_at"):
        return False
    return bool(str(patient.get("consent_granted_at") or "").strip())


def assert_ai_consent(patient: dict[str, Any] | None) -> dict[str, Any]:
    """Return ``patient`` if AI-processing consent is on record, else raise.

    Raises:
        ConsentMissing: if ``patient`` is None/empty or has no recorded (or a
            revoked) AI-processing consent. HIPAA §164.508 requires explicit
            authorization before PHI is processed by an AI provider.
    """
    if not has_ai_consent(patient):
        raise ConsentMissing(
            "Patient has not authorized AI processing of their record."
        )
    return patient
