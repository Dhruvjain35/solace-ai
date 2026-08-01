"""CloudWatch log redaction — strip patient_id UUIDs + Bearer tokens from access logs.

FastAPI + uvicorn log every request line including the path
(`POST /api/demo/patients/fbc01b0a-... /refine-triage 200`). That UUID is a
pointer to a patient record and must not persist in CloudWatch where searchers
without DDB permissions could correlate. Similarly for Authorization headers.

This module installs a logging.Filter on uvicorn + root that rewrites any
record's formatted message in-place before it leaves the process.

Not a substitute for CloudTrail — this is hygiene on Lambda stdout.
"""
from __future__ import annotations

import logging
import re

# UUID4 shape: 8-4-4-4-12 hex
_UUID_RX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# Bearer tokens in Authorization headers that might sneak into traceback dumps
_BEARER_RX = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
# Nonce tokens (secrets.token_urlsafe produces A-Z a-z 0-9 _ -, 32 chars)
_NONCE_RX = re.compile(r"(intake_token[=:]\s*)[A-Za-z0-9_\-]{20,}")


class RedactPatientUUIDsFilter(logging.Filter):
    """Rewrite `msg`/`args` of every log record to redact UUIDs + bearer tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Format the final message ourselves so we can redact even %-args
        try:
            msg = record.getMessage()
        except Exception:
            return True

        if not any(rx.search(msg) for rx in (_UUID_RX, _BEARER_RX, _NONCE_RX)):
            return True

        cleaned = _UUID_RX.sub("[PID]", msg)
        cleaned = _BEARER_RX.sub("Bearer [REDACTED]", cleaned)
        cleaned = _NONCE_RX.sub(r"\1[REDACTED]", cleaned)
        # Replace the record's msg + clear args so downstream formatting is a no-op
        record.msg = cleaned
        record.args = ()
        return True


_FILTER = RedactPatientUUIDsFilter()
_patched = False


def _attach(handler: logging.Handler) -> None:
    if not any(isinstance(f, RedactPatientUUIDsFilter) for f in handler.filters):
        handler.addFilter(_FILTER)


def install() -> None:
    """Attach the redaction filter to every handler that can emit a record.

    Filters go on HANDLERS, not on loggers, and that distinction is the whole
    point of this function.

    A Logger's filters run only against records created on that logger. A record
    from a child logger propagates to ancestor *handlers* and skips ancestor
    *filters* completely. The previous version attached to five named loggers,
    root among them, which reads as full coverage and is not: 97 modules in this
    codebase log through ``logging.getLogger(__name__)``, and not one of those
    records was ever seen by the filter. Only the single module using
    ``getLogger("solace")``, plus uvicorn's own lines, were redacted.

    Handlers are the choke point every record passes through regardless of which
    logger created it, so that is where the filter belongs.

    ``Logger.addHandler`` is also patched, once, because uvicorn and the Lambda
    runtime install their handlers at times we do not control. Attaching only to
    the handlers present right now would pass every test and still leak in
    production, where uvicorn configures logging after this import.
    """
    global _patched

    for name in ("", "uvicorn.access", "uvicorn.error", "solace", "mangum"):
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            _attach(handler)
        # Kept as well as, not instead of. Covers a record logged directly to
        # one of these loggers in a process that has no handlers attached yet.
        if not any(isinstance(f, RedactPatientUUIDsFilter) for f in logger.filters):
            logger.addFilter(_FILTER)

    if not _patched:
        _original_add_handler = logging.Logger.addHandler

        def add_handler(self: logging.Logger, hdlr: logging.Handler) -> None:
            _attach(hdlr)
            _original_add_handler(self, hdlr)

        logging.Logger.addHandler = add_handler  # type: ignore[method-assign]
        _patched = True
