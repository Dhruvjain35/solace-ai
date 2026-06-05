"""Per-workspace EHR vendor-config: service, router, and SMART-flow integration.

Covers the WS-EHR-WSCFG mission:
  1. Per-workspace vendor config CRUD via db.storage, keyed by (hospital_id,
     workspace_id); clinician-only (SEC-008); audit on mutation (COMP-002); errors
     as HTTPException (QUAL-003); cross-tenant isolation (SEC-008 / COMP-011).
  2. Secrets referenced by AWS Secrets Manager NAME only — never plaintext (COMP-007):
     inline PEM/secret material is rejected, and the public view never echoes a value.
  3. SMART v2 `cruds` scopes with per-vendor minimum-necessary sets + v1 fallback.
  4. Token lifecycle: expiry tracking on the handoff/refresh payloads, and a /revoke
     path that invalidates a parked handle.

Runs in local mode (in-memory storage) — no AWS, no boto3.
"""
from __future__ import annotations

import os

os.environ["SOLACE_MODE"] = "local"

import time  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402
from lib.auth import require_clinician  # noqa: E402
from lib import ehr_vendors, smart_auth  # noqa: E402
from db import storage  # noqa: E402
from services import ehr_config as ehr_config_service  # noqa: E402
from services import workspaces as workspace_service  # noqa: E402
from routers import ehr_auth  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state():
    settings.solace_mode = "local"
    storage._reset_for_tests()
    ehr_auth._LAUNCH_STATES_LOCAL.clear()
    yield
    storage._reset_for_tests()
    ehr_auth._LAUNCH_STATES_LOCAL.clear()
    app.dependency_overrides.pop(require_clinician, None)


def _auth_as(hospital_id: str):
    app.dependency_overrides[require_clinician] = lambda: {
        "clinician_id": "tester", "hospital_id": hospital_id,
        "name": "Tester", "role": "clinician", "auth_method": "jwt",
    }


def _seed_workspace(hospital_id: str, name: str = "Pediatrics") -> str:
    ws = workspace_service.create_workspace(hospital_id=hospital_id, name=name)
    return ws["workspace_id"]


# ---- clinician gating (SEC-008) -----------------------------------------------------
def test_get_config_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")

    app.dependency_overrides[require_clinician] = _reject
    r = client.get("/api/hosp-a/workspaces/peds/ehr-config")
    assert r.status_code == 401


def test_list_configs_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")

    app.dependency_overrides[require_clinician] = _reject
    assert client.get("/api/hosp-a/ehr-configs").status_code == 401


# ---- CRUD round-trip ----------------------------------------------------------------
def test_create_and_get_config(client):
    _auth_as("hosp-a")
    wid = _seed_workspace("hosp-a")
    r = client.put(
        f"/api/hosp-a/workspaces/{wid}/ehr-config",
        json={"vendor": "smart"},
    )
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["vendor"] == "smart"
    assert cfg["hospital_id"] == "hosp-a"
    assert cfg["workspace_id"] == wid
    # Defaults from the static vendor template fill in endpoints.
    assert cfg["fhir_base_url"].startswith("https://")
    assert cfg["smart_version"] == "v2"

    got = client.get(f"/api/hosp-a/workspaces/{wid}/ehr-config")
    assert got.status_code == 200
    assert got.json()["vendor"] == "smart"


def test_create_requires_vendor(client):
    _auth_as("hosp-a")
    wid = _seed_workspace("hosp-a")
    r = client.put(f"/api/hosp-a/workspaces/{wid}/ehr-config", json={"label": "x"})
    assert r.status_code == 400


def test_config_requires_existing_workspace(client):
    _auth_as("hosp-a")
    # No workspace created → binding target does not exist for this hospital → 404.
    r = client.put("/api/hosp-a/workspaces/ghost-ws/ehr-config", json={"vendor": "smart"})
    assert r.status_code == 404


def test_patch_and_delete_config(client):
    _auth_as("hosp-a")
    wid = _seed_workspace("hosp-a")
    client.put(f"/api/hosp-a/workspaces/{wid}/ehr-config", json={"vendor": "smart"})

    patched = client.patch(
        f"/api/hosp-a/workspaces/{wid}/ehr-config",
        json={"label": "Peds SMART", "smart_version": "v1"},
    )
    assert patched.status_code == 200
    assert patched.json()["label"] == "Peds SMART"
    assert patched.json()["smart_version"] == "v1"

    deleted = client.delete(f"/api/hosp-a/workspaces/{wid}/ehr-config")
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert client.get(f"/api/hosp-a/workspaces/{wid}/ehr-config").status_code == 404


def test_list_configs_scoped_to_hospital(client):
    _auth_as("hosp-a")
    w1 = _seed_workspace("hosp-a", "Peds")
    w2 = _seed_workspace("hosp-a", "Cardio")
    client.put(f"/api/hosp-a/workspaces/{w1}/ehr-config", json={"vendor": "smart"})
    client.put(f"/api/hosp-a/workspaces/{w2}/ehr-config", json={"vendor": "epic"})
    r = client.get("/api/hosp-a/ehr-configs")
    assert r.status_code == 200
    vendors = {c["vendor"] for c in r.json()["configs"]}
    assert vendors == {"smart", "epic"}


# ---- cross-tenant isolation (SEC-008 / COMP-011) ------------------------------------
def test_cross_hospital_config_is_invisible(client):
    # hosp-b owns a workspace + config.
    wid = _seed_workspace("hosp-b")
    ehr_config_service.upsert_config(
        hospital_id="hosp-b", workspace_id=wid, body={"vendor": "epic"}
    )
    # A clinician authed to hosp-a must never see it — 404, existence not revealed.
    _auth_as("hosp-a")
    assert client.get(f"/api/hosp-a/workspaces/{wid}/ehr-config").status_code == 404
    # And it is absent from hosp-a's list.
    assert client.get("/api/hosp-a/ehr-configs").json()["configs"] == []


def test_cross_hospital_delete_blocked(client):
    wid = _seed_workspace("hosp-b")
    ehr_config_service.upsert_config(
        hospital_id="hosp-b", workspace_id=wid, body={"vendor": "epic"}
    )
    _auth_as("hosp-a")
    assert client.delete(f"/api/hosp-a/workspaces/{wid}/ehr-config").status_code == 404
    # hosp-b's config survives the cross-tenant delete attempt.
    assert storage.get_ehr_config("hosp-b", wid) is not None


# ---- secrets-by-reference only (COMP-007) -------------------------------------------
def test_inline_private_key_is_rejected(client):
    _auth_as("hosp-a")
    wid = _seed_workspace("hosp-a")
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    r = client.put(
        f"/api/hosp-a/workspaces/{wid}/ehr-config",
        json={"vendor": "epic", "private_key_ref": pem},
    )
    assert r.status_code == 400, r.text


def test_secret_ref_name_is_accepted_and_value_never_returned(client):
    _auth_as("hosp-a")
    wid = _seed_workspace("hosp-a")
    r = client.put(
        f"/api/hosp-a/workspaces/{wid}/ehr-config",
        json={"vendor": "epic", "private_key_ref": "solace/ehr/hosp-a/epic-key"},
    )
    assert r.status_code == 200, r.text
    cfg = r.json()
    # The reference NAME is surfaced (it's a pointer), the value is not.
    assert cfg["private_key_ref"] == "solace/ehr/hosp-a/epic-key"
    assert cfg["confidential_client"] is True
    # No field in the public view carries secret material.
    assert "private_key" not in cfg
    assert "-----BEGIN" not in r.text


def test_stored_record_never_holds_plaintext_secret():
    wid = _seed_workspace("hosp-a")
    ehr_config_service.upsert_config(
        hospital_id="hosp-a", workspace_id=wid,
        body={"vendor": "epic", "client_secret_ref": "solace/ehr/epic-secret"},
    )
    raw = storage.get_ehr_config("hosp-a", wid)
    assert raw["client_secret_ref"] == "solace/ehr/epic-secret"
    # The raw record stores only the reference name — there is no value field at all.
    assert "client_secret" not in raw
    assert "private_key" not in raw


# ---- SMART v2 scopes + v1 fallback --------------------------------------------------
def test_vendor_v2_scopes_use_cruds_spelling():
    v = ehr_vendors.get("epic")
    v2 = v.scope_string(smart_version="v2")
    # v2 grammar: read+search spelled `.rs`, never the v1 `.read`.
    assert "user/Patient.rs" in v2
    assert ".read" not in v2
    # Identity scopes are unchanged across versions.
    assert "openid" in v2 and "fhirUser" in v2


def test_vendor_v1_fallback_keeps_read_spelling():
    v = ehr_vendors.get("epic")
    v1 = v.scope_string(smart_version="v1")
    assert "user/Patient.read" in v1
    assert ".rs" not in v1


def test_v2_scopes_parse_as_minimum_necessary_read_only():
    v = ehr_vendors.get("smart")
    granted = v.scope_string(smart_version="v2")
    # read + search are granted...
    assert smart_auth.scope_granted(granted, "user", "Observation", "r")
    assert smart_auth.scope_granted(granted, "user", "Observation", "s")
    # ...but write/create/delete are NOT (minimum-necessary, HIPAA §164.502(b)).
    assert not smart_auth.scope_granted(granted, "user", "Observation", "c")
    assert not smart_auth.scope_granted(granted, "user", "Observation", "u")
    assert not smart_auth.scope_granted(granted, "user", "Observation", "d")


# ---- per-workspace vendor resolution for the SMART flow -----------------------------
def test_resolve_vendor_prefers_workspace_config():
    wid = _seed_workspace("hosp-a")
    ehr_config_service.upsert_config(
        hospital_id="hosp-a", workspace_id=wid,
        body={
            "vendor": "epic",
            "fhir_base_url": "https://tenant.example.org/fhir/r4/",
            "client_id": "tenant-specific-client",
        },
    )
    v = ehr_config_service.resolve_vendor("hosp-a", wid)
    assert v is not None
    assert v.fhir_base_url == "https://tenant.example.org/fhir/r4/"
    assert v.client_id == "tenant-specific-client"
    # The v2 scope set comes along from the vendor template.
    assert "user/Patient.rs" in v.scope_string(smart_version="v2")


def test_resolve_vendor_none_when_no_config():
    wid = _seed_workspace("hosp-a")
    assert ehr_config_service.resolve_vendor("hosp-a", wid) is None
    assert ehr_config_service.resolve_vendor("hosp-a", "") is None


def test_resolve_vendor_skips_disabled_config():
    wid = _seed_workspace("hosp-a")
    ehr_config_service.upsert_config(
        hospital_id="hosp-a", workspace_id=wid, body={"vendor": "epic", "status": "disabled"},
    )
    assert ehr_config_service.resolve_vendor("hosp-a", wid) is None


def test_resolve_vendor_is_tenant_isolated():
    wid = _seed_workspace("hosp-b")
    ehr_config_service.upsert_config(
        hospital_id="hosp-b", workspace_id=wid, body={"vendor": "epic"}
    )
    # Asking as hosp-a for hosp-b's workspace must not resolve hosp-b's binding.
    assert ehr_config_service.resolve_vendor("hosp-a", wid) is None


# ---- confidential-secret resolution (local-mode env fallback) -----------------------
def test_resolve_secret_returns_none_for_public_client():
    wid = _seed_workspace("hosp-a")
    ehr_config_service.upsert_config(
        hospital_id="hosp-a", workspace_id=wid, body={"vendor": "smart"}
    )
    value, kid = ehr_config_service.resolve_secret("hosp-a", wid)
    assert value is None and kid is None


def test_resolve_secret_dereferences_local_env(monkeypatch):
    wid = _seed_workspace("hosp-a")
    ehr_config_service.upsert_config(
        hospital_id="hosp-a", workspace_id=wid,
        body={"vendor": "epic", "private_key_ref": "solace/ehr/epic-key", "kid": "k1"},
    )
    # In local mode the secret_name maps to an UPPER_SNAKE env var.
    monkeypatch.setenv("SOLACE_EHR_EPIC_KEY", "PRETEND_PEM_VALUE")
    value, kid = ehr_config_service.resolve_secret("hosp-a", wid, kind="private_key")
    assert value == "PRETEND_PEM_VALUE"
    assert kid == "k1"


# ---- SMART /launch uses the per-workspace binding -----------------------------------
def test_launch_uses_workspace_vendor_binding(client):
    wid = _seed_workspace("demo")
    ehr_config_service.upsert_config(
        hospital_id="demo", workspace_id=wid,
        body={
            "vendor": "smart",
            "fhir_base_url": "http://localhost:9/fhir",
            "authorize_url": "http://localhost:9/authorize",
            "token_url": "http://localhost:9/token",
            "client_id": "ws-client",
        },
    )
    r = client.get(
        "/api/auth/ehr/launch",
        params={
            "vendor": "smart", "hospital_id": "demo", "workspace_id": wid,
            "redirect_uri": "http://localhost:5173/cb",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    # The authorize redirect points at the workspace-configured endpoint + client.
    assert loc.startswith("http://localhost:9/authorize")
    assert "client_id=ws-client" in loc
    # v2 cruds scopes are requested by default (url-encoded `.rs`).
    assert "Patient.rs" in loc.replace("%2F", "/").replace("+", " ")


def test_launch_falls_back_to_static_without_workspace(client):
    r = client.get(
        "/api/auth/ehr/launch",
        params={
            "vendor": "smart", "hospital_id": "demo",
            "redirect_uri": "http://localhost:5173/cb",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    # Static SMART Health IT authorize endpoint.
    assert "launch.smarthealthit.org" in r.headers["location"]


# ---- token lifecycle: expiry tracking + revoke --------------------------------------
def test_exchange_includes_expiry_and_revoke_invalidates_handle(client):
    # Park a handoff exactly as callback() does, including a refresh_token + expiry.
    code = "lifecycle-code-1"
    handoff_payload = {
        "token": "jwt", "clinician_id": "c1",
        "access_token_expires_in": 3600,
        "access_token_expires_at": int(time.time()) + 3600,
    }
    ehr_auth._store_state(f"handoff-{code}", {
        "handoff": __import__("json").dumps(handoff_payload),
        "refresh_token": "RT_SHOULD_NOT_LEAK",
        "vendor": "smart",
        "token_url": "http://localhost:9/token",
        "hospital_id": "demo",
        "workspace_id": "peds",
        "exp": int(time.time()) + 120,
    })
    ex = client.post("/api/auth/ehr/exchange", json={"handoff_code": code})
    assert ex.status_code == 200, ex.text
    body = ex.json()
    assert body["access_token_expires_in"] == 3600
    assert body["access_token_expires_at"] > int(time.time())
    handle = body["refresh_handle"]
    assert "RT_SHOULD_NOT_LEAK" not in ex.text

    # The re-parked refresh record carries tenant identity (for /refresh resolution).
    parked = ehr_auth._LAUNCH_STATES_LOCAL[f"refresh-{handle}"]
    assert parked["hospital_id"] == "demo" and parked["workspace_id"] == "peds"
    assert "ttl" in parked  # self-expiry

    # Revoke consumes the handle; a second revoke is idempotent.
    rv = client.post("/api/auth/ehr/revoke", json={"refresh_handle": handle})
    assert rv.status_code == 200 and rv.json()["revoked"] is True
    assert ehr_auth._pop_state(f"refresh-{handle}") is None


def test_revoke_unknown_handle_is_idempotent(client):
    rv = client.post("/api/auth/ehr/revoke", json={"refresh_handle": "nope"})
    assert rv.status_code == 200 and rv.json()["revoked"] is True
