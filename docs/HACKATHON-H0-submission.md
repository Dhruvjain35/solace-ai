# H0: Hack the Zero Stack — Solace submission package

## ⏳ LIVE DRAFT STATUS (Devpost submission #1066936)
Draft is created and these fields are FILLED in the form (do not reload the open tab or they may be lost before you save):
- **Project name:** Solace — AI-native ED intake & triage
- **Elevator pitch / Story / Built-with tags (18) / Demo URL / Video link:** ✅ done
- **Track:** Monetizable B2B app ✅
- **Published Vercel link:** https://solaceaidemo.vercel.app/showcase ✅
- **Database:** Amazon DynamoDB ✅

### ❗ Remaining — only YOU can do these (then Save & continue → Submit):
1. **Submitter Type** — Individual or Team (Solace is a team project → likely "Team"; you'd be the Representative)
2. **Country of Residence** — your country (personal; check excluded-countries list in rules)
3. **App Status** — "New" if Solace was first built within May 27–Jun 29, 2026; else "Existing" + one line on what you updated
4. **Vercel Team ID** — vercel.com → the team hosting the live site (inkspire) → Settings → General → "Team ID" (team_xxxx)
5. **Architecture diagram** (file upload, required) — I can generate a PNG for you
6. **AWS DB screenshot** (file upload, required) — screenshot your AWS Console → DynamoDB → Tables list showing the `solace-*` tables
7. **Final Submit** — this is YOUR click (submitting = agreeing to the Official Rules as a binding contract)

Deadline: **June 29, 2026, 5:00 pm PT.**

---


**Deadline:** June 29, 2026, 5:00 pm Pacific (≈1 day out). Submit a *draft* early, keep editing until the deadline.

**Track:** **Track 2 — Monetizable B2B App** (healthcare is named explicitly in the track).
You are also automatically eligible for the four Best-of prizes (Best Technical Implementation, Best Design, **Most Impactful**, Most Original) — Most Impactful is very winnable for an ED-triage product.

**Database used:** **Amazon DynamoDB** (one of the three required AWS Databases). ✅
**Frontend deployment:** **Vercel** (patient intake SPA + clinician terminal + marketing site). ✅

---

## Why this is a real fit (not a stretch)
- Required stack = (Aurora **or** Aurora DSQL **or** DynamoDB) + (Vercel **or** v0). Solace = **DynamoDB + Vercel**. Met.
- Rules updated 6/10 to be "more inclusive if you don't use the new integration" — you only need a **screenshot proving AWS DB usage**. So Vite+React on Vercel + DynamoDB via the FastAPI/Lambda backend qualifies.
- Built within the submission window (May 27–June 29, 2026), so "New & Existing" is satisfied.

**Honesty guardrail:** Do **not** claim you used v0 to scaffold it (you used Vite/React). Lead with the **DynamoDB data model** and the **Vercel-hosted frontends** — both true and both strong.

---

## The DynamoDB story (this is the linchpin — criterion #1)
Solace runs entirely on a **multi-table DynamoDB design**, on-demand (PAY_PER_REQUEST), every table CMK-encrypted, TTL on transient tables. Real, deliberate modeling:

| Domain | Tables |
|---|---|
| Patient + clinical | `solace-patients`, `solace-ehr-patients`, `solace-clinicians`, `solace-hospitals`, `solace-notes`, `solace-prescriptions`, `solace-appointments`, `solace-calls` |
| Auth / sessions | `solace-magic-tokens`, `solace-intake-nonces` (TTL), `solace-blocklist` |
| Integrity / safety | `solace-idempotency` (TTL — exactly-once writes), `solace-quotas`, `solace-audit-log` (6-yr retention), `SolaceRateLimit` |

Talking points for the video/description:
- **Why DynamoDB, not Aurora:** ED intake is spiky and bursty (waiting-room rushes). On-demand DynamoDB absorbs traffic spikes with single-digit-ms reads and zero capacity planning — the right call for unpredictable hospital load and for scaling to many hospitals.
- **Deliberate keys/TTL:** idempotency + nonce tables use TTL for self-expiring exactly-once semantics; audit log is append-only for HIPAA.
- **Single-digit-ms** lookups power the live clinician queue refresh and EHR auto-match before the patient is roomed.

---

## Per-criterion framing (equally weighted)
1. **Technical Implementation** — DynamoDB multi-table model + TTL/idempotency, 4-model ML triage ensemble (LightGBM+XGBoost+CatBoost+MLP) with SHAP + conformal prediction, Bedrock/Transcribe/Polly, CloudFront+WAF, all under the AWS BAA. Frontends on Vercel.
2. **Design** — Polished patient intake (multilingual voice, no app/login) + clinician terminal; cohesive front-to-back full-stack feel.
3. **Impact & Real-world Applicability** — Cuts ED front-end dead time, fixes under-triage for limited-English patients, real HIPAA-grade architecture. Shippable to hospitals today.
4. **Originality** — Explainable AI triage (provisional ESI + SHAP) with multilingual voice intake and a phone voice agent — a genuinely novel combination.

---

## Required submission artifacts — checklist
- [x] **Text description** (below)
- [x] **Database used:** DynamoDB
- [x] **Demo video (<3 min, YouTube):** https://www.youtube.com/watch?v=vFjxtGklkCo — *confirm it's <3:00 and shows the working app + names DynamoDB; if it doesn't mention the DB, add one sentence of narration or a caption.*
- [x] **Published Vercel project link:** https://mysolaceclinic.com (marketing) and the product app https://solaceaidemo.vercel.app/showcase
- [ ] **Vercel Team ID** — get from Vercel dashboard → team → Settings → "Team ID" (project lives under the `inkspire-custom-arts-projects` team)
- [ ] **Architecture diagram** — use the ASCII one in `README.md`; turn it into an image (the README diagram already shows Patient→Vercel SPA→CloudFront/WAF→API GW→Lambda→DynamoDB/S3/Bedrock). Need a PNG.
- [ ] **Screenshot proving AWS DB usage** — AWS console screenshot of the DynamoDB **Tables** list showing the `solace-*` tables. (Strongest possible proof.)

---

## Ready-to-paste TEXT DESCRIPTION

**Solace — AI-native patient intake & clinical triage for emergency departments**
*Track: Monetizable B2B App · Database: Amazon DynamoDB · Frontend: Vercel*

Emergency departments lose time on the front end of every encounter: registration pulls nurses off clinical work, language barriers cause under-triage for non-English speakers, and clinicians flip through paper forms before seeing a patient. Solace removes that dead time.

A patient scans a QR code in the waiting room, speaks their symptoms in any of 20+ languages (no app, no account), and optionally photographs an injury or insurance card. Within seconds they hear a calm, spoken explanation of their triage level and what to expect. On the other side of the department, the clinician already has an AI pre-brief — provisional ESI level, SHAP attribution, EHR auto-match, and a scribe draft — before the patient is roomed.

**Why DynamoDB.** ED traffic is bursty and unpredictable. Solace runs on a multi-table Amazon DynamoDB design (on-demand capacity, CMK-encrypted, TTL on transient tables) — `solace-patients`, `solace-ehr-patients`, `solace-clinicians`, `solace-hospitals`, `solace-appointments`, `solace-notes`, `solace-prescriptions`, plus TTL-backed `solace-idempotency` and `solace-intake-nonces` for exactly-once writes and self-expiring sessions, and an append-only `solace-audit-log` for HIPAA. Single-digit-millisecond reads power the live clinician queue and EHR match with zero capacity planning — the right database for spiky waiting-room load and for scaling across many hospitals.

**Stack.** Frontends (patient intake SPA + clinician terminal) deploy on Vercel. Backend is FastAPI on AWS Lambda behind API Gateway + CloudFront/WAF. AI runs through AWS Bedrock (Claude), Transcribe, and Polly — all under the AWS Business Associate Agreement. A 4-model stacked ML ensemble (LightGBM + XGBoost + CatBoost + MLP) refines ESI from bedside vitals with SHAP explanations and conformal prediction intervals.

Solace is HIPAA-grade and shippable to hospitals today.
