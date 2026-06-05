# Epic — Marketplace / Connection-Hub Approval Playbook

> Goal: get Solace registered and approved as a **provider-facing SMART on FHIR**
> app on Epic's developer program, from free sandbox to a live customer connection.
>
> Epic has rebranded its program several times — **App Orchard → Showroom →
> "Vendor Services" / "Connection Hub" / "Epic on FHIR" + "Open Epic"**. The exact
> portal names and fee schedule change; **verify current names, steps, and pricing on
> https://fhir.epic.com and https://vendorservices.epic.com before submitting.** The
> technical bar (below) is stable; the program packaging is what shifts.

---

## 0. TL;DR sequence

1. Create an account on **fhir.epic.com** (free, self-service).
2. Register an app under **Build Apps** → choose **Clinicians** (provider-facing) +
   **SMART on FHIR R4**. Get a **non-production client_id** immediately.
3. Pick your APIs (FHIR R4 resources) and scopes; set redirect URI.
4. Build + test against the **public sandbox** (fhir.epic.com R4 endpoint).
5. Request a **production client_id** — this triggers Epic's **technical + security
   review** (questionnaire, optionally HITRUST/SOC 2 evidence).
6. Get listed on **Showroom** (the customer-facing marketplace) so Epic provider
   orgs can find you.
7. Each **customer org** must then enable your app in their environment — Epic
   integration is **per-customer**, gated by the hospital's Epic admin.

---

## 1. Registration (fhir.epic.com)

- **Where**: https://fhir.epic.com/Developer/Apps → "Build Apps". Account creation is
  free and ~30 minutes.
- **App type**: choose **"Clinicians"** audience (provider-facing) — *not* "Patients"
  or "Backend Systems" unless you also need a backend-services app. Solace's clinician
  SMART sign-in maps to the **Clinicians / SMART on FHIR** app type.
- **FHIR version**: **R4** (Solace targets R4 throughout — `ehr_vendors.py:80`).
- **Client type**:
  - **Public** (PKCE, no secret) — matches Solace's default
    (`routers/ehr_auth.py:465-466`). Simplest for a browser-launched clinician app.
  - **Confidential** (asymmetric `private_key_jwt`) — required if you also stand up a
    **backend services** app (system scopes, no user present). Solace can do RS384
    (`lib/smart_auth.py:470-517`); register a 2048-bit **RSA** key pair (Epic accepts
    RS384/ES384 — Solace's signer is RS384-only, so use RSA).
- **Redirect URI**: must exactly match your callback. Solace's is
  `{SOLACE_API_BASE_URL}/api/auth/ehr/callback` (`routers/ehr_auth.py:792-795`).
  Register the production CloudFront URL.
- Epic issues a **non-production client_id** instantly. Set it via
  `SOLACE_EPIC_CLIENT_ID` (`ehr_vendors.py:121`); endpoints can be overridden with
  `SOLACE_EPIC_AUTHORIZE_URL` / `_TOKEN_URL` / `_FHIR_URL` (`ehr_vendors.py:118-120`).

## 2. APIs + scopes

- In the app build, **select each FHIR R4 API** (resource + interaction) you need.
  Epic only grants what you select. For a triage/scribe app:
  - **Read**: Patient, Practitioner, Encounter, Observation, Condition,
    AllergyIntolerance, MedicationRequest (matches Solace's read enrichment,
    `fhir_patient_search.py:462-467`).
  - **Write**: DocumentReference (Create), Condition (problem-list add), Observation
    (vitals), AllergyIntolerance — matches `services/ehr_epic.py:258-429`.
- **Scopes**: Epic still emits **SMART v1** scope spelling (`user/Observation.read`),
  and Solace requests v1 today (`ehr_vendors.py:56-69`). Epic accepts v1; if you opt
  into Epic's v2 scope behavior, switch the request to `user/Observation.rs`
  (`lib/smart_auth.py:290-306` can build v2 strings). **Verify which spelling the
  target tenant expects on the portal.**
- **Epic write quirks Solace already handles**:
  - 201 + empty body, id in the `Location` header (`ehr_epic.py:229-255`).
  - Problem-list `Condition` requires `category=problem-list-item` + SNOMED primary,
    ICD-10 secondary (`ehr_epic.py:318-361`).
  - Errors come back as `OperationOutcome` (`ehr_epic.py:105-130`).
  - Vitals need LOINC + UCUM `code` (`ehr_epic.py:399-429`).
  - **Note**: Epic restricts external `Observation` writes to an allowlist of LOINC
    codes and may reject `encounter-diagnosis` category writes — **confirm the writable
    resource/code list for each Epic version on the portal.**

## 3. Sandbox onboarding

- **Endpoint**: the public R4 sandbox at
  `https://fhir.epic.com/interconnect-fhir-oauth/...` (Solace's static defaults,
  `ehr_vendors.py:78-80`).
- Epic ships **sandbox test patients** (e.g. "Camila Lopez", "Derrick Lin"). Use them
  to prove launch + read + write end to end.
- Run **both** EHR launch (from Epic's sandbox launcher) and standalone launch.
- Prove your **OperationOutcome** handling on deliberate failures (bad code, missing
  scope).

## 4. Security / technical review (the gate to production)

When you request a **production client_id**, Epic runs a review. Expect:

- A **technical questionnaire**: app architecture, which scopes and why
  (minimum-necessary), data flow, where PHI is stored, multi-tenancy isolation.
- **Security attestation**: Epic increasingly asks for **HITRUST CSF certification**
  and/or **SOC 2 Type II** for apps handling PHI on customer connections. Solace today
  has security *controls* (CONSTITUTION SEC-001…010, COMP-001…006) but **no third-party
  attestation** — this is the single biggest non-code gap. Budget for SOC 2 Type II
  (6-12 month observation window) and/or HITRUST.
- **Privacy / BAA posture**: Solace is a **Business Associate**, not a Covered Entity —
  the customer org is the CE. Have your BAA template ready.
- They review your **redirect URIs, token handling, PKCE, nonce** — all of which Solace
  implements (`routers/ehr_auth.py`).

## 5. Production go-live + customer connection

- Epic integration is **per-customer**, not a single global switch. After Epic issues a
  **production client_id**, **each hospital's Epic admin** must:
  1. Enable your app in *their* Epic environment (their FHIR base URL, their tenant).
  2. Approve the scopes for their clinicians.
- Your code already supports per-deployment endpoint override via env
  (`ehr_vendors.py:73-74, 118-123`) so the **same binary** points at sandbox or a
  customer's prod Epic.
- **Showroom listing**: to be discoverable, get listed on Epic's customer-facing
  marketplace (Showroom). Requires the production review to be passed and marketing
  collateral (description, screenshots, security summary).

## 6. Timeline + cost (verify — Epic changes these)

- **Sandbox + non-prod client_id**: free, same day.
- **Production review**: historically **weeks to a few months**, gated heavily by your
  **security attestation** readiness (SOC 2 / HITRUST is the long pole).
- **Program fees**: Epic's marketplace has had per-app and/or revenue-share fee models
  that have changed repeatedly. **Confirm the current fee schedule on
  vendorservices.epic.com — do not quote a number from memory.**
- **Per-customer go-live**: depends entirely on the hospital's IT calendar (often the
  longest real-world delay).

## 7. Epic-specific certification asks

- **HITRUST CSF** and/or **SOC 2 Type II** — increasingly required for production
  connections handling PHI.
- **Inferno SMART STU2 + US Core** pass report (see smart-conformance.md §3).
- Scope-justification + data-flow doc.

## 8. What Solace already satisfies vs. owes Epic

| Epic expectation | Solace today | File:line |
|------------------|--------------|-----------|
| SMART R4, PKCE, standalone + EHR launch | Done | `routers/ehr_auth.py:186-265` |
| Discovery + nonce + handoff (no JWT in URL) | Done | `routers/ehr_auth.py:171-183, 338-432` |
| `private_key_jwt` (RS384) for confidential | Done (RSA only) | `lib/smart_auth.py:470-517` |
| Epic 201/Location, OperationOutcome, problem-list dual-code | Done | `services/ehr_epic.py:229-361` |
| v2 scope *requests* | Partial (v1 requested) | `lib/ehr_vendors.py:56-69` |
| SOC 2 / HITRUST attestation | **Missing** | — |
| Production client_id + Showroom listing | Not yet requested | — |
| Per-customer enablement | Code-ready (env override) | `lib/ehr_vendors.py:73-74` |
