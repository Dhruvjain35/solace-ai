"""COMP-002 and COMP-006 — the two controls that quietly stop working under load.

**COMP-002, audit trail.** ``lib/audit.py`` writes to DynamoDB and archives to S3,
and both failures are swallowed::

    except Exception as e:
        log.warning("audit write to DDB failed: %s", e)

If both backends fail, the request still succeeds, PHI is still disclosed, and
there is no record that it happened — with a warning as the only trace, in a log
nobody reads until afterwards. HIPAA §164.312(b) asks for audit controls, and a
trail that develops holes exactly when the system is unhealthy is the shape of
trail that is missing the incident you eventually need it for.

Not fixed by failing the request. Blocking a clinician from a chart because
logging is down trades a record-keeping problem for a patient-safety one. Fixed by
making the failure impossible to miss: error level, a process counter, and the
counter surfaced on /health so an operator sees it without reading logs.

**COMP-006, brute-force lockout.** Two defects, in opposite directions.

``check_lockout`` returns False on any exception, commented "fail open — don't
block legitimate login on DDB errors". The reasoning is sound and the scope is
too wide: a brute-force run heavy enough to throttle DynamoDB throws exactly this
exception, so the attack disables the control designed to stop it. The answer is
not to fail closed — a DynamoDB outage would lock every clinician out of an
emergency department — but to fall back to an in-process counter, which is weaker
than the shared one and much stronger than nothing.

And LOCKOUT_WINDOW_SECONDS, which the rule names, is applied by::

    if last_failed and (now - last_failed) > LOCKOUT_WINDOW_SECONDS and attempts <= 1:
        # Counter was reset by the increment above, which is fine
        pass

That is a no-op. The counter never resets, so five mistyped PINs spread across a
year lock an account as surely as five in a row.
"""
from __future__ import annotations

import time

import pytest


# ── COMP-002: an audit failure must be loud and countable ────────────────────

@pytest.fixture
def broken_backends(monkeypatch):
    from lib import audit

    def boom(*a, **kw):
        raise RuntimeError("DynamoDB unavailable")

    monkeypatch.setattr(audit, "_table", boom)
    monkeypatch.setattr(audit, "_archive_to_s3", boom)
    audit.reset_failure_count()
    return audit


def test_a_lost_audit_record_is_counted(broken_backends):
    audit = broken_backends
    audit.record(clinician_id="c1", clinician_name="Dr A", action="patients.detail",
                 source_ip="203.0.113.1", status_code=200, patient_id="pt-1")
    assert audit.failure_count() == 1


def test_a_lost_audit_record_logs_at_error_not_warning(broken_backends, caplog):
    import logging

    audit = broken_backends
    with caplog.at_level(logging.ERROR):
        audit.record(clinician_id="c1", clinician_name="Dr A", action="patients.detail",
                     source_ip=None, status_code=200, patient_id="pt-1")
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "both audit backends failed and nothing logged at error level"
    assert any("patients.detail" in r.message for r in errors), \
        "the error does not say which action went unrecorded"


def test_the_failure_log_carries_no_patient_identifier(broken_backends, caplog):
    """The record is retained for six years and read by people who may not have
    chart access, and SEC-002 exists to keep patient ids out of CloudWatch.
    Dumping the lost item into the log to save it would defeat both."""
    import logging

    audit = broken_backends
    with caplog.at_level(logging.ERROR):
        audit.record(clinician_id="c1", clinician_name="Dr A", action="patients.detail",
                     source_ip=None, status_code=200,
                     patient_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301")
    blob = " ".join(r.message for r in caplog.records)
    assert "3f2504e0" not in blob


def test_the_request_is_not_failed_by_an_audit_outage(broken_backends):
    """Blocking care because logging is down trades a record-keeping problem for
    a patient-safety one."""
    audit = broken_backends
    audit.record(clinician_id="c1", clinician_name="Dr A", action="patients.detail",
                 source_ip=None, status_code=200, patient_id="pt-1")  # must not raise


def test_health_surfaces_the_counter():
    """A counter nobody can read is a counter nobody acts on."""
    import os
    os.environ["SOLACE_MODE"] = "local"
    from fastapi.testclient import TestClient
    from main import app

    body = TestClient(app).get("/health").json()
    assert "audit_write_failures" in body


# ── COMP-006: the lockout must survive the load it exists to stop ────────────

@pytest.fixture
def ddb_down(monkeypatch):
    from lib import jwt_auth

    def boom(*a, **kw):
        raise RuntimeError("ProvisionedThroughputExceededException")

    monkeypatch.setattr(jwt_auth, "_table", boom)
    jwt_auth.reset_local_attempts()
    return jwt_auth


def test_the_lockout_still_bites_when_dynamodb_is_throwing(ddb_down):
    """A brute-force run heavy enough to throttle DynamoDB used to disable the
    control aimed at it. The in-process counter is weaker than the shared one,
    and much stronger than returning False."""
    jwt_auth = ddb_down
    cid = "c-under-attack"
    for _ in range(jwt_auth.MAX_FAILED_ATTEMPTS):
        jwt_auth.record_failed_attempt(cid)
    assert jwt_auth.check_lockout(cid) is True


def test_an_unrelated_clinician_is_not_locked_out_by_the_fallback(ddb_down):
    jwt_auth = ddb_down
    for _ in range(jwt_auth.MAX_FAILED_ATTEMPTS):
        jwt_auth.record_failed_attempt("c-under-attack")
    assert jwt_auth.check_lockout("dr-innocent") is False


def test_a_few_failures_do_not_lock_anyone_out(ddb_down):
    jwt_auth = ddb_down
    for _ in range(jwt_auth.MAX_FAILED_ATTEMPTS - 1):
        jwt_auth.record_failed_attempt("c-typo")
    assert jwt_auth.check_lockout("c-typo") is False


def test_the_attempt_window_actually_expires(ddb_down, monkeypatch):
    """LOCKOUT_WINDOW_SECONDS is named by the rule and applied by a `pass`. Five
    mistyped PINs a year apart should not lock an account."""
    jwt_auth = ddb_down
    cid = "c-slow-typist"
    for _ in range(jwt_auth.MAX_FAILED_ATTEMPTS - 1):
        jwt_auth.record_failed_attempt(cid)

    real_time = time.time
    monkeypatch.setattr(time, "time",
                        lambda: real_time() + jwt_auth.LOCKOUT_WINDOW_SECONDS + 60)

    jwt_auth.record_failed_attempt(cid)
    assert jwt_auth.check_lockout(cid) is False, \
        "attempts outside the window still counted toward the lockout"


def test_the_window_does_not_help_a_fast_attacker(ddb_down):
    """Resetting on a stale attempt must not become a way to reset on a fresh
    one. Five in quick succession still locks."""
    jwt_auth = ddb_down
    cid = "c-fast"
    for _ in range(jwt_auth.MAX_FAILED_ATTEMPTS):
        jwt_auth.record_failed_attempt(cid)
    assert jwt_auth.check_lockout(cid) is True


def test_the_documented_thresholds_are_what_the_code_uses():
    """COMP-006 names four numbers. They should be these."""
    from lib import jwt_auth

    assert jwt_auth.MAX_FAILED_ATTEMPTS == 5
    assert jwt_auth.LOCKOUT_WINDOW_SECONDS == 900
    assert jwt_auth.LOCKOUT_DURATION_SECONDS >= 1800
    assert jwt_auth.ACCESS_TTL_SECONDS <= 1800
