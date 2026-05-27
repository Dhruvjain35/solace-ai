"""Social Determinants of Health (SDoH) — PRAPARE / AHC-HRSN social-needs screener.

This module turns a patient's answers to a validated social-needs instrument into:
  1. a scored risk profile  -> `screen()`
  2. ICD-10 Z-code billing diagnoses (Z55-Z65 SDoH family) -> `screen()` / `z_codes()`
  3. a closed-loop community-resource referral payload  -> `build_referral()`

Two instruments are supported, both mapped onto a shared internal domain model:
  - PRAPARE  — Protocol for Responding to and Assessing Patients' Assets, Risks
               and Experiences (NACHC). Richer, 21-domain.
  - AHC-HRSN — CMS Accountable Health Communities Health-Related Social Needs
               screening tool. 5 core domains (housing, food, transportation,
               utilities, interpersonal safety) plus supplemental.

The referral payload is shaped to drop straight into a FindHelp (Aunt Bertha) or
Unite Us closed-loop community-information-exchange API: a referral with a
resource category, consent flag, status lifecycle, and a feedback loop slot.

Pure functions — no I/O, no AI calls, no boto3 (ARCH-002). Routers persist the
output via db.storage; this module only computes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Domain model — every supported instrument answer maps onto one of these keys.
# ---------------------------------------------------------------------------
DOMAINS: tuple[str, ...] = (
    "housing_instability",   # worried about losing housing / unstable
    "homelessness",          # currently without stable housing
    "food_insecurity",       # ran out of food / worried about food
    "transportation",        # lack of transport to medical or daily needs
    "utilities",             # utility shut-off threatened or occurred
    "interpersonal_safety",  # unsafe at home / IPV
    "financial_strain",      # cannot afford basics / employment loss
    "social_isolation",      # rarely sees or talks to people
    "childcare",             # lack of childcare blocks work/appointments
    "education",             # less than high-school / literacy barrier
    "incarceration",         # recent justice-system involvement
)

# SDoH ICD-10 Z-code mapping (Z55-Z65 family). These are billable on a claim and
# drive risk adjustment + population-health reporting.
Z_CODE_MAP: dict[str, dict[str, str]] = {
    "homelessness":         {"code": "Z59.0",  "label": "Homelessness"},
    "housing_instability":  {"code": "Z59.1",  "label": "Inadequate housing"},
    "food_insecurity":      {"code": "Z59.41", "label": "Food insecurity"},
    "transportation":       {"code": "Z59.82", "label": "Transportation insecurity"},
    "utilities":            {"code": "Z59.12", "label": "Inadequate housing utilities"},
    "interpersonal_safety": {"code": "Z63.0",  "label": "Problems in relationship with spouse or partner"},
    "financial_strain":     {"code": "Z59.86", "label": "Financial insecurity"},
    "social_isolation":     {"code": "Z60.2",  "label": "Problems related to living alone"},
    "childcare":            {"code": "Z63.6",  "label": "Dependent relative needing care at home"},
    "education":            {"code": "Z55.9",  "label": "Problems related to education and literacy"},
    "incarceration":        {"code": "Z65.1",  "label": "Imprisonment and other incarceration"},
}

# Community-resource category per domain — these are the canonical FindHelp /
# Unite Us service-category taxonomy terms a referral routes against.
RESOURCE_CATEGORY: dict[str, str] = {
    "homelessness":         "Housing — emergency shelter",
    "housing_instability":  "Housing — rent assistance & stability",
    "food_insecurity":      "Food — food banks & SNAP enrollment",
    "transportation":       "Transit — medical & daily transportation",
    "utilities":            "Utilities — LIHEAP & utility assistance",
    "interpersonal_safety": "Safety — domestic violence support & shelter",
    "financial_strain":     "Financial — emergency assistance & benefits",
    "social_isolation":     "Community — peer & senior support programs",
    "childcare":            "Childcare — subsidized care & vouchers",
    "education":            "Education — adult literacy & GED programs",
    "incarceration":        "Reentry — justice-involved support services",
}

# Domains where a positive screen is clinically high-acuity and should be acted
# on before the patient leaves.
_URGENT_DOMAINS: frozenset[str] = frozenset(
    {"homelessness", "interpersonal_safety", "food_insecurity"}
)

_RISK_BANDS = (
    (0, "none"),
    (1, "low"),
    (3, "moderate"),
    (5, "high"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Answer normalization — accept either instrument's raw answer vocabulary.
# ---------------------------------------------------------------------------
def _positive_domains(answers: dict[str, Any]) -> list[str]:
    """Return the list of DOMAINS that screen positive given raw answers.

    Accepts a flat dict keyed either by a DOMAIN name (truthy = positive) or by
    a known PRAPARE / AHC-HRSN field with its native answer vocabulary.
    """
    a = {k: v for k, v in (answers or {}).items()}
    positives: list[str] = []

    def add(domain: str) -> None:
        if domain not in positives:
            positives.append(domain)

    # Direct DOMAIN-keyed booleans (Solace internal form).
    for d in DOMAINS:
        if a.get(d) in (True, "yes", "y", 1, "1"):
            add(d)

    # PRAPARE / AHC-HRSN native fields.
    if a.get("housing_situation") in ("homeless", "no_steady"):
        add("homelessness")
    if a.get("housing_stability") in ("worried", "yes") or a.get("housing_worry") == "yes":
        add("housing_instability")
    if a.get("food_security") in ("often", "sometimes") or a.get("food_worry") == "yes":
        add("food_insecurity")
    if a.get("transportation") in ("lack", "yes", "kept_from"):
        add("transportation")
    if a.get("utilities") in ("shut_off_threat", "shut_off", "yes"):
        add("utilities")
    if a.get("safety_at_home") == "unsafe" or a.get("feel_safe") == "no":
        add("interpersonal_safety")
    if a.get("financial_strain") in ("a_lot", "very_much", "yes") or a.get("hard_to_pay") == "yes":
        add("financial_strain")
    if a.get("social_isolation") in ("never", "rarely", "less_than_once_week"):
        add("social_isolation")
    if a.get("childcare") in ("lack", "yes", "need"):
        add("childcare")
    if a.get("education") in ("less_than_hs", "lt_high_school"):
        add("education")
    if a.get("incarceration") in ("recent", "yes"):
        add("incarceration")

    return positives


def _risk_level(count: int) -> str:
    level = "none"
    for threshold, label in _RISK_BANDS:
        if count >= threshold:
            level = label
    return level


def z_codes(domains: list[str]) -> list[dict[str, str]]:
    """Map positive domains to billable ICD-10 Z-codes (deduped, stable order)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for d in domains:
        entry = Z_CODE_MAP.get(d)
        if entry and entry["code"] not in seen:
            seen.add(entry["code"])
            out.append({"domain": d, **entry})
    return out


def screen(answers: dict[str, Any], instrument: str = "prapare") -> dict[str, Any]:
    """Score a completed social-needs screener.

    Args:
        answers: flat dict of the patient's responses (PRAPARE, AHC-HRSN, or
                 Solace internal DOMAIN-keyed booleans).
        instrument: "prapare" or "ahc_hrsn" — recorded for provenance.

    Returns:
        {
          "instrument": str,
          "screened_at": ISO-8601 str,
          "positive_domains": [str, ...],
          "risk_count": int,
          "risk_level": "none"|"low"|"moderate"|"high",
          "urgent": bool,                       # any high-acuity domain positive
          "icd10_z_codes": [{"domain","code","label"}, ...],
          "recommended_referrals": [str, ...],  # resource categories to refer to
          "needs": [                            # per-domain detail for the UI
             {"domain","resource_category","z_code","z_label","urgent"}, ...
          ],
        }
    """
    inst = (instrument or "prapare").lower()
    if inst not in ("prapare", "ahc_hrsn"):
        inst = "prapare"

    positives = _positive_domains(answers)
    codes = z_codes(positives)
    urgent = any(d in _URGENT_DOMAINS for d in positives)

    needs: list[dict[str, Any]] = []
    for d in positives:
        entry = Z_CODE_MAP.get(d, {})
        needs.append({
            "domain": d,
            "resource_category": RESOURCE_CATEGORY.get(d, "Community resources"),
            "z_code": entry.get("code"),
            "z_label": entry.get("label"),
            "urgent": d in _URGENT_DOMAINS,
        })

    return {
        "instrument": inst,
        "screened_at": _now(),
        "positive_domains": positives,
        "risk_count": len(positives),
        "risk_level": _risk_level(len(positives)),
        "urgent": urgent,
        "icd10_z_codes": codes,
        "recommended_referrals": [
            RESOURCE_CATEGORY.get(d, "Community resources") for d in positives
        ],
        "needs": needs,
    }


def build_referral(
    *,
    domain: str,
    patient_ref: str,
    consent: bool,
    organization: str | None = None,
    note: str | None = None,
    network: str = "findhelp",
) -> dict[str, Any]:
    """Build a closed-loop community-resource referral payload.

    Shaped to post directly to a FindHelp (Aunt Bertha) or Unite Us community
    information exchange. The payload carries the consent flag, a status
    lifecycle, and a `feedback_loop` slot the CIE writes back into when the
    community-based organization accepts, serves, or closes the referral.

    Args:
        domain: a key from DOMAINS (the social need being referred).
        patient_ref: opaque patient reference (UUID / FHIR id) — never PHI text.
        consent: patient consent to share data with the referral network.
        organization: optional named CBO to route to; else network auto-routes.
        note: optional free-text context for the receiving CBO.
        network: "findhelp" or "unite_us".

    Returns:
        A referral dict. When `consent` is False the referral is created in
        status "blocked_no_consent" so the loop is auditable but not transmitted.
    """
    net = (network or "findhelp").lower()
    if net not in ("findhelp", "unite_us"):
        net = "findhelp"

    resource_category = RESOURCE_CATEGORY.get(domain, "Community resources")
    z = Z_CODE_MAP.get(domain, {})
    referral_id = str(uuid.uuid4())
    created = _now()

    status = "pending" if consent else "blocked_no_consent"

    return {
        "referral_id": referral_id,
        "network": net,
        "created_at": created,
        "patient_ref": patient_ref,
        "domain": domain,
        "resource_category": resource_category,
        "target_organization": organization,
        "diagnosis": {
            "icd10": z.get("code"),
            "label": z.get("label"),
        },
        "consent": {
            "granted": bool(consent),
            "recorded_at": created if consent else None,
            "scope": "share-with-community-network" if consent else None,
        },
        "note": note,
        "status": status,
        "urgent": domain in _URGENT_DOMAINS,
        # Closed-loop tracking — the CIE writes these back as the referral moves.
        "feedback_loop": {
            "sent_at": None,
            "accepted_at": None,
            "served_at": None,
            "closed_at": None,
            "outcome": None,        # "resolved" | "unable_to_contact" | "declined" | ...
            "last_update": created,
        },
        # Status lifecycle the receiving network may advance through.
        "lifecycle": [
            "pending", "sent", "accepted", "in_progress", "served", "closed"
        ],
    }


def build_referrals(
    screen_result: dict[str, Any],
    *,
    patient_ref: str,
    consent: bool,
    network: str = "findhelp",
) -> list[dict[str, Any]]:
    """Convenience: build one referral per positive domain from a `screen()` result."""
    referrals: list[dict[str, Any]] = []
    for domain in screen_result.get("positive_domains", []):
        referrals.append(build_referral(
            domain=domain,
            patient_ref=patient_ref,
            consent=consent,
            network=network,
        ))
    return referrals
