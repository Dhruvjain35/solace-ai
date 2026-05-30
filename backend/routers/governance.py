"""Public governance + transparency endpoints.

No auth required — model cards, the bias audit, the transparency summary, and
the override metrics/log are intentionally public so procurement teams, CMIOs,
and auditors can review them on the website or paste them into RFP responses.

Per HTI-1 DSI transparency requirements (45 CFR 170.315(b)(11), effective 2025).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from lib import provenance
from lib.auth import audit, require_clinician
from services import model_cards

# Fields safe to expose on the PUBLIC override log. Deliberately EXCLUDES
# clinician_id (identifying) and notes (clinician free-text — potential PHI).
# The full raw log is available via the clinician-authed endpoint below.
_PUBLIC_OVERRIDE_FIELDS = ("ts", "hospital_id", "patient_id", "purpose", "model", "decision", "diff_chars")


def _redact_override(entry: dict) -> dict:
    return {k: entry.get(k) for k in _PUBLIC_OVERRIDE_FIELDS if k in entry}

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


@router.get("/api/governance/trust-report")
def trust_report(hospital_id: str | None = Query(default=None)):
    """The PUBLIC Solace Trust Report — aggregate, no-PHI, honestly labeled.

    Assembles model inventory, per-ESI conformal q̂ + empirical coverage, a
    bias/fairness summary, and aggregate override-acceptance into one object
    safe to render on a public website. No auth: the payload is aggregate-only
    by construction and passes a recursive PHI guard before it is returned.

    Calibration figures come from a SYNTHETIC validation cohort with no
    real-world clinical labels; the payload says so (preliminary=true,
    data_provenance='synthetic validation cohort', disclaimer). Optionally
    scoped to a hospital for the aggregate override rates.

    Aggregate-only, so no clinician audit() write is made; nothing here is
    patient- or clinician-identifiable.
    """
    try:
        return model_cards.trust_report(hospital_id)
    except AssertionError as e:
        # The PHI guard tripped — fail closed rather than ship anything.
        raise HTTPException(status_code=500, detail="trust report failed integrity check") from e


@router.get("/api/governance/override-log")
def override_log(
    hospital_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """PUBLIC AI override decision log (accepted / edited / rejected per model).

    Optionally scoped to a hospital. Backed by lib.provenance.overrides() but
    entries are REDACTED to non-identifying fields (clinician_id and the
    free-text notes are stripped — those carry PHI/identity risk and are only
    available via the clinician-authed /override-log/full endpoint). Safe to
    expose to procurement/auditors alongside the aggregate override metrics.
    """
    entries = provenance.overrides(hospital_id, limit=limit)
    return {
        "count": len(entries),
        "hospital_id": hospital_id,
        "limit": limit,
        "entries": [_redact_override(e) for e in entries],
        "redacted": True,
        "metrics": provenance.metrics(hospital_id),
    }


@router.get("/api/governance/{hospital_id}/override-log/full")
def override_log_full(
    hospital_id: str = Path(...),
    limit: int = Query(default=200, ge=1, le=1000),
    caller: dict = Depends(require_clinician),
):
    """CLINICIAN-AUTHED raw override log — full entries incl. clinician_id + notes.

    For internal clinician/auditor review. Gated by require_clinician (SEC-008)
    and audited (COMP-002). Returns the unredacted entries the public endpoint
    withholds.
    """
    audit(caller, "governance.override_log_full", extra={"hospital_id": hospital_id})
    entries = provenance.overrides(hospital_id, limit=limit)
    return {
        "count": len(entries),
        "hospital_id": hospital_id,
        "limit": limit,
        "entries": entries,
        "redacted": False,
        "metrics": provenance.metrics(hospital_id),
    }
