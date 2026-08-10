"""A score has to be able to say which model produced it.

The ledger refuses an entry with no ``model_version``, on the grounds that "an
entry that cannot say which version produced it is not auditable". Wiring triage
into it found that the artifacts have no version field at all — not in
``artifacts.pkl``, not in ``predict()``'s output, nowhere.

That matters more than it sounds. The shadow-programme claim is a comparison:
Solace said ESI 2 at 22 minutes, the team got there at 4h10. If a retrain lands
mid-programme and no entry records which model was speaking, the week-14 report
is averaging two different systems together and calling the result one number.

The fix is a content hash of the artifacts rather than a hand-maintained string.
A version somebody has to remember to bump is a version that eventually lies; a
digest of the bytes that produced the score cannot. If the artifacts do declare
their own version, that wins, because "v7-sepsis-recal" means something to a
person and ``sha256:4f2a…`` does not — and the entry records which of the two it
got, so nobody has to guess later.
"""
from __future__ import annotations

import hashlib

import pytest

from services import triage_ml


@pytest.fixture(autouse=True)
def clear_cache():
    triage_ml.model_version.cache_clear()
    yield
    triage_ml.model_version.cache_clear()


def test_a_version_is_always_available():
    """Even with no artifacts on disk. Returning None would make every ledger
    write fail, and 'the model is not loaded' is itself a fact about the score."""
    version, source = triage_ml.model_version()
    assert isinstance(version, str) and version
    assert source in {"declared", "content_hash", "absent"}


def test_a_declared_version_wins(monkeypatch, tmp_path):
    """`v7-sepsis-recal` means something to a person; a digest does not."""
    monkeypatch.setattr(triage_ml, "_load", lambda: {"model_version": "v7-sepsis-recal"})
    version, source = triage_ml.model_version()
    assert version == "v7-sepsis-recal"
    assert source == "declared"


def test_undeclared_artifacts_fall_back_to_a_content_hash(monkeypatch, tmp_path):
    """The case that exists today: real artifacts, no version field."""
    artifacts = tmp_path / "artifacts.pkl"
    artifacts.write_bytes(b"pretend this is a pickle")
    monkeypatch.setattr(triage_ml, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(triage_ml, "_load", lambda: {"some": "artifacts"})

    version, source = triage_ml.model_version()
    expected = hashlib.sha256(b"pretend this is a pickle").hexdigest()[:16]
    assert version == f"sha256:{expected}"
    assert source == "content_hash"


def test_the_hash_changes_when_the_artifacts_do(monkeypatch, tmp_path):
    """The whole reason to prefer a digest: a retrain that forgets to bump a
    version string still gets a different identity."""
    artifacts = tmp_path / "artifacts.pkl"
    monkeypatch.setattr(triage_ml, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(triage_ml, "_load", lambda: {"some": "artifacts"})

    artifacts.write_bytes(b"model A")
    first, _ = triage_ml.model_version()
    triage_ml.model_version.cache_clear()

    artifacts.write_bytes(b"model B - retrained, nobody bumped anything")
    second, _ = triage_ml.model_version()

    assert first != second


def test_no_artifacts_is_reported_and_not_faked(monkeypatch, tmp_path):
    monkeypatch.setattr(triage_ml, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(triage_ml, "_load", lambda: None)
    version, source = triage_ml.model_version()
    assert source == "absent"
    assert "no-artifacts" in version


def test_the_version_is_cached():
    """It hashes a file that is tens of megabytes. Doing that per prediction
    would cost more than the prediction."""
    triage_ml.model_version()
    info = triage_ml.model_version.cache_info()
    triage_ml.model_version()
    assert triage_ml.model_version.cache_info().hits > info.hits


def test_the_version_is_acceptable_to_the_ledger():
    """The requirement that started this: the ledger rejects a falsy version."""
    from datetime import datetime, timezone

    from services import encounter_ledger as ledger

    ledger.reset()
    version, _source = triage_ml.model_version()
    entry = ledger.record(
        encounter_id="enc-version", model="triage_ml", model_version=version,
        observed_at=datetime.now(timezone.utc), output={"esi_level": 3},
        uncertainty={"coverage": 0.9, "coverage_source": "declared_default"},
    )
    assert entry.model_version == version
    ledger.reset()
