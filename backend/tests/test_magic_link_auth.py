"""End-to-end test of the magic-link identity spine (Phase 1).

Runs entirely in local mode (in-memory accounts store, console email, dev-echo
link) so no AWS is required. Exercises the real FastAPI routes through
TestClient: request -> dev_link -> verify -> JWT, plus single-use and
no-enumeration guarantees.
"""
from __future__ import annotations

import os
import uuid
from urllib.parse import parse_qs, urlparse

# Force local mode + dev echo BEFORE importing app/config.
os.environ["SOLACE_MODE"] = "local"
os.environ["EMAIL_DEV_ECHO"] = "true"

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import accounts, jwt_auth  # noqa: E402

# Belt-and-suspenders in case settings was constructed before the env was set.
settings.solace_mode = "local"
settings.email_dev_echo = True

from main import app  # noqa: E402

HOSPITAL = "test-clinic"


@pytest.fixture
def client():
    """Fresh stores + a unique User-Agent per test.

    Rate-limit/abuse counters key on an IP+UA identity hash. A unique UA gives
    each test its own bucket, so they don't accumulate against each other when
    the whole suite shares TestClient's synthetic identity.
    """
    accounts._clinicians.clear()
    accounts._magic_tokens.clear()
    c = TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"})
    yield c
    accounts._clinicians.clear()
    accounts._magic_tokens.clear()


def _token_from_dev_link(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def test_magic_link_full_login_flow(client):
    accounts.create_clinician(
        hospital_id=HOSPITAL, email="doc@clinic.org", name="Dr. Rivera", role="attending"
    )

    r = client.post(f"/api/{HOSPITAL}/auth/magic/request", json={"email": "doc@clinic.org"})
    assert r.status_code == 200, r.text
    dev_link = r.json().get("dev_link")
    assert dev_link and f"/h/{HOSPITAL}/auth/verify" in dev_link

    token = _token_from_dev_link(dev_link)
    v = client.post(f"/api/{HOSPITAL}/auth/magic/verify", json={"token": token})
    assert v.status_code == 200, v.text
    jwt_token = v.json()["token"]
    assert v.json()["role"] == "attending"

    sess = jwt_auth.verify_token(jwt_token)
    assert sess.hospital_id == HOSPITAL
    assert sess.name == "Dr. Rivera"


def test_token_is_single_use(client):
    accounts.create_clinician(hospital_id=HOSPITAL, email="doc@clinic.org", name="Dr. Rivera")
    r = client.post(f"/api/{HOSPITAL}/auth/magic/request", json={"email": "doc@clinic.org"})
    token = _token_from_dev_link(r.json()["dev_link"])

    assert client.post(f"/api/{HOSPITAL}/auth/magic/verify", json={"token": token}).status_code == 200
    # Second redeem of the same token must fail.
    assert client.post(f"/api/{HOSPITAL}/auth/magic/verify", json={"token": token}).status_code == 401


def test_unknown_email_does_not_enumerate(client):
    # No clinician for this email -> still 200, but NO dev_link (no token minted).
    r = client.post(f"/api/{HOSPITAL}/auth/magic/request", json={"email": "ghost@nowhere.org"})
    assert r.status_code == 200
    assert "dev_link" not in r.json()


def test_invite_creates_account_on_first_verify(client):
    raw = accounts.issue_magic_token(
        hospital_id=HOSPITAL, email="newhire@clinic.org",
        purpose="invite", role="resident", name="Dr. Lin",
    )
    assert accounts.find_clinician_by_email(HOSPITAL, "newhire@clinic.org") is None

    v = client.post(f"/api/{HOSPITAL}/auth/magic/verify", json={"token": raw})
    assert v.status_code == 200, v.text
    assert v.json()["role"] == "resident"
    assert accounts.find_clinician_by_email(HOSPITAL, "newhire@clinic.org") is not None


def test_wrong_hospital_rejected(client):
    raw = accounts.issue_magic_token(hospital_id="other-clinic", email="doc@clinic.org", purpose="login")
    v = client.post(f"/api/{HOSPITAL}/auth/magic/verify", json={"token": raw})
    assert v.status_code == 401
