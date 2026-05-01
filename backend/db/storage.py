"""Storage layer. Local mode = in-memory dicts. AWS mode = DynamoDB.

Swap is a Settings flag. Callers never touch the underlying store directly.
"""
from __future__ import annotations

import logging
import time
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
            "clinician_pin": settings.demo_clinician_pin,
            "created_at": _now_iso(),
        }
    )
    log.info("Seeded demo hospital '%s' (PIN redacted)", hospital_id)


def get_hospital(hospital_id: str) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        return _ddb_get_hospital(hospital_id)
    return _hospitals.get(hospital_id)


def put_hospital(hospital: dict[str, Any]) -> None:
    if settings.solace_mode == "aws":
        _ddb_put_hospital(hospital)
        return
    _hospitals[hospital["hospital_id"]] = hospital


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


# ---- Test helpers -------------------------------------------------------------------
def _reset_for_tests() -> None:
    _patients.clear()
    _hospitals.clear()
    _prescriptions.clear()
    _notes.clear()
    _appointments.clear()
