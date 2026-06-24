"""Durable AI-override / provenance log (HTI-1 transparency metrics).

Covers:
  - local-mode round-trip: record_override -> overrides()/metrics() via the
    in-memory list, and that storage.put_override is a no-op locally;
  - the AWS mode-branch logic, with db.storage mocked so no boto3 / AWS is touched:
    record_override fans out to storage.put_override, and overrides() reads back
    from storage.list_overrides for a scoped hospital_id.
"""
from __future__ import annotations

import os

# Force local mode BEFORE importing config/app.
os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import provenance  # noqa: E402
from db import storage  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset the in-memory override log and force local mode for each test."""
    original_mode = settings.solace_mode
    settings.solace_mode = "local"
    provenance._OVERRIDES.clear()
    yield
    provenance._OVERRIDES.clear()
    settings.solace_mode = original_mode


# ---- Local-mode round-trip ----------------------------------------------------------
def test_local_round_trip_in_memory():
    provenance.record_override(
        purpose="scribe",
        model_name="claude-sonnet-4-5",
        decision="accepted",
        clinician_id="c-1",
        patient_id="p-1",
        hospital_id="hosp-a",
    )
    provenance.record_override(
        purpose="scribe",
        model_name="claude-sonnet-4-5",
        decision="edited",
        clinician_id="c-1",
        patient_id="p-2",
        hospital_id="hosp-a",
        diff_chars=12,
    )
    rows = provenance.overrides("hosp-a")
    assert len(rows) == 2
    assert {r["decision"] for r in rows} == {"accepted", "edited"}
    assert all(r["hospital_id"] == "hosp-a" for r in rows)


def test_local_overrides_filters_by_hospital():
    provenance.record_override(
        purpose="ddx", model_name="m", decision="accepted",
        clinician_id="c", patient_id="p", hospital_id="hosp-a",
    )
    provenance.record_override(
        purpose="ddx", model_name="m", decision="rejected",
        clinician_id="c", patient_id="p", hospital_id="hosp-b",
    )
    assert len(provenance.overrides("hosp-a")) == 1
    assert len(provenance.overrides("hosp-b")) == 1
    assert len(provenance.overrides(None)) == 2  # unscoped aggregate


def test_local_metrics_accept_rate():
    for decision in ("accepted", "accepted", "edited", "rejected"):
        provenance.record_override(
            purpose="coding", model_name="m", decision=decision,
            clinician_id="c", patient_id="p", hospital_id="hosp-a",
        )
    summary = provenance.metrics("hosp-a")
    assert summary["coding"]["total"] == 4
    assert summary["coding"]["accept_rate"] == 0.5
    assert summary["coding"]["edit_rate"] == 0.25
    assert summary["coding"]["reject_rate"] == 0.25


def test_local_put_override_is_noop(monkeypatch):
    """storage.put_override must not call boto in local mode."""
    called = {"boto": False}

    def _boom(_name):
        called["boto"] = True
        raise AssertionError("boto must not be touched in local mode")

    monkeypatch.setattr(storage, "_boto_table", _boom)
    storage.put_override({"hospital_id": "hosp-a", "decision": "accepted"})
    assert called["boto"] is False
    assert storage.list_overrides("hosp-a") == []


# ---- AWS mode-branch logic (storage mocked — no AWS) --------------------------------
def test_aws_record_override_fans_out_to_storage(monkeypatch):
    settings.solace_mode = "aws"
    captured: list[dict] = []
    monkeypatch.setattr(storage, "put_override", lambda entry: captured.append(entry))

    provenance.record_override(
        purpose="scribe", model_name="m", decision="accepted",
        clinician_id="c-1", patient_id="p-1", hospital_id="hosp-a",
    )
    # Durable write happened with the full entry...
    assert len(captured) == 1
    assert captured[0]["hospital_id"] == "hosp-a"
    assert captured[0]["decision"] == "accepted"
    # ...and the in-memory warm cache still got the append.
    assert len(provenance._OVERRIDES) == 1


def test_aws_overrides_reads_from_storage(monkeypatch):
    settings.solace_mode = "aws"
    durable = [
        {"ts": "2026-05-30T00:00:01Z", "hospital_id": "hosp-a",
         "purpose": "scribe", "decision": "accepted"},
        {"ts": "2026-05-30T00:00:02Z", "hospital_id": "hosp-a",
         "purpose": "scribe", "decision": "edited"},
    ]

    def _list(hospital_id, *, limit=200):
        assert hospital_id == "hosp-a"
        return list(durable)

    monkeypatch.setattr(storage, "list_overrides", _list)
    rows = provenance.overrides("hosp-a")
    assert len(rows) == 2
    # Sorted oldest-first to match local ordering.
    assert rows[0]["decision"] == "accepted"
    assert rows[1]["decision"] == "edited"


def test_aws_overrides_falls_back_to_memory_when_storage_empty(monkeypatch):
    settings.solace_mode = "aws"
    # In-memory warm cache holds a record the (empty) durable store doesn't return yet.
    provenance.record_override(
        purpose="ddx", model_name="m", decision="rejected",
        clinician_id="c", patient_id="p", hospital_id="hosp-a",
    )
    monkeypatch.setattr(storage, "put_override", lambda entry: None)
    monkeypatch.setattr(storage, "list_overrides", lambda hospital_id, *, limit=200: [])
    rows = provenance.overrides("hosp-a")
    assert len(rows) == 1
    assert rows[0]["decision"] == "rejected"


def test_aws_unscoped_overrides_use_memory(monkeypatch):
    """Unscoped (hospital_id=None) reads can't query the partitioned table; use memory."""
    settings.solace_mode = "aws"

    def _boom(*a, **k):
        raise AssertionError("list_overrides must not be called for unscoped reads")

    monkeypatch.setattr(storage, "put_override", lambda entry: None)
    monkeypatch.setattr(storage, "list_overrides", _boom)
    provenance.record_override(
        purpose="ddx", model_name="m", decision="accepted",
        clinician_id="c", patient_id="p", hospital_id="hosp-a",
    )
    rows = provenance.overrides(None)
    assert len(rows) == 1


def test_aws_storage_failure_does_not_break_record(monkeypatch):
    """A durable-write failure must not raise — the request keeps moving."""
    settings.solace_mode = "aws"

    def _boom(entry):
        raise RuntimeError("DDB down")

    monkeypatch.setattr(storage, "put_override", _boom)
    # Should not raise.
    provenance.record_override(
        purpose="scribe", model_name="m", decision="accepted",
        clinician_id="c", patient_id="p", hospital_id="hosp-a",
    )
    assert len(provenance._OVERRIDES) == 1
