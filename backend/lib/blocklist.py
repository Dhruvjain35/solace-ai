"""Automated identity blocklist — moves from "logging abuse" to "shunning abusers".

When the same identity triggers N abuse audit events in T minutes, we put it on
a 1-hour blocklist. Patient endpoints check the list before any other work and
short-circuit with 429 if the identity is blocked.

Storage: DDB `solace-blocklist`:
  - PK=identity
  - TTL auto-removes expired blocks
  - `reason` + `count` fields for audit

The abuse-counter table is separate from quotas so the two rate-limiters don't
interfere (quotas count legitimate usage too; this counts only abuse events).
"""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException

from lib import audit as _audit
from lib.config import settings

log = logging.getLogger(__name__)

BLOCK_TABLE = "solace-blocklist"
BLOCK_SECONDS = 60 * 60          # 1-hour auto-block
ABUSE_WINDOW_SECONDS = 10 * 60   # 10-minute abuse counter window
ABUSE_THRESHOLD = 5              # events in window that triggers the block


def _tbl(name: str):
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def is_blocked(identity: str) -> tuple[bool, str | None]:
    """Check if the identity is currently blocked. ConsistentRead to kill race windows."""
    try:
        r = _tbl(BLOCK_TABLE).get_item(Key={"identity": identity}, ConsistentRead=True)
    except Exception as e:  # noqa: BLE001
        log.warning("blocklist lookup failed: %s", e)
        return False, None
    item = r.get("Item")
    if not item:
        return False, None
    if int(item.get("ttl", 0)) < int(time.time()):
        return False, None
    return True, item.get("reason")


def enforce(identity: str, *, source_ip: str | None = None) -> None:
    """Raise 429 if the identity is on the blocklist. Call at top of patient endpoints."""
    blocked, reason = is_blocked(identity)
    if blocked:
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.blocklist_hit",
            source_ip=source_ip, status_code=429,
            extra={"identity": identity, "reason": reason},
        )
        raise HTTPException(
            status_code=429,
            detail="temporarily rate-limited after abuse detection — retry in 1 hour",
            headers={"Retry-After": "3600"},
        )


def record_abuse(identity: str, reason: str) -> None:
    """Tick the abuse counter. On threshold breach, put the identity on the blocklist.

    Uses a rolling-bucket counter with the same atomic-increment pattern as quotas.
    """
    now = int(time.time())
    bucket_start = (now // ABUSE_WINDOW_SECONDS) * ABUSE_WINDOW_SECONDS
    key = f"{identity}#{bucket_start}"
    try:
        resp = _tbl("solace-quotas").update_item(
            Key={"bucket_key": key},
            UpdateExpression="ADD #c :one SET #i = if_not_exists(#i, :i), #a = :a, #ttl = :ttl",
            ExpressionAttributeNames={"#c": "count", "#i": "identity", "#a": "action", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":i": identity,
                ":a": "abuse_counter",
                ":ttl": bucket_start + ABUSE_WINDOW_SECONDS + 300,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(resp["Attributes"]["count"])
    except Exception as e:  # noqa: BLE001
        log.warning("abuse counter update failed: %s", e)
        return

    if count >= ABUSE_THRESHOLD:
        try:
            _tbl(BLOCK_TABLE).put_item(Item={
                "identity": identity,
                "reason": reason,
                "count": count,
                "created_at": now,
                "ttl": now + BLOCK_SECONDS,
            })
            _audit.record(
                clinician_id=None, clinician_name=None, action="abuse.auto_blocked",
                status_code=429,
                extra={"identity": identity, "reason": reason, "count": count},
            )
            log.warning("auto-blocked identity %s: %d abuse events (%s)", identity, count, reason)
        except Exception as e:  # noqa: BLE001
            log.warning("block failed for %s: %s", identity, e)
