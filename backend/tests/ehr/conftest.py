"""Pytest fixtures for the offline EHR write-back harness.

Adds ``backend/`` to ``sys.path`` so ``services.fhir_writer`` and the optional
``services.ehr_*`` adapters import the same way they do under the running app.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# backend/tests/ehr/conftest.py -> parents[2] == backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_FIXTURE_DIR = Path(__file__).parent / "fixtures"

from tests.ehr.mock_fhir_server import (  # noqa: E402
    InjectableHTTPClient,
    MockFHIRServer,
)


@pytest.fixture
def fixture_dir() -> Path:
    """Directory holding the FHIR R4 JSON fixtures."""
    return _FIXTURE_DIR


@pytest.fixture
def load_fixture():
    """Return a loader: ``load_fixture('patient')`` -> parsed dict."""
    def _load(name: str) -> dict:
        path = _FIXTURE_DIR / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def mock_fhir() -> MockFHIRServer:
    """A fresh recording mock FHIR server per test."""
    return MockFHIRServer()


@pytest.fixture
def fake_requests(mock_fhir, monkeypatch):
    """Inject a fake ``requests`` module backed by the mock FHIR server.

    Yields the ``MockFHIRServer`` so the test can program errors and inspect
    captured POSTs. ``monkeypatch`` restores ``sys.modules`` afterward.
    """
    fake = mock_fhir.as_requests_module()
    monkeypatch.setitem(sys.modules, "requests", fake)
    return mock_fhir


@pytest.fixture
def injectable_client(mock_fhir) -> InjectableHTTPClient:
    """An injectable fake HTTP client backed by the mock FHIR server.

    Suitable for adapters that accept an ``http_client=`` argument
    (EpicAdapter, OracleEHRClient, AthenaWriteClient).
    """
    return InjectableHTTPClient(mock_fhir)
