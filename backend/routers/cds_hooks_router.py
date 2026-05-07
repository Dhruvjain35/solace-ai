"""CDS Hooks public service.

Mounted at the root path so EHRs hit `/cds-services` (the spec-required base).
No auth — CDS Hooks discovery is public; production should validate the EHR's
signed JWT from the hook request header.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from services import cds_hooks

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/cds-services")
def discovery() -> dict[str, Any]:
    return cds_hooks.discovery()


@router.post("/cds-services/solace-patient-view")
def patient_view(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return cds_hooks.patient_view(hook_request=payload)


@router.post("/cds-services/solace-order-select")
def order_select(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return cds_hooks.order_select(hook_request=payload)
