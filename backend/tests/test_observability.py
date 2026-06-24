"""Tests for the per-request observability middleware (backend/lib/observability.py).

Verifies:
  * one CloudWatch EMF metric line is emitted per request with the expected
    dimensions (hospital_id, route template, method, status_class) and metrics
    (latency_ms, error);
  * the route TEMPLATE is emitted, never the resolved path — so a request whose
    URL contains a patient_id UUID never leaks that UUID, a token, or any other
    PHI into the metric payload;
  * the optional OTel/X-Ray trace hook is a complete no-op unless explicitly
    enabled (DEPS-003).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Make `lib.*` / `main` importable the same way the running app does. The
# top-level tests rely on backend/ being on sys.path.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib import observability  # noqa: E402
from lib.observability import (  # noqa: E402
    ObservabilityMiddleware,
    build_emf_payload,
    _safe_hospital_id,
    set_trace_hook,
)


# A representative patient_id UUID + a fake bearer token we will make sure
# never show up in any emitted metric line.
_PATIENT_ID = "fbc01b0a-1111-2222-3333-444455556666"
_FAKE_TOKEN = "Bearer abcdef0123456789supersecrettoken"
_TRANSCRIPT = "patient reports crushing chest pain radiating to left arm"


def _make_app() -> FastAPI:
    """A tiny app mirroring Solace's per-hospital + per-patient route shape."""
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware)

    @app.get("/api/{hospital_id}/patients/{patient_id}")
    def get_patient(hospital_id: str, patient_id: str):
        return {"ok": True}

    @app.post("/api/{hospital_id}/patients/{patient_id}/refine-triage")
    def refine(hospital_id: str, patient_id: str, request: Request):
        # A route opting into the model_source dimension.
        request.state.model_source = "trained_ensemble"
        return {"esi_level": 3}

    @app.get("/api/{hospital_id}/boom")
    def boom(hospital_id: str):
        raise RuntimeError("kaboom")

    return app


def _capture_metrics(caplog) -> list[dict]:
    """Parse every EMF JSON line emitted on the solace.metrics logger."""
    out: list[dict] = []
    for rec in caplog.records:
        if rec.name != "solace.metrics":
            continue
        try:
            out.append(json.loads(rec.getMessage()))
        except (ValueError, TypeError):
            continue
    return out


def test_emits_one_metric_with_expected_dimensions(caplog):
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="solace.metrics"):
        resp = client.get(f"/api/demo/patients/{_PATIENT_ID}")
    assert resp.status_code == 200

    metrics = _capture_metrics(caplog)
    assert len(metrics) == 1, f"expected exactly one metric line, got {len(metrics)}"
    m = metrics[0]

    # Dimensions
    assert m["hospital_id"] == "demo"
    assert m["route"] == "/api/{hospital_id}/patients/{patient_id}"
    assert m["method"] == "GET"
    assert m["status_class"] == "2xx"
    # Metrics
    assert isinstance(m["latency_ms"], (int, float))
    assert m["latency_ms"] >= 0
    assert m["error"] == 0
    # EMF structure
    assert m["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Solace/API"
    metric_names = {x["Name"] for x in m["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert metric_names == {"latency_ms", "error"}


def test_no_patient_id_or_phi_in_payload(caplog):
    """The core SEC-002 guarantee: a path containing a patient_id UUID, a
    bearer token, and transcript-like query data emits ZERO of those in the
    metric payload."""
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="solace.metrics"):
        resp = client.get(
            f"/api/demo/patients/{_PATIENT_ID}",
            params={"note": _TRANSCRIPT},
            headers={"Authorization": _FAKE_TOKEN},
        )
    assert resp.status_code == 200

    metrics = _capture_metrics(caplog)
    assert len(metrics) == 1
    raw = json.dumps(metrics[0])

    # No patient_id UUID, no bearer token, no transcript text, no query string.
    assert _PATIENT_ID not in raw
    assert "abcdef0123456789supersecrettoken" not in raw
    assert "Bearer" not in raw
    assert "chest pain" not in raw
    assert "note" not in raw
    # The template placeholder IS present (proves we emit the template, not path).
    assert "{patient_id}" in raw


def test_5xx_marks_error_and_still_emits(caplog):
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="solace.metrics"):
        resp = client.get("/api/demo/boom")
    assert resp.status_code == 500

    metrics = _capture_metrics(caplog)
    assert len(metrics) == 1
    m = metrics[0]
    assert m["status_class"] == "5xx"
    assert m["error"] == 1
    assert m["hospital_id"] == "demo"
    assert m["route"] == "/api/{hospital_id}/boom"


def test_model_source_dimension_when_set(caplog):
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="solace.metrics"):
        resp = client.post(f"/api/demo/patients/{_PATIENT_ID}/refine-triage")
    assert resp.status_code == 200

    metrics = _capture_metrics(caplog)
    assert len(metrics) == 1
    m = metrics[0]
    assert m["model_source"] == "trained_ensemble"
    assert m["route"] == "/api/{hospital_id}/patients/{patient_id}/refine-triage"
    assert _PATIENT_ID not in json.dumps(m)


def test_unmatched_route_emits_coarse_phi_free_shape(caplog):
    """A 404 (no matched route) must still emit a parameter-free path shape so
    a raw URL with a UUID never leaks via the 404 path."""
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="solace.metrics"):
        resp = client.get(f"/api/demo/unknown/{_PATIENT_ID}/secret")
    assert resp.status_code == 404

    metrics = _capture_metrics(caplog)
    assert len(metrics) == 1
    m = metrics[0]
    assert m["status_class"] == "4xx"
    assert _PATIENT_ID not in json.dumps(m)
    assert m["route"] == "/api/{hospital_id}/*"


def test_safe_hospital_id_redacts_uuid():
    """A UUID in the hospital_id slot is redacted, never emitted as-is."""
    assert _safe_hospital_id("/api/demo/patients/x") == "demo"
    assert _safe_hospital_id(f"/api/{_PATIENT_ID}/patients/x") == "redacted"
    assert _safe_hospital_id("/health") == "none"
    assert _safe_hospital_id("/api/Mercy-General_01/x") == "Mercy-General_01"


def test_build_emf_payload_is_phi_free_pure_fn():
    payload = build_emf_payload(
        hospital_id="demo",
        route_template="/api/{hospital_id}/patients/{patient_id}",
        method="GET",
        status_code=200,
        latency_ms=12.34,
        error=0,
        model_source="bedrock",
    )
    raw = json.dumps(payload)
    assert _PATIENT_ID not in raw
    assert payload["hospital_id"] == "demo"
    assert payload["model_source"] == "bedrock"
    assert payload["latency_ms"] == 12.34
    assert payload["error"] == 0


def test_trace_hook_is_noop_unless_enabled(caplog, monkeypatch):
    """DEPS-003: the OTel/X-Ray hook must be a complete no-op unless explicitly
    enabled via env AND registered. No heavy SDK is ever imported."""
    calls: list[dict] = []

    def hook(span):
        calls.append(span)

    set_trace_hook(hook)
    try:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Tracing NOT enabled -> hook must not fire.
        monkeypatch.delenv("SOLACE_TRACING_ENABLED", raising=False)
        client.get(f"/api/demo/patients/{_PATIENT_ID}")
        assert calls == []

        # Tracing enabled -> hook fires, but the span carries NO patient_id.
        monkeypatch.setenv("SOLACE_TRACING_ENABLED", "true")
        client.get(f"/api/demo/patients/{_PATIENT_ID}")
        assert len(calls) == 1
        assert _PATIENT_ID not in json.dumps(calls[0])
        assert calls[0]["route"] == "/api/{hospital_id}/patients/{patient_id}"
    finally:
        set_trace_hook(None)


def test_no_otel_or_xray_sdk_imported():
    """Guard DEPS-003: importing observability must not pull in opentelemetry
    or aws_xray_sdk."""
    # observability is already imported at module top; assert the heavy SDKs
    # are absent from sys.modules as a result of our import.
    assert "opentelemetry" not in sys.modules
    assert "aws_xray_sdk" not in sys.modules


def test_app_import_order_preserved():
    """SEC-002 / PERF-002 regression guard: importing the real app must keep the
    redaction filter installed and the warmup handler intact, with our
    middleware wired in."""
    from main import app, handler  # noqa: PLC0415
    import logging as _logging  # noqa: PLC0415
    from lib.log_redaction import RedactPatientUUIDsFilter  # noqa: PLC0415

    # Redaction filter still on the root logger.
    root = _logging.getLogger("")
    assert any(isinstance(f, RedactPatientUUIDsFilter) for f in root.filters)

    # Our middleware is registered on the app.
    assert any(
        getattr(m, "cls", None) is ObservabilityMiddleware for m in app.user_middleware
    ), "ObservabilityMiddleware not wired into the app"

    # Warmup handler still pre-loads + dry-predicts (returns 200 + warm marker).
    resp = handler({"warmup": True}, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["warm"] is True
