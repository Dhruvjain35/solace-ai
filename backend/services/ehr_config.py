"""Per-workspace EHR vendor-config service.

Binds a single **workspace** (a department / clinic / care-team inside a hospital)
to its own EHR: vendor, FHIR base URL, OAuth client_id, authorize/token endpoints,
the chosen SMART scope set, and — for confidential clients — the AWS Secrets Manager
*name* of the client secret or private-key PEM.

Why per-workspace (not per-process):
  Solace today resolves a single shipped-everywhere vendor binding from env vars
  (``lib.ehr_vendors``). For production / certification each tenant runs against its
  OWN registered Epic/Cerner/Athena app, so the binding must be data keyed by
  ``(hospital_id, workspace_id)`` — exactly the composite key the workspace itself
  uses, so a config row is structurally owned by the same tenant as its workspace.

Security posture:
  - Secrets NEVER stored in plaintext (COMP-007). The config row carries only the
    Secrets Manager *name* (``client_secret_ref`` / ``private_key_ref``). The value
    is dereferenced at token-exchange time via ``db.storage.resolve_secret_value``.
  - Isolation (SEC-008): every read/mutation is keyed by the owning ``hospital_id``;
    ``assert_owned`` is a defense-in-depth guard that collapses cross-tenant access
    to a uniform not-found so existence is never revealed across hospitals.
  - SEC-006: the config cannot widen the redirect allowlist — redirect URIs remain
    enforced in ``routers.ehr_auth`` against its module-level allowlist.

Layering (ARCH-001 / ARCH-002):
  - This service owns validation + the ownership guard. It reaches the datastore and
    Secrets Manager ONLY through ``db.storage`` — it never imports boto3.
  - The router imports this service and never touches DynamoDB directly.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from db import storage
from lib import ehr_vendors
from services import workspaces as workspace_service

log = logging.getLogger(__name__)


class EHRConfigError(Exception):
    """Base for EHR-config validation/lifecycle errors. Carries a stable ``code`` the
    router maps to an HTTP status without leaking internals to the client."""

    code = "ehr_config_error"


class InvalidEHRConfig(EHRConfigError):
    code = "invalid_ehr_config"


class EHRConfigNotFound(EHRConfigError):
    code = "ehr_config_not_found"


class CrossTenantEHRConfig(EHRConfigError):
    """A config does not belong to the asserting hospital_id. Uniform message so
    callers cannot distinguish 'exists elsewhere' from 'does not exist' (SEC-008)."""

    code = "ehr_config_not_found"


# Fields the caller may set/patch. Anything else is dropped — a caller can never
# overwrite the immutable key (hospital_id / workspace_id / created_at) or inject a
# raw secret value (only the *_ref name fields are accepted; see _SECRET_REF_FIELDS).
_MUTABLE_FIELDS = {
    "vendor",
    "fhir_base_url",
    "authorize_url",
    "token_url",
    "client_id",
    "scopes",
    "scopes_v2",
    "smart_version",
    "client_secret_ref",
    "private_key_ref",
    "kid",
    "label",
    "sandbox",
    "status",
}

# These name Secrets Manager entries — they are REFERENCES, never secret values
# (COMP-007). We additionally reject anything that looks like an inline secret.
_SECRET_REF_FIELDS = {"client_secret_ref", "private_key_ref"}

# Bare secret material a caller must never paste into a *_ref field.
_INLINE_SECRET_MARKERS = ("-----BEGIN", "PRIVATE KEY", "\n")

_VALID_SMART_VERSIONS = {"v1", "v2"}
_VALID_STATUS = {"active", "disabled"}
# A Secrets Manager name is path-like: letters, digits, and /_+=.@- (AWS allowed set).
_SECRET_REF_RE = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,512}$")


def _require_https(url: str, field: str) -> str:
    """Validate an endpoint URL is a well-formed absolute HTTPS URL.

    Plain-HTTP FHIR/OAuth endpoints are rejected (COMP-004 — no cleartext path to
    PHI), with a localhost exception for offline/mock testing only.
    """
    url = (url or "").strip()
    if not url:
        raise InvalidEHRConfig(f"{field} is required")
    parsed = urlparse(url)
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"):
        return url  # offline mock harness only
    if parsed.scheme != "https" or not parsed.netloc:
        raise InvalidEHRConfig(f"{field} must be an absolute https:// URL")
    return url


def _validate_secret_ref(value: str, field: str) -> str:
    """Ensure a ``*_ref`` field is a Secrets Manager NAME, not inline secret material."""
    value = (value or "").strip()
    if not value:
        return ""
    if any(marker in value for marker in _INLINE_SECRET_MARKERS):
        # Refuse to persist anything resembling a raw secret/PEM (COMP-007).
        raise InvalidEHRConfig(
            f"{field} must be an AWS Secrets Manager name, not an inline secret value"
        )
    if not _SECRET_REF_RE.match(value):
        raise InvalidEHRConfig(f"{field} is not a valid Secrets Manager name")
    return value


def _validate_scopes(raw: Any, field: str) -> list[str]:
    """Validate a scopes list: each token is a plain SMART scope string."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise InvalidEHRConfig(f"{field} must be a list of scope strings")
    out: list[str] = []
    for tok in raw:
        tok = str(tok).strip()
        if not tok or " " in tok or len(tok) > 128:
            raise InvalidEHRConfig(f"{field} contains an invalid scope token")
        out.append(tok)
    return out


def _normalize(hospital_id: str, workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize a create/update body into a storable record fragment.

    Only whitelisted fields survive. Secret-ref fields are checked to be names, not
    values. Endpoint URLs are forced HTTPS. Returns just the cleaned mutable fields
    (caller merges in the immutable key + timestamps).
    """
    patch: dict[str, Any] = {}
    for key in _MUTABLE_FIELDS:
        if key not in body or body[key] is None:
            continue
        val = body[key]
        if key == "vendor":
            vid = str(val).strip().lower()
            if not vid or not re.match(r"^[a-z0-9_-]{2,32}$", vid):
                raise InvalidEHRConfig("vendor must be a short alphanumeric id")
            patch["vendor"] = vid
        elif key in _SECRET_REF_FIELDS:
            ref = _validate_secret_ref(str(val), key)
            if ref:
                patch[key] = ref
        elif key in ("fhir_base_url", "authorize_url", "token_url"):
            patch[key] = _require_https(str(val), key)
        elif key in ("scopes", "scopes_v2"):
            scopes = _validate_scopes(val, key)
            if scopes:
                patch[key] = scopes
        elif key == "smart_version":
            sv = str(val).strip().lower()
            if sv not in _VALID_SMART_VERSIONS:
                raise InvalidEHRConfig(f"smart_version must be one of {sorted(_VALID_SMART_VERSIONS)}")
            patch[key] = sv
        elif key == "status":
            st = str(val).strip().lower()
            if st not in _VALID_STATUS:
                raise InvalidEHRConfig(f"status must be one of {sorted(_VALID_STATUS)}")
            patch[key] = st
        elif key == "sandbox":
            patch[key] = bool(val)
        elif key in ("client_id", "label", "kid"):
            patch[key] = str(val).strip()[:256]
    return patch


def assert_owned(record: dict[str, Any] | None, hospital_id: str) -> dict[str, Any]:
    """Return ``record`` iff it exists AND is owned by ``hospital_id``, else raise.

    Defense-in-depth twin of ``services.workspaces.assert_owned``: even though the
    storage key already scopes by hospital_id, every load re-asserts ownership so a
    future GSI/global lookup can never leak a row across tenants (SEC-008).
    """
    if not record or record.get("hospital_id") != hospital_id:
        raise CrossTenantEHRConfig("ehr config not found for this hospital")
    return record


def _public_view(record: dict[str, Any]) -> dict[str, Any]:
    """Project a stored config into the response shape.

    NON-SECRET by construction: secret-ref fields are surfaced ONLY as a boolean
    "is a confidential client" flag plus the reference NAME (safe — it is just a
    pointer), never the resolved value. No client secret or PEM ever appears here.
    """
    return {
        "hospital_id": record["hospital_id"],
        "workspace_id": record["workspace_id"],
        "vendor": record.get("vendor", ""),
        "fhir_base_url": record.get("fhir_base_url", ""),
        "authorize_url": record.get("authorize_url", ""),
        "token_url": record.get("token_url", ""),
        "client_id": record.get("client_id", ""),
        "scopes": record.get("scopes", []),
        "scopes_v2": record.get("scopes_v2", []),
        "smart_version": record.get("smart_version", "v2"),
        "label": record.get("label", ""),
        "sandbox": bool(record.get("sandbox", True)),
        "status": record.get("status", "active"),
        # Confidential-client posture WITHOUT exposing secret values.
        "confidential_client": bool(
            record.get("client_secret_ref") or record.get("private_key_ref")
        ),
        "client_secret_ref": record.get("client_secret_ref", ""),
        "private_key_ref": record.get("private_key_ref", ""),
        "kid": record.get("kid", ""),
        "created_at": record.get("created_at"),
        "created_by": record.get("created_by"),
        "updated_at": record.get("updated_at"),
    }


def _assert_workspace_exists(hospital_id: str, workspace_id: str) -> None:
    """A config can only bind to a workspace this hospital actually owns (SEC-008)."""
    # Raises WorkspaceNotFound/CrossTenant (mapped by the service to not-found) when
    # the workspace is absent or owned by another hospital.
    workspace_service.get_workspace(hospital_id, workspace_id)


def upsert_config(
    *,
    hospital_id: str,
    workspace_id: str,
    body: dict[str, Any],
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create or replace the EHR binding for one workspace. Returns the public view.

    ``vendor`` is required on first create. Endpoint URLs default from the static
    vendor template when omitted, so a workspace using a public sandbox need only
    name the vendor.
    """
    workspace_service.validate_workspace_id(workspace_id)
    _assert_workspace_exists(hospital_id, workspace_id)

    patch = _normalize(hospital_id, workspace_id, body)
    existing = storage.get_ehr_config(hospital_id, workspace_id)
    if existing is None and "vendor" not in patch:
        raise InvalidEHRConfig("vendor is required to create an EHR config")

    # Merge onto any existing record; fill endpoint defaults from the vendor template.
    merged: dict[str, Any] = dict(existing or {})
    merged.update(patch)
    vendor_id = merged.get("vendor", "")
    template = ehr_vendors.get(vendor_id)
    if template is not None:
        merged.setdefault("fhir_base_url", template.fhir_base_url)
        merged.setdefault("authorize_url", template.authorize_url)
        merged.setdefault("token_url", template.token_url)
        merged.setdefault("client_id", template.client_id)
    merged.setdefault("smart_version", "v2")
    merged.setdefault("status", "active")
    merged.setdefault("sandbox", template.sandbox if template else True)

    record = {
        **merged,
        "hospital_id": hospital_id,
        "workspace_id": workspace_id,
    }
    if existing is None:
        record["created_by"] = created_by
        record["created_at"] = storage._now_iso()
    else:
        record["created_at"] = existing.get("created_at", storage._now_iso())
        record["created_by"] = existing.get("created_by", created_by)
        record["updated_at"] = storage._now_iso()
    storage.put_ehr_config(record)
    log.info("upserted EHR config for workspace %s (hospital %s)", workspace_id, hospital_id)
    return _public_view(record)


def get_config(hospital_id: str, workspace_id: str) -> dict[str, Any]:
    """Fetch a workspace's EHR config (public view), asserting ownership. Raises on miss."""
    workspace_service.validate_workspace_id(workspace_id)
    record = assert_owned(storage.get_ehr_config(hospital_id, workspace_id), hospital_id)
    return _public_view(record)


def list_configs(hospital_id: str) -> list[dict[str, Any]]:
    """List every workspace EHR config owned by ``hospital_id`` (tenant-scoped query)."""
    return [_public_view(r) for r in storage.list_ehr_configs(hospital_id)]


def update_config(
    hospital_id: str, workspace_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Patch an existing config in place. Raises ``EHRConfigNotFound`` if absent."""
    workspace_service.validate_workspace_id(workspace_id)
    assert_owned(storage.get_ehr_config(hospital_id, workspace_id), hospital_id)
    patch = _normalize(hospital_id, workspace_id, updates)
    if not patch:
        raise EHRConfigError("no updatable fields provided")
    patch["updated_at"] = storage._now_iso()
    updated = storage.update_ehr_config(hospital_id, workspace_id, patch)
    if updated is None:
        raise EHRConfigNotFound("ehr config not found for this hospital")
    return _public_view(updated)


def delete_config(hospital_id: str, workspace_id: str) -> None:
    """Delete a workspace's EHR config. Raises ``EHRConfigNotFound`` if absent."""
    workspace_service.validate_workspace_id(workspace_id)
    assert_owned(storage.get_ehr_config(hospital_id, workspace_id), hospital_id)
    if not storage.delete_ehr_config(hospital_id, workspace_id):
        raise EHRConfigNotFound("ehr config not found for this hospital")


# ----------------------------------------------------------------------------------
# Resolution for the SMART flow — resolve the active workspace's vendor binding.
# ----------------------------------------------------------------------------------


def resolve_vendor(hospital_id: str, workspace_id: str | None) -> ehr_vendors.EHRVendor | None:
    """Resolve an :class:`EHRVendor` for the active (hospital, workspace), or None.

    Returns None when ``workspace_id`` is empty or no config exists / it is disabled,
    so callers fall back to the static, env-driven ``ehr_vendors.get(vendor)``. The
    returned vendor is pure non-secret routing metadata — confidential-client secrets
    stay in Secrets Manager and are resolved separately via :func:`resolve_secret`.
    """
    if not workspace_id:
        return None
    record = storage.get_ehr_config(hospital_id, workspace_id)
    if not record or record.get("hospital_id") != hospital_id:
        return None
    if record.get("status", "active") != "active":
        return None
    return ehr_vendors.from_workspace_config(record)


def resolve_secret(
    hospital_id: str, workspace_id: str, kind: str = "private_key"
) -> tuple[str | None, str | None]:
    """Resolve a confidential-client secret for this workspace from Secrets Manager.

    ``kind`` is ``"private_key"`` (RS384 private_key_jwt) or ``"client_secret"``.
    Returns ``(value, kid)`` where ``value`` is None when the workspace registered
    as a public client (no *_ref configured). The secret VALUE is fetched by NAME at
    call time and is NEVER persisted, returned to the frontend, or logged (COMP-007).
    """
    record = storage.get_ehr_config(hospital_id, workspace_id)
    if not record or record.get("hospital_id") != hospital_id:
        return None, None
    ref_field = "private_key_ref" if kind == "private_key" else "client_secret_ref"
    secret_name = record.get(ref_field, "")
    if not secret_name:
        return None, None
    value = storage.resolve_secret_value(secret_name)
    return value, record.get("kid") or None
