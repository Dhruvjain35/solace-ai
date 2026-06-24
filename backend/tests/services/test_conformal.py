"""Unit tests for Mondrian (class-conditional) conformal prediction.

Two layers:
  1. ``lib.conformal`` math in isolation (pure numpy, no model load) — fast,
     deterministic, exercises per-class q̂, empirical coverage, the weighted
     variant, and the non-empty-set guarantee.
  2. ``services.triage_ml`` integration — the loaded ensemble produces a
     per-class q̂ dict, and ``recalibrate_from_outcomes`` updates q̂ from
     clinician-confirmed labels. Skipped cleanly if ML artifacts/deps are
     not importable locally.
"""
from __future__ import annotations

import numpy as np
import pytest

conformal = pytest.importorskip("lib.conformal")


# ---------------------------------------------------------------------------
# Layer 1: pure conformal math
# ---------------------------------------------------------------------------
def _make_calibration(n_easy: int = 150, n_hard: int = 150, seed: int = 1):
    """A 5-class set where class 0 is easy (peaked) and class 2 is hard (diffuse)."""
    rng = np.random.default_rng(seed)
    probs, labels = [], []
    for _ in range(n_easy):
        probs.append(rng.dirichlet([30, 1, 1, 1, 1]))
        labels.append(0)
    for _ in range(n_hard):
        probs.append(rng.dirichlet([2, 2, 3, 2, 2]))
        labels.append(2)
    return np.array(probs), np.array(labels)


class TestMondrianMath:
    def test_per_class_q_hat_is_a_dict_keyed_by_esi(self):
        probs, labels = _make_calibration()
        cal = conformal.MondrianConformal.fit(probs, labels, alpha=0.10)
        by_class = cal.q_hat_by_esi()
        # Dict keyed by 1-based ESI level strings, one entry per ESI level.
        assert set(by_class.keys()) == {"1", "2", "3", "4", "5"}
        assert all(isinstance(v, float) for v in by_class.values())

    def test_hard_class_gets_larger_q_hat_than_easy_class(self):
        # The whole point of Mondrian: a class the model handles poorly keeps a
        # wide set even when the global error rate is tiny.
        probs, labels = _make_calibration()
        cal = conformal.MondrianConformal.fit(probs, labels, alpha=0.10)
        assert cal.q_hat[2] > cal.q_hat[0]

    def test_does_not_collapse_to_degenerate_global_singleton(self):
        # On a near-perfect (text-dominant) distribution a *global* q̂ collapses
        # to ~0; the per-class representative q̂ must stay meaningfully > 0 for the
        # classes the model is not certain about.
        rng = np.random.default_rng(2)
        # Mostly-correct but with a genuinely uncertain minority class.
        probs, labels = [], []
        for _ in range(400):
            probs.append(rng.dirichlet([60, 1, 1, 1, 1])); labels.append(0)
        for _ in range(40):
            probs.append(rng.dirichlet([1, 1, 1, 1, 1])); labels.append(3)
        probs, labels = np.array(probs), np.array(labels)
        cal = conformal.MondrianConformal.fit(probs, labels, alpha=0.10)
        global_q = conformal._conformal_quantile(
            conformal.nonconformity(probs, labels), 0.10
        )
        # Global q̂ is tiny; the hard class's q̂ is not.
        assert global_q < 0.2
        assert cal.q_hat[3] > 0.5

    def test_empirical_coverage_meets_target_within_tolerance(self):
        probs, labels = _make_calibration(n_easy=400, n_hard=400, seed=5)
        # Hold out a fresh draw from the same generator for honest coverage.
        cal = conformal.MondrianConformal.fit(probs, labels, alpha=0.10)
        hold_probs, hold_labels = _make_calibration(n_easy=400, n_hard=400, seed=99)
        cov = conformal.empirical_coverage(cal, hold_probs, hold_labels)
        # Target 90% coverage; allow a sampling tolerance band.
        assert cov["overall"] >= 0.85
        assert cov["overall"] <= 0.99
        for esi, c in cov["by_class"].items():
            assert c >= 0.80, f"ESI {esi} undercovered at {c}"

    def test_prediction_set_is_never_empty(self):
        probs, labels = _make_calibration()
        cal = conformal.MondrianConformal.fit(probs, labels, alpha=0.10)
        # A row that matches no class threshold still yields the argmax.
        adversarial = np.array([0.05, 0.05, 0.05, 0.05, 0.80])
        pset = cal.predict_set(adversarial)
        assert len(pset) >= 1
        assert all(1 <= x <= 5 for x in pset)

    def test_representative_q_hat_is_a_float_for_legacy_ui(self):
        probs, labels = _make_calibration()
        cal = conformal.MondrianConformal.fit(probs, labels, alpha=0.10)
        q = cal.representative_q_hat()
        assert isinstance(q, float)
        # Must be > the collapsed global value (dragged up by hard classes).
        assert q > 0.0

    def test_empty_class_falls_back_to_global_q_hat(self):
        # Only classes 0 and 4 present; 1/2/3 must fall back to global q̂.
        rng = np.random.default_rng(3)
        probs = np.array([rng.dirichlet([10, 1, 1, 1, 1]) for _ in range(50)]
                         + [rng.dirichlet([1, 1, 1, 1, 10]) for _ in range(50)])
        labels = np.array([0] * 50 + [4] * 50)
        cal = conformal.MondrianConformal.fit(probs, labels, alpha=0.10)
        assert cal.n_per_class[1] == 0
        assert cal.q_hat[1] == cal.global_q_hat

    def test_importance_weighted_variant_runs_and_covers(self):
        probs, labels = _make_calibration(n_easy=300, n_hard=300, seed=11)
        weights = np.where(labels == 2, 3.0, 1.0)  # up-weight the hard class
        cal = conformal.MondrianConformal.fit(
            probs, labels, alpha=0.10, weights=weights
        )
        cov = conformal.empirical_coverage(cal, probs, labels)
        assert 0.80 <= cov["overall"] <= 1.0
        assert cal.source == "synthetic_calibration"

    def test_nonconformity_score_is_one_minus_p_true(self):
        probs = np.array([[0.7, 0.1, 0.1, 0.05, 0.05],
                          [0.1, 0.1, 0.6, 0.1, 0.1]])
        labels = np.array([0, 2])
        s = conformal.nonconformity(probs, labels)
        np.testing.assert_allclose(s, [0.3, 0.4])

    def test_zero_calibration_admits_everything(self):
        q = conformal._conformal_quantile(np.array([]), 0.10)
        assert q == 1.0


# ---------------------------------------------------------------------------
# Layer 2: triage_ml integration (skipped if artifacts/deps unavailable)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def loaded_art():
    triage_ml = pytest.importorskip("services.triage_ml")
    art = triage_ml._load()
    if art is None:
        pytest.skip("ML artifacts not present / not loadable locally")
    # Calibration is lazy (deferred out of _load() to keep cold-start fast), but the
    # integration tests below assert on a populated calibrator, so prime it once here.
    # This makes the fixture order-independent: every test that reads art["conformal"]
    # sees it fitted no matter which test runs first.
    triage_ml._ensure_calibrated(art)
    return triage_ml, art


def _sample_patient():
    patient = {
        "patient_id": "test",
        "transcript": "chest pain radiating to the left arm",
        "language": "en",
        "medical_info": {"age": 62, "sex": "male", "conditions": ["Hypertension"]},
    }
    vitals = {
        "systolic_bp": 150, "diastolic_bp": 95, "heart_rate": 108,
        "respiratory_rate": 22, "temperature_c": 37.1, "spo2": 95,
        "gcs_total": 15, "pain_score": 8, "mental_status": "alert",
    }
    return patient, vitals


class TestTriageMLIntegration:
    def test_load_defers_calibration_then_lazy_fits_per_class(self, loaded_art):
        triage_ml, _shared = loaded_art
        # Assert the DEFERRAL contract on a PRISTINE load without disturbing the
        # shared lru_cache'd singleton (other tests depend on it being calibrated).
        # _load.__wrapped__() is the undecorated function — a fresh, uncached build.
        art = triage_ml._load.__wrapped__()
        # _load() must NOT calibrate eagerly — that would run ~150 ensemble
        # inferences inside the cold-start/warmup path and blow the Lambda timeout.
        assert art.get("conformal") is None, "calibration must be deferred, not run in _load()"
        assert art.get("_conformal_pending") is True
        # Lazy fit on first use produces the per-class Mondrian calibrator.
        triage_ml._ensure_calibrated(art)
        cal = art.get("conformal")
        assert cal is not None, "Mondrian calibrator missing after lazy calibration"
        assert set(cal.q_hat_by_esi().keys()) == {"1", "2", "3", "4", "5"}
        assert art.get("_conformal_pending") is False

    def test_predict_surfaces_per_class_q_hat(self, loaded_art):
        triage_ml, _ = loaded_art
        patient, vitals = _sample_patient()
        r = triage_ml.predict(patient, vitals)
        assert r is not None
        # Legacy scalar still a float (UI calls .toFixed(4)).
        assert isinstance(r["conformal_q_hat"], float)
        # New per-class dict present and keyed by ESI level.
        assert r["conformal_q_hat_by_class"] is not None
        assert set(r["conformal_q_hat_by_class"].keys()) == {"1", "2", "3", "4", "5"}
        assert "mondrian" in r["conformal_method"]
        assert r["conformal_set"]  # non-empty
        assert all(1 <= x <= 5 for x in r["conformal_set"])

    def test_q_hat_does_not_collapse(self, loaded_art):
        # The representative q̂ must be meaningfully above the collapsed global
        # value (~1e-4) baked into the pickle.
        _, art = loaded_art
        cal = art["conformal"]
        assert cal.representative_q_hat() > 1e-2
        legacy_global = float(art.get("conformal_q_hat_noisy", 0.0))
        assert cal.representative_q_hat() > legacy_global

    def test_recalibrate_from_outcomes_updates_q_hat(self, loaded_art):
        triage_ml, art = loaded_art
        before = dict(art["conformal"].q_hat_by_esi())

        # Real-outcome shape: probabilities + clinician-confirmed ESI. Construct a
        # set where the model was confidently wrong on ESI 4 so q̂[4] must grow.
        outcomes = []
        for _ in range(40):
            outcomes.append({
                "probabilities": {"1": 0.02, "2": 0.03, "3": 0.90, "4": 0.03, "5": 0.02},
                "confirmed_esi": 4,  # model said 3, clinician says 4
            })
        for _ in range(40):
            outcomes.append({
                "probabilities": {"1": 0.90, "2": 0.04, "3": 0.03, "4": 0.02, "5": 0.01},
                "confirmed_esi": 1,  # model correct
            })

        result = triage_ml.recalibrate_from_outcomes(outcomes)
        assert result["updated"] is True
        assert result["n_outcomes_used"] == 80
        assert result["source"] == "clinician_confirmed_outcomes"

        after = art["conformal"].q_hat_by_esi()
        assert after != before
        # ESI 4 was confidently mispredicted -> its q̂ must be large.
        assert after["4"] > 0.5
        assert art["conformal"].source == "clinician_confirmed_outcomes"

        # Restore the synthetic calibrator so other tests/modules see a clean state.
        triage_ml._calibrate(art)

    def test_recalibrate_noops_on_empty_outcomes(self, loaded_art):
        triage_ml, art = loaded_art
        result = triage_ml.recalibrate_from_outcomes([])
        assert result["updated"] is False
        assert result["reason"] == "no_usable_outcomes"
        # Calibrator left intact.
        assert art.get("conformal") is not None

    def test_recalibrate_accepts_patient_vitals_shape(self, loaded_art):
        triage_ml, art = loaded_art
        patient, vitals = _sample_patient()
        outcomes = [
            {"patient": patient, "vitals": vitals, "confirmed_esi": 2}
            for _ in range(20)
        ]
        result = triage_ml.recalibrate_from_outcomes(outcomes)
        assert result["updated"] is True
        assert result["n_outcomes_used"] == 20
        triage_ml._calibrate(art)  # restore
