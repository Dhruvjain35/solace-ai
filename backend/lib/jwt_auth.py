"""JWT sign/verify + clinician PIN verification via bcrypt + brute-force lockout.

- Signing key lives in Secrets Manager `solace/clinician-auth`
- Clinician records with bcrypt-hashed PINs live in DDB `solace-clinicians`
- JWT: HS256, 30-min absolute expiry, sub=clinician_id, includes name + role + hospital
- Brute-force: 5 failed login attempts in 15 minutes triggers 30-minute lockout
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

ACCESS_TTL_SECONDS = 30 * 60  # 30 minutes absolute
MAX_FAILED_ATTEMPTS = 5       # lock after this many failures
LOCKOUT_WINDOW_SECONDS = 900  # 15-minute window for counting failures
LOCKOUT_DURATION_SECONDS = 1800  # 30-minute lockout

# JWT algorithm confusion hardening: the accepted algorithm set is a fixed
# constant and is NEVER read from the secret payload or the token header.
# Allowing the token to dictate its own algorithm enables the classic
# "alg":"none" bypass and HS/RS key-confusion attacks. HS256 is the only
# algorithm Solace ever signs with, so it is the only one we will verify.
JWT_ALGORITHMS = ["HS256"]

# A throwaway bcrypt hash used to burn a constant amount of CPU when a
# clinician record is missing, so an attacker cannot distinguish "unknown
# clinician" from "bad PIN" via response timing (username-enumeration oracle).
# Generated once with bcrypt.gensalt(); value is not a real credential.
_DUMMY_PIN_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO6PqkN5lF.B6Z6dQ8x9zXq0pY3uVwT1m"


@dataclass
class Session:
    clinician_id: str
    name: str
    role: str
    hospital_id: str
    exp: int


class AuthError(Exception):
    """Raised for any auth failure (bad PIN, expired token, unknown clinician)."""


@lru_cache(maxsize=1)
def _auth_secret() -> dict:
    """Fetch `solace/clinician-auth` once per cold start. Cached.

    Local mode uses a deterministic dev signing key so the whole auth flow
    (PIN + magic-link) runs on a laptop without AWS. This key is dev-only and
    never used in aws mode, where Secrets Manager is the sole source.
    """
    if settings.solace_mode != "aws":
        # Second lock on the same door. main.py refuses to boot a Lambda in local
        # mode, and this refuses to hand out the dev key there regardless of how
        # the process got started — an import-time path, a script, a future entry
        # point that skips the startup assertion. The key below is committed to
        # this repository, so anything signed with it is forgeable by anyone who
        # has read the source, and the cost of being wrong once is every
        # clinician token on the platform.
        from lib.config import is_deployed  # noqa: PLC0415

        if is_deployed():
            raise RuntimeError(
                "Refusing to issue the local dev signing key inside AWS Lambda. "
                "SOLACE_MODE must be 'aws' in a deployed environment."
            )
        return {
            "JWT_SIGNING_KEY": "local-dev-only-signing-key-not-for-production",
            "JWT_ALGORITHM": "HS256",
            "DEMO_CLINICIANS": {},
        }
    import boto3  # noqa: PLC0415

    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    resp = client.get_secret_value(SecretId="solace/clinician-auth")
    return json.loads(resp["SecretString"])


def _table(name: str):
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def find_clinician(hospital_id: str, name: str) -> dict | None:
    """Look up a clinician by their display name within a hospital."""
    resp = _table("solace-clinicians").query(
        IndexName="hospital_name-index",
        KeyConditionExpression="hospital_id = :h AND name_lower = :n",
        ExpressionAttributeValues={":h": hospital_id, ":n": name.lower().strip()},
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def verify_pin(plain_pin: str, stored_hash: str) -> bool:
    import bcrypt  # noqa: PLC0415

    try:
        return bcrypt.checkpw(plain_pin.encode(), stored_hash.encode())
    except Exception:  # noqa: BLE001
        return False


def dummy_verify() -> None:
    """Burn a bcrypt-equivalent amount of CPU without revealing anything.

    Called on the "unknown clinician" path so login latency is statistically
    indistinguishable from the "known clinician, bad PIN" path. Closes the
    username-enumeration timing oracle. Result is intentionally discarded.
    """
    import bcrypt  # noqa: PLC0415

    try:
        bcrypt.checkpw(b"timing-equalizer", _DUMMY_PIN_HASH.encode())
    except Exception:  # noqa: BLE001
        pass


def check_lockout(clinician_id: str) -> bool:
    """Return True if the clinician is currently locked out due to too many failed attempts."""
    try:
        tbl = _table("solace-clinicians")
        resp = tbl.get_item(
            Key={"clinician_id": clinician_id},
            ProjectionExpression="failed_attempts, locked_until",
            ConsistentRead=True,
        )
        item = resp.get("Item")
        if not item:
            return False
        locked_until = int(item.get("locked_until", 0))
        if locked_until and int(time.time()) < locked_until:
            return True
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("lockout check failed for %s: %s", clinician_id, e)
        return False  # fail open — don't block legitimate login on DDB errors


def record_failed_attempt(clinician_id: str) -> None:
    """Increment failed login counter. Triggers lockout at MAX_FAILED_ATTEMPTS."""
    try:
        now = int(time.time())
        tbl = _table("solace-clinicians")

        # Atomic increment of failed_attempts counter
        resp = tbl.update_item(
            Key={"clinician_id": clinician_id},
            UpdateExpression=(
                "SET failed_attempts = if_not_exists(failed_attempts, :zero) + :one, "
                "last_failed_at = :now"
            ),
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":now": now,
            },
            ReturnValues="ALL_NEW",
        )
        attrs = resp.get("Attributes", {})
        attempts = int(attrs.get("failed_attempts", 0))
        last_failed = int(attrs.get("last_failed_at", 0))

        # Check if window has expired — reset if so
        if last_failed and (now - last_failed) > LOCKOUT_WINDOW_SECONDS and attempts <= 1:
            # Counter was reset by the increment above, which is fine
            pass

        if attempts >= MAX_FAILED_ATTEMPTS:
            # Lock the account
            tbl.update_item(
                Key={"clinician_id": clinician_id},
                UpdateExpression="SET locked_until = :until",
                ExpressionAttributeValues={
                    ":until": now + LOCKOUT_DURATION_SECONDS,
                },
            )
            log.warning(
                "clinician %s locked out for %d minutes after %d failed attempts",
                clinician_id, LOCKOUT_DURATION_SECONDS // 60, attempts,
            )
    except Exception as e:  # noqa: BLE001
        log.warning("failed to record login failure for %s: %s", clinician_id, e)


def clear_failed_attempts(clinician_id: str) -> None:
    """Reset failed login counter on successful login."""
    try:
        _table("solace-clinicians").update_item(
            Key={"clinician_id": clinician_id},
            UpdateExpression="SET failed_attempts = :zero REMOVE locked_until",
            ExpressionAttributeValues={":zero": 0},
        )
    except Exception as e:  # noqa: BLE001
        log.warning("could not clear failed attempts for %s: %s", clinician_id, e)


def issue_token(clinician: dict) -> tuple[str, Session]:
    import jwt  # noqa: PLC0415

    now = int(time.time())
    sess = Session(
        clinician_id=clinician["clinician_id"],
        name=clinician["name"],
        role=clinician.get("role", "clinician"),
        hospital_id=clinician["hospital_id"],
        exp=now + ACCESS_TTL_SECONDS,
    )
    claims = {
        "sub": sess.clinician_id,
        "name": sess.name,
        "role": sess.role,
        "hid": sess.hospital_id,
        "iat": now,
        "exp": sess.exp,
    }
    token = jwt.encode(claims, _auth_secret()["JWT_SIGNING_KEY"], algorithm=JWT_ALGORITHMS[0])
    return token, sess


def verify_token(token: str) -> Session:
    import jwt  # noqa: PLC0415

    secret = _auth_secret()
    try:
        # Algorithm allowlist is the fixed JWT_ALGORITHMS constant — never the
        # secret payload, never the token header. This blocks "alg":"none" and
        # HS/RS key-confusion attacks. `require=["exp"]` rejects tokens that
        # omit an expiry; `verify_exp` enforces it. Existing 30-min demo tokens
        # already carry `exp` (see issue_token), so they keep validating until
        # they naturally expire — no mass 401 on deploy.
        claims = jwt.decode(
            token,
            secret["JWT_SIGNING_KEY"],
            algorithms=JWT_ALGORITHMS,
            options={"require": ["exp"], "verify_exp": True},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("token expired") from e
    except jwt.MissingRequiredClaimError as e:
        raise AuthError("token missing required claim") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}") from e
    try:
        return Session(
            clinician_id=claims["sub"],
            name=claims.get("name", ""),
            role=claims.get("role", "clinician"),
            hospital_id=claims["hid"],
            exp=claims["exp"],
        )
    except KeyError as e:
        raise AuthError(f"token missing required claim: {e}") from e


def update_last_login(clinician_id: str) -> None:
    """Best-effort update of the clinician's last_login_at."""
    from datetime import datetime, timezone  # noqa: PLC0415

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        _table("solace-clinicians").update_item(
            Key={"clinician_id": clinician_id},
            UpdateExpression="SET last_login_at = :ts",
            ExpressionAttributeValues={":ts": now_iso},
        )
    except Exception as e:  # noqa: BLE001
        log.warning("could not update last_login_at for %s: %s", clinician_id, e)
