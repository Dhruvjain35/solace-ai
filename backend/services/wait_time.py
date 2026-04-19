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
Final estimate is clamped to [0, 180 min] and rounded to the nearest 5.
"""
from __future__ import annotations

from typing import Iterable

_BASE_MINUTES = {1: 0, 2: 10, 3: 30, 4: 60, 5: 90}
_SERVICE_MINUTES = {1: 15, 2: 20, 3: 25, 4: 15, 5: 10}


def estimate_minutes(
    patient_esi: int,
    queue: Iterable[dict],
) -> int:
    """Return an estimated wait in minutes for a patient with `patient_esi`.

    `queue` = list of patient dicts currently in "waiting" status (NOT including the
    subject patient). Each dict just needs an `esi_level` key.
    """
    ahead = [
        p for p in queue
        if p.get("status") == "waiting"
        and isinstance(p.get("esi_level"), int)
        and p["esi_level"] <= patient_esi
    ]
    queue_time = sum(_SERVICE_MINUTES.get(int(p["esi_level"]), 20) for p in ahead)
    base = _BASE_MINUTES.get(int(patient_esi), 30)
    est = max(base, queue_time)
    est = min(est, 180)
    # Round to nearest 5 for display — exact minute precision overstates certainty
    return int(round(est / 5.0) * 5)


def format_range(minutes: int) -> str:
    """Human-readable wait range, e.g. '20-30 min' or 'less than 5 min'."""
    if minutes <= 5:
        return "less than 5 min"
    lower = max(5, minutes - 5)
    upper = minutes + 5
    return f"{lower}-{upper} min"
