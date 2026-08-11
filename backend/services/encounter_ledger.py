"""Append-only record of what every model saw and said during an encounter.

This is the spine of the shadow programme. When the week-14 report says "Solace
flagged this patient at 22 minutes and the team recognised it at 4 hours 10",
that is a claim about this ledger, not about the model. So the ledger has to be
worth believing on its own:

  * **Append-only.** There is no update and no delete on the public surface, and
    a test asserts that none appear later.
  * **Ordered.** Two models can score the same patient in the same second. A
    monotonic sequence number per encounter says which was written first, which
    wall-clock timestamps cannot.
  * **Immutable once written.** Callers get deep copies both ways. A caller that
    mutates what it passed in, or what it got back, does not rewrite history.
  * **Tamper-evident.** Each entry carries a hash of its own content plus the
    hash of the entry before it. Editing or removing an entry breaks the chain
    at a detectable point. This does not make tampering impossible, it makes it
    visible, which is the property an auditor actually needs.

One rule is enforced here rather than left to callers: **a model output must
arrive with an uncertainty estimate and a stated coverage figure.** The claim we
make to a hospital is that this system says when it is unsure. If a bare number
can reach the record, that claim is true of the pitch and false of the software.
Enforcing it at the write path is the only place it cannot be forgotten.

Events (`model="event"`) are exempt, because "the team moved the patient to
resus" is something that happened, not a prediction, and has no coverage rate.

Storage is in-memory here. The DynamoDB backing follows the same pattern as
``db.storage`` and is deliberately not written yet: the shape wants to be
settled against real use first, and a wrong table design is more expensive to
change than a wrong function.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = [
    "Entry",
    "LedgerUnavailable",
    "SequenceTaken",
    "MissingUncertainty",
    "VerifyResult",
    "latest",
    "record",
    "reset",
    "timeline",
    "verify",
]

LEDGER_TABLE = "solace-encounter-ledger"

# Predictions must state their uncertainty. Events are things that happened.
_EVENT_MODEL = "event"


class MissingUncertainty(ValueError):
    """A model output arrived without a calibrated uncertainty estimate."""


@dataclass
class Entry:
    encounter_id: str
    seq: int
    model: str
    model_version: str
    observed_at: datetime
    inputs: dict[str, Any]
    output: dict[str, Any]
    uncertainty: dict[str, Any] | None
    recorded_at: datetime
    prev_hash: str | None
    entry_hash: str = field(default="")


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    broken_at: int | None = None
    reason: str | None = None


_entries: dict[str, list[Entry]] = {}
_lock = threading.Lock()


class SequenceTaken(Exception):
    """Another writer already holds this sequence number for this encounter."""

    def __init__(self, seq: int):
        super().__init__(f"sequence {seq} is already taken")
        self.seq = seq


class LedgerUnavailable(RuntimeError):
    """The entry could not be durably recorded.

    Raised rather than swallowed. A ledger that drops writes quietly is worse
    than no ledger at all: the gap reads as "nothing happened to this patient"
    rather than "we failed to write it down", and the second is the one an
    auditor needs to see.
    """


# How many times a writer will step to the next sequence number before giving
# up. Contention is one competing writer per attempt, so anything past a handful
# means something is badly wrong and spinning inside a request will not fix it.
_MAX_SEQ_ATTEMPTS = 8


def _use_dynamo() -> bool:
    from lib.config import settings  # noqa: PLC0415

    return settings.solace_mode == "aws"


def _table():
    import boto3  # noqa: PLC0415

    from lib.config import settings  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(LEDGER_TABLE)


def _persist(entry: Entry) -> None:
    """Write one entry durably, refusing to overwrite an existing sequence.

    The ConditionExpression is the whole point. In memory, append-only is
    enforced by not exposing an update function, which stops honest mistakes and
    nothing else. Here the *database* rejects a write onto a sequence number
    that already exists, so code that tries to rewrite history fails at the
    storage layer rather than at the manners layer. Paired with an IAM policy
    denying UpdateItem and DeleteItem on this table, it is an immutability claim
    an auditor can check without reading our source.
    """
    if not _use_dynamo():
        return  # in-memory chain is the store in local mode

    from botocore.exceptions import ClientError  # noqa: PLC0415

    item = {
        "encounter_id": entry.encounter_id,
        "seq": entry.seq,
        "model": entry.model,
        "model_version": entry.model_version,
        "observed_at": entry.observed_at.isoformat(),
        "recorded_at": entry.recorded_at.isoformat(),
        "inputs": json.dumps(entry.inputs, sort_keys=True, default=str),
        "output": json.dumps(entry.output, sort_keys=True, default=str),
        "uncertainty": (
            json.dumps(entry.uncertainty, sort_keys=True, default=str)
            if entry.uncertainty is not None else None
        ),
        "prev_hash": entry.prev_hash,
        "entry_hash": entry.entry_hash,
    }
    try:
        _table().put_item(
            Item={k: v for k, v in item.items() if v is not None},
            ConditionExpression="attribute_not_exists(encounter_id) AND attribute_not_exists(seq)",
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise SequenceTaken(entry.seq) from e
        raise


def _load_all(encounter_id: str) -> list[Entry]:
    """Every persisted entry for an encounter, ordered by sequence.

    Paginated, and it has to be. DynamoDB caps a Query response at 1MB and
    reports the truncation only by returning ``LastEvaluatedKey`` — a caller
    that ignores it gets a prefix and no error. Every entry here carries its
    inputs, its output and a SHAP attribution as JSON, so a long encounter
    reaches 1MB on a timescale that matters: a patient scored every five
    minutes generates ~288 entries a day, and a boarding patient is exactly the
    population the under-triage number is about.

    The failure that produced was silent in both directions. ``record`` derives
    the next sequence from ``len(chain) + 1``, so a truncated read allocates a
    number that already exists; the conditional put rejects it; it retries eight
    times against the same truncated prefix and raises LedgerUnavailable. The
    encounter is then permanently unwritable. Meanwhile ``verify`` walks the
    same prefix, finds it internally consistent, and returns ok — so the record
    stops growing while continuing to report that it is intact.
    """
    if not _use_dynamo():
        return []

    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    table = _table()
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("encounter_id").eq(encounter_id),
        "ScanIndexForward": True,
        "ConsistentRead": True,
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return [_from_item(i) for i in items]


def _from_item(item: dict[str, Any]) -> Entry:
    return Entry(
        encounter_id=item["encounter_id"],
        seq=int(item["seq"]),
        model=item["model"],
        model_version=item["model_version"],
        observed_at=datetime.fromisoformat(item["observed_at"]),
        inputs=json.loads(item.get("inputs") or "{}"),
        output=json.loads(item.get("output") or "{}"),
        uncertainty=json.loads(item["uncertainty"]) if item.get("uncertainty") else None,
        recorded_at=datetime.fromisoformat(item["recorded_at"]),
        prev_hash=item.get("prev_hash"),
        entry_hash=item["entry_hash"],
    )


def _chain(encounter_id: str) -> list[Entry]:
    """The chain for an encounter, reading through to storage on a cold cache.

    A Lambda container that never saw this encounter has an empty dict and a
    full table. Without this read-through it would start numbering at 1 again
    and write a second, unlinked chain over the top of the real one.
    """
    chain = _entries.get(encounter_id)
    if chain is None:
        chain = _load_all(encounter_id)
        _entries[encounter_id] = chain
    return chain


def reset() -> None:
    """Drop everything. Test support, and the local-mode equivalent of a fresh
    table. Not exported to any router."""
    with _lock:
        _entries.clear()


def _digest(entry: Entry) -> str:
    """Hash of an entry's content plus its predecessor.

    `sort_keys` matters: two dicts that are equal must hash equal, and Python's
    insertion order would otherwise make an identical entry hash differently
    depending on how the caller happened to build the dict.
    """
    payload = json.dumps(
        {
            "encounter_id": entry.encounter_id,
            "seq": entry.seq,
            "model": entry.model,
            "model_version": entry.model_version,
            "observed_at": entry.observed_at.isoformat(),
            "inputs": entry.inputs,
            "output": entry.output,
            "uncertainty": entry.uncertainty,
            "prev_hash": entry.prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _check_uncertainty(model: str, uncertainty: dict[str, Any] | None) -> None:
    if model == _EVENT_MODEL:
        return
    if not uncertainty:
        raise MissingUncertainty(
            f"model {model!r} produced an output with no uncertainty estimate; "
            "a bare prediction cannot be recorded"
        )
    if "coverage" not in uncertainty:
        raise MissingUncertainty(
            f"model {model!r} supplied an uncertainty without a coverage figure; "
            "a prediction set with no stated coverage is not a calibrated claim"
        )
    # Presence was the whole check, so {"coverage": None} satisfied it. That is
    # the rule the ledger rests on being defeated by the value that means "we
    # did not work it out" — and it would have passed every test in this suite,
    # because every test supplied a real number. A key whose value is None is
    # not a stated coverage; it is the absence of one, spelled differently.
    coverage = uncertainty["coverage"]
    if coverage is None:
        raise MissingUncertainty(
            f"model {model!r} supplied coverage=None; a coverage key with no "
            "value is not a stated coverage figure"
        )
    if not isinstance(coverage, (int, float)) or isinstance(coverage, bool):
        raise MissingUncertainty(
            f"model {model!r} supplied a non-numeric coverage {coverage!r}; "
            "coverage is a probability and has to be a number"
        )
    if not 0 < float(coverage) <= 1:
        raise MissingUncertainty(
            f"model {model!r} supplied coverage {coverage!r}, which is outside "
            "(0, 1]; a coverage figure outside that range is not a probability"
        )


def record(
    *,
    encounter_id: str,
    model: str,
    model_version: str,
    observed_at: datetime,
    inputs: dict[str, Any] | None = None,
    output: dict[str, Any],
    uncertainty: dict[str, Any] | None = None,
) -> Entry:
    """Append one observation. Returns a copy of what was written.

    Raises ``MissingUncertainty`` if a model output has no calibrated estimate,
    and ``ValueError`` for anything that would make the entry unauditable.
    """
    if not encounter_id:
        raise ValueError("encounter_id is required")
    if not model:
        raise ValueError("model is required")
    if not model_version:
        raise ValueError(
            "model_version is required; an entry that cannot say which version "
            "produced it is not auditable"
        )
    if observed_at.tzinfo is None:
        raise ValueError(
            "observed_at must be timezone-aware; the report is a claim about "
            "minutes and a naive timestamp is ambiguous"
        )
    _check_uncertainty(model, uncertainty)

    with _lock:
        chain = _chain(encounter_id)
        last_error: Exception | None = None
        # Tracked separately from len(chain) so that stepping past a contended
        # number never requires putting something in the chain to make it longer.
        # The previous code advanced the sequence by appending the very entry the
        # store had just rejected, which is why the chain could disagree with the
        # store — see the SequenceTaken handler below.
        next_seq = len(chain) + 1

        for _attempt in range(_MAX_SEQ_ATTEMPTS):
            prev = chain[-1] if chain else None
            entry = Entry(
                encounter_id=encounter_id,
                seq=next_seq,
                model=model,
                model_version=model_version,
                observed_at=observed_at,
                # Deep copies on the way in, so a caller that reuses and mutates
                # its payload dict cannot retroactively change what we recorded.
                inputs=copy.deepcopy(inputs or {}),
                output=copy.deepcopy(output),
                uncertainty=copy.deepcopy(uncertainty),
                recorded_at=datetime.now(observed_at.tzinfo),
                prev_hash=prev.entry_hash if prev else None,
            )
            entry.entry_hash = _digest(entry)
            try:
                _persist(entry)
            except SequenceTaken as e:
                # Another writer took this number. Re-read the tail and rebuild
                # on top of whatever actually landed, rather than assuming our
                # own next number is free — their entry is now our prev_hash.
                last_error = e
                if not _use_dynamo():
                    # No durable store to reconcile against: in local mode the
                    # in-memory chain IS the store, and `_load_all` returns []
                    # by definition rather than because anything is wrong. Step
                    # past the contended number and rebuild. Nothing is appended
                    # to the chain, so the rejected entry is discarded rather
                    # than recorded — which is the distinction the old code lost.
                    next_seq += 1
                    continue
                reread = _load_all(encounter_id)
                if not reread:
                    # An empty re-read here is a contradiction, and it used to be
                    # papered over with `_load_all(...) or chain + [entry]`. That
                    # fallback spliced `entry` — which by definition did NOT
                    # persist, because the conditional put just rejected it — into
                    # the in-memory chain as though it had. The consequences were
                    # exactly backwards from what a ledger is for: this process
                    # went on reporting the entry as present and verify() returned
                    # ok, while the store held one fewer row. After the next cold
                    # start the chain reloads from DynamoDB, the fabricated entry
                    # is gone, and verify() reports a sequence gap — the ledger
                    # accusing itself of tampering over a record nobody touched.
                    #
                    # SequenceTaken means a row exists at that sequence. A read
                    # that comes back empty therefore is not telling the truth,
                    # and the only safe response to an untrustworthy read is to
                    # refuse the write. A caller that gets LedgerUnavailable knows
                    # the entry is not recorded. A caller that got the old
                    # behaviour was told it was.
                    raise LedgerUnavailable(
                        f"sequence {entry.seq} for encounter {encounter_id!r} was "
                        "taken, but re-reading the chain returned nothing; the "
                        "store is not answering consistently and this entry has "
                        "not been recorded"
                    ) from e
                chain = reread
                _entries[encounter_id] = chain
                next_seq = len(chain) + 1
                continue
            except Exception as e:  # noqa: BLE001
                raise LedgerUnavailable(
                    f"could not record entry for encounter {encounter_id!r}: {e}"
                ) from e
            chain.append(entry)
            return copy.deepcopy(entry)

        raise LedgerUnavailable(
            f"could not allocate a sequence number for encounter {encounter_id!r} "
            f"after {_MAX_SEQ_ATTEMPTS} attempts: {last_error}"
        )


def timeline(encounter_id: str) -> list[Entry]:
    """Every entry for an encounter, in the order it was written."""
    with _lock:
        return [copy.deepcopy(e) for e in _chain(encounter_id)]


def latest(encounter_id: str, model: str | None = None) -> Entry | None:
    """The most recent entry, optionally for one model. ``None`` if there is
    nothing to return, which is not an error."""
    with _lock:
        chain = _chain(encounter_id)
        for entry in reversed(chain):
            if model is None or entry.model == model:
                return copy.deepcopy(entry)
        return None


def verify(encounter_id: str) -> VerifyResult:
    """Walk the chain and report the first place it breaks.

    An encounter with no entries verifies. There is nothing to have tampered
    with, and treating absence as failure would make the result meaningless.
    """
    with _lock:
        chain = _chain(encounter_id)
        expected_prev: str | None = None
        for i, entry in enumerate(chain, start=1):
            if entry.seq != i:
                return VerifyResult(False, i, broken_at=i, reason="sequence gap")
            if entry.prev_hash != expected_prev:
                return VerifyResult(False, i, broken_at=i, reason="broken link")
            if _digest(entry) != entry.entry_hash:
                return VerifyResult(False, i, broken_at=i, reason="content edited")
            expected_prev = entry.entry_hash
        return VerifyResult(True, len(chain))


# ── Test-only trapdoors ─────────────────────────────────────────────────────
# Underscored so they are not part of the public surface, and so the
# append-only test that scans `dir()` does not trip on them. They exist so the
# tamper-detection tests can actually tamper. Nothing in the application may
# call these.

def _tamper_for_tests(encounter_id: str, seq: int, **changes: Any) -> None:
    with _lock:
        entry = _entries[encounter_id][seq - 1]
        for key, value in changes.items():
            setattr(entry, key, value)


def _drop_for_tests(encounter_id: str, seq: int) -> None:
    with _lock:
        del _entries[encounter_id][seq - 1]
