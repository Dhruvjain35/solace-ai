"""Demo operations — wipe test data, keep canonical seed patients pristine.
Also exposes a cost dashboard for clinicians/admins to see per-encounter $ spend.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path

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
            sk_value = item.get(sk_name)
            if sk_value is None:
                continue
            t.delete_item(Key={"patient_id": patient_id, sk_name: sk_value})


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
            sk_value = row.get(sk_name)
            if sk_value is None:
                continue
            nt.delete_item(Key={"patient_id": patient_id, sk_name: sk_value})


@router.post("/admin/reset-demo")
def reset_demo(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    # Demo-only: this wipes/reseeds the canonical demo patients. A real
    # provisioned workspace must never be reset to demo seed data.
    from lib.config import settings  # noqa: PLC0415
    if hospital_id != settings.demo_hospital_id:
        raise HTTPException(status_code=403, detail="Reset is only available in the demo workspace.")
    audit(caller, "admin.reset_demo")
    try:
        rows = storage.list_patients_for_hospital(hospital_id, status="all")
    except Exception as e:  # noqa: BLE001
        log.exception("reset-demo: failed to list patients: %s", e)
        raise HTTPException(status_code=502, detail="could not list patients for reset")
    deleted: list[str] = []
    cleared: list[str] = []
    failed: list[str] = []
    for p in rows:
        name = (p.get("name") or "").strip()
        pid = p.get("patient_id")
        if not pid:
            log.warning("reset-demo: skipping row with no patient_id")
            continue
        try:
            if name in CANONICAL_NAMES:
                _clear_canonical_fields(pid)
                cleared.append(name)
            else:
                _delete_ddb_patient(pid)
                deleted.append(name or pid[:8])
        except Exception as e:  # noqa: BLE001
            log.exception("reset-demo: failed for patient %s: %s", pid[:8], e)
            failed.append(name or pid[:8])
    log.info("reset-demo: deleted=%d cleared=%d failed=%d", len(deleted), len(cleared), len(failed))
    return {
        "success": True,
        "deleted_test_patients": deleted,
        "cleared_canonical_patients": cleared,
        "failed_patients": failed,
    }


@router.get("/admin/cost-stats")
def cost_stats(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Per-encounter AI spend dashboard. Aggregated from `ai_cost_usd` on each
    patient row + breakdown across the seven Claude services + Whisper + TTS."""
    audit(caller, "admin.cost_stats")
    try:
        rows = storage.list_patients_for_hospital(hospital_id, status="all")
    except Exception as e:  # noqa: BLE001
        log.exception("cost-stats: failed to list patients: %s", e)
        raise HTTPException(status_code=502, detail="could not load cost data")
    total = 0.0
    breakdown_total: dict[str, float] = {}
    encounters_with_cost = 0
    for p in rows:
        c = p.get("ai_cost_usd")
        if c is None:
            continue
        try:
            total += float(c)
            encounters_with_cost += 1
        except (TypeError, ValueError):
            continue
        try:
            import json as _json  # noqa: PLC0415
            bd = p.get("ai_cost_breakdown")
            if isinstance(bd, str):
                bd = _json.loads(bd)
            if isinstance(bd, dict):
                for k, v in bd.items():
                    breakdown_total[k] = round(breakdown_total.get(k, 0.0) + float(v), 5)
        except Exception:  # noqa: BLE001
            pass
    avg = round(total / encounters_with_cost, 4) if encounters_with_cost else 0.0
    return {
        "encounters_with_cost_data": encounters_with_cost,
        "total_usd": round(total, 4),
        "avg_per_encounter_usd": avg,
        "breakdown_usd": {k: round(v, 4) for k, v in sorted(breakdown_total.items())},
    }
