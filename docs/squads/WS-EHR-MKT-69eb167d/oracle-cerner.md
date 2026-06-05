# Oracle Health (Cerner) — Code Console / Ignite APIs Approval Playbook

> Goal: get Solace registered and approved as a **provider-facing SMART on FHIR**
> app against **Oracle Health (Cerner Millennium)** via the **code.cerner.com** developer
> portal ("Code Console") and the **Ignite APIs** (Oracle's FHIR R4 + proprietary
> surfaces).
>
> Oracle acquired Cerner; branding is migrating from "Cerner" to "Oracle Health". The
> developer portal, console, and sandbox URLs are in flux. **Verify current portal URLs,
> console names, and the promotion process on https://code.cerner.com /
> https://docs.oracle.com/en/industries/health before submitting.** Technical bar below
> is stable.

---

## 0. TL;DR sequence

1. Create a developer account on **code.cerner.com** (Code Console). Free.
2. Register a **provider-facing SMART on FHIR (R4)** app; get a sandbox **client_id**.
3. Configure scopes, redirect URI, and (for confidential/system apps) a JWKS.
4. Build + test against the **public sandbox tenant** (`fhir-ehr-code.cerner.com`).
5. Submit for **validation / review**; on pass, **promote to production**.
6. Each provider org enables your app in **their** Millennium tenant (per-customer).

---

## 1. Registration (code.cerner.com — Code Console)

- **Where**: https://code.cerner.com → register, then create an app in the console.
- **App type**: **Provider** (clinician-facing) **SMART on FHIR**, **R4**.
- **Client type**:
  - **Public** (PKCE) for the browser-launched clinician app — Solace default
    (`routers/ehr_auth.py:465-466`).
  - **Confidential** for SMART **Backend Services** (system scopes): host a **JWKS**
    (public keys) so Oracle can verify your `private_key_jwt`. Solace signs RS384
    (`lib/smart_auth.py:470-517`); register an **RSA** key (ES384 unsupported by the
    pure-Python signer, `lib/smart_auth.py:405-410`).
- **Redirect URI**: register Solace's callback
  `{SOLACE_API_BASE_URL}/api/auth/ehr/callback` (`routers/ehr_auth.py:792-795`).
- Set the sandbox **client_id** via `SOLACE_CERNER_CLIENT_ID` (`ehr_vendors.py:132`);
  endpoints overridable via `SOLACE_CERNER_AUTHORIZE_URL` / `_TOKEN_URL` / `_FHIR_URL`
  (`ehr_vendors.py:129-131`).

## 2. SMART scopes (Ignite APIs)

- Oracle uses standard **SMART v2** `resource.cruds` scopes with `patient/`, `user/`,
  `system/` prefixes. For a provider triage/scribe app, request `user/` scopes:
  - Read: `user/Patient.rs`, `user/Practitioner.rs`, `user/Encounter.rs`,
    `user/Observation.rs`, `user/Condition.rs`, `user/AllergyIntolerance.rs`,
    `user/MedicationRequest.rs` + `openid fhirUser launch online_access`.
  - Write (per resource Oracle permits): `user/DocumentReference.c`,
    `user/Condition.c`, `user/AllergyIntolerance.c`, `user/Observation.c`.
- **Solace gap**: `_DEFAULT_SCOPES` (`ehr_vendors.py:56-69`) requests **v1** spelling
  (`user/Patient.read`). Oracle's tenants are stricter about v2; switch the Cerner
  scope request to v2 `cruds`. Solace can build v2 strings (`lib/smart_auth.py:290-306`).
- Tenant URL carries the **tenant GUID** in the path — Solace's defaults already do
  (`ehr_vendors.py:83-91`); never strip it (`ehr_oracle.py:31-33`).

## 3. Sandbox onboarding

- **Endpoint**: public sandbox tenant at
  `https://fhir-ehr-code.cerner.com/r4/{tenant}/` with auth at
  `https://authorization.cerner.com/tenants/{tenant}/...` — these are Solace's static
  Cerner defaults (`ehr_vendors.py:83-91`).
- Sandbox ships Millennium **test patients**. Prove launch + read + write.
- Exercise **both** standalone and EHR launch.

## 4. Validation / review

- Oracle's review checks your app **registration metadata, scopes (minimum-necessary),
  redirect URIs, and security posture**. Like Epic, expect a questionnaire and a request
  for **SOC 2 / HITRUST** evidence for production PHI access. **Confirm the exact
  validation steps and any certification requirement on code.cerner.com.**
- Run **Inferno** (SMART STU2 + US Core) and attach the report (smart-conformance.md §3).

## 5. Production promotion + customer connection

- After validation, **promote the app from sandbox to production** in the Code Console;
  Oracle issues a **production client_id**.
- Integration is **per-customer / per-tenant**: each provider org's Oracle Health admin
  must enable your app in **their** Millennium tenant and approve scopes. Solace points
  at any tenant via env override (`ehr_vendors.py:73-74, 129-132`), so one binary serves
  sandbox and each customer tenant.

## 6. Oracle write quirks Solace already handles (`services/ehr_oracle.py`)

- Plain FHIR `POST {base}/{ResourceType}` create — **no** Epic-style `$add`
  (`ehr_oracle.py:211-213`).
- **201 + empty body**, id only in `Location` / `Content-Location` header
  (`ehr_oracle.py:176-188, 238-253`).
- Stricter required fields: `Condition.category` + `clinicalStatus`
  (`ehr_oracle.py:303-348`); `AllergyIntolerance.category` + RxNorm for drug allergies
  (`ehr_oracle.py:350-396`); `Observation` needs `status` + `category` + `effective[x]`
  (`ehr_oracle.py:398-443`).
- `application/fhir+json` content negotiation is mandatory (`ehr_oracle.py:154-167`).
- `OperationOutcome` error parsing (`ehr_oracle.py:457-480`).
- **Note**: the Oracle adapter is **not yet wired into `routers/ehr.py`** — the exact
  router lines to add are documented in the adapter footer (`ehr_oracle.py:483-518`).

## 7. Timeline + cost (verify)

- **Sandbox + client_id**: free, same day on Code Console.
- **Validation → production promotion**: typically **weeks**; security attestation is
  the long pole.
- **Fees**: Oracle/Cerner has had program/listing fees that have changed. **Confirm the
  current fee model on the portal — do not quote from memory.**
- **Per-customer enablement**: hospital IT calendar driven.

## 8. Certification asks

- **SOC 2 Type II** and/or **HITRUST** for production PHI — Solace has controls but **no
  attestation yet** (same blocker as Epic).
- **Inferno** SMART STU2 + US Core report.

## 9. Solace satisfies vs. owes Oracle

| Oracle expectation | Solace today | File:line |
|--------------------|--------------|-----------|
| SMART R4, PKCE, tenant-scoped base | Done | `lib/ehr_vendors.py:83-91`, `routers/ehr_auth.py` |
| Plain-create, 201/Location, fhir+json | Done | `services/ehr_oracle.py:190-253` |
| Condition/Allergy/Observation required fields + RxNorm | Done | `services/ehr_oracle.py:303-443` |
| v2 `cruds` scope *requests* | **Partial (v1 requested)** | `lib/ehr_vendors.py:56-69` |
| Adapter wired into a clinician router | **Not yet** | `services/ehr_oracle.py:483-518` |
| Backend-services JWKS hosting | Not yet (RS384 signer ready) | `lib/smart_auth.py:470-517` |
| SOC 2 / HITRUST | **Missing** | — |
| Production client_id / promotion | Not yet requested | — |
