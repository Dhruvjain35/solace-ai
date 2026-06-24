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


# ---- Async Lambda self-invoke (deferred intake artifacts) ---------------------------
# ARCH-002: boto3 is confined to db/. Callers (lib.async_invoke / the intake service)
# ask this layer to fan out a fire-and-forget Lambda invocation; they never touch boto3.
def invoke_lambda_async(function_name: str, payload: dict[str, Any]) -> None:  # pragma: no cover - AWS mode only
    """Fire an asynchronous ('Event') Lambda invocation. Fire-and-forget: returns
    immediately, the target runs out-of-band. Used to defer the slow clinician-only
    artifact generation off the patient-facing intake request (API GW 30s hard cap).

    Failure-safe at the boundary — a transport error is logged (NON-PHI breadcrumb:
    only the function name, never the payload, which carries a patient_id) and
    re-raised so the caller can decide whether to fall back to inline generation.
    """
    import boto3  # noqa: PLC0415

    client = boto3.client("lambda", region_name=settings.aws_region)
    client.invoke(
        FunctionName=function_name,
        InvocationType="Event",  # async — does not wait for the target to finish
        Payload=json.dumps(payload).encode(),
    )


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


# ---- Billing / usage-metering events (Bet #1) ---------------------------------------
# Durable store for backend/lib/metering.py. Records ONE billable event per triage
# encounter so usage can be aggregated for an ROI/billing panel. NON-PHI by construction:
# events carry hospital_id, encounter_type, model_source, an opaque event id, a ts, and
# an optional CPT hint — never patient names/notes/UUID-as-key. Partition by hospital_id,
# sort by ts_id ("{epoch_ms}#{uuid}") so list-by-hospital is a .query() not a .scan()
# (PERF-004). CMK-encrypted at rest (COMP-003). 18-month hot TTL (longer than the 90-day
# clinical tables — billing/usage history is referenced across quarterly review cycles).
BILLING_EVENTS_TABLE = "solace-billing-events"
BILLING_EVENTS_TTL_SECONDS = 18 * 30 * 24 * 3600  # ~18 months hot in DDB


def put_billing_event(entry: dict[str, Any]) -> None:
    """Persist one billable usage event.

    AWS mode: write to DynamoDB (CMK, ~18-month TTL). Stamps ts/ts_id/ttl here so
    callers stay storage-agnostic. Failure-safe at the boundary — a write error is
    logged (NON-PHI breadcrumb) and swallowed; metering must never break a request.
    Local mode: no-op — lib.metering keeps its in-memory list authoritative.
    """
    if settings.solace_mode != "aws":
        return

    now = datetime.now(timezone.utc)
    ts_unix = int(now.timestamp() * 1000)
    event_uuid = uuid.uuid4().hex[:12]
    item = dict(entry)
    item.setdefault("ts", _now_iso())
    item["hospital_id"] = entry.get("hospital_id") or "_"
    item["ts_id"] = f"{ts_unix}#{event_uuid}"
    item["ttl"] = int(time.time()) + BILLING_EVENTS_TTL_SECONDS

    try:
        _boto_table(BILLING_EVENTS_TABLE).put_item(Item=_to_ddb(item))
    except Exception as e:  # noqa: BLE001
        # SEC-002: log only the failure + hospital_id, never the full item.
        log.warning("billing_event write to DDB failed for hospital=%s: %s",
                    item.get("hospital_id"), e)


def list_billing_events(
    hospital_id: str, *, since_ms: int | None = None, limit: int = 5000
) -> list[dict[str, Any]]:
    """Return billing events for one hospital, newest first.

    Uses .query() on the (hospital_id, ts_id) key — never .scan() (PERF-004). When
    `since_ms` is set, the sort-key range condition (ts_id > "{since_ms}#") trims the
    read at the index instead of post-filtering. AWS mode only; local mode returns []
    (lib.metering falls back to its in-memory list).
    """
    if settings.solace_mode != "aws":
        return []
    try:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        cond = Key("hospital_id").eq(hospital_id)
        if since_ms is not None:
            # ts_id sorts lexicographically; zero-padded epoch_ms keeps it monotonic
            # for the windows we care about, and a "#" boundary excludes the marker.
            cond = cond & Key("ts_id").gt(f"{since_ms}#")
        resp = _boto_table(BILLING_EVENTS_TABLE).query(
            KeyConditionExpression=cond,
            ScanIndexForward=False,  # newest ts_id first
            Limit=limit,
        )
        return [_from_ddb(i) for i in resp.get("Items", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("billing_event list failed for hospital=%s: %s", hospital_id, e)
        return []


def aggregate_billing_events(
    hospital_id: str, *, since_ms: int | None = None, limit: int = 5000
) -> dict[str, Any]:
    """Aggregate billable usage for one hospital into NON-PHI counts.

    Returns total billable count, a breakdown by encounter_type and by model_source,
    and a count of CPT hints. Pure aggregation over list_billing_events — no event
    identifiers or per-encounter detail leak out. Local mode returns zeros (the
    in-memory authoritative aggregate lives in lib.metering).
    """
    rows = list_billing_events(hospital_id, since_ms=since_ms, limit=limit)
    billable = [r for r in rows if r.get("billable", True)]
    by_type: dict[str, int] = {}
    by_model: dict[str, int] = {}
    cpt_hints: dict[str, int] = {}
    for r in billable:
        by_type[r.get("encounter_type", "unknown")] = by_type.get(r.get("encounter_type", "unknown"), 0) + 1
        by_model[r.get("model_source", "unknown")] = by_model.get(r.get("model_source", "unknown"), 0) + 1
        hint = r.get("cpt_hint")
        if hint:
            cpt_hints[hint] = cpt_hints.get(hint, 0) + 1
    return {
        "billable_encounters": len(billable),
        "total_events": len(rows),
        "by_encounter_type": by_type,
        "by_model_source": by_model,
        "cpt_hints": cpt_hints,
    }


# ---- Workspace helpers (multi-tenant sub-scope within a hospital) -------------------
# A Workspace is a sub-tenant scope WITHIN a hospital (e.g. a department, clinic, or
# care team). hospital_id remains the top-level tenant boundary (the organization);
# workspace_id is a child scope that is always owned by exactly one hospital_id.
#
# Table layout (AWS mode): partition key = hospital_id, sort key = workspace_id. This
# makes "list workspaces for a hospital" a single .query() on the partition (PERF-004,
# never a .scan()) and makes cross-tenant isolation structural — you cannot read a
# workspace row without naming the owning hospital_id in the key. All key/condition
# expressions use boto3 Key() (SEC-009) — no f-string interpolation of caller input.
#
# The workspace record itself is DURABLE tenant config (not transient nonce/quota
# state), so it carries NO TTL — ARCH-009's TTL guidance applies to transient state.
# CMK encryption at rest (COMP-003) is a table-level property provisioned in IaC,
# identical to solace-patients / solace-hospitals.
_workspaces: dict[str, dict[str, Any]] = {}  # (hospital_id, workspace_id) -> record

WORKSPACES_TABLE = "solace-workspaces"


def put_workspace(record: dict[str, Any]) -> None:
    """Persist (create or overwrite) a workspace record.

    Caller (service layer) is responsible for setting hospital_id + workspace_id and
    for validating them. Local mode keys the in-memory store by (hospital_id,
    workspace_id) so two hospitals can never collide and isolation is structural.
    """
    record.setdefault("created_at", _now_iso())
    if settings.solace_mode == "aws":
        _boto_table(WORKSPACES_TABLE).put_item(Item=_to_ddb(record))
        return
    _workspaces[(record["hospital_id"], record["workspace_id"])] = record


def get_workspace(hospital_id: str, workspace_id: str) -> dict[str, Any] | None:
    """Fetch one workspace by its full (hospital_id, workspace_id) key.

    Returns None when no such workspace exists FOR THIS HOSPITAL. A workspace that
    exists under a different hospital_id is invisible here — cross-tenant reads can
    never succeed because the partition key is the owning hospital_id (SEC-008).
    """
    if settings.solace_mode == "aws":
        resp = _boto_table(WORKSPACES_TABLE).get_item(
            Key={"hospital_id": hospital_id, "workspace_id": workspace_id}
        )
        item = resp.get("Item")
        return _from_ddb(item) if item else None
    return _workspaces.get((hospital_id, workspace_id))


def list_workspaces(hospital_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """Return all workspaces owned by one hospital, newest first.

    Uses .query() on the hospital_id partition (PERF-004 — never .scan()) with a
    parameterized Key() expression (SEC-009).
    """
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(WORKSPACES_TABLE).query(
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
            Limit=limit,
        )
        rows = [_from_ddb(i) for i in resp.get("Items", [])]
    else:
        rows = [v for (h, _w), v in _workspaces.items() if h == hospital_id]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


def update_workspace(
    hospital_id: str, workspace_id: str, updates: dict[str, Any]
) -> dict[str, Any] | None:
    """Patch mutable fields on a workspace, scoped to its owning hospital.

    Returns the updated record, or None if the workspace does not exist for this
    hospital. The DDB ConditionExpression makes the update fail closed if the row is
    absent, so a cross-tenant or stale id can never silently create a phantom row.
    """
    cleaned = _to_ddb(updates)
    if not cleaned:
        return get_workspace(hospital_id, workspace_id)
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

        expr = "SET " + ", ".join(f"#{i}=:{i}" for i in range(len(cleaned)))
        names = {f"#{i}": k for i, k in enumerate(cleaned.keys())}
        values = {f":{i}": v for i, v in enumerate(cleaned.values())}
        try:
            resp = _boto_table(WORKSPACES_TABLE).update_item(
                Key={"hospital_id": hospital_id, "workspace_id": workspace_id},
                UpdateExpression=expr,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression=Attr("workspace_id").exists(),
                ReturnValues="ALL_NEW",
            )
        except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = not found
            log.warning("workspace update failed (missing or cross-tenant): %s", e)
            return None
        return _from_ddb(resp.get("Attributes"))
    existing = _workspaces.get((hospital_id, workspace_id))
    if not existing:
        return None
    existing.update(updates)
    return existing


def delete_workspace(hospital_id: str, workspace_id: str) -> bool:
    """Delete a workspace, scoped to its owning hospital.

    Returns True if a row was removed, False if it did not exist for this hospital.
    """
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

        try:
            _boto_table(WORKSPACES_TABLE).delete_item(
                Key={"hospital_id": hospital_id, "workspace_id": workspace_id},
                ConditionExpression=Attr("workspace_id").exists(),
            )
            return True
        except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = not found
            log.warning("workspace delete failed (missing or cross-tenant): %s", e)
            return False
    return _workspaces.pop((hospital_id, workspace_id), None) is not None


# ---- Per-workspace EHR vendor config ------------------------------------------------
# Each workspace (a department/clinic/care-team inside a hospital) can bind to its own
# EHR: vendor id, FHIR base URL, OAuth client_id, authorize/token endpoints, scopes,
# and — for confidential clients — the AWS Secrets Manager *name* that holds the client
# secret or private-key PEM. The secret VALUE is never stored here (COMP-007); only the
# reference name is persisted, and the value is resolved at use time from Secrets Mgr.
#
# Table layout (AWS mode): partition key = hospital_id, sort key = workspace_id — the
# SAME composite key as solace-workspaces, so a config row is structurally owned by the
# same tenant as its workspace and "list configs for a hospital" is a single .query()
# on the partition (PERF-004, never .scan()). All key/condition expressions use boto3
# Key()/Attr() (SEC-009) — no f-string interpolation of caller input. Durable tenant
# config, so NO TTL. CMK encryption at rest (COMP-003) is a table-level IaC property.
_ehr_configs: dict[tuple[str, str], dict[str, Any]] = {}  # (hospital_id, workspace_id) -> rec

EHR_CONFIGS_TABLE = "solace-ehr-configs"


def put_ehr_config(record: dict[str, Any]) -> None:
    """Persist (create or overwrite) a workspace EHR-config record.

    Caller (service layer) sets + validates hospital_id and workspace_id. Local mode
    keys the in-memory store by (hospital_id, workspace_id) so two hospitals can never
    collide and isolation is structural.
    """
    record.setdefault("created_at", _now_iso())
    if settings.solace_mode == "aws":
        _boto_table(EHR_CONFIGS_TABLE).put_item(Item=_to_ddb(record))
        return
    _ehr_configs[(record["hospital_id"], record["workspace_id"])] = record


def get_ehr_config(hospital_id: str, workspace_id: str) -> dict[str, Any] | None:
    """Fetch one workspace EHR config by its full (hospital_id, workspace_id) key.

    Returns None when no config exists FOR THIS HOSPITAL. A config owned by a different
    hospital_id is invisible here — the partition key is the owning hospital_id, so a
    cross-tenant read can never succeed (SEC-008).
    """
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(EHR_CONFIGS_TABLE).query(
            KeyConditionExpression=(
                Key("hospital_id").eq(hospital_id) & Key("workspace_id").eq(workspace_id)
            ),
        )
        items = resp.get("Items", [])
        return _from_ddb(items[0]) if items else None
    return _ehr_configs.get((hospital_id, workspace_id))


def list_ehr_configs(hospital_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """List every workspace EHR config owned by one hospital, newest first.

    Uses .query() on the hospital_id partition (PERF-004 — never .scan()) with a
    parameterized Key() expression (SEC-009).
    """
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(EHR_CONFIGS_TABLE).query(
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
            Limit=limit,
        )
        rows = [_from_ddb(i) for i in resp.get("Items", [])]
    else:
        rows = [v for (h, _w), v in _ehr_configs.items() if h == hospital_id]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


def update_ehr_config(
    hospital_id: str, workspace_id: str, updates: dict[str, Any]
) -> dict[str, Any] | None:
    """Patch mutable fields on a workspace EHR config, scoped to its owning hospital.

    Returns the updated record, or None if no config exists for this hospital. The DDB
    ConditionExpression makes the update fail closed if the row is absent, so a
    cross-tenant or stale id can never silently create a phantom row.
    """
    cleaned = _to_ddb(updates)
    if not cleaned:
        return get_ehr_config(hospital_id, workspace_id)
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

        expr = "SET " + ", ".join(f"#{i}=:{i}" for i in range(len(cleaned)))
        names = {f"#{i}": k for i, k in enumerate(cleaned.keys())}
        values = {f":{i}": v for i, v in enumerate(cleaned.values())}
        try:
            resp = _boto_table(EHR_CONFIGS_TABLE).update_item(
                Key={"hospital_id": hospital_id, "workspace_id": workspace_id},
                UpdateExpression=expr,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression=Attr("workspace_id").exists(),
                ReturnValues="ALL_NEW",
            )
        except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = not found
            log.warning("ehr config update failed (missing or cross-tenant): %s", e)
            return None
        return _from_ddb(resp.get("Attributes"))
    existing = _ehr_configs.get((hospital_id, workspace_id))
    if not existing:
        return None
    existing.update(updates)
    return existing


def delete_ehr_config(hospital_id: str, workspace_id: str) -> bool:
    """Delete a workspace EHR config, scoped to its owning hospital.

    Returns True if a row was removed, False if it did not exist for this hospital.
    """
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

        try:
            _boto_table(EHR_CONFIGS_TABLE).delete_item(
                Key={"hospital_id": hospital_id, "workspace_id": workspace_id},
                ConditionExpression=Attr("workspace_id").exists(),
            )
            return True
        except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = not found
            log.warning("ehr config delete failed (missing or cross-tenant): %s", e)
            return False
    return _ehr_configs.pop((hospital_id, workspace_id), None) is not None


def resolve_secret_value(secret_name: str) -> str | None:
    """Resolve a client secret / private-key PEM from AWS Secrets Manager BY NAME.

    The per-workspace EHR config stores only the Secrets Manager *name* of a
    confidential-client secret (COMP-007) — never the value. This is the single
    db-layer chokepoint (ARCH-002: boto3 stays in db/) that dereferences that name
    at use time, inside the token exchange.

    Returns the secret string, or None when the name is empty or cannot be
    resolved (so the caller falls back to public-client / PKCE-only behavior).
    NEVER logs the secret value or the resolved payload.
    """
    if not secret_name:
        return None
    if settings.solace_mode != "aws":
        # Local dev: confidential-client secrets are supplied via env, mirroring the
        # convention ehr_auth uses for SOLACE_<VENDOR>_PRIVATE_KEY. The env var name
        # is the configured secret_name upper-cased with non-alnum -> "_".
        import os  # noqa: PLC0415
        import re  # noqa: PLC0415

        env_key = re.sub(r"[^A-Z0-9]+", "_", secret_name.upper()).strip("_")
        raw = os.environ.get(env_key, "")
        return raw.replace("\\n", "\n").strip() or None
    try:
        import boto3  # noqa: PLC0415

        client = boto3.client("secretsmanager", region_name=settings.aws_region)
        resp = client.get_secret_value(SecretId=secret_name)
        raw = resp.get("SecretString") or ""
        return raw.replace("\\n", "\n").strip() or None
    except Exception as e:  # noqa: BLE001 — NEVER include the secret value in the log
        log.warning("Secrets Manager resolve failed for a configured EHR secret: %s", type(e).__name__)
        return None


# ---- EHR bulk-export job state ------------------------------------------------------
# Transient async-job tracking for FHIR Bulk Data $export (ARCH-009: short-TTL
# DynamoDB in AWS, in-memory dict in local mode). Partition by hospital_id, sort
# by job_id so list-by-hospital is a parameterized .query() (SEC-009, PERF-004).
EHR_BULK_JOBS_TABLE = "solace-ehr-bulk-jobs"
EHR_BULK_JOB_TTL_SECONDS = 7 * 24 * 3600  # 7 days — a job + its manifest is short-lived
_ehr_bulk_jobs: dict[tuple[str, str], dict[str, Any]] = {}  # (hospital_id, job_id) -> record


def put_bulk_job(record: dict[str, Any]) -> None:
    """Persist/update a bulk-export job record. Requires hospital_id + job_id."""
    record.setdefault("created_at", _now_iso())
    record.setdefault("ttl", int(time.time()) + EHR_BULK_JOB_TTL_SECONDS)
    if settings.solace_mode == "aws":
        _boto_table(EHR_BULK_JOBS_TABLE).put_item(Item=_to_ddb(record))
        return
    _ehr_bulk_jobs[(record["hospital_id"], record["job_id"])] = record


def get_bulk_job(hospital_id: str, job_id: str) -> dict[str, Any] | None:
    """Fetch one bulk-export job by parameterized composite key (SEC-009)."""
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(EHR_BULK_JOBS_TABLE).query(
            KeyConditionExpression=(
                Key("hospital_id").eq(hospital_id) & Key("job_id").eq(job_id)
            ),
        )
        items = resp.get("Items", [])
        return _from_ddb(items[0]) if items else None
    return _ehr_bulk_jobs.get((hospital_id, job_id))


def list_bulk_jobs(hospital_id: str) -> list[dict[str, Any]]:
    """List a hospital's bulk-export jobs via parameterized .query() (no .scan())."""
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(EHR_BULK_JOBS_TABLE).query(
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
        )
        items = [_from_ddb(i) for i in resp.get("Items", [])]
        items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return items
    rows = [r for (h, _j), r in _ehr_bulk_jobs.items() if h == hospital_id]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


# ---- EHR Subscription registration state --------------------------------------------
# Tracks FHIR Subscription resources Solace created so the webhook receiver can
# verify the shared secret and resolve which hospital a notification belongs to.
EHR_SUBSCRIPTIONS_TABLE = "solace-ehr-subscriptions"
EHR_SUBSCRIPTION_TTL_SECONDS = 90 * 24 * 3600  # 90 days — subscriptions are renewed
_ehr_subscriptions: dict[tuple[str, str], dict[str, Any]] = {}  # (hospital_id, sub_id) -> rec


def put_subscription(record: dict[str, Any]) -> None:
    """Persist a Subscription registration. Requires hospital_id + subscription_id."""
    record.setdefault("created_at", _now_iso())
    record.setdefault("ttl", int(time.time()) + EHR_SUBSCRIPTION_TTL_SECONDS)
    if settings.solace_mode == "aws":
        _boto_table(EHR_SUBSCRIPTIONS_TABLE).put_item(Item=_to_ddb(record))
        return
    _ehr_subscriptions[(record["hospital_id"], record["subscription_id"])] = record


def get_subscription(hospital_id: str, subscription_id: str) -> dict[str, Any] | None:
    """Fetch one Subscription registration by parameterized composite key."""
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(EHR_SUBSCRIPTIONS_TABLE).query(
            KeyConditionExpression=(
                Key("hospital_id").eq(hospital_id)
                & Key("subscription_id").eq(subscription_id)
            ),
        )
        items = resp.get("Items", [])
        return _from_ddb(items[0]) if items else None
    return _ehr_subscriptions.get((hospital_id, subscription_id))


def list_subscriptions(hospital_id: str) -> list[dict[str, Any]]:
    """List a hospital's Subscription registrations via parameterized .query()."""
    if settings.solace_mode == "aws":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        resp = _boto_table(EHR_SUBSCRIPTIONS_TABLE).query(
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
        )
        items = [_from_ddb(i) for i in resp.get("Items", [])]
        items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return items
    rows = [r for (h, _s), r in _ehr_subscriptions.items() if h == hospital_id]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


# ---- Contact / sales inquiries (public marketing form) ------------------------------
# Inbound from POST /api/contact (routers/contact.py). NON-PHI by construction —
# name/work-email/org/topic/message from a public marketing form, never patient
# data. Mirrors the access-requests pattern: simple PK (contact_id), in-memory
# dict locally, DDB `solace-contact-requests` in aws mode (table provisioned
# idempotently by scripts/setup_clinician_auth.py).
CONTACT_REQUESTS_TABLE = "solace-contact-requests"
_contact_requests: dict[str, dict[str, Any]] = {}  # contact_id -> record


def put_contact_request(record: dict[str, Any]) -> None:
    """Persist one contact/sales inquiry. Caller sets contact_id + created_at."""
    record.setdefault("created_at", _now_iso())
    if settings.solace_mode == "aws":
        _boto_table(CONTACT_REQUESTS_TABLE).put_item(Item=_to_ddb(record))
        return
    _contact_requests[record["contact_id"]] = record


def get_contact_request(contact_id: str) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        resp = _boto_table(CONTACT_REQUESTS_TABLE).get_item(Key={"contact_id": contact_id})
        item = resp.get("Item")
        return _from_ddb(item) if item else None
    return _contact_requests.get(contact_id)


# ---- Test helpers -------------------------------------------------------------------
def _reset_for_tests() -> None:
    _patients.clear()
    _hospitals.clear()
    _prescriptions.clear()
    _notes.clear()
    _appointments.clear()
    _workspaces.clear()
    _ehr_configs.clear()
    _ehr_bulk_jobs.clear()
    _ehr_subscriptions.clear()
    _contact_requests.clear()
