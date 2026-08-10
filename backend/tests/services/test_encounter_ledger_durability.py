"""The ledger has to survive the process that wrote it.

``services/encounter_ledger.py`` was built well and stored everything in a module
dict, with a docstring saying so::

    Storage is in-memory here. The DynamoDB backing ... is deliberately not
    written yet: the shape wants to be settled against real use first.

That was the right call when nothing used it. It is the wrong state to ship,
because the deployment target is Lambda: the dict lives for the life of a warm
container and then goes. A shadow programme whose central claim is "Solace
flagged this patient at 22 minutes and the team recognised it at 4 hours 10"
cannot rest on a store that loses last Tuesday whenever AWS recycles a container.

So this file drives the property the ledger actually needs: an entry written by
one process is readable, and still verifiable, by a different one.

The part worth doing properly is the append-only guarantee. In memory it is
enforced by not exposing an update function, which stops honest mistakes and
nothing else. In DynamoDB it is enforced by writing each entry with

    ConditionExpression="attribute_not_exists(seq)"

so the *database* refuses to overwrite an existing sequence number. Code that
tries to rewrite history fails at the storage layer, not at the manners layer.
Paired with an IAM policy that denies UpdateItem and DeleteItem on the table,
that is an immutability claim an auditor can check without reading our source.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

from services import encounter_ledger as ledger

NOW = datetime(2026, 8, 10, 14, 32, tzinfo=timezone.utc)
UNC = {"coverage": 0.9, "set": [2, 3]}


@pytest.fixture(autouse=True)
def clean():
    ledger.reset()
    yield
    ledger.reset()


def _record(enc="enc-1", model="triage_ml", seq_hint=None, **kw):
    return ledger.record(
        encounter_id=enc, model=model, model_version="v7",
        observed_at=NOW, output={"esi_level": 3}, uncertainty=UNC, **kw
    )


# ── Surviving the process ────────────────────────────────────────────────────

def test_entries_survive_a_module_reload(monkeypatch):
    """Standing in for a Lambda container recycle: same table, new process."""
    store = {}
    monkeypatch.setattr(ledger, "_persist", lambda e: store.__setitem__((e.encounter_id, e.seq), e))
    monkeypatch.setattr(ledger, "_load_all", lambda enc: [
        v for (k, s), v in sorted(store.items(), key=lambda kv: kv[0][1]) if k == enc
    ])

    _record()
    _record()
    ledger.reset()  # the container went away; the table did not

    restored = ledger.timeline("enc-1")
    assert len(restored) == 2
    assert [e.seq for e in restored] == [1, 2]


def test_the_chain_still_verifies_after_a_round_trip(monkeypatch):
    """A hash chain that only holds while the writer is alive proves nothing."""
    store = {}
    monkeypatch.setattr(ledger, "_persist", lambda e: store.__setitem__((e.encounter_id, e.seq), e))
    monkeypatch.setattr(ledger, "_load_all", lambda enc: [
        v for (k, s), v in sorted(store.items(), key=lambda kv: kv[0][1]) if k == enc
    ])

    for _ in range(3):
        _record()
    ledger.reset()

    result = ledger.verify("enc-1")
    assert result.ok is True
    assert result.checked == 3


def test_tampering_with_the_persisted_copy_is_still_caught(monkeypatch):
    """The property has to hold against the store, not just against the dict."""
    store = {}
    monkeypatch.setattr(ledger, "_persist", lambda e: store.__setitem__((e.encounter_id, e.seq), e))
    monkeypatch.setattr(ledger, "_load_all", lambda enc: [
        v for (k, s), v in sorted(store.items(), key=lambda kv: kv[0][1]) if k == enc
    ])

    for _ in range(3):
        _record()
    ledger.reset()

    # Somebody edits the middle row directly in the table.
    store[("enc-1", 2)].output = {"esi_level": 5}

    result = ledger.verify("enc-1")
    assert result.ok is False
    assert result.broken_at == 2


# ── Sequence allocation under concurrency ────────────────────────────────────

def test_concurrent_writers_get_distinct_sequence_numbers():
    """Two Lambdas can score the same encounter at once. Duplicate seq numbers
    would silently drop one of them and break the chain for both."""
    import threading

    errors = []

    def writer():
        try:
            for _ in range(10):
                _record(enc="enc-race")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writes raised: {errors}"
    seqs = [e.seq for e in ledger.timeline("enc-race")]
    assert seqs == list(range(1, 41)), f"sequence is not contiguous: {seqs[:5]}...{seqs[-5:]}"
    assert ledger.verify("enc-race").ok is True


def test_a_taken_sequence_number_is_retried_not_overwritten(monkeypatch):
    """The conditional-write path. The first attempt loses the race; the writer
    must take the next number rather than clobber the winner."""
    attempts = []
    real_persist = ledger._persist
    taken = {1}

    def flaky_persist(entry):
        attempts.append(entry.seq)
        if entry.seq in taken:
            taken.discard(entry.seq)
            raise ledger.SequenceTaken(entry.seq)
        real_persist(entry)

    monkeypatch.setattr(ledger, "_persist", flaky_persist)
    entry = _record(enc="enc-retry")
    assert attempts == [1, 2], f"did not retry onto the next seq: {attempts}"
    assert entry.seq == 2


def test_a_writer_gives_up_rather_than_spinning(monkeypatch):
    """If every sequence number is contended the writer must fail loudly, not
    loop forever inside a request."""
    monkeypatch.setattr(ledger, "_persist",
                        lambda e: (_ for _ in ()).throw(ledger.SequenceTaken(e.seq)))
    with pytest.raises(ledger.LedgerUnavailable):
        _record(enc="enc-hot")


# ── The in-memory path stays usable ──────────────────────────────────────────

def test_local_mode_needs_no_aws():
    """Every test above this line and the whole local dev loop depend on it."""
    _record(enc="enc-local")
    assert len(ledger.timeline("enc-local")) == 1
    assert ledger.verify("enc-local").ok is True


def test_the_public_surface_still_has_no_update_or_delete():
    """The original guarantee, restated after adding a storage layer — that is
    exactly when an innocent-looking `save` or `put` tends to appear."""
    forbidden = {"update", "delete", "remove", "edit", "modify", "set", "put", "save", "overwrite"}
    public = {n for n in dir(ledger) if not n.startswith("_")}
    assert not (public & forbidden), f"mutating names on the public surface: {public & forbidden}"


def test_persistence_failure_does_not_silently_drop_an_entry(monkeypatch):
    """A ledger that loses writes quietly is worse than no ledger: the gap looks
    like 'nothing happened' rather than 'we failed to record'."""
    monkeypatch.setattr(ledger, "_persist",
                        lambda e: (_ for _ in ()).throw(RuntimeError("table gone")))
    with pytest.raises(ledger.LedgerUnavailable):
        _record(enc="enc-broken")
