"""Patient-result poll endpoint contract — GET /public-patients/{id}.

The patient result screen renders ESI + explanation immediately from the fast
intake response, then polls this endpoint for the DEFERRED comfort_protocol +
audio_url (generated out-of-band by services/intake_artifacts after intake
returns, to keep the sync intake path under API Gateway's 30s timeout).

These tests pin two things:
  * the endpoint surfaces exactly the patient-safe fields the poller needs
    (esi_level/esi_label/language/patient_explanation/comfort_protocol/
    audio_url/artifacts_status/comfort_ready/care_recommendation) and reflects
    the pending → ready transition;
  * the endpoint NEVER leaks transcript, clinician artifacts, or any other PHI
    beyond the patient's own result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from db import storage  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from services import intake_artifacts  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _local_clean(monkeypatch):
    monkeypatch.setattr(settings, "solace_mode", "local", raising=False)
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()


def _seed(patient_id="p-1", hospital_id="h-1", **overrides):
    patient = {
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "name": "Jane Q Public",
        "language": "es",
        "transcript": "SECRET TRANSCRIPT chest pain SSN 123-45-6789",
        "medical_info": json.dumps({"age": 58}),
        "followup_qa": json.dumps([{"q": "onset?", "a": "2h"}]),
        "photo_analysis": json.dumps({}),
        "esi_level": 2,
        "esi_label": "Emergent",
        "patient_explanation": "You will be seen very soon.",
        "care_recommendation": json.dumps(
            {"destination": "ed", "label": "Stay in the ED", "rationale": "x",
             "action_cta": "Wait here", "severity": "high"}
        ),
        "status": "waiting",
        **intake_artifacts.empty_artifacts(),
        "artifacts_status": intake_artifacts.STATUS_PENDING,
    }
    patient.update(overrides)
    storage.put_patient(patient)
    return patient


# ---- pending → ready transition for comfort/audio ----------------------------------
def test_pending_returns_empty_comfort_and_not_ready(client):
    _seed()
    r = client.get("/api/h-1/public-patients/p-1")
    assert r.status_code == 200
    body = r.json()
    # ESI + explanation available immediately for the result screen.
    assert body["esi_level"] == 2
    assert body["esi_label"] == "Emergent"
    assert body["language"] == "es"
    assert body["patient_explanation"] == "You will be seen very soon."
    # Comfort/audio still pending.
    assert body["comfort_protocol"] == []
    assert body["audio_url"] is None
    assert body["artifacts_status"] == intake_artifacts.STATUS_PENDING
    assert body["comfort_ready"] is False


def test_ready_after_deferred_generation(client, monkeypatch):
    from lib import claude  # noqa: PLC0415

    monkeypatch.setattr(claude, "available", lambda: False)
    _seed()
    # Run the deferred worker (populates comfort_protocol + audio_url + status).
    intake_artifacts.generate_clinician_artifacts("h-1", "p-1")

    body = client.get("/api/h-1/public-patients/p-1").json()
    assert body["artifacts_status"] == intake_artifacts.STATUS_READY
    assert isinstance(body["comfort_protocol"], list)
    assert len(body["comfort_protocol"]) > 0
    assert body["comfort_ready"] is True


# ---- patient-safe contract: NO PHI / NO clinician artifacts leak --------------------
def test_no_phi_or_clinician_artifacts_leak(client, monkeypatch):
    from lib import claude  # noqa: PLC0415

    monkeypatch.setattr(claude, "available", lambda: False)
    _seed()
    # Even after the clinician artifacts exist, the public endpoint must not
    # surface any of them.
    intake_artifacts.generate_clinician_artifacts("h-1", "p-1")

    body = client.get("/api/h-1/public-patients/p-1").json()
    forbidden = {
        "transcript", "clinician_prebrief", "clinical_scribe_note",
        "differential", "workup_orders", "disposition", "shap_values",
        "clinical_flags", "composites", "medical_info", "followup_qa",
        "insurance_info", "consent_granted_at", "ai_processing_log",
        "photo_analysis", "name", "seen_by", "clinician_id",
    }
    leaked = forbidden & set(body.keys())
    assert not leaked, f"public-patient endpoint leaked: {leaked}"

    # Belt-and-suspenders: the raw transcript / SSN must not appear anywhere in
    # the serialized response.
    blob = json.dumps(body)
    assert "SECRET TRANSCRIPT" not in blob
    assert "123-45-6789" not in blob


def test_cross_hospital_returns_404(client):
    _seed(hospital_id="h-1")
    assert client.get("/api/h-OTHER/public-patients/p-1").status_code == 404
