"""E&M leveling + ICD-10 / CPT auto-suggestion with deterministic validation.

Pipeline (two LLM calls run in parallel, then deterministic post-processing):

  Stage 1 (LLM, parallel):
    a) MDM extraction — problems addressed, amount/complexity of data
       reviewed, risk of complications/morbidity, plus total encounter time
       if the note documents it. Covers both outpatient (99202-99215) and
       inpatient/observation (99221-99239) settings.
    b) ICD-10-CM + CPT/procedure candidate proposal with note-cited support.

  Stage 2 (deterministic, no LLM):
    - E&M leveling via the 2021/2023 AMA MDM rubric. Each of the three MDM
      elements is scored on a 1-4 scale; the AMA "2 of 3" rule takes the
      second-highest element to set the level. Outpatient and hospital
      code families are leveled independently. A time-based cross-check
      maps documented total time to its own code and flags disagreement.
    - Top-3 ranked E&M codes with supporting documentation per code.
    - NCCI-style CPT validation: mutually-exclusive pair detection,
      bundling (comprehensive/component) edits, and add-on-code orphan
      detection (add-on billed without its required primary).
    - Modifier 25 / 59 / 95 suggestion logic, deterministic.

Never auto-submits. Every code carries a confidence and the evidence behind
it. Backward compatible: all original flat fields are preserved; new fields
are additive.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = settings.model_clinical


# ---------------------------------------------------------------------------
# E&M code reference tables
# ---------------------------------------------------------------------------

# Outpatient office/other E&M (2021 AMA MDM-or-time rubric, refined 2023).
_OUTPATIENT_LEVELS = [
    {"code": "99202", "level": 2, "mdm": "straightforward", "time_min": (15, 29), "patient": "new"},
    {"code": "99203", "level": 3, "mdm": "low",            "time_min": (30, 44), "patient": "new"},
    {"code": "99204", "level": 4, "mdm": "moderate",       "time_min": (45, 59), "patient": "new"},
    {"code": "99205", "level": 5, "mdm": "high",           "time_min": (60, 74), "patient": "new"},
    {"code": "99212", "level": 2, "mdm": "straightforward", "time_min": (10, 19), "patient": "established"},
    {"code": "99213", "level": 3, "mdm": "low",            "time_min": (20, 29), "patient": "established"},
    {"code": "99214", "level": 4, "mdm": "moderate",       "time_min": (30, 39), "patient": "established"},
    {"code": "99215", "level": 5, "mdm": "high",           "time_min": (40, 54), "patient": "established"},
]

# Hospital inpatient / observation E&M (2023 AMA merge of obs into inpatient).
# Initial care: 99221-99223. Subsequent care: 99231-99233. Discharge: 99238/99239.
_HOSPITAL_LEVELS = [
    {"code": "99221", "level": 1, "mdm": "low",      "time_min": (40, 54),  "patient": "initial"},
    {"code": "99222", "level": 2, "mdm": "moderate", "time_min": (55, 74),  "patient": "initial"},
    {"code": "99223", "level": 3, "mdm": "high",     "time_min": (75, 999), "patient": "initial"},
    {"code": "99231", "level": 1, "mdm": "low",      "time_min": (25, 34),  "patient": "subsequent"},
    {"code": "99232", "level": 2, "mdm": "moderate", "time_min": (35, 49),  "patient": "subsequent"},
    {"code": "99233", "level": 3, "mdm": "high",     "time_min": (50, 999), "patient": "subsequent"},
    {"code": "99238", "level": 1, "mdm": "discharge", "time_min": (1, 30),   "patient": "discharge"},
    {"code": "99239", "level": 2, "mdm": "discharge", "time_min": (31, 999), "patient": "discharge"},
]

# MDM tier ordering for ranking / comparison.
_MDM_ORDER = {"straightforward": 0, "low": 1, "moderate": 2, "high": 3}

# Normalize the many phrasings the LLM may emit into a 1-4 element score.
# 1 = minimal/straightforward, 2 = low, 3 = moderate, 4 = high.
_ELEMENT_RANK = {
    "minimal": 1, "straightforward": 1, "none": 1, "self-limited": 1, "minor": 1,
    "low": 2, "limited": 2, "stable": 2,
    "moderate": 3, "extensive": 3,
    "high": 4, "severe": 4, "extensive-high": 4,
}

_SETTING_OUTPATIENT = "outpatient"
_SETTING_HOSPITAL = "hospital"


# ---------------------------------------------------------------------------
# NCCI-style deterministic edit tables (curated, illustrative subset)
# ---------------------------------------------------------------------------

# Mutually-exclusive CPT pairs: should never be reported together on the same
# day for the same patient (frozenset of the two codes).
_MUTUALLY_EXCLUSIVE: list[frozenset[str]] = [
    frozenset({"99213", "99214"}),  # cannot bill two office E&M of same encounter
    frozenset({"99291", "99281"}),  # critical care vs low-level ED visit
    frozenset({"45378", "45380"}),  # diagnostic vs biopsy colonoscopy (same session ME)
]

# Bundling edits: component code is included in the comprehensive code.
# {component: comprehensive} — billing both unbundles inappropriately.
_BUNDLED_INTO: dict[str, str] = {
    "36415": "*",       # routine venipuncture bundled into most E&M / panels
    "94760": "*",       # pulse oximetry single — bundled into E&M
    "94761": "*",       # pulse oximetry multiple — bundled into E&M
    "12001": "13132",   # simple repair bundled into complex repair same site
    "11042": "11043",   # debridement subq bundled into deeper debridement
}

# Add-on CPT codes and the primary code(s) they must accompany.
# An add-on with no listed primary present is an "orphan" and is invalid.
_ADD_ON_PRIMARIES: dict[str, list[str]] = {
    "99417": ["99205", "99215"],          # prolonged outpatient time, w/ highest level
    "99418": ["99223", "99233"],          # prolonged inpatient time
    "11045": ["11042", "11043", "11044"], # add-on debridement, each add'l 20cm2
    "13133": ["13132"],                   # complex repair, each add'l 5cm
    "90461": ["90460"],                   # immunization admin, each add'l component
    "G2211": ["99202", "99203", "99204", "99205",
              "99212", "99213", "99214", "99215"],  # visit complexity add-on
}


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_SYSTEM_MDM = """You extract E&M leveling elements from a clinical encounter note. Return JSON only.

Output:
{
  "setting": "outpatient | hospital",
  "patient_type": "new | established | initial | subsequent | discharge",
  "mdm": {
    "problems_addressed": "minimal | low | moderate | high",
    "problems_detail": "short clause naming the problems and their status",
    "data_reviewed": "minimal | limited | moderate | extensive",
    "data_detail": "short clause: labs/imaging ordered, records reviewed, independent interpretation, discussion with other provider",
    "risk_of_complications": "minimal | low | moderate | high",
    "risk_detail": "short clause: prescription drug mgmt, decision re: surgery, social determinants limiting care",
    "summary_supporting_evidence": "1-2 short clauses citing the note verbatim"
  },
  "total_time_minutes": null,
  "time_documented": false,
  "time_evidence": "verbatim time statement from the note, or empty"
}

Rules:
- setting = hospital only if the note documents inpatient/observation/admission care; else outpatient.
- patient_type: outpatient -> new|established; hospital -> initial|subsequent|discharge.
- Score each MDM element strictly on 2021/2023 AMA criteria. Do not inflate.
- total_time_minutes: only fill if the note explicitly states total time on the date of encounter; else null and time_documented=false.
- Never invent. If an element is undocumented, score it the lowest plausible tier.
"""

_SYSTEM_CODES = """You propose billing codes from a clinical encounter note. Return JSON only.

Output:
{
  "icd10_candidates": [
    {"code": "K35.80", "name": "Acute appendicitis, unspecified", "support": "RLQ pain, fever, anorexia", "specificity": "high"}
  ],
  "cpt_procedure_candidates": [
    {"code": "12001", "name": "Simple repair of scalp 2.5cm", "support": "verbatim note clause", "add_on": false}
  ],
  "telehealth": false,
  "telehealth_evidence": ""
}

Rules:
- ICD-10-CM codes only; up to 6 candidates, ranked most-specific first; specificity is high|moderate|low.
- cpt_procedure_candidates: procedures/services beyond the E&M visit itself. Return [] if none. Mark add_on=true for CPT add-on codes.
- telehealth=true only if the note documents a synchronous audio-video or audio-only visit.
- Never invent diagnoses or procedures not supported by the note.
"""


# ---------------------------------------------------------------------------
# Deterministic E&M leveling
# ---------------------------------------------------------------------------

def _element_score(value: str | None) -> int:
    """Map an MDM element phrase to a 1-4 score."""
    if not value:
        return 1
    return _ELEMENT_RANK.get(str(value).strip().lower(), 1)


def _score_to_mdm_tier(score: int) -> str:
    return {1: "straightforward", 2: "low", 3: "moderate", 4: "high"}.get(score, "straightforward")


def _level_by_mdm(mdm: dict[str, str]) -> dict[str, Any]:
    """Apply the AMA 2-of-3 rule: the second-highest of the three MDM
    elements determines the overall MDM level."""
    pa = _element_score(mdm.get("problems_addressed"))
    dr = _element_score(mdm.get("data_reviewed"))
    rk = _element_score(mdm.get("risk_of_complications"))
    scores = sorted([pa, dr, rk], reverse=True)
    driving = scores[1]  # second-highest = the "2 of 3" threshold
    return {
        "element_scores": {"problems": pa, "data": dr, "risk": rk},
        "mdm_tier": _score_to_mdm_tier(driving),
        "driving_score": driving,
        "rule": "AMA 2-of-3: level set by the 2nd-highest MDM element",
    }


def _rank_em_codes(table: list[dict[str, Any]], patient_filter: str,
                    target_tier: str) -> list[dict[str, Any]]:
    """Return E&M codes from `table` for the given patient family, ranked by
    proximity to the target MDM tier. Closest tier first."""
    fam = [c for c in table if c["patient"] == patient_filter]
    if not fam:
        fam = table
    target_idx = _MDM_ORDER.get(target_tier, 1)

    def distance(c: dict[str, Any]) -> tuple[int, int]:
        idx = _MDM_ORDER.get(c["mdm"], 0)
        # prefer exact tier, then one step lower (conservative), then anything
        return (abs(idx - target_idx), 0 if idx <= target_idx else 1)

    return sorted(fam, key=distance)


def _time_crosscheck(setting: str, patient_filter: str,
                     total_minutes: float | None) -> dict[str, Any]:
    """Map documented total time to its own E&M code and report it as an
    independent cross-check against the MDM-derived level."""
    if total_minutes is None:
        return {"documented": False, "note": "No total time documented; MDM-only leveling."}
    table = _OUTPATIENT_LEVELS if setting == _SETTING_OUTPATIENT else _HOSPITAL_LEVELS
    fam = [c for c in table if c["patient"] == patient_filter] or table
    match = None
    for c in fam:
        lo, hi = c["time_min"]
        if lo <= total_minutes <= hi:
            match = c
            break
    if match is None:
        # below the lowest band -> lowest code; above highest -> highest code
        fam_sorted = sorted(fam, key=lambda c: c["time_min"][0])
        match = fam_sorted[0] if total_minutes < fam_sorted[0]["time_min"][0] else fam_sorted[-1]
    return {
        "documented": True,
        "total_minutes": total_minutes,
        "time_based_code": match["code"],
        "time_based_range": f'{match["time_min"][0]}-{match["time_min"][1]} min',
        "note": "Time-based code derived independently of MDM.",
    }


def _build_em_ranking(setting: str, patient_filter: str, mdm: dict[str, str],
                      time_check: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce a top-3 ranked E&M list with supporting documentation,
    confidence, and a flag where the time-based code disagrees."""
    table = _OUTPATIENT_LEVELS if setting == _SETTING_OUTPATIENT else _HOSPITAL_LEVELS
    leveling = _level_by_mdm(mdm)
    ranked = _rank_em_codes(table, patient_filter, leveling["mdm_tier"])[:3]
    time_code = time_check.get("time_based_code")

    out: list[dict[str, Any]] = []
    for i, c in enumerate(ranked):
        # Confidence: top pick high if MDM clean and (no time doc or time agrees).
        if i == 0:
            if time_code and time_code != c["code"]:
                conf = 0.6
            else:
                conf = 0.85
        elif i == 1:
            conf = 0.45
        else:
            conf = 0.2
        support = mdm.get("summary_supporting_evidence", "")
        out.append({
            "code": c["code"],
            "level": c["level"],
            "mdm": c["mdm"],
            "time_min": list(c["time_min"]),
            "confidence": round(conf, 2),
            "supporting_documentation": support,
            "rank": i + 1,
            "agrees_with_time": (time_code is None) or (time_code == c["code"]),
        })
    return out


# ---------------------------------------------------------------------------
# Deterministic NCCI-style CPT validation
# ---------------------------------------------------------------------------

def _validate_cpt(cpt_candidates: list[dict[str, Any]],
                   em_code: str | None) -> dict[str, Any]:
    """Run NCCI-style edits over the proposed CPT set + the chosen E&M code.

    Detects: mutually-exclusive pairs, bundling edits, and add-on orphans.
    Returns flags only; never removes codes (clinician decides)."""
    codes = [str(c.get("code", "")).strip() for c in cpt_candidates if c.get("code")]
    all_codes = set(codes) | ({em_code} if em_code else set())
    flags: list[dict[str, Any]] = []

    # Mutually-exclusive pairs
    for pair in _MUTUALLY_EXCLUSIVE:
        if pair.issubset(all_codes):
            a, b = sorted(pair)
            flags.append({
                "type": "mutually_exclusive",
                "codes": [a, b],
                "severity": "error",
                "message": f"{a} and {b} are mutually exclusive on the same date of service.",
            })

    # Bundling edits
    for comp, comprehensive in _BUNDLED_INTO.items():
        if comp not in all_codes:
            continue
        if comprehensive == "*" and em_code:
            flags.append({
                "type": "bundled",
                "codes": [comp, em_code],
                "severity": "warning",
                "message": f"{comp} is typically bundled into the E&M visit ({em_code}); "
                           f"separate billing usually denied without documentation.",
            })
        elif comprehensive in all_codes:
            flags.append({
                "type": "bundled",
                "codes": [comp, comprehensive],
                "severity": "error",
                "message": f"{comp} is a component of {comprehensive}; bill only {comprehensive}.",
            })

    # Add-on orphan detection
    for code in codes:
        primaries = _ADD_ON_PRIMARIES.get(code)
        if primaries is None:
            continue
        if not any(p in all_codes for p in primaries):
            flags.append({
                "type": "add_on_orphan",
                "codes": [code],
                "severity": "error",
                "message": f"Add-on code {code} requires a primary code "
                           f"({', '.join(primaries)}); none is present.",
            })

    errors = sum(1 for f in flags if f["severity"] == "error")
    return {
        "flags": flags,
        "passed": errors == 0,
        "error_count": errors,
        "warning_count": sum(1 for f in flags if f["severity"] == "warning"),
        "checked_codes": sorted(all_codes),
    }


def _rank_cpt(cpt_candidates: list[dict[str, Any]],
              validation: dict[str, Any]) -> list[dict[str, Any]]:
    """Top-3 CPT procedures with confidence, demoting any code carrying an
    NCCI error flag."""
    error_codes: set[str] = set()
    for f in validation["flags"]:
        if f["severity"] == "error":
            error_codes.update(f["codes"])
    ranked: list[dict[str, Any]] = []
    for i, c in enumerate(cpt_candidates[:6]):
        code = str(c.get("code", "")).strip()
        base = 0.8 - 0.15 * i
        if code in error_codes:
            base = min(base, 0.3)
        ranked.append({
            "code": code,
            "name": c.get("name", ""),
            "support": c.get("support", ""),
            "add_on": bool(c.get("add_on", False)),
            "confidence": round(max(base, 0.1), 2),
            "ncci_clean": code not in error_codes,
        })
    ranked.sort(key=lambda x: x["confidence"], reverse=True)
    return ranked[:3]


# ---------------------------------------------------------------------------
# Deterministic modifier suggestion (25 / 59 / 95)
# ---------------------------------------------------------------------------

def _suggest_modifiers(em_code: str | None, cpt_candidates: list[dict[str, Any]],
                       telehealth: bool, mdm_tier: str) -> list[dict[str, Any]]:
    """Deterministically derive modifier 25 / 59 / 95 suggestions from the
    code set. Suggestions only — clinician confirms documentation."""
    cpt_codes = [str(c.get("code", "")).strip() for c in cpt_candidates if c.get("code")]
    mods: list[dict[str, Any]] = []

    # Modifier 25: significant, separately identifiable E&M on the same day as
    # a procedure. Requires both an E&M code AND a procedure, with the E&M
    # being more than the inherent pre/post work of the procedure.
    if em_code and cpt_codes:
        confident = mdm_tier in ("moderate", "high")
        mods.append({
            "modifier": "25",
            "attach_to": em_code,
            "reason": "Significant, separately identifiable E&M performed on the "
                      "same day as a procedure.",
            "confidence": 0.7 if confident else 0.45,
            "requires": "E&M documentation must stand on its own, beyond the "
                        "procedure's inherent work.",
        })

    # Modifier 59: distinct procedural service — only meaningful with 2+
    # procedures that could otherwise be bundled.
    if len(cpt_codes) >= 2:
        mods.append({
            "modifier": "59",
            "attach_to": cpt_codes[1],
            "reason": "Distinct procedural service — separate site/session/lesion "
                      "from the other procedure(s) billed.",
            "confidence": 0.5,
            "requires": "Document separate anatomic site, session, or lesion; "
                        "prefer an X{EPSU} modifier when applicable.",
        })

    # Modifier 95: synchronous telemedicine via real-time audio-video.
    if telehealth and em_code:
        mods.append({
            "modifier": "95",
            "attach_to": em_code,
            "reason": "Synchronous telemedicine service rendered via real-time "
                      "interactive audio-video.",
            "confidence": 0.75,
            "requires": "Note must document a real-time audio-video encounter.",
        })

    return mods


# ---------------------------------------------------------------------------
# LLM call helpers (run in parallel)
# ---------------------------------------------------------------------------

def _parse_json(resp: Any) -> dict[str, Any]:
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def _call_mdm(note_text: str) -> dict[str, Any]:
    resp = claude.messages_create(
        model=_MODEL,
        max_tokens=900,
        system=_SYSTEM_MDM,
        messages=[{"role": "user",
                   "content": f'Encounter note:\n"""\n{note_text[:7000]}\n"""\n\nReturn JSON now.'}],
        purpose="em_coding_mdm",
    )
    return _parse_json(resp)


def _call_codes(note_text: str) -> dict[str, Any]:
    resp = claude.messages_create(
        model=_MODEL,
        max_tokens=900,
        system=_SYSTEM_CODES,
        messages=[{"role": "user",
                   "content": f'Encounter note:\n"""\n{note_text[:7000]}\n"""\n\nReturn JSON now.'}],
        purpose="em_coding_codes",
    )
    return _parse_json(resp)


# ---------------------------------------------------------------------------
# Public entrypoint — signature stable
# ---------------------------------------------------------------------------

def suggest(note_text: str, *, established_patient: bool = True) -> dict[str, Any]:
    """Suggest E&M level, ICD-10, CPT, and modifiers for an encounter note.

    Backward compatible: original flat fields (`mdm`, `em_primary`,
    `em_alternate`, `icd10`, `cpt_procedures`, `modifiers`,
    `established_patient`, `available`) are preserved. New fields are
    additive: `em_ranked`, `em_leveling`, `time_crosscheck`,
    `ncci_validation`, `cpt_ranked`, `setting`, `patient_type`.
    """
    if not claude.available():
        return {"available": False}

    # Stage 1: two LLM calls in parallel.
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            mdm_future = pool.submit(_call_mdm, note_text)
            codes_future = pool.submit(_call_codes, note_text)
            mdm_parsed = mdm_future.result()
            codes_parsed = codes_future.result()
    except Exception as e:
        log.warning("em_coding failed: %s", e)
        return {"available": False, "error": str(e)}

    # --- Setting & patient family resolution -------------------------------
    setting = mdm_parsed.get("setting", _SETTING_OUTPATIENT)
    if setting not in (_SETTING_OUTPATIENT, _SETTING_HOSPITAL):
        setting = _SETTING_OUTPATIENT

    patient_type = mdm_parsed.get("patient_type", "")
    if setting == _SETTING_OUTPATIENT:
        if patient_type not in ("new", "established"):
            patient_type = "established" if established_patient else "new"
        establish = patient_type == "established"
    else:
        if patient_type not in ("initial", "subsequent", "discharge"):
            patient_type = "subsequent"
        establish = established_patient  # not meaningful for hospital; pass through

    mdm = mdm_parsed.get("mdm", {})

    # --- Time cross-check ---------------------------------------------------
    raw_time = mdm_parsed.get("total_time_minutes")
    total_minutes: float | None
    try:
        total_minutes = float(raw_time) if raw_time is not None else None
    except (TypeError, ValueError):
        total_minutes = None
    time_check = _time_crosscheck(setting, patient_type, total_minutes)
    if mdm_parsed.get("time_evidence"):
        time_check["evidence"] = mdm_parsed["time_evidence"]

    # --- Deterministic E&M leveling ----------------------------------------
    leveling = _level_by_mdm(mdm)
    em_ranked = _build_em_ranking(setting, patient_type, mdm, time_check)
    em_primary = em_ranked[0] if em_ranked else None
    em_alternate = em_ranked[1] if len(em_ranked) > 1 else em_primary
    em_code = em_primary["code"] if em_primary else None

    # --- ICD-10 candidates --------------------------------------------------
    icd10 = codes_parsed.get("icd10_candidates", [])[:6]

    # --- CPT validation + ranking ------------------------------------------
    cpt_candidates = codes_parsed.get("cpt_procedure_candidates", []) or []
    ncci = _validate_cpt(cpt_candidates, em_code)
    cpt_ranked = _rank_cpt(cpt_candidates, ncci)

    # --- Modifiers ----------------------------------------------------------
    telehealth = bool(codes_parsed.get("telehealth", False))
    modifiers = _suggest_modifiers(em_code, cpt_candidates, telehealth,
                                   leveling["mdm_tier"])

    return {
        "available": True,
        # --- original flat fields (backward compatible) ---
        "mdm": mdm,
        "em_primary": em_primary,
        "em_alternate": em_alternate,
        "icd10": icd10,
        "cpt_procedures": cpt_candidates,
        "modifiers": modifiers,
        "established_patient": establish,
        # --- new additive fields ---
        "setting": setting,
        "patient_type": patient_type,
        "em_leveling": leveling,
        "em_ranked": em_ranked,
        "time_crosscheck": time_check,
        "cpt_ranked": cpt_ranked,
        "ncci_validation": ncci,
        "auto_submit": False,
    }
