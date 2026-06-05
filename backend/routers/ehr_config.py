"""Clinician-facing per-workspace EHR-config endpoints.

Binds a workspace (department / clinic / care-team inside a hospital) to its own
EHR vendor connection: FHIR base URL, OAuth client_id, authorize/token endpoints,
SMART scope set, and — for confidential clients — the AWS Secrets Manager *name*
of the client secret / private key (the secret VALUE never travels through here,
COMP-007).

Mounted under ``/api/{hospital_id}`` so the path names the owning tenant, and
``require_clinician`` (SEC-008) verifies the caller's JWT hospital_id matches that
path segment before any handler runs.

Layering: the router never touches DynamoDB (ARCH-001) — all data access goes
through ``services.ehr_config`` → ``db.storage`` (boto3 stays in db/, ARCH-002).
Request bodies are inline Pydantic models (ARCH-005). Errors surface as
HTTPException (QUAL-003), and every mutation calls audit() (COMP-002).

  - GET    /workspaces/{workspace_id}/ehr-config   — fetch the binding
  - GET    /ehr-configs                            — list all bindings for the hospital
  - PUT    /workspaces/{workspace_id}/ehr-config   — create / replace the binding
  - PATCH  /workspaces/{workspace_id}/ehr-config   — patch fields
  - DELETE /workspaces/{workspace_id}/ehr-config   — remove the binding
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from lib.auth import audit, require_clinician
from services import ehr_config as ehr_config_service

log = logging.getLogger(__name__)

router = APIRouter()


# ---- Inline request models (ARCH-005) ----------------------------------------------
class EHRConfigBody(BaseModel):
    """Create/replace body. ``vendor`` is required on first create; endpoint URLs
    default from the static vendor template when omitted (public-sandbox case)."""

    vendor: str | None = Field(None, max_length=32, description="smart | epic | cerner | athena | <custom>")
    fhir_base_url: str | None = Field(None, max_length=512)
    authorize_url: str | None = Field(None, max_length=512)
    token_url: str | None = Field(None, max_length=512)
    client_id: str | None = Field(None, max_length=256)
    scopes: list[str] | None = Field(None, description="SMART v1 (.read) scope tokens")
    scopes_v2: list[str] | None = Field(None, description="SMART v2 (.cruds) scope tokens")
    smart_version: str | None = Field(None, max_length=8, description="v1 | v2")
    label: str | None = Field(None, max_length=120)
    sandbox: bool | None = None
    status: str | None = Field(None, max_length=16, description="active | disabled")
    # Secrets Manager *names* only — never inline secret values (COMP-007).
    client_secret_ref: str | None = Field(
        None, max_length=512, description="AWS Secrets Manager name of the client secret"
    )
    private_key_ref: str | None = Field(
        None, max_length=512, description="AWS Secrets Manager name of the RS384 private key PEM"
    )
    kid: str | None = Field(None, max_length=256, description="JWK kid for the signing key")


class EHRConfigPatchBody(EHRConfigBody):
    """Patch body — same shape as create, all fields optional (vendor optional too)."""


def _to_http(err: ehr_config_service.EHRConfigError) -> HTTPException:
    """Map a service error to an HTTPException, hiding internals from the client.

    Cross-tenant and not-found collapse to 404 so existence is never revealed across
    hospitals (SEC-008). Validation maps to 400.
    """
    code = getattr(err, "code", "ehr_config_error")
    if code == "ehr_config_not_found":
        return HTTPException(status_code=404, detail="ehr config not found")
    if code in ("invalid_ehr_config", "invalid_workspace_id"):
        return HTTPException(status_code=400, detail=str(err))
    return HTTPException(status_code=400, detail=str(err))


def _map_error(err: Exception) -> HTTPException:
    """Map either an EHRConfigError or a WorkspaceError (the binding target must
    exist for THIS hospital) to an HTTPException, collapsing not-found to 404."""
    code = getattr(err, "code", "")
    if code in ("workspace_not_found",):
        return HTTPException(status_code=404, detail="workspace not found")
    if code in ("invalid_workspace_id",):
        return HTTPException(status_code=400, detail=str(err))
    if isinstance(err, ehr_config_service.EHRConfigError):
        return _to_http(err)
    raise err  # not a known domain error — let it surface


@router.get("/ehr-configs")
def list_ehr_configs(
    request: Request,
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "ehr_config.list", request=request, extra={"hospital_id": hospital_id})
    return {"configs": ehr_config_service.list_configs(hospital_id)}


@router.get("/workspaces/{workspace_id}/ehr-config")
def get_ehr_config(
    request: Request,
    hospital_id: str = Path(...),
    workspace_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(
        caller, "ehr_config.get", request=request,
        extra={"hospital_id": hospital_id, "workspace_id": workspace_id},
    )
    try:
        return ehr_config_service.get_config(hospital_id, workspace_id)
    except ehr_config_service.EHRConfigError as err:
        raise _to_http(err)


@router.put("/workspaces/{workspace_id}/ehr-config")
def put_ehr_config(
    body: EHRConfigBody,
    request: Request,
    hospital_id: str = Path(...),
    workspace_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    try:
        cfg = ehr_config_service.upsert_config(
            hospital_id=hospital_id,
            workspace_id=workspace_id,
            body=body.model_dump(exclude_none=True),
            created_by=caller.get("clinician_id"),
        )
    except Exception as err:  # noqa: BLE001 — mapped below; unknown errors re-raise
        http_err = _map_error(err)
        audit(
            caller, "ehr_config.upsert_failed", request=request,
            status_code=http_err.status_code,
            extra={"hospital_id": hospital_id, "workspace_id": workspace_id},
        )
        raise http_err
    audit(
        caller, "ehr_config.upsert", request=request, status_code=200,
        extra={"hospital_id": hospital_id, "workspace_id": workspace_id,
               "vendor": cfg.get("vendor")},
    )
    return cfg


@router.patch("/workspaces/{workspace_id}/ehr-config")
def patch_ehr_config(
    body: EHRConfigPatchBody,
    request: Request,
    hospital_id: str = Path(...),
    workspace_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    try:
        cfg = ehr_config_service.update_config(
            hospital_id, workspace_id, body.model_dump(exclude_none=True)
        )
    except ehr_config_service.EHRConfigError as err:
        raise _to_http(err)
    audit(
        caller, "ehr_config.update", request=request, status_code=200,
        extra={"hospital_id": hospital_id, "workspace_id": workspace_id},
    )
    return cfg


@router.delete("/workspaces/{workspace_id}/ehr-config")
def delete_ehr_config(
    request: Request,
    hospital_id: str = Path(...),
    workspace_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    try:
        ehr_config_service.delete_config(hospital_id, workspace_id)
    except ehr_config_service.EHRConfigError as err:
        raise _to_http(err)
    audit(
        caller, "ehr_config.delete", request=request, status_code=200,
        extra={"hospital_id": hospital_id, "workspace_id": workspace_id},
    )
    return {"deleted": True, "workspace_id": workspace_id}
