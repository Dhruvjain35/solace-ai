"""EHR Copilot — four entry points over the PHI-isolation layer.

  - ask()          — grounded Q&A. Plan -> Execute -> Narrate; the model reasons
                     over coded outputs only (see services/copilot/).
  - summary()      — "catch me up": the same pipeline with a handoff plan hint.
  - scan()         — deterministic fixable-issue finder (engines only, no model).
  - autopopulate() — deterministic EHR-vs-chart field diff for a review UI.

HIPAA: ask()/summary() never send raw PHI to the model — it sees coded
flags/codes/scores and binds real values by reference; the deterministic layer
renders them for the clinician. scan()/autopopulate() are model-free: they run
the engines / diff directly and return structured results to the clinician UI.
Every call is audited by the router.
"""
from __future__ import annotations

import logging
from typing import Any

from services import copilot, drug_interactions, hedis
from services.copilot import context
from services.copilot.executor import _crawl_ehr

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model-backed entry points — delegate to the PHI-isolation pipeline
# ---------------------------------------------------------------------------

def ask(hospital_id: str, patient_id: str, question: str) -> dict[str, Any]:
    return copilot.answer_question(hospital_id, patient_id, question)


def summary(hospital_id: str, patient_id: str) -> dict[str, Any]:
    return copilot.catch_me_up(hospital_id, patient_id)


# ---------------------------------------------------------------------------
# Deterministic entry points — no model involved
# ---------------------------------------------------------------------------

def _hedis_patient(ctx: dict[str, Any]) -> dict[str, Any]:
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


def scan(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Deterministic fixable-issue finder — runs the engines directly (no model)
    so results are reliable and auditable, grouped and severity-sorted."""
    ctx = context.build_chart(hospital_id, patient_id)
    chart = ctx["chart"]
    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

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
            sources.append({"resource": "drug_interactions"})
    except Exception as e:  # noqa: BLE001
        log.warning("scan drug_interactions failed: %s", e)

    try:
        for gap in hedis.evaluate(_hedis_patient(ctx))[:10]:
            items.append({
                "type": "care_gap", "severity": gap.get("priority", "medium"),
                "title": gap.get("name") or gap.get("measure") or "Care gap",
                "detail": gap.get("description") or "", "action": gap.get("action") or "",
                "icd10": gap.get("icd10"),
            })
        sources.append({"resource": "hedis"})
    except Exception as e:  # noqa: BLE001
        log.warning("scan care_gaps failed: %s", e)

    order = {"high": 0, "critical": 0, "moderate": 1, "medium": 1, "low": 2}
    items.sort(key=lambda x: order.get(str(x.get("severity", "")).lower(), 1))
    return {"count": len(items), "items": items, "sources": sources}


def autopopulate(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Crawl the linked EHR and produce a per-field diff (EHR value vs current
    chart value) for a clinician review/accept UI. Read-only — proposes, never
    writes. Clinician-facing, so it surfaces real values directly (no model)."""
    ctx = context.build_chart(hospital_id, patient_id)
    rec = _crawl_ehr(ctx)
    if not rec:
        return {"linked": False, "fields": [], "note": "No linked EHR record to populate from."}

    chart = ctx["chart"]

    def _names(its: Any) -> list[str]:
        out = []
        for it in its or []:
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
        "field": name, "current": current, "ehr": ehr,
        "additions": additions, "has_changes": bool(additions),
    }
