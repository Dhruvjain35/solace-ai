"""CONSTITUTION SEC-006 — the redirect allowlist, and why prefix matching is not one.

The rule says /launch and /callback must validate redirect_uri against a
module-level allowlist. They do. The allowlist was::

    def _validate_redirect_uri(uri: str) -> bool:
        return any(uri.startswith(origin) for origin in _ALLOWED_REDIRECT_ORIGINS)

``startswith`` on a URL is string matching wearing a URL's clothes. Every one of
these passed::

    https://solaceaidemo.vercel.app.evil.com/steal      suffix append
    https://solaceaidemo.vercel.app%2eevil.com/x        encoded dot
    http://localhost:5173.evil.com/                     same, on a dev origin
    https://solaceaidemo.vercel.app@evil.com/           userinfo

The last is the one that matters most. A browser reads everything before the "@"
as credentials, so that URL goes to evil.com while reading as the real host to a
person skimming it. This is the redirect that carries a SMART-on-FHIR
authorization code.

Separately, ``/mock-authorize`` took an arbitrary redirect_uri and 302'd to it
with no check at all, and it is registered on the production API. That is an open
redirect on the hospital's own domain: a link that looks like it belongs to
Solace and lands on a phishing page. The mock endpoints are a demo affordance and
now refuse to exist in a deployed environment.

Comparison is on the parsed (scheme, host, port), which is the only thing an
allowlist of origins can mean.
"""
from __future__ import annotations

import os
import uuid

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402

settings.solace_mode = "local"

from main import app  # noqa: E402
from routers.ehr_auth import _validate_redirect_uri as valid  # noqa: E402


# ── The bypasses ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("uri", [
    "https://solaceaidemo.vercel.app.evil.com/steal",
    "https://solaceaidemo.vercel.app-evil.com/steal",
    "https://solaceaidemo.vercel.app%2eevil.com/x",
    "http://localhost:5173.evil.com/",
    "https://solaceaidemo.vercel.app@evil.com/",
    "https://evil.com/https://solaceaidemo.vercel.app",
    "//solaceaidemo.vercel.app.evil.com/x",
    "https://solaceaidemo.vercel.app:8443@evil.com/",
])
def test_lookalike_hosts_are_rejected(uri):
    assert valid(uri) is False, f"allowlist accepted {uri}"


@pytest.mark.parametrize("uri", [
    "http://solaceaidemo.vercel.app/cb",      # scheme downgrade on an https origin
    "https://localhost:5173/cb",              # scheme upgrade on an http origin
    "https://solaceaidemo.vercel.app:8443/cb",  # port that is not the origin's
])
def test_scheme_and_port_must_match_too(uri):
    """An origin is scheme, host and port. Two of the three is not a match."""
    assert valid(uri) is False, f"allowlist accepted {uri}"


@pytest.mark.parametrize("uri", ["", "   ", "javascript:alert(1)", "data:text/html,x",
                                 "not a url", "https://"])
def test_junk_is_rejected_without_raising(uri):
    assert valid(uri) is False


# ── The legitimate values, which must keep working ───────────────────────────

@pytest.mark.parametrize("uri", [
    "https://solaceaidemo.vercel.app",
    "https://solaceaidemo.vercel.app/",
    "https://solaceaidemo.vercel.app/ehr/callback",
    "https://solaceaidemo.vercel.app/ehr/callback?x=1",
    "https://solace-page.vercel.app/ehr/callback",
    "http://localhost:5173/ehr/callback",
    "http://127.0.0.1:3000/ehr/callback",
])
def test_the_real_origins_are_still_accepted(uri):
    assert valid(uri) is True, f"allowlist rejected a legitimate redirect: {uri}"


def test_host_comparison_is_case_insensitive():
    """DNS is case-insensitive, so an uppercase host is the same origin and
    rejecting it would be a bug that looks like a security feature."""
    assert valid("https://SolaceAIDemo.vercel.app/cb") is True


# ── The mock endpoints ───────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"},
                      follow_redirects=False)


def test_mock_authorize_will_not_redirect_off_platform(client):
    r = client.get("/api/auth/ehr/mock-authorize", params={
        "client_id": "x", "redirect_uri": "https://evil.com/phish", "state": "s",
    })
    assert r.status_code != 302 or "evil.com" not in r.headers.get("location", ""), \
        "open redirect: mock-authorize sent the caller to an arbitrary host"


def test_mock_authorize_still_works_for_a_real_origin(client):
    """The offline demo depends on it."""
    r = client.get("/api/auth/ehr/mock-authorize", params={
        "client_id": "x", "redirect_uri": "http://localhost:5173/ehr/callback", "state": "s",
    })
    assert r.status_code == 302
    assert r.headers["location"].startswith("http://localhost:5173/ehr/callback")


def test_the_mock_endpoints_are_absent_from_a_deployed_process(client, monkeypatch):
    """They exist so a fully-offline demo works. In production they are an
    unauthenticated vendor-authorize stand-in that approves anything."""
    from lib import config

    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api")
    for path, params in (
        ("/api/auth/ehr/mock-authorize", {"client_id": "x", "redirect_uri": "http://localhost:5173/", "state": "s"}),
        ("/api/auth/ehr/mock-fhir/epic/metadata", {}),
    ):
        r = client.get(path, params=params)
        assert r.status_code == 404, f"{path} answered {r.status_code} inside Lambda"
    assert config.is_deployed()
