"""Lightweight per-request observability for Solace on Lambda.

Emits ONE structured CloudWatch EMF (Embedded Metric Format) JSON line per
request to stdout via ``logging``. CloudWatch automatically extracts the
declared metrics (latency_ms, error) dimensioned by hospital_id, route,
method, and status_class — no AWS SDK, no boto3, no OTel/X-Ray dependency.

Constitution alignment:
  * SEC-002 — NEVER emit patient UUIDs / PHI. We dimension by ``hospital_id``
    (a non-PHI tenant id pulled ONLY from the ``/api/{hospital_id}/...`` path
    segment) and by the *route template* (``/api/{hospital_id}/patients/{patient_id}``),
    never the resolved path that contains the patient_id. We never log tokens,
    transcripts, request bodies, or query strings.
  * ARCH-002 — no boto3 here. Metrics ship via stdout EMF; Lambda forwards
    stdout to CloudWatch Logs and the EMF parser turns it into metrics.
  * DEPS-003 — no OTel / X-Ray SDK is imported unconditionally. The optional
    tracing hook is a complete no-op unless an explicitly-provided hook is set
    AND ``SOLACE_TRACING_ENABLED`` is truthy; we never import a heavy SDK.
  * QUAL-006 — uses ``logging``, never ``print``.

The middleware is intentionally defensive: instrumentation must never break a
request. Any failure in metric emission is swallowed (logged at debug) so a
500 in the observability path can't take down a clinical endpoint.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Dedicated logger. The SEC-002 redaction filter is attached to the root logger
# (name "") in log_redaction.install(), so any record from this child logger is
# still scrubbed of UUIDs/Bearer/nonce as a belt-and-suspenders backstop — but
# we are careful never to put PHI in the payload in the first place.
log = logging.getLogger("solace.metrics")

_METRIC_NAMESPACE = "Solace/API"

# Pull the hospital_id (tenant id) from the FIRST segment after /api/.
# Tenant ids are non-PHI account identifiers (e.g. "demo", a slug, or a short
# id). We deliberately do NOT use this for the patient_id segment which lives
# deeper in the path.
_HOSPITAL_RX = re.compile(r"^/api/(?P<hospital_id>[^/]+)")

# A hospital_id we are willing to emit must look like a tenant slug/id, never a
# UUID (which could be mistaken for or correlated to a record pointer) and
# never something with PHI-ish length. Conservative allow-list shape.
_SAFE_HOSPITAL_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_UUID_RX = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _safe_hospital_id(path: str) -> str:
    """Extract a PHI-free tenant id from the path, or 'none'/'redacted'.

    Only the ``/api/{hospital_id}/...`` segment is considered. If it doesn't
    look like a safe tenant slug (e.g. it's a UUID), we redact it rather than
    risk emitting a record pointer as a metric dimension.
    """
    m = _HOSPITAL_RX.match(path or "")
    if not m:
        return "none"
    hid = m.group("hospital_id")
    if _UUID_RX.match(hid) or not _SAFE_HOSPITAL_RX.match(hid):
        return "redacted"
    return hid


def _route_template(request: Request) -> str:
    """Return the parameterized route template, never the resolved path.

    e.g. ``/api/{hospital_id}/patients/{patient_id}`` — the ``{patient_id}``
    placeholder is left as a literal template token, so no patient id is ever
    emitted. Falls back to a coarse, PHI-free shape if no route matched (404).
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None) or getattr(route, "path_format", None)
    if template:
        return template
    # No matched route (e.g. 404). Emit a coarse, parameter-free shape so we
    # never leak the raw path. Keep only the first two static segments.
    raw = request.scope.get("path", "") or "/"
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return "/"
    # /api/<tenant>/... -> "/api/{hospital_id}/*" ; otherwise "/<seg0>/*"
    if parts[0] == "api":
        return "/api/{hospital_id}/*" if len(parts) > 1 else "/api"
    return f"/{parts[0]}/*" if len(parts) > 1 else f"/{parts[0]}"


def _status_class(status_code: int) -> str:
    """Bucket a status code into 2xx/3xx/4xx/5xx for low-cardinality metrics."""
    try:
        return f"{status_code // 100}xx"
    except Exception:  # noqa: BLE001 — never break on a weird status
        return "unknown"


def _model_source(request: Request, response: Response) -> Optional[str]:
    """Read a non-PHI model-source tag if a route chose to set one.

    Routes may set ``request.state.model_source`` (e.g. "trained_ensemble",
    "clinical_simulation", "bedrock") to dimension by which inference path ran.
    We only accept a short, alphanumeric token — anything else is dropped to
    avoid accidental PHI / high cardinality.
    """
    src = getattr(request.state, "model_source", None)
    if src is None:
        # Allow the response header form too (some handlers prefer headers).
        src = response.headers.get("X-Model-Source")
    if not isinstance(src, str):
        return None
    src = src.strip()
    if not src or len(src) > 40 or not re.match(r"^[A-Za-z0-9._-]+$", src):
        return None
    return src


# ---------------------------------------------------------------------------
# Optional, dependency-free tracing hook (OTel / X-Ray).
# ---------------------------------------------------------------------------
# We NEVER import opentelemetry or aws_xray_sdk here (DEPS-003). Instead, a
# caller may register a hook callable. The hook only fires when tracing is
# explicitly enabled via env AND a hook was registered — otherwise it is a
# complete no-op. This keeps the Lambda image dependency-free by default.

_TraceHook = Callable[[dict[str, Any]], None]
_trace_hook: Optional[_TraceHook] = None


def set_trace_hook(hook: Optional[_TraceHook]) -> None:
    """Register (or clear) an opt-in tracing hook. No SDK is imported here."""
    global _trace_hook
    _trace_hook = hook


def _tracing_enabled() -> bool:
    return os.environ.get("SOLACE_TRACING_ENABLED", "").lower() in {"1", "true", "yes", "on"}


def _maybe_trace(span: dict[str, Any]) -> None:
    """Invoke the opt-in trace hook if present and enabled. Never raises."""
    hook = _trace_hook
    if hook is None or not _tracing_enabled():
        return
    try:
        hook(span)
    except Exception:  # noqa: BLE001 — tracing must never break a request
        log.debug("trace hook failed", exc_info=True)


def _emit(payload: dict[str, Any]) -> None:
    """Write one EMF JSON line to stdout via logging. Never raises."""
    try:
        log.info(json.dumps(payload, separators=(",", ":")))
    except Exception:  # noqa: BLE001 — instrumentation must never break a request
        log.debug("metric emit failed", exc_info=True)


def build_emf_payload(
    *,
    hospital_id: str,
    route_template: str,
    method: str,
    status_code: int,
    latency_ms: float,
    error: int,
    model_source: Optional[str] = None,
) -> dict[str, Any]:
    """Build a CloudWatch EMF-format payload. Pure function — easy to unit-test.

    EMF spec: a JSON object with an ``_aws`` block declaring the metric
    namespace, the dimension sets, and the metric definitions; the metric and
    dimension *values* live as sibling top-level keys.
    """
    status_class = _status_class(status_code)
    dimensions: dict[str, str] = {
        "hospital_id": hospital_id,
        "route": route_template,
        "method": method,
        "status_class": status_class,
    }
    if model_source:
        dimensions["model_source"] = model_source

    # Dimension sets we want CloudWatch to aggregate by. Keep cardinality sane:
    # the broadest set is everything; we also publish a per-route and a
    # per-hospital rollup.
    dimension_sets = [
        ["hospital_id", "route", "method", "status_class"],
        ["route", "status_class"],
        ["hospital_id"],
    ]

    payload: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": _METRIC_NAMESPACE,
                    "Dimensions": dimension_sets,
                    "Metrics": [
                        {"Name": "latency_ms", "Unit": "Milliseconds"},
                        {"Name": "error", "Unit": "Count"},
                    ],
                }
            ],
        },
        # Metric values
        "latency_ms": round(latency_ms, 2),
        "error": error,
        # A stable event marker so these lines are easy to grep / route.
        "metric_type": "request",
    }
    payload.update(dimensions)
    return payload


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Emit one PHI-free EMF metric line per request."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        status_code = 500
        response: Optional[Response] = None
        errored = 1
        try:
            response = await call_next(request)
            status_code = response.status_code
            errored = 1 if status_code >= 500 else 0
            return response
        except Exception:
            # Let the exception propagate to FastAPI's handlers, but record the
            # failure first. status_code stays 500, errored stays 1.
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000.0
            try:
                hospital_id = _safe_hospital_id(request.scope.get("path", ""))
                route_template = _route_template(request)
                method = request.method
                model_source = (
                    _model_source(request, response) if response is not None else None
                )
                payload = build_emf_payload(
                    hospital_id=hospital_id,
                    route_template=route_template,
                    method=method,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    error=errored,
                    model_source=model_source,
                )
                _emit(payload)
                _maybe_trace(
                    {
                        "hospital_id": hospital_id,
                        "route": route_template,
                        "method": method,
                        "status_class": _status_class(status_code),
                        "latency_ms": latency_ms,
                        "error": errored,
                        "model_source": model_source,
                    }
                )
            except Exception:  # noqa: BLE001 — never let metrics break the request
                log.debug("observability middleware failed", exc_info=True)
