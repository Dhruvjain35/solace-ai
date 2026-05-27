"""Clinician accounts + single-use magic-link tokens.

This is the identity spine for passwordless (magic-link) auth. It deliberately
mirrors db/storage.py's local/aws split so the full onboarding flow runs on a
laptop (solace_mode=local, in-memory) AND in production (DDB) with identical
call sites. jwt_auth.py still owns JWT signing, PIN verify, and lockout; this
module owns account lookup/creation and the magic-token lifecycle.

Tables (aws mode):
  - solace-clinicians     (existing) + new GSI `hospital_email-index`
                          (hospital_id HASH, email_lower RANGE)
  - solace-magic-tokens   (new) keyed by token_hash; `expires_at` is a DDB TTL.

Tokens are stored only as SHA-256 hashes; the raw token lives solely in the
emailed URL. Consumption is single-use via a conditional delete.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

CLINICIANS_TABLE = "solace-clinicians"
MAGIC_TOKENS_TABLE = "solace-magic-tokens"
ACCESS_REQUESTS_TABLE = "solace-access-requests"
EMAIL_INDEX = "hospital_email-index"
NAME_INDEX = "hospital_name-index"
HOSPITAL_INDEX = "hospital-index"

# Roles allowed to administer a workspace (invite/approve/onboard).
ADMIN_ROLES = {"admin", "chief"}

# ---- In-memory stores (local mode) -------------------------------------------------
_clinicians: dict[str, dict[str, Any]] = {}        # clinician_id -> record
_magic_tokens: dict[str, dict[str, Any]] = {}      # token_hash -> record
_access_requests: dict[str, dict[str, Any]] = {}   # request_id -> record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_aws() -> bool:
    return settings.solace_mode == "aws"


def _table(name: str):
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- Clinician accounts ------------------------------------------------------------
def find_clinician_by_email(hospital_id: str, email: str) -> dict | None:
    """Return the clinician record for (hospital, email) or None."""
    email_lower = email.lower().strip()
    if not email_lower:
        return None
    if not _is_aws():
        for rec in _clinicians.values():
            if rec.get("hospital_id") == hospital_id and rec.get("email_lower") == email_lower:
                return rec
        return None
    resp = _table(CLINICIANS_TABLE).query(
        IndexName=EMAIL_INDEX,
        KeyConditionExpression="hospital_id = :h AND email_lower = :e",
        ExpressionAttributeValues={":h": hospital_id, ":e": email_lower},
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def create_clinician(
    *,
    hospital_id: str,
    email: str,
    name: str,
    role: str = "clinician",
) -> dict:
    """Create a passwordless clinician account (no PIN). Idempotent on email."""
    existing = find_clinician_by_email(hospital_id, email)
    if existing:
        return existing
    cid = f"cln-{uuid.uuid4().hex[:16]}"
    record = {
        "clinician_id": cid,
        "hospital_id": hospital_id,
        "name": name.strip(),
        "name_lower": name.lower().strip(),
        "email": email.strip(),
        "email_lower": email.lower().strip(),
        "role": role,
        "auth_method": "magic_link",
        "created_at": _now_iso(),
        "last_login_at": None,
    }
    if not _is_aws():
        _clinicians[cid] = record
        return record
    _table(CLINICIANS_TABLE).put_item(Item=record)
    return record


# ---- Magic-link tokens -------------------------------------------------------------
def issue_magic_token(
    *,
    hospital_id: str,
    email: str,
    purpose: str = "login",
    role: str = "clinician",
    name: str | None = None,
    ttl_seconds: int | None = None,
) -> str:
    """Mint a single-use token, persist its hash with a TTL, return the RAW token.

    For `purpose="invite"`, the target clinician may not exist yet; `role` and
    `name` are carried on the token so the account can be created on consume.
    """
    raw = secrets.token_urlsafe(32)
    ttl = ttl_seconds or settings.magic_link_ttl_seconds
    expires_at = int(time.time()) + ttl
    record = {
        "token_hash": _hash_token(raw),
        "hospital_id": hospital_id,
        "email": email.strip(),
        "email_lower": email.lower().strip(),
        "purpose": purpose,
        "role": role,
        "name": (name or "").strip(),
        "created_at": _now_iso(),
        "expires_at": expires_at,
    }
    if not _is_aws():
        _magic_tokens[record["token_hash"]] = record
    else:
        _table(MAGIC_TOKENS_TABLE).put_item(Item=record)
    return raw


def consume_magic_token(raw: str) -> dict | None:
    """Validate + single-use-consume a token. Returns the record or None.

    None means: unknown, already used, or expired. Consumption is atomic — a
    second call with the same token returns None.
    """
    token_hash = _hash_token(raw)
    now = int(time.time())

    if not _is_aws():
        rec = _magic_tokens.pop(token_hash, None)  # pop = single-use
        if not rec:
            return None
        if int(rec.get("expires_at", 0)) < now:
            return None
        return rec

    tbl = _table(MAGIC_TOKENS_TABLE)
    try:
        # Conditional delete: only succeeds once. ReturnValues gives us the row.
        resp = tbl.delete_item(
            Key={"token_hash": token_hash},
            ConditionExpression="attribute_exists(token_hash)",
            ReturnValues="ALL_OLD",
        )
    except Exception:  # noqa: BLE001 — ConditionalCheckFailed = already consumed
        return None
    rec = resp.get("Attributes")
    if not rec:
        return None
    # DDB TTL deletion can lag; enforce expiry ourselves.
    if int(rec.get("expires_at", 0)) < now:
        return None
    return rec


def list_clinicians(hospital_id: str) -> list[dict]:
    """All clinician records for a workspace (admin views + onboarding counts)."""
    if not _is_aws():
        return [r for r in _clinicians.values() if r.get("hospital_id") == hospital_id]
    resp = _table(CLINICIANS_TABLE).query(
        IndexName=NAME_INDEX,
        KeyConditionExpression="hospital_id = :h",
        ExpressionAttributeValues={":h": hospital_id},
    )
    return resp.get("Items", [])


def list_admins(hospital_id: str) -> list[dict]:
    """Clinicians who can administer the workspace — used to notify on join requests."""
    return [c for c in list_clinicians(hospital_id) if c.get("role") in ADMIN_ROLES]


# ---- Access requests (request-to-join) ---------------------------------------------
def create_access_request(
    *, hospital_id: str, email: str, name: str, note: str = ""
) -> dict:
    """Record a clinician's request to join a workspace. Idempotent per pending
    (hospital, email): a duplicate pending request returns the existing one."""
    email_lower = email.lower().strip()
    for r in list_access_requests(hospital_id, status="pending"):
        if r.get("email_lower") == email_lower:
            return r
    rid = f"req-{uuid.uuid4().hex[:16]}"
    record = {
        "request_id": rid,
        "hospital_id": hospital_id,
        "email": email.strip(),
        "email_lower": email_lower,
        "name": name.strip(),
        "note": note.strip()[:500],
        "status": "pending",
        "created_at": _now_iso(),
    }
    if not _is_aws():
        _access_requests[rid] = record
    else:
        _table(ACCESS_REQUESTS_TABLE).put_item(Item=record)
    return record


def list_access_requests(hospital_id: str, status: str | None = None) -> list[dict]:
    if not _is_aws():
        items = [r for r in _access_requests.values() if r.get("hospital_id") == hospital_id]
    else:
        resp = _table(ACCESS_REQUESTS_TABLE).query(
            IndexName=HOSPITAL_INDEX,
            KeyConditionExpression="hospital_id = :h",
            ExpressionAttributeValues={":h": hospital_id},
        )
        items = resp.get("Items", [])
    if status:
        items = [r for r in items if r.get("status") == status]
    return sorted(items, key=lambda r: r.get("created_at", ""), reverse=True)


def get_access_request(request_id: str) -> dict | None:
    if not _is_aws():
        return _access_requests.get(request_id)
    resp = _table(ACCESS_REQUESTS_TABLE).get_item(Key={"request_id": request_id})
    return resp.get("Item")


def set_access_request_status(request_id: str, status: str, *, decided_by: str | None = None) -> None:
    if not _is_aws():
        rec = _access_requests.get(request_id)
        if rec:
            rec["status"] = status
            rec["decided_by"] = decided_by
            rec["decided_at"] = _now_iso()
        return
    _table(ACCESS_REQUESTS_TABLE).update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET #s = :s, decided_by = :by, decided_at = :at",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":by": decided_by, ":at": _now_iso()},
    )
