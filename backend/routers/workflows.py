"""Workflow CRUD + catalog endpoints (clinician-auth)."""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from lib.auth import audit, require_clinician
from services.workflows import actions, engine, phi, storage, templates, triggers

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/workflows/catalog")
def catalog(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """One call returns everything the workflow editor needs to render:
    available triggers, available actions (with field schemas), and the
    template list."""
    audit(caller, "workflows.catalog")
    return {
        "triggers": triggers.to_public_list(),
        "actions": actions.to_public_list(),
        "templates": [
            {"id": t["id"], "label": t["label"], "description": t["description"],
             "trigger": t["trigger"]}
            for t in templates.TEMPLATES
        ],
    }


@router.get("/workflows")
def list_workflows(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "workflows.list")
    return {"workflows": storage.list_for_hospital(hospital_id)}


class WorkflowBody(BaseModel):
    name: str
    trigger: str
    enabled: bool = True
    filters: dict | None = None
    steps: list[dict] = []


@router.post("/workflows")
def create_workflow(
    hospital_id: str = Path(...),
    body: WorkflowBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    if body is None or not body.name.strip() or not body.trigger:
        raise HTTPException(status_code=400, detail="name + trigger required")
    if not triggers.by_name(body.trigger):
        raise HTTPException(status_code=400, detail=f"unknown trigger '{body.trigger}'")
    _validate_steps(body.steps)
    _validate_no_phi(body.steps, body.filters)
    audit(caller, "workflows.create")

    workflow_id = f"wf-{secrets.token_urlsafe(10)}"
    record = {
        "workflow_id": workflow_id,
        "hospital_id": hospital_id,
        "name": body.name.strip(),
        "trigger": body.trigger,
        "enabled": body.enabled,
        "filters": body.filters or {},
        "steps": body.steps,
        "fire_count": 0,
        "created_by": caller.get("name", ""),
    }
    storage.put(record)
    return {"success": True, "workflow": record}


@router.put("/workflows/{workflow_id}")
def update_workflow(
    hospital_id: str = Path(...),
    workflow_id: str = Path(...),
    body: WorkflowBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    if body is None:
        raise HTTPException(status_code=400, detail="body required")
    existing = storage.get(workflow_id)
    if not existing or existing.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="workflow not found")
    if not triggers.by_name(body.trigger):
        raise HTTPException(status_code=400, detail=f"unknown trigger '{body.trigger}'")
    _validate_steps(body.steps)
    _validate_no_phi(body.steps, body.filters)
    audit(caller, "workflows.update", patient_id=workflow_id)
    existing.update({
        "name": body.name.strip(),
        "trigger": body.trigger,
        "enabled": body.enabled,
        "filters": body.filters or {},
        "steps": body.steps,
    })
    storage.put(existing)
    return {"success": True, "workflow": existing}


@router.delete("/workflows/{workflow_id}")
def delete_workflow(
    hospital_id: str = Path(...),
    workflow_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    existing = storage.get(workflow_id)
    if not existing or existing.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="workflow not found")
    audit(caller, "workflows.delete", patient_id=workflow_id)
    storage.delete(workflow_id)
    return {"success": True}


class TestBody(BaseModel):
    workflow_id: str | None = None
    workflow: dict | None = None  # for testing an unsaved draft


@router.post("/workflows/test")
def test_workflow(
    hospital_id: str = Path(...),
    body: TestBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Dry-run a workflow against the trigger's sample context. Useful in the
    editor to see what would happen without firing the real event."""
    audit(caller, "workflows.test")
    wf = None
    if body and body.workflow_id:
        wf = storage.get(body.workflow_id)
    if not wf and body and body.workflow:
        wf = body.workflow
    if not wf:
        raise HTTPException(status_code=400, detail="workflow_id or workflow required")
    trig = triggers.by_name(wf.get("trigger", ""))
    if not trig:
        raise HTTPException(status_code=400, detail="trigger missing on workflow")
    context = {**trig.sample_context, "trigger": trig.name, "test_mode": True}
    results = []
    for step in wf.get("steps") or []:
        if not isinstance(step, dict):
            continue
        r = actions.run(step.get("type", ""), step.get("config") or {}, context)
        results.append({"step_type": step.get("type"), "result": r})
    return {"context": context, "results": results}


class FromTemplateBody(BaseModel):
    template_id: str


@router.post("/workflows/from-template")
def from_template(
    hospital_id: str = Path(...),
    body: FromTemplateBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    if body is None:
        raise HTTPException(status_code=400, detail="template_id required")
    tpl = templates.by_id(body.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="template not found")
    audit(caller, "workflows.from_template")
    workflow_id = f"wf-{secrets.token_urlsafe(10)}"
    record = {
        "workflow_id": workflow_id,
        "hospital_id": hospital_id,
        "name": tpl["label"],
        "trigger": tpl["trigger"],
        "enabled": False,  # disabled by default — admin fills missing fields then enables
        "filters": tpl.get("filters") or {},
        "steps": tpl["steps"],
        "fire_count": 0,
        "from_template": tpl["id"],
        "created_by": caller.get("name", ""),
    }
    storage.put(record)
    return {"success": True, "workflow": record}


# --- helpers ----------------------------------------------------------------


def _validate_steps(steps: list[dict]) -> None:
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="steps must be a list")
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or not s.get("type"):
            raise HTTPException(status_code=400, detail=f"step {i} missing type")
        if not actions.by_type(s["type"]):
            raise HTTPException(status_code=400, detail=f"step {i} unknown type '{s['type']}'")


def _validate_no_phi(steps: list[dict], filters: dict | None) -> None:
    """PHI-safety gate — reject any workflow whose step configs or filters
    reference a PHI context path or hard-code a literal PHI signature."""
    safe, findings = phi.validate_no_phi({"steps": steps, "filters": filters or {}})
    if not safe:
        raise HTTPException(
            status_code=422,
            detail=f"workflow rejected — PHI-leaking step template(s): {findings}",
        )


# Re-export for the route hooks below
fire = engine.fire
