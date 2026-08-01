"""Unit tests for ``services.em_coding`` — deterministic E&M leveling + NCCI.

Only the deterministic Stage-2 helpers are tested. The two LLM calls and the
``suggest()`` public entrypoint (which is API-key gated) are not exercised.

The module imports ``lib.claude`` / ``lib.config`` at import time, so the whole
module is import-guarded; if those deps are unavailable the suite skips.
"""
from __future__ import annotations

import pytest

# Imported directly rather than via pytest.importorskip. A guard turns
# "this module is broken" into "these tests were skipped" and lets a red
# build report green, which is how a genuine import failure went unnoticed.
import services.em_coding as em


# ---- _element_score --------------------------------------------------------
class TestElementScore:
    def test_none_defaults_to_one(self):
        assert em._element_score(None) == 1

    def test_empty_defaults_to_one(self):
        assert em._element_score("") == 1

    def test_known_phrases(self):
        assert em._element_score("straightforward") == 1
        assert em._element_score("low") == 2
        assert em._element_score("moderate") == 3
        assert em._element_score("high") == 4

    def test_synonyms(self):
        assert em._element_score("minimal") == 1
        assert em._element_score("limited") == 2
        assert em._element_score("extensive") == 3
        assert em._element_score("severe") == 4

    def test_case_and_whitespace_insensitive(self):
        assert em._element_score("  HIGH  ") == 4

    def test_unknown_defaults_to_one(self):
        assert em._element_score("gobbledygook") == 1


# ---- _score_to_mdm_tier ----------------------------------------------------
class TestScoreToTier:
    def test_mapping(self):
        assert em._score_to_mdm_tier(1) == "straightforward"
        assert em._score_to_mdm_tier(2) == "low"
        assert em._score_to_mdm_tier(3) == "moderate"
        assert em._score_to_mdm_tier(4) == "high"

    def test_out_of_range_defaults(self):
        assert em._score_to_mdm_tier(99) == "straightforward"


# ---- _level_by_mdm — AMA 2-of-3 rule ---------------------------------------
class TestLevelByMdm:
    def test_two_of_three_takes_second_highest(self):
        # scores: high(4), high(4), low(2) -> sorted desc [4,4,2] -> 2nd = 4
        r = em._level_by_mdm({
            "problems_addressed": "high",
            "data_reviewed": "high",
            "risk_of_complications": "low",
        })
        assert r["driving_score"] == 4
        assert r["mdm_tier"] == "high"

    def test_single_high_does_not_drive(self):
        # high(4), low(2), low(2) -> sorted [4,2,2] -> 2nd = 2 -> low
        r = em._level_by_mdm({
            "problems_addressed": "high",
            "data_reviewed": "low",
            "risk_of_complications": "low",
        })
        assert r["driving_score"] == 2
        assert r["mdm_tier"] == "low"

    def test_all_moderate(self):
        r = em._level_by_mdm({
            "problems_addressed": "moderate",
            "data_reviewed": "moderate",
            "risk_of_complications": "moderate",
        })
        assert r["mdm_tier"] == "moderate"

    def test_missing_elements_default_low(self):
        r = em._level_by_mdm({})
        assert r["mdm_tier"] == "straightforward"
        assert r["element_scores"] == {"problems": 1, "data": 1, "risk": 1}


# ---- _rank_em_codes --------------------------------------------------------
class TestRankEmCodes:
    def test_outpatient_established_moderate_top(self):
        ranked = em._rank_em_codes(em._OUTPATIENT_LEVELS, "established", "moderate")
        assert ranked[0]["code"] == "99214"  # established + moderate

    def test_outpatient_new_high_top(self):
        ranked = em._rank_em_codes(em._OUTPATIENT_LEVELS, "new", "high")
        assert ranked[0]["code"] == "99205"

    def test_only_returns_requested_family(self):
        ranked = em._rank_em_codes(em._OUTPATIENT_LEVELS, "established", "low")
        assert all(c["patient"] == "established" for c in ranked)

    def test_hospital_initial(self):
        ranked = em._rank_em_codes(em._HOSPITAL_LEVELS, "initial", "high")
        assert ranked[0]["code"] == "99223"


# ---- _time_crosscheck ------------------------------------------------------
class TestTimeCrosscheck:
    def test_no_time_documented(self):
        r = em._time_crosscheck("outpatient", "established", None)
        assert r["documented"] is False

    def test_outpatient_established_30min(self):
        # 99214 established time band is 30-39
        r = em._time_crosscheck("outpatient", "established", 32)
        assert r["documented"] is True
        assert r["time_based_code"] == "99214"

    def test_below_lowest_band_gives_lowest_code(self):
        r = em._time_crosscheck("outpatient", "established", 2)
        assert r["time_based_code"] == "99212"

    def test_above_highest_band_gives_highest_code(self):
        r = em._time_crosscheck("outpatient", "established", 999)
        assert r["time_based_code"] == "99215"

    def test_hospital_initial_band(self):
        # 99222 initial band 55-74
        r = em._time_crosscheck("hospital", "initial", 60)
        assert r["time_based_code"] == "99222"


# ---- _build_em_ranking -----------------------------------------------------
class TestBuildEmRanking:
    def test_top3_returned(self):
        mdm = {"problems_addressed": "moderate", "data_reviewed": "moderate",
               "risk_of_complications": "low", "summary_supporting_evidence": "cited"}
        time_check = {"documented": False}
        ranked = em._build_em_ranking("outpatient", "established", mdm, time_check)
        assert len(ranked) == 3
        assert ranked[0]["rank"] == 1
        assert ranked[0]["confidence"] >= ranked[1]["confidence"]

    def test_time_agreement_high_confidence(self):
        mdm = {"problems_addressed": "moderate", "data_reviewed": "moderate",
               "risk_of_complications": "moderate", "summary_supporting_evidence": ""}
        # 99214 is established/moderate; documented time agrees
        time_check = {"documented": True, "time_based_code": "99214"}
        ranked = em._build_em_ranking("outpatient", "established", mdm, time_check)
        assert ranked[0]["code"] == "99214"
        assert ranked[0]["agrees_with_time"] is True
        assert ranked[0]["confidence"] == 0.85

    def test_time_disagreement_lowers_confidence(self):
        mdm = {"problems_addressed": "moderate", "data_reviewed": "moderate",
               "risk_of_complications": "moderate", "summary_supporting_evidence": ""}
        time_check = {"documented": True, "time_based_code": "99212"}
        ranked = em._build_em_ranking("outpatient", "established", mdm, time_check)
        assert ranked[0]["agrees_with_time"] is False
        assert ranked[0]["confidence"] == 0.6


# ---- _validate_cpt — NCCI edits --------------------------------------------
class TestValidateCpt:
    def test_clean_set_passes(self):
        r = em._validate_cpt([{"code": "12001"}], em_code=None)
        # 12001 is bundled-into '*' but with no em_code no flag fires
        assert r["passed"] is True

    def test_mutually_exclusive_pair_errors(self):
        r = em._validate_cpt([{"code": "99213"}, {"code": "99214"}], em_code=None)
        assert r["passed"] is False
        assert any(f["type"] == "mutually_exclusive" for f in r["flags"])

    def test_bundled_into_em_warns(self):
        r = em._validate_cpt([{"code": "36415"}], em_code="99213")
        assert any(f["type"] == "bundled" and f["severity"] == "warning"
                   for f in r["flags"])
        # warning does not fail the check
        assert r["passed"] is True

    def test_component_into_comprehensive_errors(self):
        r = em._validate_cpt([{"code": "12001"}, {"code": "13132"}], em_code=None)
        assert r["passed"] is False
        assert any(f["type"] == "bundled" and f["severity"] == "error"
                   for f in r["flags"])

    def test_add_on_orphan_errors(self):
        r = em._validate_cpt([{"code": "99417"}], em_code=None)
        assert r["passed"] is False
        assert any(f["type"] == "add_on_orphan" for f in r["flags"])

    def test_add_on_with_primary_ok(self):
        r = em._validate_cpt([{"code": "99417"}], em_code="99215")
        assert not any(f["type"] == "add_on_orphan" for f in r["flags"])

    def test_error_and_warning_counts(self):
        r = em._validate_cpt([{"code": "99213"}, {"code": "99214"}], em_code=None)
        assert r["error_count"] >= 1
        assert r["warning_count"] >= 0


# ---- _rank_cpt -------------------------------------------------------------
class TestRankCpt:
    def test_top3_descending_confidence(self):
        cands = [{"code": str(c)} for c in (11111, 22222, 33333, 44444)]
        validation = {"flags": []}
        ranked = em._rank_cpt(cands, validation)
        assert len(ranked) == 3
        confs = [c["confidence"] for c in ranked]
        assert confs == sorted(confs, reverse=True)

    def test_error_code_demoted(self):
        cands = [{"code": "AAA"}, {"code": "BBB"}]
        validation = {"flags": [{"severity": "error", "codes": ["AAA"]}]}
        ranked = em._rank_cpt(cands, validation)
        aaa = [c for c in ranked if c["code"] == "AAA"][0]
        assert aaa["confidence"] <= 0.3
        assert aaa["ncci_clean"] is False


# ---- _suggest_modifiers ----------------------------------------------------
class TestSuggestModifiers:
    def test_modifier_25_with_em_and_procedure(self):
        mods = em._suggest_modifiers("99214", [{"code": "12001"}], False, "moderate")
        m25 = [m for m in mods if m["modifier"] == "25"]
        assert m25 and m25[0]["attach_to"] == "99214"
        assert m25[0]["confidence"] == 0.7  # moderate tier -> confident

    def test_modifier_25_low_tier_lower_confidence(self):
        mods = em._suggest_modifiers("99212", [{"code": "12001"}], False, "low")
        m25 = [m for m in mods if m["modifier"] == "25"][0]
        assert m25["confidence"] == 0.45

    def test_no_modifier_25_without_procedure(self):
        mods = em._suggest_modifiers("99214", [], False, "moderate")
        assert not any(m["modifier"] == "25" for m in mods)

    def test_modifier_59_with_two_procedures(self):
        mods = em._suggest_modifiers("99214", [{"code": "AAA"}, {"code": "BBB"}],
                                     False, "moderate")
        m59 = [m for m in mods if m["modifier"] == "59"]
        assert m59 and m59[0]["attach_to"] == "BBB"

    def test_no_modifier_59_with_one_procedure(self):
        mods = em._suggest_modifiers("99214", [{"code": "AAA"}], False, "moderate")
        assert not any(m["modifier"] == "59" for m in mods)

    def test_modifier_95_telehealth(self):
        mods = em._suggest_modifiers("99214", [], True, "moderate")
        m95 = [m for m in mods if m["modifier"] == "95"]
        assert m95 and m95[0]["attach_to"] == "99214"

    def test_no_modifier_95_without_telehealth(self):
        mods = em._suggest_modifiers("99214", [], False, "moderate")
        assert not any(m["modifier"] == "95" for m in mods)
