"""EHR vendor registry — real SMART-on-FHIR endpoints.

Each entry mirrors the SMART-on-FHIR launch.json that the vendor publishes —
this is exactly the metadata Solace needs to integrate with real Epic / Cerner /
Athena environments.

Defaults point at the real public sandboxes:
  - epic   → https://fhir.epic.com (requires a registered client_id, free at
             https://fhir.epic.com/Developer/Apps — 30-min self-service)
  - cerner → https://fhir-ehr-code.cerner.com (requires a registered client_id
             at https://code.cerner.com)
  - smart  → https://launch.smarthealthit.org (works with ANY client_id —
             Boston Children's-hosted public sandbox, no registration; this is
             the default for demos and integration testing)
  - athena → https://api.preview.platform.athenahealth.com (requires a
             registered client_id at https://developer.athenahealth.com)

Override any field per vendor via env var, e.g. SOLACE_EPIC_CLIENT_ID,
SOLACE_EPIC_AUTHORIZE_URL, SOLACE_EPIC_FHIR_URL — ship the same code base
to demo + production.

The display fields (label, color, sandbox flag) are read by the frontend login
screen so each vendor button looks distinct without a hardcoded asset.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EHRVendor:
    id: str
    label: str          # Display name on the button
    color: str          # Hex used for the button accent
    fhir_base_url: str  # Where to issue FHIR queries after auth
    authorize_url: str  # OAuth2 authorize endpoint (vendor-hosted)
    token_url: str      # OAuth2 token exchange endpoint
    client_id: str      # Solace's registered client_id with this vendor
    scopes: tuple[str, ...]              # SMART v1 (`.read`) — the fallback spelling
    sandbox: bool       # True = demo / sandbox / non-PHI environment
    pkce_required: bool = True  # SMART-on-FHIR public clients MUST use PKCE
    # SMART v2 (`.cruds`) spelling of the same minimum-necessary set. Empty tuple
    # means "use v1" — callers should prefer v2 when present, fall back to v1.
    scopes_v2: tuple[str, ...] = ()

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "color": self.color,
            "sandbox": self.sandbox,
        }

    def scope_string(self, *, smart_version: str = "v2") -> str:
        """Space-delimited scope string for the requested SMART version.

        ``smart_version="v2"`` returns the granular ``resource.cruds`` spelling
        when the vendor defines one, else transparently falls back to v1. Any
        other value (``"v1"``) forces the legacy ``.read`` spelling — used as the
        retry when a tenant's authorize endpoint rejects v2 scopes.
        """
        if smart_version == "v2" and self.scopes_v2:
            return " ".join(self.scopes_v2)
        return " ".join(self.scopes)


# SMART-on-FHIR scope set per https://hl7.org/fhir/smart-app-launch/scopes-and-launch-context.html
# `launch/patient` lets the EHR pass us a patient context on launch (when applicable).
# `online_access` requests a refresh token so we don't have to re-prompt every 30 min.
#
# Identity / launch scopes are spelled identically in SMART v1 and v2 — only the
# resource scopes differ (`.read` in v1 vs the `.cruds` permission string in v2).
_IDENTITY_SCOPES: tuple[str, ...] = (
    "openid",
    "fhirUser",
    "launch",
    "online_access",
    "profile",
)

# Minimum-necessary FHIR resource set Solace reads to power triage / the copilot.
# All read+search (HIPAA §164.502(b) minimum-necessary): we never request write/
# create/delete here, so the v2 permission string is "rs" (read + search).
_READ_RESOURCES: tuple[str, ...] = (
    "Patient",
    "Practitioner",
    "Encounter",
    "Observation",
    "MedicationRequest",
    "AllergyIntolerance",
    "Condition",
)

# SMART v1 resource scopes — Epic and some Cerner tenants still only understand
# the `.read` spelling. Kept as the safe fallback when a tenant rejects v2.
_DEFAULT_SCOPES: tuple[str, ...] = _IDENTITY_SCOPES + tuple(
    f"user/{r}.read" for r in _READ_RESOURCES
)

# SMART v2 resource scopes — the granular `resource.cruds` grammar
# (https://hl7.org/fhir/smart-app-launch/scopes-and-launch-context.html#scopes-for-requesting-fhir-resources).
# `.rs` = read + search only, the minimum-necessary set for read-oriented triage.
# Per the marketplace gap analysis, vendors that have moved to SMART v2 (current
# Epic, Oracle Health) reject the v1 `.read` spelling at the authorize endpoint,
# so we must request the v2 form first and fall back to v1 only when needed.
_DEFAULT_SCOPES_V2: tuple[str, ...] = _IDENTITY_SCOPES + tuple(
    f"user/{r}.rs" for r in _READ_RESOURCES
)


# Real public sandbox endpoints. Use _env to allow per-vendor production overrides.
def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# Epic on FHIR — public R4 sandbox. Apps register at https://fhir.epic.com/Developer/Apps
_EPIC_AUTH = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"
_EPIC_TOKEN = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
_EPIC_FHIR = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/"

# Oracle Cerner / HealtheLife — public sandbox tenant
_CERNER_TENANT = "ec2458f2-1e24-41c8-b71b-0e701af7583d"
_CERNER_AUTH = (
    f"https://authorization.cerner.com/tenants/{_CERNER_TENANT}/protocols/oauth2/profiles/smart-v1/"
    "personas/provider/authorize"
)
_CERNER_TOKEN = (
    f"https://authorization.cerner.com/tenants/{_CERNER_TENANT}/protocols/oauth2/profiles/smart-v1/token"
)
_CERNER_FHIR = f"https://fhir-ehr-code.cerner.com/r4/{_CERNER_TENANT}/"

# SMART Health IT — Boston Children's reference implementation. Accepts any
# client_id, no registration needed. Best demo / integration target.
_SMART_AUTH = "https://launch.smarthealthit.org/v/r4/auth/authorize"
_SMART_TOKEN = "https://launch.smarthealthit.org/v/r4/auth/token"
_SMART_FHIR = "https://launch.smarthealthit.org/v/r4/fhir"


VENDORS: dict[str, EHRVendor] = {
    # SMART Health IT first — works without registration, the demo path.
    "smart": EHRVendor(
        id="smart",
        label="SMART Health IT",
        color="#1F4E79",
        fhir_base_url=_env("SOLACE_SMART_FHIR_URL", _SMART_FHIR),
        authorize_url=_env("SOLACE_SMART_AUTHORIZE_URL", _SMART_AUTH),
        token_url=_env("SOLACE_SMART_TOKEN_URL", _SMART_TOKEN),
        # SMART Health IT accepts any client_id — this string is shipped to demos.
        client_id=_env("SOLACE_SMART_CLIENT_ID", "solace_demo"),
        scopes=_DEFAULT_SCOPES,
        scopes_v2=_DEFAULT_SCOPES_V2,
        sandbox=True,
    ),
    "epic": EHRVendor(
        id="epic",
        label="Epic",
        color="#CB2E2E",
        fhir_base_url=_env("SOLACE_EPIC_FHIR_URL", _EPIC_FHIR),
        authorize_url=_env("SOLACE_EPIC_AUTHORIZE_URL", _EPIC_AUTH),
        token_url=_env("SOLACE_EPIC_TOKEN_URL", _EPIC_TOKEN),
        client_id=_env("SOLACE_EPIC_CLIENT_ID", ""),
        scopes=_DEFAULT_SCOPES,
        scopes_v2=_DEFAULT_SCOPES_V2,
        sandbox=_env("SOLACE_EPIC_SANDBOX", "true").lower() == "true",
    ),
    "cerner": EHRVendor(
        id="cerner",
        label="Oracle Cerner",
        color="#386FA4",
        fhir_base_url=_env("SOLACE_CERNER_FHIR_URL", _CERNER_FHIR),
        authorize_url=_env("SOLACE_CERNER_AUTHORIZE_URL", _CERNER_AUTH),
        token_url=_env("SOLACE_CERNER_TOKEN_URL", _CERNER_TOKEN),
        client_id=_env("SOLACE_CERNER_CLIENT_ID", ""),
        scopes=_DEFAULT_SCOPES,
        scopes_v2=_DEFAULT_SCOPES_V2,
        sandbox=_env("SOLACE_CERNER_SANDBOX", "true").lower() == "true",
    ),
    "athena": EHRVendor(
        id="athena",
        label="Athenahealth",
        color="#5B7F4F",
        fhir_base_url=_env(
            "SOLACE_ATHENA_FHIR_URL",
            "https://api.preview.platform.athenahealth.com/fhir/r4/",
        ),
        authorize_url=_env(
            "SOLACE_ATHENA_AUTHORIZE_URL",
            "https://api.preview.platform.athenahealth.com/oauth2/v1/authorize",
        ),
        token_url=_env(
            "SOLACE_ATHENA_TOKEN_URL",
            "https://api.preview.platform.athenahealth.com/oauth2/v1/token",
        ),
        client_id=_env("SOLACE_ATHENA_CLIENT_ID", ""),
        scopes=_DEFAULT_SCOPES,
        scopes_v2=_DEFAULT_SCOPES_V2,
        sandbox=_env("SOLACE_ATHENA_SANDBOX", "true").lower() == "true",
    ),
}


def get(vendor_id: str) -> EHRVendor | None:
    return VENDORS.get((vendor_id or "").lower())


def from_workspace_config(cfg: dict) -> EHRVendor:
    """Build an :class:`EHRVendor` from a per-workspace EHR-config record.

    The per-workspace binding (``services.ehr_config``) stores the same SMART
    metadata a static ``VENDORS`` entry carries — vendor id, FHIR base URL,
    authorize/token endpoints, client_id, and the chosen scope set — but scoped
    to one ``(hospital_id, workspace_id)`` instead of process-wide env vars.

    This lets the SMART flow resolve a tenant's real Epic/Cerner/Athena binding
    at request time instead of a single shipped-everywhere default. Where a field
    is absent from the stored config we fall back to the static vendor template
    for that ``vendor`` id (so a workspace can override only the URLs it needs).

    NOTE: this NEVER carries a client secret or private key — those live only in
    AWS Secrets Manager, referenced by name on the config record (COMP-007). The
    returned ``EHRVendor`` is pure non-secret routing metadata.
    """
    vendor_id = str(cfg.get("vendor", "")).lower()
    base = VENDORS.get(vendor_id)

    def _f(key: str, fallback: str) -> str:
        val = cfg.get(key)
        return str(val) if val not in (None, "") else fallback

    raw_scopes = cfg.get("scopes")
    if isinstance(raw_scopes, (list, tuple)) and raw_scopes:
        scopes_v1: tuple[str, ...] = tuple(str(s) for s in raw_scopes)
    else:
        scopes_v1 = base.scopes if base else _DEFAULT_SCOPES

    raw_scopes_v2 = cfg.get("scopes_v2")
    if isinstance(raw_scopes_v2, (list, tuple)) and raw_scopes_v2:
        scopes_v2: tuple[str, ...] = tuple(str(s) for s in raw_scopes_v2)
    else:
        scopes_v2 = base.scopes_v2 if base else _DEFAULT_SCOPES_V2

    return EHRVendor(
        id=vendor_id or (base.id if base else "smart"),
        label=_f("label", base.label if base else vendor_id),
        color=_f("color", base.color if base else "#1F4E79"),
        fhir_base_url=_f("fhir_base_url", base.fhir_base_url if base else ""),
        authorize_url=_f("authorize_url", base.authorize_url if base else ""),
        token_url=_f("token_url", base.token_url if base else ""),
        client_id=_f("client_id", base.client_id if base else ""),
        scopes=scopes_v1,
        scopes_v2=scopes_v2,
        sandbox=bool(cfg.get("sandbox", base.sandbox if base else True)),
    )


def list_public() -> list[dict]:
    """Vendors with a configured client_id, plus SMART (always on for demo)."""
    out: list[dict] = []
    for v in VENDORS.values():
        # Hide vendors that aren't usable yet — no client_id means a click would
        # 400 at the vendor's authorize endpoint. SMART always works.
        if v.id == "smart" or v.client_id:
            out.append(v.to_public_dict())
    return out
