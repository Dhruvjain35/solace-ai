"""Unit tests for ``services.screeners`` — validated PRO/screener scoring.

Reference cutoffs are the published gold standards documented in the module
docstring. LLM ``auto_extract`` is not exercised.
"""
from __future__ import annotations

import pytest

# Imported directly rather than via pytest.importorskip. A guard turns
# "this module is broken" into "these tests were skipped" and lets a red
# build report green, which is how a genuine import failure went unnoticed.
import services.screeners as scr


# ---- PHQ-9 -----------------------------------------------------------------
class TestPHQ9:
    def test_none_minimal(self):
        r = scr.phq9([0] * 9)
        assert r["score"] == 0
        assert r["severity"] == "none-minimal"
        assert r["suicidality"] is False
        assert r["flags"] == []

    def test_mild_boundary(self):
        # 9 items: 1,1,1,1,1,0,0,0,0 -> 5 -> mild
        r = scr.phq9([1, 1, 1, 1, 1, 0, 0, 0, 0])
        assert r["score"] == 5
        assert r["severity"] == "mild"

    def test_moderate(self):
        r = scr.phq9([2, 2, 2, 2, 2, 0, 0, 0, 0])
        assert r["score"] == 10
        assert r["severity"] == "moderate"

    def test_moderately_severe(self):
        r = scr.phq9([2, 2, 2, 2, 2, 2, 2, 1, 0])
        assert r["score"] == 15
        assert r["severity"] == "moderately severe"
        assert any("major depressive" in f for f in r["flags"])

    def test_severe(self):
        r = scr.phq9([3] * 8 + [0])
        assert r["score"] == 24
        assert r["severity"] == "severe"

    def test_suicidality_flag_on_item9(self):
        r = scr.phq9([0] * 8 + [1])
        assert r["suicidality"] is True
        assert any("suicidality" in f.lower() for f in r["flags"])

    def test_wrong_item_count_raises(self):
        with pytest.raises(ValueError):
            scr.phq9([0] * 8)


# ---- GAD-7 -----------------------------------------------------------------
class TestGAD7:
    def test_minimal(self):
        r = scr.gad7([0] * 7)
        assert r["score"] == 0
        assert r["severity"] == "minimal"

    def test_mild(self):
        r = scr.gad7([1, 1, 1, 1, 1, 0, 0])
        assert r["score"] == 5
        assert r["severity"] == "mild"

    def test_moderate(self):
        r = scr.gad7([2, 2, 2, 2, 2, 0, 0])
        assert r["score"] == 10
        assert r["severity"] == "moderate"

    def test_severe_with_flag(self):
        r = scr.gad7([3, 3, 3, 3, 3, 0, 0])
        assert r["score"] == 15
        assert r["severity"] == "severe"
        assert any("severe GAD" in f for f in r["flags"])

    def test_wrong_count_raises(self):
        with pytest.raises(ValueError):
            scr.gad7([0] * 6)


# ---- AUDIT-C ---------------------------------------------------------------
class TestAuditC:
    def test_male_cutoff_negative(self):
        r = scr.audit_c([1, 1, 1], sex="M")
        assert r["score"] == 3
        assert r["cutoff"] == 4
        assert r["positive"] is False

    def test_male_cutoff_positive(self):
        r = scr.audit_c([2, 1, 1], sex="M")
        assert r["score"] == 4
        assert r["positive"] is True
        assert r["flags"]

    def test_female_cutoff_is_three(self):
        r = scr.audit_c([1, 1, 1], sex="F")
        assert r["cutoff"] == 3
        assert r["positive"] is True

    def test_default_sex_is_male(self):
        r = scr.audit_c([1, 1, 1])
        assert r["cutoff"] == 4


# ---- EPDS ------------------------------------------------------------------
class TestEPDS:
    def test_low(self):
        r = scr.epds([0] * 10)
        assert r["score"] == 0
        assert r["severity"] == "low"

    def test_possible(self):
        r = scr.epds([1] * 10)
        assert r["score"] == 10
        assert r["severity"] == "possible depression"

    def test_likely_with_flags(self):
        r = scr.epds([2] * 6 + [1] * 4)
        assert r["score"] == 16
        assert r["severity"] == "likely depression"
        assert any("perinatal" in f for f in r["flags"])

    def test_self_harm_flag_item10(self):
        r = scr.epds([0] * 9 + [2])
        assert r["suicidality"] is True
        assert any("self-harm" in f for f in r["flags"])


# ---- PCL-5 -----------------------------------------------------------------
class TestPCL5:
    def test_below_threshold(self):
        r = scr.pcl5([1] * 20)
        assert r["score"] == 20
        assert r["probable_ptsd"] is False

    def test_at_threshold_33(self):
        # 13 items of 3 + 7 of 0 wouldn't reach; use 11*3 = 33
        r = scr.pcl5([3] * 11 + [0] * 9)
        assert r["score"] == 33
        assert r["probable_ptsd"] is True
        assert r["flags"]


# ---- ACE -------------------------------------------------------------------
class TestACE:
    def test_minimal(self):
        r = scr.ace([0] * 10)
        assert r["score"] == 0
        assert r["risk"] == "minimal"

    def test_elevated(self):
        r = scr.ace([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        assert r["score"] == 1
        assert r["risk"] == "elevated"

    def test_high_at_four(self):
        r = scr.ace([1, 1, 1, 1, 0, 0, 0, 0, 0, 0])
        assert r["score"] == 4
        assert r["risk"] == "high"
        assert r["flags"]

    def test_counts_any_positive_as_one(self):
        # values >0 each count once regardless of magnitude
        r = scr.ace([5, 9, 0, 0, 0, 0, 0, 0, 0, 0])
        assert r["score"] == 2


# ---- CRAFFT ----------------------------------------------------------------
class TestCRAFFT:
    def test_negative(self):
        r = scr.crafft([1, 0, 0, 0, 0, 0])
        assert r["score"] == 1
        assert r["positive"] is False

    def test_positive_at_two(self):
        r = scr.crafft([1, 1, 0, 0, 0, 0])
        assert r["score"] == 2
        assert r["positive"] is True
        assert r["flags"]


# ---- PRAPARE ---------------------------------------------------------------
class TestPRAPARE:
    def test_no_risks(self):
        r = scr.prapare({})
        assert r["risk_count"] == 0
        assert r["risks"] == []
        assert r["icd10_z_codes"] == []

    def test_homeless_yields_z59_0(self):
        r = scr.prapare({"housing_situation": "homeless"})
        assert "housing" in r["risks"]
        assert "Z59.0" in r["icd10_z_codes"]
        assert "housing assistance" in r["community_resource_categories"]

    def test_food_insecurity(self):
        r = scr.prapare({"food_security": "often"})
        assert "food_insecurity" in r["risks"]
        assert "Z59.41" in r["icd10_z_codes"]

    def test_ipv_safety(self):
        r = scr.prapare({"safety_at_home": "unsafe"})
        assert "intimate_partner_violence" in r["risks"]
        assert "Z63.0" in r["icd10_z_codes"]

    def test_multiple_domains(self):
        r = scr.prapare({
            "housing_situation": "homeless",
            "food_security": "sometimes",
            "transportation": "lack",
            "stress": "a_lot",
        })
        assert r["risk_count"] == 4


# ---- Registry / dispatcher -------------------------------------------------
class TestRegistry:
    def test_list_screeners_shape(self):
        items = scr.list_screeners()
        keys = {i["key"] for i in items}
        assert {"phq9", "gad7", "audit_c", "prapare"}.issubset(keys)

    def test_score_dispatch_phq9(self):
        out = scr.score("phq9", {"items": [3] * 9})
        assert out["screener"] == "phq9"
        assert out["result"]["score"] == 27

    def test_score_dispatch_audit_c_uses_sex(self):
        out = scr.score("audit_c", {"items": [1, 1, 1], "sex": "F"})
        assert out["result"]["positive"] is True

    def test_score_dispatch_prapare_uses_answers(self):
        out = scr.score("prapare", {"answers": {"housing_situation": "homeless"}})
        assert out["result"]["risk_count"] == 1

    def test_score_unknown_key(self):
        out = scr.score("nope", {})
        assert "error" in out

    def test_score_bad_payload_surfaces_error(self):
        out = scr.score("phq9", {"items": [0, 0, 0]})
        assert "error" in out
