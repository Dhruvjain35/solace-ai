"""The encounter timeline — what this system decided, when, and how sure it was.

Reads ``services.encounter_ledger``. Two endpoints, and the split between them
is deliberate:

  GET /encounters/{id}/timeline   the record itself, plus whether it verifies
  GET /encounters/{id}/verify     only whether it verifies

A long stay accumulates a lot of entries, and every one of them is PHI. An
auditor or a monitor asking "has this record been altered" should not have to
move the record to find out, so ``verify`` answers on its own and returns no
clinical content at all.

Both are clinician-authenticated and hospital-scoped. A timeline is the complete
decision history for one patient, so it is a more concentrated disclosure than
any single decision on it, and it gets the same tenant check as everything else
(SEC-008).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Path

from lib import tenancy
from lib.auth import audit, require_clinician
from services import encounter_ledger

log = logging.getLogger(__name__)

router = APIRouter()


def _serialize(entry: encounter_ledger.Entry) -> dict[str, Any]:
    """One entry, as JSON.

    ``entry_hash`` and ``prev_hash`` are included on purpose. They are what lets
    somebody who does not trust us recompute the chain themselves from the same
    fields, which is the difference between a log and a record.
    """
    return {
        "seq": entry.seq,
        "model": entry.model,
        "model_version": entry.model_version,
        "observed_at": entry.observed_at.isoformat(),
        "recorded_at": entry.recorded_at.isoformat(),
        "inputs": entry.inputs,
        "output": entry.output,
        "uncertainty": entry.uncertainty,
        "prev_hash": entry.prev_hash,
        "entry_hash": entry.entry_hash,
    }


@router.get("/encounters/{patient_id}/timeline")
def timeline(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Every decision recorded for this encounter, oldest first.

    An encounter with nothing on it returns an empty list and verifies. "Nothing
    has been decided yet" is a real answer and a different one from "no such
    patient", which is the 404 above it.
    """
    audit(caller, "encounters.timeline", patient_id=patient_id)
    tenancy.require_patient(patient_id, hospital_id)

    entries = encounter_ledger.timeline(patient_id)
    result = encounter_ledger.verify(patient_id)
    return {
        "encounter_id": patient_id,
        "entries": [_serialize(e) for e in entries],
        "verified": result.ok,
        "checked": result.checked,
        "broken_at": result.broken_at,
        "reason": result.reason,
    }


@router.get("/encounters/{patient_id}/verify")
def verify(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Whether the chain for this encounter is intact, and nothing else.

    Returns no clinical content, so a monitor can poll it continuously without
    moving PHI around to ask a question about integrity.
    """
    audit(caller, "encounters.verify", patient_id=patient_id)
    tenancy.require_patient(patient_id, hospital_id)

    result = encounter_ledger.verify(patient_id)
    return {
        "encounter_id": patient_id,
        "ok": result.ok,
        "checked": result.checked,
        "broken_at": result.broken_at,
        "reason": result.reason,
    }
