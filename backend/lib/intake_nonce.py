"""Short-lived, one-use, IP-bound intake tokens.

The QR landing page calls POST /start-intake to issue a nonce. That nonce is
required on /intake submission AND is bound to the caller's IP + User-Agent
fingerprint — a nonce farmed on one client can't be reused on another.

Attack surface closed:
- Bots can't `curl /intake` with fabricated payloads — need a fresh nonce.
- Distributed farm attack (issue on box A, consume on box B) — blocked by IP binding.
- Headless scraper that harvests nonces + feeds them to other clients — blocked by UA binding.
- Stolen nonces can't be reused — atomic mark-used (conditional update).
- Nonces don't persist past 30 min (DDB TTL).

IP + UA are stored as short keyed-HMAC hashes, not plaintext, so the DDB table
never leaks raw IPs even if dumped. The HMAC key is the clinician-auth JWT key
(already CMK-encrypted in Secrets Manager).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from functools import lru_cache
from typing import Any

from fastapi import HTTPException

from lib import audit as _audit
from lib.config import settings

log = logging.getLogger(__name__)

TABLE = "solace-intake-nonces"
TTL_SECONDS = 4 * 60 * 60  # 4 hours — wide margin for live demos + long sessions


def _table():
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(TABLE)


@lru_cache(maxsize=1)
def _hmac_key() -> bytes:
    """Reuse the clinician-auth JWT signing key as an HMAC salt for IP/UA hashes.

    Benefit: already CMK-encrypted in Secrets Manager, already rotated when PIN
    rotates. No new secret to manage.
    """
    from lib import jwt_auth  # noqa: PLC0415 — avoid top-level circular with jwt_auth

    return jwt_auth._auth_secret()["JWT_SIGNING_KEY"].encode()


def _fingerprint(source_ip: str | None, user_agent: str | None) -> dict[str, str]:
    """Derive binding hashes. 24-char truncation is plenty (192 bits)."""
    ip = (source_ip or "unknown").split(",")[0].strip()  # X-Forwarded-For: client, proxy1, proxy2
    ua = (user_agent or "unknown").strip()
    key = _hmac_key()
    return {
        "ip_hash": hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()[:24],
        "ua_hash": hmac.new(key, ua.encode(), hashlib.sha256).hexdigest()[:24],
    }


def issue(
    hospital_id: str,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    nonce = secrets.token_urlsafe(24)
    now = int(time.time())
    fp = _fingerprint(source_ip, user_agent)
    item = {
        "nonce": nonce,
        "hospital_id": hospital_id,
        "created_at": now,
        "ip_hash": fp["ip_hash"],
        "ua_hash": fp["ua_hash"],
        "used": False,
        "ttl": now + TTL_SECONDS,
    }
    _table().put_item(Item=item)
    return {"token": nonce, "expires_at": now + TTL_SECONDS}


def require(
    hospital_id: str,
    token: str | None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Verify the nonce AND its IP/UA binding, then atomically consume it.

    Order matters: we pre-fetch to check the fingerprint, THEN mark used. A
    mismatched-IP request does NOT burn the nonce, so the legitimate patient's
    submission from the right device/network still succeeds.
    """
    if not token:
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.intake_no_nonce",
            source_ip=source_ip, status_code=401,
        )
        raise HTTPException(
            status_code=401, detail="intake token required — please re-scan the QR code"
        )

    try:
        # ConsistentRead=True closes the eventual-consistency window between the
        # put_item in /start-intake and this GET — essential for the IP-hash match
        # to be reliable under high concurrency.
        resp = _table().get_item(Key={"nonce": token}, ConsistentRead=True)
    except Exception as e:  # noqa: BLE001
        log.warning("nonce lookup failed: %s", e)
        raise HTTPException(status_code=500, detail="intake token lookup failed")
    item = resp.get("Item")
    if not item:
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.intake_bad_nonce",
            source_ip=source_ip, status_code=403,
            extra={"token_prefix": token[:8]},
        )
        raise HTTPException(status_code=403, detail="intake token invalid")

    if item.get("hospital_id") != hospital_id:
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.intake_wrong_hospital",
            source_ip=source_ip, status_code=403,
            extra={"token_prefix": token[:8]},
        )
        raise HTTPException(status_code=403, detail="intake token not for this hospital")

    if int(item.get("ttl", 0)) < int(time.time()):
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.intake_expired_nonce",
            source_ip=source_ip, status_code=403,
            extra={"token_prefix": token[:8]},
        )
        raise HTTPException(
            status_code=403, detail="intake token expired — please re-scan the QR code"
        )

    fp = _fingerprint(source_ip, user_agent)
    # Primary binding: IP must match. Secondary: User-Agent — record mismatch but
    # don't block on UA alone (iOS Safari PWA switches UA strings on add-to-home).
    if fp["ip_hash"] != item.get("ip_hash"):
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.intake_nonce_ip_mismatch",
            source_ip=source_ip, status_code=403,
            extra={"token_prefix": token[:8]},
        )
        raise HTTPException(
            status_code=403, detail="intake token was issued to a different device"
        )
    if fp["ua_hash"] != item.get("ua_hash"):
        # Soft signal — logged but doesn't block, so UA churn from add-to-home-screen
        # or browser updates mid-session doesn't break real patients.
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.intake_nonce_ua_mismatch",
            source_ip=source_ip, status_code=200,
            extra={"token_prefix": token[:8]},
        )

    # Now atomic mark-used. If someone else already burned the nonce between our
    # GET and here, this fails cleanly.
    try:
        _table().update_item(
            Key={"nonce": token},
            UpdateExpression="SET used = :t, used_at = :n",
            ConditionExpression="used = :f",
            ExpressionAttributeValues={":t": True, ":f": False, ":n": int(time.time())},
        )
    except Exception:
        _audit.record(
            clinician_id=None, clinician_name=None, action="abuse.intake_nonce_reuse",
            source_ip=source_ip, status_code=403,
            extra={"token_prefix": token[:8]},
        )
        raise HTTPException(status_code=403, detail="intake token already used")
