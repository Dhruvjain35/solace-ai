"""Storage layer. Local mode = in-memory dicts. AWS mode = DynamoDB.

Swap is a Settings flag. Callers never touch the underlying store directly.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

# ---- In-memory stores (local mode) --------------------------------------------------
_patients: dict[str, dict[str, Any]] = {}
_hospitals: dict[str, dict[str, Any]] = {}
_prescriptions: dict[str, list[dict[str, Any]]] = {}  # patient_id -> list
_notes: dict[str, list[dict[str, Any]]] = {}  # patient_id -> list


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_ttl() -> int:
    return int(time.time()) + 24 * 3600  # 24h


# ---- DynamoDB float/Decimal conversion ---------------------------------------------
def _to_ddb(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_ddb(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_to_ddb(v) for v in obj]
    return obj


def _from_ddb(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


# ---- Hospital helpers ---------------------------------------------------------------
def seed_demo_hospital() -> None:
    """Ensure the demo hospital exists. Called on app startup."""
    hospital_id = settings.demo_hospital_id
    if get_hospital(hospital_id):
        return
    put_hospital(
        {
            "hospital_id": hospital_id,
            "name": settings.demo_hospital_name,
            # Legacy plaintext clinician_pin removed — auth is JWT-only.
            # Clinician PINs are stored as bcrypt hashes in solace-clinicians table.
            "created_at": _now_iso(),
        }
    )
    log.info("Seeded demo hospital '%s'", hospital_id)


def get_hospital(hospital_id: str) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        return _ddb_get_hospital(hospital_id)
    return _hospitals.get(hospital_id)


def put_hospital(hospital: dict[str, Any]) -> None:
    if settings.solace_mode == "aws":
        _ddb_put_hospital(hospital)
        return
    _hospitals[hospital["hospital_id"]] = hospital


def get_hospital_by_slug(slug: str) -> dict[str, Any] | None:
    """Resolve a hospital by its URL-safe slug. The slug doubles as hospital_id
    for provisioned workspaces, so this is a direct key lookup. Returns the
    hospital only if its stored slug matches (guards against id/slug drift)."""
    hospital = get_hospital(slug)
    if hospital and hospital.get("slug", hospital.get("hospital_id")) == slug:
        return hospital
    return None


def slug_exists(slug: str) -> bool:
    """True if a hospital already occupies this slug. Used to keep slugs unique
    when provisioning a new workspace."""
    return get_hospital(slug) is not None


# ---- Patient helpers ----------------------------------------------------------------
def put_patient(patient: dict[str, Any]) -> None:
    patient.setdefault("created_at", _now_iso())
    patient.setdefault("ttl", _default_ttl())
    if settings.solace_mode == "aws":
        _ddb_put_patient(patient)
        return
    _patients[patient["patient_id"]] = patient


def get_patient(patient_id: str) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        return _ddb_get_patient(patient_id)
    return _patients.get(patient_id)


def update_patient(patient_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        return _ddb_update_patient(patient_id, updates)
    existing = _patients.get(patient_id)
    if not existing:
        return None
    existing.update(updates)
    return existing


def list_patients_for_hospital(hospital_id: str, status: str | None = None) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        rows = _ddb_query_patients_by_hospital(hospital_id)
    else:
        rows = [p for p in _patients.values() if p.get("hospital_id") == hospital_id]
    if status and status != "all":
        rows = [p for p in rows if p.get("status") == status]
    rows.sort(key=lambda p: (int(p.get("esi_level", 5)), p.get("created_at", "")))
    return rows


# ---- DynamoDB implementations ------------------------------------------------------
def _boto_table(name: str):  # pragma: no cover - AWS mode only
    import boto3

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def _ddb_get_hospital(hospital_id: str) -> dict[str, Any] | None:
    resp = _boto_table(settings.dynamodb_table_hospitals).get_item(Key={"hospital_id": hospital_id})
    item = resp.get("Item")
    return _from_ddb(item) if item else None


def _ddb_put_hospital(hospital: dict[str, Any]) -> None:
    _boto_table(settings.dynamodb_table_hospitals).put_item(Item=_to_ddb(hospital))


def _ddb_get_patient(patient_id: str) -> dict[str, Any] | None:
    resp = _boto_table(settings.dynamodb_table_patients).get_item(Key={"patient_id": patient_id})
    item = resp.get("Item")
    return _from_ddb(item) if item else None


def _ddb_put_patient(patient: dict[str, Any]) -> None:
    _boto_table(settings.dynamodb_table_patients).put_item(Item=_to_ddb(patient))


def _ddb_update_patient(patient_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    cleaned = _to_ddb(updates)
    expr = "SET " + ", ".join(f"#{i}=:{i}" for i in range(len(cleaned)))
    names = {f"#{i}": k for i, k in enumerate(cleaned.keys())}
    values = {f":{i}": v for i, v in enumerate(cleaned.values())}
    resp = _boto_table(settings.dynamodb_table_patients).update_item(
        Key={"patient_id": patient_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return _from_ddb(resp.get("Attributes"))


def _ddb_query_patients_by_hospital(hospital_id: str) -> list[dict[str, Any]]:
    resp = _boto_table(settings.dynamodb_table_patients).query(
        IndexName="hospital_id-created_at-index",
        KeyConditionExpression="hospital_id = :h",
        ExpressionAttributeValues={":h": hospital_id},
    )
    return [_from_ddb(i) for i in resp.get("Items", [])]


# ---- Prescription helpers -----------------------------------------------------------
def add_prescription(record: dict[str, Any]) -> None:
    record.setdefault("ttl", _default_ttl())
    if settings.solace_mode == "aws":
        _boto_table(settings.dynamodb_table_prescriptions).put_item(Item=_to_ddb(record))
        return
    _prescriptions.setdefault(record["patient_id"], []).append(record)


def list_prescriptions(patient_id: str) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        resp = _boto_table(settings.dynamodb_table_prescriptions).query(
            KeyConditionExpression="patient_id = :p",
            ExpressionAttributeValues={":p": patient_id},
        )
        items = [_from_ddb(i) for i in resp.get("Items", [])]
        items.sort(key=lambda r: r.get("created_at", ""))
        return items
    return list(_prescriptions.get(patient_id, []))


# ---- Clinician note helpers ---------------------------------------------------------
def add_note(record: dict[str, Any]) -> None:
    record.setdefault("ttl", _default_ttl())
    if settings.solace_mode == "aws":
        _boto_table(settings.dynamodb_table_notes).put_item(Item=_to_ddb(record))
        return
    _notes.setdefault(record["patient_id"], []).append(record)


def list_notes(patient_id: str) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        resp = _boto_table(settings.dynamodb_table_notes).query(
            KeyConditionExpression="patient_id = :p",
            ExpressionAttributeValues={":p": patient_id},
        )
        items = [_from_ddb(i) for i in resp.get("Items", [])]
        items.sort(key=lambda r: r.get("created_at", ""))
        return items
    return list(_notes.get(patient_id, []))


# ---- Appointment helpers (voice agent) ----------------------------------------------
_appointments: dict[str, dict[str, Any]] = {}  # confirmation_code -> record

APPOINTMENTS_TABLE = "solace-appointments"


def add_appointment(record: dict[str, Any]) -> None:
    record.setdefault("created_at", _now_iso())
    record.setdefault("ttl", int(time.time()) + 30 * 86400)  # 30d
    if settings.solace_mode == "aws":
        _boto_table(APPOINTMENTS_TABLE).put_item(Item=_to_ddb(record))
        return
    _appointments[record["confirmation_code"]] = record


def cancel_appointment(confirmation_code: str, *, hospital_id: str) -> bool:
    if settings.solace_mode == "aws":
        try:
            from boto3.dynamodb.conditions import Key  # noqa: PLC0415
            tbl = _boto_table(APPOINTMENTS_TABLE)
            resp = tbl.query(
                IndexName="confirmation_code-index",
                KeyConditionExpression=Key("confirmation_code").eq(confirmation_code),
            )
            items = resp.get("Items", [])
            if not items:
                return False
            row = _from_ddb(items[0])
            if row.get("hospital_id") != hospital_id:
                return False
            tbl.update_item(
                Key={"appointment_id": row["appointment_id"]},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "cancelled"},
            )
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("appointment cancel failed: %s", e)
            return False
    rec = _appointments.get(confirmation_code)
    if not rec or rec.get("hospital_id") != hospital_id:
        return False
    rec["status"] = "cancelled"
    return True


def list_appointments(*, hospital_id: str) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        try:
            from boto3.dynamodb.conditions import Key  # noqa: PLC0415
            resp = _boto_table(APPOINTMENTS_TABLE).query(
                IndexName="hospital_id-created_at-index",
                KeyConditionExpression=Key("hospital_id").eq(hospital_id),
                ScanIndexForward=False,
                Limit=50,
            )
            return [_from_ddb(i) for i in resp.get("Items", [])]
        except Exception as e:  # noqa: BLE001
            log.warning("appointment list failed: %s", e)
            return []
    rows = [r for r in _appointments.values() if r.get("hospital_id") == hospital_id]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


# ---- AI override / provenance log (HTI-1 transparency metrics) -----------------------
# Durable backing store for backend/lib/provenance.py. Mirrors the audit-log dual-write:
# DynamoDB (90-day hot TTL) + S3 CMK-encrypted JSONL (6-year cold retention). Partition
# by hospital_id, sort by ts_id so list-by-hospital is a .query() not a .scan() (PERF-004).
OVERRIDES_TABLE = "solace-ai-overrides"
OVERRIDES_TTL_SECONDS = 90 * 24 * 3600  # 90 days hot in DDB (also archived to S3 for 6yr)
_OVERRIDES_S3_PREFIX = "ai-overrides-archive"


def _overrides_archive_to_s3(item: dict[str, Any]) -> None:
    """Append an override record as a JSONL line to a daily S3 object.

    CMK-encrypted at rest via the bucket's default encryption. Mirrors
    lib.audit._archive_to_s3 for the 6-year HTI-1/HIPAA retention path.
    """
    if settings.solace_mode != "aws" or not settings.s3_bucket_media:
        return  # Skip in local mode

    try:
        import boto3  # noqa: PLC0415

        s3 = boto3.client("s3", region_name=settings.aws_region)
        today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        record_id = item.get("ts_id", "").replace("#", "_") or _now_iso()
        key = f"{_OVERRIDES_S3_PREFIX}/{today}/{record_id}.json"

        clean = {k: v for k, v in item.items() if v is not None and k != "ttl"}
        s3.put_object(
            Bucket=settings.s3_bucket_media,
            Key=key,
            Body=json.dumps(clean, default=str).encode(),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",
        )
    except Exception as e:  # noqa: BLE001
        # S3 archive failure must not block the request or lose the DDB record.
        log.warning("ai_override S3 archive failed: %s", e)


def put_override(entry: dict[str, Any]) -> None:
    """Persist one AI override-decision record.

    AWS mode: dual-write to DynamoDB (CMK, 90-day TTL) + S3 CMK JSONL (6-year).
    Local mode: no-op — lib.provenance keeps the in-memory list authoritative.
    """
    if settings.solace_mode != "aws":
        return

    now = datetime.now(timezone.utc)
    ts_unix = int(now.timestamp() * 1000)
    override_uuid = uuid.uuid4().hex[:12]
    item = dict(entry)
    item.setdefault("ts", _now_iso())
    item["hospital_id"] = entry.get("hospital_id") or "_"
    item["ts_id"] = f"{ts_unix}#{override_uuid}"
    item["ttl"] = int(time.time()) + OVERRIDES_TTL_SECONDS

    try:
        _boto_table(OVERRIDES_TABLE).put_item(Item=_to_ddb(item))
    except Exception as e:  # noqa: BLE001
        log.warning("ai_override write to DDB failed: %s", e)

    _overrides_archive_to_s3(item)


def list_overrides(hospital_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """Return override records for one hospital, newest first.

    Uses .query() on the (hospital_id, ts_id) key — never .scan() (PERF-004).
    AWS mode only; local mode returns [] (lib.provenance falls back to memory).
    """
    if settings.solace_mode != "aws":
        return []
    try:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(OVERRIDES_TABLE).query(
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
            ScanIndexForward=False,  # newest ts_id first
            Limit=limit,
        )
        return [_from_ddb(i) for i in resp.get("Items", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("ai_override list failed: %s", e)
        return []


# ---- ML label store (active-learning training data) ---------------------------------
# Durable backing store for backend/lib/label_store.py. When a clinician corrects or
# rejects the model's ESI, we capture a labeled training example (the model's stored
# probabilities / feature vector + the clinician-confirmed ESI) so synthetic-only
# training can be augmented with real labels and fed into triage_ml.recalibrate_from_outcomes.
#
# Mirrors the override/audit dual-write: DynamoDB (90-day hot TTL) + S3 CMK-encrypted
# JSONL (6-year cold retention). Partition by hospital_id, sort by ts_id so list-by-
# hospital is a .query() not a .scan() (PERF-004). CMK-encrypted at rest (COMP-003).
# COMP-001: labels are training data — they stay tenant-scoped (hospital_id partition)
# and never leave the CMK-encrypted store; nothing here flows to an AI/external provider.
LABELS_TABLE = "solace-ml-labels"
LABELS_TTL_SECONDS = 90 * 24 * 3600  # 90 days hot in DDB (also archived to S3 for 6yr)
_LABELS_S3_PREFIX = "ml-labels-archive"


def _labels_archive_to_s3(item: dict[str, Any]) -> None:
    """Append a label record as a JSONL-style line to a daily S3 object.

    CMK-encrypted at rest via the bucket's default encryption (aws:kms). Mirrors
    lib.audit._archive_to_s3 / _overrides_archive_to_s3 for the 6-year HIPAA
    retention path. Failure here must never block the request or lose the DDB record.
    """
    if settings.solace_mode != "aws" or not settings.s3_bucket_media:
        return  # Skip in local mode

    try:
        import boto3  # noqa: PLC0415

        s3 = boto3.client("s3", region_name=settings.aws_region)
        today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        record_id = item.get("ts_id", "").replace("#", "_") or _now_iso()
        key = f"{_LABELS_S3_PREFIX}/{today}/{record_id}.json"

        clean = {k: v for k, v in item.items() if v is not None and k != "ttl"}
        s3.put_object(
            Bucket=settings.s3_bucket_media,
            Key=key,
            Body=json.dumps(clean, default=str).encode(),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ml_label S3 archive failed: %s", e)


def put_label(entry: dict[str, Any]) -> None:
    """Persist one clinician-confirmed ML training label.

    AWS mode: dual-write to DynamoDB (CMK, 90-day TTL) + S3 CMK JSONL (6-year).
    Local mode: no-op — lib.label_store keeps its in-memory list authoritative.
    """
    if settings.solace_mode != "aws":
        return

    now = datetime.now(timezone.utc)
    ts_unix = int(now.timestamp() * 1000)
    label_uuid = uuid.uuid4().hex[:12]
    item = dict(entry)
    item.setdefault("ts", _now_iso())
    item["hospital_id"] = entry.get("hospital_id") or "_"
    item["ts_id"] = f"{ts_unix}#{label_uuid}"
    item["ttl"] = int(time.time()) + LABELS_TTL_SECONDS

    try:
        _boto_table(LABELS_TABLE).put_item(Item=_to_ddb(item))
    except Exception as e:  # noqa: BLE001
        log.warning("ml_label write to DDB failed: %s", e)

    _labels_archive_to_s3(item)


def list_labels(hospital_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
    """Return clinician-confirmed labels for one hospital, newest first.

    Uses .query() on the (hospital_id, ts_id) key — never .scan() (PERF-004).
    AWS mode only; local mode returns [] (lib.label_store falls back to memory).
    """
    if settings.solace_mode != "aws":
        return []
    try:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(LABELS_TABLE).query(
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
            ScanIndexForward=False,  # newest ts_id first
            Limit=limit,
        )
        return [_from_ddb(i) for i in resp.get("Items", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("ml_label list failed: %s", e)
        return []


# ---- Test helpers -------------------------------------------------------------------
def _reset_for_tests() -> None:
    _patients.clear()
    _hospitals.clear()
    _prescriptions.clear()
    _notes.clear()
    _appointments.clear()
