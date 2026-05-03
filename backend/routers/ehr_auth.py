"""SMART-on-FHIR sign-in for clinicians.

Real OAuth flow against any SMART-on-FHIR-compliant EHR (Epic on FHIR, Oracle
Cerner, SMART Health IT public sandbox, Athenahealth). PKCE-protected per the
SMART spec for public clients (https://hl7.org/fhir/smart-app-launch/).

Flow:
  1. /launch?vendor=epic            → 302 to vendor authorize URL with PKCE challenge
  2. vendor handles user login + consent → 302 back to /callback?code=...&state=...
  3. /callback                      → POST token endpoint with PKCE verifier
                                    → GET FHIR Practitioner/{id} for clinician identity
                                    → mint Solace JWT
                                    → 302 to frontend with handoff payload

The Solace JWT issued at the end embeds the vendor + FHIR base URL + access_token
so every downstream EHR query knows where to talk and how to authenticate.

The mock-* endpoints are kept for offline / airplane testing — set vendor=mock or
override SOLACE_*_AUTHORIZE_URL to point at them. Defaults are real now.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

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
# Launch — clinician clicks "Sign in with Epic" → 302 to the vendor authorize URL
# ----------------------------------------------------------------------------------


# PKCE state — DDB-backed so a Lambda cold start mid-OAuth-roundtrip doesn't
# drop the verifier. Falls back to an in-memory dict in local mode.
_LAUNCH_STATES_LOCAL: dict[str, dict[str, Any]] = {}
_STATE_TTL = 600  # 10 minutes
_STATE_TABLE = "solace-oauth-states"


def _ddb_states_table():
    import boto3  # noqa: PLC0415
    from lib.config import settings  # noqa: PLC0415
    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(_STATE_TABLE)


def _put_state(state: str, data: dict[str, Any]) -> None:
    from lib.config import settings  # noqa: PLC0415
    if settings.solace_mode != "aws":
        _LAUNCH_STATES_LOCAL[state] = data
        return
    try:
        _ddb_states_table().put_item(Item={"state": state, **data})
    except Exception as e:  # noqa: BLE001
        log.warning("oauth state DDB put failed, falling back to in-memory: %s", e)
        _LAUNCH_STATES_LOCAL[state] = data


def _pop_state(state: str) -> dict[str, Any] | None:
    from lib.config import settings  # noqa: PLC0415
    if settings.solace_mode != "aws":
        return _LAUNCH_STATES_LOCAL.pop(state, None)
    # Try DDB first; fall back to in-memory if the table is empty (race or fallback).
    try:
        resp = _ddb_states_table().delete_item(
            Key={"state": state}, ReturnValues="ALL_OLD",
        )
        item = resp.get("Attributes")
        if item:
            return {k: v for k, v in item.items() if k != "state"}
    except Exception as e:  # noqa: BLE001
        log.warning("oauth state DDB pop failed: %s", e)
    return _LAUNCH_STATES_LOCAL.pop(state, None)


def _pkce_pair() -> tuple[str, str]:
    """Generate a SMART-spec compliant PKCE verifier + S256 challenge.

    Verifier: 43-128 chars from [A-Z, a-z, 0-9, -._~]. We use 64 random bytes
    base64url-encoded, no padding — yields 86 url-safe chars.
    Challenge: base64url(sha256(verifier)).
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


@router.get("/launch")
def launch(
    vendor: str = Query(..., description="smart | epic | cerner | athena"),
    hospital_id: str = Query("demo"),
    redirect_uri: str = Query(..., description="Frontend URL to return to after success"),
) -> RedirectResponse:
    v = ehr_vendors.get(vendor)
    if not v:
        raise HTTPException(status_code=404, detail=f"Unknown EHR vendor '{vendor}'")
    if not v.client_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{v.label} client_id not configured. Set SOLACE_{v.id.upper()}_CLIENT_ID "
                "in Lambda env (and the matching authorize/token/FHIR URLs if not "
                "using the public sandbox)."
            ),
        )
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = _pkce_pair()
    _put_state(state, {
        "vendor": v.id,
        "hospital_id": hospital_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "exp": int(time.time()) + _STATE_TTL,
        "ttl": int(time.time()) + _STATE_TTL,  # DDB TTL field
    })

    params = {
        "response_type": "code",
        "client_id": v.client_id,
        "redirect_uri": _solace_callback_url(),
        "scope": " ".join(v.scopes),
        "state": state,
        "aud": v.fhir_base_url,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
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
    rec = _pop_state(state)
    if not rec or int(rec.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=400, detail="invalid or expired state")
    vendor = ehr_vendors.get(rec["vendor"])
    if not vendor:
        raise HTTPException(status_code=400, detail="vendor missing on stored state")

    # Exchange the auth code for an access_token. PKCE verifier matches the
    # challenge the vendor stored at /launch — without it the vendor 400s.
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                vendor.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _solace_callback_url(),
                    "client_id": vendor.client_id,
                    "code_verifier": rec["code_verifier"],
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                log.warning(
                    "EHR token exchange %s -> %d body=%s",
                    vendor.id, resp.status_code, resp.text[:300],
                )
                return _redirect_with_error(rec["redirect_uri"], "token_exchange_failed")
            payload = resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("EHR token exchange failed (%s): %s", vendor.id, e)
        return _redirect_with_error(rec["redirect_uri"], "token_exchange_failed")

    access_token: str = payload.get("access_token", "")
    if not access_token:
        log.warning("EHR token response missing access_token: %s", payload)
        return _redirect_with_error(rec["redirect_uri"], "token_exchange_failed")

    # Resolve the clinician's identity. Three sources, in order:
    #   1. `practitioner` field in the token response (mock returns this directly)
    #   2. `id_token` JWT — SMART servers include `fhirUser` claim there
    #   3. `fhirUser` field on the token response (raw URL pointing at Practitioner/{id})
    practitioner = (
        _practitioner_from_token_response(payload)
        or _practitioner_from_id_token(payload.get("id_token", ""))
        or {}
    )
    fhir_user_ref = (
        payload.get("fhirUser")
        or practitioner.get("fhir_user_ref")
        or ""
    )

    # If we have only a reference, fetch the full Practitioner resource so we
    # can show the clinician's real name + role on the dashboard.
    if (not practitioner.get("name")) and fhir_user_ref:
        fetched = _fetch_practitioner(vendor.fhir_base_url, access_token, fhir_user_ref)
        if fetched:
            practitioner = {**practitioner, **fetched}

    fhir_user_id = (
        practitioner.get("id")
        or fhir_user_ref.rsplit("/", 1)[-1] if fhir_user_ref else ""
    ) or "unknown"
    name = practitioner.get("name") or _name_from_id_token(payload.get("id_token", "")) or "EHR Clinician"
    role = practitioner.get("role", "clinician")
    hospital_id = rec["hospital_id"]

    clinician = {
        "clinician_id": f"ehr-{vendor.id}-{fhir_user_id}",
        "name": str(name),
        "role": role,
        "hospital_id": hospital_id,
        "ehr_vendor": vendor.id,
        "fhir_base_url": vendor.fhir_base_url,
        "fhir_access_token": access_token,
    }

    try:
        token, sess = jwt_auth.issue_token(clinician)
    except Exception as e:  # noqa: BLE001
        log.exception("issue_token failed for EHR session: %s", e)
        return _redirect_with_error(rec["redirect_uri"], "session_issue_failed")

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
# FHIR Practitioner resolution helpers
# ----------------------------------------------------------------------------------


def _practitioner_from_token_response(payload: dict) -> dict:
    """The mock token endpoint and some sandboxes embed Practitioner inline."""
    p = payload.get("practitioner")
    if isinstance(p, dict) and (p.get("name") or p.get("id")):
        return {
            "id": str(p.get("id", "")),
            "name": str(p.get("name", "")),
            "role": str(p.get("role", "clinician")),
        }
    return {}


def _practitioner_from_id_token(id_token: str) -> dict:
    """Extract Practitioner reference + name from the OIDC id_token claims.

    SMART id_tokens include `fhirUser` (a relative URL to the Practitioner/Patient
    resource) and standard OIDC `name` / `preferred_username`.
    """
    if not id_token or id_token.count(".") != 2:
        return {}
    try:
        body_b64 = id_token.split(".")[1]
        # JWT base64 segments aren't padded — pad before decoding.
        body_b64 += "=" * (-len(body_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(body_b64).decode())
    except Exception:  # noqa: BLE001
        return {}
    fhir_user = claims.get("fhirUser") or claims.get("fhiruser") or ""
    name = claims.get("name") or claims.get("preferred_username") or ""
    return {
        "id": fhir_user.rsplit("/", 1)[-1] if fhir_user else "",
        "name": name,
        "fhir_user_ref": fhir_user,
        "role": claims.get("role", "clinician"),
    }


def _name_from_id_token(id_token: str) -> str:
    return _practitioner_from_id_token(id_token).get("name", "")


def _fetch_practitioner(fhir_base_url: str, access_token: str, fhir_user_ref: str) -> dict | None:
    """GET FHIR Practitioner/{id} and pull a display name + role.

    `fhir_user_ref` may be:
      - a relative URL: "Practitioner/abc123"
      - an absolute URL: "https://fhir.example.com/.../Practitioner/abc123"
      - just an id: "abc123" (legacy / mock)
    """
    if not fhir_user_ref or not access_token or not fhir_base_url:
        return None
    if fhir_user_ref.startswith("http"):
        url = fhir_user_ref
    else:
        ref = fhir_user_ref if "/" in fhir_user_ref else f"Practitioner/{fhir_user_ref}"
        url = fhir_base_url.rstrip("/") + "/" + ref.lstrip("/")
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/fhir+json",
                },
            )
            if resp.status_code != 200:
                log.info("Practitioner fetch %s -> %d", url, resp.status_code)
                return None
            res = resp.json()
    except Exception as e:  # noqa: BLE001
        log.info("Practitioner fetch error: %s", e)
        return None

    return {
        "id": str(res.get("id", "")),
        "name": _format_practitioner_name(res),
        "role": _format_practitioner_role(res),
    }


def _format_practitioner_name(res: dict) -> str:
    """FHIR HumanName picker — prefer official, fall back to first usable entry."""
    names = res.get("name") or []
    if not isinstance(names, list) or not names:
        return ""
    for n in names:
        if (n.get("use") or "").lower() == "official":
            return _hn_to_string(n)
    return _hn_to_string(names[0])


def _hn_to_string(n: dict) -> str:
    if not isinstance(n, dict):
        return ""
    if n.get("text"):
        return str(n["text"])
    given = " ".join(n.get("given") or [])
    family = n.get("family") or ""
    prefix = " ".join(n.get("prefix") or [])
    parts = [p for p in (prefix, given, family) if p]
    return " ".join(parts).strip()


def _format_practitioner_role(res: dict) -> str:
    """FHIR Practitioner.qualification[0].code.text or fall back to 'clinician'."""
    qual = res.get("qualification") or []
    if isinstance(qual, list) and qual:
        code = (qual[0].get("code") or {})
        text = code.get("text") or ""
        if text:
            return text
        coding = code.get("coding") or []
        if isinstance(coding, list) and coding:
            return coding[0].get("display") or coding[0].get("code") or "clinician"
    return "clinician"


# ----------------------------------------------------------------------------------
# Mock authorize / token / FHIR endpoints — kept for offline / airplane testing.
# Real flow is the default now; these only fire if vendor.authorize_url is overridden
# to point at them (e.g. SOLACE_SMART_AUTHORIZE_URL=…/api/auth/ehr/mock-authorize).
# ----------------------------------------------------------------------------------


@router.get("/mock-authorize")
def mock_authorize(
    response_type: str = Query("code"),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: str = Query(""),
    state: str = Query(...),
    aud: str = Query(""),
    code_challenge: str = Query(""),
    code_challenge_method: str = Query(""),
) -> RedirectResponse:
    """Stand-in for vendor authorize. Instant approve so a fully-offline demo
    works. PKCE challenge is accepted but not validated — the matching mock-token
    endpoint also skips PKCE."""
    code = f"mock-code-{secrets.token_hex(8)}"
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)


@router.post("/mock-token")
async def mock_token(request: Request) -> JSONResponse:
    """Synthetic token + Practitioner identity for offline demos."""
    form = await request.form()
    client_id = form.get("client_id", "")
    vendor_id = "smart"
    for v in ehr_vendors.VENDORS.values():
        if v.client_id == client_id:
            vendor_id = v.id
            break
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
            "patient": "",
        }
    )


@router.get("/mock-fhir/{vendor_id}/metadata")
def mock_fhir_metadata(vendor_id: str = Path(...)) -> dict:
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
