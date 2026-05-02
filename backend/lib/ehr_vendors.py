"""EHR vendor registry.

Each entry mirrors the SMART-on-FHIR launch.json that the vendor publishes —
this is exactly the metadata Solace needs to integrate with real Epic / Cerner /
Athena environments. For demo / hackathon purposes the values point at our own
mock authorize endpoint so the OAuth dance works end-to-end without real
credentials. To flip on a vendor for real, replace the URLs + client_id + scopes
and re-deploy. Nothing else changes.

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
    authorize_url: str  # OAuth2 authorize endpoint (vendor-hosted in prod)
    token_url: str      # OAuth2 token exchange endpoint
    client_id: str      # Solace's registered client_id with this vendor
    scopes: tuple[str, ...]
    sandbox: bool       # True = demo / sandbox / non-PHI environment

    def to_public_dict(self) -> dict:
        # Subset shipped to the frontend — never includes secrets.
        return {
            "id": self.id,
            "label": self.label,
            "color": self.color,
            "sandbox": self.sandbox,
        }


# Production-grade scope sets — request only what we use to keep consent prompts honest.
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

# Read overrides from the environment so the same code base flips between
# mock (demo) and real (Epic App Orchard, Cerner Code Console) without a rebuild.
_BASE = os.environ.get("SOLACE_API_BASE_URL", "https://djfjrel7b1ebi.cloudfront.net")
_MOCK_AUTHORIZE = f"{_BASE}/api/auth/ehr/mock-authorize"
_MOCK_TOKEN = f"{_BASE}/api/auth/ehr/mock-token"
_MOCK_FHIR = f"{_BASE}/api/auth/ehr/mock-fhir"


VENDORS: dict[str, EHRVendor] = {
    "epic": EHRVendor(
        id="epic",
        label="Epic",
        color="#CB2E2E",
        fhir_base_url=os.environ.get(
            "SOLACE_EPIC_FHIR_URL",
            f"{_MOCK_FHIR}/epic",
        ),
        authorize_url=os.environ.get(
            "SOLACE_EPIC_AUTHORIZE_URL",
            _MOCK_AUTHORIZE,
        ),
        token_url=os.environ.get(
            "SOLACE_EPIC_TOKEN_URL",
            _MOCK_TOKEN,
        ),
        client_id=os.environ.get("SOLACE_EPIC_CLIENT_ID", "solace-epic-sandbox"),
        scopes=_DEFAULT_SCOPES,
        sandbox=os.environ.get("SOLACE_EPIC_SANDBOX", "true").lower() == "true",
    ),
    "cerner": EHRVendor(
        id="cerner",
        label="Oracle Cerner",
        color="#386FA4",
        fhir_base_url=os.environ.get(
            "SOLACE_CERNER_FHIR_URL",
            f"{_MOCK_FHIR}/cerner",
        ),
        authorize_url=os.environ.get(
            "SOLACE_CERNER_AUTHORIZE_URL",
            _MOCK_AUTHORIZE,
        ),
        token_url=os.environ.get(
            "SOLACE_CERNER_TOKEN_URL",
            _MOCK_TOKEN,
        ),
        client_id=os.environ.get("SOLACE_CERNER_CLIENT_ID", "solace-cerner-sandbox"),
        scopes=_DEFAULT_SCOPES,
        sandbox=os.environ.get("SOLACE_CERNER_SANDBOX", "true").lower() == "true",
    ),
    "athena": EHRVendor(
        id="athena",
        label="Athenahealth",
        color="#5B7F4F",
        fhir_base_url=os.environ.get(
            "SOLACE_ATHENA_FHIR_URL",
            f"{_MOCK_FHIR}/athena",
        ),
        authorize_url=os.environ.get(
            "SOLACE_ATHENA_AUTHORIZE_URL",
            _MOCK_AUTHORIZE,
        ),
        token_url=os.environ.get(
            "SOLACE_ATHENA_TOKEN_URL",
            _MOCK_TOKEN,
        ),
        client_id=os.environ.get("SOLACE_ATHENA_CLIENT_ID", "solace-athena-sandbox"),
        scopes=_DEFAULT_SCOPES,
        sandbox=os.environ.get("SOLACE_ATHENA_SANDBOX", "true").lower() == "true",
    ),
}


def get(vendor_id: str) -> EHRVendor | None:
    return VENDORS.get((vendor_id or "").lower())


def list_public() -> list[dict]:
    return [v.to_public_dict() for v in VENDORS.values()]
