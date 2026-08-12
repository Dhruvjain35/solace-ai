"""The triage model card must describe the model that is actually running.

The defect this suite exists to prevent had already shipped. `model_cards.py`
carried a hand-written block asserting the ensemble trained on "1.2M
de-identified triage encounters" and that "no synthetic or generative
augmentation" was used, while `scripts/train_triage_model.py` wrote "Kaggle
Triagegeist (80k synthetic ED encounters)" into the artifact the served model is
loaded from. Both lived in the repo at the same time. The false one was the one
published at /api/model-cards for procurement teams and CMIOs to read.

The rule these tests encode: **the card may not assert a training-data claim it
did not read from the artifact.** Not "the card should be accurate" — accuracy is
what a hand-written string claims about itself right up until a retrain. The card
has to be structurally incapable of holding an independent opinion.

Scope is derived, not listed. `test_no_hardcoded_training_claims` walks the static
CARDS literal rather than checking the specific strings that were wrong, because a
test that names the old lie only catches the old lie. This is the CONSTITUTION's
own lesson about SEC-002: a hand-written scope is the first thing to go stale.
"""
from __future__ import annotations

import re

import pytest

from services import model_cards


TRIAGE = model_cards.TRIAGE_CARD_ID


# ---------------------------------------------------------------------------
# The static literal must not carry provenance claims at all.
# ---------------------------------------------------------------------------

# Attributes whose truth depends on which artifact is loaded. A static card that
# holds any of these is holding a second copy of a fact, which is the failure
# mode this suite exists for.
DERIVED_ATTRIBUTES = (
    "training_data",
    "data_provenance",
    "performance",
    "synthetic_data_caveat",
)


def test_triage_card_literal_declares_no_provenance():
    """The source literal must be silent about training data.

    If someone re-adds a hand-written `training_data` block to the triage card,
    this fails — regardless of whether what they wrote happens to be true today.
    """
    static = model_cards.CARDS[TRIAGE]
    held = [attr for attr in DERIVED_ATTRIBUTES if attr in static]
    assert held == [], (
        f"The triage card literal carries {held}. These are read from the model "
        "artifact at request time by _apply_triage_provenance(). A hand-written "
        "copy will disagree with the shipped model after the next retrain, and "
        "nothing else in CI would notice."
    )


# A number followed by M/K/million/thousand and then a word about encounters or
# patients. This is the shape of the claim that was wrong ("1.2M de-identified
# triage encounters"), expressed generally enough to catch the next one.
_COHORT_SIZE_CLAIM = re.compile(
    r"\b\d[\d,.]*\s*(?:m|k|million|thousand)?\s*"
    r"(?:de-identified\s+)?(?:triage\s+|ed\s+|clinical\s+)?"
    r"(?:encounter|patient|record|visit)s?\b",
    re.IGNORECASE,
)


def test_no_card_asserts_an_unverifiable_cohort_size():
    """No card may state how many encounters it trained on in a static string.

    A cohort size is exactly the kind of impressive, specific, unverifiable
    number that ends up in a card because it sounded right. If a real one is
    known it belongs in the artifact, where provenance() will read it.
    """
    offenders: list[tuple[str, str, str]] = []
    for card_id, card in model_cards.CARDS.items():
        for key, value in card.items():
            for text in _walk_strings(value):
                match = _COHORT_SIZE_CLAIM.search(text)
                if match:
                    offenders.append((card_id, key, match.group(0)))
    assert offenders == [], (
        "Training-cohort size asserted in a static card literal: "
        + "; ".join(f"{c}.{k} -> {m!r}" for c, k, m in offenders)
    )


def _walk_strings(value):
    """Yield every string anywhere inside a nested card value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk_strings(v)


# ---------------------------------------------------------------------------
# The rendered card must agree with the artifact, in both directions.
# ---------------------------------------------------------------------------

@pytest.fixture
def rendered(monkeypatch):
    """Render the triage card against a controllable provenance."""

    def _render(prov: dict, version=("test-version", "declared")):
        import services.triage_ml as triage_ml

        monkeypatch.setattr(triage_ml, "provenance", lambda: prov)
        monkeypatch.setattr(triage_ml, "model_version", lambda: version)
        return model_cards.get_card(TRIAGE)

    return _render


SYNTHETIC_PROV = {
    "dataset": "Kaggle Triagegeist (80k synthetic ED encounters)",
    "known": True,
    "is_synthetic": True,
    "metrics": {"oof_qwk": 0.9993, "oof_accuracy": 0.9987},
    "source": "artifact",
}


def test_synthetic_training_is_disclosed_in_the_caveat(rendered):
    """The word has to appear, in the field a reviewer reads for exactly this."""
    card = rendered(SYNTHETIC_PROV)
    assert "synthetic" in card["synthetic_data_caveat"].lower()
    assert card["training_data"]["is_synthetic"] is True
    assert card["training_data"]["source"] == SYNTHETIC_PROV["dataset"]


def test_synthetic_card_never_claims_clinical_validation(rendered):
    """A synthetic-trained model must not read as validated."""
    card = rendered(SYNTHETIC_PROV)
    assert card["performance"]["clinically_validated"] is False
    joined = " ".join(_walk_strings(card)).lower()
    assert "trains exclusively on real" not in joined
    assert "no synthetic" not in joined


def test_synthetic_metrics_are_labelled_as_a_ceiling(rendered):
    """99.87% accuracy without context is the most misleading true number here."""
    card = rendered(SYNTHETIC_PROV)
    interpretation = card["performance"]["interpretation"].lower()
    assert "ceiling" in interpretation
    assert card["performance"]["measured_on"] == SYNTHETIC_PROV["dataset"]
    # The real metrics still surface — honesty is not the same as hiding them.
    assert card["performance"]["oof_qwk"] == 0.9993


def test_absent_artifact_yields_unknown_not_a_guess(rendered):
    """No artifact must produce "unknown", never a plausible default.

    A card that admits it cannot read its provenance is embarrassing. A card that
    fills the gap with a confident string is a false HTI-1 disclosure.
    """
    card = rendered({"known": False, "source": "no_artifacts_loaded", "dataset": None})
    assert card["training_data"]["status"] == "unknown"
    assert card["training_data"]["source"] is None
    assert card["performance"]["status"] == "unknown"
    assert "unknown" in card["synthetic_data_caveat"].lower()
    # Silence must not be readable as reassurance.
    assert "do not treat the absence" in card["synthetic_data_caveat"].lower()


def test_non_synthetic_provenance_still_refuses_to_claim_validation(rendered):
    """Real training data is not the same as a validated clinical model."""
    card = rendered({
        "dataset": "Partner health system LDS 2024-2026",
        "known": True,
        "is_synthetic": False,
        "metrics": {"oof_qwk": 0.71},
        "source": "artifact",
    })
    assert card["training_data"]["is_synthetic"] is False
    assert card["performance"]["clinically_validated"] is False
    assert "licence" in card["data_provenance"]["consent_basis"].lower()


def test_card_reports_which_model_version_is_running(rendered):
    """A provenance claim is meaningless without saying which weights it describes."""
    card = rendered(SYNTHETIC_PROV, version=("sha256:abcd1234", "content_hash"))
    assert card["model_version_running"] == {
        "version": "sha256:abcd1234",
        "derived_from": "content_hash",
    }


# ---------------------------------------------------------------------------
# The summary procurement actually reads must not diverge from the card.
# ---------------------------------------------------------------------------

def test_transparency_summary_counts_the_derived_attributes(monkeypatch):
    """The triage row must not look less transparent than the card it summarises.

    Removing the static literals could have silently dropped the triage model's
    disclosed-attribute count, which is the number a CMIO scans first.
    """
    import services.triage_ml as triage_ml

    monkeypatch.setattr(triage_ml, "provenance", lambda: SYNTHETIC_PROV)
    monkeypatch.setattr(triage_ml, "model_version", lambda: ("v", "declared"))

    summary = model_cards.transparency_summary()
    row = next(m for m in summary["models"] if m["model_id"] == TRIAGE)
    assert "data_provenance" in row["hti1_attributes_disclosed"]
    assert "synthetic_data_caveat" in row["hti1_attributes_disclosed"]


def test_summary_renders_without_an_artifact_present():
    """/api/model-cards is unauthenticated and must not 500 on a bare container."""
    summary = model_cards.transparency_summary()
    assert summary["model_count"] == len(model_cards.CARDS)
    row = next(m for m in summary["models"] if m["model_id"] == TRIAGE)
    assert row["risk_tier"] == "tier_1_high"


# ---------------------------------------------------------------------------
# The shipped artifact does not describe itself. Production proved it.
# ---------------------------------------------------------------------------

BARE_TRIAGEGEIST_PROV = {
    "dataset": "triagegeist",
    "known": True,
    "is_synthetic": True,
    "synthetic_basis": "known_corpus",
    "corpus_note": "Kaggle Triagegeist — a synthetic ED triage corpus.",
    "metrics": {"oof_qwk": 0.9999},
    "source": "artifact",
}


def test_a_bare_corpus_name_is_still_disclosed_as_synthetic(rendered):
    """The artifact in S3 records only "triagegeist".

    Word-matching found nothing, so the first version of this fix published
    "the artifact does not mark it synthetic" — true about the artifact, and
    useless to the reader. Recognising the named corpus closes that.
    """
    card = rendered(BARE_TRIAGEGEIST_PROV)
    caveat = card["synthetic_data_caveat"]
    assert "TRAINED ON SYNTHETIC DATA" in caveat
    assert card["training_data"]["is_synthetic"] is True


def test_the_card_says_how_it_concluded_synthetic(rendered):
    """A reader must be able to audit the conclusion, not just accept it."""
    card = rendered(BARE_TRIAGEGEIST_PROV)
    assert "does not say 'synthetic'" in card["synthetic_data_caveat"]


def test_absence_of_a_marker_is_never_phrased_as_reassurance(rendered):
    """The non-synthetic branch must not read as a clean bill of health."""
    card = rendered({
        "dataset": "Partner health system LDS 2024-2026",
        "known": True,
        "is_synthetic": False,
        "synthetic_basis": None,
        "corpus_note": None,
        "metrics": {},
        "source": "artifact",
    })
    caveat = card["synthetic_data_caveat"]
    assert "not an attestation" in caveat
    assert "confirm provenance" in caveat


def test_the_real_shipped_dataset_string_is_recognised():
    """Guards the mapping itself against the live artifact's actual value."""
    from services import triage_ml

    assert any(
        key in "triagegeist" for key in triage_ml._KNOWN_SYNTHETIC_CORPORA
    ), "the corpus string the deployed artifact actually carries must be recognised"
