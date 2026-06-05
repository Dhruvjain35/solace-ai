# SMART App Launch v2 + US Core / USCDI Conformance Bar

> The shared technical bar all three major programs (Epic, Oracle Health, athenahealth)
> hold a provider-facing app to before they will let it touch a real customer's data.
> This is the spec layer; the per-vendor docs cover the *program* (registration, review,
> go-live) layered on top.
>
> Authoritative specs (verify current versions on the vendor portal before submission):
> - SMART App Launch 2.0.0 — https://hl7.org/fhir/smart-app-launch/
> - US Core 6.1.0 / 7.0.0 (FHIR R4) — https://hl7.org/fhir/us/core/
> - USCDI v3/v4 (the data-element list US Core profiles realize) — https://www.healthit.gov/isp/united-states-core-data-interoperability-uscdi
> - ONC (g)(10) Standardized API certification criterion — the federal rule that
>   forces all three vendors to expose the same SMART/US Core surface.

---

## 1. What a passing provider-facing SMART app must demonstrate

A provider (clinician-facing) SMART on FHIR app is judged on five axes:

| Axis | Requirement | Solace status (see gap-checklist.md) |
|------|-------------|--------------------------------------|
| **Launch** | Support EHR launch + standalone launch | Both implemented |
| **Authorization** | OAuth2 auth-code + PKCE (S256), `state`, OIDC `nonce`, refresh | Implemented |
| **Client auth** | Public (PKCE) and confidential asymmetric (`private_key_jwt`, RS384/ES384) | RS384 only |
| **Scopes** | SMART v2 `resource.cruds` granular scopes, identity scopes | Mixed v1/v2 |
| **Data** | Read/write US Core R4 profiles with USCDI vocab (LOINC/SNOMED/RxNorm/UCUM) | Read normalizes; write profiles partial |

### 1.1 Launch modes (SMART App Launch §3-4)

- **EHR launch**: the EHR opens the app from inside a chart and passes a `launch`
  token + `iss` (the FHIR base). The app threads `launch` through to `authorize`,
  and the token response returns launch context (`patient`, `encounter`).
  - Solace: `routers/ehr_auth.py:186-265` (launch handler threads `launch`, validates
    `iss` against the configured base at `:229`), context extracted at
    `lib/smart_auth.py:546-565`.
- **Standalone launch**: clinician opens the app directly; the app discovers the
  FHIR server and runs the same auth-code flow without a `launch` token.
  - Solace: same handler, `launch_type` recorded at `routers/ehr_auth.py:246`.

### 1.2 Authorization (SMART App Launch §2, OAuth2 + PKCE + OIDC)

A passing app MUST:

1. **Discover** endpoints from `{fhir_base}/.well-known/smart-configuration`
   (SMART v2 mandates this document).
   - Solace: `lib/smart_auth.py:158-207` parses it; `routers/ehr_auth.py:171-183`
     prefers discovered endpoints, falls back to static.
2. **PKCE S256 mandatory for all clients** (SMART v2 tightened this from v1).
   - Solace: `lib/smart_auth.py:64-72` (verifier 86 chars, S256 challenge); sent at
     `routers/ehr_auth.py:258-259`.
3. **`state`** for CSRF binding + **OIDC `nonce`** echoed into the `id_token` and
   validated on return.
   - Solace: generated `lib/smart_auth.py:88-95`; nonce validated
     `routers/ehr_auth.py:338-344` via `validate_nonce` (`lib/smart_auth.py:105-114`).
4. **Never** place the session token in a URL.
   - Solace: one-time handoff code, JWT exchanged via POST `/exchange`
     (`routers/ehr_auth.py:398-432, 478-508`).
5. Honor **`aud`** (the FHIR base) on the authorize request.
   - Solace: `routers/ehr_auth.py:256`.

### 1.3 Token-endpoint client authentication

- **Public client (default)**: PKCE only, `client_id` sent as a form field.
  - Solace: `routers/ehr_auth.py:465-466`.
- **Confidential asymmetric** (`private_key_jwt`): a signed JWT client assertion,
  `iss=sub=client_id`, `aud=token_endpoint`, unique `jti`, short `exp`, **RS384 or
  ES384**. This is what Epic/Oracle require for **system/backend-services** apps and
  for confidential SMART clients.
  - Solace: RS384 implemented in pure Python `lib/smart_auth.py:470-517`;
    `CLIENT_ASSERTION_TYPE` at `:521`; applied at `routers/ehr_auth.py:455-463`.
  - **Gap**: ES384 is explicitly unsupported (`lib/smart_auth.py:405-410`) because the
    venv has no `cryptography`. RS384 satisfies SMART, so this is acceptable but worth
    noting — some tenants prefer EC keys.

### 1.4 SMART v2 granular scopes (`resource.cruds`)

SMART v2 replaced v1's `.read`/`.write` with `resource.cruds` (create, read, update,
delete, search) and added `patient/`, `user/`, `system/` prefixes.

- Solace parses **both** v1 and v2 and upgrades v1→v2: `lib/smart_auth.py:217-319`
  (regex `_V2_SCOPE_RE`/`_V1_SCOPE_RE` at `:217-220`, `scope_granted` at `:277-287`).
- **Gap**: the scopes Solace *requests* (`lib/ehr_vendors.py:56-69`) are still SMART
  **v1** spelling (`user/Patient.read`, …). Servers downgrade-accept them, but a v2
  reviewer expects v2 requests (`user/Patient.rs`). Mechanically supported, not yet
  emitted. See gap-checklist.md.

### 1.5 US Core / USCDI data conformance

The FHIR resources the app reads and writes must conform to **US Core R4 profiles**,
which carry **USCDI** vocabulary bindings:

| Data | US Core profile | Required vocab | Solace coverage |
|------|-----------------|----------------|-----------------|
| Patient | US Core Patient | — | read: `fhir_patient_search.py:510-552` |
| Problem | US Core Condition (Problems) | SNOMED CT + ICD-10-CM, `category=problem-list-item` | write: `fhir_writer.py:122-137`, Epic dual-codes `ehr_epic.py:318-361` |
| Allergy | US Core AllergyIntolerance | RxNorm (drugs), `clinicalStatus`+`verificationStatus` | write: `fhir_writer.py:140-149`; Oracle adds RxNorm `ehr_oracle.py:350-396` |
| Med | US Core MedicationRequest (read) / MedicationStatement | RxNorm | read: `fhir_patient_search.py:648-655`; write `fhir_writer.py:221-258` |
| Vitals | US Core Vital Signs | LOINC + UCUM, `category=vital-signs` | write: `fhir_writer.py:176-192` (UCUM map `:154-173`) |
| Immunization | US Core Immunization | CVX, `primarySource` | write: `fhir_writer.py:207-218` |
| Clinical note | US Core DocumentReference | LOINC type, `category=clinical-note` | write: `fhir_writer.py:79-119` |
| Provenance | US Core Provenance (+ HTI-1 DSI) | — | `fhir_writer.py:262-325` |

**Vocabulary the app must speak** (USCDI): LOINC (labs/vitals/doc types), SNOMED CT
(problems), RxNorm (meds/drug allergies), CVX (vaccines), ICD-10-CM (billing crosswalk),
UCUM (units). Solace builders emit all six.

---

## 2. Conformance gaps that block a clean pass (summary)

1. **Requested scopes are v1, not v2** (`lib/ehr_vendors.py:56-69`). The `_DEFAULT_SCOPES`
   tuple is shipped to every vendor unchanged — reviewers (and per-tenant scope
   allowlists) expect v2 `cruds` and per-vendor scope sets.
2. **No US Core profile validation step.** Builders set the right `category`/codes but
   there is no test asserting resources validate against the US Core StructureDefinitions
   (e.g. via the HL7 validator / Inferno). Reviewers run Inferno; Solace should too.
3. **Read path is normalize-only, no profile assertion** (`fhir_patient_search.py`):
   it tolerantly reads any FHIR but does not prove it handles US-Core-`mustSupport`
   elements. Fine for an app that *consumes*, but Inferno's "US Core" test group expects
   the app to request and handle the mustSupport set.
4. **No `.well-known/smart-configuration` published by Solace itself** — not required
   for a *client* app (only servers publish it), so this is a non-issue; called out to
   avoid confusion.
5. **id_token signature is not cryptographically verified** (`lib/smart_auth.py:524-543`
   decodes claims without verifying the JWKS signature; trust is delegated to TLS from
   the token endpoint). Acceptable per the documented threat model, but a strict
   reviewer may flag it — fetching the issuer JWKS and verifying RS256 is the rigorous
   path.

---

## 3. The certification artifact reviewers look for

- **Inferno** (ONC's official test kit, https://inferno.healthit.gov/) — run the
  **SMART App Launch STU2** and **US Core** test groups against your app + a reference
  server. Capture the pass report. Epic and Oracle both expect you to have done this;
  athena's review is lighter but the same standards apply.
- A **scope justification** doc: for each scope you request, why a clinician-facing
  triage/scribe app needs it (minimum-necessary, HIPAA §164.502(b)).
- A **data-flow / PHI-handling** description (the security questionnaires want this).

See `gap-checklist.md` for the line-by-line Solace mapping.
