"""Copilot Agent endpoints — bounded agentic chat + confirm-gated chart writes.

POST /api/{hospital_id}/patients/{patient_id}/copilot/agent
    Runs the bounded tool loop (services/copilot/agent.py). The model only ever
    sees coded chart metadata; consent (SEC-004) + tenancy are enforced at the
    PHI boundary inside context.build_chart. Returns proposed actions — nothing
    is written here.

POST /api/{hospital_id}/patients/{patient_id}/copilot/agent/execute
    Writes ONLY the actions the clinician explicitly confirmed (they arrive in
    the request body). Each action is allowlist-checked, given a server-side
    Patient subject reference, audited individually, and routed through the
    same ehr_gateway path as routers/ehr.py write_back.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from db import storage
from lib import tenant
from lib.auth import audit, require_clinician
from routers.ehr import _ehr_config
from services import ehr_gateway
from services.copilot import agent

log = logging.getLogger(__name__)

router = APIRouter()


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field("", max_length=8000)


class AgentBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=50)


@router.post("/patients/{patient_id}/copilot/agent")
def agent_chat(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: AgentBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """One agent turn: message + capped history in; reply + proposals out."""
    audit(caller, "copilot.agent", patient_id=patient_id)
    history = [{"role": h.role, "content": h.content}
               for h in body.history][-agent.HISTORY_CAP:]
    return agent.run_agent(hospital_id, patient_id, body.message, history)


class ActionItem(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    resource_type: str = Field(..., min_length=1, max_length=64)
    summary: str = Field("", max_length=500)
    resource: dict[str, Any]


class ExecuteBody(BaseModel):
    actions: list[ActionItem] = Field(..., min_length=1, max_length=20)


@router.post("/patients/{patient_id}/copilot/agent/execute")
def agent_execute(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: ExecuteBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Write the clinician-confirmed actions. ONLY what arrives in the request
    body is ever written — the server holds no pending-action state."""
    # Tenancy: the target patient must belong to this hospital (uniform 404).
    try:
        tenant.assert_patient_in_hospital(storage.get_patient(patient_id), hospital_id)
    except tenant.CrossTenantAccess:
        raise HTTPException(status_code=404, detail="Patient not found") from None

    cfg = _ehr_config(hospital_id)  # 404 if the hospital doesn't exist
    written: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for action in body.actions:
        allowed = action.resource_type in agent.ALLOWED_WRITE_TYPES
        audit(
            caller, "copilot.agent_execute", patient_id=patient_id,
            extra={"action_id": action.id, "resource_type": action.resource_type,
                   "allowed": allowed},
        )
        if not allowed:
            errors.append({
                "id": action.id,
                "error": (f"resource type '{action.resource_type}' is not allowed; "
                          f"must be one of {list(agent.ALLOWED_WRITE_TYPES)}"),
            })
            continue

        resource = dict(action.resource or {})
        resource["resourceType"] = action.resource_type
        # Attach the subject server-side — the model/client never addresses
        # the patient itself (AllergyIntolerance uses `patient`, others `subject`).
        ref = {"reference": f"Patient/{patient_id}"}
        if action.resource_type == "AllergyIntolerance":
            resource["patient"] = ref
            resource.pop("subject", None)
        else:
            resource["subject"] = ref
            resource.pop("patient", None)

        try:
            ehr_gateway.write_resource(resource, ehr_config=cfg)
            written.append({"id": action.id, "resource_type": action.resource_type,
                            "summary": action.summary})
        except ehr_gateway.EhrGatewayError as e:
            log.warning("agent execute write failed (%s): %s", action.id, e)
            errors.append({"id": action.id, "error": f"EHR write failed: {e.message}"})
        except Exception as e:  # noqa: BLE001 — one bad action must not abort the rest
            log.warning("agent execute write error (%s): %s", action.id, e)
            errors.append({"id": action.id, "error": "EHR write failed"})

    return {"written": written, "errors": errors}
