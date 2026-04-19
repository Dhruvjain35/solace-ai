"""Idempotency for /intake so network-retried submissions don't create duplicate patients.

Flow:
  - Client generates a stable Idempotency-Key (UUID4) per intake attempt.
  - First request with that key → execute, cache response in DDB.
  - Any retry of the same key within 24h → return the cached response.

Storage: DDB `solace-idempotency` (PK=key, 24h TTL). Only response shape + status
are cached (never raw audio/image bytes).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

TABLE = "solace-idempotency"
TTL_SECONDS = 24 * 3600  # 24 hours


def _table():
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(TABLE)


def _normalize(key: str, scope: str) -> str:
    """Per-scope normalized key — a client's IKey for /intake can't collide with /transcribe."""
    raw = f"{scope}:{key}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def get_cached(key: str, *, scope: str) -> dict[str, Any] | None:
    if not key:
        return None
    try:
        resp = _table().get_item(Key={"key": _normalize(key, scope)}, ConsistentRead=True)
    except Exception as e:  # noqa: BLE001
        log.warning("idempotency get failed: %s", e)
        return None
    item = resp.get("Item")
    if not item:
        return None
    if int(item.get("ttl", 0)) < int(time.time()):
        return None
    try:
        return json.loads(item["response"])
    except (KeyError, json.JSONDecodeError):
        return None


def save(key: str, scope: str, response: dict[str, Any]) -> None:
    if not key:
        return
    try:
        _table().put_item(Item={
            "key": _normalize(key, scope),
            "scope": scope,
            "response": json.dumps(response, default=str),
            "ttl": int(time.time()) + TTL_SECONDS,
        })
    except Exception as e:  # noqa: BLE001
        log.warning("idempotency save failed: %s", e)
