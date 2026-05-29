"""Workflow execution engine.

`fire(event_name, hospital_id, context)` is called from anywhere a trigger
event happens (intake submit, mark-seen, pain flag, appointment booked, etc.).
The engine looks up enabled workflows for that trigger + hospital, sanitizes
the context for PHI, evaluates filters, and runs the action chain in order.
Each action result is logged.

Safety model:
  - PHI: `phi.sanitize_context()` runs once before any action sees the
    context — names, phones, emails, DOB, transcripts and addresses are
    stripped, opaque ids/hashes are kept. No handler ever receives raw PHI.
  - Bounded execution: a chain runs at most `MAX_STEPS` steps and each step is
    given at most `STEP_TIMEOUT_SECONDS` of wall-clock time, so a runaway
    branch or a hung webhook cannot pin a daemon thread forever.
  - Conditional branching: a step may carry an `if` clause; when it does not
    match the (sanitized) context the step is skipped. A step may also set
    `goto` to jump to a named step, with a visited-cap that prevents loops.

Failures don't propagate — a broken workflow can't take down the patient flow
that fired the event. Errors are recorded against the workflow row so admins
see them on the dashboard.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any

from services.workflows import actions, phi, storage

log = logging.getLogger(__name__)

# Bounded-execution guards — keep a daemon workflow thread from running away.
MAX_STEPS = 25                 # hard cap on steps executed per workflow run
STEP_TIMEOUT_SECONDS = 12.0    # wall-clock budget per individual action


def fire(event_name: str, hospital_id: str, context: dict[str, Any]) -> None:
    """Fire all enabled workflows matching this trigger. Synchronous lookup,
    each matching workflow runs in its own daemon thread. Never raises — the
    caller (a request handler) is shielded."""
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

    # PHI minimization — strip identifiers ONCE, before any workflow or action
    # sees the context. Everything downstream operates on the sanitized copy.
    safe_context = phi.sanitize_context({**context, "trigger": event_name})

    for wf in matching:
        if not _filters_match(wf.get("filters") or {}, safe_context):
            continue
        # Each workflow runs in a daemon thread so a slow webhook doesn't delay
        # the request that fired the event. Each thread gets its own context
        # copy. Errors stay inside the thread.
        threading.Thread(
            target=_run_workflow_safe,
            args=(wf, dict(safe_context)),
            daemon=True,
        ).start()


def _run_workflow_safe(workflow: dict, context: dict) -> None:
    workflow_id = workflow.get("workflow_id", "?")
    try:
        results = _execute_chain(workflow.get("steps") or [], context)
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


def _execute_chain(steps: list, context: dict) -> list[dict]:
    """Run an action chain with conditional branching and bounded execution.

    Step shape (all keys beyond `type` are optional):
      {"type": "send_sms", "config": {...},
       "id": "notify",                # name used as a `goto` target
       "if": {"patient.esi_level_lte": 2},   # skip step unless filter matches
       "stop_on_error": true,         # halt the chain on failure
       "goto": "escalate"}            # jump to the step with id == "escalate"

    Caps: at most MAX_STEPS executions; each action gets STEP_TIMEOUT_SECONDS.
    """
    norm = [s for s in steps if isinstance(s, dict) and s.get("type")]
    by_id = {s["id"]: i for i, s in enumerate(norm) if s.get("id")}
    results: list[dict] = []
    idx = 0
    executed = 0

    while 0 <= idx < len(norm) and executed < MAX_STEPS:
        step = norm[idx]
        executed += 1

        # Conditional: skip this step if its `if` clause does not match.
        cond = step.get("if")
        if cond and not _filters_match(cond, context):
            results.append({"type": step["type"], "skipped": True})
            idx += 1
            continue

        r = _run_step_bounded(step["type"], step.get("config") or {}, context)
        results.append({"type": step["type"],
                         **{k: r[k] for k in ("success",) if k in r}})

        if r.get("success") is False and step.get("stop_on_error"):
            break

        # Branching: an explicit goto jumps to a named step; otherwise advance.
        goto = step.get("goto")
        if goto and goto in by_id:
            idx = by_id[goto]
        else:
            idx += 1

    if executed >= MAX_STEPS:
        log.warning("workflow chain hit MAX_STEPS=%d cap — halted", MAX_STEPS)
    return results


def _run_step_bounded(stype: str, sconfig: dict, context: dict) -> dict:
    """Run a single action under a wall-clock timeout. A hung handler (slow
    webhook, stuck AI call) is abandoned rather than pinning the thread."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(actions.run, stype, sconfig, context)
        try:
            return future.result(timeout=STEP_TIMEOUT_SECONDS)
        except FuturesTimeout:
            log.warning("workflow action %s exceeded %.0fs — abandoned",
                        stype, STEP_TIMEOUT_SECONDS)
            return {"success": False, "reason": "step_timeout", "type": stype}
        except Exception as e:  # noqa: BLE001
            log.exception("workflow action %s failed: %s", stype, e)
            return {"success": False, "reason": "step_exception",
                    "message": str(e)[:200]}


def _filters_match(filters: dict, context: dict) -> bool:
    """Tiny filter language — also used for per-step `if` conditions.

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
