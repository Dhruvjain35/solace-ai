"""Validated PRO/screener library — deterministic scoring + LLM auto-extract.

All scoring rubrics are the published gold-standard cutoffs:
    - PHQ-9 depression (0-27): 0-4 none, 5-9 mild, 10-14 moderate, 15-19 mod-severe, 20-27 severe.
      Item 9 (suicidality) is a red flag at any positive score.
    - GAD-7 anxiety (0-21): 0-4 none, 5-9 mild, 10-14 moderate, 15-21 severe.
    - AUDIT-C alcohol (0-12): >=4 men, >=3 women suggests alcohol misuse.
    - EPDS perinatal depression (0-30): >=10 possible, >=13 likely.
    - PCL-5 PTSD (0-80): >=33 probable PTSD.
    - PRAPARE (SDoH) — multi-domain risk count.
    - ACE (Adverse Childhood Experiences, 0-10): >=4 high lifetime risk.
    - CRAFFT (adolescent substance): >=2 yes is positive.
    - Vanderbilt (peds ADHD) — placeholder structure (full form is large).
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _sum(items: list[int], expected: int) -> int:
    if len(items) != expected:
        raise ValueError(f"expected {expected} items, got {len(items)}")
    return sum(int(x) for x in items)


# ---- PHQ-9 -----------------------------------------------------------------------
def phq9(items: list[int]) -> dict[str, Any]:
    score = _sum(items, 9)
    si = items[8] > 0
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
    flags = []
    if si:
        flags.append("positive item 9 — suicidality screen positive — ASSESS NOW")
    if score >= 15:
        flags.append("major depressive disorder likely — same-day pharmacotherapy + counseling discussion")
    return {"score": score, "severity": sev, "flags": flags, "suicidality": si}


# ---- GAD-7 -----------------------------------------------------------------------
def gad7(items: list[int]) -> dict[str, Any]:
    score = _sum(items, 7)
    if score <= 4:
        sev = "minimal"
    elif score <= 9:
        sev = "mild"
    elif score <= 14:
        sev = "moderate"
    else:
        sev = "severe"
    flags = []
    if score >= 15:
        flags.append("severe GAD — consider pharmacotherapy + referral")
    return {"score": score, "severity": sev, "flags": flags}


# ---- AUDIT-C ---------------------------------------------------------------------
def audit_c(items: list[int], sex: str = "M") -> dict[str, Any]:
    score = _sum(items, 3)
    cutoff = 4 if sex.upper().startswith("M") else 3
    positive = score >= cutoff
    return {
        "score": score,
        "cutoff": cutoff,
        "positive": positive,
        "flags": ["alcohol misuse screen positive — brief intervention indicated"] if positive else [],
    }


# ---- EPDS (perinatal) ------------------------------------------------------------
def epds(items: list[int]) -> dict[str, Any]:
    score = _sum(items, 10)
    si = items[9] > 0
    if score >= 13:
        sev = "likely depression"
    elif score >= 10:
        sev = "possible depression"
    else:
        sev = "low"
    flags = []
    if si:
        flags.append("positive item 10 — self-harm screen positive — ASSESS NOW")
    if score >= 13:
        flags.append("perinatal depression likely — refer perinatal psychiatry")
    return {"score": score, "severity": sev, "flags": flags, "suicidality": si}


# ---- PCL-5 PTSD ------------------------------------------------------------------
def pcl5(items: list[int]) -> dict[str, Any]:
    score = _sum(items, 20)
    return {
        "score": score,
        "probable_ptsd": score >= 33,
        "flags": ["probable PTSD — refer behavioral health"] if score >= 33 else [],
    }


# ---- ACE -------------------------------------------------------------------------
def ace(items: list[int]) -> dict[str, Any]:
    score = sum(1 if int(x) > 0 else 0 for x in items)
    if score >= 4:
        risk = "high"
        flags = ["ACE >= 4 — elevated lifetime risk for chronic disease, mental health, substance use"]
    elif score >= 1:
        risk = "elevated"
        flags = []
    else:
        risk = "minimal"
        flags = []
    return {"score": score, "risk": risk, "flags": flags}


# ---- CRAFFT (adolescent) ---------------------------------------------------------
def crafft(items: list[int]) -> dict[str, Any]:
    score = sum(1 if int(x) > 0 else 0 for x in items)
    return {
        "score": score,
        "positive": score >= 2,
        "flags": ["positive — full substance use assessment indicated"] if score >= 2 else [],
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
    },
    "gad7": {
        "name": "GAD-7 — anxiety",
        "fn": gad7,
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
    },
    "audit_c": {
        "name": "AUDIT-C — alcohol misuse",
        "fn": audit_c,
        "items": [
            "How often do you have a drink containing alcohol?",
            "How many standard drinks on a typical drinking day?",
            "How often do you have 6 or more drinks on one occasion?",
        ],
        "scale": "0-4 per item; 3 items",
    },
    "epds": {
        "name": "EPDS — perinatal depression",
        "fn": epds,
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
    },
    "pcl5": {
        "name": "PCL-5 — PTSD",
        "fn": pcl5,
        "items": ["20 DSM-5 PTSD symptom prompts"],
        "scale": "0-4 per item; 20 items",
    },
    "ace": {
        "name": "Adverse Childhood Experiences",
        "fn": ace,
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
    },
    "crafft": {
        "name": "CRAFFT — adolescent substance",
        "fn": crafft,
        "items": [
            "Car: ridden with substance-impaired driver",
            "Relax: used to relax/feel better",
            "Alone: used while alone",
            "Forget: forgotten things you did while using",
            "Family/Friends say cut down",
            "Trouble while using",
        ],
        "scale": "yes/no per item",
    },
    "prapare": {
        "name": "PRAPARE — social determinants",
        "fn": prapare,
        "items": PRAPARE_DOMAINS,
        "scale": "categorical answers",
    },
}


def list_screeners() -> list[dict[str, Any]]:
    return [
        {"key": k, "name": v["name"], "items": v["items"], "scale": v["scale"]}
        for k, v in SCREENERS.items()
    ]


def score(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    if key not in SCREENERS:
        return {"error": f"unknown screener '{key}'"}
    fn = SCREENERS[key]["fn"]
    try:
        if key == "audit_c":
            return {"screener": key, "result": fn(payload.get("items") or [], payload.get("sex", "M"))}
        if key == "prapare":
            return {"screener": key, "result": fn(payload.get("answers") or {})}
        return {"screener": key, "result": fn(payload.get("items") or [])}
    except Exception as e:
        return {"screener": key, "error": str(e)}


_AUTO_SYSTEM = """You are extracting validated screener responses from an ED encounter transcript.
Only fill items the patient explicitly answered. If silent, mark unknown.

Return JSON ONLY:
{
  "<screener_key>": {"items": [int...], "unknown_indices": [int...]} OR
  "<screener_key>": {"answers": {...}, "unknown": ["..."]}  // for PRAPARE
}
"""


def auto_extract(transcript: str, screener_keys: list[str]) -> dict[str, Any]:
    from lib import claude
    from lib.config import settings

    if not settings.anthropic_api_key:
        return {}
    schema = {k: SCREENERS[k]["items"] for k in screener_keys if k in SCREENERS}
    user = (
        f'Transcript:\n"""\n{transcript[:6000]}\n"""\n\n'
        f"Schemas:\n{json.dumps(schema, indent=2)}\n\nReturn JSON now."
    )
    try:
        resp = claude.messages_create(
            model="claude-sonnet-4-5",
            max_tokens=900,
            system=_AUTO_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="screener_extract",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:
        log.warning("screener auto-extract failed: %s", e)
        return {}
