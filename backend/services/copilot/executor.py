"""The executor — the deterministic engine that runs a validated plan.

It is the ONLY component that reads real patient values and calls the clinical
services. For each plan step it invokes the primitive's adapter, which returns
*coded* structured output. Any real value the clinician must see is parked in the
slot map (keyed S1, S2, ...) and referenced from the coded output as
``{"$slot": "S1"}`` — the slot map is returned to the router for deterministic
rendering and is NEVER placed in a model call.

A boundary linter runs over every coded output before it is handed back, failing
loudly if a raw-PHI-shaped string slipped through an adapter.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services import fhir_patient_search

log = logging.getLogger(__name__)


class SlotMap:
    """Holds real (clinician-only) values keyed by opaque slot ids."""

    def __init__(self) -> None:
        self._slots: dict[str, dict[str, str]] = {}
        self._n = 0

    def put(self, label: str, value: str) -> dict[str, str]:
        """Park a real value; return the coded marker the model will see."""
        self._n += 1
        sid = f"S{self._n}"
        self._slots[sid] = {"label": label, "value": str(value)}
        return {"$slot": sid, "label": label}

    def as_dict(self) -> dict[str, dict[str, str]]:
        return dict(self._slots)


class Executor:
    """Runs primitive adapters against the real chart, accumulating slots."""

    def __init__(self, ctx: dict[str, Any]) -> None:
        self.ctx = ctx
        self.chart = ctx["chart"]
        self.slots = SlotMap()
        self.sources: list[dict[str, Any]] = []

    # -- helpers adapters use ------------------------------------------------

    def slot(self, label: str, value: str) -> dict[str, str]:
        return self.slots.put(label, value)

    def cite(self, resource: str, **extra: Any) -> None:
        self.sources.append({"resource": resource, **extra})

    def ehr_record(self) -> dict[str, Any] | None:
        """Fetch + cache the linked FHIR record (deterministic zone only)."""
        if self.ctx.get("ehr_record") is not None:
            return self.ctx["ehr_record"] or None
        rec = _crawl_ehr(self.ctx)
        self.ctx["ehr_record"] = rec or {}
        return rec

    # -- the run loop --------------------------------------------------------

    def run(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute each validated step; return coded results keyed by step id."""
        from services.copilot import registry  # noqa: PLC0415 (avoid import cycle)

        results: list[dict[str, Any]] = []
        for step in plan.get("steps", []):
            sid = step["id"]
            name = step["primitive"]
            params = step.get("params") or {}
            spec = registry.PRIMITIVES[name]
            try:
                data = spec["adapter"](self, params)
                _assert_no_raw_phi(name, data, self.chart)
                self.cite(spec["group"] + "." + name.split(".")[-1])
            except Exception as e:  # noqa: BLE001 — a primitive failure must not crash the run
                log.warning("copilot primitive %s failed: %s", name, e)
                data = {"error": f"{name} unavailable"}
            results.append({"id": sid, "primitive": name, "data": data})
        return results


# ---------------------------------------------------------------------------
# EHR crawl (deterministic) — adapted from the legacy copilot
# ---------------------------------------------------------------------------

def _crawl_ehr(ctx: dict[str, Any]) -> dict[str, Any] | None:
    patient = ctx["patient"]
    fhir_id = patient.get("ehr_fhir_id")
    try:
        if fhir_id:
            bundle = fhir_patient_search._search("Patient", {"_id": fhir_id})
            entries = bundle.get("entry") or []
            if entries:
                return fhir_patient_search._enrich_patient(entries[0].get("resource") or {})
        name = (ctx["chart"].get("name") or "").split()
        if len(name) >= 2:
            rec = fhir_patient_search.match_by_demographics(
                {"first_name": name[0], "last_name": name[-1], "dob": (patient.get("dob") or "")}
            )
            if rec and rec.get("record"):
                return rec["record"]
    except Exception as e:  # noqa: BLE001
        log.info("copilot EHR crawl failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# Boundary linter — last line of defence before coded output is trusted
# ---------------------------------------------------------------------------

def _assert_no_raw_phi(primitive: str, data: Any, chart: dict[str, Any]) -> None:
    """Fail if a coded output leaks an identifier or raw chart string.

    Real values are allowed ONLY inside slot entries (``{"$slot": ...}``), which
    are stripped here before the scan. Identifiers (name) and raw med/allergy
    product strings must never appear verbatim in model-bound coded output.
    """
    forbidden: set[str] = set()
    name = (chart.get("name") or "").strip()
    if name:
        forbidden.update(p.lower() for p in name.split() if len(p) > 1)
    for key in ("medications", "allergies"):
        for v in chart.get(key) or []:
            t = str(v).strip().lower()
            if len(t) > 2:
                forbidden.add(t)
            # also forbid the significant words (e.g. "warfarin" from "warfarin 5mg")
            # so an adapter leaking the generic name is still caught.
            forbidden.update(re.findall(r"[a-z]{4,}", t))

    def scan(node: Any) -> None:
        if isinstance(node, dict):
            if "$slot" in node:  # slot markers are the sanctioned channel — skip
                return
            for v in node.values():
                scan(v)
        elif isinstance(node, list):
            for v in node:
                scan(v)
        elif isinstance(node, str):
            low = node.lower()
            for bad in forbidden:
                if bad in low:
                    raise AssertionError(
                        f"PHI boundary violation in {primitive}: coded output "
                        f"contains raw value '{bad}' outside a slot"
                    )

    scan(data)
