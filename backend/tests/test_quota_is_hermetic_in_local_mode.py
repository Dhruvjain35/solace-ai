"""Rate limiting must work without DynamoDB, and must not reach for it locally.

`lib/quota.py` called boto3 unconditionally. Two things followed, neither of them
visible from reading the module:

  * On any machine with AWS credentials — a developer laptop, a CI container —
    running the test suite incremented counters in the **production**
    solace-quotas table. The suite was not hermetic and nothing said so.

  * Where the caller lacked permission on that table, `check_and_consume`'s
    blanket `except Exception: return  # fail-open` swallowed the AccessDenied
    and returned. Rate limiting was silently *off*, and every test that did not
    specifically assert throttling still passed. That is how CodeBuild found it:
    test_care_instructions_are_rate_limited failed with "no request was ever
    throttled: [200]" while 25 requests sailed through.

Fail-open is the right choice for a production infra blip — a DynamoDB outage
must not stop a real patient getting care. It is the wrong thing to have running
in a test, because it converts "the control is broken" into "the control is
absent" and then into a green build.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from lib import quota
from lib.config import settings


@pytest.fixture(autouse=True)
def clean_counters():
    quota.reset_local()
    yield
    quota.reset_local()


def _action_and_limit():
    """Pick a real quota'd action and its cap from the live config."""
    action, limit = next(iter(quota.LIMITS.items()))
    return action, limit.per_hour


def test_local_mode_enforces_the_limit(monkeypatch):
    """The behaviour the throttling test depends on."""
    monkeypatch.setattr(settings, "solace_mode", "local")
    action, cap = _action_and_limit()

    for _ in range(cap):
        quota.check_and_consume("ident-a", action)

    with pytest.raises(HTTPException) as exc:
        quota.check_and_consume("ident-a", action)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_local_mode_never_constructs_a_dynamodb_client(monkeypatch):
    """The hermeticity claim, asserted rather than assumed.

    If this fails, running the suite is writing to production tables again.
    """
    monkeypatch.setattr(settings, "solace_mode", "local")

    def explode():
        raise AssertionError(
            "quota.check_and_consume reached for DynamoDB in local mode — the "
            "test suite is mutating production counters"
        )

    monkeypatch.setattr(quota, "_table", explode)
    action, _ = _action_and_limit()
    quota.check_and_consume("ident-b", action)  # must not raise


def test_identities_have_separate_buckets(monkeypatch):
    """One noisy client must not throttle everybody else."""
    monkeypatch.setattr(settings, "solace_mode", "local")
    action, cap = _action_and_limit()

    for _ in range(cap):
        quota.check_and_consume("ident-c", action)

    quota.check_and_consume("ident-d", action)  # different identity, still fine


def test_an_unknown_action_is_not_quotad(monkeypatch):
    """Unchanged behaviour, restated so the local path cannot diverge from it."""
    monkeypatch.setattr(settings, "solace_mode", "local")
    for _ in range(200):
        quota.check_and_consume("ident-e", "not-a-real-action")


def test_aws_mode_still_uses_dynamodb(monkeypatch):
    """The local path must not leak into a deployed process.

    A process in aws mode has to use the shared store: per-container counters
    would let a caller multiply their limit by the number of warm Lambdas.
    """
    monkeypatch.setattr(settings, "solace_mode", "aws")
    called = {"n": 0}

    class _FakeTable:
        def update_item(self, **kwargs):
            called["n"] += 1
            return {"Attributes": {"count": 1}}

    monkeypatch.setattr(quota, "_table", lambda: _FakeTable())
    action, _ = _action_and_limit()
    quota.check_and_consume("ident-f", action)
    assert called["n"] == 1, "aws mode must go through the shared table"
