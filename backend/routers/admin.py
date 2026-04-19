"""Demo operations — wipe test data, keep canonical seed patients pristine."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Path

from db import storage
from lib.auth import audit, require_clinician

log = logging.getLogger(__name__)

router = APIRouter()

CANONICAL_NAMES = {"Marcus", "Elena", "Priya", "James", "Sofia"}
# Fields cleared on canonical patients so refine-triage / notes / publish get reset state
REFINED_FIELDS = [
    "refined_esi_level", "refined_confidence", "refined_probabilities",
    "refined_conformal_set", "refined_top_features", "refined_source",
    "refined_at", "measured_vitals",
    "patient_education", "patient_education_published_at",
]


def _delete_ddb_patient(patient_id: str) -> None:
    import boto3  # noqa: PLC0415
    from lib.config import settings  # noqa: PLC0415

    if settings.solace_mode != "aws":
        storage._patients.pop(patient_id, None)
        storage._prescriptions.pop(patient_id, None)
        storage._notes.pop(patient_id, None)
        return

    dynamo = boto3.resource("dynamodb", region_name=settings.aws_region)
    dynamo.Table(settings.dynamodb_table_patients).delete_item(Key={"patient_id": patient_id})
    # Delete prescriptions + notes (each keyed on patient_id + SK)
    for (table_name, sk_name) in [
        (settings.dynamodb_table_prescriptions, "prescription_id"),
        (settings.dynamodb_table_notes, "note_id"),
    ]:
        t = dynamo.Table(table_name)
        resp = t.query(
            KeyConditionExpression="patient_id = :p",
            ExpressionAttributeValues={":p": patient_id},
        )
        for item in resp.get("Items", []):
            t.delete_item(Key={"patient_id": patient_id, sk_name: item[sk_name]})


def _clear_canonical_fields(patient_id: str) -> None:
    import boto3  # noqa: PLC0415
    from lib.config import settings  # noqa: PLC0415

    if settings.solace_mode != "aws":
        p = storage._patients.get(patient_id)
        if p:
            for f in REFINED_FIELDS:
                p.pop(f, None)
        storage._prescriptions.pop(patient_id, None)
        storage._notes.pop(patient_id, None)
        return

    dynamo = boto3.resource("dynamodb", region_name=settings.aws_region)
    t = dynamo.Table(settings.dynamodb_table_patients)
    # Build REMOVE expression only for present fields
    item = t.get_item(Key={"patient_id": patient_id}).get("Item") or {}
    present = [f for f in REFINED_FIELDS if f in item]
    if present:
        names = {f"#{i}": f for i, f in enumerate(present)}
        t.update_item(
            Key={"patient_id": patient_id},
            UpdateExpression="REMOVE " + ", ".join(f"#{i}" for i in range(len(present))),
            ExpressionAttributeNames=names,
        )
    # Nuke prescriptions + notes for the canonical patient too
    for (table_name, sk_name) in [
        (settings.dynamodb_table_prescriptions, "prescription_id"),
        (settings.dynamodb_table_notes, "note_id"),
    ]:
        nt = dynamo.Table(table_name)
        resp = nt.query(
            KeyConditionExpression="patient_id = :p",
            ExpressionAttributeValues={":p": patient_id},
        )
        for row in resp.get("Items", []):
            nt.delete_item(Key={"patient_id": patient_id, sk_name: row[sk_name]})


@router.post("/admin/reset-demo")
def reset_demo(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "admin.reset_demo")
    rows = storage.list_patients_for_hospital(hospital_id, status="all")
    deleted: list[str] = []
    cleared: list[str] = []
    for p in rows:
        name = (p.get("name") or "").strip()
        pid = p["patient_id"]
        if name in CANONICAL_NAMES:
            _clear_canonical_fields(pid)
            cleared.append(name)
        else:
            _delete_ddb_patient(pid)
            deleted.append(name or pid[:8])
    log.info("reset-demo: deleted=%d cleared=%d", len(deleted), len(cleared))
    return {
        "success": True,
        "deleted_test_patients": deleted,
        "cleared_canonical_patients": cleared,
    }
