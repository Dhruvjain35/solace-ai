"""CONSTITUTION SEC-001 — the app must not be able to serve without real secrets.

The rule says required secrets are hydrated from Secrets Manager before serving,
and that missing keys crash the app. Both halves are true in AWS mode. The
problem is what decides whether we are in AWS mode::

    solace_mode: Literal["local", "aws"] = "local"

The default is local. ``hydrate_from_secrets_manager()`` returns immediately when
the mode is not "aws", and ``jwt_auth._auth_secret()`` hands back a hardcoded
signing key with the same condition::

    "JWT_SIGNING_KEY": "local-dev-only-signing-key-not-for-production"

So a deployment that does not set SOLACE_MODE does not fail. It boots, skips
hydration entirely, and signs clinician JWTs with a string that is committed to
this repository. Anyone who can read the repo mints a valid clinician token for
any hospital. The crash SEC-001 promises never fires, because the code never
reached the branch that can crash.

Pydantic's Literal does catch a *typo* — SOLACE_MODE=awz raises at settings
construction. The gap is the variable being absent, which is indistinguishable
from a developer's laptop.

The fix is not documentation. A deployed process can tell it is deployed: Lambda
sets AWS_LAMBDA_FUNCTION_NAME and AWS_EXECUTION_ENV in the environment, and no
laptop has those. So the dev key becomes unreachable from anything running in
Lambda, whatever SOLACE_MODE says, and the failure mode goes from silent to loud.
"""
from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Strip the Lambda markers so each test sets its own."""
    for var in ("AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "AWS_LAMBDA_RUNTIME_API"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ── The gap ──────────────────────────────────────────────────────────────────

def test_a_lambda_process_cannot_run_in_local_mode(clean_env):
    """The whole finding in one assertion. If this passes, a deployment that
    forgets SOLACE_MODE crashes on boot instead of serving forged-token traffic."""
    from lib import config

    clean_env.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api")
    with pytest.raises(RuntimeError, match="(?i)deployed|lambda|SOLACE_MODE"):
        config.assert_deployment_is_configured("local")


def test_the_other_lambda_marker_is_enough_on_its_own(clean_env):
    from lib import config

    clean_env.setenv("AWS_EXECUTION_ENV", "AWS_Lambda_python3.11")
    with pytest.raises(RuntimeError):
        config.assert_deployment_is_configured("local")


def test_a_laptop_is_still_allowed_to_run_locally(clean_env):
    """The check has to leave local development alone or it gets reverted."""
    from lib import config

    config.assert_deployment_is_configured("local")  # must not raise


def test_a_lambda_in_aws_mode_is_fine(clean_env):
    from lib import config

    clean_env.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api")
    config.assert_deployment_is_configured("aws")  # must not raise


# ── The dev signing key ──────────────────────────────────────────────────────

def test_the_dev_signing_key_is_unreachable_from_a_deployed_process(clean_env):
    """Belt as well as braces. Even if something skips the startup assertion —
    an import-time code path, a test harness, a future entry point — the key
    itself refuses to be handed out inside Lambda."""
    from lib import jwt_auth

    clean_env.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api")
    jwt_auth._auth_secret.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            jwt_auth._auth_secret()
    finally:
        jwt_auth._auth_secret.cache_clear()


def test_local_development_still_gets_a_working_key(clean_env):
    from lib import jwt_auth

    jwt_auth._auth_secret.cache_clear()
    try:
        secret = jwt_auth._auth_secret()
        assert secret["JWT_SIGNING_KEY"]
        assert secret["JWT_ALGORITHM"] == "HS256"
    finally:
        jwt_auth._auth_secret.cache_clear()


def test_the_dev_key_is_obviously_not_a_production_key():
    """If it ever does escape, it should be recognisable at a glance in a log or
    a token dump rather than looking like a real secret."""
    from lib import jwt_auth

    jwt_auth._auth_secret.cache_clear()
    try:
        key = jwt_auth._auth_secret()["JWT_SIGNING_KEY"]
        assert "local" in key and "not-for-production" in key
    finally:
        jwt_auth._auth_secret.cache_clear()


# ── The signing key is a required secret, not an afterthought ────────────────

def test_the_signing_key_is_checked_at_startup_not_at_first_login(clean_env, monkeypatch):
    """hydrate_from_secrets_manager() requires exactly one key,
    DEMO_CLINICIAN_PIN. The JWT signing key lives in a different secret fetched
    lazily on the first login, so a missing or malformed solace/clinician-auth
    surfaces as a 500 for the first clinician to try, not as a failure to boot.
    SEC-001 says missing keys crash the app; this is the key whose absence
    matters most."""
    from lib import config

    monkeypatch.setattr(config.settings, "solace_mode", "aws", raising=False)

    calls = []

    def fake_auth_secret():
        calls.append(1)
        return {"JWT_SIGNING_KEY": "", "JWT_ALGORITHM": "HS256"}

    from lib import jwt_auth
    monkeypatch.setattr(jwt_auth, "_auth_secret", fake_auth_secret)

    with pytest.raises(RuntimeError, match="(?i)signing"):
        config.assert_signing_key_present()
    assert calls, "the signing key was never actually fetched"
