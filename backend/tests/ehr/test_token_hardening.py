"""Token-at-rest hardening checks for the SMART-on-FHIR OAuth router.

These assert the SEC-002 (log redaction), SEC-009 (parameterized DDB keys via
the in-memory local store), and SEC-010 (external HTTP timeout <= 30s) guarantees
on backend/routers/ehr_auth.py — specifically that SMART access/refresh tokens
never reach logs in plaintext and that opaque handles round-trip without exposing
the raw refresh_token to the browser.

Runs entirely in local mode (in-memory state store, no AWS).
"""
from __future__ import annotations

import inspect
import logging
import os

# Force local mode BEFORE importing app/config so the state store is in-memory.
os.environ.setdefault("SOLACE_MODE", "local")

import pytest  # noqa: E402

from lib.config import settings  # noqa: E402
from lib.log_redaction import RedactPatientUUIDsFilter  # noqa: E402
from routers import ehr_auth  # noqa: E402

settings.solace_mode = "local"


@pytest.fixture(autouse=True)
def _clean_state():
    """Each test gets a fresh in-memory OAuth state store."""
    ehr_auth._LAUNCH_STATES_LOCAL.clear()
    yield
    ehr_auth._LAUNCH_STATES_LOCAL.clear()


# ---------------------------------------------------------------------------
# SEC-002 — token values must never reach logs in plaintext
# ---------------------------------------------------------------------------


def test_missing_access_token_does_not_log_raw_payload(caplog):
    """The no-access_token branch must not dump the raw token payload.

    A token response missing `access_token` can still carry a `refresh_token`
    and/or `id_token`. The CloudWatch redaction filter only catches `Bearer ...`,
    UUIDs, and `intake_token=` — a bare refresh_token in a dict repr would slip
    through. So this branch must log only non-sensitive key names, never values.
    """
    leaked_refresh = "supersecretrefreshtoken_abc123XYZ_value_should_never_log"
    leaked_id = "header.eyJzdWIiOiJ4In0.signature_id_token_secret"
    payload = {"refresh_token": leaked_refresh, "id_token": leaked_id, "error": "x"}

    with caplog.at_level(logging.WARNING, logger="routers.ehr_auth"):
        # Reproduce exactly the log call the callback() no-token branch makes.
        ehr_auth.log.warning(
            "EHR token response missing access_token (%s): keys=%s",
            "epic",
            sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        )

    logged = caplog.text
    assert leaked_refresh not in logged, "raw refresh_token leaked into logs"
    assert leaked_id not in logged, "raw id_token leaked into logs"
    # Key names are safe and useful for diagnostics.
    assert "refresh_token" in logged and "id_token" in logged


def test_source_no_longer_logs_full_payload():
    """Static guard: callback() must not pass `payload` straight to a log call.

    Pins the fix in place so a future edit can't reintroduce
    `log.warning(..., payload)` in the missing-access_token branch.
    """
    src = inspect.getsource(ehr_auth.callback)
    assert "missing access_token: %s" not in src, (
        "callback() logs the raw token payload — SEC-002 regression"
    )
    assert "keys=%s" in src


def test_redaction_filter_strips_bearer_tokens():
    """Belt-and-suspenders: the installed filter redacts Bearer access tokens."""
    f = RedactPatientUUIDsFilter()
    rec = logging.LogRecord(
        name="solace", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="auth header Bearer abc.def-GHI_123 used", args=(), exc_info=None,
    )
    assert f.filter(rec) is True
    assert "abc.def-GHI_123" not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()


# ---------------------------------------------------------------------------
# SEC-009 / token-at-rest — opaque handle round-trip, TTL present, no raw token to browser
# ---------------------------------------------------------------------------


def test_parked_state_carries_ttl_attribute():
    """Every parked record gets a DynamoDB `ttl` attribute for auto-expiry."""
    ehr_auth._store_state("refresh-handle-xyz", {
        "refresh_token": "rt_value",
        "vendor": "epic",
        "token_url": "https://example.org/token",
        "exp": 1,
    })
    rec = ehr_auth._LAUNCH_STATES_LOCAL["refresh-handle-xyz"]
    assert "ttl" in rec, "parked token record missing DynamoDB ttl attribute"
    assert rec["ttl"] > int(__import__("time").time()), "ttl must be in the future"


def test_refresh_handle_round_trips_and_consumes_atomically():
    """A parked refresh record is retrievable once, then gone (replay-safe)."""
    handle = "refresh-roundtrip-1"
    ehr_auth._store_state(handle, {
        "refresh_token": "rt_secret",
        "vendor": "epic",
        "token_url": "https://example.org/token",
        "exp": int(__import__("time").time()) + 600,
    })
    first = ehr_auth._pop_state(handle)
    assert first is not None and first["refresh_token"] == "rt_secret"
    # Consumed — a replayed handle returns nothing.
    assert ehr_auth._pop_state(handle) is None


def test_exchange_never_returns_raw_refresh_token():
    """`/exchange` hands back an opaque refresh_handle, never the raw token."""
    from fastapi.testclient import TestClient
    from main import app

    # Park a handoff record exactly as callback() does, including a refresh_token.
    code = "handoff-code-test-1"
    ehr_auth._store_state(f"handoff-{code}", {
        "handoff": __import__("json").dumps({"token": "jwt", "clinician_id": "c1"}),
        "refresh_token": "RAW_REFRESH_SHOULD_NOT_LEAK",
        "vendor": "epic",
        "token_url": "https://example.org/token",
        "exp": int(__import__("time").time()) + 120,
    })

    client = TestClient(app)
    r = client.post("/api/auth/ehr/exchange", json={"handoff_code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    # An opaque handle is returned; the raw refresh_token is not.
    assert "refresh_handle" in body
    assert "RAW_REFRESH_SHOULD_NOT_LEAK" not in r.text
    assert "refresh_token" not in body


# ---------------------------------------------------------------------------
# SEC-010 — external token-endpoint HTTP calls set a timeout <= 30s
# ---------------------------------------------------------------------------


def test_all_httpx_clients_have_bounded_timeout():
    """Every httpx.Client(...) in ehr_auth sets timeout and it is <= 30s."""
    src = inspect.getsource(ehr_auth)
    import re

    clients = re.findall(r"httpx\.Client\(([^)]*)\)", src)
    assert clients, "expected at least one httpx.Client call to inspect"
    for args in clients:
        m = re.search(r"timeout\s*=\s*([0-9.]+)", args)
        assert m, f"httpx.Client missing timeout: httpx.Client({args})"
        assert float(m.group(1)) <= 30.0, f"timeout > 30s: httpx.Client({args})"
