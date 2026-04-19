"""Identity-bound rate + cost guards.

API Gateway throttles by raw IP, which proxies and botnets defeat. This adds a
second layer keyed on a stable "identity" derived from IP + User-Agent, and
tracks BOTH request count AND cost units (e.g. audio seconds).

Buckets are hourly, hashed into DDB `solace-quotas`. Atomic counter increments
(`ADD #c :units`) are strongly consistent — no race between parallel requests.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException

from lib import audit as _audit
from lib.config import settings

log = logging.getLogger(__name__)

TABLE = "solace-quotas"
BUCKET_SECONDS = 3600  # 1-hour buckets
TTL_GRACE = 300        # keep buckets 5 min after window closes for audit trail


@dataclass(frozen=True)
class Limit:
    action: str         # e.g. "intake.start", "intake.submit", "audio.seconds"
    per_hour: int       # units (req-count OR cost-units) allowed in a rolling hour


# Tuned for the demo. Real ED volume would be higher; these are meant to squash
# scripted abuse while staying generous enough for a judge testing the flow.
LIMITS: dict[str, Limit] = {
    # /start-intake is the cheapest endpoint and fires on every page mount —
    # keep the ceiling high enough that a patient reloading/returning doesn't hit it.
    "intake.start":      Limit("intake.start", per_hour=120),
    "intake.submit":     Limit("intake.submit", per_hour=10),
    "transcribe":        Limit("transcribe", per_hour=20),
    "scan_insurance":    Limit("scan_insurance", per_hour=20),
    "audio.seconds":     Limit("audio.seconds", per_hour=300),
}

# Per-upload absolute caps (checked before charging the hourly quota)
MAX_AUDIO_SECONDS = 120  # 2 min per single upload


def _table():
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(TABLE)


def identity_of(source_ip: str | None, user_agent: str | None) -> str:
    """Stable 24-char identity hash from IP + UA. Reuses the clinician-auth HMAC key."""
    from lib.intake_nonce import _hmac_key  # noqa: PLC0415 — shared salt

    ip = (source_ip or "unknown").split(",")[0].strip()
    ua = (user_agent or "unknown").strip()[:256]
    combined = f"{ip}|{ua}".encode()
    return hmac.new(_hmac_key(), combined, hashlib.sha256).hexdigest()[:24]


def _bucket_key(identity: str, action: str, now: int) -> str:
    bucket_start = (now // BUCKET_SECONDS) * BUCKET_SECONDS
    return f"{identity}#{action}#{bucket_start}"


def check_and_consume(
    identity: str,
    action: str,
    *,
    units: int = 1,
    source_ip: str | None = None,
) -> None:
    """Atomically add `units` to the identity's hourly counter for `action`.

    Raises 429 with a clear Retry-After-style message if this push would exceed
    the configured hourly limit. Cost-tracking (audio seconds) passes `units>1`.
    """
    limit = LIMITS.get(action)
    if limit is None:
        return  # action not quota'd — caller misspelled or opted out

    now = int(time.time())
    bucket_end = ((now // BUCKET_SECONDS) + 1) * BUCKET_SECONDS
    key = _bucket_key(identity, action, now)

    try:
        resp = _table().update_item(
            Key={"bucket_key": key},
            UpdateExpression="ADD #c :u SET #i = if_not_exists(#i, :i), #a = :a, #ttl = :ttl",
            ExpressionAttributeNames={"#c": "count", "#i": "identity", "#a": "action", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":u": units,
                ":i": identity,
                ":a": action,
                ":ttl": bucket_end + TTL_GRACE,
            },
            ReturnValues="UPDATED_NEW",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("quota update failed, failing-open: %s", e)
        return  # fail-open so infra blips don't break real patients

    new_count = int(resp["Attributes"]["count"])
    if new_count > limit.per_hour:
        _audit.record(
            clinician_id=None, clinician_name=None,
            action=f"abuse.quota_exceeded.{action}",
            source_ip=source_ip, status_code=429,
            extra={
                "identity": identity,
                "current": new_count,
                "limit_per_hour": limit.per_hour,
                "units_added": units,
            },
        )
        wait_seconds = bucket_end - now
        raise HTTPException(
            status_code=429,
            detail=(
                f"rate limit: {action} capped at {limit.per_hour}/hour — "
                f"retry in {wait_seconds}s"
            ),
            headers={"Retry-After": str(wait_seconds)},
        )


def check_audio_duration(
    seconds: float,
    identity: str,
    *,
    source_ip: str | None = None,
) -> None:
    """Enforce the per-upload absolute cap AND the per-identity rolling cost budget."""
    if seconds > MAX_AUDIO_SECONDS:
        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.audio_too_long",
            source_ip=source_ip, status_code=413,
            extra={
                "duration_seconds": round(seconds, 2),
                "cap_seconds": MAX_AUDIO_SECONDS,
                "identity": identity,
            },
        )
        raise HTTPException(
            status_code=413,
            detail=f"audio is {round(seconds)}s — cap is {MAX_AUDIO_SECONDS}s",
        )
    # Charge the identity's audio-seconds quota atomically
    check_and_consume(identity, "audio.seconds", units=int(seconds) or 1, source_ip=source_ip)
