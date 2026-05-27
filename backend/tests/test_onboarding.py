"""End-to-end test of Phase 3 onboarding: admin provisioning, teammate invites,
and the request-to-join flow. Local mode, no AWS.
"""
from __future__ import annotations

import os
import uuid
from urllib.parse import parse_qs, urlparse

os.environ["SOLACE_MODE"] = "local"
os.environ["EMAIL_DEV_ECHO"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import accounts  # noqa: E402
from db import storage  # noqa: E402

settings.solace_mode = "local"
settings.email_dev_echo = True

from main import app  # noqa: E402


@pytest.fixture
def client():
    accounts._clinicians.clear()
    accounts._magic_tokens.clear()
    accounts._access_requests.clear()
    storage._hospitals.clear()
    c = TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"})
    yield c
    accounts._clinicians.clear()
    accounts._magic_tokens.clear()
    accounts._access_requests.clear()
    storage._hospitals.clear()


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def _provision_and_signin(client, name="Riverside General", admin="chief@riverside.org"):
    """Provision a workspace with an admin and return (slug, admin auth headers)."""
    r = client.post("/hospitals/provision", json={"name": name, "admin_email": admin})
    assert r.status_code == 200, r.text
    data = r.json()
    slug = data["hospital_id"]
    assert data["admin_invited"] is True
    token = _token(data["admin_dev_link"])
    v = client.post(f"/api/{slug}/auth/magic/verify", json={"token": token})
    assert v.status_code == 200, v.text
    assert v.json()["role"] == "admin"
    return slug, {"Authorization": f"Bearer {v.json()['token']}"}


def test_provision_creates_signed_in_admin(client):
    slug, headers = _provision_and_signin(client)
    who = client.get(f"/api/{slug}/auth/whoami", headers=headers)
    assert who.status_code == 200
    assert who.json()["role"] == "admin"
    # Workspace starts un-onboarded.
    status = client.get(f"/api/{slug}/onboarding", headers=headers)
    assert status.status_code == 200
    assert status.json()["onboarded"] is False
    assert status.json()["team_size"] == 1


def test_admin_invites_teammate_who_can_sign_in(client):
    slug, headers = _provision_and_signin(client)
    inv = client.post(
        f"/api/{slug}/invites",
        json={"email": "nurse@riverside.org", "name": "Pat Nurse", "role": "nurse"},
        headers=headers,
    )
    assert inv.status_code == 200, inv.text
    # The invitee redeems their invite link -> account created with the right role.
    token = _token(inv.json()["dev_link"])
    v = client.post(f"/api/{slug}/auth/magic/verify", json={"token": token})
    assert v.status_code == 200, v.text
    assert v.json()["role"] == "nurse"
    team = client.get(f"/api/{slug}/care-team", headers=headers)
    assert team.json()["count"] == 2


def test_non_admin_cannot_invite(client):
    slug, admin_headers = _provision_and_signin(client)
    # Invite a plain clinician and sign them in.
    inv = client.post(
        f"/api/{slug}/invites",
        json={"email": "doc@riverside.org", "name": "Dr. Doc", "role": "clinician"},
        headers=admin_headers,
    )
    v = client.post(f"/api/{slug}/auth/magic/verify", json={"token": _token(inv.json()["dev_link"])})
    doc_headers = {"Authorization": f"Bearer {v.json()['token']}"}
    # A non-admin trying to invite is forbidden.
    blocked = client.post(
        f"/api/{slug}/invites", json={"email": "x@y.org"}, headers=doc_headers
    )
    assert blocked.status_code == 403


def test_request_to_join_then_admin_approves(client):
    slug, headers = _provision_and_signin(client)
    # Public request to join.
    req = client.post(
        f"/api/{slug}/access-requests",
        json={"email": "applicant@elsewhere.org", "name": "Dr. Applicant", "note": "ER moonlighter"},
    )
    assert req.status_code == 200
    # Admin sees it pending.
    pending = client.get(f"/api/{slug}/access-requests", headers=headers)
    assert pending.status_code == 200
    reqs = pending.json()["requests"]
    assert len(reqs) == 1
    rid = reqs[0]["request_id"]
    # Approve -> invite emailed -> applicant redeems and is in.
    approve = client.post(f"/api/{slug}/access-requests/{rid}/approve", headers=headers)
    assert approve.status_code == 200, approve.text
    v = client.post(f"/api/{slug}/auth/magic/verify", json={"token": _token(approve.json()["dev_link"])})
    assert v.status_code == 200
    assert accounts.find_clinician_by_email(slug, "applicant@elsewhere.org") is not None
    # No longer pending.
    assert client.get(f"/api/{slug}/access-requests", headers=headers).json()["requests"] == []


def test_complete_onboarding_sets_flag(client):
    slug, headers = _provision_and_signin(client)
    done = client.post(f"/api/{slug}/onboarding/complete", headers=headers)
    assert done.status_code == 200
    assert client.get(f"/api/{slug}/onboarding", headers=headers).json()["onboarded"] is True


def test_reset_demo_blocked_for_real_workspace(client):
    # Phase 5: demo scaffolding must never touch a provisioned workspace.
    slug, headers = _provision_and_signin(client)
    r = client.post(f"/api/{slug}/admin/reset-demo", headers=headers)
    assert r.status_code == 403
