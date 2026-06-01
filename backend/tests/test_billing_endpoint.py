"""Billing usage endpoint + triage metering hook.

Covers:
  - GET /api/{hospital_id}/billing/usage is gated by require_clinician (SEC-008);
  - when authed it returns the aggregate, NON-PHI usage summary (no per-encounter detail);
  - refine_triage emits exactly one billing event at the END of a successful refine;
  - a metering failure NEVER breaks the triage request (still returns 200).
"""
from __future__ import annotations

import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import metering  # noqa: E402
from lib.auth import require_clinician  # noqa: E402
from db import storage  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state():
    settings.solace_mode = "local"
    metering._EVENTS.clear()
    storage._reset_for_tests()
    yield
    metering._EVENTS.clear()
    storage._reset_for_tests()
    app.dependency_overrides.pop(require_clinician, None)


def _auth_as(hospital_id: str):
    app.dependency_overrides[require_clinician] = lambda: {
        "clinician_id": "tester", "hospital_id": hospital_id, "name": "Tester", "auth_method": "jwt",
    }


# ---- endpoint auth gating -----------------------------------------------------------
def test_usage_endpoint_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")

    app.dependency_overrides[require_clinician] = _reject
    assert client.get("/api/hosp-a/billing/usage").status_code == 401


def test_usage_endpoint_returns_aggregate_when_authed(client):
    _auth_as("hosp-a")
    metering.record_encounter(hospital_id="hosp-a", encounter_type="triage.refine", model_source="m")
    metering.record_encounter(hospital_id="hosp-a", encounter_type="triage.refine", model_source="m")

    r = client.get("/api/hosp-a/billing/usage?period=month")
    assert r.status_code == 200
    body = r.json()
    assert body["hospital_id"] == "hosp-a"
    assert body["billable_encounters"] == 2
    assert body["estimated_value_usd"] == round(2 * settings.billing_rate_per_encounter_usd, 2)
    # Aggregate-only: no per-encounter identifiers leak out.
    raw = r.text
    assert "event_id" not in raw
    assert "ts_id" not in raw


def test_usage_endpoint_is_tenant_scoped(client):
    metering.record_encounter(hospital_id="hosp-a", encounter_type="triage.refine", model_source="m")
    metering.record_encounter(hospital_id="hosp-b", encounter_type="triage.refine", model_source="m")
    _auth_as("hosp-b")
    r = client.get("/api/hosp-b/billing/usage")
    assert r.json()["billable_encounters"] == 1


# ---- refine_triage emits a billing event at the END --------------------------------
def _seed_patient(hospital_id="hosp-a", patient_id="p-1"):
    storage.put_patient({
        "patient_id": patient_id, "hospital_id": hospital_id,
        "name": "Test Patient", "esi_level": 3, "status": "waiting",
    })


def _fake_predict_result():
    return {
        "esi_level": 2, "confidence": 0.91,
        "probabilities": {"1": 0.05, "2": 0.7, "3": 0.2, "4": 0.04, "5": 0.01},
        "conformal_set": [2, 3], "top_features": [{"feature": "spo2", "value": 0.3}],
        "source": "lightgbm-ensemble-v3",
    }


def test_refine_triage_emits_one_billing_event(client, monkeypatch):
    _seed_patient("hosp-a", "p-1")
    import services.triage_ml as triage_ml  # noqa: PLC0415
    monkeypatch.setattr(triage_ml, "predict", lambda patient, vitals: _fake_predict_result())
    # Quiet the workflow trigger so the test focuses on metering.
    import services.workflows.engine as wf  # noqa: PLC0415
    monkeypatch.setattr(wf, "fire", lambda *a, **k: None)
    _auth_as("hosp-a")

    r = client.post("/api/hosp-a/patients/p-1/refine-triage", json={"spo2": 88, "heart_rate": 120})
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Exactly one billing event, NON-PHI, with the model source threaded through.
    assert len(metering._EVENTS) == 1
    ev = metering._EVENTS[0]
    assert ev["hospital_id"] == "hosp-a"
    assert ev["encounter_type"] == "triage.refine"
    assert ev["model_source"] == "lightgbm-ensemble-v3"
    assert ev["billable"] is True
    # NON-PHI: no patient identifier of any kind on the event.
    assert "patient_id" not in ev
    assert "p-1" not in str(ev)


def test_metering_failure_does_not_break_triage(client, monkeypatch):
    _seed_patient("hosp-a", "p-1")
    import services.triage_ml as triage_ml  # noqa: PLC0415
    monkeypatch.setattr(triage_ml, "predict", lambda patient, vitals: _fake_predict_result())
    import services.workflows.engine as wf  # noqa: PLC0415
    monkeypatch.setattr(wf, "fire", lambda *a, **k: None)

    def _boom(**kw):
        raise RuntimeError("metering down")

    monkeypatch.setattr(metering, "record_encounter", _boom)
    _auth_as("hosp-a")

    r = client.post("/api/hosp-a/patients/p-1/refine-triage", json={"spo2": 88})
    # Triage must still succeed even though metering blew up.
    assert r.status_code == 200
    assert r.json()["success"] is True
