"""Workspace CRUD + tenancy isolation tests.

Covers:
  - workspace CRUD through the HTTP surface (create / list / get / update / delete);
  - require_clinician gating (SEC-008);
  - workspace_id validation (service-level and endpoint 400s);
  - cross-workspace / cross-hospital isolation: a clinician authed to hospital A can
    never read, mutate, or delete a workspace owned by hospital B — every such
    attempt 404s and never reveals existence (SEC-008 / COMP-011);
  - the service-level ownership guard + id generator.

Runs in local mode (in-memory storage) — no AWS, no boto3.
"""
from __future__ import annotations

import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402
from lib.auth import require_clinician  # noqa: E402
from db import storage  # noqa: E402
from services import workspaces as workspace_service  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state():
    settings.solace_mode = "local"
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()
    app.dependency_overrides.pop(require_clinician, None)


def _auth_as(hospital_id: str):
    """Override require_clinician to act as a clinician authed to ``hospital_id``."""
    app.dependency_overrides[require_clinician] = lambda: {
        "clinician_id": "tester", "hospital_id": hospital_id,
        "name": "Tester", "role": "clinician", "auth_method": "jwt",
    }


# ---- endpoint auth gating (SEC-008) -------------------------------------------------
def test_list_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")

    app.dependency_overrides[require_clinician] = _reject
    assert client.get("/api/hosp-a/workspaces").status_code == 401


def test_create_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")

    app.dependency_overrides[require_clinician] = _reject
    r = client.post("/api/hosp-a/workspaces", json={"name": "Pediatrics"})
    assert r.status_code == 401


# ---- CRUD happy path ----------------------------------------------------------------
def test_create_and_get_workspace(client):
    _auth_as("hosp-a")
    r = client.post(
        "/api/hosp-a/workspaces",
        json={"name": "Pediatrics", "description": "peds ED"},
    )
    assert r.status_code == 201
    ws = r.json()
    assert ws["hospital_id"] == "hosp-a"
    assert ws["workspace_id"] == "pediatrics"
    assert ws["name"] == "Pediatrics"
    assert ws["status"] == "active"
    assert ws["created_by"] == "tester"

    g = client.get(f"/api/hosp-a/workspaces/{ws['workspace_id']}")
    assert g.status_code == 200
    assert g.json()["workspace_id"] == "pediatrics"


def test_create_with_requested_id(client):
    _auth_as("hosp-a")
    r = client.post(
        "/api/hosp-a/workspaces",
        json={"name": "Emergency Dept North", "requested_id": "ed-north"},
    )
    assert r.status_code == 201
    assert r.json()["workspace_id"] == "ed-north"


def test_list_is_tenant_scoped(client):
    _auth_as("hosp-a")
    client.post("/api/hosp-a/workspaces", json={"name": "Cardiology"})
    client.post("/api/hosp-a/workspaces", json={"name": "Oncology"})
    # A workspace under a different hospital must not appear in hosp-a's list.
    storage.put_workspace(
        {"hospital_id": "hosp-b", "workspace_id": "neurology", "name": "Neuro"}
    )

    r = client.get("/api/hosp-a/workspaces")
    assert r.status_code == 200
    ids = {w["workspace_id"] for w in r.json()["workspaces"]}
    assert ids == {"cardiology", "oncology"}
    assert "neurology" not in ids


def test_update_workspace(client):
    _auth_as("hosp-a")
    client.post("/api/hosp-a/workspaces", json={"name": "Pediatrics"})
    r = client.patch(
        "/api/hosp-a/workspaces/pediatrics",
        json={"name": "Pediatric ED", "status": "archived"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Pediatric ED"
    assert body["status"] == "archived"
    assert body["updated_at"] is not None


def test_delete_workspace(client):
    _auth_as("hosp-a")
    client.post("/api/hosp-a/workspaces", json={"name": "Pediatrics"})
    d = client.delete("/api/hosp-a/workspaces/pediatrics")
    assert d.status_code == 200
    assert d.json()["deleted"] is True
    # Gone now.
    assert client.get("/api/hosp-a/workspaces/pediatrics").status_code == 404


# ---- workspace_id validation --------------------------------------------------------
def test_create_with_invalid_requested_id(client):
    _auth_as("hosp-a")
    r = client.post(
        "/api/hosp-a/workspaces",
        json={"name": "Bad", "requested_id": "Has Spaces!"},
    )
    assert r.status_code == 400


def test_create_with_reserved_id(client):
    _auth_as("hosp-a")
    r = client.post(
        "/api/hosp-a/workspaces",
        json={"name": "All", "requested_id": "all"},
    )
    assert r.status_code == 400


def test_duplicate_requested_id_conflicts(client):
    _auth_as("hosp-a")
    client.post("/api/hosp-a/workspaces", json={"name": "Peds", "requested_id": "peds"})
    r = client.post("/api/hosp-a/workspaces", json={"name": "Peds2", "requested_id": "peds"})
    assert r.status_code == 409


def test_get_invalid_id_400(client):
    _auth_as("hosp-a")
    # An id that fails the pattern is a 400, not a 404.
    assert client.get("/api/hosp-a/workspaces/AB").status_code == 400


@pytest.mark.parametrize("good", ["ed-north", "peds", "icu-3", "a1b2c3"])
def test_validate_workspace_id_accepts_good(good):
    assert workspace_service.validate_workspace_id(good) == good


@pytest.mark.parametrize(
    "bad", ["ab", "-leads", "trails-", "Upper", "has space", "x" * 49, "all", "wat!"]
)
def test_validate_workspace_id_rejects_bad(bad):
    with pytest.raises(workspace_service.InvalidWorkspaceId):
        workspace_service.validate_workspace_id(bad)


# ---- cross-workspace / cross-hospital ISOLATION (the core security property) --------
def test_cross_hospital_get_is_404(client):
    # hosp-b owns 'neurology'.
    storage.put_workspace(
        {"hospital_id": "hosp-b", "workspace_id": "neurology", "name": "Neuro"}
    )
    # A clinician authed to hosp-a must not be able to read it — and must not learn
    # that it exists. 404, identical to a never-created id.
    _auth_as("hosp-a")
    assert client.get("/api/hosp-a/workspaces/neurology").status_code == 404


def test_cross_hospital_update_is_404_and_no_mutation(client):
    storage.put_workspace(
        {"hospital_id": "hosp-b", "workspace_id": "neurology",
         "name": "Neuro", "status": "active"}
    )
    _auth_as("hosp-a")
    r = client.patch(
        "/api/hosp-a/workspaces/neurology", json={"status": "archived"}
    )
    assert r.status_code == 404
    # hosp-b's record is untouched.
    assert storage.get_workspace("hosp-b", "neurology")["status"] == "active"


def test_cross_hospital_delete_is_404_and_no_mutation(client):
    storage.put_workspace(
        {"hospital_id": "hosp-b", "workspace_id": "neurology", "name": "Neuro"}
    )
    _auth_as("hosp-a")
    r = client.delete("/api/hosp-a/workspaces/neurology")
    assert r.status_code == 404
    # Still present under its real owner.
    assert storage.get_workspace("hosp-b", "neurology") is not None


def test_same_id_different_hospitals_are_isolated(client):
    # Both hospitals legitimately have a 'pediatrics' workspace — they must not
    # collide or bleed into each other.
    _auth_as("hosp-a")
    a = client.post(
        "/api/hosp-a/workspaces", json={"name": "Peds", "requested_id": "pediatrics"}
    )
    assert a.status_code == 201

    _auth_as("hosp-b")
    b = client.post(
        "/api/hosp-b/workspaces", json={"name": "Kids", "requested_id": "pediatrics"}
    )
    assert b.status_code == 201

    # Each sees only its own.
    _auth_as("hosp-a")
    assert client.get("/api/hosp-a/workspaces/pediatrics").json()["name"] == "Peds"
    _auth_as("hosp-b")
    assert client.get("/api/hosp-b/workspaces/pediatrics").json()["name"] == "Kids"


# ---- service-level ownership guard --------------------------------------------------
def test_assert_owned_rejects_cross_tenant():
    rec = {"hospital_id": "hosp-b", "workspace_id": "x", "name": "X"}
    with pytest.raises(workspace_service.CrossTenantWorkspace):
        workspace_service.assert_owned(rec, "hosp-a")


def test_assert_owned_rejects_missing():
    with pytest.raises(workspace_service.CrossTenantWorkspace):
        workspace_service.assert_owned(None, "hosp-a")


def test_assert_owned_accepts_match():
    rec = {"hospital_id": "hosp-a", "workspace_id": "x", "name": "X"}
    assert workspace_service.assert_owned(rec, "hosp-a") is rec


def test_generate_workspace_id_unique_within_hospital():
    storage.put_workspace(
        {"hospital_id": "hosp-a", "workspace_id": "pediatrics", "name": "Peds"}
    )
    wid = workspace_service.generate_workspace_id("hosp-a", "Pediatrics")
    # Collides with the existing one, so it must differ (random suffix appended).
    assert wid != "pediatrics"
    assert wid.startswith("pediatrics-")
