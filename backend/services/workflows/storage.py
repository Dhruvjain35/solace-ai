"""DynamoDB storage for workflows.

Local mode uses an in-memory dict, AWS mode uses solace-workflows table:
  PK: workflow_id (S)
  GSI: hospital_id (HASH) + created_at (RANGE)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

TABLE = "solace-workflows"

_local: dict[str, dict[str, Any]] = {}  # workflow_id -> record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _table():
    import boto3  # noqa: PLC0415
    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(TABLE)


def put(record: dict[str, Any]) -> None:
    record.setdefault("created_at", _now_iso())
    record["updated_at"] = _now_iso()
    if settings.solace_mode == "aws":
        from db.storage import _to_ddb  # noqa: PLC0415
        try:
            _table().put_item(Item=_to_ddb(record))
        except Exception as e:  # noqa: BLE001
            log.warning("workflow put failed: %s", e)
            _local[record["workflow_id"]] = record
        return
    _local[record["workflow_id"]] = record


def get(workflow_id: str) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        from db.storage import _from_ddb  # noqa: PLC0415
        try:
            resp = _table().get_item(Key={"workflow_id": workflow_id})
            item = resp.get("Item")
            return _from_ddb(item) if item else None
        except Exception as e:  # noqa: BLE001
            log.warning("workflow get failed: %s", e)
            return _local.get(workflow_id)
    return _local.get(workflow_id)


def list_for_hospital(hospital_id: str) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        from db.storage import _from_ddb  # noqa: PLC0415
        try:
            from boto3.dynamodb.conditions import Key  # noqa: PLC0415
            resp = _table().query(
                IndexName="hospital_id-created_at-index",
                KeyConditionExpression=Key("hospital_id").eq(hospital_id),
                ScanIndexForward=False,
            )
            return [_from_ddb(it) for it in resp.get("Items", [])]
        except Exception as e:  # noqa: BLE001
            log.warning("workflow list failed: %s", e)
    return [r for r in _local.values() if r.get("hospital_id") == hospital_id]


def delete(workflow_id: str) -> None:
    if settings.solace_mode == "aws":
        try:
            _table().delete_item(Key={"workflow_id": workflow_id})
        except Exception as e:  # noqa: BLE001
            log.warning("workflow delete failed: %s", e)
    _local.pop(workflow_id, None)


def increment_fire_count(workflow_id: str) -> None:
    rec = get(workflow_id)
    if not rec:
        return
    rec["fire_count"] = int(rec.get("fire_count") or 0) + 1
    rec["last_fired_at"] = _now_iso()
    put(rec)
