# Solace

**AI-assisted ER triage. You're not waiting alone.**

Submitted to **[HackFW](https://fwtx.devpost.com)** — Fort Worth's convergent technology hackathon. Built in ~72 hours.

A patient scans the QR on the waiting-room kiosk, speaks their symptoms in any language, and optionally snaps a photo of their injury or insurance card. Within ~7 seconds they hear a warm voice explain their ESI triage level and what to do while they wait. On the other side of the ED, the clinician opens their terminal and sees a full AI-generated pre-brief for every waiting patient — provisional ESI, SHAP explanation, clinician pre-brief, AI scribe draft, EHR match — before the patient is even roomed.

When vitals are taken at bedside, a LightGBM 5-fold ensemble refines the ESI with real numeric signal + conformal prediction intervals.

---

## North Texas Impact

Fort Worth's emergency departments face two compounding problems:

- **JPS Health Network** (the county safety-net hospital) handles one of the highest Medicaid + uninsured patient volumes in Texas — patients who often lack established care and arrive sicker
- **~38% of Tarrant County residents** speak a language other than English at home; Spanish-speaking patients frequently can't communicate symptoms clearly during intake, leading to under-triage
- **Baylor Scott & White** and **Texas Health Resources** serve the broader DFW metro with ED wait times consistently above the national average during peak hours

Solace directly targets all three: multilingual voice intake (Whisper + ElevenLabs in any language), AI pre-briefs that compress clinician catch-up time, and a two-stage ESI model that improves triage accuracy when handoff information is thin. The system is deployable on existing hospital Wi-Fi — patients need only a smartphone and a QR code at the door.

- **Live frontend:** https://solace.d2gsbjipp9quan.amplifyapp.com
- **Patient intake:** `/demo/patient` (QR-scan target)
- **Clinician dashboard:** `/demo/clinician`

---

## What makes it different

1. **Two-stage inference.** Claude handles the narrative triage on intake (text, pre-brief, comfort protocol). LightGBM + SHAP refines the ESI once bedside vitals land. Provisional ESI gets the queue moving; refined ESI locks in the acuity.
2. **Real SHAP + conformal prediction.** Not heuristic weights — `pred_contrib=True` feature attributions and split-conformal 90%-coverage prediction sets straight off a 5-fold ensemble trained on the Kaggle Triageist dataset.
3. **HIPAA-aware by construction.** §164.508 consent gate, §164.514 minimum-necessary payloads, §164.312 technical safeguards (TLS 1.2+, CMK-encrypted storage across 11 DynamoDB tables + S3 + Secrets Manager, audit trail, per-call AI-attribution logs stored on every patient record for Bedrock migration).
4. **FHIR-shape EHR integration.** Auto-matches a patient by name on intake and merges allergies, meds, conditions, family history, prior visits into the clinician view — before rooming.
5. **Adaptive intake form.** Pregnancy questions only appear for female patients aged 12-55. Diabetes type follow-up. NYHA class for heart failure. Severity per allergy. Skip-logic built in.
6. **Voice in, voice out.** OpenAI Whisper transcribes (any language), ElevenLabs multilingual TTS delivers the plan in the patient's own language.
7. **Real adversarial abuse prevention.** IP+UA-bound intake nonces, identity-keyed rate limits, content safety guard on text uploads, multi-layer abuse-event audit + auto-blocklist, CMK-encrypted at rest on everything.

---

## Architecture

```
Patient phone ─► QR /demo/patient ─► Vite+React SPA
                                  │
                                  │ WAFv2 → CloudFront → API GW (HTTP)
                                  ▼
                            FastAPI on Lambda
                            (container, arm64, Python 3.12)
                    ┌───────────┼────────────┬─────────────┐
                    ▼           ▼            ▼             ▼
              OpenAI Whisper   Claude 4.5   ElevenLabs   LightGBM
              (transcribe)    (pre-brief,  (empathetic   5-fold
                               scribe,     TTS)          ensemble
                               comfort,                  + SHAP
                               photo vision,             + conformal
                               insurance                 prediction
                               OCR)
                    │           │            │             │
                    └─────┬─────┴────────────┴─────────────┘
                          ▼
                    DynamoDB (11 tables, CMK)
                    S3 media (24h lifecycle, CMK)
                    Audit log + SNS alerts
```

### Stack

| Layer | Tech |
|---|---|
| Frontend | Vite + React 18 + TypeScript + Tailwind + Framer Motion |
| Backend | FastAPI + Mangum (Lambda adapter), Python 3.12 |
| Runtime | AWS Lambda container image (ECR, arm64) behind API Gateway HTTP API |
| CDN / WAF | CloudFront + WAFv2 (IP reputation, Known Bad Inputs, OWASP common, rate-based limit) |
| Storage | DynamoDB (11 tables, all CMK-encrypted, PAY_PER_REQUEST, TTLs set) |
| Media | S3 (CMK, 24h lifecycle, TLS-only, public access blocked) |
| Secrets | Secrets Manager (CMK-encrypted, JWT key + API keys + demo PINs) |
| Observability | CloudWatch + CloudTrail + SNS alerts + EventBridge |
| Deploy | Amplify Hosting (frontend) + deploy script (Lambda container) |
| AI providers | OpenAI Whisper + Anthropic Claude Sonnet 4.5 + ElevenLabs `eleven_multilingual_v2` |
| ML | LightGBM 5-fold ensemble, SHAP via `pred_contrib=True`, split-conformal 90% coverage |
| Video demo | Remotion (`/demo`) |

### Repo layout

```
solace/
├── backend/                 FastAPI + Mangum
│   ├── main.py              Lambda handler (handler = Mangum(app))
│   ├── routers/             intake, ehr, clinician, patients, refine, public, ...
│   ├── services/            Whisper, Claude, ElevenLabs, triage, scribe, ...
│   ├── lib/                 auth, audit, quota, blocklist, intake_nonce,
│   │                        claude (provider adapter), ai_log, content_guard, ...
│   ├── db/                  DynamoDB storage layer
│   └── models/              LightGBM fold files + artifacts (gitignored)
├── frontend/
│   └── src/
│       ├── pages/           PatientIntake, PatientResult, ClinicianDashboard
│       ├── components/      patient/*, clinician/* (EHRPanel, VitalsPanel, ...)
│       ├── hooks/           usePollingPatients, useVoiceRecorder, ...
│       └── lib/             api client, constants, runtime-config
├── scripts/                 AWS setup + deploy (deploy_container.py,
│                            deploy_amplify.py, setup_*.py, rotate_pins.py)
├── demo/                    Remotion composition for the hackathon video
│   └── src/Solace.tsx       Motion-graphics timeline (~86s @ 30fps)
├── Dockerfile.lambda        arm64 container image
└── requirements-lambda.txt  Lambda-slim dependency set
```

---

## Local development

No AWS required. Backend runs against real AI APIs with in-memory storage; media served from `backend/tmp/media/`.

### Prereqs

- Python 3.11 or 3.12
- Node 20+
- Docker (only needed to deploy Lambda, not for local dev)
- OpenAI + Anthropic + ElevenLabs API keys

### Setup

```bash
# 1. Environment
cp .env.example .env
# Edit .env with your API keys + SOLACE_MODE=local

# 2. Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

- Backend: http://localhost:8000
- Frontend: http://localhost:5173
- Patient intake: http://localhost:5173/demo/patient
- Clinician dashboard: http://localhost:5173/demo/clinician (PIN `123456` in local mode)

### Health check

```bash
curl http://localhost:8000/health
# {"status":"ok","mode":"local","services":{"openai":true,"anthropic":true,"elevenlabs":true,"triage":true}}
```

`"triage":true` requires the LightGBM fold files in `backend/models/`. They're gitignored (~340 MB). Rehydrate by re-running the Triageist training notebook or copying them from S3 — paths are the standard `lgbm_fold{0..4}.txt` + `artifacts.pkl`.

### Provider swap

`CLAUDE_PROVIDER=anthropic` (default) uses the direct Anthropic API.
`CLAUDE_PROVIDER=bedrock` routes through AWS Bedrock using the same shape-compatible adapter — flip the env var, no code changes. Used for the HIPAA BAA migration path.

---

## Live deployment

### URLs

| What | Where |
|---|---|
| Frontend (Amplify) | https://solace.d2gsbjipp9quan.amplifyapp.com |
| API (CloudFront + WAF + API GW + Lambda) | https://djfjrel7b1ebi.cloudfront.net |
| API direct (no WAF, debug only) | https://7ew5f2x01d.execute-api.us-east-1.amazonaws.com |

### Redeploy

```bash
# Backend
docker build -f Dockerfile.lambda -t solace-lambda:latest --platform linux/arm64 .
source backend/.venv/bin/activate
python scripts/deploy_container.py          # push to ECR, update Lambda, smoke-test

# Frontend
cd frontend && npm run build
cd .. && source backend/.venv/bin/activate
python scripts/deploy_amplify.py            # zip → Amplify deployment job
```

`deploy_container.py` pushes the image to ECR, updates the Lambda to the new digest, re-points API Gateway + EventBridge warmer, and runs an end-to-end smoke test — it **fails the deploy** if `ml_ok=False`.

### Full infra bootstrap (idempotent)

```bash
python scripts/setup_aws.py                  # DDB tables + S3 bucket
python scripts/setup_security.py             # CMK, Secrets Manager, CloudTrail, PITR
python scripts/setup_clinician_auth.py       # clinicians + audit log + demo PINs
python scripts/setup_abuse_prevention.py     # intake-nonces + API GW throttle
python scripts/setup_waf_cloudfront.py       # WAFv2 + CloudFront distribution
python scripts/setup_security_alerts.py dhruvhydrox@gmail.com
python scripts/setup_cloudwatch_alarms.py
python scripts/setup_amplify_headers.py      # CSP/HSTS/etc
python scripts/setup_ehr.py                  # seed 7 FHIR-shape EHR records
```

---

## Security posture

Every live control is documented in `scripts/setup_security.py`, but the short list:

- **Encryption**: one customer-managed KMS key for all Solace data — every DynamoDB table, every S3 bucket, every Secrets Manager secret uses it
- **TLS**: 1.2+ enforced at CloudFront, API GW, and S3 bucket policy; HSTS via Amplify custom headers
- **Auth**: JWT HS256 (key in Secrets Manager), bcrypt PINs for clinicians, rotation script
- **Abuse prevention**: IP+UA-bound intake nonces (4h TTL) atomically consumed per submit; identity-keyed rate limits; content-safety guard on text uploads; multi-layer abuse-event audit with auto-blocklist (30m cooldown)
- **CloudTrail**: management events + S3 data events to a separate bucket (read-only to most principals)
- **SNS alerts**: security events → `dhruvhydrox@gmail.com` via EventBridge
- **CloudWatch alarms**: 13 alarms on Lambda error rate, throttle count, 5xx rate, throughput, duration p99, cold starts, DDB throttles, WAF blocks
- **HIPAA**: §164.508 consent logged on every intake (version + granted-at), §164.514 minimum-necessary scrubbing on AI prompts, §164.312 technical safeguards via all of the above; **AI attribution log** (provider + model + input-tokens + output-tokens + duration) persisted on every patient record

Known gaps: Bedrock Claude migration (env-var flip, pending AWS BAA + model access), GuardDuty not enabled, MFA permission boundary drafted not applied.

---

## Teaching the model

The LightGBM ensemble was trained on the Kaggle Triageist dataset (chief complaints + patient history + vitals → ESI 1-5), with:

- 5-fold stratified CV
- Class-balanced sample weights
- Conformal-split calibration on noise-perturbed vitals (90% coverage)
- Feature engineering: shock_index, keyword-text features (`kw_stroke`, `kw_seizure`, `kw_mi`, `kw_sepsis`, ...), arrival-hour cyclic encoding, vitals normalization

Training data + notebook live in the sibling `triagegeist/` repo. Model files (`lgbm_fold{0..4}.txt`, `artifacts.pkl`) are dropped into `backend/models/` for inference.

---

## Team

| Role | Owner |
|---|---|
| Cloud / Infra / Backend / ML | Dhruv Jain |
| Frontend / UX / Product | Sriyan Bodla |

Built in ~72 hours. Originally prototyped at Hook'em Hacks 2026 @ UT Austin; submitted to HackFW 2026 for North Texas deployment.

---

## License

MIT — see `LICENSE`.
