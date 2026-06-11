"""Tests for the override-log access split (lead fix).

The PUBLIC /api/governance/override-log must REDACT identifying/PHI fields
(clinician_id + free-text notes); the full raw log is only available via the
clinician-authed /api/governance/override-log/full endpoint (SEC-008 + COMP-002).
"""
from __future__ import annotations

import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib import provenance  # noqa: E402
from lib.auth import require_clinician  # noqa: E402
from main import app  # noqa: E402

_CANARY_NOTES = "PATIENT-DISCLOSED-SUICIDAL-IDEATION-canary"
_CANARY_CLINICIAN = "dr-jane-doe-canary"
_CANARY_PATIENT = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _seed_override():
    provenance._OVERRIDES.clear()
    provenance.record_override(
        purpose="ddx",
        model_name="claude-haiku-4-5",
        decision="edited",
        clinician_id=_CANARY_CLINICIAN,
        patient_id=_CANARY_PATIENT,
        hospital_id="demo",
        diff_chars=42,
        notes=_CANARY_NOTES,
    )
    yield
    provenance._OVERRIDES.clear()


def test_public_override_log_redacts_clinician_and_notes(client):
    r = client.get("/api/governance/override-log?hospital_id=demo")
    assert r.status_code == 200
    body = r.json()
    assert body["redacted"] is True
    raw = r.text
    assert _CANARY_NOTES not in raw
    assert _CANARY_CLINICIAN not in raw
    # patient_id is PHI on this UNAUTHENTICATED, any-hospital endpoint — must be stripped.
    assert _CANARY_PATIENT not in raw
    assert "notes" not in raw
    assert "clinician_id" not in raw
    assert "patient_id" not in raw
    # non-sensitive fields still present
    entry = body["entries"][0]
    assert entry["decision"] == "edited"
    assert entry["purpose"] == "ddx"
    assert entry["diff_chars"] == 42


def test_full_override_log_is_gated_by_require_clinician(client):
    # Prove the /full route is gated: force require_clinician to reject and confirm
    # /full returns 401 while the PUBLIC redacted endpoint stays open.
    from fastapi import HTTPException

    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")

    app.dependency_overrides[require_clinician] = _reject
    try:
        assert client.get("/api/governance/demo/override-log/full").status_code == 401
        assert client.get("/api/governance/override-log?hospital_id=demo").status_code == 200
    finally:
        app.dependency_overrides.pop(require_clinician, None)


def test_full_override_log_returns_raw_when_authed(client):
    app.dependency_overrides[require_clinician] = lambda: {
        "clinician_id": "tester", "hospital_id": "demo", "name": "Tester", "auth_method": "jwt",
    }
    try:
        r = client.get("/api/governance/demo/override-log/full")
        assert r.status_code == 200
        body = r.json()
        assert body["redacted"] is False
        assert body["entries"][0]["notes"] == _CANARY_NOTES
        assert body["entries"][0]["clinician_id"] == _CANARY_CLINICIAN
    finally:
        app.dependency_overrides.pop(require_clinician, None)
