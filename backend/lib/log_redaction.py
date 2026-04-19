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


def install() -> None:
    """Attach the redaction filter to every relevant logger.

    uvicorn names its access logger "uvicorn.access"; we also attach to root
    + our own "solace" logger so exceptions don't leak UUIDs from tracebacks.
    """
    f = RedactPatientUUIDsFilter()
    for name in ("uvicorn.access", "uvicorn.error", "solace", "", "mangum"):
        logger = logging.getLogger(name)
        # Avoid stacking duplicate filters if install() runs twice (warm starts)
        if not any(isinstance(h, RedactPatientUUIDsFilter) for h in logger.filters):
            logger.addFilter(f)
