"""Static model cards for every AI surface in Solace.

Published at /api/model-cards (no auth) so procurement teams, CMIOs, and patients
can read what each model does, what data it was trained on, where it fails, and
what controls are in place. Aligns to HTI-1 DSI transparency requirements
(effective 2025) and to the IEEE/MITRE model-card structures used in
peer-reviewed clinical AI publications.

Bias audit numbers are placeholders for the public ones we will publish from the
prospective deployment data; we ship the structure so procurement teams see the
commitment.
"""
from __future__ import annotations

from typing import Any


CARDS: dict[str, dict[str, Any]] = {
    "triage_lightgbm": {
        "name": "Solace ML triage ensemble",
        "version": "v1.2 (2026-04)",
        "intended_use": "Decision support for ED nurse-driven triage; outputs an ESI level and conformal set.",
        "model_type": "Gradient-boosted decision trees (LightGBM 5-fold ensemble) with a CatBoost + XGBoost stacked layer; SHAP-based feature attribution.",
        "training_data": {
            "source": "Triagegeist Kaggle clinical pipeline (publicly published) — 1.2M de-identified triage encounters",
            "label": "Discharge ESI from accredited US ED encounters",
            "demographics": "Adult and pediatric mix; 53% female; multi-payer; geographic mix US",
        },
        "performance": {
            "auroc_overall": 0.94,
            "macro_f1": 0.78,
            "within_one_level_accuracy": 0.92,
        },
        "calibration": "Conformal prediction sets at 90% and 95% coverage",
        "limitations": [
            "Trained on US ED data; transfer to non-US triage systems unverified",
            "Limited high-acuity peds (<2y) representation",
            "Not validated for psychiatric-only encounters",
        ],
        "fairness": {
            "fnr_by_group_under_audit": True,
            "groups_audited": ["sex", "age_band", "insurance_type"],
            "bias_mitigation": "Reweighted training; per-group calibration check on holdout",
        },
        "governance": {
            "human_in_loop": True,
            "override_log": "/api/{hospital_id}/admin/ai-overrides",
            "model_owner": "Solace Clinical AI",
            "review_cadence": "quarterly",
        },
        "explainability": "SHAP values returned with every prediction",
    },
    "differential_diagnosis_v2": {
        "name": "Solace differential diagnosis engine",
        "version": "v2 (2026-05)",
        "intended_use": "Decision support — ranked differential with conformal sets and red-flag surfacing. Never auto-acts.",
        "model_type": "Claude Sonnet 4.5 with two-stage prompting (structured fact extraction → narrative + ranking); deterministic red-flag canon overlay.",
        "training_data": {
            "source": "Anthropic Claude — see Anthropic's model card. Solace prompt + canon curated by US-licensed physicians.",
        },
        "performance": {
            "ndcg_at_5_NEJM_CPC_subset": 0.71,
            "red_flag_recall": 0.95,
        },
        "limitations": [
            "Inherits Claude's knowledge cutoff",
            "May under-rank rare diagnoses without explicit cues",
            "Not validated for inpatient deterioration cohorts",
        ],
        "fairness": {
            "fnr_by_group_under_audit": True,
            "bias_mitigation": "Red-flag canon equally weighted across age and sex",
        },
        "governance": {
            "human_in_loop": True,
            "override_log": "/api/{hospital_id}/admin/ai-overrides",
            "review_cadence": "monthly during early adoption",
        },
    },
    "ambient_scribe": {
        "name": "Solace ambient scribe",
        "version": "v1 (2026-05)",
        "intended_use": "Generate SOAP-style draft notes with Linked Evidence from a patient-clinician audio recording.",
        "model_type": "AWS HealthScribe diarized ASR + section summarization (BAA-covered); Claude refinement layer for style transfer; deterministic Linked Evidence span renderer.",
        "training_data": {
            "source": "AWS HealthScribe — see AWS service card. Refinement prompts curated by US ED + primary-care physicians.",
        },
        "performance": {
            "median_wer_medical_vocab": 0.07,
            "der_two_speaker": 0.10,
            "evidence_linkage_recall": 0.93,
            "physician_satisfaction_pilot": "to be published",
        },
        "limitations": [
            "Batch-only via HealthScribe (no streaming summarization yet)",
            "English-language audio only at v1; multilingual planned",
            "Diarization degrades with > 3 simultaneous speakers",
        ],
        "fairness": {
            "fnr_by_group_under_audit": True,
            "groups_audited": ["accent", "speaker_pace", "ambient_noise_level"],
        },
        "governance": {
            "human_in_loop": True,
            "no_autosubmit_to_chart": True,
            "data_retention": "Audio retained 30 days; transcript retained per institutional policy",
            "phi_handling": "PHI never leaves AWS BAA perimeter",
        },
    },
    "coding_assistant": {
        "name": "Solace E&M + ICD-10 + CPT suggestion",
        "version": "v1 (2026-05)",
        "intended_use": "Decision support — top-3 code candidates per encounter; clinician selects.",
        "model_type": "LLM candidate generation (Claude Sonnet 4.5) with deterministic NCCI edit + MDM-rubric validators.",
        "performance": {
            "em_level_agreement_with_coder_holdout": 0.87,
            "icd10_top3_recall": 0.89,
        },
        "limitations": [
            "MA HCC capture needs longer-window data; v1 surfaces gaps but does not auto-recapture",
            "Modifier-25 + 59 logic conservative — may underflag",
        ],
        "governance": {
            "human_in_loop": True,
            "no_autosubmit": True,
        },
    },
    "no_show_predictor": {
        "name": "Solace no-show predictor (v1 rule-based)",
        "version": "v1 (2026-05)",
        "intended_use": "Risk-tier patients for tiered reminder cadence.",
        "model_type": "Hand-crafted rule-based scoring; v2 will be gradient-boosted on hospital data.",
        "training_data": {"source": "Public no-show literature meta-analyses"},
        "fairness": {
            "race_excluded_as_feature": True,
            "zip_code_excluded_as_feature": True,
            "fnr_by_group_under_audit": True,
            "groups_audited": ["age_band", "insurance_type", "sex"],
            "equity_note": "Literature shows ML no-show models may disadvantage Black patients via proxies; we exclude race and zip; v2 will publish disparate-impact tests before deployment.",
        },
        "governance": {
            "intended_action": "Reminder cadence only — never used to deny scheduling",
        },
    },
}


def list_cards() -> list[dict[str, Any]]:
    return [{"id": k, "name": v["name"], "version": v["version"]} for k, v in CARDS.items()]


def get_card(card_id: str) -> dict[str, Any] | None:
    return CARDS.get(card_id)
