"""Public contact/sales form (POST /api/contact) — local mode, no AWS.

Pattern from test_magic_link_auth.py: real FastAPI routes through TestClient,
in-memory storage, console email. Rate-limit identity is IP+User-Agent, so each
test gets a unique UA and therefore its own quota bucket.
"""
from __future__ import annotations

import os
import uuid

# Force local mode BEFORE importing app/config.
os.environ["SOLACE_MODE"] = "local"
os.environ["EMAIL_DEV_ECHO"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import quota  # noqa: E402
from db import storage  # noqa: E402

# Belt-and-suspenders in case settings was constructed before the env was set.
settings.solace_mode = "local"
settings.email_dev_echo = True

from main import app  # noqa: E402


VALID = {
    "name": "Dr. Maya Singh",
    "email": "maya@riversidehealth.org",
    "organization": "Riverside Health",
    "role": "CMO",
    "topic": "demo",
    "message": "We run a 12-provider urgent care group and want a walkthrough.",
}


@pytest.fixture
def client():
    """Fresh contact store + a unique User-Agent per test (own quota bucket)."""
    storage._contact_requests.clear()
    c = TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"})
    yield c
    storage._contact_requests.clear()


def test_valid_submit_stores_and_returns_ok(client):
    r = client.post("/api/contact", json=VALID)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    cid = body["id"]
    assert cid and cid.startswith("ct-")

    stored = storage._contact_requests.get(cid)
    assert stored is not None
    assert stored["email"] == VALID["email"]
    assert stored["topic"] == "demo"
    assert stored["status"] == "new"


def test_honeypot_silently_drops_without_storing(client):
    r = client.post("/api/contact", json={**VALID, "website": "http://spam.example"})
    # Indistinguishable from a success — but nothing is stored.
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["id"]
    assert storage._contact_requests == {}


def test_invalid_email_is_422(client):
    r = client.post("/api/contact", json={**VALID, "email": "not-an-email"})
    assert r.status_code == 422
    assert storage._contact_requests == {}


def test_invalid_topic_and_oversize_message_are_422(client):
    assert client.post("/api/contact", json={**VALID, "topic": "spam"}).status_code == 422
    assert client.post("/api/contact", json={**VALID, "message": "x" * 4001}).status_code == 422
    assert storage._contact_requests == {}


class _FakeQuotaTable:
    """In-memory stand-in for DDB solace-quotas. In local mode the real quota
    layer fails open (no AWS); this fake makes the atomic ADD counter real so
    the 429 path is exercised end to end."""

    def __init__(self):
        self.rows: dict[str, int] = {}

    def update_item(self, *, Key, ExpressionAttributeValues, **_kw):
        k = Key["bucket_key"]
        self.rows[k] = self.rows.get(k, 0) + int(ExpressionAttributeValues[":u"])
        return {"Attributes": {"count": self.rows[k]}}


def test_rate_limit_kicks_in(client, monkeypatch):
    fake = _FakeQuotaTable()
    monkeypatch.setattr(quota, "_table", lambda: fake)

    limit = quota.LIMITS["contact.submit"].per_hour
    for i in range(limit):
        r = client.post("/api/contact", json=VALID)
        assert r.status_code == 200, f"submit {i + 1}/{limit}: {r.text}"

    blocked = client.post("/api/contact", json=VALID)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    # Nothing past the limit was stored.
    assert len(storage._contact_requests) == limit


def test_notify_email_sent_when_configured(client, monkeypatch):
    from routers import contact as contact_router

    sent: list[dict] = []
    monkeypatch.setattr(settings, "contact_notify_email", "sales@solace.health")
    monkeypatch.setattr(
        contact_router.email_service,
        "send_email",
        lambda **kw: sent.append(kw) or {"provider": "console", "delivered": True},
    )

    r = client.post("/api/contact", json=VALID)
    assert r.status_code == 200
    assert len(sent) == 1
    assert sent[0]["to"] == "sales@solace.health"
    assert VALID["name"] in sent[0]["subject"]
