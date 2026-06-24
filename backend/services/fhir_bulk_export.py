"""FHIR Bulk Data ``$export`` (Flat FHIR / SMART Backend Services).

Implements the asynchronous bulk-export request flow from the HL7 FHIR Bulk
Data Access IG (https://hl7.org/fhir/uv/bulkdata/export.html):

    1. **kickoff**  — ``GET [base]/$export`` (system) | ``[base]/Group/{id}/$export``
       (group) | ``[base]/Patient/$export`` (all-patient) with
       ``Accept: application/fhir+json`` and ``Prefer: respond-async``. The server
       replies ``202 Accepted`` with a ``Content-Location`` status URL.
    2. **status poll** — ``GET <status_url>``. ``202`` while in progress (with an
       ``X-Progress`` / ``Retry-After`` hint), then ``200`` with a *Complete
       Status* manifest JSON listing one NDJSON file URL per resource type.
    3. **file retrieval** — ``GET <file_url>`` with ``Accept:
       application/fhir+ndjson``; one FHIR resource per line.

Auth is the **SMART Backend Services** profile
(https://hl7.org/fhir/smart-app-launch/backend-services.html): a confidential
client authenticates to the token endpoint with ``grant_type=client_credentials``
and a signed (RS384) ``private_key_jwt`` client assertion, reusing
``lib.smart_auth.build_client_assertion`` — no new crypto, no new dependency.

Layering / constitution:
  * ARCH-002 — this is a service: it imports ``lib.*`` and ``services.*`` only,
    never ``boto3``. All persisted job state goes through the router → db layer.
  * SEC-005 / COMP-001 — any free-text pulled out of an ingested resource that is
    destined for an AI provider is run through ``lib.content_guard.scan()`` via
    :func:`scan_resource_freetext` before it is surfaced to a caller that will
    forward it to Claude/Whisper/Polly. Bulk NDJSON is otherwise treated as
    opaque PHI and is never logged.
  * No PHI in logs — only counts, resource types, job ids, and status codes.

Base URLs / tokens are resolved from a hospital ``ehr_config`` dict (the same
shape ``services.ehr_gateway`` consumes), so the router never hard-codes a
vendor endpoint.

Testability: every network call goes through an injected ``http_client``
(an ``httpx.Client``). Tests pass one built on the in-repo mock FHIR server's
``httpx_transport()``; production passes a real ``httpx.Client``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from lib import content_guard, smart_auth

log = logging.getLogger(__name__)

# Bulk Data wire constants.
_ACCEPT_JSON = "application/fhir+json"
_ACCEPT_NDJSON = "application/fhir+ndjson"
_PREFER_ASYNC = "respond-async"
CLIENT_CREDENTIALS_GRANT = "client_credentials"

# Async polling bounds. The status loop is bounded so a stuck export cannot hang
# a request forever; the router exposes a single status poll for long jobs.
_DEFAULT_KICKOFF_TIMEOUT_S = 30.0
_DEFAULT_FILE_TIMEOUT_S = 60.0
_DEFAULT_TOKEN_TIMEOUT_S = 15.0
_DEFAULT_MAX_POLLS = 30
_DEFAULT_POLL_INTERVAL_S = 2.0
_POLL_INTERVAL_CAP_S = 10.0

# Export levels.
_LEVELS = {"system", "group", "patient"}


class BulkExportError(Exception):
    """Raised when a bulk-export step fails in a way the caller must handle."""

    def __init__(
        self,
        message: str,
        *,
        phase: str | None = None,
        status_code: int | None = None,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.phase = phase
        self.status_code = status_code
        self.transient = transient

    def __str__(self) -> str:
        bits = [self.message]
        if self.phase:
            bits.append(f"phase={self.phase}")
        if self.status_code is not None:
            bits.append(f"status={self.status_code}")
        return " | ".join(bits)


# --------------------------------------------------------------------------
# Config resolution (from a hospital ehr_config dict)
# --------------------------------------------------------------------------


@dataclass
class BackendServicesAuth:
    """Resolved SMART Backend Services client-credentials parameters."""

    token_url: str
    client_id: str
    private_key_pem: str
    scope: str = "system/*.read"
    kid: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token_url and self.client_id and self.private_key_pem)


def resolve_auth(ehr_config: dict[str, Any] | None) -> BackendServicesAuth | None:
    """Build :class:`BackendServicesAuth` from a hospital ``ehr_config`` dict.

    Reads the Backend Services block::

        ehr_config["backend_services"] = {
            "token_url":   "https://fhir.example/oauth2/token",
            "client_id":   "solace-backend",
            "private_key": "<RSA PEM>",        # PKCS#1 or PKCS#8
            "scope":       "system/*.read",    # optional
            "kid":         "...",              # optional JWK kid
        }

    Returns ``None`` when no Backend Services block is present — the caller then
    runs token-less against an open/mock server (the demo path).
    """
    cfg = (ehr_config or {}).get("backend_services") or {}
    if not cfg:
        return None
    return BackendServicesAuth(
        token_url=str(cfg.get("token_url", "")).strip(),
        client_id=str(cfg.get("client_id", "")).strip(),
        private_key_pem=str(cfg.get("private_key", "")).replace("\\n", "\n").strip(),
        scope=str(cfg.get("scope") or "system/*.read"),
        kid=(str(cfg["kid"]) if cfg.get("kid") else None),
    )


def resolve_base_url(ehr_config: dict[str, Any] | None) -> str:
    """The FHIR base URL for this hospital, trailing slash stripped."""
    base = ((ehr_config or {}).get("base_url") or "").strip()
    return base.rstrip("/")


def build_export_url(base_url: str, *, level: str, group_id: str | None = None) -> str:
    """Build the kickoff URL for a given export level.

    * ``system``  -> ``[base]/$export``
    * ``patient`` -> ``[base]/Patient/$export``
    * ``group``   -> ``[base]/Group/{group_id}/$export``
    """
    base = base_url.rstrip("/")
    if level == "system":
        return f"{base}/$export"
    if level == "patient":
        return f"{base}/Patient/$export"
    if level == "group":
        if not group_id:
            raise BulkExportError("group-level export requires a group_id", phase="kickoff")
        return f"{base}/Group/{group_id}/$export"
    raise BulkExportError(f"unknown export level '{level}'", phase="kickoff")


# --------------------------------------------------------------------------
# Backend Services token acquisition (client_credentials + private_key_jwt)
# --------------------------------------------------------------------------


def fetch_backend_services_token(
    auth: BackendServicesAuth,
    *,
    http_client: httpx.Client,
) -> str:
    """Run the SMART Backend Services client_credentials grant; return the token.

    Builds an RS384 ``private_key_jwt`` assertion (via ``lib.smart_auth``) and
    POSTs the client-credentials form to ``auth.token_url``. Raises
    :class:`BulkExportError` on any failure.
    """
    if not auth.configured:
        raise BulkExportError(
            "Backend Services auth is not fully configured (token_url/client_id/private_key)",
            phase="token",
        )
    try:
        assertion = smart_auth.build_client_assertion(
            client_id=auth.client_id,
            token_endpoint=auth.token_url,
            private_key_pem=auth.private_key_pem,
            kid=auth.kid,
        )
    except smart_auth.PrivateKeyJwtError as e:
        raise BulkExportError(
            f"could not sign client assertion: {e}", phase="token"
        ) from e

    form = {
        "grant_type": CLIENT_CREDENTIALS_GRANT,
        "scope": auth.scope,
        "client_assertion_type": smart_auth.CLIENT_ASSERTION_TYPE,
        "client_assertion": assertion,
    }
    try:
        resp = http_client.post(
            auth.token_url,
            data=form,
            headers={"Accept": "application/json"},
            timeout=_DEFAULT_TOKEN_TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        raise BulkExportError(f"token request transport error: {e}", phase="token", transient=True) from e
    if resp.status_code >= 400:
        raise BulkExportError(
            f"token endpoint returned {resp.status_code}",
            phase="token",
            status_code=resp.status_code,
            transient=resp.status_code in (429, 500, 502, 503, 504),
        )
    token = (resp.json() or {}).get("access_token", "")
    if not token:
        raise BulkExportError("token response missing access_token", phase="token")
    return str(token)


def _auth_header(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


# --------------------------------------------------------------------------
# Kickoff / status / file retrieval primitives
# --------------------------------------------------------------------------


def kickoff_export(
    base_url: str,
    *,
    level: str,
    group_id: str | None = None,
    http_client: httpx.Client,
    access_token: str | None = None,
    type_filter: list[str] | None = None,
    since: str | None = None,
) -> str:
    """Kick off an async ``$export``; return the status-polling URL.

    ``type_filter`` maps to ``_type`` and ``since`` to ``_since`` (ISO instant)
    per the IG. Raises :class:`BulkExportError` if the server does not return
    ``202`` with a ``Content-Location``.
    """
    if level not in _LEVELS:
        raise BulkExportError(f"unsupported export level '{level}'", phase="kickoff")
    url = build_export_url(base_url, level=level, group_id=group_id)
    params: dict[str, str] = {"_outputFormat": _ACCEPT_NDJSON}
    if type_filter:
        params["_type"] = ",".join(type_filter)
    if since:
        params["_since"] = since
    headers = {"Accept": _ACCEPT_JSON, "Prefer": _PREFER_ASYNC, **_auth_header(access_token)}
    try:
        resp = http_client.get(
            url, params=params, headers=headers, timeout=_DEFAULT_KICKOFF_TIMEOUT_S
        )
    except httpx.HTTPError as e:
        raise BulkExportError(f"kickoff transport error: {e}", phase="kickoff", transient=True) from e
    if resp.status_code != 202:
        raise BulkExportError(
            f"kickoff expected 202, got {resp.status_code}",
            phase="kickoff",
            status_code=resp.status_code,
            transient=resp.status_code in (429, 500, 502, 503, 504),
        )
    status_url = resp.headers.get("Content-Location") or resp.headers.get("content-location")
    if not status_url:
        raise BulkExportError("kickoff 202 missing Content-Location header", phase="kickoff")
    return status_url


@dataclass
class ExportStatus:
    """Result of one status poll."""

    done: bool
    manifest: dict[str, Any] | None = None
    retry_after_s: float | None = None
    progress: str | None = None


def poll_status_once(
    status_url: str,
    *,
    http_client: httpx.Client,
    access_token: str | None = None,
) -> ExportStatus:
    """Poll the status URL exactly once.

    ``202`` -> in progress (``done=False``); ``200`` -> complete with the
    *Complete Status* manifest. Any other code raises.
    """
    headers = {"Accept": _ACCEPT_JSON, **_auth_header(access_token)}
    try:
        resp = http_client.get(status_url, headers=headers, timeout=_DEFAULT_KICKOFF_TIMEOUT_S)
    except httpx.HTTPError as e:
        raise BulkExportError(f"status transport error: {e}", phase="status", transient=True) from e
    if resp.status_code == 202:
        retry = resp.headers.get("Retry-After")
        try:
            retry_s = float(retry) if retry else None
        except ValueError:
            retry_s = None
        return ExportStatus(
            done=False,
            retry_after_s=retry_s,
            progress=resp.headers.get("X-Progress"),
        )
    if resp.status_code == 200:
        try:
            manifest = resp.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise BulkExportError("status 200 had malformed manifest JSON", phase="status") from e
        return ExportStatus(done=True, manifest=manifest)
    raise BulkExportError(
        f"status poll returned {resp.status_code}",
        phase="status",
        status_code=resp.status_code,
        transient=resp.status_code in (429, 500, 502, 503, 504),
    )


def manifest_files(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Extract ``[{type, url}]`` entries from a Complete Status manifest."""
    out: list[dict[str, str]] = []
    for entry in (manifest or {}).get("output", []) or []:
        if isinstance(entry, dict) and entry.get("url"):
            out.append({"type": str(entry.get("type", "")), "url": str(entry["url"])})
    return out


def fetch_ndjson_resources(
    file_url: str,
    *,
    http_client: httpx.Client,
    access_token: str | None = None,
    max_resources: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch and parse one NDJSON file into a list of FHIR resource dicts.

    Skips blank lines and lines that are not valid JSON objects (a malformed
    line never aborts the whole file). ``max_resources`` caps how many lines
    are parsed (defense against unexpectedly huge files in a single request).
    """
    headers = {"Accept": _ACCEPT_NDJSON, **_auth_header(access_token)}
    try:
        resp = http_client.get(file_url, headers=headers, timeout=_DEFAULT_FILE_TIMEOUT_S)
    except httpx.HTTPError as e:
        raise BulkExportError(f"file transport error: {e}", phase="file", transient=True) from e
    if resp.status_code != 200:
        raise BulkExportError(
            f"file fetch returned {resp.status_code}",
            phase="file",
            status_code=resp.status_code,
            transient=resp.status_code in (429, 500, 502, 503, 504),
        )
    resources: list[dict[str, Any]] = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            log.warning("bulk file %s: skipped a non-JSON NDJSON line", _safe_url(file_url))
            continue
        if isinstance(obj, dict):
            resources.append(obj)
        if max_resources is not None and len(resources) >= max_resources:
            break
    return resources


def _safe_url(url: str) -> str:
    """A log-safe URL: path only, no query string (which can carry identifiers)."""
    return url.split("?", 1)[0]


# --------------------------------------------------------------------------
# Orchestration: kickoff -> poll-to-completion -> fetch all files
# --------------------------------------------------------------------------


@dataclass
class ExportResult:
    """Outcome of a full run_export()."""

    status_url: str
    manifest: dict[str, Any]
    resources_by_type: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    polls: int = 0
    file_count: int = 0

    @property
    def total_resources(self) -> int:
        return sum(len(v) for v in self.resources_by_type.values())


def run_export(
    ehr_config: dict[str, Any] | None,
    *,
    level: str = "system",
    group_id: str | None = None,
    type_filter: list[str] | None = None,
    since: str | None = None,
    http_client: httpx.Client,
    max_polls: int = _DEFAULT_MAX_POLLS,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    max_resources_per_file: int | None = None,
) -> ExportResult:
    """Run a bulk export end-to-end against a hospital's FHIR server.

    Resolves Backend Services auth from ``ehr_config`` (token-less when no
    Backend Services block is present, e.g. the open mock/demo server), kicks
    off the export, polls to completion (bounded by ``max_polls``), then fetches
    and parses every NDJSON file in the manifest.

    ``sleep`` is injectable so tests run without real delays. Raises
    :class:`BulkExportError` on any hard failure or if the poll budget is
    exhausted before completion.
    """
    base_url = resolve_base_url(ehr_config)
    if not base_url:
        raise BulkExportError("ehr_config has no base_url for bulk export", phase="kickoff")

    auth = resolve_auth(ehr_config)
    token: str | None = None
    if auth is not None:
        token = fetch_backend_services_token(auth, http_client=http_client)

    status_url = kickoff_export(
        base_url,
        level=level,
        group_id=group_id,
        http_client=http_client,
        access_token=token,
        type_filter=type_filter,
        since=since,
    )

    polls = 0
    manifest: dict[str, Any] | None = None
    while polls < max_polls:
        polls += 1
        status = poll_status_once(status_url, http_client=http_client, access_token=token)
        if status.done:
            manifest = status.manifest or {}
            break
        wait = status.retry_after_s if status.retry_after_s is not None else poll_interval_s
        sleep(min(max(0.0, wait), _POLL_INTERVAL_CAP_S))
    if manifest is None:
        raise BulkExportError(
            f"export did not complete within {max_polls} polls",
            phase="status",
            transient=True,
        )

    resources_by_type: dict[str, list[dict[str, Any]]] = {}
    files = manifest_files(manifest)
    for entry in files:
        rows = fetch_ndjson_resources(
            entry["url"],
            http_client=http_client,
            access_token=token,
            max_resources=max_resources_per_file,
        )
        rtype = entry["type"] or (rows[0].get("resourceType", "Resource") if rows else "Resource")
        resources_by_type.setdefault(rtype, []).extend(rows)

    log.info(
        "bulk export complete: level=%s polls=%d files=%d types=%s total=%d",
        level, polls, len(files), sorted(resources_by_type.keys()),
        sum(len(v) for v in resources_by_type.values()),
    )
    return ExportResult(
        status_url=status_url,
        manifest=manifest,
        resources_by_type=resources_by_type,
        polls=polls,
        file_count=len(files),
    )


# --------------------------------------------------------------------------
# SEC-005 / COMP-001 — content guard on ingested free-text
# --------------------------------------------------------------------------

# FHIR fields that commonly carry clinician/patient free-text. Any of these,
# when pulled out of an ingested resource for downstream AI use, must be scanned.
_FREETEXT_PATHS: tuple[tuple[str, ...], ...] = (
    ("note",),                 # list[Annotation]
    ("text", "div"),           # narrative
    ("code", "text"),
    ("valueString",),
    ("comment",),
    ("description",),
)


def _collect_freetext(resource: dict[str, Any]) -> list[str]:
    """Best-effort extraction of free-text strings from a FHIR resource."""
    out: list[str] = []

    def _add(v: Any) -> None:
        if isinstance(v, str) and v.strip():
            out.append(v)

    # Annotations: resource["note"] = [{"text": ...}, ...]
    notes = resource.get("note")
    if isinstance(notes, list):
        for n in notes:
            if isinstance(n, dict):
                _add(n.get("text"))
    # Narrative text.
    text = resource.get("text")
    if isinstance(text, dict):
        _add(text.get("div"))
    code = resource.get("code")
    if isinstance(code, dict):
        _add(code.get("text"))
    _add(resource.get("valueString"))
    _add(resource.get("comment"))
    _add(resource.get("description"))
    return out


def scan_resource_freetext(
    resource: dict[str, Any],
    *,
    label: str = "ehr_bulk_ingest",
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Run ``content_guard.scan()`` over every free-text field of a resource.

    SEC-005 / COMP-001: any ingested free-text that will flow toward an AI
    provider must be scanned first; unsafe text (prompt-injection patterns)
    causes ``safe=False`` so the caller drops the resource from the AI path.
    PII is redacted from the returned cleaned strings.

    Returns ``(safe, cleaned_texts, findings)``. ``cleaned_texts`` is the
    sanitized/redacted version of each scanned field, in order.
    """
    cleaned: list[str] = []
    findings: list[str] = []
    for raw in _collect_freetext(resource):
        safe, clean, hits = content_guard.scan(
            raw, label=label, source_ip=source_ip, user_agent=user_agent
        )
        findings.extend(hits)
        if not safe:
            return False, cleaned, findings
        cleaned.append(clean)
    return True, cleaned, findings


def scan_export_for_ai(
    result: ExportResult,
    *,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Scan all free-text in an export result before any AI hand-off.

    Returns a summary ``{safe_resources, rejected_resources, findings}``. Used
    by callers that intend to forward bulk-ingested content to an AI provider —
    they must consult this and drop the rejected resources. The bulk PHI itself
    is never returned here (no PHI in logs / summaries).
    """
    safe_count = 0
    rejected = 0
    all_findings: list[str] = []
    for rtype, rows in result.resources_by_type.items():
        for res in rows:
            safe, _cleaned, findings = scan_resource_freetext(
                res, label=f"ehr_bulk:{rtype}",
                source_ip=source_ip, user_agent=user_agent,
            )
            all_findings.extend(findings)
            if safe:
                safe_count += 1
            else:
                rejected += 1
    return {
        "safe_resources": safe_count,
        "rejected_resources": rejected,
        "findings": sorted(set(all_findings)),
    }
