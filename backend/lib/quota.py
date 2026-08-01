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


# Hospital-NAT scenarios put many real patients behind one identity, so ceilings are
# generous. Cost-runaway is still bounded but legitimate retries / re-records never trip.
LIMITS: dict[str, Limit] = {
    "intake.start":      Limit("intake.start", per_hour=2000),
    "intake.submit":     Limit("intake.submit", per_hour=500),
    "transcribe":        Limit("transcribe", per_hour=2000),
    "scan_insurance":    Limit("scan_insurance", per_hour=500),
    "audio.seconds":     Limit("audio.seconds", per_hour=120000),
    "voice_simulator":   Limit("voice_simulator", per_hour=200),
    "pain_flag":         Limit("pain_flag", per_hour=30),
    # Auth + identity endpoints. Login is per-IP; hospital NAT can put a few
    # clinicians behind one identity, but 60/hr still blunts credential
    # stuffing. identity/lookup is a PHI enumeration surface — kept tight.
    "auth.login":        Limit("auth.login", per_hour=60),
    # Passwordless magic-link. Request is the email-send surface (tighter, to
    # blunt mailbox-bombing one address); verify is the token-redeem surface.
    "auth.magic_request": Limit("auth.magic_request", per_hour=30),
    "auth.magic_verify":  Limit("auth.magic_verify", per_hour=60),
    "identity.lookup":   Limit("identity.lookup", per_hour=120),
    # Workspace provisioning — unauthenticated onboarding. Tight ceiling
    # blunts slug-squatting / table-flooding while leaving room for a sales
    # team spinning up a handful of demos from one office IP.
    "hospitals.provision": Limit("hospitals.provision", per_hour=20),
    # Request-to-join is public (unauthenticated) — tight ceiling blunts spam
    # against a workspace's admin inbox.
    "onboarding.access_request": Limit("onboarding.access_request", per_hour=10),
    # Patient asking for their own care plan by SMS. Every send costs the clinic
    # money on their Twilio account, so this is the tightest ceiling here: a
    # patient needs one message, maybe two if the first did not arrive. Before
    # this existed the route had no limit at all and would send indefinitely.
    "sms.care_instructions": Limit("sms.care_instructions", per_hour=10),
    # Public patient status page. Polled by the waiting-room screen every few
    # seconds, so the ceiling is high; it exists to bound scraping, not polling.
    "patients.public_view": Limit("patients.public_view", per_hour=3000),
    # Appointment self-service. The confirmation code is six characters from a
    # 32-symbol alphabet, so roughly a billion combinations — safe against a
    # patient mistyping, not against a machine trying codes at speed. These
    # ceilings are what makes the code space actually hold up.
    "appointments.lookup": Limit("appointments.lookup", per_hour=60),
    "appointments.cancel": Limit("appointments.cancel", per_hour=30),
    "appointments.availability": Limit("appointments.availability", per_hour=300),
    # Inbound telephony. Twilio is the only legitimate caller, but the webhook
    # is a public URL: without a ceiling, anyone posting to it opens sessions and
    # generates speech at our expense.
    "voice.inbound": Limit("voice.inbound", per_hour=600),
}

# Per-upload absolute caps (checked before charging the hourly quota)
MAX_AUDIO_SECONDS = 300  # 5 min per single upload — covers verbose patients


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
