"""Shared medical-info formatter for Claude prompts.

Every Claude-driven service (prebrief, scribe, comfort_protocol, differential,
workup, disposition, prescription) needs to inject the patient's medical info
into a system prompt as a compact, clinical-shorthand string. They were all
hand-rolling the same `_fmt(info)` helper — seven copies that drifted in tiny
ways. One source of truth here, callers import + use.
"""
from __future__ import annotations

from typing import Any


def format_medical_info(info: dict[str, Any] | None) -> str:
    """Render `medical_info` as one short clinical-shorthand line.

    Output shape:
        "38yo female; pregnant; allergies: Penicillin (anaphylaxis); meds: Insulin; hx: Diabetes"

    Returns "none reported" when the dict is empty / sentinel-only — callers
    can drop that line from their prompt without parsing.
    """
    if not info:
        return "none reported"

    parts: list[str] = []

    # Demographics
    if info.get("age") not in (None, 0, ""):
        parts.append(f"{info['age']}yo")
    if info.get("sex"):
        parts.append(str(info["sex"]))
    if info.get("pregnant"):
        weeks = info.get("gestational_weeks")
        parts.append(f"pregnant{f' {weeks}w' if weeks else ''}")
    if info.get("smoker"):
        parts.append("smoker")

    # Allergies (with severity if known)
    allergies = _filter_none(info.get("allergies"))
    if allergies:
        sev_map = info.get("allergy_severity") or {}
        labeled = [f"{a} ({sev_map[a]})" if sev_map.get(a) else a for a in allergies]
        parts.append(f"allergies: {', '.join(labeled)}")

    # Meds (with blood thinner specifier)
    meds = _filter_none(info.get("medications"))
    if meds:
        bt = info.get("blood_thinner_name")
        labeled = [f"{m} ({bt})" if m == "Blood thinners" and bt else m for m in meds]
        parts.append(f"meds: {', '.join(labeled)}")

    # Conditions (with diabetes type / NYHA class specifiers)
    conds = _filter_none(info.get("conditions"))
    if conds:
        dtype = info.get("diabetes_type")
        nyha = info.get("heart_failure_class")
        labeled = []
        for c in conds:
            if c == "Diabetes" and dtype:
                labeled.append(f"{c} ({dtype})")
            elif c == "Heart failure" and nyha:
                labeled.append(f"{c} (NYHA {nyha})")
            else:
                labeled.append(c)
        parts.append(f"hx: {', '.join(labeled)}")

    return "; ".join(parts) or "none reported"


def _filter_none(arr: Any) -> list[str]:
    """Drop the literal sentinel 'None' that the patient form sends when nothing applies."""
    if not isinstance(arr, list):
        return []
    return [str(x) for x in arr if x and str(x).lower() != "none"]
