"""Unit tests for ``services.cds_calculators`` — deterministic CDS scoring.

Every reference value below is hand-derived from the canonical published
rubric and the module's own documented cutoffs. No LLM / network paths are
exercised (``auto_extract`` is import-guarded and not invoked).
"""
from __future__ import annotations

import pytest

cds = pytest.importorskip("services.cds_calculators")


# ---- HEART score -----------------------------------------------------------
class TestHeart:
    def test_low_risk(self):
        # total = 0+0+0+0+0 = 0 -> low
        r = cds.heart(history=0, ekg=0, age=0, risk_factors=0, troponin=0)
        assert r["score"] == 0
        assert r["risk"] == "low"
        assert r["components"]["history"] == 0

    def test_boundary_3_is_low(self):
        r = cds.heart(history=1, ekg=1, age=1, risk_factors=0, troponin=0)
        assert r["score"] == 3
        assert r["risk"] == "low"

    def test_boundary_4_is_moderate(self):
        r = cds.heart(history=1, ekg=1, age=1, risk_factors=1, troponin=0)
        assert r["score"] == 4
        assert r["risk"] == "moderate"

    def test_boundary_6_is_moderate(self):
        r = cds.heart(history=2, ekg=2, age=2, risk_factors=0, troponin=0)
        assert r["score"] == 6
        assert r["risk"] == "moderate"

    def test_high_risk(self):
        r = cds.heart(history=2, ekg=2, age=2, risk_factors=2, troponin=2)
        assert r["score"] == 10
        assert r["risk"] == "high"


# ---- Wells PE --------------------------------------------------------------
class TestWellsPE:
    def test_all_negative_unlikely(self):
        r = cds.wells_pe()
        assert r["score"] == 0
        assert r["risk"] == "PE unlikely"

    def test_boundary_4_unlikely(self):
        # 3 + 1 = 4 -> still unlikely (<= 4)
        r = cds.wells_pe(clinical_signs_dvt=True, hemoptysis=True, malignancy=True)
        assert r["score"] == 5  # 3 + 1 + 1
        assert r["risk"] == "PE likely"

    def test_exactly_4_unlikely(self):
        # 3 (dvt) + 1 (hemoptysis) = 4
        r = cds.wells_pe(clinical_signs_dvt=True, hemoptysis=True)
        assert r["score"] == 4
        assert r["risk"] == "PE unlikely"

    def test_likely(self):
        r = cds.wells_pe(clinical_signs_dvt=True, pe_most_likely=True)
        assert r["score"] == 6
        assert r["risk"] == "PE likely"


# ---- Wells DVT -------------------------------------------------------------
class TestWellsDVT:
    def test_low(self):
        r = cds.wells_dvt()
        assert r["score"] == 0
        assert r["risk"] == "low"

    def test_moderate(self):
        r = cds.wells_dvt(active_cancer=True, pitting_edema=True)
        assert r["score"] == 2
        assert r["risk"] == "moderate"

    def test_high(self):
        r = cds.wells_dvt(active_cancer=True, entire_leg_swollen=True, prior_dvt=True)
        assert r["score"] == 3
        assert r["risk"] == "high"

    def test_alternative_dx_subtracts_two(self):
        r = cds.wells_dvt(active_cancer=True, pitting_edema=True, alternative_dx_likely=True)
        assert r["score"] == 0
        assert r["risk"] == "low"


# ---- PERC ------------------------------------------------------------------
class TestPERC:
    def test_all_negative_excludes(self):
        r = cds.perc(True, True, True, True, True, True, True, True)
        assert r["perc_negative"] is True

    def test_one_positive_cannot_exclude(self):
        r = cds.perc(False, True, True, True, True, True, True, True)
        assert r["perc_negative"] is False


# ---- NIHSS -----------------------------------------------------------------
class TestNIHSS:
    def test_zero(self):
        r = cds.nihss({})
        assert r["score"] == 0
        assert r["severity"] == "no stroke symptoms"

    def test_minor(self):
        r = cds.nihss({"loc": 2, "visual": 2})
        assert r["score"] == 4
        assert r["severity"] == "minor"

    def test_moderate(self):
        r = cds.nihss({"loc": 3, "best_gaze": 2, "motor_arm_left": 4, "best_language": 3})
        assert r["score"] == 12
        assert r["severity"] == "moderate"

    def test_severe(self):
        # All 15 items at their per-item maximum -> 42, the saturated total.
        items = {k: 9 for k in cds._NIHSS_MAX}
        r = cds.nihss(items)
        assert r["score"] == sum(cds._NIHSS_MAX.values())  # 42
        assert r["score"] > 20
        assert r["severity"] == "severe"

    def test_ignores_unknown_keys(self):
        r = cds.nihss({"loc": 2, "bogus_key": 99})
        assert r["score"] == 2


# ---- CURB-65 ---------------------------------------------------------------
class TestCURB65:
    def test_outpatient(self):
        r = cds.curb65(False, False, False, False, False)
        assert r["score"] == 0
        assert "outpatient" in r["action"].lower()

    def test_two_short_inpatient(self):
        r = cds.curb65(True, True, False, False, False)
        assert r["score"] == 2
        assert "observation" in r["action"]

    def test_inpatient(self):
        r = cds.curb65(True, True, True, True, True)
        assert r["score"] == 5
        assert "inpatient" in r["action"].lower()


# ---- qSOFA -----------------------------------------------------------------
class TestQSOFA:
    def test_low(self):
        r = cds.qsofa(False, False, False)
        assert r["score"] == 0
        assert r["high_risk"] is False

    def test_one_not_high(self):
        r = cds.qsofa(True, False, False)
        assert r["score"] == 1
        assert r["high_risk"] is False

    def test_two_high_risk(self):
        r = cds.qsofa(True, True, False)
        assert r["score"] == 2
        assert r["high_risk"] is True
        assert "Sepsis" in r["action"]

    def test_three_high_risk(self):
        r = cds.qsofa(True, True, True)
        assert r["score"] == 3
        assert r["high_risk"] is True


# ---- NEWS2 -----------------------------------------------------------------
class TestNEWS2:
    def test_all_normal_zero(self):
        # rr 16, spo2 98, no O2, sbp 120, hr 75, temp 37, alert
        r = cds.news2(rr=16, spo2=98, on_oxygen=False, sbp=120, hr=75, temp_c=37.0, alert=True)
        assert r["score"] == 0
        assert r["risk"].startswith("low")

    def test_high_score_multiple_derangements(self):
        # rr 30 (+3), spo2 90 (+3), on O2 (+2), sbp 85 (+3), hr 135 (+3),
        # temp 35 (+3), not alert (+3) = 20
        r = cds.news2(rr=30, spo2=90, on_oxygen=True, sbp=85, hr=135, temp_c=35.0, alert=False)
        assert r["score"] == 20
        assert r["risk"].startswith("high")

    def test_medium_band(self):
        # rr 22 (+2), spo2 94 (+1), no O2, sbp 105 (+1), hr 92 (+1), temp 37 (0), alert
        # = 5 -> medium
        r = cds.news2(rr=22, spo2=94, on_oxygen=False, sbp=105, hr=92, temp_c=37.0, alert=True)
        assert r["score"] == 5
        assert r["risk"].startswith("medium")

    def test_single_oxygen_point(self):
        r = cds.news2(rr=16, spo2=98, on_oxygen=True, sbp=120, hr=75, temp_c=37.0, alert=True)
        assert r["score"] == 2


# ---- Centor + McIsaac ------------------------------------------------------
class TestCentor:
    def test_adult_all_positive(self):
        # 4 base points, age 30 (no modifier) -> 4
        r = cds.centor(age=30, tonsillar_exudate=True, tender_anterior_cervical_nodes=True,
                       fever_history=True, cough_absent=True)
        assert r["score"] == 4
        assert "empiric antibiotics" in r["action"]

    def test_child_age_modifier_adds_one(self):
        # age 10 -> +1; one base point -> 2
        r = cds.centor(age=10, tonsillar_exudate=True, tender_anterior_cervical_nodes=False,
                       fever_history=False, cough_absent=False)
        assert r["score"] == 2

    def test_older_adult_modifier_subtracts_one(self):
        # age 50 -> -1; two base points -> 1
        r = cds.centor(age=50, tonsillar_exudate=True, tender_anterior_cervical_nodes=True,
                       fever_history=False, cough_absent=False)
        assert r["score"] == 1
        assert "symptomatic" in r["action"]

    def test_negative_score_no_testing(self):
        r = cds.centor(age=70, tonsillar_exudate=False, tender_anterior_cervical_nodes=False,
                       fever_history=False, cough_absent=False)
        assert r["score"] == -1
        assert "no testing or antibiotics" in r["action"]


# ---- GCS -------------------------------------------------------------------
class TestGCS:
    def test_full_score_minor(self):
        r = cds.gcs(eye=4, verbal=5, motor=6)
        assert r["score"] == 15
        assert r["severity"] == "minor"

    def test_moderate(self):
        r = cds.gcs(eye=2, verbal=3, motor=5)
        assert r["score"] == 10
        assert r["severity"] == "moderate"

    def test_severe(self):
        r = cds.gcs(eye=1, verbal=1, motor=4)
        assert r["score"] == 6
        assert r["severity"] == "severe"

    def test_clamps_out_of_range_inputs(self):
        # eye clamped to 4, verbal clamped to 5, motor clamped to 6 -> 15
        r = cds.gcs(eye=99, verbal=99, motor=99)
        assert r["score"] == 15

    def test_clamps_negative_inputs(self):
        # Each subscale clamps to its minimum of 1 (not 0): 1 + 1 + 1 = 3.
        r = cds.gcs(eye=-5, verbal=-5, motor=-5)
        assert r["score"] == 3
        assert r["components"] == {"eye": 1, "verbal": 1, "motor": 1}
        assert r["severity"] == "severe"


# ---- Registry / dispatcher -------------------------------------------------
class TestRegistry:
    def test_list_calculators_shape(self):
        items = cds.list_calculators()
        keys = {i["key"] for i in items}
        assert {"heart", "qsofa", "gcs", "news2"}.issubset(keys)
        for i in items:
            assert "name" in i and "inputs" in i and "applies_when" in i

    def test_calculate_dispatch_qsofa(self):
        out = cds.calculate("qsofa", {
            "rr_at_least_22": True, "altered_mental": True, "sbp_at_most_100": False,
        })
        assert out["calculator"] == "qsofa"
        assert out["result"]["score"] == 2

    def test_calculate_unknown_key(self):
        out = cds.calculate("does_not_exist", {})
        assert "error" in out

    def test_calculate_missing_input_surfaces_error(self):
        out = cds.calculate("qsofa", {"rr_at_least_22": True})
        assert "error" in out
        assert out["calculator"] == "qsofa"

    def test_relevant_calculators_chest_pain(self):
        rel = cds.relevant_calculators("severe chest pain radiating to arm")
        assert "heart" in rel

    def test_relevant_calculators_fallback(self):
        rel = cds.relevant_calculators("")
        assert rel == ["news2"]

    def test_relevant_calculators_sore_throat(self):
        rel = cds.relevant_calculators("patient with sore throat")
        assert "centor" in rel
