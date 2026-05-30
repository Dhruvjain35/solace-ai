"""The plan-validation gate — runs BEFORE any PHI is touched.

A plan that fails any check is rejected wholesale (no partial execution). Because
every param is typed ``enum | bool | int`` and validated against the catalog
vocab — there is no free-string param type anywhere in the registry — the model
has no structural channel to express a raw patient value in a valid plan.
"""
from __future__ import annotations

from typing import Any

from services.copilot import registry

MAX_STEPS = 8


class PlanRejected(Exception):
    """Raised when a plan violates the gate. Message is safe to surface."""


def validate(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PlanRejected("plan must be an object")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PlanRejected("plan must contain at least one step")
    if len(steps) > MAX_STEPS:
        raise PlanRejected(f"plan exceeds the {MAX_STEPS}-step budget")

    seen_ids: set[str] = set()
    clean_steps: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlanRejected(f"step {i} is not an object")
        sid = str(step.get("id") or f"s{i + 1}")
        if sid in seen_ids:
            raise PlanRejected(f"duplicate step id '{sid}'")
        seen_ids.add(sid)

        name = step.get("primitive")
        spec = registry.PRIMITIVES.get(name)
        if spec is None:
            raise PlanRejected(f"unknown primitive '{name}'")

        clean_params = _validate_params(name, spec["params"], step.get("params") or {})
        clean_steps.append({"id": sid, "primitive": name, "params": clean_params})

    return {"reasoning": str(plan.get("reasoning") or "")[:500], "steps": clean_steps}


def _validate_params(primitive: str, schema: dict[str, Any], given: Any) -> dict[str, Any]:
    if not isinstance(given, dict):
        raise PlanRejected(f"{primitive}: params must be an object")

    unknown = set(given) - set(schema)
    if unknown:
        raise PlanRejected(f"{primitive}: unknown param(s) {sorted(unknown)}")

    out: dict[str, Any] = {}
    for key, rule in schema.items():
        if key not in given:
            if rule.get("required"):
                raise PlanRejected(f"{primitive}: missing required param '{key}'")
            continue
        val = given[key]
        kind = rule["type"]
        if kind == "enum":
            if val not in rule["values"]:
                # This is the smuggling guard: a non-vocab value (e.g. a raw name)
                # cannot pass as an enum param.
                raise PlanRejected(f"{primitive}.{key}: '{val}' is not an allowed value")
        elif kind == "bool":
            if not isinstance(val, bool):
                raise PlanRejected(f"{primitive}.{key}: must be a boolean")
        elif kind == "int":
            if not isinstance(val, int) or isinstance(val, bool):
                raise PlanRejected(f"{primitive}.{key}: must be an integer")
        else:  # pragma: no cover — registry only declares enum/bool/int
            raise PlanRejected(f"{primitive}.{key}: unsupported param type")
        out[key] = val
    return out
