"""FHIR Subscriptions router — create a Subscription + receive notifications.

Two faces:

  * Clinician-only (under ``/api/{hospital_id}``):
      - ``POST /ehr/subscriptions``            — create + register a Subscription.
      - ``GET  /ehr/subscriptions``            — list this hospital's subscriptions.

  * Webhook receiver (public, unauthenticated by clinician JWT — the EHR server
    calls it). Mounted at the app root because the path must be a stable,
    server-registered absolute URL:
      - ``POST /ehr/subscriptions/notify/{hospital_id}/{subscription_id}`` —
        ingest a notification. Authenticated by the per-subscription shared
        secret header, not a clinician session.

Constitution:
  * ARCH-001 — subscription state flows through ``db.storage`` only; the create
    write goes through ``services.ehr_gateway`` (vendor routing + retry + audit
    hook reused). Parameterized ``Key()`` queries (SEC-009) + TTL (ARCH-009) live
    in the db layer.
  * COMP-002 / QUAL-003 — clinician + notification actions call ``audit()``;
    errors raise ``HTTPException``.
  * SEC-005 — inbound notification free-text is scanned via ``content_guard``
    (delegated to the service) before any AI hand-off; only counts/findings are
    returned, never raw PHI.
  * No PHI in logs — only resource types, subscription ids, and counts.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, Field

from db import storage
from lib import audit as _audit
from lib.auth import audit, require_clinician
from services import ehr_gateway, fhir_subscriptions

log = logging.getLogger(__name__)

# Clinician-scoped router (mounted under /api/{hospital_id}).
router = APIRouter()

# Webhook receiver router (mounted at app root — absolute, EHR-registered path).
webhook_router = APIRouter()


def _ehr_config(hospital_id: str) -> dict[str, Any]:
    """Build the gateway ``ehr_config`` dict from a hospital's stored EHR settings.

    Mirrors ``routers/ehr.py:_ehr_config`` — kept local so this router stays
    independent of the ehr.py module (minimizes cross-file merge collisions).
    """
    hospital = storage.get_hospital(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail="hospital not found")
    hl7_host = hospital.get("ehr_hl7_host") or ""
    hl7_port = hospital.get("ehr_hl7_port") or 0
    cfg: dict[str, Any] = {
        "vendor": hospital.get("ehr_vendor") or "",
        "base_url": hospital.get("ehr_base_url") or hospital.get("fhir_base_url") or "",
        "access_token": hospital.get("ehr_access_token") or "",
    }
    if hl7_host and hl7_port:
        cfg["hl7"] = {"host": hl7_host, "port": int(hl7_port)}
    return cfg


class SubscriptionBody(BaseModel):
    """Create a FHIR Subscription (rest-hook channel)."""

    criteria: str = Field(
        ..., description="FHIR search criteria the server watches, e.g. "
                         "'Encounter?status=in-progress'"
    )
    callback_base_url: str = Field(
        ..., description="Public base URL of this Solace deployment (https://...). "
                         "The webhook endpoint path is appended automatically."
    )
    end: str | None = Field(None, description="Optional ISO instant when the subscription expires")
    dry_run: bool = Field(False, description="Preview routing without external I/O")


@router.post("/ehr/subscriptions")
def create_subscription(
    request: Request,
    hospital_id: str = Path(...),
    body: SubscriptionBody = ...,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """Create + register a FHIR Subscription for change notifications.

    Builds a ``rest-hook`` Subscription pointing back at this deployment's
    webhook receiver, writes it through the EHR gateway (vendor routing + retry +
    audit), and persists the registration (with its shared secret) so inbound
    notifications can be verified.
    """
    if not body.criteria.strip():
        raise HTTPException(status_code=400, detail="criteria is required")
    if not body.callback_base_url.startswith("https://") and \
            not body.callback_base_url.startswith("http://localhost"):
        raise HTTPException(
            status_code=400,
            detail="callback_base_url must be https:// (or http://localhost for dev)",
        )

    subscription_id = f"sub-{secrets.token_urlsafe(12)}"
    secret = fhir_subscriptions.generate_subscription_secret()
    endpoint = (
        f"{body.callback_base_url.rstrip('/')}"
        f"/ehr/subscriptions/notify/{hospital_id}/{subscription_id}"
    )

    audit(
        caller, "ehr.subscription_create", request=request,
        extra={"criteria_type": body.criteria.split("?", 1)[0], "dry_run": body.dry_run},
    )

    cfg = _ehr_config(hospital_id)
    try:
        result = fhir_subscriptions.create_subscription(
            criteria=body.criteria,
            endpoint=endpoint,
            ehr_config=cfg,
            secret_header=secret,
            end=body.end,
            dry_run=body.dry_run,
        )
    except ehr_gateway.EhrGatewayError as e:
        log.warning("subscription create failed: %s", e)
        raise HTTPException(status_code=502, detail=f"subscription create failed: {e.message}") from e

    # Persist the registration (the secret is server-side state, never returned
    # to the EHR or echoed in logs).
    storage.put_subscription({
        "hospital_id": hospital_id,
        "subscription_id": subscription_id,
        "criteria": body.criteria,
        "endpoint": endpoint,
        "secret": secret,
        "remote_id": result.get("id"),
        "state": "requested",
        "clinician_id": caller.get("clinician_id"),
    })

    return {
        "subscription_id": subscription_id,
        "criteria": body.criteria,
        "endpoint": endpoint,
        "state": "requested",
        "remote_id": result.get("id"),
        "dry_run": result.get("dry_run", False),
    }


@router.get("/ehr/subscriptions")
def list_subscriptions(
    request: Request,
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    """List this hospital's registered subscriptions (secret omitted)."""
    audit(caller, "ehr.subscription_list", request=request)
    subs = storage.list_subscriptions(hospital_id)
    public = [
        {
            "subscription_id": s.get("subscription_id"),
            "criteria": s.get("criteria"),
            "endpoint": s.get("endpoint"),
            "state": s.get("state"),
            "remote_id": s.get("remote_id"),
            "created_at": s.get("created_at"),
        }
        for s in subs
    ]
    return {"subscriptions": public}


@webhook_router.post("/ehr/subscriptions/notify/{hospital_id}/{subscription_id}")
async def receive_notification(
    request: Request,
    hospital_id: str = Path(...),
    subscription_id: str = Path(...),
    x_solace_subscription_secret: str | None = Header(None),
) -> dict[str, Any]:
    """Receive a FHIR Subscription notification from the EHR server.

    Authenticated by the per-subscription shared secret (not a clinician JWT).
    Parses the notification, runs content_guard over any inline free-text
    (SEC-005), audits the event (COMP-002), and returns a non-PHI summary. The
    raw notification body is never logged.
    """
    sub = storage.get_subscription(hospital_id, subscription_id)
    if not sub:
        # Do not reveal whether the hospital or the subscription is the unknown
        # part — a 404 either way avoids an enumeration oracle.
        raise HTTPException(status_code=404, detail="unknown subscription")

    expected_secret = sub.get("secret")
    headers = {"x-solace-subscription-secret": x_solace_subscription_secret or ""}
    if not fhir_subscriptions.verify_notification_secret(headers, expected_secret):
        _audit.record(
            clinician_id=None, clinician_name=None,
            action="ehr.subscription_notify_rejected",
            status_code=401,
            extra={"subscription_id": subscription_id, "reason": "bad_secret"},
        )
        raise HTTPException(status_code=401, detail="invalid subscription secret")

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 — a malformed body is still a (no-op) ping
        payload = {}

    parsed = fhir_subscriptions.parse_notification(payload if isinstance(payload, dict) else {})

    # SEC-005: scan any inline free-text before it could reach an AI provider.
    guard = fhir_subscriptions.scan_notification_for_ai(
        parsed,
        source_ip=request.headers.get("x-forwarded-for", "") or None,
        user_agent=request.headers.get("user-agent") or None,
    )

    # COMP-002: audit the ingestion with non-PHI metadata only.
    _audit.record(
        clinician_id=None, clinician_name=None,
        action="ehr.subscription_notify",
        status_code=200,
        extra={
            "subscription_id": subscription_id,
            "event": parsed.get("event"),
            "reference_count": len(parsed.get("references", [])),
            "resource_count": len(parsed.get("resources", [])),
            "rejected_for_ai": guard.get("rejected_resources", 0),
        },
    )

    # Mark the subscription active on first successful notification.
    if sub.get("state") != "active":
        storage.put_subscription({**sub, "state": "active"})

    return {
        "received": True,
        "event": parsed.get("event"),
        "reference_count": len(parsed.get("references", [])),
        "resource_count": len(parsed.get("resources", [])),
        "content_guard": guard,
    }
