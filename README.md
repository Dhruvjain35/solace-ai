# Solace

**AI-native patient intake and clinical triage for emergency departments.**

[![Watch the Solace demo](https://img.youtube.com/vi/hXsBIY23V2c/hqdefault.jpg)](https://www.youtube.com/watch?v=vFjxtGklkCo)

### ▶️ See it live

| | |
|---|---|
| 🏥 **Product app — judges start here** | **[solaceaidemo.vercel.app/showcase](https://solaceaidemo.vercel.app/showcase)** — auto-signs in, split-screen patient + clinician view |
| 📹 **2-min walkthrough** | **[▶️ Watch the demo on YouTube](https://www.youtube.com/watch?v=vFjxtGklkCo)** |
| 🌐 **Marketing site** | **[mysolaceclinic.com](https://mysolaceclinic.com)** |
| 🔌 **Live API health** | [`/health`](https://7ew5f2x01d.execute-api.us-east-1.amazonaws.com/health) → `{"status":"ok","mode":"aws","triage":"trained_ensemble"}` — the real 4-model ML ensemble is running in production, not a stub |

> Manual clinician sign-in (only if you skip `/showcase`): **Dr. Chen · PIN 224466**.

### Screenshots

| Clinician terminal — provisional ESI + AI pre-brief | Live patient queue |
|---|---|
| ![Clinician terminal](landing/public/assets/shots/terminal.png) | ![Live queue](landing/public/assets/shots/queue.png) |

| EHR auto-match | Multilingual voice intake | AI care plan |
|---|---|---|
| ![EHR pull](landing/public/assets/shots/ehr-clean.png) | ![Voice intake](landing/public/assets/shots/voice.png) | ![Care plan](landing/public/assets/shots/plan.png) |

---

> **Repo layout** — three independent pieces:
> | Folder | What | Where it runs |
> |---|---|---|
> | `landing/` | Marketing site ([live](https://mysolaceclinic.com)) | Vercel, auto-deploys from `main` (see `landing/README.md`) |
> | `frontend/` | The product app (patient intake + Atlas clinician terminal) | solaceaidemo.vercel.app |
> | `backend/` | FastAPI on AWS Lambda | AWS |

Solace eliminates the dead time between a patient walking through the ED door and a clinician knowing what they need. A patient scans a QR code, speaks their symptoms in any language, and optionally photographs their injury or insurance card. Within seconds they hear a warm voice explain their triage level and what to expect while they wait. On the other side of the department, the clinician already has a full AI-generated pre-brief — provisional ESI level, SHAP attribution, clinical scribe draft, EHR pull — before the patient is roomed.

---

## The problem

Emergency departments lose significant time on the front end of every patient encounter:

- **Registration and intake** pull nursing time away from clinical work
- **Language barriers** cause under-triage for non-English speakers — 1 in 5 ED visits in major metros involves a patient with limited English proficiency
- **Clinician handoff** requires flipping through paper intake forms or navigating multiple EHR screens before seeing the patient
- **Repeat data entry** — patients re-enter the same information that already exists in the EHR

Solace addresses all four simultaneously, with a system that runs on existing hospital Wi-Fi and requires nothing from the patient except a smartphone.

---

## How it works

### Patient side

1. Patient scans a QR code posted at the waiting room entrance
2. A voice-guided intake begins in their language — no app download, no account
3. They describe symptoms in their own words; optionally photograph injury or insurance card
4. Within ~7 seconds they receive spoken triage guidance and comfort instructions in their language
5. They can tap a button anytime if their pain worsens — the clinician dashboard alarms immediately

### Clinician side

1. Dashboard auto-refreshes with every new patient arrival
2. Each card shows provisional ESI level, chief complaint, AI-generated pre-brief, SHAP explanation, and matched EHR data
3. Vitals entered at bedside trigger a LightGBM ensemble refinement — the ESI updates in real time with conformal prediction intervals
4. One-click AI scribe draft, prescription suggestions, and patient education letter

### Voice agent (phone)

Patients who can't access the QR intake can call the hospital's Twilio number. Solace's voice agent handles triage questions, appointment booking, FAQ, and emergency escalation — automatically transferring to a human or advising 911 when needed.

---

## Features

| Capability | Detail |
|---|---|
| **Multilingual voice intake** | Whisper STT + Polly TTS in 20+ languages — patient speaks, Solace responds |
| **Two-stage triage** | Claude handles narrative ESI on intake; a 4-model stacked ensemble (LightGBM + XGBoost + CatBoost + MLP) refines with bedside vitals |
| **SHAP explanations** | Per-patient feature attributions from `pred_contrib=True` — clinicians see *why* the model scored what it did |
| **Conformal prediction** | Split-conformal 90%-coverage prediction sets on every refined ESI — the model tells you when it's uncertain |
| **EHR auto-match** | Matches patient by name + insurance member ID; merges allergies, meds, conditions, prior visits into clinician view before rooming |
| **Insurance OCR** | Claude Vision extracts member ID, group, payer, and coverage type from a phone photo of the insurance card |
| **Pain escalation** | Patient-side button re-arms clinician alarm; concurrent acknowledgements handled gracefully |
| **Inbound voice agent** | Full phone receptionist — triage, scheduling, FAQ, 911 escalation |
| **Self-scheduling** | Patients book appointments from the portal; confirmation by SMS |
| **Workflow automation** | Keragon-style trigger/action engine — e.g. "when ESI ≤ 2, Slack the charge nurse" |
| **SMART-on-FHIR sign-in** | Clinicians authenticate via Epic, Cerner, or Athena OAuth + PKCE |
| **AI scribe** | Structured SOAP-lite note drafted from intake transcript — one click to edit and sign |
| **Patient education** | Discharge letter generated in patient's language, readable via QR |

---

## Architecture

```
Patient phone ─► QR /patient ──► Vite + React SPA
                                        │
                               CloudFront + WAFv2
                                        │
                                 API Gateway (HTTP)
                                        │
                              FastAPI on AWS Lambda
                              (container, arm64, Python 3.12)
                   ┌──────────────┬──────────────┬───────────────┐
                   ▼              ▼              ▼               ▼
             AWS Transcribe   AWS Bedrock    AWS Polly      Stacked ML
             (STT, BAA)       (Claude 4.5,   (TTS, BAA)     (LGBM+XGB+CAT
                              BAA)                          +MLP) + SHAP
                                                            + conformal
                   └──────────────┴──────────────┴───────────────┘
                                        │
                          DynamoDB (all tables CMK-encrypted)
                          S3 (media + 6-year audit archive, CMK)
                          Secrets Manager (CMK)
```

All AI inference routes through AWS-managed services covered under the **AWS Business Associate Agreement** — no separate vendor BAAs required.

### Stack

| Layer | Technology |
|---|---|
| Frontend | Vite + React 18 + TypeScript + Tailwind + Framer Motion |
| Backend | FastAPI + Mangum, Python 3.12 |
| Runtime | AWS Lambda container image (ECR, arm64) + API Gateway HTTP API |
| CDN / Security | CloudFront + WAFv2 (IP reputation, OWASP common, Known Bad Inputs, rate-based) |
| Storage | DynamoDB (PAY_PER_REQUEST, CMK-encrypted, TTL on all transient tables) |
| Media | S3 (CMK, TLS-only, public access blocked, presigned URLs for delivery) |
| Secrets | AWS Secrets Manager (CMK-encrypted — JWT key, API keys, bcrypt PINs) |
| Observability | CloudWatch (13 alarms) + CloudTrail + SNS + EventBridge |
| AI — inference | AWS Bedrock (Claude Sonnet 4.5) |
| AI — STT | AWS Transcribe (primary) / OpenAI Whisper (fallback) |
| AI — TTS | AWS Polly Neural (primary) / ElevenLabs (fallback) |
| AI — vision | Claude Vision via Bedrock (injury photos, insurance OCR) |
| ML | 4-model stacked ensemble (LightGBM + XGBoost + CatBoost + MLP), 5-fold CV, logistic-regression meta-learner, ordinal threshold optimization, split-conformal calibration, SHAP via `pred_contrib` |
| Auth | JWT HS256 + bcrypt + SMART-on-FHIR PKCE |
| Phone | Twilio Voice + inbound voice agent |

### Repository layout

```
solace/
├── backend/
│   ├── main.py                  Lambda handler (Mangum adapter)
│   ├── routers/                 intake, ehr, clinician, patients, auth,
│   │                            appointments, voice, pain_flag, workflows, ...
│   ├── services/
│   │   ├── triage.py            Two-stage ESI engine
│   │   ├── transcription.py     AWS Transcribe / Whisper adapter
│   │   ├── tts.py               AWS Polly / ElevenLabs adapter
│   │   ├── scheduling.py        Appointment availability + booking
│   │   ├── workflows/           Trigger/action engine
│   │   └── voice_agent/         Inbound phone agent (intents, session, TTS cache)
│   ├── lib/
│   │   ├── claude.py            Bedrock / Anthropic adapter
│   │   ├── auth.py              JWT Bearer — no legacy PIN
│   │   ├── jwt_auth.py          Brute-force lockout (5 failures → 30-min lock)
│   │   ├── content_guard.py     Prompt injection + 15-pattern PHI redaction
│   │   ├── audit.py             Dual-write audit (DDB 90d + S3 6yr)
│   │   ├── quota.py             Identity-keyed rate limiting
│   │   └── blocklist.py         Auto-blocklist (5 abuse events → 1hr block)
│   └── db/                      DynamoDB storage layer
├── frontend/
│   └── src/
│       ├── pages/               PatientIntake, PatientResult, ClinicianDashboard,
│       │                        VoiceSimulator, EHRCallback, Appointments
│       ├── components/
│       │   ├── clinician/       PainAlarm, VitalsPanel, EHRPanel, NotesPanel,
│       │   │                    PrescriptionPanel, WorkflowEditor, ...
│       │   └── patient/         MicButton, PhotoCapture, InsuranceScanner, ...
│       └── lib/                 api client, session management
└── scripts/                     Idempotent AWS provisioning scripts
    ├── setup_aws.py             DDB tables + S3 (all CMK-encrypted)
    ├── setup_security.py        CMK alias, Secrets Manager, CloudTrail
    ├── setup_clinician_auth.py  Clinician table + audit log + bcrypt PINs
    ├── setup_abuse_prevention.py  Nonce/quota/blocklist/idempotency tables
    ├── setup_waf_cloudfront.py  WAFv2 + CloudFront distribution
    └── setup_cloudwatch_alarms.py  13 production alarms
```

---

## Security and HIPAA compliance

Solace is built HIPAA-compliant by construction, not as an afterthought. Every control is implemented in code and provisioned via reproducible scripts.

### Technical safeguards (45 CFR §164.312)

| Control | Implementation |
|---|---|
| **Encryption at rest** | One CMK (`alias/solace`) across all DynamoDB tables, S3 buckets, and Secrets Manager — no AWS-managed key fallbacks |
| **Encryption in transit** | TLS 1.2+ enforced at CloudFront, API Gateway, and S3 bucket policy |
| **Access control** | JWT HS256 Bearer tokens; bcrypt PINs in Secrets Manager; SMART-on-FHIR PKCE for EHR sign-in |
| **Brute-force protection** | 5 failed logins in 15 min → 30-min lockout, enforced atomically via DynamoDB |
| **Audit controls** | Every action written to `solace-audit-log`; 90-day hot storage (DDB) + 6-year cold archive (S3, CMK) per §164.530(j)(2) |
| **AI attribution log** | Provider + model + token counts persisted on every patient record for complete inference audit trail |

### PHI handling (45 CFR §164.514)

All transcripts pass through a content guard before any AI provider call. Fifteen Safe Harbor identifiers are redacted:

SSN · credit card · phone · email · date of birth · street address · ZIP · MRN · insurance member ID · account number · driver's license · VIN · device ID · URL · IP address

### Authorization (45 CFR §164.508)

Explicit consent is required before any PHI flows to an AI provider. Consent version and granted-at timestamp are persisted on every patient record. Requests without consent return HTTP 403.

### Abuse prevention

- IP+UA-bound one-time intake nonces — atomic consumption prevents replay
- Identity-keyed rate limiting (HMAC-SHA256 of IP + User-Agent) tracked with atomic DynamoDB counters
- 5 abuse events in 10 minutes → 1-hour blocklist, enforced with `ConsistentRead=True` on every patient-facing endpoint
- Prompt injection scanning on all text inputs before Claude
- Voice simulator and pain flag endpoints: blocklist + rate limiting + content guard

### EHR OAuth

- Redirect URI validated against explicit allowlist — no open redirects
- OAuth CSRF state stored in DynamoDB (survives Lambda cold starts, multi-container deployments)
- PKCE S256 challenge/verifier on every authorization request
- JWT never passed in redirect URL — one-time handoff code exchanged via POST

---

## Local development

No AWS account required. The backend runs with in-memory storage and falls back to the direct Anthropic and OpenAI APIs.

### Prerequisites

- Python 3.11+
- Node 20+
- Anthropic API key (for Claude)
- OpenAI API key (for Whisper fallback — optional if using AWS)

### Setup

```bash
# 1. Clone and configure
git clone https://github.com/Dhruvjain35/solace-ai.git
cd solace-ai
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and OPENAI_API_KEY; leave SOLACE_MODE=local

# 2. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

| URL | What |
|---|---|
| http://localhost:5173/demo/patient | Patient intake (QR target) |
| http://localhost:5173/demo/clinician | Clinician dashboard |
| http://localhost:8000/health | API health check |

### Switching AI providers

| Variable | Options | Default |
|---|---|---|
| `CLAUDE_PROVIDER` | `bedrock` \| `anthropic` | `bedrock` |
| `TRANSCRIPTION_PROVIDER` | `aws` \| `openai` | `aws` |
| `TTS_PROVIDER` | `aws` \| `elevenlabs` | `aws` |

All three default to AWS BAA-covered services in production. Set to the direct API paths for local development without AWS credentials.

### Triage model

The acuity model is a **4-model stacked ensemble** — LightGBM + XGBoost + CatBoost + MLP, each trained with 5-fold stratified CV, stacked through a logistic-regression meta-learner, with ordinal threshold optimization (differential evolution + Nelder-Mead) and **split-conformal calibration** (90% coverage, with a separate noise-perturbed q-hat for robustness). Per-patient explanations come from LightGBM `pred_contrib` (SHAP). Feature engineering includes shock index, qSOFA/SIRS composites, keyword features (`kw_stroke`, `kw_seizure`, `kw_mi`, `kw_sepsis`), arrival-hour cyclic encoding, and vitals normalization — kept in sync between training (`scripts/train_triage_model.py`) and inference (`backend/services/triage_ml.py`).

**The trained ensemble is live in production.** Hitting the deployed [`/health`](https://7ew5f2x01d.execute-api.us-east-1.amazonaws.com/health) returns `"triage": "trained_ensemble"` — the real models are loaded and serving. The artifacts (`lgbm_fold{0..4}.txt` + `artifacts.pkl`, ~340 MB) are hosted in S3 (`SOLACE_MODELS_BUCKET`) rather than committed to git due to size. To reproduce locally, obtain the Kaggle Triageist dataset and run `scripts/train_triage_model.py`; without artifacts the backend falls back to a deterministic clinical-heuristic simulation and `/health` reports `"clinical_simulation"`.

> **Demo vs production AI path.** The public demo deployment runs the direct Anthropic API on Claude Haiku (fast + low-cost) with full PHI redaction via the content guard. The HIPAA-by-construction path described in `SECURITY.md` (AWS Bedrock + Claude Sonnet under the AWS BAA) is one environment flag away (`CLAUDE_PROVIDER=bedrock`) and is what a real covered-entity deployment would use.

> **Honesty note on accuracy.** Reported model metrics are a *synthetic-data ceiling* — the ensemble is trained on the Kaggle Triageist dataset (~80k **synthetic** ED encounters), not real clinical records, and is **not clinically validated**. On real free-text the ML can over-default to the modal class (ESI 3); this is mitigated by a deterministic safety floor (`backend/services/triage_rules.py`) that can only *raise* acuity, never lower it. See `docs/clinical-performance-brief.md` for the full breakdown.

---

## Deployment

### Infrastructure provisioning (run once, idempotent)

```bash
python scripts/setup_security.py             # KMS CMK, Secrets Manager, CloudTrail
python scripts/setup_aws.py                  # DynamoDB tables + S3 (all CMK-encrypted)
python scripts/setup_clinician_auth.py       # Clinician auth table + bcrypt PINs
python scripts/setup_abuse_prevention.py     # Nonce, quota, blocklist, idempotency tables
python scripts/setup_waf_cloudfront.py       # WAFv2 + CloudFront distribution
python scripts/setup_security_alerts.py your@email.com
python scripts/setup_cloudwatch_alarms.py
```

### Deploy

```bash
# Backend (Lambda container)
docker build -f Dockerfile.lambda -t solace-lambda:latest --platform linux/arm64 .
python scripts/deploy_container.py   # ECR push → Lambda update → smoke test

# Frontend
cd frontend && npm run build
python scripts/deploy_amplify.py     # zip → Amplify deployment job
```

---

## Integrations

| System | How |
|---|---|
| **Epic / Cerner / Athena** | SMART-on-FHIR PKCE OAuth — clinicians sign in with their EHR credentials |
| **Twilio Voice** | Inbound phone line → voice agent for triage, scheduling, FAQ |
| **Twilio SMS** | Appointment confirmations and discharge instructions to patient phone |
| **AWS Bedrock** | Claude Sonnet 4.5 for triage, scribe, pre-brief, comfort, vision |
| **AWS Transcribe** | HIPAA-eligible STT — all audio stays inside the AWS BAA perimeter |
| **AWS Polly** | Neural TTS in 20+ languages — no ElevenLabs account required |

---

## Team

| | |
|---|---|
| **Dhruv Jain** | Backend · Cloud / Infra · ML · HIPAA |
| **Sriyan Bodla** | Frontend · UX · Product |

---

## License

MIT — see `LICENSE`.
