"""Every decision about a patient lands on one verifiable timeline.

The ledger was built with 28 tests and wired to nothing. This is the part that
makes it a product feature rather than a well-tested module: a clinician can ask
"what did this system think about this patient, when, and how sure was it", and
get an answer whose integrity they can check without trusting us.

Three kinds of thing go on the timeline:

  triage_ml    a model score, with its conformal set and the coverage that set
               claims to hold at
  event        something that happened — a clinician accepted, edited or
               rejected an AI suggestion. Not a prediction, so no uncertainty.
  (future)     anything else that changes what the system believes

The rule the ledger enforces is that a *prediction* cannot be recorded without a
stated coverage figure. Wiring it up immediately surfaced that the ML artifacts
store q_hat but never the alpha it was calibrated against, so the coverage of
every conformal set this product has ever produced was unrecorded. Rather than
assert 90% and hope, the entry now carries where the number came from.
"""
from __future__ import annotations

import os
import uuid

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402

settings.solace_mode = "local"

from db import storage  # noqa: E402
from lib import jwt_auth  # noqa: E402
from main import app  # noqa: E402
from services import encounter_ledger as ledger  # noqa: E402

HOSP = "demo"


@pytest.fixture(autouse=True)
def clean():
    ledger.reset()
    yield
    ledger.reset()


@pytest.fixture
def patient():
    pid = f"pt-{uuid.uuid4().hex[:10]}"
    storage.put_patient({
        "patient_id": pid, "hospital_id": HOSP, "name": "Test Patient",
        "chief_complaint": "chest pain", "esi_level": 3,
    })
    return pid


@pytest.fixture
def client():
    token, _ = jwt_auth.issue_token({
        "clinician_id": "c-1", "hospital_id": HOSP, "name": "Dr Test", "role": "clinician",
    })
    return TestClient(app, headers={
        "Authorization": f"Bearer {token}", "User-Agent": f"pytest-{uuid.uuid4().hex}",
    })


# ── The read surface ─────────────────────────────────────────────────────────

def test_an_encounter_with_no_decisions_returns_an_empty_timeline(client, patient):
    """Not a 404. "Nothing has been decided yet" is a real and different answer
    from "no such patient"."""
    r = client.get(f"/api/{HOSP}/encounters/{patient}/timeline")
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == []
    assert body["verified"] is True


def test_the_timeline_is_scoped_to_the_hospital(patient):
    """Same rule as every other patient-scoped route. A timeline is a complete
    record of a patient's care, so leaking one across tenants is worse than
    leaking any single decision from it."""
    token, _ = jwt_auth.issue_token({
        "clinician_id": "c-x", "hospital_id": "other-health", "name": "Dr X", "role": "clinician",
    })
    other = TestClient(app, headers={
        "Authorization": f"Bearer {token}", "User-Agent": f"pytest-{uuid.uuid4().hex}",
    })
    r = other.get(f"/api/other-health/encounters/{patient}/timeline")
    assert r.status_code == 404


def test_the_timeline_requires_authentication(patient):
    anon = TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"})
    r = anon.get(f"/api/{HOSP}/encounters/{patient}/timeline")
    assert r.status_code in (401, 403)


# ── What lands on it ─────────────────────────────────────────────────────────

def test_a_clinician_decision_is_recorded_as_an_event(client, patient):
    r = client.post(f"/api/{HOSP}/ai-override", json={
        "purpose": "differential", "patient_id": patient,
        "model_name": "differential", "decision": "rejected",
        "notes": "not consistent with the exam",
    })
    assert r.status_code == 200

    entries = client.get(f"/api/{HOSP}/encounters/{patient}/timeline").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["model"] == "event"
    assert entries[0]["output"]["decision"] == "rejected"


def test_an_event_needs_no_uncertainty(client, patient):
    """"The clinician rejected it" is something that happened, not a prediction,
    and has no coverage rate. The ledger exempts events for that reason and this
    asserts the exemption is actually reachable through the API."""
    client.post(f"/api/{HOSP}/ai-override", json={
        "purpose": "differential", "patient_id": patient,
            "model_name": "differential", "decision": "accepted",
    })
    entries = client.get(f"/api/{HOSP}/encounters/{patient}/timeline").json()["entries"]
    assert entries[0]["uncertainty"] is None


def test_decisions_accumulate_in_order(client, patient):
    for decision in ("accepted", "edited", "rejected"):
        client.post(f"/api/{HOSP}/ai-override", json={
            "purpose": "differential", "patient_id": patient,
            "model_name": "differential", "decision": decision,
        })
    entries = client.get(f"/api/{HOSP}/encounters/{patient}/timeline").json()["entries"]
    assert [e["seq"] for e in entries] == [1, 2, 3]
    assert [e["output"]["decision"] for e in entries] == ["accepted", "edited", "rejected"]


# ── Verification is the point ────────────────────────────────────────────────

def test_the_response_reports_whether_the_chain_holds(client, patient):
    client.post(f"/api/{HOSP}/ai-override", json={
        "purpose": "differential", "patient_id": patient,
            "model_name": "differential", "decision": "accepted",
    })
    body = client.get(f"/api/{HOSP}/encounters/{patient}/timeline").json()
    assert body["verified"] is True
    assert body["checked"] == 1


def test_a_tampered_timeline_reports_itself_as_broken(client, patient):
    """The property that makes the record worth anything to somebody who does
    not trust us."""
    for _ in range(3):
        client.post(f"/api/{HOSP}/ai-override", json={
            "purpose": "differential", "patient_id": patient,
            "model_name": "differential", "decision": "accepted",
        })
    ledger._tamper_for_tests(patient, 2, output={"decision": "rejected"})

    body = client.get(f"/api/{HOSP}/encounters/{patient}/timeline").json()
    assert body["verified"] is False
    assert body["broken_at"] == 2


def test_the_verify_endpoint_answers_on_its_own(client, patient):
    """A cheap endpoint an auditor or a monitor can poll without pulling the
    whole record, which for a long stay is a lot of PHI to move around."""
    client.post(f"/api/{HOSP}/ai-override", json={
        "purpose": "differential", "patient_id": patient,
            "model_name": "differential", "decision": "accepted",
    })
    r = client.get(f"/api/{HOSP}/encounters/{patient}/verify")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["checked"] == 1
    assert "entries" not in body, "verify should not return the record itself"


def test_reading_the_timeline_is_audited(client, patient, monkeypatch):
    """Reading a full decision history is a PHI access like any other."""
    recorded = []
    from lib import audit
    monkeypatch.setattr(audit, "record", lambda **kw: recorded.append(kw))
    client.get(f"/api/{HOSP}/encounters/{patient}/timeline")
    assert any("timeline" in str(r.get("action", "")) for r in recorded)


# ── The coverage-provenance finding ──────────────────────────────────────────

def test_a_model_entry_states_where_its_coverage_figure_came_from():
    """Wiring the ledger up surfaced that the artifacts never stored the
    calibration target, so every conformal set this product has produced had an
    unrecorded coverage level. Recording 0.9 as though it were measured would
    make the ledger say something we do not know."""
    from datetime import datetime, timezone

    entry = ledger.record(
        encounter_id="enc-cov", model="triage_ml", model_version="v7",
        observed_at=datetime.now(timezone.utc),
        output={"esi_level": 2},
        uncertainty={"coverage": 0.9, "coverage_source": "declared_default",
                     "conformal_set": [2, 3]},
    )
    assert entry.uncertainty["coverage_source"] == "declared_default"


def test_a_bare_prediction_is_still_refused():
    """The rule the whole ledger rests on, checked after the wiring."""
    from datetime import datetime, timezone

    with pytest.raises(ledger.MissingUncertainty):
        ledger.record(
            encounter_id="enc-bare", model="triage_ml", model_version="v7",
            observed_at=datetime.now(timezone.utc), output={"esi_level": 2},
        )
