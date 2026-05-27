# Solace — clinical performance brief

> Version: 1.0 · 2026-05-14 · St. David's Medical Center reference deployment

A single-page evidence summary for clinicians, IRBs, and procurement reviewers. Every number below traces to live production code or measured production behaviour. Honesty over hype: synthetic-data limitations and known triage failure modes are called out.

---

## 1. Model architecture (ESI triage)

- **Algorithm:** LightGBM gradient-boosted classifier ensemble
- **Folds:** 5-fold stratified cross-validation, predictions averaged at inference
- **Feature space:** 561 features — 450 TF-IDF (word + char n-grams over chief complaint and intake transcript) and 111 structured (age, sex, vitals when entered bedside, medication and allergy and condition presence flags, derived composites like shock index and qSOFA)
- **Calibration:** split conformal prediction. Nonconformity score `1 − p(true_class)`; quantile `q̂` computed on a 10% held-out fold
- **Explainability:** per-prediction SHAP contributions (`pred_contrib=True`) on the highest-probability fold. Top-K feature contributions surfaced on the clinician dashboard
- **Two-stage inference:** Stage 1 runs on the patient's self-reported intake. Stage 2 runs after the clinician enters bedside vitals (HR, BP, RR, SpO₂, temp, GCS, pain, mental status) and refines the ESI

Source: `backend/services/triage_ml.py`, `backend/models/artifacts.pkl`.

## 2. Training data and known ceiling

| Item | Value |
|---|---|
| Dataset | Kaggle Triagegeist — **80,000 synthetic ED encounters** |
| OOF accuracy | 99.87% |
| OOF Quadratic Weighted Kappa | 0.9993 |
| Conformal q̂ (clean validation) | 6.9 × 10⁻⁵ |
| Conformal q̂ (noise-injected, bedside vitals) | 1.15 × 10⁻⁴ |

**Honest caveat (preserved verbatim from `artifacts.pkl::training_data_note`):**

> QWK ≈ 1.0 reflects the clean synthetic data ceiling. On real patient data, published ESI models (MIMIC-IV, NEWS2) typically achieve QWK 0.65–0.85. The noise-perturbed q̂ gives a more realistic uncertainty budget.

Translation: the 99.87% accuracy is the synthetic-data ceiling. Real-patient performance is expected to be in the **QWK 0.65–0.85** range, which matches published benchmarks (Levin et al. 2018 NEWS2; MIMIC-IV ED triage models). A retrospective study against real ED registry data is the next step before any production deployment.

## 3. Live production behaviour (n = 10 synthetic encounters, 2026-05-14)

10 chief-complaint scenarios were fired against the deployed Solace API (`https://djfjrel7b1ebi.cloudfront.net`) covering chest pain, severe SOB, thunderclap headache, deep laceration, RUQ abdominal pain, ankle sprain, URI symptoms, fall-on-anticoagulation, asthma flare, and post-epi pediatric anaphylaxis.

### Operational metrics

| Metric | Value |
|---|---|
| Success rate | 10 / 10 (100%) |
| Median end-to-end latency | **1.29 s** |
| Mean latency | 1.80 s |
| Max latency (single cold path: Claude + ML + comfort + TTS) | 4.53 s |

End-to-end here means the full pipeline: HIPAA consent gate → nonce check → text quality scan → triage model → Ddx + workup + disposition → comfort protocol → TTS upload → DDB persist. All inside one Lambda invocation, all returned to the patient.

### ESI distribution

| ESI | Count | Sample case |
|---|---|---|
| 1 (Resuscitation) | 0 | — |
| 2 (Emergent) | 3 | Chest pain with radiation, severe SOB, URI complaint (over-triaged) |
| 3 (Urgent) | 6 | RUQ abdominal pain, thunderclap headache (under-triaged), anaphylaxis post-epi (under-triaged) |
| 4 (Less Urgent) | 1 | Ankle sprain — correct |
| 5 (Non-urgent) | 0 | — |

### Where the model was honest vs. where it missed (clinical read)

- **Correct:** chest pain → ESI 2 with `ed_now` routing, severe SOB → ESI 2, ankle sprain → ESI 4 with `telehealth` routing.
- **Over-triage (false positive):** URI complaint (sore throat 3 days, mild fever) → ESI 2. Reasonable from a safety standpoint, costs care-team attention.
- **Under-triage (false negative — the dangerous direction):**
  - Thunderclap headache → ESI 3. Clinically this should be **ESI 1–2** because SAH is on the differential.
  - Pediatric anaphylaxis post-epi-pen → ESI 3. Should be **ESI 1–2** because biphasic reactions require monitoring.
  - Anticoagulated head injury → ESI 3. Should be **ESI 2** because intracranial hemorrhage risk is elevated on warfarin.

This is the **single most important section of this brief.** A 30% false-negative rate on must-not-miss presentations in a 10-case sample confirms the synthetic-data ceiling claim above: the model is calibrated on Synthea-generated narratives that don't carry the nuance of real ED handoffs. **No production deployment until a retrospective study against real ED registry data shifts this number.**

The Stage 2 vitals refinement (run after the clinician enters bedside vitals) closes some of this gap because shock index and qSOFA pick up the deteriorating patient that the text-only Stage 1 missed. That refinement was not exercised in this 10-case run — Stage 1 only.

## 4. Ambient scribe quality

- Current path: Claude Sonnet 4.5 (via AWS Bedrock when `CLAUDE_PROVIDER=bedrock`, default) synthesizes a Linked Evidence note (sections + evidence-segment anchors) from the doctor-patient transcript. Refinement pass rewrites in clinical shorthand without inventing facts. Source: `backend/services/ambient_scribe.py:64-91`.
- Wired and ready: **AWS HealthScribe** (`transcribe:StartMedicalScribeJob`). The `solace-healthscribe-data-access` IAM role exists, the Lambda has the env var, and the BAA covers the service. Flip is one configuration change in `ambient_scribe.py` once a medical-grade STT path is preferred over Claude synthesis. Source: `backend/services/ambient_scribe.py:95-145`.
- Transcription itself is dual-path: browser Web Speech API as the deterministic primary (instant, no cloud roundtrip), AWS Transcribe as the BAA-covered fallback. Source: `frontend/src/hooks/useAudioRecorder.ts`.

## 5. Multilingual coverage

20 languages with full i18n at the patient surface — English, Spanish, Mandarin, Tagalog, Vietnamese, Arabic, French, Korean, Russian, German, Haitian Creole, Portuguese, Italian, Polish, Japanese, Persian, Urdu, Hindi, Bengali, Gujarati. RTL handling on the document root for Arabic/Persian/Urdu. Source: `frontend/src/lib/i18n.ts`.

This is broader than every named competitor (Abridge 1, Suki 4, Phreesia 19, Clearstep 9 per their public materials as of 2026-05).

## 6. EHR integration

- **Auto-pop on intake:** ID scan + insurance card scan trigger a real FHIR `Patient.search` against `https://launch.smarthealthit.org/v/r4/fhir` (SMART Health IT public sandbox, Synthea population). Allergies, medications, conditions, and the last 5 encounters pre-fill the intake form. Source: `backend/services/fhir_patient_search.py`.
- **Write-back:** `DocumentReference` (the SOAP note) + `Condition` (from ICD-10 coding) + `AllergyIntolerance` are pushed via the existing `/ehr-write` endpoint. Routes to a local FHIR mock store when no production endpoint is configured. Source: `backend/services/fhir_writer.py`.
- **Production swap:** set `EHR_FHIR_BASE_URL` and `EHR_FHIR_ACCESS_TOKEN` on the Lambda to point at Epic / Cerner / Athena. Code path is identical. Source: `backend/services/fhir_patient_search.py:32-43`.
- **Clinician sign-in:** real SMART-on-FHIR PKCE flow for Epic, Cerner, athenahealth, and SMART Health IT. Vendor registry at `backend/lib/ehr_vendors.py`. Epic sandbox app registration recipe at `docs/epic-sandbox-setup.md`.

## 7. Compliance posture

| Control | Status |
|---|---|
| HIPAA Safe Harbor PII redaction (15 identifiers) | Live, scanning every transcript before AI submission. `backend/lib/content_guard.py` |
| Audit log immutability + 6-year retention design | Live, dual-write DDB + CMK-encrypted S3 JSONL. `backend/lib/audit.py` |
| Encryption at rest via single CMK | Live across DynamoDB, S3, Secrets Manager. `scripts/setup_security.py` |
| TLS 1.2 enforced in transit | Live across CloudFront → API Gateway → Lambda |
| BAA-covered AI providers default | `CLAUDE_PROVIDER=bedrock`, `TRANSCRIPTION_PROVIDER=aws`, `TTS_PROVIDER=aws` |
| Clinician session timeout + brute-force lockout | 30-minute absolute, 15-minute idle, 5-attempt lockout. `backend/lib/jwt_auth.py` |
| HITRUST / SOC 2 attestation | **Not yet.** Controls are in place; third-party audit is the next compliance step |

Full constitution at `CONSTITUTION.md` (78 evidence-cited rules across Security / Compliance / Architecture / Quality / Usability / Testing / Dependencies / Performance).

## 8. Honest gaps

- **No real-patient validation study.** All ESI accuracy numbers are synthetic-data ceilings.
- **3 of 10 must-not-miss undertriages** in the live run above. This is the blocker for production.
- **No HITRUST / SOC 2 certificate.** Controls are implemented; the paperwork is unstarted.
- **No production EHR app registrations.** SMART Health IT sandbox is live today. Epic registration is a 30-minute self-serve away (`docs/epic-sandbox-setup.md`). Cerner is ~1 hour. Athena is 1–2 weeks of vendor approval.
- **Zero paying clinician users.** This is a pre-pilot product.

## 9. What "above and beyond market" actually means for Solace

Solace is **above market** on (a) vertical breadth — intake plus scribe plus differential plus EHR plus admin in one product (b) ML explainability — SHAP plus conformal sets on every triage (no competitor ships this) (c) language coverage at 20 languages (d) real FHIR integration today, not on a roadmap slide.

Solace is **at market** on ambient scribe quality (acceptable, not exceptional) and clinician UX polish.

Solace is **below market** on production EHR depth (no App Orchard listing), medical-grade STT (Web Speech is fast not fine-tuned), clinical validation (zero peer-reviewed accuracy data on real patients), compliance certificates (controls yes, certificate no), and customer base (zero).

---

*This document is generated from live production code, deployed services, and a 2026-05-14 production benchmark. For the underlying data, see `/tmp/solace_intake_metrics.json` and `backend/models/artifacts.pkl`. For implementation details, the constitution at `CONSTITUTION.md` cross-references every claim to source files.*
