"""Workspace service — multi-tenant sub-scope lifecycle within a hospital.

A **Workspace** is a sub-tenant scope WITHIN a hospital (e.g. a department, clinic,
or care team). The hospital (``hospital_id``) is the top-level tenant boundary — the
organization that adopted Solace. A workspace is a child scope owned by exactly one
hospital. This lets a single hospital partition its clinicians, patients lists, and
config across teams without standing up a separate tenant.

Layering (ARCH-001 / ARCH-002):
  - This service owns validation, ``workspace_id`` generation, and the cross-tenant
    ownership guard.
  - It reaches the datastore ONLY through ``db.storage`` — it never imports boto3.
  - The router imports this service and never touches DynamoDB directly.

Isolation (SEC-008 / COMP-011): every read/mutation is keyed by the owning
``hospital_id``. ``assert_owned`` is a defense-in-depth guard mirroring
``lib.tenant.assert_patient_in_hospital`` — it raises a uniform error so a caller
authenticated to hospital A can never observe (or even confirm the existence of) a
workspace owned by hospital B.
"""
from __future__ import annotations

import logging
import re
import secrets
from typing import Any

from db import storage

log = logging.getLogger(__name__)

# A workspace_id is URL-safe, lower-case, hyphen-separated. Bounds keep it usable in
# paths and DynamoDB sort keys, and the strict pattern means caller input is never
# interpolated raw into any key (SEC-009 is enforced at the db layer via Key(), but
# validating here fails bad input fast with a clear 400 instead of a malformed query).
_ID_MIN_LEN = 3
_ID_MAX_LEN = 48
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$")

# Reserved ids that collide with fixed sub-paths or sentinel values.
_RESERVED_IDS = {"all", "none", "default", "_", "api", "admin", "new"}


class WorkspaceError(Exception):
    """Base for workspace validation/lifecycle errors. Carries a stable ``code`` the
    router maps to an HTTP status without leaking internals to the client."""

    code = "workspace_error"


class InvalidWorkspaceId(WorkspaceError):
    code = "invalid_workspace_id"


class WorkspaceNotFound(WorkspaceError):
    code = "workspace_not_found"


class WorkspaceExists(WorkspaceError):
    code = "workspace_exists"


class CrossTenantWorkspace(WorkspaceError):
    """A workspace does not belong to the asserting hospital_id. Uniform message so
    callers cannot distinguish 'exists elsewhere' from 'does not exist' (SEC-008)."""

    code = "workspace_not_found"


def _slugify(text: str) -> str:
    """Lower-case, ASCII, hyphen-separated; collapse separators; trim hyphens."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:_ID_MAX_LEN].strip("-")


def validate_workspace_id(workspace_id: str) -> str:
    """Return the id unchanged if it is a well-formed, non-reserved workspace_id.

    Raises ``InvalidWorkspaceId`` otherwise. This is the single chokepoint every
    caller-supplied id passes through before it reaches the datastore.
    """
    wid = (workspace_id or "").strip()
    if not (_ID_MIN_LEN <= len(wid) <= _ID_MAX_LEN):
        raise InvalidWorkspaceId(
            f"workspace_id must be {_ID_MIN_LEN}-{_ID_MAX_LEN} characters"
        )
    if wid in _RESERVED_IDS:
        raise InvalidWorkspaceId(f"'{wid}' is reserved and cannot be used")
    if not _ID_PATTERN.match(wid):
        raise InvalidWorkspaceId(
            "workspace_id must be lower-case letters, digits, and hyphens "
            "(not starting or ending with a hyphen)"
        )
    return wid


def generate_workspace_id(hospital_id: str, name: str) -> str:
    """Derive a unique workspace_id for this hospital from a human name.

    Uniqueness is scoped to the hospital (the partition), so two different hospitals
    may each have a 'pediatrics' workspace without colliding. Falls back to a random
    suffix when the base name (or short retries) are already taken.
    """
    base = _slugify(name)
    if len(base) < _ID_MIN_LEN or base in _RESERVED_IDS:
        # Name slugified to something unusable — start from a random handle.
        base = f"ws-{secrets.token_hex(3)}"
    candidate = base
    for _ in range(8):
        if candidate not in _RESERVED_IDS and storage.get_workspace(hospital_id, candidate) is None:
            return candidate
        suffix = secrets.token_hex(2)  # 4 hex chars
        trimmed = base[: _ID_MAX_LEN - 5].rstrip("-")
        candidate = f"{trimmed}-{suffix}"
    raise WorkspaceExists("could not allocate a unique workspace_id — try another name")


def assert_owned(workspace: dict[str, Any] | None, hospital_id: str) -> dict[str, Any]:
    """Return ``workspace`` iff it exists AND is owned by ``hospital_id``, else raise.

    Defense-in-depth twin of ``lib.tenant.assert_patient_in_hospital``: even though
    the storage key already scopes by hospital_id, every code path that loads a
    workspace re-asserts ownership so a future GSI/global lookup can never leak a row
    across tenants. The error message is uniform (CrossTenantWorkspace.code maps to
    a 404) so existence is not revealed across hospitals.
    """
    if not workspace or workspace.get("hospital_id") != hospital_id:
        raise CrossTenantWorkspace("workspace not found for this hospital")
    return workspace


def _public_view(record: dict[str, Any]) -> dict[str, Any]:
    """Project a stored workspace into the response shape. NON-PHI by construction —
    a workspace holds only tenant config (name, status), never patient data."""
    return {
        "workspace_id": record["workspace_id"],
        "hospital_id": record["hospital_id"],
        "name": record.get("name", ""),
        "description": record.get("description", ""),
        "status": record.get("status", "active"),
        "created_at": record.get("created_at"),
        "created_by": record.get("created_by"),
        "updated_at": record.get("updated_at"),
    }


def create_workspace(
    *,
    hospital_id: str,
    name: str,
    description: str = "",
    created_by: str | None = None,
    requested_id: str | None = None,
) -> dict[str, Any]:
    """Create a workspace owned by ``hospital_id``. Returns the public view.

    If ``requested_id`` is given it is validated and must be free within the
    hospital; otherwise an id is generated from ``name``.
    """
    if not name or not name.strip():
        raise WorkspaceError("workspace name is required")

    if requested_id:
        workspace_id = validate_workspace_id(requested_id)
        if storage.get_workspace(hospital_id, workspace_id) is not None:
            raise WorkspaceExists(f"workspace '{workspace_id}' already exists")
    else:
        workspace_id = generate_workspace_id(hospital_id, name)

    record = {
        "hospital_id": hospital_id,
        "workspace_id": workspace_id,
        "name": name.strip(),
        "description": (description or "").strip(),
        "status": "active",
        "created_by": created_by,
        "created_at": storage._now_iso(),
    }
    storage.put_workspace(record)
    log.info("created workspace %s for hospital %s", workspace_id, hospital_id)
    return _public_view(record)


def get_workspace(hospital_id: str, workspace_id: str) -> dict[str, Any]:
    """Fetch a single workspace, asserting hospital ownership. Raises on miss."""
    validate_workspace_id(workspace_id)
    record = assert_owned(storage.get_workspace(hospital_id, workspace_id), hospital_id)
    return _public_view(record)


def list_workspaces(hospital_id: str) -> list[dict[str, Any]]:
    """List every workspace owned by ``hospital_id`` (tenant-scoped query)."""
    return [_public_view(r) for r in storage.list_workspaces(hospital_id)]


_MUTABLE_FIELDS = {"name", "description", "status"}
_VALID_STATUS = {"active", "archived"}


def update_workspace(
    hospital_id: str, workspace_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Patch ``name`` / ``description`` / ``status`` on an owned workspace.

    Validates the id and ownership first, then applies only whitelisted fields so a
    caller can never overwrite the immutable key (hospital_id / workspace_id /
    created_at). Raises ``WorkspaceNotFound`` if the workspace is absent.
    """
    validate_workspace_id(workspace_id)
    assert_owned(storage.get_workspace(hospital_id, workspace_id), hospital_id)

    patch = {k: v for k, v in updates.items() if k in _MUTABLE_FIELDS and v is not None}
    if "status" in patch and patch["status"] not in _VALID_STATUS:
        raise WorkspaceError(f"status must be one of {sorted(_VALID_STATUS)}")
    if not patch:
        raise WorkspaceError("no updatable fields provided")
    patch["updated_at"] = storage._now_iso()

    updated = storage.update_workspace(hospital_id, workspace_id, patch)
    if updated is None:
        raise WorkspaceNotFound("workspace not found for this hospital")
    return _public_view(updated)


def delete_workspace(hospital_id: str, workspace_id: str) -> None:
    """Delete an owned workspace. Raises ``WorkspaceNotFound`` if absent."""
    validate_workspace_id(workspace_id)
    assert_owned(storage.get_workspace(hospital_id, workspace_id), hospital_id)
    if not storage.delete_workspace(hospital_id, workspace_id):
        raise WorkspaceNotFound("workspace not found for this hospital")
