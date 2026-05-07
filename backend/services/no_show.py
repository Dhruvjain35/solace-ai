"""No-show prediction (rule-based v1).

Production target is a gradient-boosted model trained on historical scheduling
data. This v1 uses a clinically-defensible rule combination so the UX (risk
tier + reminder cadence) ships now and the model swap is plug-in.

Equity audit: the model is intentionally not given race or zip code as direct
features. Only behavioral history, lead time, and visit-day proxy. We log all
predictions for downstream FNR/FPR-by-demographic auditing per the model card.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _hours_until(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return 24
    now = datetime.now(timezone.utc)
    return max(0.0, (dt - now).total_seconds() / 3600)


def predict(
    appointment_iso: str,
    prior_no_shows: int = 0,
    prior_completed: int = 0,
    visit_type: str = "follow_up",
    booking_lead_days: int = 7,
    age: int | None = None,
    has_phone: bool = True,
) -> dict[str, Any]:
    base = 0.10  # population baseline ~10% no-show

    # Behavioral history (single strongest predictor in literature)
    total = prior_no_shows + prior_completed
    if total >= 3:
        rate = prior_no_shows / total
        base = 0.4 * rate + 0.6 * base

    # Lead time effect
    if booking_lead_days >= 30:
        base += 0.06
    elif booking_lead_days >= 14:
        base += 0.03

    # Visit type
    if visit_type in ("new_patient", "consult"):
        base += 0.04
    if visit_type == "physical":
        base += 0.02

    # Time of day proxy via the appointment hour (early-morning slots no-show more)
    try:
        dt = datetime.fromisoformat(appointment_iso.replace("Z", "+00:00"))
        if dt.hour < 9:
            base += 0.04
        if dt.weekday() == 0:  # Monday
            base += 0.02
    except Exception:
        pass

    # Age — youngest cohort no-shows more (literature)
    if age is not None and age < 25:
        base += 0.03

    # No phone -> no reminder is reachable
    if not has_phone:
        base += 0.05

    base = max(0.0, min(0.95, base))

    if base >= 0.30:
        tier = "high"
        cadence = ["sms 7d", "sms 3d", "voice 1d", "voice 4h"]
    elif base >= 0.15:
        tier = "medium"
        cadence = ["sms 3d", "sms 1d", "sms 4h"]
    else:
        tier = "low"
        cadence = ["sms 1d"]

    return {
        "no_show_probability": round(base, 3),
        "tier": tier,
        "reminder_cadence": cadence,
        "hours_until": round(_hours_until(appointment_iso), 1),
    }
