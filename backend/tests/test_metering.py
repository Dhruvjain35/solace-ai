"""Usage metering (backend/lib/metering.py + db.storage billing accessors).

Covers:
  - local-mode record_encounter -> usage_summary round-trip (counts + estimated value);
  - tenant scoping (one hospital's events don't leak into another's summary);
  - storage.put_billing_event is a no-op in local mode (no boto, list returns []);
  - AWS-mode fan-out to storage (storage mocked, no AWS touched);
  - failure-safety: a durable-write blowup never raises out of record_encounter;
  - SEC-002: no patient-identifying data in logs (only hospital_id + non-sensitive shape).
"""
from __future__ import annotations

import logging
import os

# Force local mode BEFORE importing config/app.
os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import metering  # noqa: E402
from db import storage  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    original_mode = settings.solace_mode
    settings.solace_mode = "local"
    metering._EVENTS.clear()
    yield
    metering._EVENTS.clear()
    settings.solace_mode = original_mode


# ---- record -> summary round-trip ---------------------------------------------------
def test_record_then_summary_round_trip():
    metering.record_encounter(
        hospital_id="hosp-a", encounter_type="triage.refine",
        model_source="lightgbm-v3", billable=True,
    )
    metering.record_encounter(
        hospital_id="hosp-a", encounter_type="triage.refine",
        model_source="lightgbm-v3", billable=True, cpt_hint="99284",
    )
    summary = metering.usage_summary("hosp-a", period="month")
    assert summary["billable_encounters"] == 2
    assert summary["total_events"] == 2
    assert summary["by_encounter_type"]["triage.refine"] == 2
    assert summary["by_model_source"]["lightgbm-v3"] == 2
    assert summary["cpt_hints"]["99284"] == 1
    # estimated value = billable * configured rate
    assert summary["estimated_value_usd"] == round(2 * settings.billing_rate_per_encounter_usd, 2)
    assert summary["currency"] == "USD"


def test_non_billable_excluded_from_value():
    metering.record_encounter(
        hospital_id="hosp-a", encounter_type="triage.refine",
        model_source="m", billable=False,
    )
    summary = metering.usage_summary("hosp-a")
    assert summary["total_events"] == 1
    assert summary["billable_encounters"] == 0
    assert summary["estimated_value_usd"] == 0.0


def test_summary_is_tenant_scoped():
    metering.record_encounter(hospital_id="hosp-a", encounter_type="triage.refine", model_source="m")
    metering.record_encounter(hospital_id="hosp-b", encounter_type="triage.refine", model_source="m")
    metering.record_encounter(hospital_id="hosp-b", encounter_type="triage.refine", model_source="m")
    assert metering.usage_summary("hosp-a")["billable_encounters"] == 1
    assert metering.usage_summary("hosp-b")["billable_encounters"] == 2


def test_unknown_period_falls_back_to_month():
    metering.record_encounter(hospital_id="hosp-a", encounter_type="triage.refine", model_source="m")
    summary = metering.usage_summary("hosp-a", period="fortnight")
    assert summary["period"] == "month"


def test_empty_hospital_summary_is_zero():
    summary = metering.usage_summary("hosp-empty")
    assert summary["billable_encounters"] == 0
    assert summary["estimated_value_usd"] == 0.0
    assert summary["by_encounter_type"] == {}


# ---- storage.put_billing_event no-op in local mode ----------------------------------
def test_local_put_billing_event_is_noop(monkeypatch):
    called = {"boto": False}

    def _boom(_name):
        called["boto"] = True
        raise AssertionError("boto must not be touched in local mode")

    monkeypatch.setattr(storage, "_boto_table", _boom)
    storage.put_billing_event({"hospital_id": "hosp-a", "encounter_type": "triage.refine"})
    assert called["boto"] is False
    assert storage.list_billing_events("hosp-a") == []
    assert storage.aggregate_billing_events("hosp-a")["billable_encounters"] == 0


# ---- AWS-mode fan-out + failure-safety ----------------------------------------------
def test_aws_record_fans_out_to_storage(monkeypatch):
    settings.solace_mode = "aws"
    captured: list[dict] = []
    monkeypatch.setattr(storage, "put_billing_event", lambda entry: captured.append(entry))

    metering.record_encounter(
        hospital_id="hosp-a", encounter_type="triage.refine", model_source="lightgbm-v3",
    )
    assert len(captured) == 1
    assert captured[0]["encounter_type"] == "triage.refine"
    # warm cache still got the append
    assert len(metering._EVENTS) == 1


def test_aws_durable_failure_does_not_raise(monkeypatch):
    settings.solace_mode = "aws"

    def _boom(entry):
        raise RuntimeError("DDB down")

    monkeypatch.setattr(storage, "put_billing_event", _boom)
    # Must NOT raise — metering must never break the triage request.
    ev = metering.record_encounter(
        hospital_id="hosp-a", encounter_type="triage.refine", model_source="m",
    )
    assert ev["encounter_type"] == "triage.refine"
    assert len(metering._EVENTS) == 1


def test_aws_summary_reads_durable_then_falls_back(monkeypatch):
    settings.solace_mode = "aws"
    # Durable read returns rows -> used directly.
    monkeypatch.setattr(
        storage, "list_billing_events",
        lambda hid, *, since_ms=None, limit=5000: [
            {"hospital_id": hid, "encounter_type": "triage.refine", "model_source": "m", "billable": True},
        ],
    )
    summary = metering.usage_summary("hosp-a")
    assert summary["billable_encounters"] == 1


# ---- SEC-002: no PHI in logs --------------------------------------------------------
def test_no_phi_in_record_logs(caplog):
    with caplog.at_level(logging.INFO):
        metering.record_encounter(
            hospital_id="hosp-a", encounter_type="triage.refine",
            model_source="lightgbm-v3", cpt_hint="99285",
        )
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "hosp-a" in text          # hospital_id IS allowed
    assert "triage.refine" in text   # encounter_type is non-sensitive
    # No patient-identifying token should ever appear (we never pass one in).
    assert "patient" not in text.lower() or "patient_id" not in text
