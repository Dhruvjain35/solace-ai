"""EMAIL_DEV_ECHO must be impossible in a deployed environment.

``lib/config.py`` describes the setting accurately::

    #   email_dev_echo — when true, the magic link is returned in the API
    #     response body so sandbox/local flows are testable WITHOUT a mailbox.
    #     MUST stay false in production (it would leak login links).

The default is False and the comment is correct. The production Lambda had it set
to "true" anyway::

    $ aws lambda get-function-configuration --function-name solace-api
    { "SOLACE_MODE": "aws", "EMAIL_DEV_ECHO": "true", ... }

``POST /auth/magic/request`` is unauthenticated. With the echo on, it answers with
the clinician's working single-use login link in the response body, so knowing
somebody's email address is enough to sign in as them. No mailbox access, no
password, no second factor. The magic-link flow's entire security is that the
link goes to an inbox only the clinician can read.

A comment saying MUST is not a control. This makes the setting inert wherever it
would do harm, so the same env var cannot cause the same problem twice.

Forced off rather than refusing to boot, deliberately: the leak closes either
way, and taking the whole API down over an email flag trades one outage for
another. It logs at error level so the misconfiguration is still visible.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def env(monkeypatch):
    for var in ("AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "AWS_LAMBDA_RUNTIME_API"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_dev_echo_is_forced_off_inside_lambda(env, caplog):
    from lib import config

    env.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api")
    env.setattr(config.settings, "email_dev_echo", True, raising=False)

    config.harden_for_deployment()

    assert config.settings.email_dev_echo is False
    assert any("EMAIL_DEV_ECHO" in r.message for r in caplog.records), \
        "the setting was silently corrected with no record of it"


def test_dev_echo_survives_on_a_laptop(env):
    """Local development and the sandbox depend on this. A fix that breaks them
    gets reverted, and then the production leak comes back with it."""
    from lib import config

    env.setattr(config.settings, "email_dev_echo", True, raising=False)
    config.harden_for_deployment()
    assert config.settings.email_dev_echo is True


def test_the_link_is_not_echoed_when_the_setting_is_off(env, monkeypatch):
    """The property that actually matters, asserted at the function that builds
    the response rather than at the flag."""
    from lib import config
    from services import email

    env.setattr(config.settings, "email_dev_echo", False, raising=False)
    monkeypatch.setattr(email, "send_email",
                        lambda **kw: {"delivered": True, "provider": "test"})

    result = email.send_magic_link(
        to="clinician@example.org", link="https://app.example.org/verify?token=SECRET",
        hospital_name="Test Clinic", purpose="login",
    )
    assert "dev_link" not in result
    assert "SECRET" not in str(result)


def test_the_link_is_echoed_on_a_laptop(env, monkeypatch):
    from lib import config
    from services import email

    env.setattr(config.settings, "email_dev_echo", True, raising=False)
    monkeypatch.setattr(email, "send_email",
                        lambda **kw: {"delivered": True, "provider": "console"})

    result = email.send_magic_link(
        to="clinician@example.org", link="https://localhost:5173/verify?token=SECRET",
        hospital_name="Test Clinic", purpose="login",
    )
    assert result["dev_link"].endswith("token=SECRET")


def test_hardening_runs_at_startup():
    """A guard nothing calls is decoration."""
    import pathlib

    main = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text()
    assert "harden_for_deployment()" in main, \
        "main.py never calls harden_for_deployment(), so the guard never runs"
