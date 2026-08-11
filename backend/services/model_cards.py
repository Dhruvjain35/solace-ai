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

from typing import Any


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
        # training_data, data_provenance, performance and synthetic_data_caveat
        # are NOT written here. They are filled at read time by
        # _apply_triage_provenance() from the artifact the running model was
        # loaded from. See that function for why. Anything hand-written in this
        # block would be a second copy of a fact, and the second copy is the one
        # that goes stale.
        "risk_tier": "tier_1_high",
        "calibration": "Conformal prediction sets at 90% and 95% coverage",
        "monitoring_plan": {
            "cadence": "Monthly subgroup bias audit (Tier 1); continuous override-rate tracking via /api/governance/override-metrics.",
            "drift_detection": "Population stability index on input feature distributions; conformal set-size inflation as a coverage-drift signal.",
            "triggers": "Subgroup FNR disparate-impact ratio < 0.80, macro-F1 drop > 3 points, or sustained override (reject) rate > 20% triggers model-owner review.",
            "rollback": "Prior ensemble version is retained and hot-swappable if a shipped version regresses a subgroup FNR.",
        },
        "limitations": [
            "Not clinically validated. No prospective or retrospective evaluation against real patient outcomes has been completed.",
            "Trained on US ED data; transfer to non-US triage systems unverified",
            "Limited high-acuity peds (<2y) representation",
            "Not validated for psychiatric-only encounters",
            "On real free-text the ensemble can over-default to the modal class (ESI 3). A deterministic safety floor (services/triage_rules.py) can only raise acuity, never lower it.",
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


# --------------------------------------------------------------------------
# Provenance overlay — the triage card describes the model that is running.
# --------------------------------------------------------------------------
TRIAGE_CARD_ID = "triage_lightgbm"


def _apply_triage_provenance(card: dict[str, Any]) -> dict[str, Any]:
    """Fill the triage card's training-data claims from the loaded artifact.

    The card used to carry a hand-written block saying the ensemble trained on
    "1.2M de-identified triage encounters" and that "no synthetic or generative
    augmentation" was used. The artifact the model actually loads from records
    "Kaggle Triagegeist (80k synthetic ED encounters)". The card was wrong, and
    it was wrong in the one document written specifically to be read by people
    deciding whether to trust the model.

    Two ways to fix that. Correct the string, or remove the possibility. A
    corrected string is one retrain away from being wrong again, and nothing in
    CI would notice, because a hand-written claim has nothing to disagree with.
    So the claim is derived instead: this reads services.triage_ml.provenance(),
    which reads the artifact that predict() scores against. If the shipped model
    changes, the card changes with it, and if the two ever disagree the test in
    tests/services/test_model_card_provenance.py fails.

    The import is local. model_cards is served at /api/model-cards without auth
    and must stay importable on a container where the 340MB artifacts were never
    staged; triage_ml pulls in pandas and numpy at module scope.
    """
    try:
        from services import triage_ml

        prov = triage_ml.provenance()
        version, version_source = triage_ml.model_version()
    except Exception:  # pragma: no cover - defensive; card must still render
        prov = {"known": False, "source": "provenance_unavailable"}
        version, version_source = "unknown", "absent"

    enriched = dict(card)
    enriched["model_version_running"] = {"version": version, "derived_from": version_source}

    if not prov.get("known"):
        enriched["training_data"] = {
            "source": None,
            "status": "unknown",
            "explanation": (
                "No model artifact is loaded in this environment, so the training "
                "corpus cannot be read. This card will not assert a provenance it "
                "cannot verify. Reason: " + str(prov.get("source", "unknown"))
            ),
        }
        enriched["data_provenance"] = {
            "origin": None,
            "status": "unknown",
            "explanation": "Not asserted. No artifact loaded to read it from.",
        }
        enriched["performance"] = {
            "status": "unknown",
            "explanation": "Not asserted. No artifact loaded to read metrics from.",
        }
        enriched["synthetic_data_caveat"] = (
            "Unknown in this environment — no artifact loaded. Do not treat the "
            "absence of a caveat as an assurance that training data was real."
        )
        return enriched

    dataset = prov["dataset"]
    is_synthetic = bool(prov.get("is_synthetic"))
    metrics = prov.get("metrics", {})

    enriched["training_data"] = {
        "source": dataset,
        "label": "Triage acuity (ESI 1-5) as recorded in the source corpus",
        "read_from": "artifacts.pkl of the loaded model",
        "is_synthetic": is_synthetic,
    }
    enriched["data_provenance"] = {
        "origin": dataset,
        "lineage": (
            "Source corpus -> feature engineering (scripts/train_triage_model.py) "
            "-> 5-fold stacked ensemble training -> split-conformal calibration."
        ),
        "consent_basis": (
            "Synthetic data. No individually identifiable PHI is implicated, because "
            "no real patient contributed a record."
            if is_synthetic
            else "Secondary use of de-identified data; verify the licence permits "
            "commercial deployment before shipping a model trained on it."
        ),
        "time_range": "Retrospective; not continuously refreshed.",
        "known_gaps": "US-only; thin high-acuity peds (<2y); psychiatric-only encounters under-represented.",
        "read_from": "artifacts.pkl of the loaded model",
    }
    enriched["performance"] = {
        **metrics,
        "measured_on": dataset,
        "clinically_validated": False,
        "interpretation": (
            "These figures are the clean synthetic-data ceiling and do not estimate "
            "real-patient performance. Published ESI models on real data typically "
            "reach QWK 0.65-0.85. Treat any figure here as an upper bound that has "
            "not been earned on real patients."
            if is_synthetic
            else "Measured on the source corpus. Not a substitute for prospective "
            "clinical validation."
        ),
    }
    enriched["synthetic_data_caveat"] = (
        f"TRAINED ON SYNTHETIC DATA. The corpus is '{dataset}'. No real patient "
        "record contributed to these weights. The model is not clinically validated "
        "and must not be represented as a clinical model. A deterministic safety "
        "floor (services/triage_rules.py) can only raise acuity, never lower it."
        if is_synthetic
        else f"Training corpus is '{dataset}'; the artifact does not mark it synthetic."
    )
    return enriched


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
    enriched = _apply_triage_provenance(card) if card_id == TRIAGE_CARD_ID else dict(card)
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

    for cid, static_card in CARDS.items():
        # Read through get_card so the triage row reflects the artifact-derived
        # provenance rather than the static literal, which deliberately no longer
        # carries those attributes. Counting the literal would report the triage
        # model as disclosing fewer attributes than it does.
        card = get_card(cid) or static_card
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
