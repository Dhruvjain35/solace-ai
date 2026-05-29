"""Claude-generated disposition recommendation: admit / observe / discharge.

The clinician sees this alongside the differential + workup as the third pillar of the
decision-support panel. As with all Claude output, it's an AI draft — but the draft is
reconciled against a deterministic physiologic safety net so the AI can escalate care
but can never de-escalate below a hard red-flag floor.
"""
from __future__ import annotations

import logging
from typing import Any

from lib import claude, json_extract
from lib.config import settings
from lib.medical_format import format_medical_info

log = logging.getLogger(__name__)

_MODEL = settings.model_clinical


_SYSTEM = """You are an ED attending writing a disposition recommendation draft.

Output JSON ONLY (no preamble, no markdown fence):
{
  "disposition": "admit | observe | discharge | transfer",
  "level_of_care": "ICU | step-down | floor | obs unit | home" or empty if N/A,
  "expected_los_hours": integer,
  "rationale": "1-2 short sentences referencing the strongest Dx",
  "discharge_criteria": ["criterion 1", "criterion 2"],
  "return_precautions": ["come back if X", "come back if Y"],
  "consult_services": ["service 1", "service 2"]
}

Rules:
- ESI 1: almost always admit (often ICU). ESI 2: admit/observe. ESI 3: observe or discharge with workup. ESI 4-5: discharge.
- "discharge_criteria" only populated when disposition is observe or discharge.
- "return_precautions" mandatory when disposition is discharge.
- "expected_los_hours": realistic ED length-of-stay (admit may say 4-6 hours for boarding).
- "consult_services": specialist services to involve (e.g. Cardiology, Surgery, ICU) — empty list if none.
- Use the patient's vitals + Ddx + ESI together. Don't override the ESI without explicit reasoning.
"""


def generate(
    transcript: str,
    esi_level: int,
    differential: list[dict],
    medical_info: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
) -> dict:
    if not claude.available():
        return _reconcile(_empty(esi_level), esi_level, vitals, differential)
    try:
        parts = [
            f'Transcript:\n"""\n{transcript.strip()}\n"""',
            f"ESI: {esi_level}",
        ]
        if differential:
            ddx_lines = [f"- {d['diagnosis']} ({d.get('likelihood','low')})" for d in differential]
            parts.append("Differential:\n" + "\n".join(ddx_lines))
        if medical_info:
            parts.append(f"Medical info: {format_medical_info(medical_info)}")
        if vitals:
            v = ", ".join(f"{k}={val}" for k, val in vitals.items() if val is not None)
            if v:
                parts.append(f"Vitals: {v}")
        parts.append("Return the JSON object now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=700,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="disposition",
        )
        raw = "".join(b.text for b in resp.content)
        draft = _parse(raw, esi_level)
    except Exception as e:
        log.exception("Disposition generation failed: %s", e)
        draft = _empty(esi_level)
    return _reconcile(draft, esi_level, vitals, differential)


_VALID_DISPO = {"admit", "observe", "discharge", "transfer"}


def _parse(raw: str, esi_level: int) -> dict:
    obj = json_extract.extract_obj(raw)
    if not obj:
        return _empty(esi_level)
    dispo = str(obj.get("disposition", "")).strip().lower()
    if dispo not in _VALID_DISPO:
        dispo = _default_dispo(esi_level)
    try:
        los = int(obj.get("expected_los_hours") or 0)
    except (TypeError, ValueError):
        los = 0
    return {
        "disposition": dispo,
        "level_of_care": str(obj.get("level_of_care", "")).strip(),
        "expected_los_hours": max(0, min(los, 168)),
        "rationale": str(obj.get("rationale", "")).strip(),
        "discharge_criteria": [str(x).strip() for x in (obj.get("discharge_criteria") or []) if str(x).strip()][:4],
        "return_precautions": [str(x).strip() for x in (obj.get("return_precautions") or []) if str(x).strip()][:5],
        "consult_services": [str(x).strip() for x in (obj.get("consult_services") or []) if str(x).strip()][:5],
    }


def _default_dispo(esi_level: int) -> str:
    if esi_level <= 2:
        return "admit"
    if esi_level == 3:
        return "observe"
    return "discharge"


def _empty(esi_level: int) -> dict:
    return {
        "disposition": _default_dispo(esi_level),
        "level_of_care": "",
        "expected_los_hours": 0,
        "rationale": "",
        "discharge_criteria": [],
        "return_precautions": [],
        "consult_services": [],
    }


# ---------------------------------------------------------------------------
# Deterministic physiologic safety net.
#
# The AI draft is advisory. This floor encodes hard red flags from adult ED
# vital-sign thresholds (qSOFA / NEWS2-aligned). It ranks dispositions and
# levels of care; the reconciled output is always the MORE acute of the two.
# The AI may escalate (e.g. discharge -> admit) but can never de-escalate
# below the deterministic floor.
# ---------------------------------------------------------------------------

# Acuity rank: higher = more acute. Used to take the max() of AI vs floor.
_DISPO_RANK = {"discharge": 0, "transfer": 1, "observe": 1, "admit": 2}
_LOC_RANK = {"": 0, "home": 0, "obs unit": 1, "floor": 2, "step-down": 3, "icu": 4}
_RANK_LOC = {0: "", 1: "obs unit", 2: "floor", 3: "step-down", 4: "ICU"}


def _num(vitals: dict[str, Any] | None, *keys: str) -> float | None:
    """Pull the first numeric value among `keys` from a loose vitals dict."""
    if not vitals:
        return None
    for k in keys:
        for cand in (k, k.lower(), k.upper()):
            if cand in vitals and vitals[cand] is not None:
                try:
                    return float(str(vitals[cand]).split("/")[0].strip())
                except (TypeError, ValueError):
                    pass
    return None


def safety_net(esi_level: int, vitals: dict[str, Any] | None) -> dict:
    """Deterministic physiologic disposition floor.

    Returns {disposition, level_of_care, red_flags, source}. `red_flags` lists
    the triggered physiologic criteria. This output is a FLOOR — the reconciled
    disposition is never less acute than this.
    """
    red_flags: list[str] = []

    sbp = _num(vitals, "systolic", "sbp", "blood_pressure", "bp")
    spo2 = _num(vitals, "spo2", "o2_sat", "oxygen_saturation", "sat")
    hr = _num(vitals, "heart_rate", "hr", "pulse")
    rr = _num(vitals, "respiratory_rate", "rr", "resp_rate")
    temp = _num(vitals, "temperature", "temp")
    gcs = _num(vitals, "gcs", "glasgow")

    # ICU-level red flags
    if sbp is not None and sbp < 90:
        red_flags.append(f"hypotension (SBP {sbp:.0f} < 90)")
    if spo2 is not None and spo2 < 90:
        red_flags.append(f"hypoxia (SpO2 {spo2:.0f}% < 90%)")
    if rr is not None and (rr >= 30 or rr < 8):
        red_flags.append(f"respiratory failure risk (RR {rr:.0f})")
    if hr is not None and (hr >= 130 or hr < 40):
        red_flags.append(f"extreme heart rate (HR {hr:.0f})")
    if gcs is not None and gcs <= 8:
        red_flags.append(f"depressed consciousness (GCS {gcs:.0f} <= 8)")

    icu = bool(red_flags)

    # Floor / admit-level concern (not ICU, but not safe to discharge)
    admit_flags: list[str] = []
    if not icu:
        if sbp is not None and sbp < 100:
            admit_flags.append(f"borderline hypotension (SBP {sbp:.0f})")
        if spo2 is not None and 90 <= spo2 < 94:
            admit_flags.append(f"low oxygen saturation (SpO2 {spo2:.0f}%)")
        if hr is not None and 110 <= hr < 130:
            admit_flags.append(f"tachycardia (HR {hr:.0f})")
        if rr is not None and 22 <= rr < 30:
            admit_flags.append(f"tachypnea (RR {rr:.0f})")
        if temp is not None and (temp >= 38.3 or temp <= 35.0):
            admit_flags.append(f"temperature derangement ({temp:.1f}C)")

    if icu:
        disposition, level_of_care = "admit", "ICU"
    elif admit_flags:
        disposition, level_of_care = "admit", "floor"
        red_flags = admit_flags
    elif esi_level <= 2:
        # ESI 1-2 should never floor below admit even with normal vitals captured.
        disposition, level_of_care = "admit", "floor" if esi_level == 2 else "ICU"
    elif esi_level == 3:
        disposition, level_of_care = "observe", "obs unit"
    else:
        disposition, level_of_care = "discharge", ""

    return {
        "disposition": disposition,
        "level_of_care": level_of_care,
        "red_flags": red_flags,
        "source": "physiologic_safety_net",
    }


def _boarding_risk(disposition: str, level_of_care: str, esi_level: int) -> dict:
    """Estimate ED boarding (admitted-but-no-inpatient-bed) risk.

    Boarding is driven by admit decisions, higher levels of care, and acuity.
    Returns {level, score, factors} — score 0-100, level low/moderate/high.
    """
    score = 0
    factors: list[str] = []
    if disposition == "admit":
        score += 40
        factors.append("admission ordered")
    elif disposition == "transfer":
        score += 30
        factors.append("transfer pending accepting facility")
    loc = (level_of_care or "").lower()
    if loc == "icu":
        score += 35
        factors.append("ICU bed demand (scarce)")
    elif loc == "step-down":
        score += 20
        factors.append("step-down bed demand")
    elif loc == "floor":
        score += 12
        factors.append("inpatient floor bed demand")
    if esi_level <= 2:
        score += 10
        factors.append("high-acuity prioritization")
    score = max(0, min(score, 100))
    level = "high" if score >= 60 else "moderate" if score >= 30 else "low"
    return {"level": level, "score": score, "factors": factors}


def _reconcile(
    draft: dict,
    esi_level: int,
    vitals: dict[str, Any] | None,
    differential: list[dict] | None,
) -> dict:
    """Merge the AI draft with the deterministic safety net.

    The reconciled disposition + level_of_care are the MORE acute of the two.
    Adds `safety_net`, `boarding_risk`, and an `escalated` flag. Keeps every
    key the prior contract returned so persistence/serialization is unchanged.
    """
    floor = safety_net(esi_level, vitals)

    ai_dispo = draft.get("disposition") or _default_dispo(esi_level)
    ai_loc = draft.get("level_of_care") or ""

    final_dispo = ai_dispo
    if _DISPO_RANK.get(floor["disposition"], 0) > _DISPO_RANK.get(ai_dispo, 0):
        final_dispo = floor["disposition"]

    floor_loc_rank = _LOC_RANK.get(floor["level_of_care"].lower(), 0)
    ai_loc_rank = _LOC_RANK.get(ai_loc.lower(), 0)
    final_loc = ai_loc if ai_loc_rank >= floor_loc_rank else _RANK_LOC[floor_loc_rank]

    escalated = (
        _DISPO_RANK.get(final_dispo, 0) > _DISPO_RANK.get(ai_dispo, 0)
        or _LOC_RANK.get((final_loc or "").lower(), 0) > ai_loc_rank
    )

    # Consult services: union of AI suggestions + red-flag-implied services.
    consults = list(draft.get("consult_services") or [])
    if floor["level_of_care"].lower() == "icu" and "Critical Care" not in consults:
        consults.append("Critical Care")
    for d in (differential or [])[:1]:
        # Surface the top-Dx specialty hint already present in many differential rows.
        spec = str(d.get("specialty") or "").strip()
        if spec and spec not in consults:
            consults.append(spec)

    out = dict(draft)
    out["disposition"] = final_dispo
    out["level_of_care"] = final_loc
    out["consult_services"] = consults[:6]
    out["safety_net"] = floor
    out["boarding_risk"] = _boarding_risk(final_dispo, final_loc, esi_level)
    out["escalated_by_safety_net"] = escalated
    if escalated and floor["red_flags"]:
        note = "Auto-escalated: " + "; ".join(floor["red_flags"]) + "."
        out["rationale"] = (note + " " + out.get("rationale", "")).strip()
    return out
