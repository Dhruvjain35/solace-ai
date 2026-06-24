"""Clinician-facing Workspace endpoints — multi-tenant sub-scope CRUD.

A Workspace is a sub-tenant scope WITHIN a hospital (department / clinic / care
team). hospital_id stays the top-level tenant boundary; workspace_id is a child
scope owned by exactly one hospital. These routes are mounted under
``/api/{hospital_id}`` so the path itself names the owning tenant, and
``require_clinician`` (SEC-008) verifies the caller's JWT hospital_id matches that
path segment before any handler runs.

Layering: the router never touches DynamoDB (ARCH-001) — all data access goes
through ``services.workspaces``, which in turn uses ``db.storage`` (boto3 stays in
db/, ARCH-002). Request bodies are inline Pydantic models (ARCH-005). Errors are
raised as HTTPException, and every mutation calls audit() (QUAL-003 / COMP-002).

  - GET    /workspaces                     — list workspaces for this hospital
  - POST   /workspaces                     — create a workspace
  - GET    /workspaces/{workspace_id}      — fetch one workspace
  - PATCH  /workspaces/{workspace_id}      — update name/description/status
  - DELETE /workspaces/{workspace_id}      — delete a workspace
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from lib.auth import audit, require_clinician
from services import workspaces as workspace_service

log = logging.getLogger(__name__)

router = APIRouter()


# ---- Inline request models (ARCH-005) ----------------------------------------------
class CreateWorkspaceBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    # Optional caller-chosen id; validated + uniqueness-checked in the service. When
    # omitted the service generates one from the name.
    requested_id: str | None = Field(None, max_length=48)


class UpdateWorkspaceBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    status: str | None = Field(None, max_length=20)


def _to_http(err: workspace_service.WorkspaceError) -> HTTPException:
    """Map a service error to an HTTPException, hiding internals from the client.

    Cross-tenant and not-found collapse to 404 so existence is never revealed across
    hospitals (SEC-008). Validation/collision map to 400/409.
    """
    code = getattr(err, "code", "workspace_error")
    if code == "workspace_not_found":
        return HTTPException(status_code=404, detail="workspace not found")
    if code == "invalid_workspace_id":
        return HTTPException(status_code=400, detail=str(err))
    if code == "workspace_exists":
        return HTTPException(status_code=409, detail=str(err))
    return HTTPException(status_code=400, detail=str(err))


@router.get("/workspaces")
def list_workspaces(
    request: Request,
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "workspaces.list", request=request)
    items = workspace_service.list_workspaces(hospital_id)
    return {"workspaces": items}


@router.post("/workspaces", status_code=201)
def create_workspace(
    body: CreateWorkspaceBody,
    request: Request,
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    try:
        ws = workspace_service.create_workspace(
            hospital_id=hospital_id,
            name=body.name,
            description=body.description,
            created_by=caller.get("clinician_id"),
            requested_id=body.requested_id,
        )
    except workspace_service.WorkspaceError as err:
        # Audit the failed attempt too — a 409/400 on create is still a clinician
        # action worth recording, but never leak why beyond the HTTP detail.
        http_err = _to_http(err)
        audit(
            caller, "workspaces.create_failed", request=request,
            status_code=http_err.status_code,
            extra={"hospital_id": hospital_id},
        )
        raise http_err

    audit(
        caller, "workspaces.create", request=request, status_code=201,
        extra={"hospital_id": hospital_id, "workspace_id": ws["workspace_id"]},
    )
    return ws


@router.get("/workspaces/{workspace_id}")
def get_workspace(
    request: Request,
    hospital_id: str = Path(...),
    workspace_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(
        caller, "workspaces.get", request=request,
        extra={"hospital_id": hospital_id, "workspace_id": workspace_id},
    )
    try:
        return workspace_service.get_workspace(hospital_id, workspace_id)
    except workspace_service.WorkspaceError as err:
        raise _to_http(err)


@router.patch("/workspaces/{workspace_id}")
def update_workspace(
    body: UpdateWorkspaceBody,
    request: Request,
    hospital_id: str = Path(...),
    workspace_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    try:
        ws = workspace_service.update_workspace(
            hospital_id, workspace_id, body.model_dump(exclude_none=True)
        )
    except workspace_service.WorkspaceError as err:
        raise _to_http(err)

    audit(
        caller, "workspaces.update", request=request, status_code=200,
        extra={"hospital_id": hospital_id, "workspace_id": workspace_id},
    )
    return ws


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(
    request: Request,
    hospital_id: str = Path(...),
    workspace_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    try:
        workspace_service.delete_workspace(hospital_id, workspace_id)
    except workspace_service.WorkspaceError as err:
        raise _to_http(err)

    audit(
        caller, "workspaces.delete", request=request, status_code=200,
        extra={"hospital_id": hospital_id, "workspace_id": workspace_id},
    )
    return {"deleted": True, "workspace_id": workspace_id}
