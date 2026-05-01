"""Per-call session state. Backed by `solace-calls` DynamoDB table in AWS mode,
in-memory dict in local mode. Lifetime is one phone call (or one simulator session).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

TABLE = "solace-calls"
TTL_DAYS = 90

# In-memory store for local mode + as a hot cache for AWS mode (one call's
# turn-taking happens inside a few minutes, so a Lambda warm container can
# answer without re-fetching DDB on every webhook).
_calls: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def hash_phone(phone: str) -> str:
    """Last-4 + sha256 hash, so call rows don't store raw PII numbers in plaintext."""
    if not phone:
        return ""
    last4 = phone[-4:] if len(phone) >= 4 else phone
    h = hashlib.sha256(phone.encode()).hexdigest()[:16]
    return f"{last4}:{h}"


def start(*, hospital_id: str, caller_phone: str | None, language: str, channel: str,
          twilio_call_sid: str | None = None) -> dict[str, Any]:
    """Open a new call session. Returns the seed dict (also persisted)."""
    call_id = twilio_call_sid or f"sim-{uuid.uuid4().hex[:12]}"
    record = {
        "call_id": call_id,
        "hospital_id": hospital_id,
        "language": (language or "en")[:2],
        "channel": channel,                # "twilio" | "simulator"
        "caller_phone_hash": hash_phone(caller_phone or ""),
        "started_at": _now_iso(),
        "status": "active",
        "transcript": [],                  # list[{"role", "text", "ts"}]
        "tools_called": [],                # list[{"name", "input", "result_summary"}]
        "history": [],                     # Claude messages array — internal only
        "intent": None,
        "escalation": None,                # "human" | "911" | None
        "ttl": int(time.time()) + TTL_DAYS * 86400,
    }
    _calls[call_id] = record
    if settings.solace_mode == "aws":
        _ddb_put(record)
    return record


def get(call_id: str) -> dict[str, Any] | None:
    if call_id in _calls:
        return _calls[call_id]
    if settings.solace_mode == "aws":
        rec = _ddb_get(call_id)
        if rec:
            _calls[call_id] = rec
        return rec
    return None


def update(call_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    rec = get(call_id)
    if not rec:
        return None
    rec.update(patch)
    rec["updated_at"] = _now_iso()
    _calls[call_id] = rec
    if settings.solace_mode == "aws":
        _ddb_put(rec)
    return rec


def append_turn(call_id: str, *, role: str, text: str) -> None:
    rec = get(call_id)
    if not rec:
        return
    rec.setdefault("transcript", []).append({
        "role": role, "text": text[:1000], "ts": _now_iso(),
    })
    if settings.solace_mode == "aws":
        _ddb_put(rec)


def append_tool(call_id: str, *, name: str, tool_input: dict[str, Any], result_summary: str) -> None:
    rec = get(call_id)
    if not rec:
        return
    rec.setdefault("tools_called", []).append({
        "name": name,
        "input": _shallow(tool_input),
        "result_summary": result_summary[:300],
        "ts": _now_iso(),
    })
    if settings.solace_mode == "aws":
        _ddb_put(rec)


def end(call_id: str, *, disposition: str) -> None:
    rec = get(call_id)
    if not rec:
        return
    rec["status"] = "ended"
    rec["disposition"] = disposition
    rec["ended_at"] = _now_iso()
    if rec.get("started_at"):
        rec["duration_seconds"] = max(0, _seconds_between(rec["started_at"], rec["ended_at"]))
    if settings.solace_mode == "aws":
        _ddb_put(rec)


def list_recent(*, hospital_id: str, limit: int = 20) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        return _ddb_query_recent(hospital_id, limit)
    rows = [r for r in _calls.values() if r.get("hospital_id") == hospital_id]
    rows.sort(key=lambda r: r.get("started_at", ""), reverse=True)
    return rows[:limit]


def stats(*, hospital_id: str) -> dict[str, Any]:
    rows = list_recent(hospital_id=hospital_id, limit=200)
    if not rows:
        return {"total": 0, "intents": {}, "escalations": 0, "avg_duration_seconds": 0}
    intents: dict[str, int] = {}
    escalations = 0
    total_duration = 0
    duration_count = 0
    for r in rows:
        if r.get("intent"):
            intents[r["intent"]] = intents.get(r["intent"], 0) + 1
        if r.get("escalation"):
            escalations += 1
        if r.get("duration_seconds"):
            total_duration += int(r["duration_seconds"])
            duration_count += 1
    return {
        "total": len(rows),
        "intents": intents,
        "escalations": escalations,
        "avg_duration_seconds": int(total_duration / duration_count) if duration_count else 0,
    }


# --- DynamoDB I/O --------------------------------------------------------------------


def _table():
    import boto3  # noqa: PLC0415
    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(TABLE)


def _ddb_put(rec: dict[str, Any]) -> None:
    try:
        from db.storage import _to_ddb  # noqa: PLC0415 — reuse existing float→Decimal helper
        # Strip the live `history` field — keep it in memory only. It carries the full
        # Claude messages array including tool_use blocks, which DDB doesn't accept
        # cleanly and which we don't need to keep across cold starts.
        sanitized = {k: v for k, v in rec.items() if k != "history"}
        _table().put_item(Item=_to_ddb(sanitized))
    except Exception as e:  # noqa: BLE001
        log.warning("calls DDB put failed: %s", e)


def _ddb_get(call_id: str) -> dict[str, Any] | None:
    try:
        from db.storage import _from_ddb  # noqa: PLC0415
        resp = _table().get_item(Key={"call_id": call_id})
        item = resp.get("Item")
        if not item:
            return None
        rec = _from_ddb(item)
        rec.setdefault("history", [])
        return rec
    except Exception as e:  # noqa: BLE001
        log.warning("calls DDB get failed: %s", e)
        return None


def _ddb_query_recent(hospital_id: str, limit: int) -> list[dict[str, Any]]:
    try:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415
        from db.storage import _from_ddb  # noqa: PLC0415
        resp = _table().query(
            IndexName="hospital_id-started_at-index",
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_from_ddb(it) for it in resp.get("Items", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("calls DDB query failed: %s", e)
        return []


def _seconds_between(a_iso: str, b_iso: str) -> int:
    try:
        a = datetime.fromisoformat(a_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
        return int((b - a).total_seconds())
    except Exception:
        return 0


def _shallow(d: dict[str, Any]) -> dict[str, Any]:
    """Truncate string values so a single tool input can't blow up DDB row size."""
    out: dict[str, Any] = {}
    for k, v in (d or {}).items():
        if isinstance(v, str):
            out[k] = v[:200]
        else:
            try:
                out[k] = json.loads(json.dumps(v))[:1] if isinstance(v, list) else v
            except Exception:
                out[k] = str(v)[:200]
    return out
