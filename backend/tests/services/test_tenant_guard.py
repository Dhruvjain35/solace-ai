"""Tenant-isolation guard for the EHR Copilot context loader.

Defense in depth for SEC-008 / COMP-011: ``context.build_chart`` receives a
hospital_id and loads a patient by id. It must NOT trust that the loaded patient
belongs to that hospital. These tests pin the guarantee:

  - a cross-hospital patient never builds a chart (surfaces as 404)
  - a missing patient never builds a chart (surfaces as 404)
  - a same-hospital patient builds a chart exactly as before

It also exercises the framework-agnostic ``lib.tenant`` helper directly.
"""
from __future__ import annotations

import json

import pytest

context = pytest.importorskip("services.copilot.context")

from fastapi import HTTPException  # noqa: E402

from lib import tenant  # noqa: E402

# --- Synthetic patient that belongs to hospital "h1" -----------------------

_PATIENT_H1 = {
    "patient_id": "p1",
    "hospital_id": "h1",
    # SEC-004: build_chart now also enforces the AI-processing consent gate, so
    # this tenancy fixture must carry a recorded authorization to exercise the
    # happy path. The cross-tenant/missing-patient cases reject before consent.
    "consent_granted_at": "2024-03-15T10:00:00Z",
    "name": "Marcus Welby",
    "chief_complaint": "chest pain",
    "transcript": "reports crushing chest pain.",
    "esi_level": 2,
    "vitals": {"abnormal": True},
    "medical_info": json.dumps({
        "age": 67, "sex": "male",
        "conditions": ["atrial fibrillation"],
        "medications": ["warfarin 5mg"], "allergies": ["penicillin"],
    }),
}


# ---------------------------------------------------------------------------
# lib.tenant — framework-agnostic helper
# ---------------------------------------------------------------------------

class TestTenantHelper:
    def test_patient_belongs_same_hospital(self):
        assert tenant.patient_belongs(_PATIENT_H1, "h1") is True

    def test_patient_belongs_cross_hospital(self):
        assert tenant.patient_belongs(_PATIENT_H1, "h2") is False

    def test_patient_belongs_missing(self):
        assert tenant.patient_belongs(None, "h1") is False
        assert tenant.patient_belongs({}, "h1") is False

    def test_assert_returns_patient_same_hospital(self):
        assert tenant.assert_patient_in_hospital(_PATIENT_H1, "h1") is _PATIENT_H1

    def test_assert_raises_cross_hospital(self):
        with pytest.raises(tenant.CrossTenantAccess):
            tenant.assert_patient_in_hospital(_PATIENT_H1, "h2")

    def test_assert_raises_missing(self):
        with pytest.raises(tenant.CrossTenantAccess):
            tenant.assert_patient_in_hospital(None, "h1")

    def test_cross_tenant_is_permission_error(self):
        # Existing `except PermissionError` handlers still catch it.
        assert issubclass(tenant.CrossTenantAccess, PermissionError)


# ---------------------------------------------------------------------------
# build_chart — the PHI-boundary loader
# ---------------------------------------------------------------------------

class TestBuildChartTenancy:
    def test_same_hospital_builds_chart(self, monkeypatch):
        monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(_PATIENT_H1))
        ctx = context.build_chart("h1", "p1")
        assert ctx["hospital_id"] == "h1"
        assert ctx["patient_id"] == "p1"
        # Legitimate same-hospital behavior unchanged: real values present.
        assert ctx["chart"]["name"] == "Marcus Welby"
        assert "warfarin 5mg" in ctx["chart"]["medications"]
        assert ctx["chart"]["chief_complaint"] == "chest pain"
        assert ctx["patient"]["hospital_id"] == "h1"

    def test_cross_hospital_raises_404(self, monkeypatch):
        # Patient exists but belongs to h1; caller asserts h2.
        monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(_PATIENT_H1))
        with pytest.raises(HTTPException) as exc:
            context.build_chart("h2", "p1")
        assert exc.value.status_code == 404

    def test_missing_patient_raises_404(self, monkeypatch):
        monkeypatch.setattr("db.storage.get_patient", lambda pid: None)
        with pytest.raises(HTTPException) as exc:
            context.build_chart("h1", "does-not-exist")
        assert exc.value.status_code == 404

    def test_no_phi_in_404_detail(self, monkeypatch):
        # The 404 message must not leak that the patient exists elsewhere.
        monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(_PATIENT_H1))
        with pytest.raises(HTTPException) as exc:
            context.build_chart("h2", "p1")
        assert "h1" not in str(exc.value.detail)
        assert "Marcus" not in str(exc.value.detail)
