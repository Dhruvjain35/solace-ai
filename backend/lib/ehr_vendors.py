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
    scopes: tuple[str, ...]
    sandbox: bool       # True = demo / sandbox / non-PHI environment
    pkce_required: bool = True  # SMART-on-FHIR public clients MUST use PKCE

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "color": self.color,
            "sandbox": self.sandbox,
        }


# SMART-on-FHIR scope set per https://hl7.org/fhir/smart-app-launch/scopes-and-launch-context.html
# `launch/patient` lets the EHR pass us a patient context on launch (when applicable).
# `online_access` requests a refresh token so we don't have to re-prompt every 30 min.
_DEFAULT_SCOPES: tuple[str, ...] = (
    "openid",
    "fhirUser",
    "launch",
    "online_access",
    "profile",
    "user/Patient.read",
    "user/Practitioner.read",
    "user/Encounter.read",
    "user/Observation.read",
    "user/MedicationRequest.read",
    "user/AllergyIntolerance.read",
    "user/Condition.read",
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
        sandbox=_env("SOLACE_ATHENA_SANDBOX", "true").lower() == "true",
    ),
}


def get(vendor_id: str) -> EHRVendor | None:
    return VENDORS.get((vendor_id or "").lower())


def list_public() -> list[dict]:
    """Vendors with a configured client_id, plus SMART (always on for demo)."""
    out: list[dict] = []
    for v in VENDORS.values():
        # Hide vendors that aren't usable yet — no client_id means a click would
        # 400 at the vendor's authorize endpoint. SMART always works.
        if v.id == "smart" or v.client_id:
            out.append(v.to_public_dict())
    return out
