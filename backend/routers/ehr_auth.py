"""SMART-on-FHIR sign-in for clinicians.

Two surfaces:

1. **Real flow (production)**: when an Epic / Cerner / Athena client_id is
   configured via env, the launch endpoint redirects the clinician to the
   vendor's authorize URL. The vendor handles login + consent, then redirects
   back to /api/auth/ehr/callback?code=... which we exchange for a FHIR
   access_token + Practitioner identity, then issue our own Solace JWT.

2. **Mock flow (demo)**: same shape, but `mock-authorize` returns a synthetic
   auth code and `mock-token` returns a fake FHIR token + a Practitioner
   resource scaffolded from the demo clinician set. End-to-end works against
   the existing seeded data without any vendor onboarding.

The Solace JWT issued at the end embeds the vendor + FHIR base URL so every
downstream EHR query knows where to talk.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from db import storage
from lib import ehr_vendors, jwt_auth

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/ehr", tags=["ehr-auth"])


# ----------------------------------------------------------------------------------
# Vendor catalog (frontend reads this to render the Sign-in-with buttons)
# ----------------------------------------------------------------------------------


@router.get("/vendors")
def list_vendors() -> dict:
    return {"vendors": ehr_vendors.list_public()}


# ----------------------------------------------------------------------------------
# Launch — clinician clicks "Sign in with Epic" → we 302 to the vendor authorize URL
# ----------------------------------------------------------------------------------


# Cross-request nonce store. Same in-memory dict approach as our intake nonces — fine
# for a single Lambda warm container, in prod we'd back this with DDB. The launch
# state survives long enough for the redirect round-trip; if the Lambda goes cold
# the user gets a fresh launch anyway.
_LAUNCH_STATES: dict[str, dict[str, Any]] = {}
_STATE_TTL = 600  # 10 minutes


def _gc_states() -> None:
    now = int(time.time())
    expired = [k for k, v in _LAUNCH_STATES.items() if v.get("exp", 0) < now]
    for k in expired:
        _LAUNCH_STATES.pop(k, None)


@router.get("/launch")
def launch(
    vendor: str = Query(..., description="epic | cerner | athena"),
    hospital_id: str = Query("demo"),
    redirect_uri: str = Query(..., description="Frontend URL to return to after success"),
) -> RedirectResponse:
    v = ehr_vendors.get(vendor)
    if not v:
        raise HTTPException(status_code=404, detail=f"Unknown EHR vendor '{vendor}'")
    _gc_states()

    state = secrets.token_urlsafe(24)
    _LAUNCH_STATES[state] = {
        "vendor": v.id,
        "hospital_id": hospital_id,
        "redirect_uri": redirect_uri,
        "exp": int(time.time()) + _STATE_TTL,
    }

    params = {
        "response_type": "code",
        "client_id": v.client_id,
        "redirect_uri": _solace_callback_url(),
        "scope": " ".join(v.scopes),
        "state": state,
        "aud": v.fhir_base_url,
    }
    return RedirectResponse(f"{v.authorize_url}?{urlencode(params)}", status_code=302)


# ----------------------------------------------------------------------------------
# Callback — vendor redirects here with ?code=... — we exchange for a FHIR token,
# fetch the Practitioner, then mint a Solace JWT and bounce back to the frontend.
# ----------------------------------------------------------------------------------


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str = Query(...),
    request: Request = None,
) -> RedirectResponse:
    rec = _LAUNCH_STATES.pop(state, None)
    if not rec or rec.get("exp", 0) < int(time.time()):
        raise HTTPException(status_code=400, detail="invalid or expired state")
    vendor = ehr_vendors.get(rec["vendor"])
    if not vendor:
        raise HTTPException(status_code=400, detail="vendor missing on stored state")

    # Exchange the auth code for an access_token + Practitioner identity.
    # The mock token endpoint returns a synthetic Practitioner so the demo runs
    # without provisioning anything; real Epic/Cerner returns the real one.
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                vendor.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _solace_callback_url(),
                    "client_id": vendor.client_id,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("EHR token exchange failed (%s): %s", vendor.id, e)
        return _redirect_with_error(rec["redirect_uri"], "token_exchange_failed")

    practitioner = payload.get("practitioner") or {}
    fhir_user = payload.get("fhirUser") or practitioner.get("id") or "unknown"
    name = (
        practitioner.get("name")
        or payload.get("name")
        or "EHR Clinician"
    )
    role = practitioner.get("role", "clinician")
    hospital_id = rec["hospital_id"]

    # Map the vendor identity to (or create) a Solace clinician. For the mock
    # path we simply mint a session-only clinician keyed on the FHIR user id
    # so audit logging has a stable handle. Production would persist this
    # mapping in `solace-clinicians`.
    clinician = {
        "clinician_id": f"ehr-{vendor.id}-{fhir_user}",
        "name": str(name),
        "role": role,
        "hospital_id": hospital_id,
        "ehr_vendor": vendor.id,
        "fhir_base_url": vendor.fhir_base_url,
        "fhir_access_token": payload.get("access_token", ""),
    }

    try:
        token, sess = jwt_auth.issue_token(clinician)
    except Exception as e:  # noqa: BLE001
        log.exception("issue_token failed for EHR session: %s", e)
        return _redirect_with_error(rec["redirect_uri"], "session_issue_failed")

    # Bundle everything the frontend needs to show "Connected to Epic — Dr. X".
    handoff = {
        "token": token,
        "expires_at": sess.exp,
        "clinician_id": sess.clinician_id,
        "name": sess.name,
        "role": sess.role,
        "hospital_id": sess.hospital_id,
        "ehr_vendor": vendor.id,
        "ehr_label": vendor.label,
        "ehr_color": vendor.color,
        "ehr_sandbox": vendor.sandbox,
        "fhir_base_url": vendor.fhir_base_url,
    }
    qp = urlencode({"handoff": json.dumps(handoff)})
    return RedirectResponse(f"{rec['redirect_uri']}?{qp}", status_code=302)


# ----------------------------------------------------------------------------------
# Mock authorize / token / FHIR endpoints — for demo when no vendor is provisioned
# ----------------------------------------------------------------------------------


@router.get("/mock-authorize")
def mock_authorize(
    response_type: str = Query("code"),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: str = Query(""),
    state: str = Query(...),
    aud: str = Query(""),
) -> RedirectResponse:
    """Stand-in for vendor authorize. No login screen — instant approve so the
    demo flow stays fast. In a real deployment this is the vendor's hosted
    OAuth login + consent screen."""
    code = f"mock-code-{secrets.token_hex(8)}"
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)


class MockTokenForm(BaseModel):
    grant_type: str
    code: str
    redirect_uri: str
    client_id: str


@router.post("/mock-token")
async def mock_token(request: Request) -> JSONResponse:
    """Stand-in for vendor token exchange. Returns a synthetic access_token
    plus a Practitioner identity scaffolded from the seeded clinician set so
    the demo flow returns a real-looking name + role."""
    form = await request.form()
    client_id = form.get("client_id", "")
    # Identify which vendor this was based on the client_id we registered.
    vendor_id = "epic"
    for v in ehr_vendors.VENDORS.values():
        if v.client_id == client_id:
            vendor_id = v.id
            break
    # Pick a demo clinician — first one we have on file for the hospital.
    seeded = _first_demo_clinician("demo")
    return JSONResponse(
        {
            "access_token": f"mock-{secrets.token_urlsafe(24)}",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": form.get("scope", ""),
            "fhirUser": f"Practitioner/{seeded.get('clinician_id', 'demo-clin-1')}",
            "practitioner": {
                "id": seeded.get("clinician_id", "demo-clin-1"),
                "name": seeded.get("name", f"EHR Clinician ({vendor_id})"),
                "role": seeded.get("role", "clinician"),
            },
            "patient": "",  # standalone launch — no patient context
        }
    )


@router.get("/mock-fhir/{vendor_id}/metadata")
def mock_fhir_metadata(vendor_id: str = Path(...)) -> dict:
    """Tiny FHIR conformance shim so a real FHIR client poking at our mock
    endpoint sees the right resourceType and supported interactions."""
    return {
        "resourceType": "CapabilityStatement",
        "fhirVersion": "4.0.1",
        "rest": [{
            "mode": "server",
            "resource": [
                {"type": "Patient", "interaction": [{"code": "read"}, {"code": "search-type"}]},
                {"type": "Encounter", "interaction": [{"code": "read"}, {"code": "search-type"}]},
                {"type": "Observation", "interaction": [{"code": "read"}, {"code": "search-type"}]},
            ],
        }],
        "_solace_vendor": vendor_id,
    }


# ----------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------


def _solace_callback_url() -> str:
    import os  # noqa: PLC0415
    base = os.environ.get("SOLACE_API_BASE_URL", "https://djfjrel7b1ebi.cloudfront.net").rstrip("/")
    return f"{base}/api/auth/ehr/callback"


def _redirect_with_error(redirect_uri: str, code: str) -> RedirectResponse:
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}error={code}", status_code=302)


def _first_demo_clinician(hospital_id: str) -> dict:
    """Pull a real seeded clinician for the mock Practitioner identity so the
    demo session looks legitimate (name + role match the hospital's roster)."""
    try:
        import boto3  # noqa: PLC0415
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415
        from lib.config import settings  # noqa: PLC0415

        tbl = boto3.resource("dynamodb", region_name=settings.aws_region).Table("solace-clinicians")
        resp = tbl.query(
            IndexName="hospital_name-index",
            KeyConditionExpression=Key("hospital_id").eq(hospital_id),
            Limit=1,
        )
        items = resp.get("Items", []) or []
        if items:
            it = items[0]
            return {
                "clinician_id": str(it.get("clinician_id", "demo-clin-1")),
                "name": str(it.get("name", "Dr. Demo")),
                "role": str(it.get("role", "clinician")),
            }
    except Exception as e:  # noqa: BLE001
        log.debug("demo clinician lookup fell back: %s", e)
    return {"clinician_id": "demo-clin-1", "name": "Dr. Demo", "role": "clinician"}


# Suppress unused import warning — storage might be needed for hospital validation later
_ = storage
