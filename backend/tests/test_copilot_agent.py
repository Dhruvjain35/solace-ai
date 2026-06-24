"""Copilot Agent loop tests — contract shape, PHI isolation, bounded rounds.

The model is ALWAYS stubbed (never a real Claude call). Every payload bound for
``claude.messages_create`` is captured and scanned for PHI tokens, extending the
copilot leak gate (tests/services/test_copilot_phi_isolation.py) to the agent
tool loop: the raw patient name / drug strings must never reach the model.
"""
from __future__ import annotations

import json
import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db import storage  # noqa: E402
from lib import claude  # noqa: E402
from lib.auth import require_clinician  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from services.copilot import agent, executor  # noqa: E402

HOSP = "h1"
PID = "p1"
URL = f"/api/{HOSP}/patients/{PID}/copilot/agent"

PHI_NAME = "Marcus Welby"
PHI_TOKENS = ["marcus", "welby", "warfarin", "metoprolol", "penicillin"]

_PATIENT = {
    "patient_id": PID,
    "hospital_id": HOSP,
    "consent_granted_at": "2024-03-15T10:00:00Z",
    "consent_version": "v1",
    "name": PHI_NAME,
    "chief_complaint": "chest pain radiating to the left arm",
    "transcript": f"{PHI_NAME} reports crushing chest pain for two hours.",
    "esi_level": 2,
    "vitals": {"abnormal": True},
    "medical_info": json.dumps({
        "age": 67, "sex": "male",
        "conditions": ["atrial fibrillation", "hypertension"],
        "medications": ["warfarin 5mg", "metoprolol 50mg"],
        "allergies": ["penicillin"],
    }),
}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    settings.solace_mode = "local"
    storage._reset_for_tests()
    app.dependency_overrides[require_clinician] = lambda: {
        "clinician_id": "tester", "hospital_id": HOSP,
        "name": "Tester", "role": "clinician", "auth_method": "jwt",
    }
    monkeypatch.setattr(claude, "available", lambda: True)
    monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(_PATIENT))
    monkeypatch.setattr(executor, "_crawl_ehr", lambda ctx: None)
    yield
    storage._reset_for_tests()
    app.dependency_overrides.pop(require_clinician, None)


def _scripted(monkeypatch, responses):
    """Stub claude.messages_create with a scripted list of Responses; capture
    every model-bound payload for the PHI leak assertion."""
    payloads: list[dict] = []
    it = iter(responses)

    def fake_create(*, model, max_tokens, system="", messages, purpose, **kw):
        payloads.append({"purpose": purpose, "model": model,
                         "system": system, "messages": messages})
        return next(it)

    monkeypatch.setattr(claude, "messages_create", fake_create)
    return payloads


def _assert_no_phi(payloads):
    assert payloads, "no model calls were captured"
    for p in payloads:
        blob = (p["system"] + json.dumps(p["messages"], default=str)).lower()
        for tok in PHI_TOKENS:
            assert tok not in blob, (
                f"PHI token '{tok}' leaked into a {p['purpose']} model payload"
            )


def _tool_round(name, tool_input, tid="tu1"):
    return claude.Response(content=[
        claude.ToolUseBlock(id=tid, name=name, input=tool_input)])


def _text_round(text):
    return claude.Response(content=[claude.TextBlock(text=text)])


# ---- auth + consent gates ------------------------------------------------------

def test_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")
    app.dependency_overrides[require_clinician] = _reject
    r = client.post(URL, json={"message": "hi", "history": []})
    assert r.status_code == 401


def test_missing_consent_is_403(client, monkeypatch):
    no_consent = {k: v for k, v in _PATIENT.items()
                  if k not in ("consent_granted_at", "consent_version")}
    monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(no_consent))
    calls = _scripted(monkeypatch, [])  # any model call would raise StopIteration
    r = client.post(URL, json={"message": "summarize", "history": []})
    assert r.status_code == 403
    assert calls == [], "model was called despite missing consent (SEC-004)"


def test_cross_hospital_patient_is_404(client, monkeypatch):
    other = dict(_PATIENT, hospital_id="other-hospital")
    monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(other))
    _scripted(monkeypatch, [])
    r = client.post(URL, json={"message": "summarize", "history": []})
    assert r.status_code == 404


# ---- the happy path: read tool -> slot-filled reply -----------------------------

def test_read_chart_round_trip_and_slot_fill(client, monkeypatch):
    payloads = _scripted(monkeypatch, [
        _tool_round("read_chart",
                    {"primitive": "feature.flag", "params": {"name": "on_anticoagulant"}}),
        _text_round("**Yes** — the patient is on an anticoagulant: {S1}."),
    ])
    r = client.post(URL, json={"message": "Is the patient on blood thinners?",
                               "history": []})
    assert r.status_code == 200
    d = r.json()

    # Contract shape
    assert set(d) == {"reply", "proposed_actions", "events", "usage"}
    assert d["proposed_actions"] == []
    assert d["usage"]["rounds"] == 2
    assert d["usage"]["input_tokens"] > 0 and d["usage"]["output_tokens"] > 0

    # Slots are filled AFTER the loop, for the clinician only.
    assert "warfarin 5mg" in d["reply"]
    assert "{S1}" not in d["reply"]

    # ...but the model itself never saw the raw value.
    _assert_no_phi(payloads)

    # Events: real timings, contract-exact keys/kinds.
    assert len(d["events"]) >= 3  # 2 think rounds + 1 fhir tool call
    for e in d["events"]:
        assert set(e) == {"kind", "label", "detail", "ms", "status"}
        assert e["kind"] in ("fhir", "think", "propose", "info")
        assert e["ms"] is None or isinstance(e["ms"], int)
        assert e["status"] in ("ok", "error", None)
    kinds = [e["kind"] for e in d["events"]]
    assert kinds.count("think") == 2
    fhir_events = [e for e in d["events"] if e["kind"] == "fhir"]
    assert any("feature.flag" in e["label"] for e in fhir_events)
    assert all(isinstance(e["ms"], int) for e in fhir_events)


def test_search_chart_tool_lists_primitives(client, monkeypatch):
    payloads = _scripted(monkeypatch, [
        _tool_round("search_chart", {"query": "interactions"}),
        _text_round("Use engine.drug_interactions."),
    ])
    r = client.post(URL, json={"message": "what can you check?", "history": []})
    assert r.status_code == 200
    # The tool result fed back to the model is the PHI-free catalog.
    tool_result_msg = payloads[1]["messages"][-1]
    content = json.loads(tool_result_msg["content"][0]["content"])
    assert any(p["primitive"] == "engine.drug_interactions"
               for p in content["primitives"])
    _assert_no_phi(payloads)


def test_invalid_primitive_param_is_rejected_not_executed(client, monkeypatch):
    # A smuggled non-vocab param must bounce off the gate as a tool error.
    payloads = _scripted(monkeypatch, [
        _tool_round("read_chart",
                    {"primitive": "feature.flag", "params": {"name": "totally_bogus_flag"}}),
        _text_round("Could not read that."),
    ])
    r = client.post(URL, json={"message": "check something", "history": []})
    assert r.status_code == 200
    fhir_events = [e for e in r.json()["events"] if e["kind"] == "fhir"]
    assert fhir_events and fhir_events[0]["status"] == "error"
    _assert_no_phi(payloads)


# ---- propose_write: collect-only ------------------------------------------------

def test_propose_write_collects_action(client, monkeypatch):
    resource = {"code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm",
                                     "code": "I10", "display": "Essential hypertension"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]}}
    payloads = _scripted(monkeypatch, [
        _tool_round("propose_write", {
            "resource_type": "Condition",
            "summary": "Add essential hypertension (I10) to the problem list",
            "resource": resource,
        }),
        _text_round("I've proposed adding hypertension — confirm to write it."),
    ])
    r = client.post(URL, json={"message": "add hypertension to the problem list",
                               "history": []})
    assert r.status_code == 200
    d = r.json()
    assert len(d["proposed_actions"]) == 1
    a = d["proposed_actions"][0]
    assert set(a) == {"id", "resource_type", "summary", "resource"}
    assert a["id"] == "a1"
    assert a["resource_type"] == "Condition"
    assert a["resource"]["resourceType"] == "Condition"
    assert "subject" not in a["resource"]  # attached server-side at execute time
    assert any(e["kind"] == "propose" and e["status"] == "ok" for e in d["events"])
    _assert_no_phi(payloads)


def test_propose_write_disallowed_type_is_refused(client, monkeypatch):
    _scripted(monkeypatch, [
        _tool_round("propose_write", {
            "resource_type": "Patient", "summary": "rewrite the patient",
            "resource": {"name": [{"family": "Hacked"}]},
        }),
        _text_round("That resource type is not allowed."),
    ])
    r = client.post(URL, json={"message": "edit the patient record", "history": []})
    assert r.status_code == 200
    d = r.json()
    assert d["proposed_actions"] == []
    assert any(e["kind"] == "propose" and e["status"] == "error" for e in d["events"])


# ---- loop bounds + history cap ---------------------------------------------------

def test_loop_is_bounded_at_five_rounds(client, monkeypatch):
    calls = {"n": 0}

    def endless(*, model, max_tokens, system="", messages, purpose, **kw):
        calls["n"] += 1
        return _tool_round("search_chart", {"query": "more"}, tid=f"tu{calls['n']}")

    monkeypatch.setattr(claude, "messages_create", endless)
    r = client.post(URL, json={"message": "loop forever", "history": []})
    assert r.status_code == 200
    d = r.json()
    assert calls["n"] == agent.MAX_ROUNDS == 5
    assert d["usage"]["rounds"] == 5
    assert d["reply"]  # non-empty fallback reply


def test_history_is_capped_at_twelve(client, monkeypatch):
    payloads = _scripted(monkeypatch, [_text_round("ok")])
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
               for i in range(20)]
    r = client.post(URL, json={"message": "final question", "history": history})
    assert r.status_code == 200
    msgs = payloads[0]["messages"]
    assert len(msgs) == 13  # 12 capped history turns + the new message
    assert msgs[-1]["content"] == "final question"
    assert msgs[0]["content"] == "turn 8"  # the OLDEST turns were dropped


def test_uses_utility_model_tier(client, monkeypatch):
    payloads = _scripted(monkeypatch, [_text_round("ok")])
    client.post(URL, json={"message": "hello", "history": []})
    assert payloads[0]["model"] == settings.model_utility


# ---- audit -----------------------------------------------------------------------

def test_agent_call_is_audited(client, monkeypatch):
    records = []
    monkeypatch.setattr("lib.audit.record", lambda **kw: records.append(kw))
    _scripted(monkeypatch, [_text_round("ok")])
    client.post(URL, json={"message": "hello", "history": []})
    actions = [r["action"] for r in records]
    assert "copilot.agent" in actions
    rec = next(r for r in records if r["action"] == "copilot.agent")
    assert rec["patient_id"] == PID
    assert rec["clinician_id"] == "tester"
