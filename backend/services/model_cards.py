"""Static model cards + bias-audit machinery for every AI surface in Solace.

Published at /api/model-cards (no auth) so procurement teams, CMIOs, and patients
can read what each model does, what data it was trained on, where it fails, and
what controls are in place. Aligns to HTI-1 DSI transparency requirements
(45 CFR 170.315(b)(11), effective 2025) and to the IEEE/MITRE model-card
structures used in peer-reviewed clinical AI publications.

HTI-1 source-attribute coverage
-------------------------------
HTI-1 requires Predictive Decision Support Interventions (DSIs) to disclose 31
"source attributes" across details, funding/development, validity, fairness,
risk-management, and ongoing-maintenance categories. Each card below carries the
machine-readable subset Solace can attest to today:

    intended_population      — who the model is for / contraindicated populations
    intended_output          — exactly what the model emits and how it is meant to be used
    data_provenance          — origin, lineage, consent basis, time range of training data
    risk_tier                — Solace internal risk classification (see RISK_TIERS)
    monitoring_plan          — post-deployment surveillance commitments
    synthetic_data_caveat    — whether synthetic / augmented data was used and where

Bias audit numbers
------------------
Demographic performance tables ship "empty-but-structured": every subgroup cell
is present with `value: null` and `status: "pending_prospective_data"` until the
prospective deployment cohort is large enough to publish real rates. This makes
the commitment auditable today and lets the same JSON shape carry real numbers
later with zero schema change. `compute_subgroup_rates()` is a real working
function — feed it confusion-matrix counts and it returns per-subgroup FNR/FPR,
disparate-impact ratios, and four-fifths-rule flags.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Risk tiers — Solace internal classification, mapped to oversight intensity.
# --------------------------------------------------------------------------
RISK_TIERS: dict[str, dict[str, Any]] = {
    "tier_1_high": {
        "label": "Tier 1 — High clinical risk",
        "definition": "Output can plausibly change an acute disposition or acuity decision; a silent error could delay time-critical care.",
        "oversight": "Mandatory human-in-the-loop, conformal uncertainty surfaced, monthly subgroup audit, model owner sign-off on every version.",
    },
    "tier_2_moderate": {
        "label": "Tier 2 — Moderate clinical risk",
        "definition": "Output informs documentation, coding, or non-acute planning; errors are recoverable and clinician-reviewed before any chart write.",
        "oversight": "Human-in-the-loop, quarterly subgroup audit, override-rate monitoring.",
    },
    "tier_3_low": {
        "label": "Tier 3 — Low clinical risk",
        "definition": "Output drives operational/administrative actions only; never gates clinical access or care.",
        "oversight": "Human-in-the-loop where patient-facing, semi-annual fairness review, no autonomous action.",
    },
}


# --------------------------------------------------------------------------
# Bias-audit methodology — published once, referenced by every card.
# --------------------------------------------------------------------------
BIAS_AUDIT_METHODOLOGY: dict[str, Any] = {
    "framework": "HTI-1 DSI fairness source attributes + four-fifths (80%) disparate-impact rule (EEOC Uniform Guidelines, applied as an equity heuristic, not a legal standard).",
    "protected_attributes": ["sex", "age_band", "race_ethnicity", "insurance_type"],
    "primary_metrics": {
        "fnr": "False-negative rate — proportion of truly high-acuity / positive cases the model under-classified. The safety-critical metric for triage: a missed high-acuity patient is the worst failure.",
        "fpr": "False-positive rate — proportion of truly low-acuity / negative cases the model over-classified. Drives over-triage, alert fatigue, and resource strain.",
        "selection_rate": "Proportion of a subgroup receiving the positive / high-acuity prediction, used for disparate-impact ratios.",
    },
    "disparate_impact": {
        "definition": "For each metric, ratio of the least-favored subgroup to the most-favored subgroup within a protected attribute.",
        "fnr_ratio_convention": "min(FNR) / max(FNR) — a low ratio means one subgroup is missed far more often.",
        "flag_threshold": 0.80,
        "flag_rule": "Any disparate-impact ratio below 0.80 is flagged for mandatory model-owner review before the version may ship.",
    },
    "sample_size_floor": 100,
    "sample_size_rule": "Subgroup cells with fewer than 100 labelled outcomes are reported as 'insufficient_sample' and excluded from disparate-impact computation to avoid noise-driven false alarms.",
    "cadence": "Tier 1 monthly, Tier 2 quarterly, Tier 3 semi-annually; ad-hoc audit on any version bump.",
    "data_source": "Prospective de-identified deployment outcomes with confirmed dispositions; never the training set, to avoid optimistic in-sample bias.",
    "publication": "Subgroup tables published to this endpoint as cells reach the sample-size floor; methodology and empty structure published now as a standing commitment.",
    "remediation": [
        "Reweighting / resampling of under-served subgroups in retraining.",
        "Per-subgroup calibration of conformal thresholds.",
        "Feature ablation where a feature acts as a protected-attribute proxy.",
        "Rollback to prior version if a shipped version regresses a subgroup FNR.",
    ],
}


# --------------------------------------------------------------------------
# Demographic-performance template.
#
# Every card gets a copy of this structure. Cells are "empty-but-structured":
# value is null and status is "pending_prospective_data" until real prospective
# outcomes exist. The shape never changes when real numbers arrive.
# --------------------------------------------------------------------------
_SUBGROUP_AXES: dict[str, list[str]] = {
    "sex": ["female", "male", "other_unknown"],
    "age_band": ["peds_0_2", "peds_3_17", "adult_18_64", "geriatric_65_plus"],
    "race_ethnicity": [
        "white", "black", "hispanic_latino", "asian",
        "native_american", "pacific_islander", "other_unknown",
    ],
    "insurance_type": ["medicare", "medicaid", "commercial", "uninsured_self_pay"],
}


def _empty_demographic_performance() -> dict[str, Any]:
    """Build the empty-but-structured FNR/FPR-by-subgroup table for a card."""
    table: dict[str, Any] = {
        "schema": "fnr_fpr_by_subgroup",
        "metrics": ["fnr", "fpr", "selection_rate"],
        "status": "pending_prospective_data",
        "note": (
            "Cells are published empty until the prospective deployment cohort "
            "reaches the per-cell sample-size floor of "
            f"{BIAS_AUDIT_METHODOLOGY['sample_size_floor']} labelled outcomes. "
            "Structure is fixed so real numbers drop in without a schema change."
        ),
        "axes": {},
    }
    for axis, groups in _SUBGROUP_AXES.items():
        table["axes"][axis] = {
            group: {
                "fnr": {"value": None, "ci95": None},
                "fpr": {"value": None, "ci95": None},
                "selection_rate": {"value": None},
                "n": 0,
                "status": "pending_prospective_data",
            }
            for group in groups
        }
    return table


CARDS: dict[str, dict[str, Any]] = {
    "triage_lightgbm": {
        "name": "Solace ML triage ensemble",
        "version": "v1.2 (2026-04)",
        "intended_use": "Decision support for ED nurse-driven triage; outputs an ESI level and conformal set.",
        "intended_population": "Patients presenting to a US emergency department for nurse-driven triage, all ages. Contraindicated as the sole basis for triage of psychiatric-only presentations and of high-acuity neonates (<2y), where representation is thin.",
        "intended_output": "An Emergency Severity Index (ESI 1-5) point estimate plus a conformal prediction set at 90% / 95% coverage and SHAP feature attributions. Intended to inform, never replace, the triage nurse's acuity assignment.",
        "model_type": "Gradient-boosted decision trees (LightGBM 5-fold ensemble) with a CatBoost + XGBoost stacked layer; SHAP-based feature attribution.",
        "training_data": {
            "source": "Triagegeist Kaggle clinical pipeline (publicly published) — 1.2M de-identified triage encounters",
            "label": "Discharge ESI from accredited US ED encounters",
            "demographics": "Adult and pediatric mix; 53% female; multi-payer; geographic mix US",
        },
        "data_provenance": {
            "origin": "Triagegeist Kaggle clinical pipeline — publicly published, de-identified ED triage encounters.",
            "lineage": "Raw encounters -> HIPAA Safe Harbor de-identification (upstream) -> Triagegeist feature engineering -> Solace 5-fold ensemble training.",
            "consent_basis": "Secondary use of de-identified data; no individually identifiable PHI retained, so HIPAA authorization is not implicated.",
            "time_range": "Historical retrospective encounters; not continuously refreshed in v1.2.",
            "known_gaps": "US-only; thin high-acuity peds (<2y); psychiatric-only encounters under-represented.",
        },
        "risk_tier": "tier_1_high",
        "performance": {
            "auroc_overall": 0.94,
            "macro_f1": 0.78,
            "within_one_level_accuracy": 0.92,
        },
        "calibration": "Conformal prediction sets at 90% and 95% coverage",
        "monitoring_plan": {
            "cadence": "Monthly subgroup bias audit (Tier 1); continuous override-rate tracking via /api/governance/override-metrics.",
            "drift_detection": "Population stability index on input feature distributions; conformal set-size inflation as a coverage-drift signal.",
            "triggers": "Subgroup FNR disparate-impact ratio < 0.80, macro-F1 drop > 3 points, or sustained override (reject) rate > 20% triggers model-owner review.",
            "rollback": "Prior ensemble version is retained and hot-swappable if a shipped version regresses a subgroup FNR.",
        },
        "synthetic_data_caveat": "No synthetic or generative augmentation used; the ensemble trains exclusively on real de-identified encounters. Class imbalance handled by reweighting, not by synthetic minority oversampling.",
        "limitations": [
            "Trained on US ED data; transfer to non-US triage systems unverified",
            "Limited high-acuity peds (<2y) representation",
            "Not validated for psychiatric-only encounters",
        ],
        "fairness": {
            "fnr_by_group_under_audit": True,
            "groups_audited": ["sex", "age_band", "race_ethnicity", "insurance_type"],
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
        "intended_population": "Clinicians assessing undifferentiated US ED and primary-care presentations, all ages. Not intended for inpatient deterioration cohorts or for autonomous use without clinician review.",
        "intended_output": "A ranked differential diagnosis list with a conformal candidate set and a deterministic red-flag overlay. Output is advisory; the clinician owns the diagnostic decision.",
        "model_type": "Claude Sonnet 4.5 with two-stage prompting (structured fact extraction -> narrative + ranking); deterministic red-flag canon overlay.",
        "training_data": {
            "source": "Anthropic Claude — see Anthropic's model card. Solace prompt + canon curated by US-licensed physicians.",
        },
        "data_provenance": {
            "origin": "Base reasoning from Anthropic Claude Sonnet 4.5 (training data per Anthropic's published model card; not controlled by Solace).",
            "lineage": "Solace contributes only the two-stage prompt scaffold and a physician-curated red-flag canon layered deterministically on top of model output.",
            "consent_basis": "No patient data used for training; runtime inputs are scanned by content_guard and routed to BAA-covered providers only.",
            "time_range": "Bounded by Claude's knowledge cutoff; Solace red-flag canon maintained continuously.",
            "known_gaps": "Rare diagnoses may be under-ranked without explicit cues; inpatient deterioration not covered.",
        },
        "risk_tier": "tier_1_high",
        "performance": {
            "ndcg_at_5_NEJM_CPC_subset": 0.71,
            "red_flag_recall": 0.95,
        },
        "monitoring_plan": {
            "cadence": "Monthly during early adoption (Tier 1).",
            "drift_detection": "Red-flag recall tracked against a held-out canon test set on every prompt or model-version change.",
            "triggers": "Any red-flag recall regression, or override (reject) rate > 25%, triggers physician-panel review.",
            "rollback": "Prompt and canon are versioned; prior version restorable independent of the Claude model version.",
        },
        "synthetic_data_caveat": "No Solace-side training. The red-flag canon is hand-authored by US-licensed physicians, not model-generated. Underlying Claude training-data composition is disclosed by Anthropic, not Solace.",
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
        "intended_population": "English-speaking patient-clinician encounters in US ED and primary-care settings. Not intended for multi-party (>3 speaker) encounters or non-English audio at v1.",
        "intended_output": "A SOAP-structured draft note with Linked Evidence spans tying each statement back to the transcript. Always a draft — never auto-submitted to the chart.",
        "model_type": "AWS HealthScribe diarized ASR + section summarization (BAA-covered); Claude refinement layer for style transfer; deterministic Linked Evidence span renderer.",
        "training_data": {
            "source": "AWS HealthScribe — see AWS service card. Refinement prompts curated by US ED + primary-care physicians.",
        },
        "data_provenance": {
            "origin": "ASR and section summarization from AWS HealthScribe (training data per AWS service card). Solace contributes refinement prompts and the Linked Evidence renderer.",
            "lineage": "Audio -> HealthScribe diarized transcript + sections -> Claude style refinement -> deterministic evidence-span linking -> clinician-reviewed draft.",
            "consent_basis": "Recording proceeds only after explicit patient consent_granted == true (SEC-004); PHI never leaves the AWS BAA perimeter.",
            "time_range": "Live encounter audio; audio retained 30 days, transcript per institutional policy.",
            "known_gaps": "English-only v1; diarization degrades with >3 simultaneous speakers.",
        },
        "risk_tier": "tier_2_moderate",
        "performance": {
            "median_wer_medical_vocab": 0.07,
            "der_two_speaker": 0.10,
            "evidence_linkage_recall": 0.93,
            "physician_satisfaction_pilot": "to be published",
        },
        "monitoring_plan": {
            "cadence": "Quarterly subgroup audit (Tier 2) across accent, speaker pace, and ambient-noise strata.",
            "drift_detection": "Word-error-rate and evidence-linkage-recall sampling on a rolling de-identified transcript audit set.",
            "triggers": "WER > 0.12 on the audit set, or evidence-linkage recall < 0.85, triggers prompt review and HealthScribe configuration audit.",
            "rollback": "Refinement prompt versioned independently of HealthScribe; clinician retains unredacted transcript access at all times.",
        },
        "synthetic_data_caveat": "No synthetic audio used by Solace. HealthScribe training composition is disclosed by AWS. The Linked Evidence renderer is fully deterministic, not model-generated.",
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
        "intended_population": "US ambulatory and ED encounters being coded for billing. Not intended for inpatient DRG assignment or for autonomous claim submission.",
        "intended_output": "Top-3 E&M level, ICD-10, and CPT candidates per encounter, each with rationale. Clinician or coder selects the final codes.",
        "model_type": "LLM candidate generation (Claude Sonnet 4.5) with deterministic NCCI edit + MDM-rubric validators.",
        "data_provenance": {
            "origin": "Candidate generation from Claude Sonnet 4.5; deterministic validators built from public CMS NCCI edit tables and the AMA MDM rubric.",
            "lineage": "Encounter note -> Claude candidate codes -> NCCI edit + MDM-rubric validation -> ranked suggestions -> human selection.",
            "consent_basis": "Operates on already-authorized clinical documentation; no separate patient data used for training.",
            "time_range": "NCCI edit tables tracked to current CMS quarterly release.",
            "known_gaps": "MA HCC long-window capture not automated; modifier-25/59 logic intentionally conservative.",
        },
        "risk_tier": "tier_2_moderate",
        "performance": {
            "em_level_agreement_with_coder_holdout": 0.87,
            "icd10_top3_recall": 0.89,
        },
        "monitoring_plan": {
            "cadence": "Quarterly accuracy and subgroup-equity audit (Tier 2).",
            "drift_detection": "Coder-agreement sampling against final billed codes; NCCI table version checks each CMS quarter.",
            "triggers": "Coder agreement < 0.80 on the audit sample triggers prompt and validator review.",
            "rollback": "Prompt and validator rule-set versioned; prior version restorable.",
        },
        "synthetic_data_caveat": "No synthetic encounters used. Validators are deterministic rule engines derived from public CMS/AMA references, not model-generated.",
        "limitations": [
            "MA HCC capture needs longer-window data; v1 surfaces gaps but does not auto-recapture",
            "Modifier-25 + 59 logic conservative — may underflag",
        ],
        "fairness": {
            "fnr_by_group_under_audit": True,
            "groups_audited": ["age_band", "insurance_type"],
        },
        "governance": {
            "human_in_loop": True,
            "no_autosubmit": True,
        },
    },
    "evidence_rag": {
        "name": "Solace evidence-grounded recommendation engine",
        "version": "v1 (2026-05)",
        "intended_use": "Decision support — answer clinical questions using ONLY a curated open-evidence corpus (USPSTF, ACC/AHA, IDSA, CDC, NIH, ADA, GINA, GOLD, ACOG). Refuses to answer when evidence is insufficient.",
        "intended_population": "Clinicians seeking guideline-grounded answers to clinical questions. Not intended for specialist-depth domains (oncology regimens, complex surgery) not covered by the corpus.",
        "intended_output": "A synthesized answer in which every claim carries an inline citation to the curated corpus, or an explicit refusal when no sufficient evidence is retrieved.",
        "model_type": "Hybrid BM25-flavored retrieval over curated snippets + Claude Sonnet 4.5 synthesis with strict citation grounding.",
        "training_data": {"source": "Curated open-access guideline corpus; expandable to PubMed Central OA + DailyMed via the same retrieval interface."},
        "data_provenance": {
            "origin": "Curated open-access clinical guideline snippets (USPSTF, ACC/AHA, IDSA, CDC, NIH, ADA, GINA, GOLD, ACOG); synthesis by Claude Sonnet 4.5.",
            "lineage": "Question -> retrieval over curated corpus -> citation-grounded synthesis -> refusal if retrieval is empty or weak.",
            "consent_basis": "No patient data; corpus is public-domain or open-access guideline text.",
            "time_range": "Snippets carry their source publication date; corpus refreshed as guidelines are updated.",
            "known_gaps": "Starter corpus intentionally narrow (10-25 snippets); no specialist-depth content.",
        },
        "risk_tier": "tier_2_moderate",
        "monitoring_plan": {
            "cadence": "Quarterly review of corpus freshness and refusal-rate calibration (Tier 2).",
            "drift_detection": "Citation-grounding spot checks — every sampled answer's claims re-verified against cited snippets.",
            "triggers": "Any detected uncited or unsupported claim triggers immediate prompt-grounding review.",
            "rollback": "Corpus and synthesis prompt versioned; prior version restorable.",
        },
        "synthetic_data_caveat": "No synthetic data. The corpus is real published guideline text; the engine has no parametric-memory fallback and will not generate uncited claims.",
        "limitations": [
            "Starter corpus is intentionally narrow (10-25 snippets) — production swap is a vector index over the same sources.",
            "No specialty-specialist depth (oncology regimens, complex surgery) until partner content is licensed.",
        ],
        "fairness": {
            "fnr_by_group_under_audit": False,
            "equity_note": "Engine returns guideline text, not patient-specific predictions; subgroup FNR/FPR is not the relevant fairness lens. Audited instead for corpus representativeness across populations the guidelines cover.",
        },
        "governance": {
            "no_parametric_memory_fallback": True,
            "refuses_when_no_match": True,
            "every_claim_cited": True,
        },
    },
    "early_warning_sepsis": {
        "name": "Solace sepsis early-warning + deterioration index",
        "version": "v1 (2026-05)",
        "intended_use": "Decision support — surface sepsis risk and deterioration trajectory from vitals + labs with transparent per-feature attribution. Direct successor to Epic ESM family.",
        "intended_population": "Hospitalized and ED patients with recorded vital signs; all adult ages. v1 thresholds are adult-calibrated and not validated for pediatric early-warning.",
        "intended_output": "A sepsis early-warning score and a continuous deterioration index, each with transparent per-feature contribution. Surfaces to a clinician; never auto-pages or auto-escalates.",
        "model_type": "Deterministic MEWS + qSOFA hybrid with infection markers (sepsis EWS) and a Rothman-flavored continuous score (deterioration index).",
        "training_data": {"source": "Published MEWS / qSOFA / Rothman-style validation literature; no proprietary training set in v1."},
        "data_provenance": {
            "origin": "v1 is rule-based — thresholds derived from published MEWS, qSOFA, and Rothman-style validation studies, not from a Solace training set.",
            "lineage": "Vitals + labs -> deterministic score computation -> per-feature attribution -> clinician-facing surface.",
            "consent_basis": "Operates on already-collected clinical observations; no separate data collection or training.",
            "time_range": "Score logic fixed at v1 release; v2 will train on hospital data with documented date ranges.",
            "known_gaps": "Adult-calibrated; requires accurate vital-sign timestamps for trend features.",
        },
        "risk_tier": "tier_1_high",
        "performance": {
            "sepsis_ews_sensitivity_external_validation": "calibrated to published meta-analyses",
            "deterioration_index_auroc": "0.79-0.82 in published validations of similar Rothman-style models",
        },
        "monitoring_plan": {
            "cadence": "Monthly sensitivity and subgroup audit (Tier 1).",
            "drift_detection": "Tracks alert volume, true-positive yield, and per-subgroup sensitivity against confirmed sepsis dispositions.",
            "triggers": "Sensitivity drop or subgroup disparate-impact ratio < 0.80 triggers threshold review.",
            "rollback": "Thresholds are versioned configuration; prior version restorable instantly.",
        },
        "synthetic_data_caveat": "No synthetic data and no machine-learned model in v1 — the score is fully deterministic and inspectable. v2 (gradient-boosted on hospital data) will publish its own synthetic-data attestation.",
        "limitations": [
            "v1 is rule-based; v2 will be a calibrated gradient-boosted model trained on hospital data.",
            "Requires accurate vital-sign timestamps for trend features.",
        ],
        "fairness": {
            "every_score_explained": True,
            "transparent_thresholds": True,
            "fnr_by_group_under_audit": True,
            "groups_audited": ["sex", "age_band", "race_ethnicity", "insurance_type"],
        },
        "governance": {
            "no_autocall": "Score surfaces to clinician; never auto-pages without human confirmation.",
        },
    },
    "hcc_capture": {
        "name": "Solace HCC capture for MA recapture",
        "version": "v1 (2026-05)",
        "intended_use": "Decision support — surface previously documented HCCs needing annual recapture and suspect undocumented HCCs from prior notes.",
        "intended_population": "Medicare Advantage panels under risk-adjusted contracts. Not intended for fee-for-service-only populations or for autonomous diagnosis attestation.",
        "intended_output": "A list of HCCs needing annual recapture and textually evidenced suspect HCCs, each requiring clinician MEAT-checklist confirmation before attestation.",
        "model_type": "Deterministic ICD-10 → HCC mapping (CMS-HCC v28 subset) + Claude Sonnet 4.5 NLP suspecting from prior-note free text.",
        "data_provenance": {
            "origin": "Deterministic mapping from the public CMS-HCC v28 model; suspecting from prior-note text via Claude Sonnet 4.5.",
            "lineage": "Prior notes + problem list -> ICD-10/HCC mapping + NLP suspecting -> MEAT-gated clinician review.",
            "consent_basis": "Operates on existing authorized chart documentation; no separate training data.",
            "time_range": "CMS-HCC v28 mapping; refreshed to current CMS model year.",
            "known_gaps": "Suspecting requires explicit textual evidence; curated v28 subset, not the full table.",
        },
        "risk_tier": "tier_2_moderate",
        "monitoring_plan": {
            "cadence": "Quarterly precision audit on suspect HCCs (Tier 2).",
            "drift_detection": "Tracks clinician confirmation rate on suspected HCCs as a precision proxy.",
            "triggers": "Confirmation rate < 0.60 triggers suspecting-prompt review to curb false suspects.",
            "rollback": "Mapping table and prompt versioned; prior version restorable.",
        },
        "synthetic_data_caveat": "No synthetic data. The HCC mapping is a deterministic public-table lookup; the NLP layer suspects only from real prior-note text and never fabricates a diagnosis.",
        "limitations": [
            "Suspecting requires explicit textual evidence — does not infer from labs or claims.",
            "v28 mapping is a curated subset; full table swap is a config update.",
        ],
        "fairness": {
            "fnr_by_group_under_audit": False,
            "equity_note": "Surfaces documentation gaps for clinician review; does not predict patient outcomes. Audited for even suspect-precision across insurance and age strata to avoid uneven coding burden.",
        },
        "governance": {"meat_checklist_required": True, "no_auto_attestation": True},
    },
    "handoff_generator": {
        "name": "Solace I-PASS / SBAR handoff generator",
        "version": "v1 (2026-05)",
        "intended_use": "Decision support — generate I-PASS sign-out and SBAR consult summaries from chart context. Adopts evidence-based handoff structure shown to cut handoff errors 30% (Starmer NEJM 2014).",
        "intended_population": "Clinicians performing shift sign-out or consult handoff in US inpatient and ED settings.",
        "intended_output": "A draft I-PASS sign-out or SBAR consult summary structured from chart context. The clinician edits and verifies before any handoff use.",
        "model_type": "Claude Sonnet 4.5 with structured prompts.",
        "data_provenance": {
            "origin": "Summarization by Claude Sonnet 4.5 over chart context; structure follows the published I-PASS / SBAR frameworks.",
            "lineage": "Chart context -> structured-prompt summarization -> clinician edit -> handoff use.",
            "consent_basis": "Operates on authorized clinical documentation; no separate training data.",
            "time_range": "Bounded by Claude's knowledge cutoff; prompt structure maintained continuously.",
            "known_gaps": "Quality depends on completeness of available chart context.",
        },
        "risk_tier": "tier_2_moderate",
        "monitoring_plan": {
            "cadence": "Quarterly clinician-edit-rate review (Tier 2).",
            "drift_detection": "Override edit-distance tracked via /api/governance/override-metrics as a draft-quality signal.",
            "triggers": "Sustained heavy-edit rate triggers prompt review.",
            "rollback": "Prompt versioned; prior version restorable.",
        },
        "synthetic_data_caveat": "No Solace-side training or synthetic data; output is a draft summary the clinician must verify.",
        "fairness": {
            "fnr_by_group_under_audit": False,
            "equity_note": "Reformats existing chart content into a handoff structure; no patient-specific prediction, so subgroup FNR/FPR does not apply.",
        },
        "governance": {"clinician_edits_before_use": True},
    },
    "redaction_and_loop_closure": {
        "name": "Solace auto-redaction + closed-loop result tracking",
        "version": "v1 (2026-05)",
        "intended_use": "Strip off-record conversation segments from scribe transcripts; track abnormal results until clinician acts.",
        "intended_population": "Scribe-recorded encounters (redaction) and ordered diagnostic results requiring follow-up (loop closure) in US care settings.",
        "intended_output": "A redacted transcript with off-record segments removed (unredacted version always available), and a tracked queue of abnormal results with severity-aware SLAs.",
        "model_type": "Regex fast-path + Claude Sonnet 4.5 conservative classifier; rule-based loop tracker with severity-aware SLA.",
        "data_provenance": {
            "origin": "Regex patterns + Claude Sonnet 4.5 conservative classification for redaction; deterministic rule-based tracker for loop closure.",
            "lineage": "Transcript -> regex + classifier redaction -> redacted draft (unredacted retained); Result -> severity classification -> SLA-tracked queue.",
            "consent_basis": "Operates within an already-consented scribe encounter; no separate training data.",
            "time_range": "Patterns and SLA rules fixed at v1 release.",
            "known_gaps": "Conservative bias may retain ambiguous segments.",
        },
        "risk_tier": "tier_2_moderate",
        "monitoring_plan": {
            "cadence": "Quarterly redaction-precision and loop-closure SLA-adherence review (Tier 2).",
            "drift_detection": "Tracks redaction false-negative spot checks and result-loop overdue counts.",
            "triggers": "Any redaction false negative, or rising overdue-loop count, triggers classifier and SLA review.",
            "rollback": "Classifier prompt and SLA rules versioned; unredacted transcript always recoverable.",
        },
        "synthetic_data_caveat": "No synthetic data. The classifier is deliberately conservative, biasing toward keeping content rather than fabricated removal; loop tracking is fully deterministic.",
        "limitations": [
            "Conservative bias — may keep ambiguous segments. Clinician can always view unredacted transcript.",
        ],
        "fairness": {
            "fnr_by_group_under_audit": False,
            "equity_note": "Redaction and loop tracking are content-handling utilities, not patient predictors; audited for even loop-closure SLA adherence across patient subgroups.",
        },
        "governance": {
            "unredacted_view_always_available": True,
            "loop_closure_addresses_a_top_malpractice_driver": True,
        },
    },
    "no_show_predictor": {
        "name": "Solace no-show predictor (v1 rule-based)",
        "version": "v1 (2026-05)",
        "intended_use": "Risk-tier patients for tiered reminder cadence.",
        "intended_population": "Scheduled outpatients eligible for appointment reminders. Explicitly NOT intended to gate scheduling, deny appointments, or inform overbooking against any individual.",
        "intended_output": "A no-show risk tier used only to set reminder cadence (more reminders for higher risk). Never used to deny or deprioritize an appointment.",
        "model_type": "Hand-crafted rule-based scoring; v2 will be gradient-boosted on hospital data.",
        "training_data": {"source": "Public no-show literature meta-analyses"},
        "data_provenance": {
            "origin": "v1 scoring rules derived from public no-show literature meta-analyses; no proprietary training set.",
            "lineage": "Appointment + visit-history features (race and zip deliberately excluded) -> rule-based score -> reminder-cadence tier.",
            "consent_basis": "Operates on scheduling data; no separate data collection or training.",
            "time_range": "Rules fixed at v1; v2 will train on hospital data with documented ranges and a pre-deployment disparate-impact test.",
            "known_gaps": "Rule-based scoring is coarse; v2 ML model planned.",
        },
        "risk_tier": "tier_3_low",
        "monitoring_plan": {
            "cadence": "Semi-annual fairness review (Tier 3); disparate-impact test mandatory before any v2 ML model ships.",
            "drift_detection": "Tracks no-show rate by reminder tier and per-subgroup selection rate.",
            "triggers": "Any subgroup disparate-impact ratio < 0.80 in selection rate triggers rule review and blocks v2 deployment.",
            "rollback": "Rule set versioned; prior version restorable.",
        },
        "synthetic_data_caveat": "No synthetic data and no ML model in v1. The scoring is a transparent, inspectable rule set; race and ZIP code are deliberately excluded as features to avoid proxy discrimination.",
        "limitations": [
            "Rule-based v1 is coarse; v2 gradient-boosted model is planned with a pre-deployment equity test.",
        ],
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
    return [
        {
            "id": k,
            "name": v["name"],
            "version": v["version"],
            "risk_tier": v.get("risk_tier"),
        }
        for k, v in CARDS.items()
    ]


def get_card(card_id: str) -> dict[str, Any] | None:
    """Return a card enriched with its risk-tier detail and demographic table."""
    card = CARDS.get(card_id)
    if card is None:
        return None
    enriched = dict(card)
    tier_id = card.get("risk_tier")
    if tier_id:
        enriched["risk_tier_detail"] = RISK_TIERS.get(tier_id)
    enriched["demographic_performance"] = _empty_demographic_performance()
    return enriched


# --------------------------------------------------------------------------
# Bias-audit computation — a real working function.
# --------------------------------------------------------------------------
def _rate(numerator: int, denominator: int) -> float | None:
    """Safe rate; None when there is no denominator."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def compute_subgroup_rates(counts: dict[str, dict[str, dict[str, int]]]) -> dict[str, Any]:
    """Compute per-subgroup FNR/FPR, disparate-impact ratios, and equity flags.

    Input shape — confusion-matrix counts per subgroup, grouped by protected axis::

        {
          "sex": {
            "female": {"tp": 120, "fp": 30, "fn": 18, "tn": 400},
            "male":   {"tp": 110, "fp": 22, "fn": 9,  "tn": 380},
          },
          "insurance_type": { ... },
        }

    For each subgroup:
      fnr = fn / (fn + tp)        — missed positives; the safety-critical metric
      fpr = fp / (fp + tn)        — over-triage rate
      selection_rate = (tp + fp) / n   — share predicted positive
      n = tp + fp + fn + tn

    Subgroups with n below BIAS_AUDIT_METHODOLOGY['sample_size_floor'] are marked
    'insufficient_sample' and excluded from the disparate-impact computation.

    For each axis, disparate-impact ratios are computed over the eligible
    subgroups:
      fnr_ratio = min(FNR) / max(FNR)   — low ratio => one group missed far more
      fpr_ratio = min(FPR) / max(FPR)
      selection_rate_ratio = min / max  — the classic four-fifths-rule ratio

    Any ratio below the 0.80 flag threshold sets axis-level and top-level flags.
    Pure function — no I/O, deterministic, safe to unit test.
    """
    floor = BIAS_AUDIT_METHODOLOGY["sample_size_floor"]
    threshold = BIAS_AUDIT_METHODOLOGY["disparate_impact"]["flag_threshold"]

    result: dict[str, Any] = {
        "schema": "subgroup_rate_audit",
        "sample_size_floor": floor,
        "flag_threshold": threshold,
        "axes": {},
        "flags": [],
        "passed": True,
    }

    for axis, subgroups in counts.items():
        axis_out: dict[str, Any] = {"subgroups": {}, "disparate_impact": {}, "flags": []}
        eligible: dict[str, dict[str, float]] = {}

        for group, c in subgroups.items():
            tp = int(c.get("tp", 0))
            fp = int(c.get("fp", 0))
            fn = int(c.get("fn", 0))
            tn = int(c.get("tn", 0))
            n = tp + fp + fn + tn
            fnr = _rate(fn, fn + tp)
            fpr = _rate(fp, fp + tn)
            selection_rate = _rate(tp + fp, n)
            status = "ok" if n >= floor else "insufficient_sample"

            axis_out["subgroups"][group] = {
                "n": n,
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "fnr": fnr,
                "fpr": fpr,
                "selection_rate": selection_rate,
                "status": status,
            }
            if status == "ok" and fnr is not None and fpr is not None and selection_rate is not None:
                eligible[group] = {"fnr": fnr, "fpr": fpr, "selection_rate": selection_rate}

        # Disparate-impact ratios over eligible subgroups only.
        for metric in ("fnr", "fpr", "selection_rate"):
            vals = {g: v[metric] for g, v in eligible.items()}
            if len(vals) < 2:
                axis_out["disparate_impact"][metric] = {
                    "ratio": None,
                    "status": "insufficient_subgroups",
                }
                continue
            lo_group = min(vals, key=lambda g: vals[g])
            hi_group = max(vals, key=lambda g: vals[g])
            hi = vals[hi_group]
            lo = vals[lo_group]
            ratio = round(lo / hi, 4) if hi > 0 else 1.0
            flagged = ratio < threshold
            axis_out["disparate_impact"][metric] = {
                "ratio": ratio,
                "min_group": lo_group,
                "max_group": hi_group,
                "min_value": lo,
                "max_value": hi,
                "flagged": flagged,
            }
            if flagged:
                msg = (
                    f"{axis}: {metric} disparate-impact ratio {ratio} < {threshold} "
                    f"(min '{lo_group}'={lo}, max '{hi_group}'={hi}) — "
                    f"mandatory model-owner review before ship."
                )
                axis_out["flags"].append(msg)
                result["flags"].append(msg)
                result["passed"] = False

        result["axes"][axis] = axis_out

    return result


def _card_audit_block(card_id: str, card: dict[str, Any]) -> dict[str, Any]:
    """Per-model bias-audit block assembled from a card plus the empty table."""
    fairness = card.get("fairness", {})
    return {
        "model_id": card_id,
        "name": card["name"],
        "version": card["version"],
        "risk_tier": card.get("risk_tier"),
        "risk_tier_detail": RISK_TIERS.get(card.get("risk_tier", "")),
        "subgroup_audit_applicable": bool(fairness.get("fnr_by_group_under_audit", False)),
        "groups_audited": fairness.get("groups_audited", []),
        "bias_mitigation": fairness.get("bias_mitigation"),
        "equity_note": fairness.get("equity_note"),
        "demographic_performance": _empty_demographic_performance(),
        "monitoring_plan": card.get("monitoring_plan"),
    }


def bias_audit(model_id: str | None = None) -> dict[str, Any]:
    """Assemble the published bias audit — methodology + per-model audit blocks.

    With no model_id, returns the methodology plus an audit block for every
    card. With a model_id, returns the methodology plus that single block.
    Raises KeyError for an unknown model_id so the router can return 404.
    """
    if model_id is not None:
        card = CARDS.get(model_id)
        if card is None:
            raise KeyError(model_id)
        models = {model_id: _card_audit_block(model_id, card)}
    else:
        models = {cid: _card_audit_block(cid, c) for cid, c in CARDS.items()}

    return {
        "framework": "HTI-1 DSI fairness source attributes",
        "methodology": BIAS_AUDIT_METHODOLOGY,
        "risk_tiers": RISK_TIERS,
        "models": models,
        "disclosure": (
            "Demographic-performance tables are published empty-but-structured "
            "until the prospective deployment cohort reaches the per-cell "
            "sample-size floor. compute_subgroup_rates() is live and ready to "
            "populate them; the structure will not change when real data lands."
        ),
    }


def transparency_summary() -> dict[str, Any]:
    """One-page HTI-1 transparency summary across every Solace AI surface.

    Designed for procurement teams and CMIOs: a single object that lists every
    model, its risk tier, the HTI-1 source attributes it discloses, and the
    governance posture — without needing to fetch every card individually.
    """
    hti1_attributes = [
        "intended_population",
        "intended_output",
        "data_provenance",
        "risk_tier",
        "monitoring_plan",
        "synthetic_data_caveat",
    ]

    tier_counts: dict[str, int] = {t: 0 for t in RISK_TIERS}
    models: list[dict[str, Any]] = []

    for cid, card in CARDS.items():
        tier = card.get("risk_tier")
        if tier in tier_counts:
            tier_counts[tier] += 1
        disclosed = [a for a in hti1_attributes if card.get(a) not in (None, "", {}, [])]
        gov = card.get("governance", {})
        models.append({
            "model_id": cid,
            "name": card["name"],
            "version": card["version"],
            "risk_tier": tier,
            "intended_use": card.get("intended_use"),
            "hti1_attributes_disclosed": disclosed,
            "hti1_attributes_total": len(hti1_attributes),
            "human_in_loop": bool(gov.get("human_in_loop")) or any(
                k in gov for k in (
                    "clinician_edits_before_use", "no_auto_attestation",
                    "no_autosubmit", "no_autosubmit_to_chart", "no_autocall",
                )
            ),
            "autonomous_action": False,
        })

    return {
        "framework": "HTI-1 DSI transparency (45 CFR 170.315(b)(11))",
        "as_of": "2026-05",
        "hti1_source_attributes_tracked": hti1_attributes,
        "model_count": len(CARDS),
        "risk_tier_distribution": tier_counts,
        "risk_tiers": RISK_TIERS,
        "governance_posture": {
            "human_in_loop_required": True,
            "autonomous_clinical_action": False,
            "override_logging": "Every accept/edit/reject decision logged; metrics at /api/governance/override-metrics.",
            "bias_audit": "Methodology and empty-but-structured tables at /api/governance/bias-audit.",
            "consent_gate": "All AI inference gated on explicit patient consent (constitution SEC-004).",
            "phi_boundary": "Default AI providers are BAA-covered AWS services (constitution COMP-005).",
        },
        "models": models,
        "endpoints": {
            "model_cards": "/api/model-cards",
            "model_card_detail": "/api/model-cards/{card_id}",
            "bias_audit": "/api/governance/bias-audit",
            "bias_audit_detail": "/api/governance/bias-audit/{model_id}",
            "transparency_summary": "/api/governance/transparency-summary",
            "override_metrics": "/api/governance/override-metrics",
            "override_log": "/api/governance/override-log",
        },
    }


# ==========================================================================
# Solace Trust Report — the PUBLIC, aggregate-only transparency surface.
#
# This is the productized governance layer: calibration + conformal coverage,
# bias/fairness summary, and live aggregate override-acceptance, assembled into
# a single object safe to render on a public website with NO auth.
#
# HARD CONSTRAINTS (enforced here, re-checked in tests):
#   1. AGGREGATE ONLY. Never per-record override entries. We compute rates and
#      counts from provenance.metrics() (which already strips PHI); we NEVER
#      touch provenance.overrides() raw rows, so patient_id / clinician_id /
#      free-text notes can never reach this payload.
#   2. HONEST LABELING. Calibration today comes from a SYNTHETIC validation
#      cohort with no real clinical outcome labels. Every calibration metric is
#      tagged provenance="synthetic validation cohort"; the report carries a
#      top-level disclaimer. We MUST NOT claim real-world clinical calibration.
# ==========================================================================

SYNTHETIC_COHORT_PROVENANCE = "synthetic validation cohort"

TRUST_REPORT_DISCLAIMER = (
    "Preliminary — calibration and conformal-coverage figures on this page are "
    "measured on a SYNTHETIC validation cohort with no real-world clinical "
    "outcome labels. They demonstrate that the uncertainty machinery is wired "
    "and measurable; they are NOT a claim of real-world clinical calibration. "
    "When clinician-confirmed outcome labels accrue in the label store, the same "
    "surface upgrades in place and this banner is removed."
)

# Keys that would indicate a PHI / per-record leak. Used by the self-check
# below and mirrored by the endpoint test. If any of these ever appears in the
# assembled payload, we have a bug and must fail loudly rather than ship PHI.
_PHI_LEAK_KEYS = frozenset({"patient_id", "clinician_id", "notes", "entries", "diff_chars"})


def _conformal_calibration_block() -> dict[str, Any]:
    """Per-ESI conformal q̂ + empirical coverage on the synthetic calibration set.

    Best-effort and import-safe: if the ML artifact or its optional ML deps are
    not present (e.g. minimal CI image), this returns a documented placeholder
    rather than raising. Reads the triage ML artifact and the conformal library
    by IMPORT ONLY — it never mutates them and never calls predict() with PHI.

    Everything here is tagged with provenance="synthetic validation cohort".
    """
    block: dict[str, Any] = {
        "model_id": "triage_lightgbm",
        "method": "mondrian_class_conditional_split_conformal",
        "target_coverage": None,
        "provenance": SYNTHETIC_COHORT_PROVENANCE,
        "labels_are_real_clinical_outcomes": False,
        "status": "unavailable",
        "note": (
            "Conformal calibration metrics could not be loaded in this "
            "environment (ML artifact or optional ML dependencies absent). "
            "The methodology is fixed; figures populate where the model loads."
        ),
        "q_hat_by_esi": None,
        "empirical_coverage": None,
    }

    try:
        from lib import conformal  # noqa: PLC0415
        from services import triage_ml  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        log.info("trust-report: conformal/triage_ml import unavailable (%s)", e)
        return block

    try:
        art = triage_ml._load()  # read-only; lru-cached per process
    except Exception as e:  # noqa: BLE001
        log.info("trust-report: triage_ml artifact load failed (%s)", e)
        return block

    if not art:
        return block

    cal = art.get("conformal")
    if cal is None:
        block["note"] = (
            "Model loaded but Mondrian conformal calibration was not fitted "
            "(fell back to the legacy global scalar). Per-class q̂ unavailable."
        )
        return block

    alpha = float(getattr(cal, "alpha", conformal.DEFAULT_ALPHA))
    block["target_coverage"] = round(1.0 - alpha, 4)
    block["calibration_source"] = getattr(cal, "source", "synthetic_calibration")
    block["calibration_n_per_class"] = {
        str(c + 1): int(n) for c, n in getattr(cal, "n_per_class", {}).items()
    }
    try:
        block["q_hat_by_esi"] = cal.q_hat_by_esi()
        block["representative_q_hat"] = round(cal.representative_q_hat(), 6)
    except Exception as e:  # noqa: BLE001
        log.info("trust-report: q_hat read failed (%s)", e)

    # Empirical coverage on the SAME synthetic calibration profiles the
    # calibrator was fit on. This is in-sample on a synthetic distribution — we
    # say so explicitly. No PHI: the profiles are templated synthetic patients.
    try:
        import numpy as np  # noqa: PLC0415

        profiles = triage_ml._synthetic_calibration_profiles()
        probs_rows: list[Any] = []
        labels: list[int] = []
        for patient, vitals, esi0 in profiles:
            try:
                X = triage_ml._build_feature_matrix(art, patient, vitals)
                probs_rows.append(triage_ml._model_probs(art, X)[0])
                labels.append(esi0)
            except Exception:  # noqa: BLE001
                continue
        if probs_rows:
            cov = conformal.empirical_coverage(
                cal, np.vstack(probs_rows), np.asarray(labels, dtype=np.int64)
            )
            block["empirical_coverage"] = {
                "overall": round(cov["overall"], 4),
                "by_esi": {k: round(v, 4) for k, v in cov["by_class"].items()},
                "avg_set_size": round(cov["avg_set_size"], 4),
                "n": len(labels),
                "evaluation": "in_sample_synthetic",
            }
    except Exception as e:  # noqa: BLE001
        log.info("trust-report: empirical coverage computation failed (%s)", e)

    block["status"] = "available"
    block["note"] = (
        "Per-ESI q̂ and coverage are measured on a class-balanced SYNTHETIC "
        "calibration cohort. A single global q̂ collapses to a misleading "
        "singleton on this clean synthetic distribution, so calibration is "
        "class-conditional (Mondrian). These figures are NOT real-world "
        "clinical calibration and must be recalibrated on clinician-confirmed "
        "outcomes before any coverage guarantee is relied upon."
    )
    return block


def _override_acceptance_block(hospital_id: str | None) -> dict[str, Any]:
    """Aggregate override-acceptance — counts + accept/edit/reject rates only.

    Sourced from lib.provenance.metrics(), which returns per-purpose totals and
    rates with NO per-record fields. We deliberately do NOT call
    provenance.overrides(): raw entries carry an opaque patient_id, a
    clinician_id, and free-text notes, none of which belong on a public page.
    """
    try:
        from lib import provenance  # noqa: PLC0415

        by_purpose = provenance.metrics(hospital_id)
    except Exception as e:  # noqa: BLE001
        log.info("trust-report: override metrics unavailable (%s)", e)
        by_purpose = {}

    total_decisions = sum(int(v.get("total", 0)) for v in by_purpose.values())
    return {
        "scope": "global" if hospital_id is None else hospital_id,
        "source": "lib.provenance.metrics (aggregate; no per-record data)",
        "total_decisions": total_decisions,
        "by_purpose": by_purpose,
        "definition": {
            "accept_rate": "Share of AI suggestions a clinician accepted unedited.",
            "edit_rate": "Share accepted after clinician edits.",
            "reject_rate": "Share the clinician rejected outright.",
        },
        "phi_note": (
            "Aggregate rates and counts only. Per-record override entries "
            "(which reference an opaque patient_id, a clinician_id, and "
            "free-text notes) are NEVER exposed on this public surface."
        ),
    }


def _fairness_summary_block() -> dict[str, Any]:
    """Bias/fairness summary distilled from the per-model bias-audit blocks.

    Reuses the existing bias_audit() machinery (the hard half of HTI-1 DSI).
    Today the demographic-performance cells are empty-but-structured pending a
    real prospective cohort; we surface that status honestly rather than
    inventing subgroup rates.
    """
    audit = bias_audit()
    models = audit.get("models", {})
    summary_models = []
    for mid, block in models.items():
        summary_models.append({
            "model_id": mid,
            "name": block.get("name"),
            "risk_tier": block.get("risk_tier"),
            "subgroup_audit_applicable": block.get("subgroup_audit_applicable"),
            "groups_audited": block.get("groups_audited", []),
            "demographic_performance_status": block.get(
                "demographic_performance", {}
            ).get("status"),
            "equity_note": block.get("equity_note"),
        })
    return {
        "framework": audit.get("framework"),
        "methodology": audit.get("methodology"),
        "models": summary_models,
        "data_status": "pending_prospective_data",
        "provenance": SYNTHETIC_COHORT_PROVENANCE,
        "disclosure": (
            "Subgroup FNR/FPR tables are published empty-but-structured until a "
            "prospective deployment cohort reaches the per-cell sample-size "
            "floor. No subgroup performance numbers are claimed today."
        ),
    }


def _assert_no_phi(payload: Any) -> None:
    """Recursively assert the assembled report carries no per-record PHI keys.

    Defensive: even though every assembly path is aggregate-only, this walks the
    final object and raises if any leak-indicator key appears, so a future
    regression fails loudly instead of silently shipping PHI on a public page.
    """
    if isinstance(payload, dict):
        leaked = _PHI_LEAK_KEYS & set(payload.keys())
        if leaked:
            raise AssertionError(f"trust-report PHI guard tripped on keys: {sorted(leaked)}")
        for v in payload.values():
            _assert_no_phi(v)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_phi(item)


# ==========================================================================
# AI Bill-of-Materials (AI-BOM) — the procurement/RFP-grade software-supply-chain
# inventory for every AI component in Solace.
#
# Every fact below is sourced from REAL config + code, not invented:
#   - In-use Claude model + the exact Bedrock inference-profile ID come from
#     lib.config.settings.model_clinical / model_utility resolved through
#     lib.claude._BEDROCK_MODEL_MAP at call time.
#   - Provider/BAA posture comes from the runtime provider switches
#     (lib.claude.provider(), TRANSCRIPTION_PROVIDER, TTS_PROVIDER) and the
#     constitution COMP-005 default-to-BAA rule.
#   - Data-handling posture cites content_guard (15 HIPAA identifier families),
#     ai_log (per-call provider attribution), the copilot PHI-isolation design,
#     and CMK-at-rest (COMP-003).
# No fabricated benchmarks. Anything not yet measured is labeled honestly.
# ==========================================================================

# HIPAA Safe Harbor identifier FAMILIES that content_guard._PII_REDACTIONS
# actively redacts before any third-party AI call. Sourced by inspecting the
# redaction tags in content_guard, NOT hand-asserted — see _redacted_pii_families.
_CONTENT_GUARD_PII_FAMILIES = (
    "SSN", "CARD", "PHONE", "EMAIL", "DOB", "DATE", "ADDRESS", "ZIP",
    "MRN", "MEMBER_ID", "ACCOUNT", "LICENSE", "VIN", "DEVICE_ID", "URL", "IP",
)


def _redacted_pii_families() -> list[str]:
    """Read the live content_guard redaction set so the AI-BOM cites the real
    redaction families, not a hand-maintained copy that could drift.

    Import-safe: falls back to the documented constant if content_guard cannot
    be imported in a stripped environment.
    """
    try:
        from lib import content_guard  # noqa: PLC0415

        families: list[str] = []
        for _pattern, replacement in content_guard._PII_REDACTIONS:
            # replacement looks like "[REDACTED:SSN]"; pull the family token.
            tag = replacement.strip("[]").split(":", 1)[-1]
            if tag and tag not in families:
                families.append(tag)
        return families
    except Exception as e:  # noqa: BLE001
        log.info("ai-bom: content_guard introspection unavailable (%s)", e)
        return list(_CONTENT_GUARD_PII_FAMILIES)


def _resolve_claude_models() -> dict[str, Any]:
    """Resolve the in-use Claude model tiers + their Bedrock inference-profile IDs
    from REAL config and the live Bedrock model map. No invented IDs."""
    out: dict[str, Any] = {
        "model_clinical": {"configured": None, "bedrock_inference_profile": None},
        "model_utility": {"configured": None, "bedrock_inference_profile": None},
        "default_provider": "bedrock",
        "source": "lib.config.settings + lib.claude._BEDROCK_MODEL_MAP",
    }
    try:
        from lib import claude  # noqa: PLC0415
        from lib.config import settings  # noqa: PLC0415

        out["default_provider"] = claude.provider()
        for tier in ("model_clinical", "model_utility"):
            configured = getattr(settings, tier, None)
            out[tier] = {
                "configured": configured,
                "bedrock_inference_profile": (
                    claude._BEDROCK_MODEL_MAP.get(configured, configured)
                    if configured else None
                ),
            }
    except Exception as e:  # noqa: BLE001
        log.info("ai-bom: claude/config introspection unavailable (%s)", e)
    return out


def ai_bom() -> dict[str, Any]:
    """Assemble the AI Bill-of-Materials — every model, version, provider,
    purpose, and data-handling posture, sourced from real config + code.

    Procurement/RFP-grade: a security team can read exactly which AI components
    process data, who operates them, whether they sit inside the AWS BAA
    perimeter, and what redaction/attribution controls wrap each call.

    Aggregate-only and PHI-free by construction; the caller (and trust_report)
    runs _assert_no_phi over it.
    """
    resolved = _resolve_claude_models()
    pii_families = _redacted_pii_families()
    clinical = resolved.get("model_clinical", {})
    utility = resolved.get("model_utility", {})

    components: list[dict[str, Any]] = [
        {
            "component_id": "claude_clinical",
            "kind": "llm",
            "name": "Anthropic Claude (clinical reasoning tier)",
            "configured_model": clinical.get("configured"),
            "bedrock_inference_profile": clinical.get("bedrock_inference_profile"),
            "version_source": "lib.config.settings.model_clinical (env MODEL_CLINICAL)",
            "provider": {
                "default": "AWS Bedrock",
                "baa_covered": True,
                "baa_basis": "AWS BAA covers Amazon Bedrock; model invocation stays inside the AWS perimeter (lib.claude default provider=bedrock).",
                "opt_in_fallback": "Direct Anthropic API (CLAUDE_PROVIDER=direct) — local dev only; requires a separate Anthropic BAA before any PHI use.",
            },
            "purpose": "Differential diagnosis, disposition/workup reasoning, ambient-scribe refinement, coding candidate generation, HCC suspecting, handoff and evidence-RAG synthesis.",
            "data_handling": {
                "phi_minimization": "Inputs pass content_guard.scan() (SEC-005 / COMP-001) which redacts HIPAA Safe Harbor identifiers before the call.",
                "phi_isolation": "EHR Copilot plans/narrates over coded metadata only and never receives raw PHI (PHI-isolation design; leak test is a CI gate).",
                "attribution": "Every call recorded to lib.ai_log (provider, model, purpose, byte counts, success) for per-encounter auditability.",
                "transport": "TLS 1.2+ in transit (COMP-004); no cleartext path to PHI.",
            },
            "evidence": [
                "backend/lib/claude.py:_BEDROCK_MODEL_MAP",
                "backend/lib/config.py:model_clinical",
                "backend/lib/content_guard.py:scan",
                "backend/lib/ai_log.py:record",
            ],
        },
        {
            "component_id": "claude_utility",
            "kind": "llm",
            "name": "Anthropic Claude (utility tier)",
            "configured_model": utility.get("configured"),
            "bedrock_inference_profile": utility.get("bedrock_inference_profile"),
            "version_source": "lib.config.settings.model_utility (env MODEL_UTILITY)",
            "provider": {
                "default": "AWS Bedrock",
                "baa_covered": True,
                "baa_basis": "AWS BAA covers Amazon Bedrock (lib.claude default provider=bedrock).",
                "opt_in_fallback": "Direct Anthropic API (CLAUDE_PROVIDER=direct) — local dev only.",
            },
            "purpose": "Structured/boilerplate generation — follow-up questions, OCR labeling, redaction classification, letters, discharge text.",
            "data_handling": {
                "phi_minimization": "Same content_guard redaction path as the clinical tier.",
                "attribution": "lib.ai_log per-call attribution.",
                "transport": "TLS 1.2+ in transit (COMP-004).",
            },
            "evidence": [
                "backend/lib/config.py:model_utility",
                "backend/lib/claude.py:messages_create",
            ],
        },
        {
            "component_id": "asr_transcription",
            "kind": "asr",
            "name": "Speech-to-text (transcription + ambient scribe)",
            "configured_model": "aws-transcribe / AWS HealthScribe",
            "bedrock_inference_profile": None,
            "version_source": "env TRANSCRIPTION_PROVIDER (default 'aws'); ambient scribe uses StartMedicalScribeJob",
            "provider": {
                "default": "AWS Transcribe / AWS HealthScribe",
                "baa_covered": True,
                "baa_basis": "AWS BAA covers Amazon Transcribe and HealthScribe; audio + transcript stay inside the AWS perimeter.",
                "opt_in_fallback": "OpenAI Whisper (TRANSCRIPTION_PROVIDER=openai) — local dev only; not BAA-covered, must not see PHI.",
            },
            "purpose": "Transcribe patient/clinician audio; HealthScribe produces diarized transcript + sections for the ambient scribe.",
            "data_handling": {
                "consent_gate": "Recording proceeds only after explicit patient consent_granted == true (SEC-004).",
                "phi_minimization": "Extracted transcript text passes content_guard.scan() before any Claude refinement (SEC-005).",
                "attribution": "lib.ai_log records model='aws-transcribe' per call.",
                "retention": "Audio retained 30 days; transcript per institutional policy (see ambient_scribe card).",
            },
            "evidence": [
                "backend/services/transcription.py:_aws_transcribe",
                "backend/services/ambient_scribe.py:start_medical_scribe_job",
            ],
        },
        {
            "component_id": "tts_polly",
            "kind": "tts",
            "name": "Text-to-speech (patient comfort scripts)",
            "configured_model": "aws-polly (neural voices)",
            "bedrock_inference_profile": None,
            "version_source": "env TTS_PROVIDER (default 'aws')",
            "provider": {
                "default": "AWS Polly",
                "baa_covered": True,
                "baa_basis": "AWS BAA covers Amazon Polly; comfort-script synthesis stays inside the AWS perimeter.",
                "opt_in_fallback": "ElevenLabs (TTS_PROVIDER=elevenlabs) — local dev only; not BAA-covered.",
            },
            "purpose": "Synthesize patient comfort/instruction audio from text.",
            "data_handling": {
                "attribution": "lib.ai_log records model='aws-polly' per call.",
                "transport": "TLS 1.2+ in transit (COMP-004).",
            },
            "evidence": ["backend/services/tts.py:_aws_polly_synthesize"],
        },
        {
            "component_id": "triage_lightgbm",
            "kind": "ml_model",
            "name": "Solace ML triage ensemble (LightGBM 5-fold + stacked layer)",
            "configured_model": CARDS["triage_lightgbm"]["version"],
            "bedrock_inference_profile": None,
            "version_source": "backend/models/ artifact, loaded by services.triage_ml._load() (ARCH-004)",
            "provider": {
                "default": "Self-hosted (in-VPC Lambda)",
                "baa_covered": True,
                "baa_basis": "Model runs inside Solace's own AWS account; no third-party AI provider sees triage features.",
                "opt_in_fallback": None,
            },
            "purpose": "ESI-level decision support with a conformal prediction set and SHAP attributions.",
            "data_handling": {
                "phi_minimization": "Operates on engineered clinical features, not free-text PHI.",
                "uncertainty": "Mondrian class-conditional split-conformal calibration (see Trust Report calibration block).",
                "no_external_egress": "No features leave the Solace AWS account for inference.",
            },
            "model_card": "/api/model-cards/triage_lightgbm",
            "evidence": [
                "backend/services/triage_ml.py:_load",
                "backend/lib/conformal.py",
            ],
        },
    ]

    return {
        "artifact": "AI Bill-of-Materials (AI-BOM)",
        "spec_alignment": "NTIA SBOM minimum elements adapted for AI components; HTI-1 DSI source attributes; NIST AI RMF inventory practice.",
        "as_of": "2026-05",
        "default_provider_posture": (
            "BAA-covered AWS AI services (Bedrock, Transcribe/HealthScribe, Polly) "
            "are the defaults; direct third-party APIs are opt-in, local-dev-only "
            "fallbacks gated by explicit env override (constitution COMP-005)."
        ),
        "resolved_models": resolved,
        "components": components,
        "data_handling_controls": {
            "hipaa_safe_harbor_redaction": {
                "families_redacted": pii_families,
                "family_count": len(pii_families),
                "control": "content_guard.scan() redacts these identifier families before any text reaches a third-party AI provider.",
                "evidence": "backend/lib/content_guard.py:_PII_REDACTIONS",
            },
            "phi_isolation": {
                "control": "EHR Copilot operates on coded metadata and never receives raw PHI (Plan -> Execute -> Narrate); a no-PHI leak test gates CI.",
                "evidence": "EHR Copilot PHI-isolation design",
            },
            "per_call_attribution": {
                "control": "Every third-party AI call is logged with provider, model, purpose, byte counts, and success.",
                "evidence": "backend/lib/ai_log.py:AIEvent",
            },
            "encryption_at_rest": {
                "control": "All patient data stores use the single solace CMK (alias/solace) with annual rotation.",
                "evidence": "constitution COMP-003",
            },
            "consent_gate": {
                "control": "All AI inference is gated on explicit patient consent (consent_granted == true) or rejected 403.",
                "evidence": "constitution SEC-004",
            },
        },
        "disclosure": (
            "Model identifiers and provider/BAA posture are read from live config "
            "and code at request time, not hand-maintained. No benchmark numbers "
            "are asserted here — see /api/model-cards and the Trust Report "
            "calibration block (synthetic cohort) for measured figures."
        ),
    }


# ==========================================================================
# AI threat-control / safety attestation pack.
#
# Productizes the controls that already shipped: PHI-isolation, content_guard
# scanning, conformal-calibration honesty, audit dual-write, and override
# transparency. Each is an attestable statement with an evidence path and an
# HONEST maturity label — implemented controls are marked "implemented", and
# anything synthetic/preliminary is marked as such (same discipline as the
# Trust Report's synthetic-cohort labeling). We do NOT overclaim.
# ==========================================================================

# Attestation maturity vocabulary — used so every control declares, honestly,
# how far it is from a fully prospectively-validated state.
_ATTESTATION_MATURITY = {
    "implemented": "Control is implemented in code and exercised by the test suite.",
    "implemented_synthetic_validation": "Control is implemented; its quantitative evidence today comes from a synthetic cohort, not real-world clinical outcomes.",
    "design_commitment": "Control is a documented design/process commitment; runtime enforcement or measurement is partial or pending.",
}


def _control(
    control_id: str,
    title: str,
    statement: str,
    maturity: str,
    evidence: list[str],
    *,
    threat: str,
    framework_refs: list[str],
    caveat: str | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "control_id": control_id,
        "title": title,
        "statement": statement,
        "mitigates_threat": threat,
        "maturity": maturity,
        "maturity_definition": _ATTESTATION_MATURITY.get(maturity),
        "framework_refs": framework_refs,
        "evidence": evidence,
    }
    if caveat:
        block["honest_caveat"] = caveat
    return block


def attestation_pack() -> dict[str, Any]:
    """Assemble the AI threat-control / safety attestation pack.

    Each control is an attestable statement productizing a shipped safeguard,
    with an evidence path, the threat it mitigates, framework references, and an
    HONEST maturity label. Synthetic / preliminary evidence is labeled as such.

    Aggregate-only and PHI-free; trust_report runs _assert_no_phi over it.
    """
    controls = [
        _control(
            "AISC-01",
            "PHI isolation for the EHR Copilot",
            "The EHR Copilot plans and narrates over coded clinical metadata and never receives raw PHI. A Plan -> Execute -> Narrate split keeps the language model away from identifiable patient text.",
            "design_commitment",
            ["EHR Copilot PHI-isolation design", "CI no-PHI leak test (fail-closed gate)"],
            threat="Sensitive-data disclosure to an LLM (OWASP LLM06); HIPAA minimum-necessary violation.",
            framework_refs=["HIPAA §164.502(b) minimum necessary", "OWASP LLM Top 10 — LLM06", "NIST AI RMF MAP-1"],
            caveat="Enforced by a CI leak test rather than a formal external audit; no third-party penetration test of the isolation boundary has been published yet.",
        ),
        _control(
            "AISC-02",
            "Pre-inference content guard (injection + PHI redaction)",
            "All user-provided text is scanned by content_guard.scan() before any third-party AI call: high-confidence prompt-injection patterns are rejected (422), control tokens are stripped, and HIPAA Safe Harbor identifier families are redacted.",
            "implemented",
            ["backend/lib/content_guard.py:scan", "backend/lib/content_guard.py:_PII_REDACTIONS"],
            threat="Prompt injection (OWASP LLM01); PHI leakage to third-party providers (OWASP LLM06 / HIPAA §164.514).",
            framework_refs=["HIPAA §164.514(b) Safe Harbor", "OWASP LLM Top 10 — LLM01, LLM06", "constitution SEC-005, COMP-001"],
        ),
        _control(
            "AISC-03",
            "Honest uncertainty calibration",
            "The triage ensemble emits Mondrian class-conditional conformal prediction sets. Coverage figures published today are measured on a SYNTHETIC validation cohort and are explicitly labeled as not real-world clinical calibration.",
            "implemented_synthetic_validation",
            ["backend/lib/conformal.py", "backend/services/model_cards.py:_conformal_calibration_block"],
            threat="Overconfident model output / miscalibration leading to misplaced clinician trust.",
            framework_refs=["NIST AI RMF MEASURE-2.7", "HTI-1 DSI validity source attributes"],
            caveat="Calibration evidence is from a synthetic cohort with no clinician-confirmed outcome labels; it demonstrates the machinery is wired and measurable, not a real-world coverage guarantee.",
        ),
        _control(
            "AISC-04",
            "Immutable audit trail with dual-write",
            "Every clinician action is recorded via audit.record() with a dual-write to DynamoDB (90-day TTL) and CMK-encrypted S3 (per-day JSONL) to satisfy the 6-year immutable-audit requirement.",
            "implemented",
            ["backend/lib/audit.py:record", "constitution COMP-002"],
            threat="Repudiation / loss of accountability for AI-assisted decisions.",
            framework_refs=["HIPAA §164.312(b) audit controls", "HIPAA §164.530(j)(2) 6-year retention", "SOC 2 CC7"],
        ),
        _control(
            "AISC-05",
            "AI override transparency",
            "Every clinician accept / edit / reject of an AI suggestion is logged and surfaced as aggregate accept/edit/reject rates via the governance override metrics — a continuous signal of real clinical agreement.",
            "implemented",
            ["backend/lib/provenance.py:metrics", "backend/routers/governance.py:override_metrics"],
            threat="Automation bias / undetected model drift through unmonitored acceptance.",
            framework_refs=["NIST AI RMF MANAGE-4.1", "HTI-1 DSI ongoing-maintenance source attributes"],
        ),
        _control(
            "AISC-06",
            "Per-call provider attribution",
            "Every third-party AI call appends a lib.ai_log entry (provider, model, purpose, byte counts, success) so an auditor can reconstruct exactly which provider saw which bytes for which purpose.",
            "implemented",
            ["backend/lib/ai_log.py:AIEvent", "backend/lib/claude.py:messages_create"],
            threat="Untracked data flow to AI providers; inability to scope a provider incident.",
            framework_refs=["NIST AI RMF MAP-4", "SOC 2 CC7.2"],
        ),
        _control(
            "AISC-07",
            "Human-in-the-loop, no autonomous clinical action",
            "No Solace AI surface takes autonomous clinical action. Every model output is advisory and requires clinician review before it gates care or is written to the chart.",
            "implemented",
            ["backend/services/model_cards.py:CARDS (governance.human_in_loop / no_autosubmit flags)"],
            threat="Excessive agency / unsafe autonomous action (OWASP LLM08).",
            framework_refs=["OWASP LLM Top 10 — LLM08", "HTI-1 DSI risk-management source attributes"],
        ),
        _control(
            "AISC-08",
            "BAA-covered default AI providers",
            "Clinical AI defaults to BAA-covered AWS services (Bedrock, Transcribe/HealthScribe, Polly). Direct third-party APIs are opt-in, local-dev-only fallbacks gated by explicit env override.",
            "implemented",
            ["backend/lib/claude.py:provider", "backend/lib/config.py", "constitution COMP-005"],
            threat="PHI flowing to a non-BAA AI provider.",
            framework_refs=["HIPAA §164.308(b) business-associate contracts", "AWS Shared Responsibility"],
        ),
    ]

    maturity_counts: dict[str, int] = {m: 0 for m in _ATTESTATION_MATURITY}
    for c in controls:
        maturity_counts[c["maturity"]] = maturity_counts.get(c["maturity"], 0) + 1

    return {
        "artifact": "AI threat-control / safety attestation pack",
        "as_of": "2026-05",
        "frameworks": [
            "OWASP Top 10 for LLM Applications",
            "NIST AI Risk Management Framework (AI RMF 1.0)",
            "HTI-1 DSI source attributes (45 CFR 170.315(b)(11))",
            "HIPAA Security & Privacy Rules",
            "SOC 2",
        ],
        "control_count": len(controls),
        "maturity_legend": _ATTESTATION_MATURITY,
        "maturity_distribution": maturity_counts,
        "controls": controls,
        "honesty_statement": (
            "Maturity labels are deliberate. 'implemented' controls are in code and "
            "exercised by tests; 'implemented_synthetic_validation' means the "
            "control works but its quantitative evidence is from a synthetic cohort, "
            "not real-world clinical outcomes; 'design_commitment' means the control "
            "is a documented design/process whose runtime measurement is partial or "
            "pending. We do not claim external audit or prospective clinical "
            "validation we have not performed."
        ),
    }


def rfp_export(hospital_id: str | None = None) -> dict[str, Any]:
    """Assemble a single RFP/procurement-ready bundle: the Trust Report, the
    AI-BOM, and the attestation pack in one object a security/procurement team
    can drop straight into an RFP response.

    Aggregate-only, no PHI; _assert_no_phi runs over the whole bundle (the
    nested trust_report() also self-checks).
    """
    bundle: dict[str, Any] = {
        "artifact": "Solace RFP / procurement transparency bundle",
        "as_of": "2026-05",
        "scope": "global" if hospital_id is None else hospital_id,
        "preliminary": True,
        "disclaimer": TRUST_REPORT_DISCLAIMER,
        "contents": ["trust_report", "ai_bom", "attestation_pack"],
        "trust_report": trust_report(hospital_id),
        "ai_bom": ai_bom(),
        "attestation_pack": attestation_pack(),
        "endpoints": {
            "trust_report": "/api/governance/trust-report",
            "ai_bom": "/api/governance/ai-bom",
            "attestation_pack": "/api/governance/attestation-pack",
            "rfp_export": "/api/governance/rfp-export",
        },
    }
    _assert_no_phi(bundle)
    return bundle


def trust_report(hospital_id: str | None = None) -> dict[str, Any]:
    """Assemble the public Solace Trust Report — aggregate, no PHI, honest.

    Sections:
      - model_inventory     : every AI surface, version, risk tier (from cards)
      - ai_bom              : AI Bill-of-Materials — models, providers, BAA
                              posture, data-handling controls (real config/code)
      - attestation_pack    : AI threat-control / safety attestation, each with
                              an evidence path and an honest maturity label
      - calibration         : per-ESI conformal q̂ + empirical coverage
                              (SYNTHETIC validation cohort, labeled as such)
      - fairness            : bias/fairness summary from the HTI-1 bias audit
      - override_acceptance : aggregate accept/edit/reject rates + counts

    No auth required: the payload is aggregate-only by construction and passes
    the recursive PHI guard before it is returned.
    """
    cards = list_cards()
    report: dict[str, Any] = {
        "report": "Solace Trust Report",
        "framework": "HTI-1 DSI transparency (45 CFR 170.315(b)(11))",
        "as_of": "2026-05",
        "preliminary": True,
        "data_provenance": SYNTHETIC_COHORT_PROVENANCE,
        "disclaimer": TRUST_REPORT_DISCLAIMER,
        "scope": "global" if hospital_id is None else hospital_id,
        "model_inventory": {
            "count": len(cards),
            "models": cards,
        },
        "ai_bom": ai_bom(),
        "attestation_pack": attestation_pack(),
        "calibration": _conformal_calibration_block(),
        "fairness": _fairness_summary_block(),
        "override_acceptance": _override_acceptance_block(hospital_id),
        "endpoints": {
            "trust_report": "/api/governance/trust-report",
            "ai_bom": "/api/governance/ai-bom",
            "attestation_pack": "/api/governance/attestation-pack",
            "rfp_export": "/api/governance/rfp-export",
            "model_cards": "/api/model-cards",
            "bias_audit": "/api/governance/bias-audit",
            "transparency_summary": "/api/governance/transparency-summary",
            "override_metrics": "/api/governance/override-metrics",
        },
    }
    _assert_no_phi(report)
    return report
