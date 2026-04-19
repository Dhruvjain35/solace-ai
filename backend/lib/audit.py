"""Fire-and-forget audit log writer — records who accessed what.

Writes to DDB `solace-audit-log` without blocking the request. TTL 30 days.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

AUDIT_TABLE = "solace-audit-log"
AUDIT_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def _table():
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(AUDIT_TABLE)


def _write_sync(item: dict[str, Any]) -> None:
    try:
        _table().put_item(Item=item)
    except Exception as e:  # noqa: BLE001
        log.warning("audit write failed: %s", e)


def record(
    *,
    clinician_id: str | None,
    clinician_name: str | None,
    action: str,
    patient_id: str | None = None,
    source_ip: str | None = None,
    request_id: str | None = None,
    status_code: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Enqueue an audit record. Non-blocking in async contexts, synchronous fallback."""
    now = datetime.now(timezone.utc)
    ts_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    ts_unix = int(now.timestamp() * 1000)
    audit_uuid = uuid.uuid4().hex[:12]
    item = {
        "clinician_id": clinician_id or "anonymous",
        "ts_id": f"{ts_unix}#{audit_uuid}",
        "clinician_name": clinician_name,
        "action": action,
        "patient_id": patient_id or "_",
        "ts": ts_iso,
        "source_ip": source_ip,
        "request_id": request_id,
        "status_code": status_code,
        "ttl": int(time.time()) + AUDIT_TTL_SECONDS,
    }
    if extra:
        item["extra"] = extra
    item = {k: v for k, v in item.items() if v is not None}

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _write_sync, item)
    except RuntimeError:
        _write_sync(item)

    # Automated response: feed abuse events into the blocklist counter.
    # Skip `abuse.quota_exceeded.*` — those are legit rate-limit hits, not malicious; counting
    # them toward a 1h auto-block double-punishes real users who reload the page a lot.
    # Also skip `abuse.content_sanitized` (soft-signal) and the blocklist-own events.
    _SKIP = (
        "abuse.blocklist_hit", "abuse.auto_blocked", "abuse.content_sanitized",
        "abuse.intake_nonce_ua_mismatch",
    )
    skip = action in _SKIP or action.startswith("abuse.quota_exceeded")
    if action.startswith("abuse.") and not skip:
        identity = None
        if extra:
            identity = extra.get("identity")
        if not identity and source_ip:
            # Approximate identity from IP when caller didn't pass one
            from lib.quota import identity_of  # noqa: PLC0415

            identity = identity_of(source_ip, None)
        if identity:
            from lib import blocklist  # noqa: PLC0415

            try:
                blocklist.record_abuse(identity, reason=action)
            except Exception as e:  # noqa: BLE001
                log.warning("blocklist increment failed: %s", e)
