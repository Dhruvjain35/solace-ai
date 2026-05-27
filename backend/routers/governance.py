"""Public governance + transparency endpoints.

No auth required — model cards, the bias audit, the transparency summary, and
the override metrics/log are intentionally public so procurement teams, CMIOs,
and auditors can review them on the website or paste them into RFP responses.

Per HTI-1 DSI transparency requirements (45 CFR 170.315(b)(11), effective 2025).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query

from lib import provenance
from services import model_cards

router = APIRouter()


@router.get("/api/model-cards")
def list_cards():
    return {"cards": model_cards.list_cards()}


@router.get("/api/model-cards/{card_id}")
def get_card(card_id: str = Path(...)):
    card = model_cards.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="not found")
    return card


@router.get("/api/governance/override-metrics")
def override_metrics():
    return provenance.metrics()


@router.get("/api/governance/bias-audit")
def bias_audit():
    """Full HTI-1 bias audit — methodology, risk tiers, and a per-model block
    with the empty-but-structured demographic-performance table."""
    return model_cards.bias_audit()


@router.get("/api/governance/bias-audit/{model_id}")
def bias_audit_for_model(model_id: str = Path(...)):
    """Bias audit narrowed to a single model. 404 if the model is unknown."""
    try:
        return model_cards.bias_audit(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")


@router.get("/api/governance/transparency-summary")
def transparency_summary():
    """One-page HTI-1 transparency summary across every Solace AI surface."""
    return model_cards.transparency_summary()


@router.get("/api/governance/override-log")
def override_log(
    hospital_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """The AI override decision log (accepted / edited / rejected per model).

    Optionally scoped to a hospital. Backed by lib.provenance.overrides();
    entries carry no PHI beyond an opaque patient_id, so the log is safe to
    expose for auditor review alongside the aggregate override metrics.
    """
    entries = provenance.overrides(hospital_id, limit=limit)
    return {
        "count": len(entries),
        "hospital_id": hospital_id,
        "limit": limit,
        "entries": entries,
        "metrics": provenance.metrics(hospital_id),
    }
