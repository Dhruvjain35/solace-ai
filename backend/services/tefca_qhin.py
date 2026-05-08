"""TEFCA QHIN connector — patient record query across the national network.

TEFCA (Trusted Exchange Framework and Common Agreement) is the federal
agreement that connects health systems via Qualified Health Information
Networks (QHINs). As of 2026 there are 7 designated QHINs (Epic Nexus,
eHealth Exchange, Health Gorilla, MedAllies, KONZA, CommonWell, Carequality).

Solace uses the QHIN to query for outside chart data when a patient checks
in. Read-only.

This module is a stub with the right shape (Individual Access Services flow
for patient consent + IHE XCA/XCPD-style query). It returns synthetic data in
dev so the UI can be demoed; production needs a designated participant
agreement under one QHIN.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


SYNTHETIC_RECORDS = {
    "JANE_DOE_19850321": {
        "patient": {"name": "Jane Doe", "dob": "1985-03-21", "sex": "F"},
        "outside_facilities": [
            {"name": "Bay Health System", "city": "Oakland, CA", "qhin": "eHealth Exchange"},
            {"name": "Sutter Health", "city": "Sacramento, CA", "qhin": "Carequality"},
        ],
        "conditions": [
            {"icd10": "E11.9", "display": "T2DM", "first_documented": "2022-04-12"},
            {"icd10": "I10", "display": "Essential hypertension", "first_documented": "2020-09-03"},
        ],
        "medications": [
            {"name": "metformin 1000 mg PO BID", "last_filled": "2026-04-30"},
            {"name": "lisinopril 10 mg PO daily", "last_filled": "2026-04-30"},
        ],
        "allergies": [{"substance": "Penicillin", "reaction": "rash", "severity": "moderate"}],
        "recent_visits": [
            {"date": "2025-12-04", "type": "outpatient", "facility": "Bay Health System", "reason": "annual physical"},
            {"date": "2024-08-15", "type": "ED", "facility": "Sutter Health", "reason": "left flank pain → urolithiasis"},
        ],
        "immunizations": [
            {"name": "Influenza", "date": "2025-10-04"},
            {"name": "COVID-19 booster", "date": "2025-09-21"},
            {"name": "Tdap", "date": "2024-04-02"},
        ],
    },
}


def _key(name: str, dob: str) -> str:
    return f"{name.upper().replace(' ', '_')}_{(dob or '').replace('-', '')}"


def query(*, patient_name: str, patient_dob: str, consent_attestation: bool = False) -> dict[str, Any]:
    """Patient Discovery + Document Query across QHINs. Synthetic in dev."""
    if not consent_attestation:
        return {"error": "patient consent attestation required for IAS flow"}
    use_real = os.getenv("USE_REAL_TEFCA") == "1"
    if use_real:  # pragma: no cover (no live QHIN endpoint here)
        try:
            return _real_query(patient_name, patient_dob)
        except Exception as e:
            log.warning("Real TEFCA query failed: %s", e)
    record = SYNTHETIC_RECORDS.get(_key(patient_name, patient_dob))
    if not record:
        return {"found": False, "reason": "no_matching_record_in_synthetic"}
    return {
        "found": True,
        "synthetic": True,
        "qhin_pathway": "Individual Access Services (IAS) demonstration",
        "record": record,
    }


def _real_query(name: str, dob: str) -> dict[str, Any]:  # pragma: no cover
    """Hook for production — replace with QHIN-specific SDK calls."""
    raise NotImplementedError("Set USE_REAL_TEFCA=1 only after QHIN designated participant agreement")
