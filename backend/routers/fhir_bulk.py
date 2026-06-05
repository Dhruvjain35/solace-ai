"""Clinician-only FHIR Bulk Data ($export) router — thin layer over the service.

Exposes the SMART Backend Services bulk-export flow to clinicians:

  * ``POST /ehr/bulk/export``  — kick off a system/group/patient-level export and
    persist the resulting status-poll URL as a job (router → service → db).
  * ``GET  /ehr/bulk/jobs``    — list this hospital's recent export jobs.
  * ``GET  /ehr/bulk/jobs/{job_id}`` — poll a job's status once and, when the
    server reports the export complete, fetch + parse the NDJSON files and return
    a non-PHI summary (resource-type counts). The raw bulk PHI is not echoed in
    this endpoint's body.

Constitution:
  * ARCH-001 — the router never touches DynamoDB directly; all job state goes
    through ``db.storage`` (parameterized ``Key()`` queries, SEC-009; TTL,
    ARCH-009). All network/FHIR work goes through ``services.fhir_bulk_export``.
  * COMP-002 / QUAL-003 — every clinician action calls ``audit()``; errors raise
    ``HTTPException``.
  * SEC-005 — when a caller asks to surface free-text for AI use
    (``scan_for_ai=true``), the service runs ``content_guard.scan()`` first and
    the response carries only counts + findings, never raw PHI.
  * No PHI in logs.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from db import storage
from lib.auth import audit, require_clinician
from services import ehr_gateway, fhir_bulk_export

log = logging.getLogger(__name__)

router = APIRouter()

# Reuse the gateway's ehr_config builder so vendor/base_url/token resolution is
# identical to the write path — but extend it with the Backend Services block.


def _ehr_config(hospital_id: str) -> dict[str, Any]:
    """Build an ``ehr_config`` dict (gateway shape + Backend Services block).

    Mirrors ``routers/ehr.py:_ehr_config`` and adds the ``backend_services``
    block the bulk-export service consumes for client_credentials auth. A
    hospital with no EHR config resolves to the local mock back end.
    """
    hospital = storage.get_hospital(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail="hospital not found")

    cfg: dict[str, Any] = {
        "vendor": hospital.get("ehr_vendor") or "",
        "base_url": hospital.get("ehr_base_url") or hospital.get("fhir_base_url") or "",
        "access_token": hospital.get("ehr_access_token") or "",
    }
    bs = hospital.get("ehr_backend_services")
    if isinstance(bs, dict) and bs:
        cfg["backend_services"] = bs
    return cfg


def _http_client() -> httpx.Client:
    """Construct a real httpx client for live FHIR traffic.

    Overridden in tests via FastAPI dependency injection to point at the mock
    FHIR server's transport.
    """
    return httpx.Client(timeout=30.0, follow_redirects=True)


class BulkExportBody(BaseModel):
    """Kick off a FHIR Bulk Data ``$export``."""

    level: str = Field("system", description="system | group | patient")
    group_id: str | None = Field(None, description="Required when level == 'group'")
    type_filter: list[str] | None = Field(
        None, description="FHIR _type filter, e.g. ['Patient','Observation']"
    )
    since: str | None = Field(None, description="ISO instant _since filter")


@router.post("/ehr/bulk/export")
def kickoff_bulk_export(
    request: Request,
    hospital_id: str = Path(...),
    body: BulkExportBody = ...,
    caller: dict = Depends(require_clinician),
    http_client: httpx.Client = Depends(_http_client),
) -> dict[str, Any]:
    """Kick off an async bulk export; persist the job; return its handle.

    Performs only the kickoff (and the Backend Services token exchange) so the
    request returns quickly even for large exports — the caller then polls
    ``GET /ehr/bulk/jobs/{job_id}``.
    """
    level = (body.level or "system").lower()
    if level not in fhir_bulk_export._LEVELS:
        raise HTTPException(status_code=400, detail=f"invalid export level '{level}'")
    if level == "group" and not body.group_id:
        raise HTTPException(status_code=400, detail="group-level export requires group_id")

    audit(
        caller, "ehr.bulk_export_kickoff", request=request,
        extra={"level": level, "type_filter": body.type_filter or [], "has_since": bool(body.since)},
    )

    cfg = _ehr_config(hospital_id)
    base_url = fhir_bulk_export.resolve_base_url(cfg)
    if not base_url:
        raise HTTPException(status_code=400, detail="hospital has no FHIR base_url configured")

    auth = fhir_bulk_export.resolve_auth(cfg)
    try:
        token = (
            fhir_bulk_export.fetch_backend_services_token(auth, http_client=http_client)
            if auth is not None else None
        )
        status_url = fhir_bulk_export.kickoff_export(
            base_url,
            level=level,
            group_id=body.group_id,
            http_client=http_client,
            access_token=token,
            type_filter=body.type_filter,
            since=body.since,
        )
    except fhir_bulk_export.BulkExportError as e:
        log.warning("bulk export kickoff failed: phase=%s status=%s", e.phase, e.status_code)
        raise HTTPException(status_code=502, detail=f"bulk export kickoff failed: {e.message}") from e

    job_id = f"job-{secrets.token_urlsafe(12)}"
    storage.put_bulk_job({
        "hospital_id": hospital_id,
        "job_id": job_id,
        "level": level,
        "status_url": status_url,
        "state": "in-progress",
        "clinician_id": caller.get("clinician_id"),
    })
    return {"job_id": job_id, "level": level, "state": "in-progress"}


@router.get("/ehr/bulk/jobs")
def list_bulk_jobs(
    request: Request,
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """List this hospital's bulk-export jobs (most recent first)."""
    audit(caller, "ehr.bulk_export_list", request=request)
    jobs = storage.list_bulk_jobs(hospital_id)
    # Strip internal fields; never echo the raw status_url (it can be a
    # capability URL) beyond what the owner needs.
    public = [
        {
            "job_id": j.get("job_id"),
            "level": j.get("level"),
            "state": j.get("state"),
            "created_at": j.get("created_at"),
            "file_count": j.get("file_count"),
            "resource_counts": j.get("resource_counts"),
        }
        for j in jobs
    ]
    return {"jobs": public}


@router.get("/ehr/bulk/jobs/{job_id}")
def poll_bulk_job(
    request: Request,
    hospital_id: str = Path(...),
    job_id: str = Path(...),
    scan_for_ai: bool = Query(
        False,
        description="Run content_guard over ingested free-text (SEC-005) and "
                    "return only counts/findings — never raw PHI.",
    ),
    caller: dict = Depends(require_clinician),
    http_client: httpx.Client = Depends(_http_client),
) -> dict[str, Any]:
    """Poll one bulk-export job; on completion fetch files + return a summary.

    The response carries resource-type counts (and, when ``scan_for_ai`` is set,
    a content-guard summary), never the raw bulk PHI.
    """
    job = storage.get_bulk_job(hospital_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="bulk job not found")

    audit(caller, "ehr.bulk_export_poll", request=request, extra={"job_id": job_id})

    cfg = _ehr_config(hospital_id)
    auth = fhir_bulk_export.resolve_auth(cfg)
    status_url = job.get("status_url", "")
    try:
        token = (
            fhir_bulk_export.fetch_backend_services_token(auth, http_client=http_client)
            if auth is not None else None
        )
        status = fhir_bulk_export.poll_status_once(
            status_url, http_client=http_client, access_token=token
        )
    except fhir_bulk_export.BulkExportError as e:
        log.warning("bulk export poll failed: phase=%s status=%s", e.phase, e.status_code)
        raise HTTPException(status_code=502, detail=f"bulk export poll failed: {e.message}") from e

    if not status.done:
        return {"job_id": job_id, "state": "in-progress", "progress": status.progress}

    # Complete — fetch and parse all NDJSON files.
    manifest = status.manifest or {}
    files = fhir_bulk_export.manifest_files(manifest)
    resource_counts: dict[str, int] = {}
    resources_by_type: dict[str, list[dict[str, Any]]] = {}
    try:
        for entry in files:
            rows = fhir_bulk_export.fetch_ndjson_resources(
                entry["url"], http_client=http_client, access_token=token,
            )
            rtype = entry["type"] or (rows[0].get("resourceType", "Resource") if rows else "Resource")
            resources_by_type.setdefault(rtype, []).extend(rows)
            resource_counts[rtype] = resource_counts.get(rtype, 0) + len(rows)
    except fhir_bulk_export.BulkExportError as e:
        log.warning("bulk file fetch failed: phase=%s", e.phase)
        raise HTTPException(status_code=502, detail=f"bulk file fetch failed: {e.message}") from e

    result = fhir_bulk_export.ExportResult(
        status_url=status_url, manifest=manifest,
        resources_by_type=resources_by_type, file_count=len(files),
    )

    body: dict[str, Any] = {
        "job_id": job_id,
        "state": "complete",
        "file_count": len(files),
        "resource_counts": resource_counts,
        "total_resources": result.total_resources,
    }

    if scan_for_ai:
        source_ip = request.headers.get("x-forwarded-for", "") or None
        user_agent = request.headers.get("user-agent") or None
        body["content_guard"] = fhir_bulk_export.scan_export_for_ai(
            result, source_ip=source_ip, user_agent=user_agent,
        )

    # Persist the completed job summary (no PHI — counts only).
    storage.put_bulk_job({
        "hospital_id": hospital_id,
        "job_id": job_id,
        "level": job.get("level"),
        "status_url": status_url,
        "state": "complete",
        "file_count": len(files),
        "resource_counts": resource_counts,
        "clinician_id": job.get("clinician_id"),
        "created_at": job.get("created_at"),
    })
    return body


@router.get("/ehr/bulk/vendor-status")
def bulk_vendor_status(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Report how this hospital's bulk-export traffic routes (no external I/O)."""
    audit(caller, "ehr.bulk_vendor_status")
    cfg = _ehr_config(hospital_id)
    status = ehr_gateway.vendor_status(cfg)
    auth = fhir_bulk_export.resolve_auth(cfg)
    status["backend_services_configured"] = bool(auth and auth.configured)
    return status
