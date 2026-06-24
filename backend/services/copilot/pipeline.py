"""Plan -> Execute -> Narrate orchestration.

Two model calls, both with fully controlled input:
  Pass 1 (plan):    catalog + question            -> QueryPlan (coded vocab only)
  Pass 2 (narrate): structured results + palette   -> artifact tree (refs only)

Between them sits the deterministic zone: gate -> executor -> (real PHI) ->
coded results + slot map. The slot map is returned to the router for rendering
and never enters a model call.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from lib import claude, content_guard
from lib.config import settings
from lib.json_extract import extract_obj
from services.copilot import artifacts, catalog, context, gate, registry
from services.copilot.executor import Executor

log = logging.getLogger(__name__)

_PLAN_MAX_TOKENS = 900
_NARRATE_MAX_TOKENS = 1500


def _plan_system() -> str:
    return (
        "You are the PLANNER for an EHR Copilot. You never see raw patient data. "
        "Given the clinician's question and the metadata catalog below, decide which "
        "primitives to run to answer it, and emit a QueryPlan as JSON only.\n\n"
        "RULES:\n"
        "- Output ONLY a JSON object: {\"reasoning\": str, \"steps\": [{\"id\": str, "
        "\"primitive\": str, \"params\": {...}}]}.\n"
        "- Use only primitives and param values from the catalog. Params are coded "
        "vocabulary, never free text or patient values.\n"
        "- Pick the minimum set of primitives needed. Prefer feature.flag / "
        "feature.category for simple facts; use ehr.* for history; clinical.differential "
        "for diagnostic reasoning; engine.* for interactions / care gaps.\n\n"
        f"SCHEMA:\n{json.dumps(catalog.schema_card())}\n\n"
        f"PRIMITIVES:\n{json.dumps(registry.planner_catalog())}"
    )


def _narrate_system(allow_replan: bool) -> str:
    palette = {name: sorted(fields) for name, fields in artifacts.COMPONENTS.items()}
    replan = (
        "- If (and only if) the results are insufficient to answer, you may instead "
        "emit {\"need\": [ {\"id\":..., \"primitive\":..., \"params\":...} ]} ONCE to "
        "fetch more data (same plan format / vocabulary). You will receive the new "
        "results and must then produce blocks.\n"
        if allow_replan else
        "- You have all the data you will get; produce blocks now even if incomplete.\n"
    )
    return (
        "You are the NARRATOR for an EHR Copilot. You receive only STRUCTURED, coded "
        "results from the planner's primitives — never raw patient data. Compose a "
        "clinical, scannable answer as an artifact tree of interactive blocks.\n\n"
        "RULES:\n"
        "- Output ONLY a JSON object: {\"blocks\": [ ... ]}.\n"
        "- Bind data BY REFERENCE using *_ref fields that point at a result path like "
        "\"<step_id>.<field>\" (e.g. \"s2.items\"). Never inline data values.\n"
        "- Real patient values appear in results as {\"$slot\": \"S#\", \"label\": ...}. "
        "To show one in prose, write the token {S#} in a text/callout field; it is filled "
        "for the clinician automatically. Never guess a real value.\n"
        "- Lead with a one-line callout answering the question. Add tables/timelines/"
        "risk_gauge/differential blocks where they make the answer clearer.\n"
        f"{replan}"
        "- Be concise and clinical.\n\n"
        f"COMPONENT PALETTE (type -> allowed fields):\n{json.dumps(palette)}"
    )


def _narrate_call(safe_q: str, results: list[dict], *, allow_replan: bool) -> dict:
    try:
        resp = claude.messages_create(
            model=settings.model_clinical, max_tokens=_NARRATE_MAX_TOKENS,
            system=_narrate_system(allow_replan),
            messages=[{"role": "user",
                       "content": f"Question: {safe_q}\n\nResults:\n{json.dumps(results)}"}],
            purpose="copilot_narrate",
        )
        return extract_obj("".join(getattr(b, "text", "") for b in resp.content)) or {"blocks": []}
    except Exception as e:  # noqa: BLE001
        log.warning("copilot narration failed: %s", e)
        return {"blocks": []}


def _run(entry: str, hospital_id: str, patient_id: str, question: str,
         *, plan_hint: str) -> dict[str, Any]:
    if not claude.available():
        return {"answer": "", "blocks": [], "slots": {}, "plan": None,
                "sources": [], "error": "AI backend unavailable"}

    # Defence in depth: scrub the free-text question before it reaches the model.
    safe_q = question
    if question:
        ok, cleaned, _findings = content_guard.scan(question, label="copilot.question")
        if not ok:
            return _refusal("That request can't be processed.")
        safe_q = cleaned
    ctx = context.build_chart(hospital_id, patient_id)
    ex = Executor(ctx)

    # -- Pass 1: plan --------------------------------------------------------
    try:
        plan_resp = claude.messages_create(
            model=settings.model_clinical, max_tokens=_PLAN_MAX_TOKENS,
            system=_plan_system(),
            messages=[{"role": "user", "content": f"{plan_hint}\nClinician question: {safe_q}"}],
            purpose="copilot_plan",
        )
        plan_raw = extract_obj("".join(getattr(b, "text", "") for b in plan_resp.content))
        plan = gate.validate(plan_raw)
    except gate.PlanRejected as e:
        log.info("copilot plan rejected: %s", e)
        return _refusal(f"I can't answer that from the record ({e}).")
    except Exception as e:  # noqa: BLE001
        log.warning("copilot planning failed: %s", e)
        return _refusal("I couldn't form a safe query plan for that question.")

    # -- Execute (deterministic, touches PHI) --------------------------------
    results = ex.run(plan)

    # -- Pass 2: narrate, with one optional bounded replanning round ---------
    tree = _narrate_call(safe_q, results, allow_replan=True)
    need = tree.get("need") if isinstance(tree, dict) else None
    if isinstance(need, list) and need:
        for i, step in enumerate(need):
            if isinstance(step, dict):
                step["id"] = f"r{i + 1}"  # namespace follow-up ids
        try:
            follow = gate.validate({"steps": need})
            results += ex.run(follow)
            plan["steps"] += follow["steps"]  # keep the audit record complete
        except gate.PlanRejected as e:
            log.info("copilot replan rejected: %s", e)
        tree = _narrate_call(safe_q, results, allow_replan=False)

    slots = ex.slots.as_dict()
    blocks = artifacts.hydrate(tree, results, slots)
    answer = artifacts.plain_text(blocks) or "No answer could be composed from the record."
    return {
        "answer": answer,
        "blocks": blocks,
        "slots": slots,
        "plan": plan,            # the auditable minimum-necessary record
        "sources": ex.sources,
        "entry": entry,
    }


def _refusal(msg: str) -> dict[str, Any]:
    return {"answer": msg, "blocks": [{"type": "callout", "text": msg}],
            "slots": {}, "plan": None, "sources": []}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def answer_question(hospital_id: str, patient_id: str, question: str) -> dict[str, Any]:
    return _run("ask", hospital_id, patient_id, question,
                plan_hint="Plan the primitives needed to answer this question.")


def catch_me_up(hospital_id: str, patient_id: str) -> dict[str, Any]:
    return _run("summary", hospital_id, patient_id,
                "Give me a catch-me-up overview of this patient for handoff.",
                plan_hint=("Plan a concise catch-me-up: chart overview features, the "
                           "differential, drug interactions, care gaps, and any linked "
                           "longitudinal history."))
