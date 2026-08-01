"""Unit tests for ``services.encounter_ledger``.

The ledger is the record of what every model saw and said during an encounter,
in order, with the time it said it. Two things depend on it being right:

  * The shadow-programme report. "Solace flagged at 22 min, the team recognised
    at 4h10" is a claim about the ledger, not about the model. If the ledger
    can be edited after the fact, the report is worthless as evidence and no
    quality department should accept it.
  * Any audit of an AI-influenced decision, which HTI-1 expects a health system
    to be able to produce.

So these tests are mostly about the properties that make a record trustworthy —
append-only, ordered, immutable once written, and detectably tampered with —
rather than about scoring anything. Scoring is tested elsewhere; this is the
paper trail.

Written before the implementation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# A hard import, deliberately. The rest of this suite uses importorskip, which
# turns "the module is broken" into "the tests were skipped" and lets CI go
# green on a red build. For a record that a hospital is meant to rely on, a
# missing module should fail loudly.
import services.encounter_ledger as el


T0 = datetime(2026, 8, 1, 14, 0, 0, tzinfo=timezone.utc)


def _obs(**overrides):
    """A well-formed observation. Every test starts from something valid so a
    failure points at the one thing the test changed."""
    base = dict(
        encounter_id="enc-1",
        model="triage_ml",
        model_version="stacked_ensemble_v1",
        observed_at=T0,
        inputs={"heart_rate": 118, "sbp": 92, "o2_sat": 94},
        output={"esi": 3},
        uncertainty={"set": [2, 3], "coverage": 0.9},
    )
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _clean():
    el.reset()
    yield
    el.reset()


# ── Appending ───────────────────────────────────────────────────────────────

def test_first_entry_gets_sequence_one():
    entry = el.record(**_obs())
    assert entry.seq == 1


def test_sequence_increments_per_encounter():
    el.record(**_obs())
    el.record(**_obs(observed_at=T0 + timedelta(minutes=5)))
    third = el.record(**_obs(observed_at=T0 + timedelta(minutes=10)))
    assert third.seq == 3


def test_sequences_are_independent_across_encounters():
    el.record(**_obs(encounter_id="enc-1"))
    el.record(**_obs(encounter_id="enc-1"))
    other = el.record(**_obs(encounter_id="enc-2"))
    assert other.seq == 1, "a second encounter must not inherit the first one's count"


def test_identical_timestamps_still_order_deterministically():
    """Two models can score the same patient in the same second. The ledger
    still has to say which was written first, or the report cannot reconstruct
    the sequence of events."""
    a = el.record(**_obs(model="triage_ml"))
    b = el.record(**_obs(model="deterioration_index"))
    assert (a.seq, b.seq) == (1, 2)
    assert [e.model for e in el.timeline("enc-1")] == ["triage_ml", "deterioration_index"]


# ── Reading back ────────────────────────────────────────────────────────────

def test_timeline_returns_entries_in_order():
    for i in range(5):
        el.record(**_obs(observed_at=T0 + timedelta(minutes=i)))
    assert [e.seq for e in el.timeline("enc-1")] == [1, 2, 3, 4, 5]


def test_timeline_of_unknown_encounter_is_empty_not_an_error():
    assert el.timeline("never-seen") == []


def test_round_trip_preserves_values():
    el.record(**_obs(inputs={"heart_rate": 118}, output={"esi": 3}))
    entry = el.timeline("enc-1")[0]
    assert entry.inputs == {"heart_rate": 118}
    assert entry.output == {"esi": 3}
    assert entry.model_version == "stacked_ensemble_v1"
    assert entry.observed_at == T0


def test_latest_returns_most_recent():
    el.record(**_obs(output={"esi": 3}))
    el.record(**_obs(observed_at=T0 + timedelta(minutes=30), output={"esi": 2}))
    assert el.latest("enc-1").output == {"esi": 2}


def test_latest_can_filter_by_model():
    el.record(**_obs(model="triage_ml", output={"esi": 3}))
    el.record(**_obs(model="deterioration_index", output={"score": 44}))
    assert el.latest("enc-1", model="triage_ml").output == {"esi": 3}


def test_latest_of_unknown_encounter_is_none():
    assert el.latest("never-seen") is None


# ── Immutability ────────────────────────────────────────────────────────────

def test_mutating_a_returned_entry_does_not_change_the_ledger():
    """Callers get a copy. Otherwise a caller can rewrite history by accident."""
    entry = el.record(**_obs())
    entry.inputs["heart_rate"] = 9999
    assert el.timeline("enc-1")[0].inputs["heart_rate"] == 118


def test_mutating_the_inputs_dict_after_recording_does_not_change_the_ledger():
    payload = {"heart_rate": 118}
    el.record(**_obs(inputs=payload))
    payload["heart_rate"] = 9999
    assert el.timeline("enc-1")[0].inputs["heart_rate"] == 118


def test_ledger_exposes_no_update_or_delete():
    """Append-only is a property of the module surface, not a convention. If
    someone adds an edit path later, this test is the thing that stops it."""
    forbidden = {"update", "delete", "remove", "edit", "amend", "overwrite", "pop"}
    exposed = {n for n in dir(el) if not n.startswith("_")}
    assert not (forbidden & exposed), f"ledger must stay append-only, found {forbidden & exposed}"


# ── Tamper evidence ─────────────────────────────────────────────────────────

def test_chain_verifies_on_an_untouched_ledger():
    for i in range(4):
        el.record(**_obs(observed_at=T0 + timedelta(minutes=i)))
    assert el.verify("enc-1").ok is True


def test_verify_is_true_for_an_empty_encounter():
    assert el.verify("never-seen").ok is True


def test_each_entry_chains_to_the_one_before_it():
    a = el.record(**_obs())
    b = el.record(**_obs(observed_at=T0 + timedelta(minutes=1)))
    assert b.prev_hash == a.entry_hash
    assert a.prev_hash is None, "the first entry has nothing before it"


def test_editing_a_stored_entry_is_detected():
    el.record(**_obs(output={"esi": 3}))
    el.record(**_obs(observed_at=T0 + timedelta(minutes=1), output={"esi": 3}))
    el._tamper_for_tests("enc-1", 1, output={"esi": 1})
    result = el.verify("enc-1")
    assert result.ok is False
    assert result.broken_at == 1


def test_deleting_a_stored_entry_is_detected():
    for i in range(3):
        el.record(**_obs(observed_at=T0 + timedelta(minutes=i)))
    el._drop_for_tests("enc-1", 2)
    assert el.verify("enc-1").ok is False


# ── The clinical rule ───────────────────────────────────────────────────────

def test_an_output_without_uncertainty_is_rejected():
    """The whole argument to a CMO is that this model says when it is unsure.
    If a bare number can reach the ledger, that argument is not true of the
    software, only of the slide."""
    with pytest.raises(el.MissingUncertainty):
        el.record(**_obs(uncertainty=None))


def test_an_empty_uncertainty_is_also_rejected():
    with pytest.raises(el.MissingUncertainty):
        el.record(**_obs(uncertainty={}))


def test_uncertainty_must_carry_a_coverage_figure():
    """A prediction set without a stated coverage rate is not a calibrated
    claim, it is a list."""
    with pytest.raises(el.MissingUncertainty):
        el.record(**_obs(uncertainty={"set": [2, 3]}))


def test_a_non_model_note_may_omit_uncertainty():
    """Not everything on the timeline is a prediction. Recording that the team
    moved the patient to resus is an event, not a claim, and has no coverage
    rate to state."""
    entry = el.record(**_obs(model="event", output={"event": "moved_to_resus"}, uncertainty=None))
    assert entry.seq == 1


# ── Input hygiene ───────────────────────────────────────────────────────────

def test_observed_at_must_be_timezone_aware():
    """A naive timestamp is ambiguous, and the report is a claim about minutes."""
    with pytest.raises(ValueError):
        el.record(**_obs(observed_at=datetime(2026, 8, 1, 14, 0, 0)))


def test_encounter_id_is_required():
    with pytest.raises(ValueError):
        el.record(**_obs(encounter_id=""))


def test_model_version_is_required():
    """An entry that cannot say which version produced it is not auditable, and
    HTI-1 asks for exactly this."""
    with pytest.raises(ValueError):
        el.record(**_obs(model_version=""))


def test_model_is_required():
    with pytest.raises(ValueError):
        el.record(**_obs(model=""))


def test_a_broken_link_is_distinguished_from_a_sequence_gap():
    """Deleting an entry shows up as a sequence gap. Re-pointing one entry's
    prev_hash leaves the sequence intact but breaks the chain, and the reason
    code has to say which happened, because they mean different things: a gap
    is a missing record, a broken link is an altered one."""
    el.record(**_obs())
    el.record(**_obs(observed_at=T0 + timedelta(minutes=1)))
    el._tamper_for_tests("enc-1", 2, prev_hash="0" * 64)
    result = el.verify("enc-1")
    assert result.ok is False
    assert result.broken_at == 2
    assert result.reason == "broken link"


def test_a_deletion_reports_a_sequence_gap():
    for i in range(3):
        el.record(**_obs(observed_at=T0 + timedelta(minutes=i)))
    el._drop_for_tests("enc-1", 2)
    assert el.verify("enc-1").reason == "sequence gap"
