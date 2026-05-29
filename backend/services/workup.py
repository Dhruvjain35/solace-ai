"""Claude-generated workup order set. Labs + imaging + monitoring tied to the Ddx.

The clinician sees these as a one-click "order set accept" panel. They are AI suggestions —
the EHR commits when the clinician signs.
"""
from __future__ import annotations

import logging
from typing import Any

from lib import claude, json_extract
from lib.config import settings
from lib.medical_format import format_medical_info

log = logging.getLogger(__name__)

_MODEL = settings.model_clinical


_SYSTEM = """You are an ED attending writing a workup order set for a patient about to be evaluated.

Output JSON ONLY (no preamble, no markdown fence):
{
  "labs":      ["short order text", ...],   // e.g. "CBC", "BMP", "Troponin (q3h x2)"
  "imaging":   ["short order text", ...],   // e.g. "ECG", "CXR PA/lateral", "CT abd/pelvis with IV contrast"
  "monitoring":["short order text", ...],   // e.g. "Continuous cardiac monitor", "SpO2 monitor"
  "consults":  ["short order text", ...],   // e.g. "Cards consult", "Surgery consult"
  "rationale": "1-2 sentences linking these orders to the differential"
}

Rules:
- Anchor each order to a Dx in the differential — don't shotgun.
- ESI 1-2: include monitoring + STAT labs/imaging.
- ESI 3: targeted labs + imaging only if clearly indicated.
- ESI 4-5: minimal — often just clinical exam, maybe a single lab.
- Use standard ED shorthand (CBC, BMP, LFTs, lipase, lactate, UA, hCG, troponin, D-dimer, BNP).
- If an order would be contraindicated by the patient's renal/hepatic/allergy history, skip it.
- Return empty arrays for sections that don't apply. Do not invent a diagnosis the Ddx didn't list.
- "rationale" is mandatory — keep it under 30 words.
"""


def generate(
    transcript: str,
    esi_level: int,
    differential: list[dict],
    medical_info: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
) -> dict:
    if not claude.available():
        return _empty()
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
            purpose="workup",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw)
    except Exception as e:
        log.exception("Workup generation failed: %s", e)
        return _empty()


def _parse(raw: str) -> dict:
    obj = json_extract.extract_obj(raw)
    if not obj:
        return _empty()
    return {
        "labs":       [str(x).strip() for x in (obj.get("labs") or []) if str(x).strip()][:8],
        "imaging":    [str(x).strip() for x in (obj.get("imaging") or []) if str(x).strip()][:6],
        "monitoring": [str(x).strip() for x in (obj.get("monitoring") or []) if str(x).strip()][:5],
        "consults":   [str(x).strip() for x in (obj.get("consults") or []) if str(x).strip()][:4],
        "rationale":  str(obj.get("rationale", "")).strip(),
    }


def _empty() -> dict:
    return {"labs": [], "imaging": [], "monitoring": [], "consults": [], "rationale": ""}


# ===========================================================================
# Contraindication checks (deterministic, no AI)
# ===========================================================================
#
# A second deterministic pass over the AI-suggested order set. The model is
# told to skip contraindicated orders, but a clinical product must not rely on
# that — these rules independently flag any order that conflicts with the
# patient's renal/hepatic/allergy/pregnancy history. Flags are advisory; the
# order stays in the set so the clinician decides, but it carries a warning.

# Each rule: substring (lower-case) matched against the order text -> a probe
# function over the medical_info dict returning a reason string or None.
def _renal(info: dict[str, Any]) -> bool:
    conds = " ".join(str(c).lower() for c in (info.get("conditions") or []))
    return any(k in conds for k in ("ckd", "renal", "kidney disease", "dialysis", "esrd"))


def _hepatic(info: dict[str, Any]) -> bool:
    conds = " ".join(str(c).lower() for c in (info.get("conditions") or []))
    return any(k in conds for k in ("cirrhosis", "hepatic", "liver disease", "hepatitis"))


def _pregnant(info: dict[str, Any]) -> bool:
    return bool(info.get("pregnant"))


def _allergic_to(info: dict[str, Any], *needles: str) -> bool:
    allergies = " ".join(str(a).lower() for a in (info.get("allergies") or []))
    return any(n in allergies for n in needles)


# (order substring, predicate, severity, reason)
_CONTRA_RULES: list[tuple[str, Any, str, str]] = [
    ("iv contrast", lambda i: _renal(i),
     "warning", "IV contrast with renal impairment — risk of contrast nephropathy; check eGFR."),
    ("with contrast", lambda i: _renal(i),
     "warning", "Contrast study with renal impairment — verify eGFR before ordering."),
    ("contrast", lambda i: _allergic_to(i, "contrast", "iodine"),
     "critical", "Documented contrast/iodine allergy — premedicate or use non-contrast alternative."),
    ("ct ", lambda i: _pregnant(i),
     "warning", "CT involves ionizing radiation in a pregnant patient — consider ultrasound/MRI."),
    ("x-ray", lambda i: _pregnant(i),
     "warning", "Radiograph in a pregnant patient — shield and confirm the study is necessary."),
    ("cxr", lambda i: _pregnant(i),
     "warning", "Chest radiograph in a pregnant patient — shield and confirm necessity."),
    ("acetaminophen", lambda i: _hepatic(i),
     "warning", "Acetaminophen with hepatic impairment — dose-limit or avoid."),
    ("lfts", lambda i: _hepatic(i),
     "info", "Known hepatic disease — interpret LFTs against the patient's baseline."),
    ("nsaid", lambda i: _renal(i),
     "warning", "NSAID with renal impairment — risk of further renal injury; prefer alternative."),
    ("ketorolac", lambda i: _renal(i),
     "warning", "Ketorolac with renal impairment — contraindicated; use an alternative analgesic."),
    ("contrast", lambda i: _allergic_to(i, "shellfish"),
     "info", "Shellfish allergy is not a true contrast contraindication — document reassurance."),
]


def check_contraindications(
    order_set: dict[str, Any],
    medical_info: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Deterministically flag orders that conflict with the patient's history.

    NO AI. Scans every labs/imaging/monitoring/consults order against the
    patient's renal/hepatic/allergy/pregnancy history.

    Returns a list of flags:
      [{"order": "...", "section": "labs|imaging|...",
        "severity": "critical|warning|info", "reason": "..."}, ...]
    """
    info = medical_info or {}
    if not info:
        return []
    flags: list[dict[str, Any]] = []
    for section in ("labs", "imaging", "monitoring", "consults"):
        for order in order_set.get(section) or []:
            text = str(order).strip()
            low = text.lower()
            for substr, predicate, severity, reason in _CONTRA_RULES:
                if substr in low:
                    try:
                        hit = predicate(info)
                    except Exception:  # defensive — never let a rule crash the check
                        hit = False
                    if hit:
                        flags.append({
                            "order": text,
                            "section": section,
                            "severity": severity,
                            "reason": reason,
                        })
    return flags


def generate_with_safety_check(
    transcript: str,
    esi_level: int,
    differential: list[dict],
    medical_info: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
) -> dict:
    """generate() plus a deterministic contraindication pass.

    Returns the workup order set with two extra keys:
      "contraindications": [ {order, section, severity, reason}, ... ]
      "has_critical_contraindication": bool
    The AI-anchored "rationale" links orders to the differential; the
    contraindication flags are an independent deterministic safety net.
    """
    order_set = generate(transcript, esi_level, differential, medical_info, vitals)
    flags = check_contraindications(order_set, medical_info)
    return {
        **order_set,
        "contraindications": flags,
        "has_critical_contraindication": any(f["severity"] == "critical" for f in flags),
    }


