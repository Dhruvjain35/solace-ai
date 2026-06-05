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
        # Seeded read store: resource_type -> [resource, ...]. GET searches
        # return these as a FHIR Bundle (drives the USCDI read path tests).
        self.store: dict[str, list[dict[str, Any]]] = {}

        # --- Bulk Data ($export) state ------------------------------------
        # One mock async job per kickoff. ``poll_until_done`` controls how many
        # 202 (in-progress) status polls precede the 200 manifest, so tests can
        # exercise the poll loop without real sleeping.
        self._bulk_jobs: dict[str, dict[str, Any]] = {}
        self._bulk_counter = 0
        self.poll_until_done = 0  # number of in-progress polls before completion
        # NDJSON payloads keyed by resource type the next export will expose.
        self.export_ndjson: dict[str, str] = {}
        # Optional hard failure injected at status-poll time.
        self.export_status_error: int | None = None

    # -- configuration -------------------------------------------------------
    def fail(self, resource_type: str, status: int) -> None:
        self.error_for[resource_type] = status

    def fail_next(self, status: int) -> None:
        self.error_once = status

    def seed(self, resource_type: str, resources: list[dict[str, Any]]) -> None:
        """Seed resources a GET search of `resource_type` will return.

        Used by the USCDI read-path tests: ``seed("Condition", [...])`` makes a
        ``GET {base}/Condition?patient=...`` return those resources in a Bundle.
        """
        self.store.setdefault(resource_type, []).extend(resources)

    def reset(self) -> None:
        self.requests.clear()
        self.error_for.clear()
        self.error_once = None
        self._id_counter = 0
        self.store.clear()

    # -- introspection -------------------------------------------------------
    @property
    def post_count(self) -> int:
        return sum(1 for r in self.requests if r.method == "POST")

    def last(self) -> RecordedRequest:
        return self.requests[-1]

    def of_type(self, resource_type: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.resource_type == resource_type]

    # -- bulk data ($export) configuration -----------------------------------
    def program_export(self, ndjson_by_type: dict[str, str],
                       *, poll_until_done: int = 0) -> None:
        """Program the NDJSON the next ``$export`` will expose.

        ``ndjson_by_type`` maps a FHIR resource type to its raw NDJSON text
        (one JSON resource per line). ``poll_until_done`` is how many status
        polls return 202 (in-progress) before the 200 manifest appears.
        """
        self.export_ndjson = dict(ndjson_by_type)
        self.poll_until_done = max(0, int(poll_until_done))

    # -- core handler --------------------------------------------------------
    def _handle(self, method: str, url: str, body: dict[str, Any],
                headers: dict[str, str]) -> tuple[int, dict[str, str], dict[str, Any]]:
        # OAuth2 token endpoints (e.g. athenahealth /oauth2/v1/token, or the
        # SMART Backend Services client_credentials grant) return a bearer token.
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
                "expires_in": 3600, "scope": "system/*.read",
            }

        # --- Bulk Data $export kickoff (GET ...$export) -------------------
        # Flat FHIR async pattern: 202 Accepted + a Content-Location header
        # pointing at the status polling URL.
        clean_url = url.split("?", 1)[0].rstrip("/")
        if method == "GET" and clean_url.endswith("$export"):
            self.requests.append(RecordedRequest(
                method=method, url=url, resource_type="$export",
                body={}, headers=dict(headers),
            ))
            if self.error_once is not None:
                status, self.error_once = self.error_once, None
                return status, {"Content-Type": "application/fhir+json"}, \
                    _OPERATION_OUTCOMES.get(status, {
                        "resourceType": "OperationOutcome",
                        "issue": [{"severity": "error", "code": "exception",
                                   "diagnostics": f"HTTP {status}"}]})
            self._bulk_counter += 1
            job_id = f"bulk-{self._bulk_counter}"
            self._bulk_jobs[job_id] = {
                "polls_remaining": self.poll_until_done,
                "ndjson": dict(self.export_ndjson),
            }
            status_url = f"{self.base_url}/_bulk/status/{job_id}"
            return 202, {"Content-Location": status_url}, {}

        # --- Bulk Data status poll ----------------------------------------
        if method == "GET" and "/_bulk/status/" in clean_url:
            job_id = clean_url.rsplit("/", 1)[-1]
            self.requests.append(RecordedRequest(
                method=method, url=url, resource_type="$export-status",
                body={}, headers=dict(headers),
            ))
            if self.export_status_error is not None:
                status, self.export_status_error = self.export_status_error, None
                return status, {"Content-Type": "application/fhir+json"}, \
                    _OPERATION_OUTCOMES.get(status, {
                        "resourceType": "OperationOutcome",
                        "issue": [{"severity": "error", "code": "exception",
                                   "diagnostics": f"HTTP {status}"}]})
            job = self._bulk_jobs.get(job_id)
            if job is None:
                return 404, {"Content-Type": "application/fhir+json"}, {
                    "resourceType": "OperationOutcome",
                    "issue": [{"severity": "error", "code": "not-found",
                               "diagnostics": "Unknown bulk job."}]}
            if job["polls_remaining"] > 0:
                job["polls_remaining"] -= 1
                return 202, {"X-Progress": "in-progress", "Retry-After": "1"}, {}
            output = []
            for rtype in job["ndjson"]:
                output.append({
                    "type": rtype,
                    "url": f"{self.base_url}/_bulk/file/{job_id}/{rtype}",
                })
            manifest = {
                "transactionTime": "2026-05-16T00:00:00Z",
                "request": url,
                "requiresAccessToken": True,
                "output": output,
                "error": [],
            }
            return 200, {"Content-Type": "application/json"}, manifest

        # --- Bulk Data NDJSON file retrieval ------------------------------
        if method == "GET" and "/_bulk/file/" in clean_url:
            parts = clean_url.rsplit("/", 2)  # .../<job_id>/<rtype>
            job_id, rtype = parts[-2], parts[-1]
            self.requests.append(RecordedRequest(
                method=method, url=url, resource_type=f"$export-file:{rtype}",
                body={}, headers=dict(headers),
            ))
            job = self._bulk_jobs.get(job_id) or {"ndjson": {}}
            ndjson_text = job["ndjson"].get(rtype, "")
            return 200, {"Content-Type": "application/fhir+ndjson"}, ndjson_text

        # GET = a FHIR search; return a Bundle of seeded resources (USCDI reads).
        # Generic catch-all AFTER the bulk-specific GET handlers above.
        if method == "GET":
            return self._handle_search(url, headers)

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

    # -- search (GET) handler ------------------------------------------------
    def _handle_search(self, url: str, headers: dict[str, str]
                       ) -> tuple[int, dict[str, str], dict[str, Any]]:
        """Serve a FHIR search as a searchset Bundle of seeded resources.

        The resource type is the last path segment before the query string;
        ``category=`` (Observation) filters by the seeded resource's category
        code. Honors the same ``error_for`` / ``error_once`` knobs as writes.
        """
        from urllib.parse import urlsplit, parse_qs

        parts = urlsplit(url)
        resource_type = parts.path.rstrip("/").rsplit("/", 1)[-1]
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.requests.append(RecordedRequest(
            method="GET", url=url, resource_type=resource_type,
            body={"_params": params}, headers=dict(headers),
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

        resources = list(self.store.get(resource_type, []))
        category = params.get("category")
        if category and resource_type == "Observation":
            resources = [
                r for r in resources
                if any(
                    coding.get("code") == category
                    for cat in (r.get("category") or [])
                    for coding in (cat.get("coding") or [])
                )
            ]
        bundle = {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": len(resources),
            "entry": [{"resource": r} for r in resources],
        }
        return 200, {"Content-Type": "application/fhir+json"}, bundle

    # -- httpx transport face ------------------------------------------------
    def httpx_transport(self) -> httpx.MockTransport:
        def _responder(request: httpx.Request) -> httpx.Response:
            try:
                body = json.loads(request.content.decode("utf-8")) if request.content else {}
            except (ValueError, UnicodeDecodeError):
                # Token requests are form-encoded, not JSON — body stays {}.
                body = {}
            status, headers, payload = self._handle(
                request.method, str(request.url), body, dict(request.headers))
            # NDJSON file payloads come back as a raw string, not a JSON object.
            if isinstance(payload, str):
                return httpx.Response(status, headers=headers, text=payload)
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

    def get(self, url: str, *, params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None,
            timeout: float | None = None, **_: Any) -> FakeResponse:
        # Fold query params into the URL so the search handler sees them.
        if params:
            from urllib.parse import urlencode
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode(params)}"
        status, resp_headers, payload = self.server._handle(
            "GET", url, {}, headers or {})
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
