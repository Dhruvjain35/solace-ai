"""Validated PRO/screener library — deterministic scoring + LLM auto-extract.

All scoring rubrics are the published gold-standard cutoffs:
    - PHQ-9 depression (0-27): 0-4 none, 5-9 mild, 10-14 moderate, 15-19 mod-severe, 20-27 severe.
      Item 9 (suicidality) is a red flag at any positive score.
      Kroenke K, Spitzer RL, Williams JBW. J Gen Intern Med 2001;16(9):606-13.
    - GAD-7 anxiety (0-21): 0-4 none, 5-9 mild, 10-14 moderate, 15-21 severe.
      Spitzer RL et al., Arch Intern Med 2006;166(10):1092-7.
    - AUDIT-C alcohol (0-12): >=4 men, >=3 women suggests alcohol misuse.
      Bush K et al., Arch Intern Med 1998;158(16):1789-95.
    - EPDS perinatal depression (0-30): >=10 possible, >=13 likely.
      Item 10 (self-harm) is a red flag at any positive score.
      Cox JL, Holden JM, Sagovsky R. Br J Psychiatry 1987;150:782-6.
    - PCL-5 PTSD (0-80): >=33 probable PTSD; full 20 DSM-5 items.
      Weathers FW et al., PTSD Checklist for DSM-5 (PCL-5), 2013.
    - PRAPARE (SDoH) — multi-domain risk count.
      NACHC PRAPARE, 2016.
    - ACE (Adverse Childhood Experiences, 0-10): >=4 high lifetime risk.
      Felitti VJ et al., Am J Prev Med 1998;14(4):245-58.
    - CRAFFT (adolescent substance): >=2 yes is positive.
      Knight JR et al., Arch Pediatr Adolesc Med 2002;156(6):607-14.

Scoring functions validate item counts and surface a structured `missing` list
(indices not answered) rather than raising a raw error.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


class ScreenerInputError(ValueError):
    """Raised when item count / payload shape is wrong. Carries `missing`."""

    def __init__(self, message: str, missing: list[Any] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []


def _coerce_items(items: Any, expected: int) -> list[int]:
    """Validate a screener item list. Returns clean ints or raises
    ScreenerInputError with the indices that are missing / unparseable."""
    if not isinstance(items, (list, tuple)):
        raise ScreenerInputError(
            f"expected a list of {expected} item scores, got {type(items).__name__}",
            missing=list(range(expected)),
        )
    items = list(items)
    if len(items) < expected:
        # Pad-detect: report the unanswered tail indices.
        missing = list(range(len(items), expected))
        raise ScreenerInputError(
            f"expected {expected} items, got {len(items)}", missing=missing
        )
    if len(items) > expected:
        raise ScreenerInputError(
            f"expected {expected} items, got {len(items)}",
            missing=[],
        )
    out: list[int] = []
    bad: list[int] = []
    for i, x in enumerate(items):
        if x is None:
            bad.append(i)
            out.append(0)
            continue
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            bad.append(i)
            out.append(0)
    if bad:
        raise ScreenerInputError(
            f"items at indices {bad} are missing or non-numeric", missing=bad
        )
    return out


def _sum(items: list[int], expected: int) -> int:
    return sum(_coerce_items(items, expected))


# ---- PHQ-9 -----------------------------------------------------------------------
_PHQ9_CITATION = "Kroenke K, Spitzer RL, Williams JBW. J Gen Intern Med 2001;16(9):606-13."


def phq9(items: list[int]) -> dict[str, Any]:
    clean = _coerce_items(items, 9)
    score = sum(clean)
    item9 = clean[8]
    si = item9 > 0
    if score <= 4:
        sev = "none-minimal"
    elif score <= 9:
        sev = "mild"
    elif score <= 14:
        sev = "moderate"
    elif score <= 19:
        sev = "moderately severe"
    else:
        sev = "severe"
    flags: list[str] = []
    red_alerts: list[dict[str, Any]] = []
    if si:
        flags.append("positive item 9 — suicidality screen positive — ASSESS NOW")
        red_alerts.append({
            "type": "suicidality",
            "instrument": "PHQ-9",
            "item": 9,
            "item_score": item9,
            "severity": "critical" if item9 >= 2 else "high",
            "message": "PHQ-9 item 9 positive — thoughts of being better off dead or self-harm. "
                       "Perform a same-encounter safety assessment before disposition.",
        })
    if score >= 15:
        flags.append("major depressive disorder likely — same-day pharmacotherapy + counseling discussion")
    return {
        "score": score,
        "severity": sev,
        "flags": flags,
        "suicidality": si,
        "red_alerts": red_alerts,
        "citation": _PHQ9_CITATION,
    }


# ---- GAD-7 -----------------------------------------------------------------------
_GAD7_CITATION = "Spitzer RL, Kroenke K, Williams JBW, Lowe B. Arch Intern Med 2006;166(10):1092-7."


def gad7(items: list[int]) -> dict[str, Any]:
    score = sum(_coerce_items(items, 7))
    if score <= 4:
        sev = "minimal"
    elif score <= 9:
        sev = "mild"
    elif score <= 14:
        sev = "moderate"
    else:
        sev = "severe"
    flags: list[str] = []
    if score >= 15:
        flags.append("severe GAD — consider pharmacotherapy + referral")
    elif score >= 10:
        flags.append("moderate anxiety — further diagnostic assessment warranted")
    return {
        "score": score,
        "severity": sev,
        "flags": flags,
        "red_alerts": [],
        "citation": _GAD7_CITATION,
    }


# ---- AUDIT-C ---------------------------------------------------------------------
_AUDITC_CITATION = "Bush K, Kivlahan DR, McDonell MB et al. Arch Intern Med 1998;158(16):1789-95."


def audit_c(items: list[int], sex: str = "M") -> dict[str, Any]:
    clean = _coerce_items(items, 3)
    score = sum(clean)
    cutoff = 4 if str(sex).strip().upper().startswith("M") else 3
    positive = score >= cutoff
    flags: list[str] = []
    red_alerts: list[dict[str, Any]] = []
    if positive:
        flags.append("alcohol misuse screen positive — brief intervention indicated")
    if score >= 8:
        red_alerts.append({
            "type": "high_risk_drinking",
            "instrument": "AUDIT-C",
            "severity": "high",
            "message": "AUDIT-C >=8 indicates high-risk / probable alcohol use disorder — "
                       "assess for withdrawal risk and consider full AUDIT.",
        })
    return {
        "score": score,
        "cutoff": cutoff,
        "positive": positive,
        "flags": flags,
        "red_alerts": red_alerts,
        "citation": _AUDITC_CITATION,
    }


# ---- EPDS (perinatal) ------------------------------------------------------------
_EPDS_CITATION = "Cox JL, Holden JM, Sagovsky R. Br J Psychiatry 1987;150:782-6."


def epds(items: list[int]) -> dict[str, Any]:
    clean = _coerce_items(items, 10)
    score = sum(clean)
    item10 = clean[9]
    si = item10 > 0
    if score >= 13:
        sev = "likely depression"
    elif score >= 10:
        sev = "possible depression"
    else:
        sev = "low"
    flags: list[str] = []
    red_alerts: list[dict[str, Any]] = []
    if si:
        flags.append("positive item 10 — self-harm screen positive — ASSESS NOW")
        red_alerts.append({
            "type": "suicidality",
            "instrument": "EPDS",
            "item": 10,
            "item_score": item10,
            "severity": "critical" if item10 >= 2 else "high",
            "message": "EPDS item 10 positive — thoughts of self-harm in a perinatal patient. "
                       "Perform a same-encounter safety assessment before disposition.",
        })
    if score >= 13:
        flags.append("perinatal depression likely — refer perinatal psychiatry")
    return {
        "score": score,
        "severity": sev,
        "flags": flags,
        "suicidality": si,
        "red_alerts": red_alerts,
        "citation": _EPDS_CITATION,
    }


# ---- PCL-5 PTSD ------------------------------------------------------------------
_PCL5_CITATION = (
    "Weathers FW, Litz BT, Keane TM, Palmieri PA, Marx BP, Schnurr PP. "
    "PTSD Checklist for DSM-5 (PCL-5), National Center for PTSD, 2013."
)

# DSM-5 symptom clusters — 0-based item indices.
_PCL5_CLUSTERS = {
    "B_intrusion": [0, 1, 2, 3, 4],          # items 1-5
    "C_avoidance": [5, 6],                   # items 6-7
    "D_cognition_mood": [7, 8, 9, 10, 11, 12, 13],  # items 8-14
    "E_arousal": [14, 15, 16, 17, 18, 19],   # items 15-20
}
# A symptom "counts" toward the provisional DSM-5 diagnosis if rated >= 2 (Moderate).
_PCL5_SYMPTOM_THRESHOLD = 2
_PCL5_CLUSTER_RULE = {"B_intrusion": 1, "C_avoidance": 1, "D_cognition_mood": 2, "E_arousal": 2}


def pcl5(items: list[int]) -> dict[str, Any]:
    """PCL-5: 20-item DSM-5 PTSD checklist, each item 0-4.
    Total >= 33 suggests probable PTSD. A provisional DSM-5 diagnosis also
    requires the per-cluster symptom-count rule (B>=1, C>=1, D>=2, E>=2 items
    rated Moderate or higher)."""
    clean = _coerce_items(items, 20)
    score = sum(clean)
    cluster_scores: dict[str, int] = {}
    cluster_symptom_counts: dict[str, int] = {}
    for name, idxs in _PCL5_CLUSTERS.items():
        cluster_scores[name] = sum(clean[i] for i in idxs)
        cluster_symptom_counts[name] = sum(
            1 for i in idxs if clean[i] >= _PCL5_SYMPTOM_THRESHOLD
        )
    dsm5_provisional = all(
        cluster_symptom_counts[c] >= need for c, need in _PCL5_CLUSTER_RULE.items()
    )
    probable = score >= 33
    flags: list[str] = []
    if probable:
        flags.append("PCL-5 >=33 — probable PTSD; refer behavioral health")
    if dsm5_provisional:
        flags.append("meets provisional DSM-5 PTSD symptom-cluster criteria")
    return {
        "score": score,
        "probable_ptsd": probable,
        "dsm5_provisional_diagnosis": dsm5_provisional,
        "cluster_scores": cluster_scores,
        "cluster_symptom_counts": cluster_symptom_counts,
        "flags": flags,
        "red_alerts": [],
        "citation": _PCL5_CITATION,
    }


# ---- ACE -------------------------------------------------------------------------
_ACE_CITATION = "Felitti VJ, Anda RF, Nordenberg D et al. Am J Prev Med 1998;14(4):245-58."


def ace(items: list[int]) -> dict[str, Any]:
    clean = _coerce_items(items, 10)
    score = sum(1 if x > 0 else 0 for x in clean)
    if score >= 4:
        risk = "high"
        flags = ["ACE >= 4 — elevated lifetime risk for chronic disease, mental health, substance use"]
    elif score >= 1:
        risk = "elevated"
        flags = []
    else:
        risk = "minimal"
        flags = []
    return {"score": score, "risk": risk, "flags": flags, "red_alerts": [], "citation": _ACE_CITATION}


# ---- CRAFFT (adolescent) ---------------------------------------------------------
_CRAFFT_CITATION = "Knight JR, Sherritt L, Shrier LA et al. Arch Pediatr Adolesc Med 2002;156(6):607-14."


def crafft(items: list[int]) -> dict[str, Any]:
    clean = _coerce_items(items, 6)
    score = sum(1 if x > 0 else 0 for x in clean)
    positive = score >= 2
    return {
        "score": score,
        "positive": positive,
        "flags": ["positive — full substance use assessment indicated"] if positive else [],
        "red_alerts": [],
        "citation": _CRAFFT_CITATION,
    }


# ---- PRAPARE (SDoH) --------------------------------------------------------------
PRAPARE_DOMAINS = [
    "race_ethnicity", "language", "housing_situation", "housing_stability",
    "food_security", "transportation", "utilities", "childcare", "education",
    "employment", "income", "insurance", "stress", "social_isolation", "incarceration",
    "refugee_status", "safety_at_home", "safety_in_community", "physical_activity",
    "tobacco_use", "alcohol_drug_use",
]


def prapare(answers: dict[str, Any]) -> dict[str, Any]:
    """Counts positive risk factors. answers is {domain: bool|str|int}."""
    risk_keys = []
    if answers.get("housing_situation") == "homeless":
        risk_keys.append("housing")
    if answers.get("housing_stability") == "worried":
        risk_keys.append("housing_instability")
    if answers.get("food_security") in ("often", "sometimes"):
        risk_keys.append("food_insecurity")
    if answers.get("transportation") == "lack":
        risk_keys.append("transportation")
    if answers.get("utilities") == "shut_off_threat":
        risk_keys.append("utilities")
    if answers.get("safety_at_home") == "unsafe":
        risk_keys.append("intimate_partner_violence")
    if answers.get("stress") in ("a_lot", "very_much"):
        risk_keys.append("stress")
    if answers.get("social_isolation") in ("never", "rarely"):
        risk_keys.append("social_isolation")
    z_codes = []
    if "housing" in risk_keys:
        z_codes.append("Z59.0")
    if "housing_instability" in risk_keys:
        z_codes.append("Z59.1")
    if "food_insecurity" in risk_keys:
        z_codes.append("Z59.41")
    if "transportation" in risk_keys:
        z_codes.append("Z59.82")
    if "utilities" in risk_keys:
        z_codes.append("Z59.12")
    if "intimate_partner_violence" in risk_keys:
        z_codes.append("Z63.0")
    if "social_isolation" in risk_keys:
        z_codes.append("Z60.2")
    return {
        "risk_count": len(risk_keys),
        "risks": risk_keys,
        "icd10_z_codes": z_codes,
        "community_resource_categories": _community_categories(risk_keys),
    }


def _community_categories(risks: list[str]) -> list[str]:
    cat: list[str] = []
    if "housing" in risks or "housing_instability" in risks:
        cat.append("housing assistance")
    if "food_insecurity" in risks:
        cat.append("food banks / SNAP enrollment")
    if "transportation" in risks:
        cat.append("medical transportation programs")
    if "utilities" in risks:
        cat.append("LIHEAP / utility assistance")
    if "intimate_partner_violence" in risks:
        cat.append("domestic violence hotline + shelter")
    if "social_isolation" in risks:
        cat.append("community senior or peer support programs")
    return cat


# ---- Registry --------------------------------------------------------------------
SCREENERS: dict[str, dict[str, Any]] = {
    "phq9": {
        "name": "PHQ-9 — depression",
        "fn": phq9,
        "expected_items": 9,
        "items": [
            "Little interest or pleasure in doing things",
            "Feeling down, depressed, or hopeless",
            "Trouble falling or staying asleep, or sleeping too much",
            "Feeling tired or having little energy",
            "Poor appetite or overeating",
            "Feeling bad about yourself",
            "Trouble concentrating",
            "Moving or speaking slowly, or being fidgety/restless",
            "Thoughts that you would be better off dead or of hurting yourself",
        ],
        "scale": "0=not at all, 1=several days, 2=more than half the days, 3=nearly every day",
        "citation": _PHQ9_CITATION,
    },
    "gad7": {
        "name": "GAD-7 — anxiety",
        "fn": gad7,
        "expected_items": 7,
        "items": [
            "Feeling nervous, anxious, or on edge",
            "Not being able to stop or control worrying",
            "Worrying too much about different things",
            "Trouble relaxing",
            "Being so restless it's hard to sit still",
            "Becoming easily annoyed or irritable",
            "Feeling afraid as if something awful might happen",
        ],
        "scale": "0=not at all, 1=several days, 2=more than half the days, 3=nearly every day",
        "citation": _GAD7_CITATION,
    },
    "audit_c": {
        "name": "AUDIT-C — alcohol misuse",
        "fn": audit_c,
        "expected_items": 3,
        "items": [
            "How often do you have a drink containing alcohol?",
            "How many standard drinks on a typical drinking day?",
            "How often do you have 6 or more drinks on one occasion?",
        ],
        "scale": "0-4 per item; 3 items",
        "citation": _AUDITC_CITATION,
    },
    "epds": {
        "name": "EPDS — perinatal depression",
        "fn": epds,
        "expected_items": 10,
        "items": [
            "I have been able to laugh and see the funny side of things",
            "I have looked forward with enjoyment to things",
            "I have blamed myself unnecessarily when things went wrong",
            "I have been anxious or worried for no good reason",
            "I have felt scared or panicky for no very good reason",
            "Things have been getting on top of me",
            "I have been so unhappy that I have had difficulty sleeping",
            "I have felt sad or miserable",
            "I have been so unhappy that I have been crying",
            "The thought of harming myself has occurred to me",
        ],
        "scale": "0-3 per item; 10 items",
        "citation": _EPDS_CITATION,
    },
    "pcl5": {
        "name": "PCL-5 — PTSD",
        "fn": pcl5,
        "expected_items": 20,
        # Real 20 DSM-5 PCL-5 items. "In the past month, how much were you bothered by:"
        "items": [
            "Repeated, disturbing, and unwanted memories of the stressful experience",
            "Repeated, disturbing dreams of the stressful experience",
            "Suddenly feeling or acting as if the stressful experience were actually happening again",
            "Feeling very upset when something reminded you of the stressful experience",
            "Having strong physical reactions when something reminded you of the stressful experience",
            "Avoiding memories, thoughts, or feelings related to the stressful experience",
            "Avoiding external reminders of the stressful experience (people, places, conversations, activities, objects, situations)",
            "Trouble remembering important parts of the stressful experience",
            "Having strong negative beliefs about yourself, other people, or the world",
            "Blaming yourself or someone else for the stressful experience or what happened after it",
            "Having strong negative feelings such as fear, horror, anger, guilt, or shame",
            "Loss of interest in activities that you used to enjoy",
            "Feeling distant or cut off from other people",
            "Trouble experiencing positive feelings",
            "Irritable behavior, angry outbursts, or acting aggressively",
            "Taking too many risks or doing things that could cause you harm",
            "Being superalert or watchful or on guard",
            "Feeling jumpy or easily startled",
            "Having difficulty concentrating",
            "Trouble falling or staying asleep",
        ],
        "scale": "0=not at all, 1=a little bit, 2=moderately, 3=quite a bit, 4=extremely; 20 items",
        "citation": _PCL5_CITATION,
    },
    "ace": {
        "name": "Adverse Childhood Experiences",
        "fn": ace,
        "expected_items": 10,
        "items": [
            "Verbal abuse before age 18",
            "Physical abuse",
            "Sexual abuse",
            "Emotional neglect",
            "Physical neglect",
            "Parental separation/divorce",
            "Household intimate partner violence",
            "Household substance abuse",
            "Household mental illness",
            "Household incarceration",
        ],
        "scale": "yes/no per item",
        "citation": _ACE_CITATION,
    },
    "crafft": {
        "name": "CRAFFT — adolescent substance",
        "fn": crafft,
        "expected_items": 6,
        "items": [
            "Car: ridden with substance-impaired driver",
            "Relax: used to relax/feel better",
            "Alone: used while alone",
            "Forget: forgotten things you did while using",
            "Family/Friends say cut down",
            "Trouble while using",
        ],
        "scale": "yes/no per item",
        "citation": _CRAFFT_CITATION,
    },
    "prapare": {
        "name": "PRAPARE — social determinants",
        "fn": prapare,
        "expected_items": None,
        "items": PRAPARE_DOMAINS,
        "scale": "categorical answers",
        "citation": "National Association of Community Health Centers, PRAPARE, 2016.",
    },
}


def list_screeners() -> list[dict[str, Any]]:
    return [
        {
            "key": k,
            "name": v["name"],
            "items": v["items"],
            "scale": v["scale"],
            "expected_items": v.get("expected_items"),
            "citation": v.get("citation", ""),
        }
        for k, v in SCREENERS.items()
    ]


def score(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Score a screener. Returns a structured payload.

    Shapes:
      unknown screener -> {"error": "..."}
      bad item count   -> {"screener", "result": None, "missing": [idx...], "error": "..."}
      success          -> {"screener", "result": {...}}
    """
    if key not in SCREENERS:
        return {"error": f"unknown screener '{key}'"}
    fn = SCREENERS[key]["fn"]
    try:
        if key == "audit_c":
            return {"screener": key, "result": fn(payload.get("items") or [], payload.get("sex", "M"))}
        if key == "prapare":
            return {"screener": key, "result": fn(payload.get("answers") or {})}
        return {"screener": key, "result": fn(payload.get("items") or [])}
    except ScreenerInputError as e:
        return {"screener": key, "result": None, "missing": e.missing, "error": str(e)}
    except Exception as e:
        return {"screener": key, "result": None, "missing": [], "error": str(e)}


_AUTO_SYSTEM = """You are extracting validated screener responses from an ED encounter transcript.
Only fill items the patient explicitly answered. If the transcript is silent on an item,
mark its index in unknown_indices — never guess a value.

Return JSON ONLY:
{
  "<screener_key>": {"items": [int...], "unknown_indices": [int...]} OR
  "<screener_key>": {"answers": {...}, "unknown": ["..."]}  // for PRAPARE
}

For item-based screeners, `items` must have exactly the expected length; place a 0
placeholder at any index you list in unknown_indices.
"""


def auto_extract(transcript: str, screener_keys: list[str]) -> dict[str, Any]:
    """LLM auto-extraction of screener responses.

    Returns a dict keyed by screener with structured results. Each entry carries
    a `missing` list (item indices the model could not determine, or that are
    out of range). A screener is only scored when nothing is missing; red-score
    suicidality alerts surface directly on the scored result.

    Output shape:
      {"<key>": {"name", "result": {...}|None, "missing": [int...], "citation"}}
    """
    from lib import claude
    from lib.config import settings

    if not claude.available():
        return {}
    schema = {
        k: {"items": SCREENERS[k]["items"], "expected_items": SCREENERS[k].get("expected_items")}
        for k in screener_keys
        if k in SCREENERS
    }
    user = (
        f'Transcript:\n"""\n{transcript[:6000]}\n"""\n\n'
        f"Schemas:\n{json.dumps(schema, indent=2)}\n\nReturn JSON now."
    )
    try:
        resp = claude.messages_create(
            model=settings.model_utility,
            max_tokens=900,
            system=_AUTO_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="screener_extract",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
    except Exception as e:
        log.warning("screener auto-extract failed: %s", e)
        return {}

    out: dict[str, Any] = {}
    for k, payload in parsed.items():
        if k not in SCREENERS or not isinstance(payload, dict):
            continue
        meta = SCREENERS[k]
        citation = meta.get("citation", "")
        if k == "prapare":
            unknown = list(payload.get("unknown") or [])
            if unknown:
                out[k] = {"name": meta["name"], "result": None, "missing": unknown, "citation": citation}
            else:
                res = score(k, {"answers": payload.get("answers") or {}})
                out[k] = {
                    "name": meta["name"],
                    "result": res.get("result"),
                    "missing": res.get("missing", []),
                    "citation": citation,
                }
            continue

        expected = meta.get("expected_items") or 0
        items = payload.get("items") or []
        unknown_idx = sorted(set(int(i) for i in (payload.get("unknown_indices") or []) if str(i).lstrip("-").isdigit()))
        # Any index not provided by the model is also missing.
        provided = len(items)
        absent = [i for i in range(expected) if i >= provided]
        missing = sorted(set(unknown_idx) | set(absent))
        if missing:
            out[k] = {"name": meta["name"], "result": None, "missing": missing, "citation": citation}
            continue
        sp = {"items": items}
        if k == "audit_c":
            sp["sex"] = payload.get("sex", "M")
        res = score(k, sp)
        out[k] = {
            "name": meta["name"],
            "result": res.get("result"),
            "missing": res.get("missing", []),
            "citation": citation,
        }
    return out
