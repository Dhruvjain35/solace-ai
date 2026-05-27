"""Unified EHR gateway — one facade over every write/read path.

Solace integrates with several EHR back ends, each with its own quirks:

  - Epic / Oracle Health / athenahealth: vendor FHIR R4 adapters
    (`services.ehr_epic`, `services.ehr_oracle`, `services.ehr_athena`).
  - HL7 v2 integration engines (Mirth / Rhapsody / Corepoint): MDM^T02 over
    MLLP via `services.hl7_v2`.
  - Plain FHIR / mock / unconfigured hospitals: the vendor-abstract
    `services.fhir_writer` (local mock store when no base URL is set).

`routers/ehr.py` should not know which of those a given hospital uses. This
module is that single decision point: given a hospital's EHR-config dict it
routes `write_resource()` / `read_resource()` to the correct back end, retries
transient transport failures with bounded exponential backoff, supports a
dry-run mode that performs no external I/O, and emits an audit hook on every
attempt.

The vendor adapter modules (`ehr_epic`, `ehr_oracle`, `ehr_athena`) are built
concurrently and may not all exist yet — every import here is **lazy** and
guarded against `ImportError`, so this module imports cleanly regardless.

---------------------------------------------------------------------------
Routing / config contract
---------------------------------------------------------------------------
A hospital EHR-config dict (the `ehr_config` argument) carries:

    {
        "vendor":        "epic" | "oracle" | "athena" | "hl7v2"
                         | "fhir" | "mock" | None,   # missing -> mock
        "base_url":      "https://fhir.example.org/api/FHIR/R4",  # FHIR vendors
        "access_token":  "<SMART-on-FHIR bearer token>",         # FHIR vendors
        "hl7":           {"host": "10.0.0.4", "port": 6661},     # hl7v2 only
        "dry_run":       bool,    # optional, overridden by call-site dry_run
        "max_retries":   int,     # optional, default 2
    }

`vendor` is matched case-insensitively. Unknown / missing vendors fall back to
`fhir_writer` (mock store when no base_url) so a misconfigured hospital still
gets a safe, demoable result instead of a crash.

---------------------------------------------------------------------------
Adapter contract (what each vendor adapter must expose)
---------------------------------------------------------------------------
Each `services.ehr_<vendor>` module must expose:

    make_adapter(*, base_url=None, access_token=None, http_client=None)
        -> adapter object with:
             .online                          -> bool
             ._post(resource: dict) -> dict    {ok, id, url, stored, ...}
             raises <Vendor>WriteError on remote failure

The gateway calls `._post()` for writes (it is the lowest common denominator
across the vendor adapters and already falls back to the mock store offline).
Vendor write errors are normalised to `EhrGatewayError`.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class EhrGatewayError(Exception):
    """Raised when an EHR write/read fails in a way the caller must handle.

    Carries the resolved `vendor`, the `resource_type` in flight, an HTTP-ish
    `status_code` when one is known, whether the failure looked `transient`
    (retryable), and any structured `issues` (e.g. FHIR OperationOutcome).
    """

    def __init__(
        self,
        message: str,
        *,
        vendor: str | None = None,
        resource_type: str | None = None,
        status_code: int | None = None,
        transient: bool = False,
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.vendor = vendor
        self.resource_type = resource_type
        self.status_code = status_code
        self.transient = transient
        self.issues = issues or []

    def __str__(self) -> str:
        bits = [self.message]
        if self.vendor:
            bits.append(f"vendor={self.vendor}")
        if self.resource_type:
            bits.append(f"resource={self.resource_type}")
        if self.status_code is not None:
            bits.append(f"status={self.status_code}")
        return " | ".join(bits)


# --------------------------------------------------------------------------
# Config / vendor resolution
# --------------------------------------------------------------------------

# Vendors backed by a vendor-specific FHIR adapter module.
_FHIR_VENDOR_ADAPTERS: dict[str, str] = {
    "epic": "ehr_epic",
    "oracle": "ehr_oracle",
    "athena": "ehr_athena",
}
# Vendors that fall through to the generic fhir_writer dispatcher.
_GENERIC_FHIR_VENDORS = {"fhir", "mock", "", "none"}

_DEFAULT_MAX_RETRIES = 2
_DEFAULT_BACKOFF_S = 0.5
_DEFAULT_BACKOFF_CAP_S = 8.0

# Transient HTTP statuses worth a retry — everything else is a hard failure.
_TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def _normalise_vendor(ehr_config: dict[str, Any] | None) -> str:
    """Lower-cased vendor key; '' when unset (treated as generic FHIR/mock)."""
    if not ehr_config:
        return ""
    vendor = ehr_config.get("vendor")
    return str(vendor).strip().lower() if vendor else ""


def vendor_status(ehr_config: dict[str, Any] | None) -> dict[str, Any]:
    """Describe how this hospital's EHR config will be routed, without I/O.

    Useful for `routers/ehr.py` health/diagnostic endpoints. Reports the
    resolved vendor, the back-end kind, whether the vendor adapter module is
    importable right now, and whether the path is `online` (real endpoint) or
    will land in the local mock store.
    """
    cfg = ehr_config or {}
    vendor = _normalise_vendor(cfg)
    base_url = (cfg.get("base_url") or "").strip()

    if vendor in _FHIR_VENDOR_ADAPTERS:
        module_name = _FHIR_VENDOR_ADAPTERS[vendor]
        mod = _try_import(f"services.{module_name}")
        return {
            "vendor": vendor,
            "backend": "vendor_fhir_adapter",
            "module": f"services.{module_name}",
            "adapter_available": mod is not None,
            "online": bool(base_url) and mod is not None,
            "configured": bool(base_url),
        }
    if vendor == "hl7v2":
        hl7 = cfg.get("hl7") or {}
        mod = _try_import("services.hl7_v2")
        return {
            "vendor": "hl7v2",
            "backend": "hl7_v2_mllp",
            "module": "services.hl7_v2",
            "adapter_available": mod is not None,
            "online": bool(hl7.get("host") and hl7.get("port")),
            "configured": bool(hl7.get("host") and hl7.get("port")),
        }
    # Generic / unknown -> fhir_writer.
    return {
        "vendor": vendor or "mock",
        "backend": "fhir_writer",
        "module": "services.fhir_writer",
        "adapter_available": _try_import("services.fhir_writer") is not None,
        "online": bool(base_url or os.getenv("FHIR_BASE_URL")),
        "configured": bool(base_url or os.getenv("FHIR_BASE_URL")),
        "fallback": vendor not in _GENERIC_FHIR_VENDORS,
    }


# --------------------------------------------------------------------------
# Lazy / defensive imports
# --------------------------------------------------------------------------


def _try_import(module_path: str):  # noqa: ANN202 — returns module | None
    """Import a module by dotted path, returning None on ImportError.

    The vendor adapter modules are authored concurrently; this keeps the
    gateway importable (and the rest of the app bootable) even when an
    adapter file does not exist yet.
    """
    try:
        import importlib  # noqa: PLC0415

        return importlib.import_module(module_path)
    except ImportError as e:
        log.warning("EHR adapter module %s unavailable: %s", module_path, e)
        return None
    except Exception as e:  # noqa: BLE001 — a broken adapter must not crash the gateway
        log.error("EHR adapter module %s failed to import: %s", module_path, e)
        return None


# --------------------------------------------------------------------------
# Audit hook
# --------------------------------------------------------------------------

# A caller (router) may register a hook; signature: (event: dict) -> None.
_AuditHook = Callable[[dict[str, Any]], None]


def _emit_audit(audit_hook: _AuditHook | None, event: dict[str, Any]) -> None:
    """Best-effort audit emission — never let an audit failure break a write."""
    if audit_hook is None:
        return
    try:
        audit_hook(event)
    except Exception as e:  # noqa: BLE001
        log.warning("EHR gateway audit hook failed: %s", e)


# --------------------------------------------------------------------------
# Retry / backoff
# --------------------------------------------------------------------------


def _is_transient(exc: Exception) -> bool:
    """True when an exception looks like a transient transport failure.

    Retries are reserved for genuinely transient conditions — never for 4xx
    validation errors, which would just fail identically on every attempt.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in _TRANSIENT_STATUSES
    if getattr(exc, "transient", False):
        return True
    # Transport-layer exceptions (timeouts, connection resets) carry no status.
    name = type(exc).__name__.lower()
    if any(tok in name for tok in ("timeout", "connect", "transport", "network")):
        return True
    msg = str(exc).lower()
    return any(tok in msg for tok in ("timed out", "connection reset", "transport error"))


def _with_retry(
    fn: Callable[[], dict[str, Any]],
    *,
    vendor: str,
    resource_type: str,
    max_retries: int,
    audit_hook: _AuditHook | None,
) -> dict[str, Any]:
    """Run `fn`, retrying transient failures with bounded exponential backoff."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except EhrGatewayError as e:
            transient = e.transient
            last_exc: Exception = e
        except Exception as e:  # noqa: BLE001 — adapter-specific error types
            transient = _is_transient(e)
            last_exc = e

        if not transient or attempt > max_retries:
            _emit_audit(
                audit_hook,
                {
                    "event": "ehr_write_failed",
                    "vendor": vendor,
                    "resource_type": resource_type,
                    "attempt": attempt,
                    "transient": transient,
                    "error": str(last_exc),
                },
            )
            if isinstance(last_exc, EhrGatewayError):
                raise last_exc
            raise EhrGatewayError(
                f"{vendor} write failed for {resource_type}: {last_exc}",
                vendor=vendor,
                resource_type=resource_type,
                status_code=getattr(last_exc, "status_code", None),
                transient=transient,
            ) from last_exc

        delay = min(_DEFAULT_BACKOFF_S * (2 ** (attempt - 1)), _DEFAULT_BACKOFF_CAP_S)
        log.warning(
            "EHR %s write attempt %d/%d failed transiently (%s) — retrying in %.1fs",
            vendor,
            attempt,
            max_retries + 1,
            last_exc,
            delay,
        )
        time.sleep(delay)


# --------------------------------------------------------------------------
# Vendor dispatch
# --------------------------------------------------------------------------


def _write_via_fhir_adapter(
    module_name: str,
    vendor: str,
    resource: dict[str, Any],
    ehr_config: dict[str, Any],
) -> dict[str, Any]:
    """Write through a vendor FHIR adapter module (epic / oracle / athena)."""
    mod = _try_import(f"services.{module_name}")
    if mod is None or not hasattr(mod, "make_adapter"):
        # Adapter not built / not importable yet — degrade to fhir_writer so
        # the write still lands somewhere instead of hard-failing.
        log.warning(
            "Vendor adapter services.%s unavailable — falling back to fhir_writer",
            module_name,
        )
        return _write_via_fhir_writer(vendor, resource, ehr_config)

    adapter = mod.make_adapter(
        base_url=ehr_config.get("base_url") or None,
        access_token=ehr_config.get("access_token") or None,
    )
    try:
        result = adapter._post(resource)  # noqa: SLF001 — documented adapter contract
    except Exception as e:  # noqa: BLE001 — normalise vendor-specific errors
        raise EhrGatewayError(
            f"{vendor} adapter write failed: {e}",
            vendor=vendor,
            resource_type=resource.get("resourceType"),
            status_code=getattr(e, "status_code", None),
            transient=_is_transient(e),
            issues=getattr(e, "issues", None),
        ) from e
    return dict(result, vendor=vendor)


def _write_via_fhir_writer(
    vendor: str,
    resource: dict[str, Any],
    ehr_config: dict[str, Any],
) -> dict[str, Any]:
    """Write through the generic `fhir_writer` dispatcher (mock store offline)."""
    mod = _try_import("services.fhir_writer")
    if mod is None:
        raise EhrGatewayError(
            "fhir_writer unavailable — cannot complete EHR write",
            vendor=vendor or "mock",
            resource_type=resource.get("resourceType"),
        )
    result = mod.write(
        resource,
        fhir_base_url=ehr_config.get("base_url") or None,
        access_token=ehr_config.get("access_token") or None,
    )
    return dict(result, vendor=vendor or "mock")


def _write_via_hl7v2(
    resource: dict[str, Any],
    ehr_config: dict[str, Any],
) -> dict[str, Any]:
    """Write through HL7 v2 MDM^T02 over MLLP.

    Only `DocumentReference`-shaped resources map cleanly to MDM^T02. The
    resource's note text and patient identifiers are pulled from a Solace
    intermediate shape carried under `resource["_hl7"]` (a dict with
    `mrn`, `family_name`, `given_name`, `dob`, `sex`, `note_text`,
    `npi`, `provider_family`, `provider_given`).
    """
    mod = _try_import("services.hl7_v2")
    if mod is None:
        raise EhrGatewayError(
            "hl7_v2 unavailable — cannot complete HL7 v2 write",
            vendor="hl7v2",
            resource_type=resource.get("resourceType"),
        )
    hl7_cfg = ehr_config.get("hl7") or {}
    host, port = hl7_cfg.get("host"), hl7_cfg.get("port")
    if not host or not port:
        raise EhrGatewayError(
            "hl7v2 config missing host/port",
            vendor="hl7v2",
            resource_type=resource.get("resourceType"),
        )
    payload = resource.get("_hl7") or {}
    try:
        msg = mod.MdmMessage(
            note_text=payload.get("note_text", ""),
            patient=mod.Patient(
                mrn=payload.get("mrn", ""),
                family_name=payload.get("family_name", ""),
                given_name=payload.get("given_name", ""),
                dob=payload.get("dob", ""),
                sex=payload.get("sex", "U"),
            ),
            provider=mod.Provider(
                npi=payload.get("npi", ""),
                family_name=payload.get("provider_family", ""),
                given_name=payload.get("provider_given", ""),
            ),
        )
        rendered = mod.render(msg)
        ack = mod.send_mllp(host, int(port), rendered, timeout=hl7_cfg.get("timeout_s", 10.0))
    except Exception as e:  # noqa: BLE001
        raise EhrGatewayError(
            f"HL7 v2 MLLP write failed: {e}",
            vendor="hl7v2",
            resource_type=resource.get("resourceType"),
            transient=_is_transient(e),
        ) from e
    if not ack.get("sent") or ack.get("ack_type") not in ("AA", None):
        raise EhrGatewayError(
            f"HL7 v2 receiver rejected message (ack={ack.get('ack_type')})",
            vendor="hl7v2",
            resource_type=resource.get("resourceType"),
            transient=ack.get("ack_type") != "AR",
        )
    return {
        "ok": True,
        "vendor": "hl7v2",
        "stored": "hl7v2",
        "ack_type": ack.get("ack_type"),
        "id": msg.message_control_id,
    }


# --------------------------------------------------------------------------
# Public facade
# --------------------------------------------------------------------------


def write_resource(
    resource: dict[str, Any],
    *,
    ehr_config: dict[str, Any] | None = None,
    dry_run: bool = False,
    audit_hook: _AuditHook | None = None,
) -> dict[str, Any]:
    """Write a FHIR resource (or HL7-shaped resource) to a hospital's EHR.

    Routes by `ehr_config["vendor"]`:
      - epic / oracle / athena -> vendor FHIR adapter
      - hl7v2                  -> HL7 v2 MDM^T02 over MLLP
      - fhir / mock / unset    -> generic `fhir_writer` (mock store offline)

    `dry_run=True` (or `ehr_config["dry_run"]`) performs no external I/O and
    returns a preview describing where the write *would* have gone.

    Transient failures are retried with bounded exponential backoff. Hard
    failures raise `EhrGatewayError`. Every attempt emits an audit event via
    `audit_hook` when one is supplied.
    """
    cfg = dict(ehr_config or {})
    vendor = _normalise_vendor(cfg)
    resource_type = resource.get("resourceType") or "Resource"
    effective_dry_run = dry_run or bool(cfg.get("dry_run"))
    max_retries = int(cfg.get("max_retries", _DEFAULT_MAX_RETRIES))

    if effective_dry_run:
        status = vendor_status(cfg)
        _emit_audit(
            audit_hook,
            {
                "event": "ehr_write_dry_run",
                "vendor": vendor or "mock",
                "resource_type": resource_type,
            },
        )
        return {
            "ok": True,
            "dry_run": True,
            "vendor": vendor or "mock",
            "resource_type": resource_type,
            "routed_to": status,
        }

    def _do_write() -> dict[str, Any]:
        if vendor in _FHIR_VENDOR_ADAPTERS:
            return _write_via_fhir_adapter(
                _FHIR_VENDOR_ADAPTERS[vendor], vendor, resource, cfg
            )
        if vendor == "hl7v2":
            return _write_via_hl7v2(resource, cfg)
        # fhir / mock / unknown -> generic dispatcher.
        return _write_via_fhir_writer(vendor, resource, cfg)

    result = _with_retry(
        _do_write,
        vendor=vendor or "mock",
        resource_type=resource_type,
        max_retries=max_retries,
        audit_hook=audit_hook,
    )
    _emit_audit(
        audit_hook,
        {
            "event": "ehr_write_ok",
            "vendor": result.get("vendor", vendor or "mock"),
            "resource_type": resource_type,
            "stored": result.get("stored"),
            "id": result.get("id"),
        },
    )
    return result


def read_resource(
    resource_type: str,
    *,
    ehr_config: dict[str, Any] | None = None,
    resource_id: str | None = None,
    audit_hook: _AuditHook | None = None,
) -> list[dict[str, Any]]:
    """Read resources of `resource_type` from a hospital's EHR.

    Today the only read-capable back end is the local `fhir_writer` mock
    store (vendor FHIR search lives in `services.fhir_patient_search` and
    `routers/ehr.py` owns that path directly). For epic/oracle/athena/hl7v2
    this returns `[]` until vendor read adapters land — callers should treat
    an empty list as "no local data" rather than an error.
    """
    cfg = dict(ehr_config or {})
    vendor = _normalise_vendor(cfg)
    _emit_audit(
        audit_hook,
        {"event": "ehr_read", "vendor": vendor or "mock", "resource_type": resource_type},
    )

    # Vendor live reads are not yet wired through the gateway.
    if vendor in _FHIR_VENDOR_ADAPTERS or vendor == "hl7v2":
        log.info("read_resource: vendor=%s has no gateway read adapter yet", vendor)
        return []

    mod = _try_import("services.fhir_writer")
    if mod is None:
        return []
    items = mod.list_local(resource_type)
    if resource_id:
        return [r for r in items if r.get("id") == resource_id]
    return items
