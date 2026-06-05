"""SMART-on-FHIR sign-in for clinicians.

Real OAuth flow against any SMART-on-FHIR-compliant EHR (Epic on FHIR, Oracle
Cerner, SMART Health IT public sandbox, Athenahealth). PKCE-protected per the
SMART spec for public clients (https://hl7.org/fhir/smart-app-launch/).

Flow (SMART App Launch v2):
  1. /launch?vendor=epic            → .well-known/smart-configuration discovery
                                    → 302 to authorize URL with PKCE challenge + nonce
     /launch?...&launch=<token>     → EHR-launch: the EHR opened us, `launch` param
                                      is threaded back to the authorize endpoint
  2. vendor handles user login + consent → 302 back to /callback?code=...&state=...
  3. /callback                      → POST token endpoint with PKCE verifier
                                      (private_key_jwt RS384 assertion for
                                       confidential clients)
                                    → validate id_token nonce (OIDC replay guard)
                                    → resolve launch context (patient/encounter)
                                    → GET FHIR Practitioner/{id} for clinician identity
                                    → mint Solace JWT
                                    → 302 to frontend with one-time handoff code
  4. /refresh                       → exchange a stored refresh_token for a fresh
                                      access_token without re-prompting the user

Security:
  - Redirect URI validated against allowlist (prevents open-redirect attacks)
  - OAuth state stored in DynamoDB (survives Lambda cold starts)
  - JWT never passed in URL — one-time handoff code exchanged via POST
  - PKCE S256 challenge/verifier — mandatory for ALL clients in SMART v2
  - OIDC nonce echoed into the id_token and validated on return
  - private_key_jwt (RS384) client authentication for confidential clients

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
from pydantic import BaseModel

from lib import ehr_vendors, jwt_auth, smart_auth

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


# Allowed redirect origins — prevents open-redirect attacks.
# Only frontend origins that are in the CORS allow-list are acceptable.
_ALLOWED_REDIRECT_ORIGINS = [
    "https://solaceaidemo.vercel.app",
    "https://solace-page.vercel.app",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]


def _validate_redirect_uri(uri: str) -> bool:
    """Ensure redirect_uri starts with one of our allowed origins."""
    return any(uri.startswith(origin) for origin in _ALLOWED_REDIRECT_ORIGINS)


# DynamoDB-backed state store for OAuth CSRF tokens + handoff codes.
# Survives Lambda cold starts and multi-container deployments.
# Falls back to in-memory dict in local dev mode.
_LAUNCH_STATES_LOCAL: dict[str, dict[str, Any]] = {}
_STATE_TTL = 600  # 10 minutes
_STATE_TABLE = "solace-oauth-states"


def _ddb_states_table():
    import boto3  # noqa: PLC0415
    from lib.config import settings  # noqa: PLC0415
    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(_STATE_TABLE)


def _store_state(state: str, data: dict[str, Any]) -> None:
    """Store OAuth state in DDB. Falls back to in-memory for local dev."""
    from lib.config import settings  # noqa: PLC0415

    data["state"] = state
    data["ttl"] = int(time.time()) + _STATE_TTL
    if settings.solace_mode == "aws":
        try:
            _ddb_states_table().put_item(Item=data)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("DDB state store failed, using in-memory: %s", e)
    _LAUNCH_STATES_LOCAL[state] = data


def _pop_state(state: str) -> dict[str, Any] | None:
    """Retrieve and delete OAuth state. Returns None if expired/missing."""
    from lib.config import settings  # noqa: PLC0415

    if settings.solace_mode == "aws":
        try:
            resp = _ddb_states_table().delete_item(
                Key={"state": state}, ReturnValues="ALL_OLD",
            )
            item = resp.get("Attributes")
            if item and item.get("ttl", 0) >= int(time.time()):
                return {k: v for k, v in item.items() if k != "state"}
            return None
        except Exception as e:  # noqa: BLE001
            log.warning("DDB state pop failed, trying in-memory: %s", e)
    return _LAUNCH_STATES_LOCAL.pop(state, None)


def _pkce_pair() -> tuple[str, str]:
    """Generate a SMART-spec compliant PKCE verifier + S256 challenge.

    Thin wrapper over ``smart_auth.generate_pkce`` — kept so existing callers
    don't change. PKCE is mandatory for every client in SMART App Launch v2.
    """
    return smart_auth.generate_pkce()


def _confidential_client_secret(vendor_id: str) -> str:
    """Return a configured RSA private-key PEM for a confidential client, if any.

    Solace registers as a *public* client by default (PKCE only). When an EHR
    requires confidential asymmetric auth, the operator provisions an RSA private
    key in env as ``SOLACE_<VENDOR>_PRIVATE_KEY`` (PEM text, newlines may be
    ``\\n``-escaped). Returns ``""`` when no key is set — the caller then falls
    back to public-client behavior.
    """
    import os  # noqa: PLC0415

    raw = os.environ.get(f"SOLACE_{vendor_id.upper()}_PRIVATE_KEY", "")
    return raw.replace("\\n", "\n").strip()


def _confidential_client_kid(vendor_id: str) -> str | None:
    """Optional JWK ``kid`` for the confidential-client signing key."""
    import os  # noqa: PLC0415

    return os.environ.get(f"SOLACE_{vendor_id.upper()}_KID") or None


def _resolve_smart_endpoints(
    vendor: ehr_vendors.EHRVendor,
) -> tuple[str, str, str, str]:
    """Resolve authorize/token URLs + jwks_uri/issuer, preferring live discovery.

    Fetches ``.well-known/smart-configuration`` from the vendor's FHIR base URL.
    On success the discovered endpoints win (they track tenant-specific routing);
    on any failure we fall back to the statically-registered vendor URLs so SMART
    v1 servers and offline mocks still work. Returns
    ``(authorize_url, token_url, jwks_uri, issuer)``; ``jwks_uri``/``issuer`` are
    empty strings when discovery is unavailable (the id_token verification then
    degrades to TLS-channel trust).
    """
    cfg = smart_auth.fetch_smart_configuration(vendor.fhir_base_url)
    if cfg and cfg.authorization_endpoint and cfg.token_endpoint:
        log.info("SMART discovery ok for %s", vendor.id)
        return cfg.authorization_endpoint, cfg.token_endpoint, cfg.jwks_uri, cfg.issuer
    return vendor.authorize_url, vendor.token_url, "", ""


@router.get("/launch")
def launch(
    vendor: str = Query(..., description="smart | epic | cerner | athena"),
    hospital_id: str = Query("demo"),
    redirect_uri: str = Query(..., description="Frontend URL to return to after success"),
    launch: str = Query(
        "",
        description=(
            "SMART EHR-launch token. Present when an EHR opens Solace from inside "
            "a patient chart; absent for a standalone (clinician-initiated) launch."
        ),
    ),
    iss: str = Query(
        "",
        description="FHIR base URL supplied by the EHR on an EHR-launch.",
    ),
) -> RedirectResponse:
    v = ehr_vendors.get(vendor)
    if not v:
        raise HTTPException(status_code=404, detail=f"Unknown EHR vendor '{vendor}'")

    # Validate redirect_uri against allowlist to prevent open redirects
    if not _validate_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=400,
            detail="redirect_uri is not an allowed origin",
        )

    if not v.client_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{v.label} client_id not configured. Set SOLACE_{v.id.upper()}_CLIENT_ID "
                "in Lambda env (and the matching authorize/token/FHIR URLs if not "
                "using the public sandbox)."
            ),
        )

    # On an EHR-launch the EHR tells us which FHIR server it is (`iss`). Trust it
    # only if it matches the vendor's configured base; otherwise keep the static
    # base — an attacker-supplied `iss` must not redirect token traffic.
    fhir_base = v.fhir_base_url
    is_ehr_launch = bool(launch)
    if is_ehr_launch and iss and iss.rstrip("/") == v.fhir_base_url.rstrip("/"):
        fhir_base = iss

    # SMART v2 discovery: prefer the live .well-known endpoints over static config.
    authorize_url, token_url, jwks_uri, issuer = _resolve_smart_endpoints(v)

    state = smart_auth.generate_state()
    nonce = smart_auth.generate_nonce()
    code_verifier, code_challenge = _pkce_pair()
    _store_state(state, {
        "vendor": v.id,
        "hospital_id": hospital_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "nonce": nonce,
        "token_url": token_url,
        "fhir_base_url": fhir_base,
        # Carry the discovered JWKS endpoint + issuer so the callback can verify
        # the id_token signature against the issuer's published keys.
        "jwks_uri": jwks_uri,
        "issuer": issuer,
        "client_id": v.client_id,
        "launch_type": "ehr" if is_ehr_launch else "standalone",
        "exp": int(time.time()) + _STATE_TTL,
    })

    params = {
        "response_type": "code",
        "client_id": v.client_id,
        "redirect_uri": _solace_callback_url(),
        "scope": " ".join(v.scopes),
        "state": state,
        "aud": fhir_base,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    # Thread the EHR-launch token straight through to the authorize endpoint so
    # the EHR can bind the existing patient/encounter context to this session.
    if is_ehr_launch:
        params["launch"] = launch
    return RedirectResponse(f"{authorize_url}?{urlencode(params)}", status_code=302)


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

    # Token endpoint: prefer the URL discovered at /launch, fall back to static.
    token_url = rec.get("token_url") or vendor.token_url
    fhir_base_url = rec.get("fhir_base_url") or vendor.fhir_base_url

    # Exchange the auth code for an access_token. PKCE verifier matches the
    # challenge the vendor stored at /launch — without it the vendor 400s.
    form: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _solace_callback_url(),
        "code_verifier": rec["code_verifier"],
    }
    try:
        _apply_client_auth(form, vendor, token_url)
    except smart_auth.PrivateKeyJwtError as e:
        log.warning("private_key_jwt build failed (%s): %s", vendor.id, e)
        return _redirect_with_error(rec["redirect_uri"], "client_auth_failed")

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                token_url,
                data=form,
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
        # SEC-002: never log the raw token payload — it can carry refresh_token /
        # id_token values the CloudWatch redaction filter does not catch. Log only
        # the non-sensitive key names so we can still diagnose a malformed response.
        log.warning(
            "EHR token response missing access_token (%s): keys=%s",
            vendor.id, sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        )
        return _redirect_with_error(rec["redirect_uri"], "token_exchange_failed")

    # OIDC id_token verification. SMART id_tokens are signed by the issuer; we
    # verify the RSA signature against the issuer's published JWKS (discovered at
    # /launch) AND validate the nonce / issuer / audience / expiry claims. When
    # the JWKS is unavailable or the key is EC (no offline EC math), we degrade to
    # the prior TLS-channel trust: still enforce the nonce, but skip the crypto.
    # Servers that issue no id_token (pure OAuth) are tolerated.
    id_token: str = payload.get("id_token", "")
    expected_nonce = rec.get("nonce", "")
    if id_token and expected_nonce:
        try:
            result = smart_auth.verify_id_token(
                id_token,
                jwks_uri=rec.get("jwks_uri", ""),
                expected_issuer=rec.get("issuer", ""),
                expected_audience=rec.get("client_id", ""),
                expected_nonce=expected_nonce,
            )
        except smart_auth.IdTokenVerificationError as e:
            # Signature/claim verification produced a definitive failure — reject.
            log.warning("EHR id_token verification failed for %s: %s", vendor.id, e)
            return _redirect_with_error(rec["redirect_uri"], "id_token_invalid")
        if result.verified:
            log.info("EHR id_token signature verified for %s", vendor.id)
        else:
            # Fallback path (no JWKS / EC key). verify_id_token already enforced
            # the nonce claim; this log records that we relied on TLS trust.
            log.info(
                "EHR id_token unverified (TLS-trust fallback) for %s: %s",
                vendor.id, result.reason,
            )

    # SMART launch context — patient / encounter the EHR bound to this session.
    launch_context = smart_auth.extract_launch_context(payload)

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
        fetched = _fetch_practitioner(fhir_base_url, access_token, fhir_user_ref)
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
        "fhir_base_url": fhir_base_url,
        "fhir_access_token": access_token,
    }

    try:
        token, sess = jwt_auth.issue_token(clinician)
    except Exception as e:  # noqa: BLE001
        log.exception("issue_token failed for EHR session: %s", e)
        return _redirect_with_error(rec["redirect_uri"], "session_issue_failed")

    # Instead of passing JWT in URL (visible in browser history, logs),
    # store the handoff payload behind a short-lived one-time code. The frontend
    # exchanges this code via POST /api/auth/ehr/exchange to get the real session.
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
        "fhir_base_url": fhir_base_url,
        # SMART launch context — present on an EHR-launch so the dashboard can
        # open straight onto the patient/encounter the EHR handed us.
        "launch_type": rec.get("launch_type", "standalone"),
        "launch_context": launch_context,
        "granted_scope": payload.get("scope", ""),
        "access_token_expires_in": int(payload.get("expires_in", 0) or 0),
    }
    handoff_code = secrets.token_urlsafe(32)
    handoff_state: dict[str, Any] = {
        "handoff": json.dumps(handoff),
        "exp": int(time.time()) + 120,  # 2-minute TTL
    }
    # Park the refresh_token (if the EHR issued one) behind the handoff record so
    # POST /refresh can mint fresh access tokens without re-prompting the user.
    # It is never placed in the URL or the frontend-visible handoff payload.
    refresh_token = payload.get("refresh_token", "")
    if refresh_token:
        handoff_state["refresh_token"] = refresh_token
        handoff_state["vendor"] = vendor.id
        handoff_state["token_url"] = token_url
    _store_state(f"handoff-{handoff_code}", handoff_state)
    qp = urlencode({"handoff_code": handoff_code})
    return RedirectResponse(f"{rec['redirect_uri']}?{qp}", status_code=302)


# ----------------------------------------------------------------------------------
# Token-endpoint client authentication
# ----------------------------------------------------------------------------------


def _apply_client_auth(
    form: dict[str, str], vendor: ehr_vendors.EHRVendor, token_url: str
) -> None:
    """Mutate ``form`` in place with the right token-endpoint client credentials.

    - Confidential client: when ``SOLACE_<VENDOR>_PRIVATE_KEY`` is set, attach an
      RS384 ``private_key_jwt`` client assertion (SMART asymmetric auth). The
      ``client_id`` is *not* sent as a form field — ``iss``/``sub`` in the
      assertion identify the client.
    - Public client (default): send ``client_id`` as a plain form field; PKCE is
      the only client proof, exactly as SMART v2 requires for public clients.

    Raises :class:`smart_auth.PrivateKeyJwtError` if a key is configured but
    cannot be used (e.g. an EC key, or malformed PEM).
    """
    private_key = _confidential_client_secret(vendor.id)
    if private_key:
        assertion = smart_auth.build_client_assertion(
            client_id=vendor.client_id,
            token_endpoint=token_url,
            private_key_pem=private_key,
            kid=_confidential_client_kid(vendor.id),
        )
        form["client_assertion_type"] = smart_auth.CLIENT_ASSERTION_TYPE
        form["client_assertion"] = assertion
    else:
        form["client_id"] = vendor.client_id


# ----------------------------------------------------------------------------------
# Handoff code exchange — frontend trades the one-time code for the real session
# ----------------------------------------------------------------------------------


class ExchangeBody(BaseModel):
    handoff_code: str


@router.post("/exchange")
def exchange_handoff(body: ExchangeBody) -> dict:
    """Exchange a one-time handoff code for the EHR session payload.

    The code is consumed atomically — replay attempts return 400.
    2-minute TTL ensures stale codes expire even without exchange.

    If the EHR issued a refresh_token, it is *not* returned to the frontend.
    Instead it is re-parked under a longer-lived ``refresh-<code>`` record and a
    ``refresh_handle`` is handed back so the frontend can later call
    POST /refresh without ever seeing the raw refresh_token.
    """
    rec = _pop_state(f"handoff-{body.handoff_code}")
    if not rec:
        raise HTTPException(status_code=400, detail="invalid or expired handoff code")
    try:
        payload = json.loads(rec["handoff"])
    except (KeyError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail="malformed handoff") from e

    refresh_token = rec.get("refresh_token", "")
    if refresh_token:
        refresh_handle = secrets.token_urlsafe(32)
        _store_state(f"refresh-{refresh_handle}", {
            "refresh_token": refresh_token,
            "vendor": rec.get("vendor", ""),
            "token_url": rec.get("token_url", ""),
            "exp": int(time.time()) + _STATE_TTL,
        })
        payload["refresh_handle"] = refresh_handle
    return payload


# ----------------------------------------------------------------------------------
# Token refresh — trade a stored refresh_token for a fresh access_token
# ----------------------------------------------------------------------------------


class RefreshBody(BaseModel):
    refresh_handle: str


@router.post("/refresh")
def refresh_token(body: RefreshBody) -> dict:
    """Mint a fresh FHIR access_token from a stored SMART refresh_token.

    The frontend never holds the raw refresh_token — it holds an opaque
    ``refresh_handle`` (issued by /exchange) that points at a server-side record.
    This endpoint runs the OAuth ``refresh_token`` grant against the vendor's
    token endpoint, re-parks any rotated refresh_token under a *new* handle, and
    returns the new access_token plus its lifetime.

    Replay-safe: the old handle is consumed atomically, so a leaked handle can be
    used at most once.
    """
    rec = _pop_state(f"refresh-{body.refresh_handle}")
    if not rec or not rec.get("refresh_token"):
        raise HTTPException(status_code=400, detail="invalid or expired refresh handle")

    vendor = ehr_vendors.get(rec.get("vendor", ""))
    if not vendor:
        raise HTTPException(status_code=400, detail="vendor missing on refresh record")
    token_url = rec.get("token_url") or vendor.token_url

    form: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": rec["refresh_token"],
        "scope": " ".join(vendor.scopes),
    }
    try:
        _apply_client_auth(form, vendor, token_url)
    except smart_auth.PrivateKeyJwtError as e:
        log.warning("private_key_jwt build failed on refresh (%s): %s", vendor.id, e)
        raise HTTPException(status_code=500, detail="client authentication failed") from e

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                token_url, data=form, headers={"Accept": "application/json"},
            )
        if resp.status_code >= 400:
            log.warning(
                "EHR token refresh %s -> %d body=%s",
                vendor.id, resp.status_code, resp.text[:300],
            )
            raise HTTPException(status_code=502, detail="EHR token refresh rejected")
        payload = resp.json()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("EHR token refresh failed (%s): %s", vendor.id, e)
        raise HTTPException(status_code=502, detail="EHR token refresh failed") from e

    access_token = payload.get("access_token", "")
    if not access_token:
        raise HTTPException(status_code=502, detail="EHR refresh response missing access_token")

    out: dict[str, Any] = {
        "access_token": access_token,
        "expires_in": int(payload.get("expires_in", 0) or 0),
        "granted_scope": payload.get("scope", ""),
        "fhir_base_url": vendor.fhir_base_url,
    }
    # The EHR may rotate the refresh_token. Re-park whichever token is current
    # under a fresh handle so the next refresh keeps working.
    new_refresh = payload.get("refresh_token") or rec["refresh_token"]
    new_handle = secrets.token_urlsafe(32)
    _store_state(f"refresh-{new_handle}", {
        "refresh_token": new_refresh,
        "vendor": vendor.id,
        "token_url": token_url,
        "exp": int(time.time()) + _STATE_TTL,
    })
    out["refresh_handle"] = new_handle
    return out


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
