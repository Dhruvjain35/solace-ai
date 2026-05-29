"""ESI-weighted wait-time estimator.

Given the current queue state for a hospital and the patient's own ESI,
estimate time-to-clinician. Uses published ED door-to-provider benchmarks:
  ESI 1: 0 min (immediate)
  ESI 2: 10 min
  ESI 3: 30 min
  ESI 4: 60 min
  ESI 5: 90 min

Adjusts for queue depth: each patient at the same-or-higher acuity ahead
of you adds their expected service time; patients at lower acuity are ignored.
A staffing factor scales the queue contribution by how many providers are on.
Final estimate is clamped to [0, 180 min] and rounded to the nearest 5.
"""
from __future__ import annotations

from typing import Iterable

_BASE_MINUTES = {1: 0, 2: 10, 3: 30, 4: 60, 5: 90}
_SERVICE_MINUTES = {1: 15, 2: 20, 3: 25, 4: 15, 5: 10}

# Baseline parallelism — the queue model implicitly assumes this many providers
# share the workload. estimate_breakdown() scales against it.
_BASELINE_PROVIDERS = 3


def estimate_minutes(
    patient_esi: int,
    queue: Iterable[dict],
) -> int:
    """Return an estimated wait in minutes for a patient with `patient_esi`.

    `queue` = list of patient dicts currently in "waiting" status (NOT including the
    subject patient). Each dict just needs an `esi_level` key.

    Public signature unchanged — this is the value `patients.py` persists.
    """
    return estimate_breakdown(patient_esi, queue)["estimate_minutes"]


def estimate_breakdown(
    patient_esi: int,
    queue: Iterable[dict],
    *,
    providers_on_shift: int | None = None,
) -> dict:
    """Detailed wait-time estimate with per-ESI breakdown and a confidence signal.

    Returns:
      {
        "estimate_minutes": int,        # rounded, clamped — same value as estimate_minutes()
        "estimate_range": str,          # human-readable, e.g. "20-30 min"
        "base_minutes": int,            # door-to-provider benchmark for this ESI
        "queue_minutes": int,           # staffing-adjusted contribution of patients ahead
        "ahead_count": int,             # patients at same-or-higher acuity ahead
        "per_esi": {esi: {"count", "service_minutes_each", "subtotal_minutes"}},
        "staffing_factor": float,       # <1.0 means extra staff shortens the wait
        "providers_on_shift": int,
        "confidence": str,              # "high" | "moderate" | "low"
        "confidence_reason": str,
      }
    """
    queue_list = list(queue)
    ahead = [
        p for p in queue_list
        if p.get("status") == "waiting"
        and isinstance(p.get("esi_level"), int)
        and p["esi_level"] <= patient_esi
    ]

    # Per-ESI breakdown of who is ahead.
    per_esi: dict[int, dict] = {}
    raw_queue_minutes = 0
    for p in ahead:
        esi = int(p["esi_level"])
        svc = _SERVICE_MINUTES.get(esi, 20)
        raw_queue_minutes += svc
        row = per_esi.setdefault(
            esi, {"count": 0, "service_minutes_each": svc, "subtotal_minutes": 0}
        )
        row["count"] += 1
        row["subtotal_minutes"] += svc

    # Staffing factor: more providers than baseline shortens the queue wait,
    # fewer lengthens it. Bounded to keep the estimate sane.
    providers = providers_on_shift if providers_on_shift and providers_on_shift > 0 else _BASELINE_PROVIDERS
    staffing_factor = max(0.5, min(_BASELINE_PROVIDERS / providers, 2.0))
    queue_minutes = int(round(raw_queue_minutes * staffing_factor))

    base = _BASE_MINUTES.get(int(patient_esi), 30)
    est = max(base, queue_minutes)
    est = min(est, 180)
    estimate_minutes_val = int(round(est / 5.0) * 5)

    confidence, confidence_reason = _confidence(len(ahead), staffing_factor, providers_on_shift)

    return {
        "estimate_minutes": estimate_minutes_val,
        "estimate_range": format_range(estimate_minutes_val),
        "base_minutes": base,
        "queue_minutes": queue_minutes,
        "ahead_count": len(ahead),
        "per_esi": {str(k): per_esi[k] for k in sorted(per_esi)},
        "staffing_factor": round(staffing_factor, 2),
        "providers_on_shift": providers,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
    }


def _confidence(
    ahead_count: int,
    staffing_factor: float,
    providers_on_shift: int | None,
) -> tuple[str, str]:
    """Confidence signal for the estimate.

    A long queue and unknown staffing widen the uncertainty band; a short queue
    with known staffing is the high-confidence case.
    """
    if providers_on_shift is None:
        return "moderate", "Staffing level not reported — estimate uses a baseline."
    if ahead_count >= 12:
        return "low", "A large queue makes the wait harder to predict."
    if staffing_factor >= 1.5:
        return "low", "Reduced staffing widens the uncertainty band."
    if ahead_count <= 4:
        return "high", "Short queue with known staffing — estimate is reliable."
    return "moderate", "Typical queue depth — estimate within a normal band."


def format_range(minutes: int) -> str:
    """Human-readable wait range, e.g. '20-30 min' or 'less than 5 min'."""
    if minutes <= 5:
        return "less than 5 min"
    lower = max(5, minutes - 5)
    upper = minutes + 5
    return f"{lower}-{upper} min"
