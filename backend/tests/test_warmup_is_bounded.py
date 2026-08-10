"""The warm ping must never be able to burn the whole Lambda timeout.

What it was doing, every four minutes, for weeks::

    START RequestId: 6bc59c64-...
    [WARNING] Matplotlib created a temporary cache directory at /tmp/matplotlib-...
    END RequestId: 6bc59c64-...
    REPORT Duration: 60000.00 ms  Billed Duration: 63353 ms  Memory Size: 2048 MB
           Max Memory Used: 642 MB  Status: timeout

Every warm ping hit the 60-second timeout. A timeout is a failure, so Lambda
retried it twice: 360 scheduled pings a day became 1,080 invocations, each billed
for a full minute at 2 GB. Eighteen hours of compute per day, on a function whose
API Gateway bill for the same month was one cent. It was the entire Lambda line
on the invoice, and because it never once completed, it never warmed anything.

Three separate things had to be true for that to happen, and each is worth its
own fix:

  the cause      matplotlib rebuilding its font cache on a read-only filesystem,
                 dragged in by unpickling artifacts.pkl -> catboost/shap.
                 Fixed in Dockerfile.lambda by baking the cache into the image.
  the multiplier Lambda's default two async retries. Now zero for this function.
  the blast      the warm path had no time budget, so "slow" became "the whole
                 timeout". That is this file.

A warm ping is an optimisation. An optimisation that can consume the entire
request budget is not one, so it gets a deadline and gives up.
"""
from __future__ import annotations

import time

import pytest

import main


class _Context:
    """Stand-in for the Lambda context object."""

    def __init__(self, remaining_ms: int = 60_000):
        self._remaining = remaining_ms

    def get_remaining_time_in_millis(self) -> int:
        return self._remaining


def test_a_slow_warmup_gives_up_rather_than_timing_out(monkeypatch):
    """The behaviour that cost the money: _load() never returning."""
    from services import triage_ml

    def never_returns():
        time.sleep(30)

    monkeypatch.setattr(triage_ml, "_load", never_returns)
    monkeypatch.setattr(main, "WARMUP_BUDGET_SECONDS", 0.5)

    started = time.perf_counter()
    result = main.handler({"warmup": True}, _Context())
    elapsed = time.perf_counter() - started

    assert elapsed < 5, f"warmup ran for {elapsed:.1f}s instead of giving up"
    assert result["statusCode"] == 200, "a slow warmup must not look like a crash"


def test_the_response_says_it_gave_up(monkeypatch):
    """Silently reporting success would hide a real cold-start regression from
    the deploy smoke test, which is the reason this path reports at all."""
    import json

    from services import triage_ml

    monkeypatch.setattr(triage_ml, "_load", lambda: time.sleep(30))
    monkeypatch.setattr(main, "WARMUP_BUDGET_SECONDS", 0.5)

    body = json.loads(main.handler({"warmup": True}, _Context())["body"])
    assert body["ml_ok"] is False
    assert "budget" in body["ml_error"] or "timed_out" in body["ml_error"]


def test_the_budget_respects_the_remaining_lambda_time(monkeypatch):
    """With 2 seconds left on the clock, a 20-second budget is not a budget."""
    assert main._warmup_budget(_Context(2_000)) < 2.0
    assert main._warmup_budget(_Context(60_000)) <= main.WARMUP_BUDGET_SECONDS
    assert main._warmup_budget(None) == main.WARMUP_BUDGET_SECONDS


def test_a_healthy_warmup_still_reports_success(monkeypatch):
    """The deploy smoke test reads ml_ok to catch broken imports and missing
    artifacts, so the happy path has to keep working."""
    import json

    from services import triage_ml

    monkeypatch.setattr(triage_ml, "_load", lambda: {"fake": "artifacts"})
    monkeypatch.setattr(triage_ml, "predict", lambda p, v: {"esi_level": 3})

    body = json.loads(main.handler({"warmup": True}, _Context())["body"])
    assert body["ml_ok"] is True


def test_missing_artifacts_are_still_reported_not_hidden(monkeypatch):
    import json

    from services import triage_ml

    monkeypatch.setattr(triage_ml, "_load", lambda: None)
    body = json.loads(main.handler({"warmup": True}, _Context())["body"])
    assert body["ml_ok"] is False
    assert body["ml_error"] == "artifacts_missing"


def test_the_budget_is_well_under_the_function_timeout():
    """60s is the configured Lambda timeout. A warm ping that can reach it is the
    bug this file exists for."""
    assert main.WARMUP_BUDGET_SECONDS <= 20
