"""Public governance + transparency endpoints.

No auth required — model cards and the override metrics summary are intentionally
public so procurement teams, CMIOs, and auditors can review them on the website
or paste them into RFP responses.

Per HTI-1 DSI transparency requirements (effective 2025).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

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
