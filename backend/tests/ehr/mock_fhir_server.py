"""Offline mock FHIR R4 server for EHR write-back tests.

Records every POSTed resource and replies with a configurable status. Two
transport faces are provided so the same recording core serves both code
paths in ``backend/services/fhir_writer.py``:

  * ``FakeRequestsModule`` — a drop-in stand-in for the ``requests`` package
    that ``fhir_writer.write()`` imports lazily on its remote branch. Inject it
    via ``sys.modules['requests']`` before calling ``write()``.

  * ``httpx_transport()`` — an ``httpx.MockTransport`` wired to the same core,
    for any code that talks FHIR over httpx.

The server is deliberately dependency-free (no ``responses`` / ``requests``
needed). It validates nothing beyond what a test explicitly programs via the
``error_for`` / ``error_once`` knobs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

# Canonical OperationOutcome bodies keyed by HTTP status.
_OPERATION_OUTCOMES: dict[int, dict[str, Any]] = {
    401: {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": "security",
                   "diagnostics": "Authorization required."}],
    },
    409: {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": "conflict",
                   "diagnostics": "Resource version conflict."}],
    },
    422: {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": "invariant",
                   "diagnostics": "Resource failed FHIR R4 validation."}],
    },
}


@dataclass
class RecordedRequest:
    """One captured POST against the mock FHIR server."""
    method: str
    url: str
    resource_type: str
    body: dict[str, Any]
    headers: dict[str, str]


class MockFHIRServer:
    """Recording core shared by both transport faces.

    Knobs:
      * ``error_for[resource_type] = status`` — always fail that type.
      * ``error_once = status`` — fail the very next request, then clear.
    """

    def __init__(self, base_url: str = "https://mock-fhir.test/r4") -> None:
        self.base_url = base_url.rstrip("/")
        self.requests: list[RecordedRequest] = []
        self.error_for: dict[str, int] = {}
        self.error_once: int | None = None
        self._id_counter = 0

    # -- configuration -------------------------------------------------------
    def fail(self, resource_type: str, status: int) -> None:
        self.error_for[resource_type] = status

    def fail_next(self, status: int) -> None:
        self.error_once = status

    def reset(self) -> None:
        self.requests.clear()
        self.error_for.clear()
        self.error_once = None
        self._id_counter = 0

    # -- introspection -------------------------------------------------------
    @property
    def post_count(self) -> int:
        return sum(1 for r in self.requests if r.method == "POST")

    def last(self) -> RecordedRequest:
        return self.requests[-1]

    def of_type(self, resource_type: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.resource_type == resource_type]

    # -- core handler --------------------------------------------------------
    def _handle(self, method: str, url: str, body: dict[str, Any],
                headers: dict[str, str]) -> tuple[int, dict[str, str], dict[str, Any]]:
        # OAuth2 token endpoints (e.g. athenahealth /oauth2/v1/token) return a
        # bearer token rather than a FHIR resource.
        if url.rstrip("/").endswith("/token"):
            self.requests.append(RecordedRequest(
                method=method, url=url, resource_type="_token",
                body=body or {}, headers=dict(headers),
            ))
            if self.error_once is not None:
                status, self.error_once = self.error_once, None
                return status, {"Content-Type": "application/json"}, {
                    "error": "invalid_client"}
            return 200, {"Content-Type": "application/json"}, {
                "access_token": "mock-access-token", "token_type": "bearer",
                "expires_in": 3600,
            }

        resource_type = (body or {}).get("resourceType") or url.rstrip("/").rsplit("/", 1)[-1]
        self.requests.append(RecordedRequest(
            method=method, url=url, resource_type=resource_type,
            body=body or {}, headers=dict(headers),
        ))

        status: int | None = None
        if self.error_once is not None:
            status, self.error_once = self.error_once, None
        elif resource_type in self.error_for:
            status = self.error_for[resource_type]

        if status is not None:
            outcome = _OPERATION_OUTCOMES.get(status, {
                "resourceType": "OperationOutcome",
                "issue": [{"severity": "error", "code": "exception",
                           "diagnostics": f"HTTP {status}"}],
            })
            return status, {"Content-Type": "application/fhir+json"}, outcome

        self._id_counter += 1
        new_id = f"{resource_type.lower()}-{self._id_counter}"
        created = dict(body or {})
        created["id"] = new_id
        created.setdefault("meta", {})["lastUpdated"] = "2026-05-16T00:00:00Z"
        location = f"{self.base_url}/{resource_type}/{new_id}/_history/1"
        return 201, {
            "Content-Type": "application/fhir+json",
            "Location": location,
            "ETag": 'W/"1"',
        }, created

    # -- httpx transport face ------------------------------------------------
    def httpx_transport(self) -> httpx.MockTransport:
        def _responder(request: httpx.Request) -> httpx.Response:
            try:
                body = json.loads(request.content.decode("utf-8")) if request.content else {}
            except (ValueError, UnicodeDecodeError):
                body = {}
            status, headers, payload = self._handle(
                request.method, str(request.url), body, dict(request.headers))
            return httpx.Response(status, headers=headers, json=payload)
        return httpx.MockTransport(_responder)

    # -- fake-requests face --------------------------------------------------
    def as_requests_module(self) -> "FakeRequestsModule":
        return FakeRequestsModule(self)


class _FakeHTTPError(Exception):
    """Stand-in for ``requests.exceptions.HTTPError``."""

    def __init__(self, message: str, response: "FakeResponse") -> None:
        super().__init__(message)
        self.response = response


class FakeResponse:
    """Minimal ``requests.Response`` look-alike."""

    def __init__(self, status_code: int, headers: dict[str, str],
                 payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self.headers = headers
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _FakeHTTPError(
                f"{self.status_code} Error for FHIR write", response=self)


class _FakeExceptions:
    """Namespace mimicking ``requests.exceptions``."""
    HTTPError = _FakeHTTPError
    RequestException = Exception


class InjectableHTTPClient:
    """A fake HTTP client for adapters that accept an injected client.

    Satisfies the structural contract used by ``EpicAdapter`` /
    ``OracleEHRClient`` (``post(url, *, headers, json, timeout)``) and the
    ``ehr_athena.HttpClient`` Protocol (``post`` / ``put`` returning an object
    with ``.status_code``, ``.text``, ``.json()`` and ``.ok``). Backed by the
    same :class:`MockFHIRServer` recording core.
    """

    def __init__(self, server: MockFHIRServer) -> None:
        self.server = server

    def post(self, url: str, *, headers: dict[str, str] | None = None,
             json: dict[str, Any] | None = None,
             data: dict[str, str] | None = None,
             timeout: float | None = None, **_: Any) -> FakeResponse:
        body = json if json is not None else (data or {})
        status, resp_headers, payload = self.server._handle(
            "POST", url, body if isinstance(body, dict) else {}, headers or {})
        return FakeResponse(status, resp_headers, payload)

    def put(self, url: str, *, headers: dict[str, str] | None = None,
            json: dict[str, Any] | None = None,
            timeout: float | None = None, **_: Any) -> FakeResponse:
        status, resp_headers, payload = self.server._handle(
            "PUT", url, json or {}, headers or {})
        return FakeResponse(status, resp_headers, payload)


@dataclass
class FakeRequestsModule:
    """Drop-in replacement for the ``requests`` package.

    Inject via ``sys.modules['requests'] = server.as_requests_module()`` so the
    lazy ``import requests`` inside ``fhir_writer.write()`` resolves to this.
    """

    server: MockFHIRServer
    exceptions: _FakeExceptions = field(default_factory=_FakeExceptions)
    HTTPError: type = _FakeHTTPError

    def post(self, url: str, *, headers: dict[str, str] | None = None,
             json: dict[str, Any] | None = None, timeout: float | None = None,
             **_: Any) -> FakeResponse:
        status, resp_headers, payload = self.server._handle(
            "POST", url, json or {}, headers or {})
        return FakeResponse(status, resp_headers, payload)

    def get(self, url: str, *, headers: dict[str, str] | None = None,
            timeout: float | None = None, **_: Any) -> FakeResponse:
        status, resp_headers, payload = self.server._handle(
            "GET", url, {}, headers or {})
        return FakeResponse(status, resp_headers, payload)
