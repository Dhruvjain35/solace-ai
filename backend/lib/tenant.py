"""Tenant-isolation guard (framework-agnostic).

A small, reusable defense-in-depth helper for enforcing hospital_id tenancy on
a patient record. Routers already guard cross-hospital reads at the HTTP surface
(SEC-008 / COMP-011), but deeper code paths that receive a hospital_id and then
load a patient by id must not implicitly trust that the patient belongs to that
hospital. Use this guard right after any ``storage.get_patient(patient_id)`` so a
missing or cross-hospital patient can never be used.

This module is intentionally framework-agnostic: it raises plain Python errors
and NEVER imports FastAPI. Callers at the HTTP boundary translate the error into
the appropriate HTTPException (typically 404 — do not reveal existence across
hospitals).
"""
from __future__ import annotations

from typing import Any


class CrossTenantAccess(PermissionError):
    """Raised when a patient does not belong to the asserting hospital_id.

    Subclasses PermissionError so existing ``except PermissionError`` handlers
    still catch it, while callers that want to distinguish a tenancy violation
    from a generic permission error can catch this type specifically.
    """


def patient_belongs(patient: dict[str, Any] | None, hospital_id: str) -> bool:
    """Return True iff ``patient`` exists and its hospital_id matches.

    Mirrors the router guard exactly: a missing patient or a hospital_id
    mismatch both fail. Does not raise.
    """
    if not patient:
        return False
    return patient.get("hospital_id") == hospital_id


def assert_patient_in_hospital(
    patient: dict[str, Any] | None, hospital_id: str
) -> dict[str, Any]:
    """Return ``patient`` if it belongs to ``hospital_id``, else raise.

    Raises:
        CrossTenantAccess: if ``patient`` is None/empty or its ``hospital_id``
            does not match. The message is deliberately uniform so callers map
            it to a single 404 (do not leak whether the patient exists in some
            other hospital).
    """
    if not patient_belongs(patient, hospital_id):
        raise CrossTenantAccess("Patient not found for this hospital")
    return patient
