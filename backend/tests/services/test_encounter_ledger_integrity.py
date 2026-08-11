"""Three defects in the ledger's durable path, each of which broke the one claim
the ledger exists to make.

The encounter ledger is the spine of the shadow programme. Its promise to a
hospital is narrow and total: what it says happened, happened, and if anyone
edited it you can tell. All three defects below let that promise fail *quietly*,
which is worse than failing loudly — a ledger that reports an outage is doing its
job, and a ledger that reports success while the store disagrees is not a ledger.

  1. FABRICATION ON A CONTRADICTORY RE-READ. The SequenceTaken handler read
     `chain = _load_all(encounter_id) or chain + [entry]`. When the re-read came
     back empty, the `or` spliced in `entry` — the entry the conditional put had
     just REJECTED, so by definition the one row known not to be in the store.
     The process then reported it present and verify() returned ok. After a cold
     start the chain reloads from DynamoDB without it, and verify() reports a
     sequence gap: the ledger accusing itself of tampering over a record nobody
     touched.

  2. coverage=None SATISFIED THE UNCERTAINTY GATE. The check was `"coverage" not
     in uncertainty`, so the value that means "we did not work it out" passed the
     rule that exists to stop bare numbers being recorded. Every existing test
     supplied a real float, so nothing caught it.

  3. _load_all DID NOT PAGINATE. DynamoDB caps a Query at 1MB and signals the
     truncation only via LastEvaluatedKey. A truncated read makes record()
     allocate a sequence that already exists, so the encounter becomes
     permanently unwritable — while verify() walks the same prefix, finds it
     consistent, and returns ok.

These tests drive the durable path with a fake table rather than the in-memory
one, because all three defects live in code that `_use_dynamo()` gates off. The
existing suite runs entirely in local mode, which is exactly why none of this was
covered.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services import encounter_ledger as led


NOW = datetime(2026, 8, 11, 14, 0, tzinfo=timezone.utc)


def _uncertainty(coverage=0.9):
    return {"coverage": coverage, "conformal_set": [2, 3], "coverage_source": "declared_default"}


def _record(encounter_id="enc-1", model="triage_ml", **kw):
    kw.setdefault("uncertainty", _uncertainty())
    return led.record(
        encounter_id=encounter_id,
        model=model,
        model_version="v-test",
        observed_at=NOW,
        output={"esi_level": 3},
        **kw,
    )


# ---------------------------------------------------------------------------
# A fake DynamoDB table honouring the two behaviours that matter: the
# append-only ConditionExpression, and 1MB-style Query pagination.
# ---------------------------------------------------------------------------

class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeTable:
    """Minimal DynamoDB stand-in. `page_size` forces LastEvaluatedKey paging."""

    def __init__(self, page_size=None):
        self.items: dict[int, dict] = {}
        self.page_size = page_size
        self.query_calls = 0
        # When set, query() returns this instead of the real contents. Used to
        # simulate a store that answers a read inconsistently.
        self.force_empty_query = False

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803
        seq = int(Item["seq"])
        if ConditionExpression and seq in self.items:
            raise FakeClientError("ConditionalCheckFailedException")
        self.items[seq] = dict(Item)

    def query(self, **kwargs):
        self.query_calls += 1
        if self.force_empty_query:
            return {"Items": []}
        ordered = [self.items[s] for s in sorted(self.items)]
        start = 0
        esk = kwargs.get("ExclusiveStartKey")
        if esk:
            start = next(
                (i for i, it in enumerate(ordered) if int(it["seq"]) == int(esk["seq"])), -1
            ) + 1
        if self.page_size is None:
            return {"Items": ordered[start:]}
        page = ordered[start : start + self.page_size]
        resp = {"Items": page}
        if start + self.page_size < len(ordered):
            last = page[-1]
            resp["LastEvaluatedKey"] = {"encounter_id": last["encounter_id"], "seq": last["seq"]}
        return resp


@pytest.fixture
def durable(monkeypatch):
    """Run the ledger against a fake durable store instead of local mode."""

    def _install(page_size=None):
        table = FakeTable(page_size=page_size)
        monkeypatch.setattr(led, "_use_dynamo", lambda: True)
        monkeypatch.setattr(led, "_table", lambda: table)

        import botocore.exceptions

        monkeypatch.setattr(botocore.exceptions, "ClientError", FakeClientError, raising=False)
        led.reset()
        return table

    return _install


# ---------------------------------------------------------------------------
# 1. Fabrication on a contradictory re-read
# ---------------------------------------------------------------------------

def test_contradictory_reread_refuses_the_write_instead_of_inventing_it(durable):
    """SequenceTaken + empty re-read must raise, not splice a phantom entry.

    Before the fix this returned an Entry, left the phantom in the in-memory
    chain, and reported ok from verify() — while the store held nothing.
    """
    table = durable()
    table.items[1] = {"encounter_id": "enc-1", "seq": 1}  # someone else got there
    table.force_empty_query = True  # ...but the read will not admit it

    with pytest.raises(led.LedgerUnavailable) as exc:
        _record()

    assert "not been recorded" in str(exc.value)


def test_a_refused_write_leaves_no_trace_in_the_in_memory_chain(durable):
    """The phantom must not survive in `_entries` either.

    This is the half that made the old bug lethal: the caller could have ignored
    the return value, but the in-memory chain was mutated regardless, so every
    later read in that container was wrong too.
    """
    table = durable()
    table.items[1] = {"encounter_id": "enc-1", "seq": 1}
    table.force_empty_query = True

    with pytest.raises(led.LedgerUnavailable):
        _record()

    # Nothing fabricated: the store is the only truth, and it has one row that
    # this process did not write.
    assert led._entries.get("enc-1", []) == []


def test_a_genuine_race_still_rebuilds_on_the_winner(durable):
    """The fix must not break the case the fallback was there to serve.

    A real competing writer leaves a readable row. That path must still succeed,
    stacking on the winner's hash rather than raising.
    """
    table = durable()
    _record()  # seq 1, ours

    # Simulate a competitor landing seq 2 between our chain read and our put.
    original_put = table.put_item
    state = {"raced": False}

    def racing_put(Item, ConditionExpression=None):  # noqa: N803
        if not state["raced"] and int(Item["seq"]) == 2:
            state["raced"] = True
            table.items[2] = {
                "encounter_id": "enc-1", "seq": 2, "model": "event",
                "model_version": "other", "observed_at": NOW.isoformat(),
                "recorded_at": NOW.isoformat(), "inputs": "{}", "output": "{}",
                "prev_hash": None, "entry_hash": "deadbeef",
            }
            raise FakeClientError("ConditionalCheckFailedException")
        return original_put(Item, ConditionExpression)

    table.put_item = racing_put

    entry = _record()
    assert entry.seq == 3, "should have stacked on top of the competitor's entry"


# ---------------------------------------------------------------------------
# 2. The uncertainty gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "coverage",
    [None, "0.9", True, 0, -0.1, 1.5],
    ids=["none", "string", "bool", "zero", "negative", "above-one"],
)
def test_coverage_must_be_a_real_probability(durable, coverage):
    """A coverage key is not a coverage figure.

    `None` is the case that shipped: the key was present, so the gate passed,
    and the ledger recorded a prediction whose stated coverage was the absence of
    one. The others close the same door from the other side.
    """
    durable()
    with pytest.raises(led.MissingUncertainty):
        _record(uncertainty={"coverage": coverage, "conformal_set": [3]})


def test_a_real_coverage_still_passes(durable):
    durable()
    entry = _record(uncertainty=_uncertainty(0.9))
    assert entry.uncertainty["coverage"] == 0.9


def test_events_remain_exempt(durable):
    """Events are things that happened; they have no coverage rate."""
    durable()
    entry = _record(model="event", uncertainty=None)
    assert entry.model == "event"


# ---------------------------------------------------------------------------
# 3. Pagination
# ---------------------------------------------------------------------------

def test_load_all_follows_every_page(durable):
    """A chain longer than one page must load whole.

    Sized deliberately: at a 5-minute cadence a patient generates ~288 entries a
    day, so a multi-day boarding stay — the exact population the under-triage
    number is about — is where this bites.
    """
    table = durable(page_size=10)
    for _ in range(25):
        _record()
    led.reset()  # force a read-through rather than trusting the warm chain

    chain = led.timeline("enc-1")
    assert len(chain) == 25
    assert [e.seq for e in chain] == list(range(1, 26))
    assert table.query_calls >= 3, "should have paged rather than taking a prefix"


def test_a_long_encounter_stays_writable(durable):
    """The consequence, not just the mechanism.

    With a truncated read, record() re-derives a sequence that already exists,
    burns all 8 attempts against the same prefix, and raises LedgerUnavailable
    forever. The encounter becomes permanently unwritable — silently, because
    verify() still passes on the prefix.
    """
    durable(page_size=10)
    for _ in range(25):
        _record()
    led.reset()

    entry = _record()
    assert entry.seq == 26


def test_verify_sees_the_whole_chain_not_a_prefix(durable):
    """verify() reporting ok on a truncated prefix is the worst outcome here."""
    durable(page_size=10)
    for _ in range(25):
        _record()
    led.reset()

    result = led.verify("enc-1")
    assert result.ok
    assert result.checked == 25, "verify must not certify a prefix as the whole record"
