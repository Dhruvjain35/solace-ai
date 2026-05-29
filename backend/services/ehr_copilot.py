"""EHR Copilot — an agentic assistant that crawls the chart and answers.

A clinician asks a question ("any prior cardiac workup? on anticoagulants?")
and the Copilot runs a Claude tool-use loop where the tools are the existing
FHIR-read layer and the clinical engines. It crawls only what it needs, cites
the resources it read, and never invents data it did not retrieve.

Capabilities (one service, four entry points):
  - ask()          — grounded Q&A over the chart, with citations.
  - summary()      — "catch me up": longitudinal synthesis of the record.
  - scan()         — proactive fixable-issue finder (care gaps, drug
                     interactions, abnormal/overdue results) via the engines.
  - autopopulate() — EHR-vs-chart field diff for a review/accept UI.

HIPAA: every chart access goes through the BAA-covered read path and is
recorded in the returned ``sources`` trace (the router writes the audit row).
On real PHI the model MUST run on Bedrock (BAA); the demo/synthetic sandbox is
safe on any provider. Tool results are truncated before they reach the model so
we send the minimum PHI necessary to answer.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from db import storage
from lib import claude
from lib.claude import ToolUseBlock
from lib.config import settings
from services import drug_interactions, fhir_patient_search, hedis

log = logging.getLogger(__name__)

_MAX_ITERS = 6
_TOOL_RESULT_CHARS = 4000


# ---------------------------------------------------------------------------
# Patient context — one cheap load, the tools read slices from it
# ---------------------------------------------------------------------------

def _parse_medical_info(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        # tolerate comma / newline separated free text
        return [p.strip() for p in value.replace("\n", ",").split(",") if p.strip()]
    return []


def build_context(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Load the Solace patient + parse the intake chart into a working context.

    The linked FHIR record is fetched lazily by the ``crawl_full_record`` tool
    so a simple question costs zero external EHR calls."""
    patient = storage.get_patient(patient_id) or {}
    info = _parse_medical_info(patient.get("medical_info"))
    chart = {
        "name": patient.get("name") or info.get("name") or "",
        "age": info.get("age") or patient.get("patient_age"),
        "sex": info.get("sex") or info.get("gender") or "",
        "chief_complaint": patient.get("chief_complaint") or patient.get("complaint") or "",
        "conditions": _as_list(info.get("conditions") or info.get("medical_conditions") or info.get("history")),
        "medications": _as_list(info.get("medications") or info.get("meds")),
        "allergies": _as_list(info.get("allergies")),
        "transcript": patient.get("transcript") or "",
        "vitals": patient.get("vitals") or info.get("vitals") or {},
        "esi_level": patient.get("esi_level") or patient.get("triage_level"),
    }
    return {
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "patient": patient,
        "chart": chart,
        "ehr_record": None,      # populated by crawl_full_record
        "sources": [],           # citation/audit trace
    }


# ---------------------------------------------------------------------------
# Tools the agent can call
# ---------------------------------------------------------------------------

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_chart_overview",
        "description": "Current encounter snapshot: demographics, chief complaint, active problem list, current medications, allergies, and recent vitals from the intake chart. Call this first.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "crawl_full_record",
        "description": "Crawl the linked EHR (FHIR) for the longitudinal record: prior encounters, historical conditions, medication history, allergies. Use when the question needs history not in the current chart (e.g. 'prior cardiac workup', 'past admissions').",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_drug_interactions",
        "description": "Run the full drug-interaction and allergy-contraindication panel on the patient's current medications. Optionally include a proposed new drug.",
        "input_schema": {
            "type": "object",
            "properties": {
                "proposed_drug": {"type": "string", "description": "optional new medication being considered"}
            },
        },
    },
    {
        "name": "find_care_gaps",
        "description": "Evaluate open preventive/quality care gaps (HEDIS) for this patient — overdue screenings, vaccinations, chronic-care follow-up.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _dispatch(name: str, inp: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool. Records a source entry for citation/audit."""
    chart = ctx["chart"]
    try:
        if name == "get_chart_overview":
            ctx["sources"].append({"tool": name, "resource": "intake_chart"})
            return {
                "name": chart["name"], "age": chart["age"], "sex": chart["sex"],
                "chief_complaint": chart["chief_complaint"],
                "conditions": chart["conditions"], "medications": chart["medications"],
                "allergies": chart["allergies"], "vitals": chart["vitals"],
                "esi_level": chart["esi_level"],
            }

        if name == "crawl_full_record":
            rec = _crawl_ehr(ctx)
            if not rec:
                ctx["sources"].append({"tool": name, "resource": "ehr", "linked": False})
                return {"linked": False, "note": "No linked EHR record found for this patient."}
            ctx["ehr_record"] = rec
            ctx["sources"].append({"tool": name, "resource": "ehr_fhir", "linked": True})
            return {
                "linked": True,
                "demographics": {k: rec.get(k) for k in ("name", "dob", "sex", "primary_care_provider")},
                "conditions": rec.get("conditions", []),
                "medications": rec.get("medications", []),
                "allergies": rec.get("allergies", []),
                "prior_visits": rec.get("prior_visits", []),
                "source": rec.get("source"),
            }

        if name == "check_drug_interactions":
            meds = list(chart["medications"])
            proposed = (inp or {}).get("proposed_drug")
            if proposed:
                meds.append(str(proposed))
            ctx["sources"].append({"tool": name, "resource": "drug_interactions"})
            return drug_interactions.check(meds, allergies=chart["allergies"], complaint=chart["chief_complaint"])

        if name == "find_care_gaps":
            ctx["sources"].append({"tool": name, "resource": "hedis"})
            return {"gaps": hedis.evaluate(_hedis_patient(ctx))}

        return {"error": f"unknown tool {name}"}
    except Exception as e:  # noqa: BLE001 — a tool failure must not crash the agent
        log.warning("copilot tool %s failed: %s", name, e)
        return {"error": f"{name} failed: {str(e)[:160]}"}


def _crawl_ehr(ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch the linked FHIR record. Prefers a stored FHIR id, else demographics."""
    patient = ctx["patient"]
    fhir_id = patient.get("ehr_fhir_id")
    try:
        if fhir_id:
            bundle = fhir_patient_search._search("Patient", {"_id": fhir_id})
            entries = bundle.get("entry") or []
            if entries:
                return fhir_patient_search._enrich_patient(entries[0].get("resource") or {})
        chart = ctx["chart"]
        name = (chart.get("name") or "").split()
        if len(name) >= 2:
            rec = fhir_patient_search.match_by_demographics(
                {"first_name": name[0], "last_name": name[-1], "dob": (ctx["patient"].get("dob") or "")}
            )
            if rec and rec.get("record"):
                return rec["record"]
    except Exception as e:  # noqa: BLE001
        log.info("copilot EHR crawl failed: %s", e)
    return None


def _hedis_patient(ctx: dict[str, Any]) -> dict[str, Any]:
    """Map our chart into the shape hedis.evaluate expects."""
    chart = ctx["chart"]
    conditions = list(chart["conditions"])
    if ctx.get("ehr_record"):
        conditions += [c.get("display") if isinstance(c, dict) else str(c)
                       for c in (ctx["ehr_record"].get("conditions") or [])]
    return {
        "age": chart.get("age") or 0,
        "sex": chart.get("sex") or "",
        "history": {"conditions": [c for c in conditions if c]},
    }


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _content_to_dicts(content: list) -> list[dict[str, Any]]:
    """Rebuild an assistant turn's content blocks for the next request."""
    out: list[dict[str, Any]] = []
    for b in content:
        if isinstance(b, ToolUseBlock):
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        elif getattr(b, "text", ""):
            out.append({"type": "text", "text": b.text})
    return out


def _run_agent(system: str, user: str, ctx: dict[str, Any], *, max_tokens: int = 1200) -> dict[str, Any]:
    """Drive the tool-use conversation until the model answers (or hits the cap)."""
    if not claude.available():
        return {"answer": "", "sources": [], "error": "AI backend unavailable"}
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    final_text = ""
    for _ in range(_MAX_ITERS):
        resp = claude.messages_create(
            model=settings.model_clinical, max_tokens=max_tokens, system=system,
            messages=messages, tools=_TOOLS, purpose="ehr_copilot",
        )
        tool_uses = [b for b in resp.content if isinstance(b, ToolUseBlock)]
        final_text = "".join(getattr(b, "text", "") for b in resp.content).strip() or final_text
        if not tool_uses:
            break
        messages.append({"role": "assistant", "content": _content_to_dicts(resp.content)})
        results = []
        for tu in tool_uses:
            out = _dispatch(tu.name, tu.input or {}, ctx)
            results.append({
                "type": "tool_result", "tool_use_id": tu.id,
                "content": json.dumps(out)[:_TOOL_RESULT_CHARS],
            })
        messages.append({"role": "user", "content": results})
    return {"answer": final_text, "sources": ctx["sources"]}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

_ASK_SYSTEM = """You are an EHR Copilot for an emergency clinician. Answer the question using ONLY data you retrieve with the tools — never invent labs, meds, or history. Call get_chart_overview first; call crawl_full_record when history is needed. Be concise and clinical. If the record does not contain the answer, say so plainly. End with a one-line 'Sources:' noting which parts of the record you used."""

_SUMMARY_SYSTEM = """You are an EHR Copilot. Produce a tight "catch me up" summary for a clinician picking up this patient. Use the tools to crawl the chart and the longitudinal record. Structure: (1) one-line snapshot, (2) active problems + meds + allergies, (3) relevant history/prior encounters, (4) what to watch. Only state what the tools return; do not fabricate."""


def ask(hospital_id: str, patient_id: str, question: str) -> dict[str, Any]:
    ctx = build_context(hospital_id, patient_id)
    user = f"Clinician question about this patient: {question.strip()}"
    return _run_agent(_ASK_SYSTEM, user, ctx, max_tokens=1200)


def summary(hospital_id: str, patient_id: str) -> dict[str, Any]:
    ctx = build_context(hospital_id, patient_id)
    user = "Give me the catch-me-up summary for this patient."
    return _run_agent(_SUMMARY_SYSTEM, user, ctx, max_tokens=1500)


def scan(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Deterministic fixable-issue finder — runs the engines directly (no model
    needed) so results are reliable and auditable, then returns structured,
    actionable items grouped by type."""
    ctx = build_context(hospital_id, patient_id)
    chart = ctx["chart"]
    items: list[dict[str, Any]] = []

    # 1. Drug interactions / allergy contraindications
    try:
        if chart["medications"]:
            di = drug_interactions.check(chart["medications"], allergies=chart["allergies"],
                                         complaint=chart["chief_complaint"])
            for issue in (di.get("drug_drug") or [])[:10]:
                items.append({
                    "type": "drug_interaction", "severity": issue.get("severity", "moderate"),
                    "title": f"{issue.get('a', '?')} + {issue.get('b', '?')}",
                    "detail": issue.get("reason") or "", "action": "Review medications",
                })
            for issue in (di.get("drug_allergy") or [])[:10]:
                items.append({
                    "type": "allergy_contraindication", "severity": issue.get("severity", "high"),
                    "title": f"{issue.get('drug') or issue.get('a', '?')} vs allergy",
                    "detail": issue.get("reason") or "", "action": "Verify allergy before ordering",
                })
            ctx["sources"].append({"tool": "scan.drug_interactions", "resource": "drug_interactions"})
    except Exception as e:  # noqa: BLE001
        log.warning("scan drug_interactions failed: %s", e)

    # 2. HEDIS care gaps
    try:
        for gap in hedis.evaluate(_hedis_patient(ctx))[:10]:
            items.append({
                "type": "care_gap", "severity": gap.get("priority", "medium"),
                "title": gap.get("name") or gap.get("measure") or "Care gap",
                "detail": gap.get("description") or "", "action": gap.get("action") or "",
                "icd10": gap.get("icd10"),
            })
        ctx["sources"].append({"tool": "scan.care_gaps", "resource": "hedis"})
    except Exception as e:  # noqa: BLE001
        log.warning("scan care_gaps failed: %s", e)

    order = {"high": 0, "critical": 0, "moderate": 1, "medium": 1, "low": 2}
    items.sort(key=lambda x: order.get(str(x.get("severity", "")).lower(), 1))
    return {"count": len(items), "items": items, "sources": ctx["sources"]}


def autopopulate(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Crawl the linked EHR and produce a per-field diff (EHR value vs current
    chart value) for a review/accept UI. Read-only — proposes, never writes."""
    ctx = build_context(hospital_id, patient_id)
    rec = _crawl_ehr(ctx)
    if not rec:
        return {"linked": False, "fields": [], "note": "No linked EHR record to populate from."}

    chart = ctx["chart"]

    def _names(items: Any) -> list[str]:
        out = []
        for it in items or []:
            if isinstance(it, dict):
                out.append(it.get("display") or it.get("name") or it.get("text") or "")
            else:
                out.append(str(it))
        return [x for x in out if x]

    fields = [
        _diff_field("allergies", chart["allergies"], _names(rec.get("allergies"))),
        _diff_field("medications", chart["medications"], _names(rec.get("medications"))),
        _diff_field("conditions", chart["conditions"], _names(rec.get("conditions"))),
    ]
    return {
        "linked": True, "source": rec.get("source"),
        "demographics": {k: rec.get(k) for k in ("name", "dob", "sex", "primary_care_provider")},
        "prior_visits": rec.get("prior_visits", []),
        "fields": [f for f in fields if f],
    }


def _diff_field(name: str, current: list[str], ehr: list[str]) -> dict[str, Any] | None:
    cur_low = {c.lower() for c in current}
    additions = [e for e in ehr if e.lower() not in cur_low]
    if not ehr and not current:
        return None
    return {
        "field": name,
        "current": current,
        "ehr": ehr,
        "additions": additions,          # in EHR, not yet on the chart
        "has_changes": bool(additions),
    }
