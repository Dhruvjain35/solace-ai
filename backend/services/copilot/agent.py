"""Bounded agentic tool loop over the coded copilot registry.

The agent answers a clinician's free-form request by calling Claude in a
bounded (<= MAX_ROUNDS) tool loop. The ONLY tools the model has are:

  - search_chart   — discover which coded primitives exist (PHI-free catalog)
  - read_chart     — run ONE registry primitive through the gate + Executor;
                     output is coded + linted by ``_assert_no_raw_phi``
  - propose_write  — COLLECT a proposed FHIR write; nothing is written here

The model therefore NEVER sees raw PHI: real values are parked in the slot map
as ``{"$slot": "S#"}`` markers and the tokens ``{S#}`` in the final reply are
filled deterministically AFTER the loop, for the clinician only. Proposed
writes are returned to the router for explicit clinician confirmation — the
agent itself has no write path.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import HTTPException

from lib import claude, content_guard
from lib.config import settings
from services.copilot import catalog, context, gate, registry
from services.copilot.executor import Executor

log = logging.getLogger(__name__)

MAX_ROUNDS = 5
HISTORY_CAP = 12
_MAX_TOKENS = 1200

# FHIR resource types the agent may PROPOSE (and the execute endpoint may write).
ALLOWED_WRITE_TYPES = (
    "Condition",
    "Observation",
    "AllergyIntolerance",
    "ServiceRequest",
    "MedicationRequest",
    "DocumentReference",
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_chart",
        "description": (
            "Search the catalog of coded chart primitives available for this "
            "patient. Returns matching primitive names, params and coded return "
            "shapes. Call with an empty query to list everything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "keywords"}},
        },
    },
    {
        "name": "read_chart",
        "description": (
            "Run ONE coded chart primitive (from search_chart) and get its coded "
            "result. Real patient values appear only as {\"$slot\": \"S#\"} "
            "markers — to show one to the clinician, write the token {S#} in "
            "your final reply and it will be filled in for them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "primitive": {"type": "string", "description": "primitive name, e.g. feature.flag"},
                "params": {"type": "object", "description": "params per the catalog vocab"},
            },
            "required": ["primitive"],
        },
    },
    {
        "name": "propose_write",
        "description": (
            "Propose ONE FHIR resource to add to the chart. It is NOT written — "
            "the clinician must confirm it in the UI. resource_type must be one "
            f"of {list(ALLOWED_WRITE_TYPES)}. Do not include patient identifiers "
            "or a subject reference; the server attaches the subject itself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_type": {"type": "string"},
                "summary": {"type": "string", "description": "one line for the confirm card"},
                "resource": {"type": "object", "description": "the FHIR resource body"},
            },
            "required": ["resource_type", "summary", "resource"],
        },
    },
]


def _system_prompt() -> str:
    return (
        "You are a clinical chart agent inside an EHR. You NEVER see raw patient "
        "data — only coded outputs from the tools. Work in this loop: use "
        "search_chart to discover primitives, read_chart to fetch coded facts, "
        "and propose_write to draft chart additions for clinician confirmation.\n\n"
        "RULES:\n"
        "- Never guess a real patient value. Coded results carry real values only "
        "as {\"$slot\": \"S#\"} markers; surface one by writing the token {S#} in "
        "your reply — it is filled in for the clinician after you finish.\n"
        "- Writes are proposals only; the clinician confirms each one. Allowed "
        f"resource types: {', '.join(ALLOWED_WRITE_TYPES)}.\n"
        "- Be concise and clinical. When you have enough data, reply in plain "
        "text (markdown bold allowed) without calling more tools.\n\n"
        f"CHART SCHEMA (coded):\n{json.dumps(catalog.schema_card())}\n\n"
        f"PRIMITIVES:\n{json.dumps(registry.planner_catalog())}"
    )


# ---------------------------------------------------------------------------
# Tool implementations (deterministic zone)
# ---------------------------------------------------------------------------

def _tool_search_chart(params: dict[str, Any]) -> dict[str, Any]:
    query = str(params.get("query") or "").strip().lower()
    entries = registry.planner_catalog()
    if query:
        terms = [t for t in query.split() if t]
        entries = [
            e for e in entries
            if any(t in (e["primitive"] + " " + e["group"] + " " + e["summary"]).lower()
                   for t in terms)
        ] or registry.planner_catalog()
    return {"primitives": entries}


def _tool_read_chart(ex: Executor, step_no: int, params: dict[str, Any]) -> dict[str, Any]:
    primitive = params.get("primitive")
    try:
        plan = gate.validate({"steps": [{
            "id": f"t{step_no}", "primitive": primitive,
            "params": params.get("params") or {},
        }]})
    except gate.PlanRejected as e:
        return {"error": str(e)}
    results = ex.run(plan)  # Executor lints every output via _assert_no_raw_phi
    return results[0]["data"] if results else {"error": "no result"}


def _tool_propose_write(
    proposals: list[dict[str, Any]], params: dict[str, Any]
) -> dict[str, Any]:
    rtype = str(params.get("resource_type") or "")
    if rtype not in ALLOWED_WRITE_TYPES:
        return {"error": f"resource_type '{rtype}' is not allowed; "
                         f"use one of {list(ALLOWED_WRITE_TYPES)}"}
    resource = params.get("resource")
    if not isinstance(resource, dict):
        return {"error": "resource must be an object"}
    summary = str(params.get("summary") or "").strip() or f"Proposed {rtype}"
    action_id = f"a{len(proposals) + 1}"
    resource = dict(resource)
    resource["resourceType"] = rtype
    # The model must not address the patient — the execute endpoint attaches
    # the subject reference server-side. Strip anything it tried to set.
    resource.pop("subject", None)
    resource.pop("patient", None)
    proposals.append({
        "id": action_id, "resource_type": rtype,
        "summary": summary[:200], "resource": resource,
    })
    return {"ok": True, "id": action_id, "status": "pending clinician confirmation"}


# ---------------------------------------------------------------------------
# Loop helpers
# ---------------------------------------------------------------------------

def _event(kind: str, label: str, detail: str | None = None,
           ms: int | None = None, status: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "label": label, "detail": detail, "ms": ms, "status": status}


def _approx_tokens(n_bytes: int) -> int:
    return max(1, n_bytes // 4)


def _payload_bytes(system: str, messages: list[dict[str, Any]]) -> int:
    return len(system.encode()) + len(json.dumps(messages, default=str).encode())


def _fill_slots(text: str, slots: dict[str, dict[str, str]]) -> str:
    import re
    return re.sub(
        r"\{(S\d+)\}",
        lambda m: slots.get(m.group(1), {}).get("value", "[unavailable]"),
        text,
    )


def _dispatch_tool(
    ex: Executor, proposals: list[dict[str, Any]], read_count: list[int],
    name: str, tool_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one tool call; return (result, event). Timing is real (monotonic)."""
    t0 = time.monotonic()
    if name == "search_chart":
        result = _tool_search_chart(tool_input)
        kind, label = "fhir", "Search chart"
        detail = str(tool_input.get("query") or "") or None
    elif name == "read_chart":
        read_count[0] += 1
        result = _tool_read_chart(ex, read_count[0], tool_input)
        kind, label = "fhir", f"Read chart: {tool_input.get('primitive')}"
        detail = None
    elif name == "propose_write":
        result = _tool_propose_write(proposals, tool_input)
        kind = "propose"
        label = f"Proposed {tool_input.get('resource_type')}"
        detail = str(tool_input.get("summary") or "")[:120] or None
    else:
        result = {"error": f"unknown tool '{name}'"}
        kind, label, detail = "info", f"Unknown tool {name}", None
    ms = int((time.monotonic() - t0) * 1000)
    status = "error" if isinstance(result, dict) and result.get("error") else "ok"
    return result, _event(kind, label, detail, ms, status)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_agent(
    hospital_id: str,
    patient_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the bounded agent loop. Returns the contract-exact response body.

    Raises HTTPException for tenancy (404), consent (403, SEC-004) and an
    unavailable AI backend (503). The consent + tenancy gates live in
    ``context.build_chart`` — the PHI-boundary entry point.
    """
    if not claude.available():
        raise HTTPException(status_code=503, detail="AI backend unavailable")

    events: list[dict[str, Any]] = []
    safe_msg = message
    if message:
        ok, cleaned, _findings = content_guard.scan(message, label="copilot.agent")
        if not ok:
            return {
                "reply": "That request can't be processed.",
                "proposed_actions": [],
                "events": [_event("info", "Request blocked", "content guard", None, "error")],
                "usage": {"input_tokens": 0, "output_tokens": 0, "rounds": 0},
            }
        safe_msg = cleaned

    # PHI boundary: tenancy (404) + SEC-004 consent (403) enforced here.
    ctx = context.build_chart(hospital_id, patient_id)
    ex = Executor(ctx)
    proposals: list[dict[str, Any]] = []
    read_count = [0]

    system = _system_prompt()
    messages: list[dict[str, Any]] = [
        {"role": h["role"], "content": h["content"]}
        for h in (history or [])[-HISTORY_CAP:]
        if h.get("role") in ("user", "assistant") and str(h.get("content") or "").strip()
    ]
    messages.append({"role": "user", "content": safe_msg})

    input_tokens = output_tokens = rounds = 0
    reply_text = ""

    for round_no in range(1, MAX_ROUNDS + 1):
        t0 = time.monotonic()
        try:
            resp = claude.messages_create(
                model=settings.model_utility,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=messages,
                purpose="copilot_agent",
                tools=TOOLS,
            )
        except Exception as e:  # noqa: BLE001 — degrade to a clean reply, never a 500
            log.warning("copilot agent model round %d failed: %s", round_no, e)
            events.append(_event("think", f"Model round {round_no}",
                                 None, int((time.monotonic() - t0) * 1000), "error"))
            reply_text = reply_text or "The AI backend is unavailable right now — please retry."
            break
        ms = int((time.monotonic() - t0) * 1000)
        rounds = round_no
        input_tokens += _approx_tokens(_payload_bytes(system, messages))
        text = "".join(getattr(b, "text", "") for b in resp.content)
        output_tokens += _approx_tokens(len(text.encode()))
        events.append(_event("think", f"Model round {round_no}", None, ms, "ok"))

        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            reply_text = text
            break

        assistant_blocks: list[dict[str, Any]] = []
        for b in resp.content:
            btype = getattr(b, "type", "")
            if btype == "text" and b.text.strip():
                assistant_blocks.append({"type": "text", "text": b.text})
            elif btype == "tool_use":
                assistant_blocks.append(
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            result, ev = _dispatch_tool(ex, proposals, read_count, tu.name, tu.input or {})
            events.append(ev)
            tool_results.append({
                "type": "tool_result", "tool_use_id": tu.id,
                "content": json.dumps(result),
            })
        messages.append({"role": "user", "content": tool_results})

        if round_no == MAX_ROUNDS:
            reply_text = text.strip() or (
                "I reached my reasoning budget before finishing. Here is what I "
                "gathered so far — ask again to continue."
            )
            events.append(_event("info", "Round budget reached",
                                 f"{MAX_ROUNDS} rounds", None, None))

    # Slot fill happens HERE, after the loop — the model never saw these values.
    reply = _fill_slots(reply_text.strip() or "I couldn't compose a reply from the record.",
                        ex.slots.as_dict())
    return {
        "reply": reply,
        "proposed_actions": proposals,
        "events": events,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "rounds": rounds,
        },
    }
