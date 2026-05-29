"""CDS Hooks 2.0 public service.

Mounted at the root path so EHRs hit `/cds-services` (the spec-required
discovery base). No auth — CDS Hooks discovery is public; production should
additionally validate the EHR's signed JWT from the hook `Authorization`
header.

Endpoints:
  - GET  /cds-services                              discovery document
  - POST /cds-services/solace-patient-view          patient-view hook
  - POST /cds-services/solace-order-select          order-select hook
  - POST /cds-services/solace-order-sign            order-sign hook (hard-stop)
  - POST /cds-services/solace-encounter-discharge   encounter-discharge hook

Malformed hook requests raise cds_hooks.HookValidationError, which every
handler endpoint maps to HTTP 400 with a clear, spec-aligned message.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from services import cds_hooks
from services.cds_hooks import HookValidationError

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/cds-services")
def discovery() -> dict[str, Any]:
    """CDS Hooks discovery — lists every Solace decision-support service."""
    return cds_hooks.discovery()


@router.post("/cds-services/solace-patient-view")
def patient_view(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """patient-view hook — open HEDIS care gaps for the chart being viewed."""
    try:
        return cds_hooks.patient_view(hook_request=payload)
    except HookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cds-services/solace-order-select")
def order_select(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """order-select hook — advisory drug-interaction check on the draft order."""
    try:
        return cds_hooks.order_select(hook_request=payload)
    except HookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cds-services/solace-order-sign")
def order_sign(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """order-sign hook — final safety check; hard-stops high-severity conflicts."""
    try:
        return cds_hooks.order_sign(hook_request=payload)
    except HookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cds-services/solace-encounter-discharge")
def encounter_discharge(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """encounter-discharge hook — red-flag and care-gap review before discharge."""
    try:
        return cds_hooks.encounter_discharge(hook_request=payload)
    except HookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
