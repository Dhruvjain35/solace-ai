"""Real-time eligibility (270/271) — Stedi-shaped mock for now.

Mirrors the Stedi `/healthcare/eligibility` response shape so swapping in the real
client is a one-line change:
    response = stedi.eligibility.check(payload)
becomes
    response = mock_check(payload)
and back. All field names mirror Stedi's JSON.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

log = logging.getLogger(__name__)


_PAYER_PROFILES: dict[str, dict[str, Any]] = {
    "aetna":      {"primary": "Aetna",      "ppo_pcp_copay": 20, "ppo_specialist_copay": 40, "ppo_ed_copay": 200, "deductible_total": 1500},
    "bcbs":       {"primary": "Blue Cross", "ppo_pcp_copay": 25, "ppo_specialist_copay": 50, "ppo_ed_copay": 250, "deductible_total": 2000},
    "cigna":      {"primary": "Cigna",      "ppo_pcp_copay": 30, "ppo_specialist_copay": 50, "ppo_ed_copay": 300, "deductible_total": 1800},
    "uhc":        {"primary": "UnitedHealthcare", "ppo_pcp_copay": 25, "ppo_specialist_copay": 45, "ppo_ed_copay": 275, "deductible_total": 1750},
    "kaiser":     {"primary": "Kaiser Permanente", "ppo_pcp_copay": 15, "ppo_specialist_copay": 25, "ppo_ed_copay": 100, "deductible_total": 500},
    "humana":     {"primary": "Humana",     "ppo_pcp_copay": 20, "ppo_specialist_copay": 40, "ppo_ed_copay": 200, "deductible_total": 1500},
    "medicare":   {"primary": "Medicare Part B", "ppo_pcp_copay": 0,  "ppo_specialist_copay": 0,  "ppo_ed_copay": 0,   "deductible_total": 240},
    "medicaid":   {"primary": "Medicaid",   "ppo_pcp_copay": 0,  "ppo_specialist_copay": 0,  "ppo_ed_copay": 0,   "deductible_total": 0},
}


def _normalize_payer(name: str) -> str:
    n = (name or "").strip().lower()
    for k in _PAYER_PROFILES:
        if k in n or n in k:
            return k
    return "uhc"  # default profile


def _seeded_remaining(member_id: str, total: int) -> int:
    """Deterministic 'remaining deductible' based on member id so each test patient
    behaves consistently across calls. Real 271 has actual usage."""
    if total == 0:
        return 0
    digest = hashlib.sha256(member_id.encode("utf-8")).hexdigest()
    pct = int(digest[:4], 16) / 0xFFFF
    return int(total * pct)


def check(
    payer_name: str,
    member_id: str,
    patient_first: str,
    patient_last: str,
    patient_dob: str,
    service_date: str | None = None,
    service_type: str = "30",  # 30=Health Benefit Plan Coverage
) -> dict[str, Any]:
    """Stedi-shaped 271 eligibility response."""
    use_real = os.getenv("STEDI_API_KEY") and os.getenv("USE_REAL_ELIGIBILITY") == "1"
    if use_real:
        try:
            return _real_stedi(payer_name, member_id, patient_first, patient_last, patient_dob, service_date)
        except Exception as e:
            log.warning("Real Stedi call failed, falling back to mock: %s", e)

    payer_key = _normalize_payer(payer_name)
    profile = _PAYER_PROFILES[payer_key]
    deductible_remaining = _seeded_remaining(member_id, profile["deductible_total"])
    oop_max = profile["deductible_total"] * 4
    oop_remaining = _seeded_remaining(member_id + "x", oop_max)

    return {
        "controlNumber": hashlib.md5(member_id.encode()).hexdigest()[:9],
        "tradingPartnerServiceId": payer_key.upper(),
        "subscriber": {
            "memberId": member_id,
            "firstName": patient_first,
            "lastName": patient_last,
            "dateOfBirth": patient_dob.replace("-", ""),
        },
        "payer": {"name": profile["primary"]},
        "planInformation": {
            "groupNumber": "GRP-001",
            "planName": f"{profile['primary']} PPO",
        },
        "planStatus": [
            {"statusCode": "1", "status": "Active Coverage", "serviceTypeCodes": [service_type]},
        ],
        "benefitsInformation": [
            {
                "code": "C", "name": "Deductible", "coverageLevelCode": "FAM",
                "benefitAmount": str(profile["deductible_total"]),
                "amountPaid": str(profile["deductible_total"] - deductible_remaining),
                "amountRemaining": str(deductible_remaining),
            },
            {
                "code": "G", "name": "Out of Pocket (Stop Loss)", "coverageLevelCode": "FAM",
                "benefitAmount": str(oop_max),
                "amountRemaining": str(oop_remaining),
            },
            {
                "code": "B", "name": "Co-Payment", "serviceTypeCodes": ["98"],  # Professional (Physician) Visit
                "benefitAmount": str(profile["ppo_pcp_copay"]),
                "description": "Primary care visit",
            },
            {
                "code": "B", "name": "Co-Payment", "serviceTypeCodes": ["UC"],  # Urgent Care
                "benefitAmount": str(profile["ppo_specialist_copay"]),
                "description": "Urgent care visit",
            },
            {
                "code": "B", "name": "Co-Payment", "serviceTypeCodes": ["86"],  # ED
                "benefitAmount": str(profile["ppo_ed_copay"]),
                "description": "Emergency room",
            },
            {
                "code": "U", "name": "Prior Authorization Required", "serviceTypeCodes": ["MR"],
                "description": "Required for advanced imaging (MRI, CT, PET)",
            },
        ],
        "_meta": {"source": "solace_mock", "note": "Replace with Stedi by setting STEDI_API_KEY + USE_REAL_ELIGIBILITY=1"},
    }


def _real_stedi(payer_name: str, member_id: str, first: str, last: str, dob: str, service_date: str | None) -> dict[str, Any]:  # pragma: no cover
    import requests
    api_key = os.environ["STEDI_API_KEY"]
    payload = {
        "controlNumber": "000000001",
        "tradingPartnerServiceId": _normalize_payer(payer_name).upper(),
        "subscriber": {"memberId": member_id, "firstName": first, "lastName": last, "dateOfBirth": dob.replace("-", "")},
    }
    r = requests.post(
        "https://healthcare.us.stedi.com/2024-04-01/eligibility",
        headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def summarize_for_clinician(response: dict[str, Any]) -> dict[str, Any]:
    """Distill a 271 down to the 5 numbers a check-in nurse actually wants."""
    benefits = response.get("benefitsInformation", [])
    out = {
        "active": any(s.get("status") == "Active Coverage" for s in response.get("planStatus", [])),
        "plan": response.get("planInformation", {}).get("planName", ""),
        "payer": response.get("payer", {}).get("name", ""),
        "deductible_remaining": None,
        "oop_remaining": None,
        "pcp_copay": None,
        "specialist_copay": None,
        "ed_copay": None,
        "prior_auth_advanced_imaging": False,
    }
    for b in benefits:
        if b.get("code") == "C":
            out["deductible_remaining"] = b.get("amountRemaining")
        elif b.get("code") == "G":
            out["oop_remaining"] = b.get("amountRemaining")
        elif b.get("code") == "B":
            stcs = b.get("serviceTypeCodes", [])
            if "98" in stcs:
                out["pcp_copay"] = b.get("benefitAmount")
            elif "UC" in stcs:
                out["specialist_copay"] = b.get("benefitAmount")
            elif "86" in stcs:
                out["ed_copay"] = b.get("benefitAmount")
        elif b.get("code") == "U" and "MR" in b.get("serviceTypeCodes", []):
            out["prior_auth_advanced_imaging"] = True
    return out
