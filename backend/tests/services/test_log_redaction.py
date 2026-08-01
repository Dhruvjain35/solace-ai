"""``lib.log_redaction`` must redact records from every logger, not just a few.

CONSTITUTION SEC-002 (L1) requires that patient UUIDs and Bearer tokens never
reach CloudWatch. ``install()`` attached the filter to five named loggers:
uvicorn.access, uvicorn.error, solace, root, and mangum.

That does not do what it looks like it does. In Python, a Logger's filters run
only against records created *on that logger*. A record from a child logger
propagates to ancestor **handlers**, and skips ancestor **filters** entirely.
So a filter on the root logger never sees anything logged by a child.

97 modules in this codebase call ``logging.getLogger(__name__)``. Exactly one
calls ``getLogger("solace")``. The practical effect was that essentially every
log line the application produced went out unredacted, while the module
responsible reported success.

These tests assert the property SEC-002 actually needs: a UUID logged from
anywhere does not reach a handler intact.
"""
from __future__ import annotations

import io
import logging

import pytest

from lib import log_redaction

UUID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


@pytest.fixture
def sink():
    """A handler on root, standing in for the one Lambda or uvicorn installs.

    Everything logged anywhere in the app ends up passing through here, which
    is exactly why it is the right place to assert against.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_filters = {name: logging.getLogger(name).filters[:]
                     for name in ("", "solace", "uvicorn.access", "uvicorn.error", "mangum")}

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    yield buf

    root.handlers, root.level = saved_handlers, saved_level
    for name, filters in saved_filters.items():
        logging.getLogger(name).filters = filters


def _emit(logger_name: str, message: str, *args):
    logging.getLogger(logger_name).info(message, *args)


# ── The failure that prompted this file ─────────────────────────────────────

@pytest.mark.parametrize("logger_name", [
    "services.triage_ml",
    "services.intake",
    "routers.intake",
    "routers.voice",
    "db.storage",
    "lib.auth",
])
def test_uuids_from_module_loggers_are_redacted(sink, logger_name):
    """The 97-module case. Every one of these uses getLogger(__name__)."""
    log_redaction.install()
    _emit(logger_name, "patient %s admitted", UUID)
    assert UUID not in sink.getvalue()
    assert "[PID]" in sink.getvalue()


def test_deeply_nested_logger_names_are_covered(sink):
    log_redaction.install()
    _emit("services.voice_agent.session.inner", "patient %s", UUID)
    assert UUID not in sink.getvalue()


# ── The cases that already worked, which must keep working ──────────────────

def test_the_solace_logger_is_still_redacted(sink):
    log_redaction.install()
    _emit("solace", "patient %s", UUID)
    assert UUID not in sink.getvalue()


def test_uvicorn_access_lines_are_still_redacted(sink):
    log_redaction.install()
    _emit("uvicorn.access", 'POST /api/demo/patients/%s/refine-triage 200', UUID)
    assert UUID not in sink.getvalue()


# ── The other two secrets the filter claims to handle ───────────────────────

def test_bearer_tokens_from_module_loggers_are_redacted(sink):
    log_redaction.install()
    _emit("services.fhir_writer", "calling with Authorization: Bearer abc.def-123_XYZ")
    out = sink.getvalue()
    assert "abc.def-123_XYZ" not in out
    assert "Bearer [REDACTED]" in out


def test_intake_nonces_from_module_loggers_are_redacted(sink):
    log_redaction.install()
    _emit("routers.intake", "redeeming intake_token=Ab3xY7zQ9mNp2LkRs5TvWu8CdEfGhJ1K")
    out = sink.getvalue()
    assert "Ab3xY7zQ9mNp2LkRs5TvWu8CdEfGhJ1K" not in out
    assert "[REDACTED]" in out


# ── Handlers that appear later ──────────────────────────────────────────────

def test_a_handler_added_after_install_still_redacts(sink):
    """uvicorn configures its handlers when it starts, which can be after our
    import. A fix that only walks the handlers present at install time would
    pass every test above and still leak in production."""
    log_redaction.install()

    late = io.StringIO()
    logging.getLogger().addHandler(logging.StreamHandler(late))
    _emit("services.triage_ml", "patient %s", UUID)

    assert UUID not in late.getvalue()


# ── Hygiene ─────────────────────────────────────────────────────────────────

def test_install_is_idempotent(sink):
    """Lambda warm starts re-import the module. Filters must not stack."""
    for _ in range(3):
        log_redaction.install()
    _emit("services.triage_ml", "patient %s", UUID)
    out = sink.getvalue()
    assert out.count("[PID]") == 1, "redaction applied more than once per record"


def test_messages_without_secrets_are_untouched(sink):
    log_redaction.install()
    _emit("services.triage_ml", "scored 412 encounters in 1.2s")
    assert "scored 412 encounters in 1.2s" in sink.getvalue()


def test_the_filter_survives_a_record_it_cannot_format():
    """A malformed format string must not turn a log call into an exception
    inside the redaction filter.

    Asserted against the filter directly rather than through a handler. A
    handler's formatter raises on `"%d" % "str"` regardless of what we do, which
    is CPython's behaviour and not ours to test. What is ours is that the filter
    passes the record on instead of adding a second failure on top.
    """
    record = logging.LogRecord(
        name="services.triage_ml", level=logging.INFO, pathname=__file__, lineno=1,
        msg="bad format %d", args=("not-an-int",), exc_info=None,
    )
    assert log_redaction.RedactPatientUUIDsFilter().filter(record) is True


def test_the_filter_redacts_before_a_handler_ever_formats():
    """Redaction happens on msg/args, so a secret is gone from the record
    itself. Anything downstream, including a handler that formats differently,
    sees the cleaned version."""
    record = logging.LogRecord(
        name="services.triage_ml", level=logging.INFO, pathname=__file__, lineno=1,
        msg="patient %s", args=(UUID,), exc_info=None,
    )
    log_redaction.RedactPatientUUIDsFilter().filter(record)
    assert UUID not in str(record.msg)
    assert record.args in ((), None)
