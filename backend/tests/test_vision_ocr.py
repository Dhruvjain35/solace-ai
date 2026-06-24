"""Vision OCR endpoint tests — Azure DI submit/poll, retries, caps, quota.

Azure is never called: httpx traffic is intercepted with httpx.MockTransport
via the azure_ocr._client test seam. Covers 503-when-unconfigured, the 429/5xx
retry behavior, the 8MB decoded cap, quota consumption, and audit capture.
"""
from __future__ import annotations

import base64
import os

os.environ["SOLACE_MODE"] = "local"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db import storage  # noqa: E402
from lib import quota  # noqa: E402
from lib.auth import require_clinician  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from services import azure_ocr  # noqa: E402

HOSP = "hosp-a"
URL = f"/api/{HOSP}/vision"
FAKE_ENDPOINT = "https://fake-di.cognitiveservices.azure.com"
OP_URL = FAKE_ENDPOINT + "/documentintelligence/operations/op-1"

PNG_B64 = base64.b64encode(b"\x89PNG fake image bytes").decode()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    settings.solace_mode = "local"
    storage._reset_for_tests()
    app.dependency_overrides[require_clinician] = lambda: {
        "clinician_id": "tester", "hospital_id": HOSP,
        "name": "Tester", "role": "clinician", "auth_method": "jwt",
    }
    # Unconfigured by default; individual tests flip these on.
    monkeypatch.setattr(settings, "azure_di_endpoint", "")
    monkeypatch.setattr(settings, "azure_di_key", "")
    monkeypatch.setattr(azure_ocr, "_sleep", lambda s: None)  # instant retries/polls
    yield
    storage._reset_for_tests()
    app.dependency_overrides.pop(require_clinician, None)


@pytest.fixture
def quota_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        quota, "check_and_consume",
        lambda identity, action, *, units=1, source_ip=None:
            calls.append({"identity": identity, "action": action, "units": units}),
    )
    return calls


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "azure_di_endpoint", FAKE_ENDPOINT)
    monkeypatch.setattr(settings, "azure_di_key", "test-key-123")


def _mock_azure(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(azure_ocr, "_client", lambda: httpx.Client(transport=transport))


# ---- gates & validation ----------------------------------------------------------

def test_requires_clinician(client):
    def _reject():
        raise HTTPException(status_code=401, detail="authentication required")
    app.dependency_overrides[require_clinician] = _reject
    r = client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert r.status_code == 401


def test_503_with_clear_message_when_unconfigured(client, quota_calls):
    r = client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert r.status_code == 503
    assert "AZURE_DI_ENDPOINT" in r.json()["detail"]


def test_invalid_base64_is_400(client, quota_calls):
    r = client.post(URL, json={"image_base64": "this is !!! not base64",
                               "mime_type": "image/png"})
    assert r.status_code == 400


def test_unsupported_mime_type_is_400(client, quota_calls):
    r = client.post(URL, json={"image_base64": PNG_B64,
                               "mime_type": "text/x-shellscript"})
    assert r.status_code == 400


def test_decoded_payload_over_8mb_is_413(client, quota_calls):
    big = base64.b64encode(b"\x00" * (8 * 1024 * 1024 + 64)).decode()
    r = client.post(URL, json={"image_base64": big, "mime_type": "image/png"})
    assert r.status_code == 413


def test_quota_limit_is_registered():
    assert "vision.ocr" in quota.LIMITS
    assert quota.LIMITS["vision.ocr"].per_hour > 0


def test_quota_is_consumed(client, quota_calls):
    client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert [c["action"] for c in quota_calls] == ["vision.ocr"]


# ---- the Azure DI submit/poll flow ------------------------------------------------

def test_happy_path_submit_poll_extracts_text(client, quota_calls, monkeypatch):
    _configure(monkeypatch)
    counts = {"post": 0, "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            counts["post"] += 1
            assert "prebuilt-read:analyze" in str(request.url)
            assert request.headers["ocp-apim-subscription-key"] == "test-key-123"
            assert request.headers["content-type"] == "image/png"
            return httpx.Response(202, headers={"operation-location": OP_URL})
        counts["get"] += 1
        if counts["get"] == 1:
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(200, json={
            "status": "succeeded",
            "analyzeResult": {"content": "RX: amoxicillin 500mg TID x7 days"},
        })

    _mock_azure(monkeypatch, handler)
    r = client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert r.status_code == 200
    assert r.json() == {"text": "RX: amoxicillin 500mg TID x7 days"}
    assert counts["post"] == 1
    assert counts["get"] == 2  # polled through 'running' to 'succeeded'


def test_429_then_5xx_submits_are_retried(client, quota_calls, monkeypatch):
    _configure(monkeypatch)
    counts = {"post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            counts["post"] += 1
            if counts["post"] == 1:
                return httpx.Response(429)
            if counts["post"] == 2:
                return httpx.Response(503)
            return httpx.Response(202, headers={"operation-location": OP_URL})
        return httpx.Response(200, json={"status": "succeeded",
                                         "analyzeResult": {"content": "ok"}})

    _mock_azure(monkeypatch, handler)
    r = client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert r.status_code == 200
    assert r.json() == {"text": "ok"}
    assert counts["post"] == 3  # two transient failures absorbed by retries


def test_retries_exhausted_is_502(client, quota_calls, monkeypatch):
    _configure(monkeypatch)
    counts = {"post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counts["post"] += 1
        return httpx.Response(500)

    _mock_azure(monkeypatch, handler)
    r = client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert r.status_code == 502
    assert counts["post"] == azure_ocr.SUBMIT_RETRIES + 1  # 1 try + 3 retries


def test_4xx_submit_is_not_retried(client, quota_calls, monkeypatch):
    _configure(monkeypatch)
    counts = {"post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counts["post"] += 1
        return httpx.Response(400, json={"error": {"message": "bad image"}})

    _mock_azure(monkeypatch, handler)
    r = client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert r.status_code == 502
    assert counts["post"] == 1  # a non-transient 4xx must not burn retries


def test_analysis_failed_status_is_502(client, quota_calls, monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"operation-location": OP_URL})
        return httpx.Response(200, json={"status": "failed",
                                         "error": {"message": "unreadable"}})

    _mock_azure(monkeypatch, handler)
    r = client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    assert r.status_code == 502


def test_data_url_prefix_is_tolerated(client, quota_calls, monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"operation-location": OP_URL})
        return httpx.Response(200, json={"status": "succeeded",
                                         "analyzeResult": {"content": "hello"}})

    _mock_azure(monkeypatch, handler)
    r = client.post(URL, json={"image_base64": f"data:image/png;base64,{PNG_B64}",
                               "mime_type": "image/png"})
    assert r.status_code == 200
    assert r.json()["text"] == "hello"


# ---- audit -----------------------------------------------------------------------

def test_vision_call_is_audited(client, quota_calls, monkeypatch):
    records = []
    monkeypatch.setattr("lib.audit.record", lambda **kw: records.append(kw))
    client.post(URL, json={"image_base64": PNG_B64, "mime_type": "image/png"})
    vision_records = [r for r in records if r["action"] == "vision.ocr"]
    assert len(vision_records) == 1
    assert vision_records[0]["extra"]["mime_type"] == "image/png"
    assert vision_records[0]["clinician_id"] == "tester"
