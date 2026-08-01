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
    "MissingUncertainty",
    "VerifyResult",
    "latest",
    "record",
    "reset",
    "timeline",
    "verify",
]

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
        chain = _entries.setdefault(encounter_id, [])
        prev = chain[-1] if chain else None
        entry = Entry(
            encounter_id=encounter_id,
            seq=len(chain) + 1,
            model=model,
            model_version=model_version,
            observed_at=observed_at,
            # Deep copies on the way in, so a caller that reuses and mutates its
            # payload dict cannot retroactively change what we recorded.
            inputs=copy.deepcopy(inputs or {}),
            output=copy.deepcopy(output),
            uncertainty=copy.deepcopy(uncertainty),
            recorded_at=datetime.now(observed_at.tzinfo),
            prev_hash=prev.entry_hash if prev else None,
        )
        entry.entry_hash = _digest(entry)
        chain.append(entry)
        return copy.deepcopy(entry)


def timeline(encounter_id: str) -> list[Entry]:
    """Every entry for an encounter, in the order it was written."""
    with _lock:
        return [copy.deepcopy(e) for e in _entries.get(encounter_id, [])]


def latest(encounter_id: str, model: str | None = None) -> Entry | None:
    """The most recent entry, optionally for one model. ``None`` if there is
    nothing to return, which is not an error."""
    with _lock:
        chain = _entries.get(encounter_id, [])
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
        chain = _entries.get(encounter_id, [])
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
