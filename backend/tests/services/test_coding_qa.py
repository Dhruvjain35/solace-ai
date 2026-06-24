"""Unit tests for ``services.coding_qa`` — the QA / audit-defense layer.

The layer is pure and deterministic (no LLM call), so it is fully testable by
feeding it ``em_coding``-shaped dicts. We build those dicts with em_coding's own
deterministic helpers where possible, so the tests stay faithful to real output.
"""
from __future__ import annotations

import pytest

qa = pytest.importorskip("services.coding_qa")
em = pytest.importorskip("services.em_coding")


def _coding_result(em_ranked, *, cpt_ranked=None, ncci=None, time_check=None,
                   leveling=None):
    """Assemble a minimal em_coding.suggest()-shaped result."""
    return {
        "available": True,
        "em_ranked": em_ranked,
        "cpt_ranked": cpt_ranked or [],
        "ncci_validation": ncci or {"flags": [], "passed": True},
        "time_crosscheck": time_check or {"documented": False},
        "em_leveling": leveling or {"mdm_tier": "moderate",
                                    "element_scores": {"problems": 3, "data": 3, "risk": 2},
                                    "rule": "AMA 2-of-3"},
    }


# ---- confidence_band -------------------------------------------------------
class TestConfidenceBand:
    def test_high(self):
        assert qa.confidence_band(0.85) == "high"
        assert qa.confidence_band(0.80) == "high"

    def test_medium(self):
        assert qa.confidence_band(0.60) == "medium"
        assert qa.confidence_band(0.50) == "medium"

    def test_low(self):
        assert qa.confidence_band(0.45) == "low"
        assert qa.confidence_band(0.0) == "low"

    def test_garbage_is_low(self):
        assert qa.confidence_band(None) == "low"
        assert qa.confidence_band("nope") == "low"


# ---- well-documented high-MDM code -> high band, no review -----------------
class TestHighMdmCleanCode:
    def test_high_band_no_review_no_downcoding(self):
        # Build a real high-MDM, time-agreeing E&M ranking via em_coding.
        mdm = {"problems_addressed": "high", "data_reviewed": "high",
               "risk_of_complications": "high",
               "summary_supporting_evidence": "sepsis workup, multiple labs, IV abx decision"}
        time_check = {"documented": True, "time_based_code": "99215",
                      "time_based_range": "40-54 min"}
        leveling = em._level_by_mdm(mdm)
        em_ranked = em._build_em_ranking("outpatient", "established", mdm, time_check)
        assert em_ranked[0]["confidence"] == 0.85  # clean top pick

        report = qa.review_codes(_coding_result(em_ranked, time_check=time_check,
                                                leveling=leveling))
        top = report["reviews"][0]
        assert top["confidence_band"] == "high"
        assert top["needs_human_review"] is False
        assert top["downcoding_risk"] is False
        assert "defensib" in top["audit_rationale"].lower() or \
               "agree" in top["audit_rationale"].lower() or \
               top["audit_rationale"]  # rationale present
        # evidence trail carried through
        assert top["evidence"]["mdm_tier"] == "high"
        assert top["evidence"]["agrees_with_time"] is True


# ---- thin / ambiguous code -> low band, review, downcoding -----------------
class TestThinAmbiguousCode:
    def test_time_disagreement_flags_review_and_downcoding(self):
        mdm = {"problems_addressed": "moderate", "data_reviewed": "moderate",
               "risk_of_complications": "moderate", "summary_supporting_evidence": ""}
        # documented time maps to a *lower* code than MDM -> disagreement
        time_check = {"documented": True, "time_based_code": "99212",
                      "time_based_range": "10-19 min"}
        leveling = em._level_by_mdm(mdm)
        em_ranked = em._build_em_ranking("outpatient", "established", mdm, time_check)
        assert em_ranked[0]["agrees_with_time"] is False
        assert em_ranked[0]["confidence"] == 0.6  # contested -> medium band

        report = qa.review_codes(_coding_result(em_ranked, time_check=time_check,
                                                leveling=leveling))
        top = report["reviews"][0]
        assert top["confidence_band"] == "medium"
        assert top["needs_human_review"] is True
        assert top["downcoding_risk"] is True
        assert "downcod" in top["audit_rationale"].lower() or \
               "reconcile" in top["audit_rationale"].lower()

    def test_low_band_em_needs_review(self):
        # A straightforward (low-confidence alternate-style) top pick with no time.
        em_ranked = [{"code": "99212", "rank": 1, "confidence": 0.45,
                      "agrees_with_time": True, "supporting_documentation": ""}]
        report = qa.review_codes(_coding_result(em_ranked))
        top = report["reviews"][0]
        assert top["confidence_band"] == "low"
        assert top["needs_human_review"] is True
        assert top["downcoding_risk"] is True

    def test_ncci_error_cpt_needs_review_and_downcoding(self):
        cpt_ranked = [{"code": "12001", "name": "repair", "support": "laceration",
                       "add_on": False, "confidence": 0.3, "ncci_clean": False}]
        ncci = {"flags": [{"type": "bundled", "codes": ["12001", "13132"],
                           "severity": "error", "message": "component of 13132"}],
                "passed": False}
        report = qa.review_codes(_coding_result(
            [{"code": "99214", "rank": 1, "confidence": 0.85,
              "agrees_with_time": True, "supporting_documentation": "x"}],
            cpt_ranked=cpt_ranked, ncci=ncci))
        cpt = [r for r in report["reviews"] if r["category"] == "cpt"][0]
        assert cpt["needs_human_review"] is True
        assert cpt["downcoding_risk"] is True
        assert cpt["evidence"]["ncci_flags"]  # flag trail carried through


# ---- clean_code_rate -------------------------------------------------------
class TestCleanCodeRate:
    def test_all_clean(self):
        em_ranked = [{"code": "99214", "rank": 1, "confidence": 0.85,
                      "agrees_with_time": True, "supporting_documentation": "x"}]
        cpt_ranked = [{"code": "99213", "confidence": 0.8, "ncci_clean": True}]
        report = qa.review_codes(_coding_result(em_ranked, cpt_ranked=cpt_ranked))
        assert report["clean_code_rate"] == 1.0
        assert report["needs_review_count"] == 0

    def test_mixed_rate(self):
        em_ranked = [
            {"code": "99214", "rank": 1, "confidence": 0.85, "agrees_with_time": True,
             "supporting_documentation": "x"},
            {"code": "99213", "rank": 2, "confidence": 0.45, "agrees_with_time": True,
             "supporting_documentation": ""},
        ]
        cpt_ranked = [{"code": "12001", "confidence": 0.2, "ncci_clean": True}]
        report = qa.review_codes(_coding_result(em_ranked, cpt_ranked=cpt_ranked))
        # top E&M clean; alternate (rank 2) never needs review; CPT low -> review
        assert report["total_codes"] == 3
        assert report["needs_review_count"] == 1
        assert report["clean_code_rate"] == round(2 / 3, 3)

    def test_empty_result_rate_is_one(self):
        report = qa.review_codes(_coding_result([]))
        assert report["total_codes"] == 0
        assert report["clean_code_rate"] == 1.0

    def test_alternate_never_carries_downcoding_risk(self):
        em_ranked = [
            {"code": "99214", "rank": 1, "confidence": 0.85, "agrees_with_time": True,
             "supporting_documentation": "x"},
            {"code": "99213", "rank": 2, "confidence": 0.45, "agrees_with_time": True,
             "supporting_documentation": ""},
        ]
        report = qa.review_codes(_coding_result(em_ranked))
        alt = [r for r in report["reviews"] if r["rank"] == 2][0]
        assert alt["needs_human_review"] is False
        assert alt["downcoding_risk"] is False


# ---- unavailable passthrough -----------------------------------------------
class TestUnavailable:
    def test_unavailable_coding_result(self):
        assert qa.review_codes({"available": False}) == {"available": False}

    def test_non_dict(self):
        assert qa.review_codes(None) == {"available": False}
        assert qa.review_codes("nope") == {"available": False}


# ---- backward-compat of em_coding output -----------------------------------
class TestEmCodingBackwardCompat:
    def test_suggest_with_qa_preserves_original_fields(self, monkeypatch):
        """suggest_with_qa() must return everything suggest() did, plus coding_qa."""
        sentinel = {
            "available": True,
            "mdm": {"problems_addressed": "moderate"},
            "em_primary": {"code": "99214", "rank": 1, "confidence": 0.85,
                           "agrees_with_time": True, "supporting_documentation": "x"},
            "em_alternate": {"code": "99213"},
            "icd10": [{"code": "K35.80"}],
            "cpt_procedures": [],
            "modifiers": [],
            "established_patient": True,
            "setting": "outpatient",
            "patient_type": "established",
            "em_leveling": {"mdm_tier": "moderate", "element_scores": {}, "rule": "r"},
            "em_ranked": [{"code": "99214", "rank": 1, "confidence": 0.85,
                           "agrees_with_time": True, "supporting_documentation": "x"}],
            "time_crosscheck": {"documented": False},
            "cpt_ranked": [],
            "ncci_validation": {"flags": [], "passed": True},
            "auto_submit": False,
        }
        monkeypatch.setattr(em, "suggest", lambda note_text, **kw: dict(sentinel))
        out = em.suggest_with_qa("some note")
        # every original key preserved
        for k in sentinel:
            assert k in out
            assert out[k] == sentinel[k]
        # additive QA block present
        assert "coding_qa" in out
        assert out["coding_qa"]["available"] is True
        assert out["coding_qa"]["total_codes"] == 1

    def test_suggest_with_qa_unavailable_passthrough(self, monkeypatch):
        monkeypatch.setattr(em, "suggest", lambda note_text, **kw: {"available": False})
        out = em.suggest_with_qa("note")
        assert out["available"] is False
        assert out["coding_qa"] == {"available": False}
