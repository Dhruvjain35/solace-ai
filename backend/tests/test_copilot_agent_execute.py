"""Copilot Agent execute tests — confirm-gated writes via the EHR gateway.

Verifies the core safety property: ONLY the actions in the request body are
written; the subject reference is attached server-side; disallowed resource
types are rejected per-action; every action attempt is audited. Writes land in
the fhir_writer local mock store (no vendor configured), mirroring the
routers/ehr.py write_back path.
"""
from __future__ import annotations

import json
import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db import storage  # noqa: E402
from lib.auth import require_clinician  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from services import fhir_writer  # noqa: E402

HOSP = "hosp-a"
PID = "p1"
URL = f"/api/{HOSP}/patients/{PID}/copilot/agent/execute"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    settings.solace_mode = "local"
    storage._reset_for_tests()
    fhir_writer.clear_local()
    monkeypatch.delenv("FHIR_BASE_URL", raising=False)
    storage.put_hospital({"hospital_id": HOSP, "name": "Hospital A"})  # no EHR vendor -> mock store
    storage.put_patient({
        "patient_id": PID, "hospital_id": HOSP, "name": "Test Patient",
        "consent_granted_at": "2024-03-15T10:00:00Z", "consent_version": "v1",
        "medical_info": json.dumps({"age": 50, "sex": "female"}),
    })
    app.dependency_overrides[require_clinician] = lambda: {
        "clinician_id": "tester", "hospital_id": HOSP,
        "name": "Tester", "role": "clinician", "auth_method": "jwt",
    }
    yield
    storage._reset_for_tests()
    fhir_writer.clear_local()
    app.dependency_overrides.pop(require_clinician, None)


def _condition_action(action_id="a1"):
    return {
        "id": action_id,
        "resource_type": "Condition",
        "summary": "Add essential hypertension (I10)",
        "resource": {"code": {"coding": [{"code": "I10",
                                          "display": "Essential hypertension"}]}},
    }


# ---- gates -----------------------------------------------------------------------

def test_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")
    app.dependency_overrides[require_clinician] = _reject
    r = client.post(URL, json={"actions": [_condition_action()]})
    assert r.status_code == 401


def test_cross_hospital_patient_is_404_and_nothing_written(client):
    storage.put_patient({"patient_id": "px", "hospital_id": "hosp-b", "name": "Other"})
    r = client.post(f"/api/{HOSP}/patients/px/copilot/agent/execute",
                    json={"actions": [_condition_action()]})
    assert r.status_code == 404
    assert fhir_writer.list_local() == []


def test_unknown_hospital_is_404(client):
    storage.put_patient({"patient_id": "py", "hospital_id": "ghost"})
    r = client.post("/api/ghost/patients/py/copilot/agent/execute",
                    json={"actions": [_condition_action()]})
    # require_clinician is overridden, but the hospital itself doesn't exist.
    assert r.status_code == 404


def test_empty_actions_rejected(client):
    r = client.post(URL, json={"actions": []})
    assert r.status_code == 422


# ---- the write path --------------------------------------------------------------

def test_confirmed_write_lands_with_server_side_subject(client):
    r = client.post(URL, json={"actions": [_condition_action()]})
    assert r.status_code == 200
    d = r.json()
    assert d["errors"] == []
    assert d["written"] == [{"id": "a1", "resource_type": "Condition",
                             "summary": "Add essential hypertension (I10)"}]

    stored = fhir_writer.list_local("Condition")
    assert len(stored) == 1
    assert stored[0]["subject"] == {"reference": f"Patient/{PID}"}
    assert stored[0]["resourceType"] == "Condition"


def test_allergy_uses_patient_reference(client):
    r = client.post(URL, json={"actions": [{
        "id": "a1", "resource_type": "AllergyIntolerance",
        "summary": "Document sulfa allergy",
        # A client-smuggled subject/patient ref must be overwritten server-side.
        "resource": {"code": {"text": "sulfonamide"},
                     "patient": {"reference": "Patient/SOMEONE-ELSE"}},
    }]})
    assert r.status_code == 200
    assert len(r.json()["written"]) == 1
    stored = fhir_writer.list_local("AllergyIntolerance")
    assert stored[0]["patient"] == {"reference": f"Patient/{PID}"}
    assert "subject" not in stored[0]


def test_client_supplied_subject_is_overwritten(client):
    action = _condition_action()
    action["resource"]["subject"] = {"reference": "Patient/SOMEONE-ELSE"}
    r = client.post(URL, json={"actions": [action]})
    assert r.status_code == 200
    stored = fhir_writer.list_local("Condition")
    assert stored[0]["subject"] == {"reference": f"Patient/{PID}"}


def test_disallowed_resource_type_is_rejected_per_action(client):
    r = client.post(URL, json={"actions": [{
        "id": "a1", "resource_type": "Patient", "summary": "overwrite the patient",
        "resource": {"name": [{"family": "Hacked"}]},
    }]})
    assert r.status_code == 200
    d = r.json()
    assert d["written"] == []
    assert len(d["errors"]) == 1
    assert d["errors"][0]["id"] == "a1"
    assert "not allowed" in d["errors"][0]["error"]
    assert fhir_writer.list_local() == []  # NOTHING was written


def test_mixed_batch_writes_only_the_allowed_action(client):
    r = client.post(URL, json={"actions": [
        _condition_action("a1"),
        {"id": "a2", "resource_type": "Encounter", "summary": "sneaky",
         "resource": {}},
    ]})
    assert r.status_code == 200
    d = r.json()
    assert [w["id"] for w in d["written"]] == ["a1"]
    assert [e["id"] for e in d["errors"]] == ["a2"]
    # Exactly ONE resource exists — only what was requested AND allowed.
    assert len(fhir_writer.list_local()) == 1


@pytest.mark.parametrize("rtype", ["Condition", "Observation", "AllergyIntolerance",
                                   "ServiceRequest", "MedicationRequest",
                                   "DocumentReference"])
def test_full_allowlist_is_writable(client, rtype):
    r = client.post(URL, json={"actions": [{
        "id": "a1", "resource_type": rtype, "summary": f"write {rtype}",
        "resource": {},
    }]})
    assert r.status_code == 200
    assert len(r.json()["written"]) == 1
    assert len(fhir_writer.list_local(rtype)) == 1


def test_gateway_failure_is_a_per_action_error(client, monkeypatch):
    from services import ehr_gateway

    def boom(resource, *, ehr_config=None, **kw):
        raise ehr_gateway.EhrGatewayError("vendor offline")

    monkeypatch.setattr(ehr_gateway, "write_resource", boom)
    # The router binds ehr_gateway by module ref, so patching the module works.
    r = client.post(URL, json={"actions": [_condition_action()]})
    assert r.status_code == 200
    d = r.json()
    assert d["written"] == []
    assert len(d["errors"]) == 1 and "EHR write failed" in d["errors"][0]["error"]


# ---- audit -----------------------------------------------------------------------

def test_every_action_is_audited_individually(client, monkeypatch):
    records = []
    monkeypatch.setattr("lib.audit.record", lambda **kw: records.append(kw))
    client.post(URL, json={"actions": [
        _condition_action("a1"),
        {"id": "a2", "resource_type": "Patient", "summary": "bad", "resource": {}},
    ]})
    execute_records = [r for r in records if r["action"] == "copilot.agent_execute"]
    assert len(execute_records) == 2  # one audit entry PER action, allowed or not
    by_id = {r["extra"]["action_id"]: r for r in execute_records}
    assert by_id["a1"]["extra"]["allowed"] is True
    assert by_id["a2"]["extra"]["allowed"] is False
    assert all(r["patient_id"] == PID for r in execute_records)
