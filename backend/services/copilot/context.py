"""Deterministic-zone context: load the patient and parse the chart.

This module lives INSIDE the PHI boundary. It holds the real patient values.
Nothing here is ever sent to the model directly — the executor reads from it and
down-projects to coded outputs + slot refs before anything crosses to the model.
"""
from __future__ import annotations

import json
from typing import Any

from db import storage


def parse_medical_info(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [p.strip() for p in value.replace("\n", ",").split(",") if p.strip()]
    return []


def build_chart(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Load the Solace patient + parse the intake chart into a working context.

    The linked FHIR record is fetched lazily by EHR primitives, so a question
    that needs no history costs zero external EHR calls.
    """
    patient = storage.get_patient(patient_id) or {}
    info = parse_medical_info(patient.get("medical_info"))
    chart = {
        "name": patient.get("name") or info.get("name") or "",
        "age": info.get("age") or patient.get("patient_age"),
        "sex": info.get("sex") or info.get("gender") or "",
        "chief_complaint": patient.get("chief_complaint") or patient.get("complaint") or "",
        "conditions": as_list(info.get("conditions") or info.get("medical_conditions") or info.get("history")),
        "medications": as_list(info.get("medications") or info.get("meds")),
        "allergies": as_list(info.get("allergies")),
        "transcript": patient.get("transcript") or "",
        "vitals": patient.get("vitals") or info.get("vitals") or {},
        "esi_level": patient.get("esi_level") or patient.get("triage_level"),
    }
    return {
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "patient": patient,
        "chart": chart,
        "ehr_record": None,  # populated lazily by EHR primitives
    }
