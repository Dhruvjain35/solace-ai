"""Tests for the public Solace Trust Report endpoint.

The Trust Report is PUBLIC-FACING. These tests enforce the two hard constraints:

  1. NO PHI / per-record data ever reaches the payload — no patient_id,
     clinician_id, free-text notes, or raw override entries, at any depth.
  2. HONEST LABELING — calibration is from a SYNTHETIC validation cohort and the
     payload says so (preliminary flag + synthetic-cohort provenance + a
     disclaimer that does NOT claim real-world clinical calibration).
"""
from __future__ import annotations

import json
import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib import provenance  # noqa: E402
from main import app  # noqa: E402

# Substrings that must never appear anywhere in a public payload.
_FORBIDDEN_KEYS = {"patient_id", "clinician_id", "notes", "entries", "diff_chars"}


@pytest.fixture
def client():
    return TestClient(app)


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def test_trust_report_returns_aggregate_shape(client):
    resp = client.get("/api/governance/trust-report")
    assert resp.status_code == 200
    body = resp.json()

    # Top-level sections present.
    for section in (
        "model_inventory",
        "calibration",
        "fairness",
        "override_acceptance",
    ):
        assert section in body, f"missing section: {section}"

    # Model inventory is a count + list, not raw records.
    assert body["model_inventory"]["count"] >= 1
    assert isinstance(body["model_inventory"]["models"], list)

    # Override acceptance is aggregate-only: totals + rate dict, NO entries list.
    oa = body["override_acceptance"]
    assert "total_decisions" in oa
    assert "by_purpose" in oa
    assert "entries" not in oa


def test_trust_report_has_honest_synthetic_labeling(client):
    body = client.get("/api/governance/trust-report").json()

    # Top-level honesty flags.
    assert body["preliminary"] is True
    assert body["data_provenance"] == "synthetic validation cohort"
    assert "disclaimer" in body and body["disclaimer"]

    # Calibration block is explicitly tagged synthetic and NOT real-clinical.
    cal = body["calibration"]
    assert cal["provenance"] == "synthetic validation cohort"
    assert cal["labels_are_real_clinical_outcomes"] is False

    # The disclaimer must NOT overclaim real-world clinical calibration.
    disclaimer = body["disclaimer"].lower()
    assert "synthetic" in disclaimer
    # Defensive: it must not assert real-world clinical calibration as fact.
    assert "real-world clinical calibration" not in disclaimer.replace(
        "not a claim of real-world clinical calibration", ""
    ).replace("not", "")


def test_trust_report_contains_no_phi_keys(client):
    body = client.get("/api/governance/trust-report").json()
    all_keys = set(_walk_keys(body))
    leaked = _FORBIDDEN_KEYS & all_keys
    assert not leaked, f"PHI / per-record keys leaked into public payload: {sorted(leaked)}"


def test_trust_report_does_not_leak_override_record_values(client):
    """Even after a real override with PHI-ish values is recorded, the public
    report must surface only aggregate rates — never the raw entry values."""
    provenance.record_override(
        purpose="scribe",
        model_name="claude-sonnet-4-5",
        decision="edited",
        clinician_id="dr-leak-canary-clinician",
        patient_id="patient-leak-canary-id",
        hospital_id="demo",
        diff_chars=42,
        notes="leak-canary-free-text-phi-note",
    )
    raw = client.get("/api/governance/trust-report").text

    # The aggregate count moved, proving the data flowed through metrics()...
    body = json.loads(raw)
    assert body["override_acceptance"]["total_decisions"] >= 1

    # ...but none of the per-record canary values are in the serialized payload.
    for canary in (
        "dr-leak-canary-clinician",
        "patient-leak-canary-id",
        "leak-canary-free-text-phi-note",
    ):
        assert canary not in raw, f"per-record value leaked: {canary}"


def test_trust_report_conformal_block_when_model_present(client):
    """When the ML artifact loads, per-ESI q̂ and coverage are present and tagged
    synthetic; when it does not, the block degrades gracefully (status field)."""
    cal = client.get("/api/governance/trust-report").json()["calibration"]
    assert cal["status"] in {"available", "unavailable"}
    assert cal["method"] == "mondrian_class_conditional_split_conformal"
    if cal["status"] == "available":
        assert cal["target_coverage"] is not None
        assert cal["q_hat_by_esi"] is not None
        # Coverage, if computed, is flagged as synthetic in-sample.
        if cal["empirical_coverage"] is not None:
            assert cal["empirical_coverage"]["evaluation"] == "in_sample_synthetic"
