# athenahealth — Marketplace / "More Disruption Please" Approval Playbook

> Goal: get Solace registered and approved on **athenahealth's Marketplace** via the
> developer program historically branded **"More Disruption Please" (MDP)**, now the
> **athenahealth Developer Portal** (developer.athenahealth.com).
>
> athena's program packaging and branding have changed (MDP → Marketplace → Developer
> Portal). **Verify current portal URLs, partner tiers, and fees on
> https://developer.athenahealth.com and https://marketplace.athenahealth.com before
> submitting.** athena differs from Epic/Oracle in one big way: it exposes **two write
> surfaces** — FHIR R4 *and* a proprietary practice-scoped REST API — and uses
> **client_credentials** OAuth for the REST surface.

---

## 0. TL;DR sequence

1. Apply to the **athenahealth Developer Portal / Marketplace partner program**.
2. Register an app; get **preview (sandbox) credentials** (`client_id` +
   `client_secret`, plus a `practice_id`).
3. Build against the **preview sandbox**
   (`api.preview.platform.athenahealth.com`).
4. athena reviews the integration (functional + security) and lists it on the
   **Marketplace**.
5. A practice subscribes/enables the listing; production credentials are scoped to that
   practice.

---

## 1. Registration (developer.athenahealth.com)

- **Where**: https://developer.athenahealth.com — apply for partner/developer access.
  Unlike Epic/Oracle, athena's developer onboarding has historically involved a
  **partner application / approval step before** you get keys (not fully self-service).
  **Confirm current self-service vs. application gating on the portal.**
- **App type**: provider-facing clinical app. athena clinical workflows are
  **practice-scoped** — every proprietary REST call is keyed by `practice_id`
  (`ehr_athena.py:353-354`).
- **Credentials**: athena issues `client_id` + `client_secret` (confidential client).
  Solace reads them from env: `SOLACE_ATHENA_CLIENT_ID`, `SOLACE_ATHENA_CLIENT_SECRET`,
  `SOLACE_ATHENA_BASE_URL`, `SOLACE_ATHENA_PRACTICE_ID` (`ehr_athena.py:175-201`).
- **Redirect URI**: for the SMART/clinician sign-in path, register Solace's callback
  `{SOLACE_API_BASE_URL}/api/auth/ehr/callback`. Note the SMART vendor entry
  (`ehr_vendors.py:136-155`) points at `api.preview.platform.athenahealth.com` and is
  set via `SOLACE_ATHENA_CLIENT_ID` (`ehr_vendors.py:152`).

## 2. OAuth + scopes (two surfaces, two flows)

athena is unusual: Solace's adapter handles **both**:

1. **FHIR R4 surface** (`{base}/fhir/r4/...`) — used for clinical **documents**
   (DocumentReference). SMART-style auth.
2. **Proprietary practice-scoped REST** (`{base}/v1/{practiceid}/...`) — used for
   problems, allergies, vitals, because athena never fully exposed those as FHIR writes.
   Auth is **OAuth2 `client_credentials`** with **HTTP Basic** (`client_id:secret`),
   token cached until just before expiry (`ehr_athena.py:264-305`).

- **athena scope string**: the proprietary surface uses athena's own scope vocabulary
  (Solace requests `athena/service/Athenanet.MDP.*`, `ehr_athena.py:285`) — **not** SMART
  `cruds`. **Confirm the exact scope string your partner tier is granted on the portal.**
- The SMART/FHIR clinician launch still uses the standard SMART scopes from
  `_DEFAULT_SCOPES` (`ehr_vendors.py:56-69`) — same v1→v2 caveat as the other vendors.

## 3. Sandbox onboarding (preview)

- **Endpoint**: `https://api.preview.platform.athenahealth.com` — FHIR at
  `/fhir/r4/`, REST at `/v1/{practiceid}/`, token at `/oauth2/v1/token`
  (`ehr_athena.py:265-266, 314-315, 353-354`; vendor defaults `ehr_vendors.py:140-151`).
- athena's preview has a **sandbox practice** with test patients/encounters. Prove:
  - FHIR `DocumentReference` write (`ehr_athena.py:317-350`).
  - REST `problems` POST (`ehr_athena.py:356-391`).
  - REST `allergies` **replace-list PUT** — the whole list, not a delta
    (`ehr_athena.py:393-429`).
  - REST `vitals` via **clinicalelementid** vocab (NOT LOINC) — Solace maps LOINC→athena
    (`ehr_athena.py:431-475, 507-530`).

## 4. Review + Marketplace listing

- athena's review is generally **lighter-weight than Epic's** but still checks
  functional correctness against the sandbox and a **security/privacy questionnaire**
  (PHI handling, BAA). Marketplace listing requires marketing collateral (description,
  screenshots, supported workflows).
- **SOC 2 / HITRUST**: athena's bar has historically been less strict than Epic's for
  listing, but production PHI access on customer practices still warrants SOC 2.
  **Confirm whether your partner tier requires an attestation.**
- Run **Inferno** for the FHIR surface (smart-conformance.md §3).

## 5. Production + practice connection

- Production credentials are **practice-scoped**: a practice subscribes to your
  Marketplace listing, and athena provisions production access for **that practice_id**.
  Solace is parameterized on `practice_id` (`ehr_athena.py:158-201`), so one binary
  serves multiple practices by swapping config.
- `AthenaConfig.is_configured()` (`ehr_athena.py:220-231`) lets the router surface the
  athena path only when all four env vars are present.

## 6. athena write quirks Solace already handles

- Dual surface (FHIR + REST) under one cached token (`ehr_athena.py:246-305`).
- `client_credentials` + HTTP Basic token acquisition (`ehr_athena.py:268-305`).
- Allergies are a **replace-list PUT** (`ehr_athena.py:393-429`).
- Vitals use **clinicalelementid**, not LOINC, with a LOINC→athena map
  (`ehr_athena.py:507-530`).
- **Note**: athena adapter is **not yet wired into `routers/ehr.py`** — exact wiring is
  documented in the module footer `ROUTER_WIRING` (`ehr_athena.py:533-574`).

## 7. Timeline + cost (verify)

- **Developer/partner access**: may require an **application + approval** (slower than
  Epic/Oracle self-service sandbox).
- **Review → listing**: typically **weeks**.
- **Fees**: athena Marketplace has had listing fees and/or revenue share. **Confirm the
  current model on marketplace.athenahealth.com — do not quote from memory.**

## 8. Solace satisfies vs. owes athena

| athena expectation | Solace today | File:line |
|--------------------|--------------|-----------|
| FHIR R4 DocumentReference write | Done | `services/ehr_athena.py:317-350` |
| `client_credentials` + Basic auth, token cache | Done | `services/ehr_athena.py:264-305` |
| REST problems / allergies(PUT) / vitals(clinicalelementid) | Done | `services/ehr_athena.py:356-475` |
| LOINC→athena vital mapping | Done | `services/ehr_athena.py:507-530` |
| Practice-scoped config | Done | `services/ehr_athena.py:158-231` |
| Adapter wired into a clinician router | **Not yet** | `services/ehr_athena.py:533-574` |
| Partner-tier scope string confirmed | **Verify on portal** | `services/ehr_athena.py:285` |
| SOC 2 (if required by tier) | **Missing** | — |
| Marketplace listing | Not yet requested | — |
