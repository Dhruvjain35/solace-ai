"""EHR Copilot endpoints — agentic chart Q&A, summary, fixable-issue scan, and
EHR→chart autopopulation diff. Clinician-auth only; every call is audited.

Mounted under /api/{hospital_id}. See services/ehr_copilot.py for the agent.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from lib.auth import audit, require_clinician
from services import ehr_copilot

log = logging.getLogger(__name__)

router = APIRouter()


class AskBody(BaseModel):
    patient_id: str
    question: str = Field(..., min_length=2, max_length=1000)


class PatientBody(BaseModel):
    patient_id: str


@router.post("/copilot/ask")
def copilot_ask(
    hospital_id: str = Path(...),
    body: AskBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Grounded Q&A over the patient's chart, with citations."""
    audit(caller, "copilot.ask", patient_id=body.patient_id)
    result = ehr_copilot.ask(hospital_id, body.patient_id, body.question)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.post("/copilot/summary")
def copilot_summary(
    hospital_id: str = Path(...),
    body: PatientBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Catch-me-up longitudinal summary of the patient."""
    audit(caller, "copilot.summary", patient_id=body.patient_id)
    result = ehr_copilot.summary(hospital_id, body.patient_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.post("/copilot/scan")
def copilot_scan(
    hospital_id: str = Path(...),
    body: PatientBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Proactive fixable-issue finder — care gaps, drug interactions."""
    audit(caller, "copilot.scan", patient_id=body.patient_id)
    return ehr_copilot.scan(hospital_id, body.patient_id)


@router.post("/copilot/autopopulate")
def copilot_autopopulate(
    hospital_id: str = Path(...),
    body: PatientBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """EHR→chart field diff for a review/accept UI (read-only)."""
    audit(caller, "copilot.autopopulate", patient_id=body.patient_id)
    return ehr_copilot.autopopulate(hospital_id, body.patient_id)
