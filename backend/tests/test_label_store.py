"""Active-learning LABEL STORE (backend/lib/label_store.py).

Covers:
  - local-mode capture -> list -> recalibrate round-trip, with triage_ml monkeypatched
    so no LightGBM artifacts or AWS are touched;
  - storage.put_label is a no-op in local mode (no boto, list_labels returns []);
  - provenance.record_override backward-compat: existing callers (no corrected_esi) are
    unaffected and capture NOTHING; an edited/rejected override WITH a corrected ESI fans
    out to label_store.capture_label; a label-capture failure never breaks record_override;
  - SEC-002: no patient_id / clinician_id / notes / feature vectors / probabilities in logs.
"""
from __future__ import annotations

import logging
import os

# Force local mode BEFORE importing config/app.
os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import label_store, provenance  # noqa: E402
from db import storage  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset in-memory label + override logs and force local mode for each test."""
    original_mode = settings.solace_mode
    settings.solace_mode = "local"
    label_store._LABELS.clear()
    provenance._OVERRIDES.clear()
    yield
    label_store._LABELS.clear()
    provenance._OVERRIDES.clear()
    settings.solace_mode = original_mode


# ---- Local-mode capture -> list -> recalibrate round-trip ---------------------------
def test_capture_then_list_round_trip():
    res = label_store.capture_label(
        hospital_id="hosp-a",
        patient_id="p-1",
        clinician_id="c-1",
        confirmed_esi=2,
        probabilities={"1": 0.1, "2": 0.2, "3": 0.4, "4": 0.2, "5": 0.1},
        model_source="lightgbm-v3",
    )
    assert res["captured"] is True
    rows = label_store.list_labels("hosp-a")
    assert len(rows) == 1
    assert rows[0]["confirmed_esi"] == 2
    assert rows[0]["hospital_id"] == "hosp-a"


def test_capture_rejects_invalid_esi():
    assert label_store.capture_label(
        hospital_id="hosp-a", patient_id="p", clinician_id="c",
        confirmed_esi=7, probabilities={"1": 1.0},
    )["captured"] is False
    assert label_store.list_labels("hosp-a") == []


def test_capture_rejects_empty_features():
    """A label with neither probabilities nor a feature vector is useless."""
    res = label_store.capture_label(
        hospital_id="hosp-a", patient_id="p", clinician_id="c", confirmed_esi=3,
    )
    assert res["captured"] is False
    assert res["reason"] == "no_features"
    assert label_store.list_labels("hosp-a") == []


def test_list_labels_is_tenant_scoped():
    label_store.capture_label(
        hospital_id="hosp-a", patient_id="p", clinician_id="c",
        confirmed_esi=2, probabilities={"1": 0.1, "2": 0.9, "3": 0, "4": 0, "5": 0},
    )
    label_store.capture_label(
        hospital_id="hosp-b", patient_id="p", clinician_id="c",
        confirmed_esi=4, probabilities={"1": 0, "2": 0, "3": 0, "4": 0.9, "5": 0.1},
    )
    assert len(label_store.list_labels("hosp-a")) == 1
    assert len(label_store.list_labels("hosp-b")) == 1
    assert label_store.list_labels("hosp-a")[0]["confirmed_esi"] == 2


def test_recalibrate_maps_labels_to_outcomes(monkeypatch):
    """recalibrate pulls stored labels, maps them, and calls triage_ml with the batch."""
    label_store.capture_label(
        hospital_id="hosp-a", patient_id="p1", clinician_id="c",
        confirmed_esi=2, probabilities={"1": 0.1, "2": 0.7, "3": 0.1, "4": 0.05, "5": 0.05},
    )
    label_store.capture_label(
        hospital_id="hosp-a", patient_id="p2", clinician_id="c",
        confirmed_esi=4, feature_vector={"age": 70, "spo2": 88},
    )
    # A different hospital's label must NOT leak into hosp-a's recalibration.
    label_store.capture_label(
        hospital_id="hosp-b", patient_id="p3", clinician_id="c",
        confirmed_esi=1, probabilities={"1": 0.9, "2": 0.1, "3": 0, "4": 0, "5": 0},
    )

    captured = {}

    def _fake_recal(outcomes, *, alpha=0.10, weights=None):
        captured["outcomes"] = outcomes
        captured["alpha"] = alpha
        return {"updated": True, "n_outcomes_used": len(outcomes)}

    import services.triage_ml as triage_ml  # noqa: PLC0415
    monkeypatch.setattr(triage_ml, "recalibrate_from_outcomes", _fake_recal)

    summary = label_store.recalibrate("hosp-a", alpha=0.05)

    assert captured["alpha"] == 0.05
    # Two hosp-a labels mapped; hosp-b excluded.
    assert len(captured["outcomes"]) == 2
    # probabilities label -> {"confirmed_esi", "probabilities"}
    assert captured["outcomes"][0]["confirmed_esi"] == 2
    assert "probabilities" in captured["outcomes"][0]
    # feature_vector label -> {"confirmed_esi", "patient"} for re-inference
    assert captured["outcomes"][1]["confirmed_esi"] == 4
    assert captured["outcomes"][1]["patient"] == {"age": 70, "spo2": 88}
    assert summary["updated"] is True
    assert summary["n_labels"] == 2
    assert summary["n_outcomes_mapped"] == 2


def test_recalibrate_with_no_labels_is_safe(monkeypatch):
    """No labels yet -> still calls triage_ml (which no-ops gracefully)."""
    seen = {}

    def _fake_recal(outcomes, *, alpha=0.10, weights=None):
        seen["n"] = len(outcomes)
        return {"updated": False, "reason": "no_usable_outcomes"}

    import services.triage_ml as triage_ml  # noqa: PLC0415
    monkeypatch.setattr(triage_ml, "recalibrate_from_outcomes", _fake_recal)

    summary = label_store.recalibrate("hosp-empty")
    assert seen["n"] == 0
    assert summary["n_labels"] == 0
    assert summary["updated"] is False


# ---- storage.put_label no-op in local mode -----------------------------------------
def test_local_put_label_is_noop(monkeypatch):
    """storage.put_label must not call boto in local mode; list_labels returns []."""
    called = {"boto": False}

    def _boom(_name):
        called["boto"] = True
        raise AssertionError("boto must not be touched in local mode")

    monkeypatch.setattr(storage, "_boto_table", _boom)
    storage.put_label({"hospital_id": "hosp-a", "confirmed_esi": 2})
    assert called["boto"] is False
    assert storage.list_labels("hosp-a") == []


# ---- AWS mode-branch: capture fans out to storage (storage mocked, no AWS) ----------
def test_aws_capture_fans_out_to_storage(monkeypatch):
    settings.solace_mode = "aws"
    captured: list[dict] = []
    monkeypatch.setattr(storage, "put_label", lambda entry: captured.append(entry))

    label_store.capture_label(
        hospital_id="hosp-a", patient_id="p", clinician_id="c",
        confirmed_esi=3, probabilities={"1": 0, "2": 0, "3": 1.0, "4": 0, "5": 0},
    )
    assert len(captured) == 1
    assert captured[0]["confirmed_esi"] == 3
    # in-memory warm cache still got the append
    assert len(label_store._LABELS) == 1


def test_aws_capture_durable_failure_does_not_raise(monkeypatch):
    settings.solace_mode = "aws"

    def _boom(entry):
        raise RuntimeError("DDB down")

    monkeypatch.setattr(storage, "put_label", _boom)
    res = label_store.capture_label(
        hospital_id="hosp-a", patient_id="p", clinician_id="c",
        confirmed_esi=2, probabilities={"1": 0.1, "2": 0.9, "3": 0, "4": 0, "5": 0},
    )
    # Capture still "succeeds" from the caller's view; warm cache holds it.
    assert res["captured"] is True
    assert len(label_store._LABELS) == 1


# ---- provenance.record_override backward-compat + label wiring ----------------------
def test_record_override_backward_compat_no_capture(monkeypatch):
    """Existing callers (no corrected_esi) must capture NOTHING and not error."""
    spy = {"calls": 0}
    monkeypatch.setattr(
        label_store, "capture_label",
        lambda **kw: spy.__setitem__("calls", spy["calls"] + 1),
    )
    # Original signature — unchanged.
    provenance.record_override(
        purpose="scribe", model_name="m", decision="edited",
        clinician_id="c", patient_id="p", hospital_id="hosp-a", diff_chars=10,
    )
    assert spy["calls"] == 0
    # The override itself still recorded.
    assert len(provenance._OVERRIDES) == 1


def test_record_override_accepted_does_not_capture(monkeypatch):
    """An 'accepted' decision is agreement — not a correction — so no label even if ESI present."""
    spy = {"calls": 0}
    monkeypatch.setattr(
        label_store, "capture_label",
        lambda **kw: spy.__setitem__("calls", spy["calls"] + 1),
    )
    provenance.record_override(
        purpose="triage", model_name="m", decision="accepted",
        clinician_id="c", patient_id="p", hospital_id="hosp-a", corrected_esi=2,
    )
    assert spy["calls"] == 0


def test_record_override_edited_with_corrected_esi_captures():
    provenance.record_override(
        purpose="triage", model_name="lightgbm-v3", decision="edited",
        clinician_id="c-1", patient_id="p-1", hospital_id="hosp-a",
        corrected_esi=2,
        probabilities={"1": 0.1, "2": 0.2, "3": 0.4, "4": 0.2, "5": 0.1},
    )
    rows = label_store.list_labels("hosp-a")
    assert len(rows) == 1
    assert rows[0]["confirmed_esi"] == 2
    assert rows[0]["model_source"] == "lightgbm-v3"


def test_record_override_capture_failure_does_not_break(monkeypatch):
    """A label-capture exception must never break record_override or the request."""
    def _boom(**kw):
        raise RuntimeError("label store down")

    monkeypatch.setattr(label_store, "capture_label", _boom)
    # Should not raise.
    provenance.record_override(
        purpose="triage", model_name="m", decision="rejected",
        clinician_id="c", patient_id="p", hospital_id="hosp-a", corrected_esi=1,
    )
    # Override still recorded despite capture failure.
    assert len(provenance._OVERRIDES) == 1


# ---- SEC-002: no PHI in logs --------------------------------------------------------
def test_no_phi_in_capture_logs(caplog):
    with caplog.at_level(logging.INFO):
        label_store.capture_label(
            hospital_id="hosp-a",
            patient_id="patient-uuid-secret",
            clinician_id="dr-secret",
            confirmed_esi=2,
            probabilities={"1": 0.1, "2": 0.9, "3": 0, "4": 0, "5": 0},
            feature_vector={"age": 70, "spo2": 88},
            notes="patient mentioned chest pain radiating to left arm",
        )
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "hosp-a" in text  # hospital_id IS allowed
    assert "patient-uuid-secret" not in text
    assert "dr-secret" not in text
    assert "chest pain" not in text
    assert "spo2" not in text
    assert "0.9" not in text


def test_no_phi_in_recalibrate_logs(monkeypatch, caplog):
    label_store.capture_label(
        hospital_id="hosp-a", patient_id="patient-uuid-secret",
        clinician_id="dr-secret", confirmed_esi=2,
        probabilities={"1": 0.1, "2": 0.9, "3": 0, "4": 0, "5": 0},
    )
    import services.triage_ml as triage_ml  # noqa: PLC0415
    monkeypatch.setattr(
        triage_ml, "recalibrate_from_outcomes",
        lambda outcomes, *, alpha=0.10, weights=None: {"updated": True},
    )
    with caplog.at_level(logging.INFO):
        label_store.recalibrate("hosp-a")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "hosp-a" in text
    assert "patient-uuid-secret" not in text
    assert "dr-secret" not in text
