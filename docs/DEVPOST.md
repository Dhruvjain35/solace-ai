# Solace — Devpost submission copy

> Paste these into the Devpost form. Theme: **Healthcare & HealthTech** (secondary: AI/ML).
> Demo video: https://youtu.be/hXsBIY23V2c

---

## Tagline (one line)
AI-native patient intake and clinical triage that turns the dead time in an ER waiting room into a calm, multilingual, explainable workflow — for patients and clinicians.

## Links
- **Live product (start here):** https://solaceaidemo.vercel.app/showcase  (auto-signs in, split-screen patient + clinician)
- **Marketing site:** https://mysolaceclinic.com
- **GitHub:** https://github.com/Dhruvjain35/solace-ai
- **Demo video:** https://youtu.be/hXsBIY23V2c
- **Live API proof:** https://7ew5f2x01d.execute-api.us-east-1.amazonaws.com/health → `{"triage":"trained_ensemble"}`
- Manual clinician login (if not using /showcase): Dr. Chen · PIN **224466**

---

## Inspiration
Emergency departments lose time on the front end of every single encounter. Registration pulls nurses off clinical work, language barriers cause measurable under-triage for non-English speakers (1 in 5 ED visits in major metros involves limited English proficiency), and clinicians flip through paper forms or multiple EHR screens before they even see the patient. We wanted to erase the gap between a patient walking through the door and a clinician knowing exactly what they need — without asking the patient to download anything.

## What it does
A patient scans a QR code in the waiting room and speaks their symptoms **in any of 20+ languages** — no app, no account. Within ~7 seconds they hear a warm, spoken explanation of their triage level and what to expect. They can optionally photograph an injury or insurance card, and tap a button if their pain worsens — which instantly alarms the clinician board.

On the other side, the clinician already has a full **AI pre-brief** before the patient is roomed: a provisional ESI acuity level, a **SHAP explanation of *why* the model scored it that way**, a **conformal prediction interval** that flags when the model is uncertain, matched EHR data (allergies, meds, conditions, prior visits), and a one-click AI scribe draft. Bedside vitals refine the ESI in real time. Patients who can't use the QR can call a Twilio voice agent that handles triage, scheduling, and 911 escalation.

## How we built it
- **Frontend:** Vite + React 18 + TypeScript + Tailwind + Framer Motion. Patient intake, a draggable split-screen clinician "showcase," WebGL hero. Strong accessibility (hundreds of `focus-visible` targets, `aria-live` regions, RTL support).
- **Backend:** FastAPI + Mangum on AWS Lambda (container, arm64, Python 3.12) behind API Gateway + CloudFront + WAFv2.
- **ML (the centerpiece):** a **4-model stacked ensemble** (LightGBM + XGBoost + CatBoost + MLP), 5-fold CV, logistic-regression meta-learner, ordinal threshold optimization, **split-conformal calibration** for 90% coverage, and **per-patient SHAP** via `pred_contrib`. A deterministic clinical safety floor can only *raise* acuity, never lower it. The trained ensemble is live in production (the `/health` endpoint proves `trained_ensemble`).
- **AI services:** Claude (triage narrative, scribe, pre-brief, vision OCR), AWS Transcribe (STT), AWS Polly (TTS). A content guard redacts 18 HIPAA Safe-Harbor identifiers before any third-party LLM call.
- **Integrations:** SMART-on-FHIR PKCE OAuth (Epic/Cerner/Athena), Twilio voice/SMS.
- **Security/compliance:** one customer-managed KMS key across DynamoDB/S3/Secrets Manager, TLS 1.2+, dual-write audit logging (90-day hot + 6-year cold), brute-force lockout, identity-keyed rate limiting, prompt-injection scanning. All provisioned by 28 idempotent scripts. See `SECURITY.md` and `docs/HIPAA_COMPLIANCE_DUE_DILIGENCE.md`.

## Challenges we ran into
- Keeping train/serve feature engineering perfectly in sync between the training notebook and the Lambda inference path.
- Making a synthetic-data-trained model clinically *safe* — solved with a deterministic safety floor rather than trusting raw probabilities.
- Real serverless HIPAA posture (CMK everywhere, BAA-covered services, audit retention) without a static server.

## Accomplishments we're proud of
- Real explainability (SHAP + conformal intervals), not a static chart — the clinician sees why and how confident.
- A genuinely production-grade security/compliance story implemented in code, not slideware.
- A patient experience that works on any phone in 20+ languages with zero install.

## What we learned
Honest ML in healthcare means quantifying uncertainty and building deterministic guardrails around a probabilistic model — and that the hardest part of "AI for clinicians" is explainability and trust, not raw accuracy.

## What's next
Real-world clinical validation study, EHR write-back (currently read-focused), per-tenant multi-hospital provisioning, and a formal SaMD/FDA pathway analysis for the acuity model (clinician-in-the-loop advisory posture). See `docs/roadmap-50-features.md`.

## Provenance (we're upfront about this)
Solace is an ongoing project we've built since April 2026; the core triage heuristics were ported from our own earlier Triage.ai/triagegeist work. We have not rewritten git history to hide the timeline. See the README "Provenance & what's new" section and `CHANGELOG.md`.

## Built with
React, TypeScript, Vite, Tailwind, Framer Motion, Python, FastAPI, AWS Lambda, API Gateway, CloudFront, WAF, DynamoDB, S3, KMS, Secrets Manager, CloudWatch, AWS Bedrock, AWS Transcribe, AWS Polly, Anthropic Claude, LightGBM, XGBoost, CatBoost, scikit-learn, SHAP, conformal prediction, Twilio, SMART-on-FHIR.

---

### How this maps to the judging criteria (for your own reference — don't paste this part)
- **Technical Complexity:** 4-model stacked ensemble + SHAP + conformal, SMART-on-FHIR PKCE, content guard, 28-script IaC. Live `/health` proves the ML is real.
- **UI/UX & Product Design:** /showcase split-screen, multilingual voice, strong a11y, polished landing.
- **Scalability & Feasibility:** serverless auto-scaling, HIPAA-by-construction, honest roadmap + cost story.
- **Presentation & Documentation:** this writeup + demo video + screenshots + README + SECURITY.md + HIPAA due-diligence.
