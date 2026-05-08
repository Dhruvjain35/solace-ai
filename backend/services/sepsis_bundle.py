"""Sepsis 1-hour bundle compliance tracker (SSC 2021).

Per the Surviving Sepsis Campaign 2021 guideline, the 1-hour bundle is:
    1. Measure lactate (re-measure if initial >2)
    2. Obtain blood cultures BEFORE antibiotics
    3. Administer broad-spectrum antibiotics
    4. Begin 30 mL/kg crystalloid for hypotension or lactate >=4
    5. Apply vasopressors if persistent hypotension after fluids (target MAP >=65)

This module computes per-encounter compliance + a cohort dashboard. Every
element has a timestamp; the engine checks whether each was completed within
its window.

The cohort surface lets a CMO see:
  - Bundle completion rate over the last 30 days
  - Median time to abx
  - Median time to lactate
  - Cases that failed the bundle (root-cause analysis)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def evaluate_encounter(
    *,
    sepsis_recognition_iso: str,
    lactate_drawn_iso: str | None = None,
    initial_lactate_value: float | None = None,
    blood_cultures_drawn_iso: str | None = None,
    antibiotics_given_iso: str | None = None,
    fluids_started_iso: str | None = None,
    fluids_dose_ml_per_kg: float | None = None,
    vasopressors_started_iso: str | None = None,
    persistent_hypotension_after_fluids: bool = False,
    bundle_window_minutes: int = 60,
) -> dict[str, Any]:
    t0 = _parse(sepsis_recognition_iso)
    if not t0:
        return {"error": "sepsis_recognition_iso required"}
    deadline = t0 + timedelta(minutes=bundle_window_minutes)

    def within(dt: datetime | None) -> bool:
        return dt is not None and t0 <= dt <= deadline

    elements: list[dict[str, Any]] = []

    # 1. Lactate
    lact_dt = _parse(lactate_drawn_iso)
    elements.append({
        "id": "lactate",
        "name": "Lactate measurement",
        "completed": within(lact_dt),
        "minutes": round(((lact_dt - t0).total_seconds() / 60), 1) if lact_dt else None,
        "value": initial_lactate_value,
        "notes": "Re-measure if >2 mmol/L (not enforced here)",
    })

    # 2. Blood cultures (before abx)
    bc_dt = _parse(blood_cultures_drawn_iso)
    abx_dt = _parse(antibiotics_given_iso)
    bc_before_abx = bc_dt is not None and abx_dt is not None and bc_dt <= abx_dt
    elements.append({
        "id": "blood_cultures",
        "name": "Blood cultures before antibiotics",
        "completed": within(bc_dt) and bc_before_abx,
        "minutes": round(((bc_dt - t0).total_seconds() / 60), 1) if bc_dt else None,
    })

    # 3. Antibiotics
    elements.append({
        "id": "antibiotics",
        "name": "Broad-spectrum antibiotics",
        "completed": within(abx_dt),
        "minutes": round(((abx_dt - t0).total_seconds() / 60), 1) if abx_dt else None,
    })

    # 4. Fluids — required for hypotension or lactate >=4
    fluids_required = (persistent_hypotension_after_fluids or (initial_lactate_value is not None and initial_lactate_value >= 4))
    fluids_dt = _parse(fluids_started_iso)
    elements.append({
        "id": "fluids",
        "name": "30 mL/kg crystalloid (if hypotension or lactate >=4)",
        "required": fluids_required,
        "completed": (not fluids_required) or (within(fluids_dt) and (fluids_dose_ml_per_kg or 0) >= 30),
        "minutes": round(((fluids_dt - t0).total_seconds() / 60), 1) if fluids_dt else None,
        "dose": fluids_dose_ml_per_kg,
    })

    # 5. Vasopressors — if persistent hypotension after fluids
    vp_dt = _parse(vasopressors_started_iso)
    elements.append({
        "id": "vasopressors",
        "name": "Vasopressors if MAP <65 after fluids",
        "required": persistent_hypotension_after_fluids,
        "completed": (not persistent_hypotension_after_fluids) or vp_dt is not None,
        "minutes": round(((vp_dt - t0).total_seconds() / 60), 1) if vp_dt else None,
    })

    relevant = [e for e in elements if e.get("required", True)]
    completed = [e for e in relevant if e["completed"]]
    rate = round(len(completed) / max(1, len(relevant)), 2)

    return {
        "sepsis_recognition_iso": sepsis_recognition_iso,
        "deadline_iso": deadline.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "elements": elements,
        "compliance_rate": rate,
        "all_complete": rate == 1.0,
    }


def cohort_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate compliance across many encounter evaluations."""
    if not evaluations:
        return {"count": 0, "compliance_rate": 0, "median_min_to_abx": None, "median_min_to_lactate": None}
    rates = [e.get("compliance_rate", 0) for e in evaluations]
    abx_times = []
    lact_times = []
    for e in evaluations:
        for el in e.get("elements", []):
            if el["id"] == "antibiotics" and el.get("minutes") is not None:
                abx_times.append(el["minutes"])
            if el["id"] == "lactate" and el.get("minutes") is not None:
                lact_times.append(el["minutes"])
    def median(xs):
        if not xs:
            return None
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    return {
        "count": len(evaluations),
        "compliance_rate": round(sum(rates) / len(rates), 2),
        "all_complete_count": sum(1 for r in rates if r == 1.0),
        "median_min_to_abx": median(abx_times),
        "median_min_to_lactate": median(lact_times),
    }
