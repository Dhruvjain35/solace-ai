"""Unit tests for ``services.triage_engine`` — deterministic ESI prediction.

The engine is pure-Python simulation mode (no model pickles, no network).
Tests cover the vital-flag / composite math (qSOFA, SIRS, shock index) and
the public ``predict_triage`` contract.
"""
from __future__ import annotations

import pytest

# Imported directly rather than via pytest.importorskip. A guard turns
# "this module is broken" into "these tests were skipped" and lets a red
# build report green, which is how a genuine import failure went unnoticed.
import services.triage_engine as te


def _patient(**overrides):
    base = {
        "heart_rate": 75, "sbp": 120, "dbp": 80, "o2_sat": 98,
        "resp_rate": 16, "temperature": 98.6, "gcs": 15, "age": 40,
        "chief_complaint": "ankle sprain", "arrival_mode": "Walk-in",
        "n_comorbidities": 0,
    }
    base.update(overrides)
    return base


# ---- _compute_vital_flags --------------------------------------------------
class TestVitalFlags:
    def test_all_normal(self):
        f = te._compute_vital_flags(75, 120, 80, 98, 16, 98.6, 15)
        assert not any(f.values())

    def test_hypotension(self):
        f = te._compute_vital_flags(75, 85, 60, 98, 16, 98.6, 15)
        assert f["hypotension"] is True
        assert f["severe_hypotension"] is False

    def test_severe_hypotension(self):
        f = te._compute_vital_flags(75, 65, 40, 98, 16, 98.6, 15)
        assert f["severe_hypotension"] is True
        assert f["hypotension"] is True

    def test_tachycardia_thresholds(self):
        assert te._compute_vital_flags(101, 120, 80, 98, 16, 98.6, 15)["tachycardia"]
        assert te._compute_vital_flags(131, 120, 80, 98, 16, 98.6, 15)["severe_tachycardia"]

    def test_hypoxia(self):
        assert te._compute_vital_flags(75, 120, 80, 93, 16, 98.6, 15)["hypoxia"]
        assert te._compute_vital_flags(75, 120, 80, 87, 16, 98.6, 15)["severe_hypoxia"]

    def test_gcs_flags(self):
        f = te._compute_vital_flags(75, 120, 80, 98, 16, 98.6, 8)
        assert f["severe_gcs"] is True
        assert f["altered_mental"] is True

    def test_shock_index_elevated(self):
        # hr 130 / sbp 100 = 1.3 > 1.0
        f = te._compute_vital_flags(130, 100, 70, 98, 16, 98.6, 15)
        assert f["shock_index_elevated"] is True

    def test_fever_and_hypothermia(self):
        assert te._compute_vital_flags(75, 120, 80, 98, 16, 101.0, 15)["fever"]
        assert te._compute_vital_flags(75, 120, 80, 98, 16, 94.0, 15)["hypothermia"]


# ---- _compute_composites — qSOFA / SIRS / shock index ----------------------
class TestComposites:
    def _comp(self, hr, sbp, rr, temp, gcs):
        flags = te._compute_vital_flags(hr, sbp, sbp - 40, 98, rr, temp, gcs)
        return te._compute_composites(hr, sbp, rr, temp, gcs, flags)

    def test_qsofa_zero(self):
        c = self._comp(75, 120, 16, 98.6, 15)
        assert c["qsofa"] == 0

    def test_qsofa_full(self):
        # sbp <=100, rr >=22, gcs <15 -> 3
        c = self._comp(110, 95, 24, 98.6, 14)
        assert c["qsofa"] == 3

    def test_qsofa_partial(self):
        # only rr >=22
        c = self._comp(75, 120, 24, 98.6, 15)
        assert c["qsofa"] == 1

    def test_sirs_zero(self):
        c = self._comp(75, 120, 16, 98.6, 15)
        assert c["sirs"] == 0

    def test_sirs_full_three(self):
        # temp >100.4, hr >90, rr >20
        c = self._comp(95, 120, 22, 101.0, 15)
        assert c["sirs"] == 3

    def test_sirs_hypothermia_counts(self):
        # temp <96.8 still triggers the temperature criterion
        c = self._comp(75, 120, 16, 96.0, 15)
        assert c["sirs"] == 1

    def test_shock_index_rounded(self):
        # hr 120 / sbp 80 = 1.5
        c = self._comp(120, 80, 16, 98.6, 15)
        assert c["shock_index"] == 1.5

    def test_shock_index_div_by_zero_guard(self):
        # sbp 0 -> max(sbp,1) avoids ZeroDivisionError
        c = self._comp(75, 0, 16, 98.6, 15)
        assert c["shock_index"] == 75.0

    def test_cv_risk_count(self):
        # hypotension + tachycardia + shock_index + hypoxia all present
        flags = te._compute_vital_flags(140, 80, 50, 85, 16, 98.6, 15)
        c = te._compute_composites(140, 80, 16, 98.6, 15, flags)
        assert c["cv_risk"] == 4


# ---- _parse_chief_complaint ------------------------------------------------
class TestParseChiefComplaint:
    def test_esi1_keyword(self):
        lvl, conf = te._parse_chief_complaint("patient is unresponsive")
        assert lvl == 1
        assert conf >= 0.9

    def test_esi2_keyword(self):
        lvl, _ = te._parse_chief_complaint("crushing chest pain")
        assert lvl == 2

    def test_low_acuity_keyword(self):
        # Refill requests are low-acuity. The expanded ESI engine classifies
        # them as ESI 4 (less-urgent) rather than 5; pin the canonical value.
        lvl, _ = te._parse_chief_complaint("medication refill request")
        assert lvl == 4

    def test_unknown_defaults_level3(self):
        lvl, conf = te._parse_chief_complaint("something unmatched entirely")
        assert lvl == 3
        assert conf == pytest.approx(0.4)

    def test_most_specific_keyword_wins(self):
        # "chest pain" (ESI2) is longer/more specific than "pain"-ish ESI3 hits
        lvl, _ = te._parse_chief_complaint("chest pain")
        assert lvl == 2


# ---- _softmax --------------------------------------------------------------
class TestSoftmax:
    def test_sums_to_one(self):
        probs = te._softmax([1.0, 2.0, 3.0])
        assert sum(probs) == pytest.approx(1.0)

    def test_monotonic(self):
        probs = te._softmax([0.0, 1.0, 2.0])
        assert probs[0] < probs[1] < probs[2]

    def test_uniform_input(self):
        probs = te._softmax([5.0, 5.0, 5.0])
        for p in probs:
            assert p == pytest.approx(1 / 3)


# ---- _generate_conformal_set -----------------------------------------------
class TestConformalSet:
    def test_high_confidence_singleton(self):
        cs, cov = te._generate_conformal_set(3, 0.95)
        assert cs == [3]
        assert cov == 0.90

    def test_mid_confidence_neighbors(self):
        cs, _ = te._generate_conformal_set(3, 0.70)
        assert cs == [2, 3, 4]

    def test_low_confidence_clamped_at_edges(self):
        cs, _ = te._generate_conformal_set(1, 0.40)
        assert cs == [1, 2]
        assert min(cs) >= 1


# ---- predict_triage — public contract --------------------------------------
class TestPredictTriage:
    def test_returns_expected_keys(self):
        out = te.predict_triage(_patient())
        for k in ("esi_level", "esi_label", "confidence", "probabilities",
                  "conformal_set", "coverage_level", "risk_factors",
                  "clinical_flags", "composites", "recommendation"):
            assert k in out

    def test_esi_level_in_range(self):
        out = te.predict_triage(_patient())
        assert 1 <= out["esi_level"] <= 5
        assert out["esi_label"] == te.ESI_LABELS[out["esi_level"]]

    def test_probabilities_normalized(self):
        out = te.predict_triage(_patient())
        assert len(out["probabilities"]) == 5
        assert sum(out["probabilities"]) == pytest.approx(1.0, abs=1e-3)

    def test_low_acuity_walkin_is_higher_esi(self):
        out = te.predict_triage(_patient(chief_complaint="suture removal",
                                         arrival_mode="Walk-in"))
        assert out["esi_level"] >= 3

    def test_severe_gcs_forces_esi1(self):
        out = te.predict_triage(_patient(gcs=5, chief_complaint="found down"))
        assert out["esi_level"] == 1

    def test_cardiac_arrest_forces_esi1(self):
        out = te.predict_triage(_patient(chief_complaint="cardiac arrest"))
        assert out["esi_level"] == 1

    def test_septic_shock_pattern_high_acuity(self):
        out = te.predict_triage(_patient(
            chief_complaint="fever and weakness", heart_rate=140, sbp=80,
            temperature=103.0, resp_rate=28, o2_sat=90,
        ))
        assert out["esi_level"] <= 2
        assert out["composites"]["qsofa"] >= 2

    def test_recommendation_nonempty(self):
        out = te.predict_triage(_patient())
        assert isinstance(out["recommendation"], str) and out["recommendation"]

    def test_clinical_flags_reflect_vitals(self):
        out = te.predict_triage(_patient(o2_sat=85, heart_rate=140))
        assert "severe hypoxia" in out["clinical_flags"]
        assert "severe tachycardia" in out["clinical_flags"]

    def test_risk_factors_capped_at_five(self):
        out = te.predict_triage(_patient(
            heart_rate=140, sbp=65, o2_sat=80, resp_rate=30, temperature=104.0,
            gcs=6, age=80, n_comorbidities=6, arrival_mode="Ambulance",
        ))
        assert len(out["risk_factors"]) <= 5

    def test_chest_pain_recommendation_addendum(self):
        out = te.predict_triage(_patient(
            chief_complaint="chest pain", heart_rate=110, sbp=95, resp_rate=24,
        ))
        # ESI 2 chest-pain path appends an ECG/troponin instruction
        if out["esi_level"] == 2:
            assert "ECG" in out["recommendation"]
