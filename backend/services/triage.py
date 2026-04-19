"""Triage service — thin wrapper around the Triage.ai engine.

Solace's self-serve intake doesn't collect vitals, so we pass clinically-normal
defaults and let the engine's chief-complaint keyword matcher + age + comorbidity
modifiers carry the weight. When the trained LightGBM/XGBoost/CatBoost pickles
are exported from the training notebook, the engine can switch to MODEL_MODE='trained'.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from services.triage_engine import predict_triage

log = logging.getLogger(__name__)

# Clinically-normal vitals — used when the patient hasn't provided them (most self-serve cases).
_DEFAULT_VITALS = {
    "heart_rate": 80.0,
    "sbp": 120.0,
    "dbp": 80.0,
    "o2_sat": 98.0,
    "resp_rate": 16.0,
    "temperature": 98.6,
    "gcs": 15,
}


@dataclass
class TriagePrediction:
    esi_level: int
    confidence: float
    confidence_band: str
    shap_values: dict[str, float]
    source: str
    # Extra clinical context the engine produces (surface on dashboard).
    clinical_flags: list[str]
    composites: dict[str, float]
    recommendation: str
    probabilities: list[float]


def predict(
    transcript: str,
    photo_analysis: dict[str, Any] | None = None,
    medical_info: dict[str, Any] | None = None,
) -> TriagePrediction:
    """Run the Triage.ai engine on the patient's transcript + known medical info."""
    patient_payload = _build_payload(transcript, photo_analysis, medical_info)
    result = predict_triage(patient_payload)

    confidence = float(result["confidence"])
    conformal: list[int] = result["conformal_set"]
    confidence_band = _format_confidence_band(conformal, result["esi_level"], confidence)

    # Convert the engine's risk factors into a SHAP-like {name: importance} dict
    # so the clinician dashboard can render the existing horizontal-bar chart.
    shap_values: dict[str, float] = {}
    for rf in result["risk_factors"]:
        name = str(rf.get("name", "")).strip()
        importance = float(rf.get("importance", 0.0))
        if name:
            shap_values[name] = importance

    return TriagePrediction(
        esi_level=int(result["esi_level"]),
        confidence=confidence,
        confidence_band=confidence_band,
        shap_values=shap_values,
        source="triageist_simulation",
        clinical_flags=list(result.get("clinical_flags", [])),
        composites=dict(result.get("composites", {})),
        recommendation=str(result.get("recommendation", "")),
        probabilities=list(result.get("probabilities", [])),
    )


def _build_payload(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    medical_info: dict[str, Any] | None,
) -> dict[str, Any]:
    age = int((medical_info or {}).get("age") or 35)
    sex_raw = (medical_info or {}).get("sex")
    sex = {"male": "Male", "female": "Female", "other": "Other"}.get(
        str(sex_raw).lower() if sex_raw else "", "Other"
    )

    conditions = (medical_info or {}).get("conditions") or []
    n_comorbidities = sum(1 for c in conditions if str(c).lower() != "none")

    chief_complaint = (transcript or "").strip()
    if photo_analysis and photo_analysis.get("description"):
        # Append a short photo signal so the keyword matcher can see it.
        chief_complaint = f"{chief_complaint}. {photo_analysis['description']}"

    payload = {
        **_DEFAULT_VITALS,
        "age": age,
        "sex": sex,
        "chief_complaint": chief_complaint or "unspecified",
        "arrival_mode": "Walk-in",
        "n_comorbidities": n_comorbidities,
    }
    return payload


def _format_confidence_band(conformal: list[int], predicted: int, confidence: float) -> str:
    if len(conformal) == 1:
        return f"ESI {predicted} (confidence {int(round(confidence * 100))}%)"
    lo, hi = conformal[0], conformal[-1]
    return f"ESI {lo}-{hi} (confidence {int(round(confidence * 100))}% at ESI {predicted})"
