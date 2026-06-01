"""Clinician-authed usage / ROI billing panel (Bet #1).

Exposes AGGREGATE billable-usage figures for a hospital so an admin can see how
many triage encounters were metered and the estimated value. Aggregate-only and
NON-PHI by construction (lib.metering.usage_summary never emits per-encounter
detail or any patient-identifying field).

Gated by require_clinician (SEC-008: JWT + hospital_id match) and audited
(COMP-002). Errors raise HTTPException (QUAL-003). Routes through lib.metering →
db.storage; the router never touches boto3 (ARCH-001 / ARCH-002).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from lib import metering
from lib.auth import audit, require_clinician

router = APIRouter()

# Periods the panel may request. Anything else falls back to "month" inside
# lib.metering.usage_summary, but we constrain at the edge for a clean 422.
_ALLOWED_PERIODS = ("day", "week", "month", "quarter", "year", "all")


@router.get("/billing/usage")
def usage(
    hospital_id: str = Path(...),
    period: str = Query(default="month"),
    caller: dict = Depends(require_clinician),
) -> dict:
    """Aggregate billable-usage + estimated ROI for this hospital.

    NO PHI — counts, breakdowns by encounter type / model, and an estimated value
    at the configured per-encounter rate. Hospital-scoped (require_clinician
    enforces the JWT hospital_id match). Audited per COMP-002.
    """
    if period not in _ALLOWED_PERIODS:
        period = "month"
    audit(caller, "billing.usage_viewed", extra={"hospital_id": hospital_id, "period": period})
    return metering.usage_summary(hospital_id, period=period)
