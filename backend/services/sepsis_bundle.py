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

# Honest synthetic-data provenance stamp attached to every result. The bundle
# evaluator is deterministic timestamp arithmetic, but the demonstration
# encounters Solace ships are synthetic; subgroup compliance gaps surfaced by
# bias_audit reflect synthetic case mix, not a real labeled cohort.
_PROVENANCE = {
    "data_source": "synthetic",
    "logic": "deterministic SSC-2021 1-hour bundle timestamp checks",
    "validated_on_real_cohort": False,
    "intended_use": "quality-improvement decision support — not a billing or "
                    "regulatory attestation of compliance",
    "note": "Re-run the cohort audit on real, labeled encounter data before "
            "drawing conclusions about subgroup compliance disparities.",
}


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
        "provenance": _PROVENANCE,
    }


def cohort_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate compliance across many encounter evaluations."""
    if not evaluations:
        return {"count": 0, "compliance_rate": 0, "median_min_to_abx": None,
                "median_min_to_lactate": None, "provenance": _PROVENANCE}
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
        "provenance": _PROVENANCE,
    }


def bias_audit(
    encounters: list[dict[str, Any]],
    *,
    strata: tuple[str, ...] = ("sex", "age_group", "race", "language"),
    disparity_threshold: float = 0.15,
) -> dict[str, Any]:
    """Audit sepsis-bundle compliance for disparities across demographic strata.

    Parallel to `early_warning.bias_audit`: this evaluates the 1-hour bundle for
    every encounter, groups by each demographic stratum, and flags any subgroup
    whose mean bundle-compliance rate or time-to-antibiotics deviates from the
    cohort baseline by more than `disparity_threshold` (relative).

    Each encounter is a dict of `evaluate_encounter` kwargs plus demographic keys
    (`sex`, `age_group`, `race`, `language`, ...). Missing demographics bucket as
    "unknown". Differential time-to-treatment by race/language is a documented
    equity concern in sepsis care; this surface makes it visible at the CMO
    dashboard level.

    Descriptive, not causal — and computed on synthetic data (see `provenance`).
    A flagged subgroup is a prompt to investigate staffing, triage, and access,
    not proof of bias.
    """
    demo_keys = set(strata)

    scored: list[dict[str, Any]] = []
    errors = 0
    for enc in encounters:
        demo = {k: (enc.get(k) or "unknown") for k in demo_keys}
        kwargs = {k: v for k, v in enc.items() if k not in demo_keys}
        try:
            result = evaluate_encounter(**kwargs)
        except Exception as exc:
            errors += 1
            log.warning("sepsis_bundle.bias_audit: skipped malformed encounter: %s", exc)
            continue
        if "error" in result:
            errors += 1
            continue
        abx_min = None
        for el in result.get("elements", []):
            if el["id"] == "antibiotics":
                abx_min = el.get("minutes")
        scored.append({
            "demo": demo,
            "compliance_rate": result.get("compliance_rate", 0.0),
            "all_complete": result.get("all_complete", False),
            "abx_min": abx_min,
        })

    n = len(scored)
    if n == 0:
        return {"count": 0, "errors": errors, "strata": {}, "flags": [],
                "provenance": _PROVENANCE}

    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    baseline_compliance = mean([s["compliance_rate"] for s in scored])
    baseline_abx = mean([s["abx_min"] for s in scored if s["abx_min"] is not None])

    strata_report: dict[str, Any] = {}
    flags: list[dict[str, Any]] = []

    for key in strata:
        groups: dict[str, list[dict[str, Any]]] = {}
        for s in scored:
            groups.setdefault(str(s["demo"][key]), []).append(s)

        group_rows = []
        for gname, members in sorted(groups.items()):
            gn = len(members)
            gcompliance = mean([m["compliance_rate"] for m in members])
            g_abx_vals = [m["abx_min"] for m in members if m["abx_min"] is not None]
            gabx = mean(g_abx_vals) if g_abx_vals else None

            comp_disp = (
                abs(gcompliance - baseline_compliance) / baseline_compliance
                if baseline_compliance else 0.0
            )
            abx_disp = (
                abs(gabx - baseline_abx) / baseline_abx
                if (gabx is not None and baseline_abx) else 0.0
            )
            flagged = (
                gn >= 5
                and (comp_disp > disparity_threshold or abx_disp > disparity_threshold)
            )
            row = {
                "group": gname,
                "n": gn,
                "mean_compliance_rate": round(gcompliance, 3),
                "mean_min_to_abx": round(gabx, 1) if gabx is not None else None,
                "compliance_disparity": round(comp_disp, 3),
                "abx_time_disparity": round(abx_disp, 3),
                "flagged": flagged,
                "underpowered": gn < 5,
            }
            group_rows.append(row)
            if flagged:
                flags.append({
                    "stratum": key,
                    "group": gname,
                    "reason": (
                        f"compliance deviates {comp_disp:.0%} / time-to-abx "
                        f"deviates {abx_disp:.0%} from cohort baseline "
                        f"(threshold {disparity_threshold:.0%})"
                    ),
                })
        strata_report[key] = {
            "baseline_mean_compliance_rate": round(baseline_compliance, 3),
            "baseline_mean_min_to_abx": round(baseline_abx, 1) if baseline_abx else None,
            "groups": group_rows,
        }

    return {
        "count": n,
        "errors": errors,
        "disparity_threshold": disparity_threshold,
        "strata": strata_report,
        "flags": flags,
        "equitable": len(flags) == 0,
        "interpretation": (
            "No subgroup exceeds the bundle-compliance disparity threshold."
            if not flags else
            f"{len(flags)} subgroup(s) flagged — investigate triage, staffing, "
            "and access pathways for these populations."
        ),
        "provenance": _PROVENANCE,
    }
