"""GET /.well-known/jwks.json — public JWKS for EHR confidential-client auth.

Serves Solace's PUBLIC signing keys (so Epic/Oracle can verify our private_key_jwt
assertions) from SOLACE_EHR_JWKS, and must never leak private-key material or 500.
"""
from __future__ import annotations

import json
import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

_PUBLIC_JWK = {
    "kty": "RSA", "use": "sig", "alg": "RS384", "kid": "test-kid",
    "n": "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM", "e": "AQAB",
}


@pytest.fixture
def client():
    return TestClient(app)


def test_jwks_empty_when_unset(client, monkeypatch):
    monkeypatch.delenv("SOLACE_EHR_JWKS", raising=False)
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    assert r.json() == {"keys": []}


def test_jwks_serves_configured_public_key(client, monkeypatch):
    monkeypatch.setenv("SOLACE_EHR_JWKS", json.dumps({"keys": [_PUBLIC_JWK]}))
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    body = r.json()
    assert body["keys"][0]["kid"] == "test-kid"
    assert body["keys"][0]["alg"] == "RS384"
    assert "cache-control" in {k.lower() for k in r.headers}


def test_jwks_never_leaks_private_fields(client, monkeypatch):
    leaky = {**_PUBLIC_JWK, "d": "PRIVATE", "p": "PRIVATE", "q": "PRIVATE"}
    monkeypatch.setenv("SOLACE_EHR_JWKS", json.dumps({"keys": [leaky]}))
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    served = r.json()["keys"][0]
    assert "d" not in served and "p" not in served and "q" not in served
    assert "PRIVATE" not in r.text


def test_jwks_malformed_env_yields_empty(client, monkeypatch):
    monkeypatch.setenv("SOLACE_EHR_JWKS", "{not valid json")
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    assert r.json() == {"keys": []}
