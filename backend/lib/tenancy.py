"""The tenant boundary (CONSTITUTION SEC-008).

A clinician authenticated to one hospital must not reach another hospital's
patients. That is the worst outcome available in this codebase: not a cost
problem or a compliance paperwork problem, but one hospital's staff reading
another hospital's charts.

Two checks are needed and they are easy to confuse:

  1. Does the JWT's hospital match the hospital in the path? Handled by
     ``lib.auth.require_clinician``, and it works — a token for alpha calling
     ``/api/beta/...`` gets a 403.

  2. Does the *patient* belong to that hospital? This one. Check 1 passing tells
     you nothing about it, because the attacker uses their OWN hospital in the
     path and someone else's patient_id in the body.

Check 2 was a copy-pasted three-liner in eleven routes and absent from a twelfth.
``GET /api/{hospital}/patients/{patient_id}/notes`` read the note text of a
patient belonging to a different hospital, and the response carried
``hospital_id: <the other hospital>`` in the payload — the data knew, and nothing
looked. Verified by driving it, not by reading it.

So the check lives here, and ``tests/test_tenant_isolation.py`` walks the router
package asserting every clinician route that resolves a patient goes through it.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

log = logging.getLogger(__name__)


def require_patient(patient_id: str, hospital_id: str) -> dict[str, Any]:
    """Load a patient, or 404 if it is not this hospital's to load.

    404 rather than 403, deliberately. A 403 would confirm the patient exists
    somewhere, which turns this endpoint into an oracle for whether a given id is
    a real patient at some other hospital on the platform. "Not found" is both
    true from the caller's perspective and silent.
    """
    from db import storage  # noqa: PLC0415  (avoids an import cycle through lib)

    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        if patient:
            # Worth a line: a valid clinician asked for a real patient belonging
            # to someone else. Usually a stale tab or a mistyped id, occasionally
            # not, and either way nobody can look into it later if it is silent.
            log.warning(
                "cross-tenant patient access refused: hospital=%s patient=%s",
                hospital_id, patient_id,
            )
            _audit_refusal(patient_id, hospital_id)
        raise HTTPException(status_code=404, detail="patient not found")
    return patient


def belongs_to(record: dict[str, Any] | None, hospital_id: str) -> bool:
    """Whether an already-loaded record belongs to this hospital.

    For the paths that fetch through a service rather than the patient store and
    already hold the row. Missing hospital_id on the record counts as no: a row
    with no tenant is exactly the shape that leaks across one.
    """
    if not isinstance(record, dict):
        return False
    return bool(record.get("hospital_id")) and record["hospital_id"] == hospital_id


def _audit_refusal(patient_id: str, hospital_id: str) -> None:
    from lib import audit as _audit  # noqa: PLC0415

    try:
        _audit.record(
            clinician_id=None,
            clinician_name=None,
            action="abuse.cross_tenant_patient_access",
            source_ip=None,
            status_code=404,
            extra={"requested_patient_id": patient_id, "acting_hospital_id": hospital_id},
        )
    except Exception:  # noqa: BLE001
        # An audit failure must not turn a refusal into an allow.
        log.exception("cross-tenant refusal could not be audited")
