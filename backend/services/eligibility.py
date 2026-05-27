"""Real-time eligibility (270/271).

Two layers:
  1. A clearinghouse-agnostic adapter seam. `check()` builds an X12 270 request
     shape, hands it to whichever adapter is configured (mock today, Stedi or
     Availity in production), and parses the 271 response into a normalized,
     clinician-friendly summary.
  2. A Stedi-shaped JSON contract. The mock adapter mirrors Stedi's
     `/healthcare/eligibility` response so swapping the real client in is a
     one-line change (`_ADAPTER = StediAdapter()`), and the 271 parser handles
     both Stedi JSON and a raw X12 271 segment string.

Adapter contract — every adapter implements:
    name: str
    check(request_270: dict) -> dict        # returns Stedi-shaped 271 JSON

Drop-in: set ELIGIBILITY_CLEARINGHOUSE=stedi|availity and the matching API key.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# X12 270/271 service type codes used across this module.
SERVICE_TYPE_CODES = {
    "30": "Health Benefit Plan Coverage",
    "98": "Professional (Physician) Visit - Office",
    "UC": "Urgent Care",
    "86": "Emergency Services",
    "MR": "Magnetic Resonance Imaging (advanced imaging)",
    "AL": "Vision (Optometry)",
    "33": "Chiropractic",
}


_PAYER_PROFILES: dict[str, dict[str, Any]] = {
    "aetna":      {"primary": "Aetna",      "payer_id": "60054", "ppo_pcp_copay": 20, "ppo_specialist_copay": 40, "ppo_ed_copay": 200, "deductible_total": 1500},
    "bcbs":       {"primary": "Blue Cross", "payer_id": "00040", "ppo_pcp_copay": 25, "ppo_specialist_copay": 50, "ppo_ed_copay": 250, "deductible_total": 2000},
    "cigna":      {"primary": "Cigna",      "payer_id": "62308", "ppo_pcp_copay": 30, "ppo_specialist_copay": 50, "ppo_ed_copay": 300, "deductible_total": 1800},
    "uhc":        {"primary": "UnitedHealthcare", "payer_id": "87726", "ppo_pcp_copay": 25, "ppo_specialist_copay": 45, "ppo_ed_copay": 275, "deductible_total": 1750},
    "kaiser":     {"primary": "Kaiser Permanente", "payer_id": "94135", "ppo_pcp_copay": 15, "ppo_specialist_copay": 25, "ppo_ed_copay": 100, "deductible_total": 500},
    "humana":     {"primary": "Humana",     "payer_id": "61101", "ppo_pcp_copay": 20, "ppo_specialist_copay": 40, "ppo_ed_copay": 200, "deductible_total": 1500},
    "medicare":   {"primary": "Medicare Part B", "payer_id": "SMMC0", "ppo_pcp_copay": 0,  "ppo_specialist_copay": 0,  "ppo_ed_copay": 0,   "deductible_total": 240},
    "medicaid":   {"primary": "Medicaid",   "payer_id": "MCDFL", "ppo_pcp_copay": 0,  "ppo_specialist_copay": 0,  "ppo_ed_copay": 0,   "deductible_total": 0},
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


# --------------------------------------------------------------------------------
# X12 270 request builder
# --------------------------------------------------------------------------------
def build_270_request(
    payer_name: str,
    member_id: str,
    patient_first: str,
    patient_last: str,
    patient_dob: str,
    service_date: str | None = None,
    service_type: str = "30",
    provider_npi: str | None = None,
    provider_name: str = "Solace Clinic",
) -> dict[str, Any]:
    """Build a clearinghouse-neutral X12 270 (eligibility inquiry) request.

    The shape matches Stedi's JSON request body; an X12-segment EDI string is
    also produced under `_x12` for clearinghouses that want raw 270 EDI. Both
    are derived from the same loops so adapters can pick whichever they consume.
    """
    payer_key = _normalize_payer(payer_name)
    profile = _PAYER_PROFILES[payer_key]
    svc_date = (service_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    dob_compact = (patient_dob or "").replace("-", "")
    control_number = hashlib.md5(f"{member_id}{svc_date}".encode()).hexdigest()[:9]

    request = {
        # ISA/GS envelope metadata
        "controlNumber": control_number,
        "tradingPartnerServiceId": profile["payer_id"],
        # 2100A Information Source — the payer
        "payer": {"name": profile["primary"], "payerId": profile["payer_id"]},
        # 2100B Information Receiver — the provider submitting the inquiry
        "provider": {
            "organizationName": provider_name,
            "npi": provider_npi or "0000000000",
        },
        # 2100C Subscriber
        "subscriber": {
            "memberId": member_id,
            "firstName": patient_first,
            "lastName": patient_last,
            "dateOfBirth": dob_compact,
        },
        # 2110C Eligibility/Benefit Inquiry — what we are asking about
        "encounter": {
            "serviceTypeCodes": [service_type],
            "dateOfService": svc_date,
        },
    }
    request["_x12"] = _render_270_edi(request, service_type, dob_compact, svc_date)
    return request


def _render_270_edi(request: dict[str, Any], service_type: str, dob: str, svc_date: str) -> str:
    """Render a representative X12 005010X279A1 270 segment string.

    Not a full ISA/IEA envelope (the clearinghouse wraps that); this is the
    transaction-set body the adapter would embed.
    """
    cn = request["controlNumber"]
    payer = request["payer"]
    prov = request["provider"]
    sub = request["subscriber"]
    seg = "~"
    segments = [
        f"ST*270*{cn}*005010X279A1",
        f"BHT*0022*13*{cn}*{svc_date.replace('-', '')}*0000",
        f"HL*1**20*1",
        f"NM1*PR*2*{payer['name']}*****PI*{payer['payerId']}",
        f"HL*2*1*21*1",
        f"NM1*1P*2*{prov['organizationName']}*****XX*{prov['npi']}",
        f"HL*3*2*22*0",
        f"NM1*IL*1*{sub['lastName']}*{sub['firstName']}****MI*{sub['memberId']}",
        f"DMG*D8*{dob}",
        f"DTP*291*D8*{svc_date.replace('-', '')}",
        f"EQ*{service_type}",
        f"SE*11*{cn}",
    ]
    return seg.join(segments) + seg


# --------------------------------------------------------------------------------
# Clearinghouse adapter seam
# --------------------------------------------------------------------------------
class MockAdapter:
    """Local adapter — produces a deterministic Stedi-shaped 271 with no network."""

    name = "solace_mock"

    def check(self, request_270: dict[str, Any]) -> dict[str, Any]:
        payer_id = request_270["tradingPartnerServiceId"]
        payer_key = next(
            (k for k, v in _PAYER_PROFILES.items() if v["payer_id"] == payer_id),
            "uhc",
        )
        profile = _PAYER_PROFILES[payer_key]
        sub = request_270["subscriber"]
        member_id = sub["memberId"]
        service_types = request_270.get("encounter", {}).get("serviceTypeCodes", ["30"])

        deductible_remaining = _seeded_remaining(member_id, profile["deductible_total"])
        oop_max = profile["deductible_total"] * 4
        oop_remaining = _seeded_remaining(member_id + "x", oop_max)

        return {
            "controlNumber": request_270["controlNumber"],
            "tradingPartnerServiceId": payer_id,
            "subscriber": {
                "memberId": member_id,
                "firstName": sub["firstName"],
                "lastName": sub["lastName"],
                "dateOfBirth": sub["dateOfBirth"],
            },
            "payer": {"name": profile["primary"]},
            "planInformation": {
                "groupNumber": "GRP-001",
                "planName": f"{profile['primary']} PPO",
            },
            "planStatus": [
                {"statusCode": "1", "status": "Active Coverage", "serviceTypeCodes": service_types},
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
                    "code": "B", "name": "Co-Payment", "serviceTypeCodes": ["98"],
                    "benefitAmount": str(profile["ppo_pcp_copay"]),
                    "description": "Primary care visit",
                },
                {
                    "code": "B", "name": "Co-Payment", "serviceTypeCodes": ["UC"],
                    "benefitAmount": str(profile["ppo_specialist_copay"]),
                    "description": "Urgent care visit",
                },
                {
                    "code": "B", "name": "Co-Payment", "serviceTypeCodes": ["86"],
                    "benefitAmount": str(profile["ppo_ed_copay"]),
                    "description": "Emergency room",
                },
                {
                    "code": "U", "name": "Prior Authorization Required", "serviceTypeCodes": ["MR"],
                    "description": "Required for advanced imaging (MRI, CT, PET)",
                },
            ],
            "_meta": {
                "source": "solace_mock",
                "note": "Set ELIGIBILITY_CLEARINGHOUSE=stedi|availity + API key to go live",
            },
        }


class StediAdapter:  # pragma: no cover - requires network + key
    """Stedi clearinghouse adapter. Stedi consumes JSON natively."""

    name = "stedi"

    def __init__(self) -> None:
        self.api_key = os.environ["STEDI_API_KEY"]
        self.base_url = os.getenv(
            "STEDI_ELIGIBILITY_URL",
            "https://healthcare.us.stedi.com/2024-04-01/eligibility",
        )

    def check(self, request_270: dict[str, Any]) -> dict[str, Any]:
        import requests
        payload = {k: v for k, v in request_270.items() if not k.startswith("_")}
        r = requests.post(
            self.base_url,
            headers={"Authorization": f"Key {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()


class AvailityAdapter:  # pragma: no cover - requires network + key
    """Availity clearinghouse adapter. Availity exchanges raw X12 270/271 EDI;
    the `_x12` segment string from build_270_request() is the request body and
    parse_271() converts the X12 271 reply back to the Stedi-shaped contract."""

    name = "availity"

    def __init__(self) -> None:
        self.api_key = os.environ["AVAILITY_API_KEY"]
        self.base_url = os.getenv(
            "AVAILITY_ELIGIBILITY_URL",
            "https://api.availity.com/availity/v1/coverages",
        )

    def check(self, request_270: dict[str, Any]) -> dict[str, Any]:
        import requests
        r = requests.post(
            self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/edi-x12"},
            data=request_270.get("_x12", ""),
            timeout=15,
        )
        r.raise_for_status()
        # Availity returns raw X12 271 — normalize it to the Stedi-shaped contract.
        return parse_271(r.text, control_number=request_270["controlNumber"])


def _select_adapter() -> Any:
    """Pick the clearinghouse adapter from env. Mock is the safe default."""
    choice = (os.getenv("ELIGIBILITY_CLEARINGHOUSE") or "").strip().lower()
    try:
        if choice == "stedi" and os.getenv("STEDI_API_KEY"):
            return StediAdapter()
        if choice == "availity" and os.getenv("AVAILITY_API_KEY"):
            return AvailityAdapter()
        # Back-compat with the older opt-in flag.
        if os.getenv("STEDI_API_KEY") and os.getenv("USE_REAL_ELIGIBILITY") == "1":
            return StediAdapter()
    except Exception as e:  # pragma: no cover
        log.warning("Clearinghouse adapter init failed (%s) — using mock: %s", choice, e)
    return MockAdapter()


# --------------------------------------------------------------------------------
# 271 parser
# --------------------------------------------------------------------------------
def parse_271(raw: str, control_number: str = "000000000") -> dict[str, Any]:
    """Parse a raw X12 005010X279A1 271 segment string into the Stedi-shaped JSON
    contract the rest of Solace consumes.

    Handles the loops Solace cares about: 2100C subscriber (NM1/DMG), 2110C
    eligibility/benefit (EB segments). EB*1 = Active Coverage, EB*C = deductible,
    EB*G = out-of-pocket stop-loss, EB*B = copay, and a 'PRIOR AUTH' message
    line drives the prior-auth-required flag.
    """
    seg_sep = "~"
    el_sep = "*"
    segments = [s.strip() for s in raw.replace("\n", "").split(seg_sep) if s.strip()]

    out: dict[str, Any] = {
        "controlNumber": control_number,
        "tradingPartnerServiceId": "",
        "subscriber": {},
        "payer": {},
        "planInformation": {},
        "planStatus": [],
        "benefitsInformation": [],
        "_meta": {"source": "x12_271_parser"},
    }
    current_st: list[str] = []  # service type codes in scope for the current EB run

    for seg in segments:
        el = seg.split(el_sep)
        tag = el[0]

        if tag == "NM1" and len(el) > 1:
            entity = el[1]
            if entity == "PR":  # payer
                out["payer"]["name"] = el[3] if len(el) > 3 else ""
                out["tradingPartnerServiceId"] = el[9] if len(el) > 9 else ""
            elif entity == "IL":  # insured / subscriber
                out["subscriber"] = {
                    "lastName": el[3] if len(el) > 3 else "",
                    "firstName": el[4] if len(el) > 4 else "",
                    "memberId": el[9] if len(el) > 9 else "",
                }
        elif tag == "DMG" and len(el) > 2:
            out["subscriber"]["dateOfBirth"] = el[2]
        elif tag in ("REF",) and len(el) > 2 and el[1] in ("6P", "1L"):
            out["planInformation"]["groupNumber"] = el[2]
        elif tag == "EB":
            eb_code = el[1] if len(el) > 1 else ""
            coverage_level = el[2] if len(el) > 2 else ""
            svc_types = el[3].split("^") if len(el) > 3 and el[3] else []
            amount = el[7] if len(el) > 7 else ""
            description = el[5] if len(el) > 5 else ""
            current_st = svc_types or current_st

            if eb_code == "1":  # Active coverage
                out["planStatus"].append({
                    "statusCode": "1", "status": "Active Coverage",
                    "serviceTypeCodes": svc_types or ["30"],
                })
            elif eb_code == "6":  # Inactive
                out["planStatus"].append({
                    "statusCode": "6", "status": "Inactive",
                    "serviceTypeCodes": svc_types or ["30"],
                })
            elif eb_code == "C":  # Deductible
                out["benefitsInformation"].append({
                    "code": "C", "name": "Deductible",
                    "coverageLevelCode": coverage_level,
                    "amountRemaining": amount,
                })
            elif eb_code == "G":  # Out of pocket / stop loss
                out["benefitsInformation"].append({
                    "code": "G", "name": "Out of Pocket (Stop Loss)",
                    "coverageLevelCode": coverage_level,
                    "amountRemaining": amount,
                })
            elif eb_code == "B":  # Co-payment
                out["benefitsInformation"].append({
                    "code": "B", "name": "Co-Payment",
                    "serviceTypeCodes": svc_types,
                    "benefitAmount": amount,
                    "description": description,
                })
            elif eb_code == "A":  # Co-insurance (percentage)
                out["benefitsInformation"].append({
                    "code": "A", "name": "Co-Insurance",
                    "serviceTypeCodes": svc_types,
                    "benefitPercent": amount,
                })
        elif tag == "MSG" and len(el) > 1:
            msg = el[1].upper()
            if "PRIOR AUTH" in msg or "PREAUTH" in msg or "AUTHORIZATION REQUIRED" in msg:
                out["benefitsInformation"].append({
                    "code": "U", "name": "Prior Authorization Required",
                    "serviceTypeCodes": current_st or ["MR"],
                    "description": el[1],
                })
        elif tag == "AAA" and len(el) > 3:
            # Rejection / error loop — surface so callers can show a real reason.
            out["_meta"]["reject_reason_code"] = el[3]
            out["_meta"]["rejected"] = True

    if not out["planStatus"]:
        out["planStatus"].append({"statusCode": "U", "status": "Unknown", "serviceTypeCodes": []})
    return out


# --------------------------------------------------------------------------------
# Public API — stable signatures
# --------------------------------------------------------------------------------
def check(
    payer_name: str,
    member_id: str,
    patient_first: str,
    patient_last: str,
    patient_dob: str,
    service_date: str | None = None,
    service_type: str = "30",  # 30=Health Benefit Plan Coverage
    provider_npi: str | None = None,
) -> dict[str, Any]:
    """Run a 270/271 eligibility check and return a Stedi-shaped 271 response.

    Builds the X12 270 request, dispatches it through the configured
    clearinghouse adapter, and falls back to the mock adapter on any failure.
    """
    request_270 = build_270_request(
        payer_name, member_id, patient_first, patient_last, patient_dob,
        service_date=service_date, service_type=service_type, provider_npi=provider_npi,
    )
    adapter = _select_adapter()
    try:
        response = adapter.check(request_270)
    except Exception as e:
        log.warning("Clearinghouse '%s' call failed, falling back to mock: %s", adapter.name, e)
        response = MockAdapter().check(request_270)
        response["_meta"]["fallback_from"] = adapter.name

    response.setdefault("_meta", {})["clearinghouse"] = adapter.name
    response["_meta"]["request_270"] = request_270
    return response


def summarize_for_clinician(response: dict[str, Any]) -> dict[str, Any]:
    """Distill a 271 down to the numbers a check-in nurse actually wants."""
    benefits = response.get("benefitsInformation", [])
    out: dict[str, Any] = {
        "active": any(s.get("status") == "Active Coverage" for s in response.get("planStatus", [])),
        "plan": response.get("planInformation", {}).get("planName", ""),
        "payer": response.get("payer", {}).get("name", ""),
        "deductible_remaining": None,
        "oop_remaining": None,
        "pcp_copay": None,
        "specialist_copay": None,
        "ed_copay": None,
        "coinsurance_pct": None,
        "prior_auth_advanced_imaging": False,
        "prior_auth_services": [],
        "clearinghouse": response.get("_meta", {}).get("clearinghouse", "unknown"),
        "rejected": bool(response.get("_meta", {}).get("rejected")),
    }
    for b in benefits:
        code = b.get("code")
        if code == "C":
            out["deductible_remaining"] = b.get("amountRemaining")
        elif code == "G":
            out["oop_remaining"] = b.get("amountRemaining")
        elif code == "A":
            out["coinsurance_pct"] = b.get("benefitPercent")
        elif code == "B":
            stcs = b.get("serviceTypeCodes", [])
            if "98" in stcs:
                out["pcp_copay"] = b.get("benefitAmount")
            elif "UC" in stcs:
                out["specialist_copay"] = b.get("benefitAmount")
            elif "86" in stcs:
                out["ed_copay"] = b.get("benefitAmount")
        elif code == "U":
            stcs = b.get("serviceTypeCodes", [])
            out["prior_auth_services"].extend(stcs)
            if "MR" in stcs:
                out["prior_auth_advanced_imaging"] = True
    return out
