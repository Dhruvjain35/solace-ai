"""Workflow execution engine.

`fire(event_name, hospital_id, context)` is called from anywhere a trigger
event happens (intake submit, mark-seen, pain flag, appointment booked, etc.).
The engine looks up enabled workflows for that trigger + hospital, evaluates
filters, and runs the action chain in order. Each action result is logged.

Failures don't propagate — a broken workflow can't take down the patient flow
that fired the event. Errors are recorded against the workflow row so admins
see them on the dashboard.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from services.workflows import actions, storage

log = logging.getLogger(__name__)


def fire(event_name: str, hospital_id: str, context: dict[str, Any]) -> None:
    """Fire all enabled workflows matching this trigger. Synchronous — runs
    the action chain inline. Thread-safe (each workflow gets a copy of the
    context). Never raises — caller (a request handler) is shielded."""
    try:
        workflows = storage.list_for_hospital(hospital_id)
    except Exception as e:  # noqa: BLE001
        log.warning("workflow lookup failed for %s: %s", hospital_id, e)
        return

    matching = [
        w for w in workflows
        if w.get("enabled", True) and w.get("trigger") == event_name
    ]
    if not matching:
        return

    enriched = {**context, "trigger": event_name}
    for wf in matching:
        if not _filters_match(wf.get("filters") or {}, enriched):
            continue
        # Each workflow runs in a daemon thread so a slow webhook doesn't
        # delay the request that fired the event. Errors stay inside the thread.
        threading.Thread(
            target=_run_workflow_safe,
            args=(wf, enriched),
            daemon=True,
        ).start()


def _run_workflow_safe(workflow: dict, context: dict) -> None:
    workflow_id = workflow.get("workflow_id", "?")
    try:
        results = []
        for step in workflow.get("steps") or []:
            if not isinstance(step, dict):
                continue
            stype = step.get("type")
            sconfig = step.get("config") or {}
            if not stype:
                continue
            r = actions.run(stype, sconfig, context)
            results.append({"type": stype, **{k: r[k] for k in ("success",) if k in r}})
            if r.get("success") is False and step.get("stop_on_error"):
                break
        log.info(
            "workflow %s fired (trigger=%s) → %d steps, %d ok",
            workflow_id, context.get("trigger"),
            len(results), sum(1 for r in results if r.get("success")),
        )
        try:
            storage.increment_fire_count(workflow_id)
        except Exception:  # noqa: BLE001 — bookkeeping is best-effort
            pass
    except Exception as e:  # noqa: BLE001
        log.exception("workflow %s exception: %s", workflow_id, e)


def _filters_match(filters: dict, context: dict) -> bool:
    """Tiny filter language — same key/value match against the context.

    Supported:
      patient.esi_level_lte: 3      → patient.esi_level <= 3
      patient.esi_level_gte: 4      → patient.esi_level >= 4
      patient.esi_level: 2          → patient.esi_level == 2
      patient.language: "es"
    """
    if not filters:
        return True
    for key, want in filters.items():
        # Path-based dotted key, with optional _lte / _gte / _eq suffix.
        op = "eq"
        path = key
        for suffix in ("_lte", "_gte", "_eq"):
            if key.endswith(suffix):
                op = suffix[1:]  # 'lte' / 'gte' / 'eq'
                path = key[: -len(suffix)]
                break
        actual = _dig(context, path.split("."))
        if actual is None:
            return False
        try:
            if op == "lte" and not (float(actual) <= float(want)):
                return False
            elif op == "gte" and not (float(actual) >= float(want)):
                return False
            elif op == "eq" and actual != want:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _dig(obj: Any, path: list[str]) -> Any:
    cur = obj
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur
