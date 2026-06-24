# EHR Marketplace Gap Checklist — Solace Current Code vs. Vendor Bar

> Line-by-line map of Solace's **current** EHR code to the Epic / Oracle Health /
> athenahealth approval bar. Grounded in the actual files; every claim cites `file:line`.
> "✅ conforms" = code is present and correct. "⚠️ partial" = present but needs change.
> "❌ missing" = not in the codebase / not a code problem (program/legal).
>
> Where a current vendor requirement could not be confirmed from code, the entry says
> **"verify on the vendor portal"** rather than asserting a specific.

Files audited: `routers/ehr_auth.py`, `lib/smart_auth.py`, `lib/ehr_vendors.py`,
`services/ehr_epic.py`, `services/ehr_oracle.py`, `services/ehr_athena.py`,
`services/ehr_gateway.py`, `services/fhir_writer.py`, `services/fhir_patient_search.py`,
`tests/ehr/` (confirmed `tests/ehr/test_fhir_writer.py`).

---

## A. SMART App Launch v2 (shared bar)

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| A1 | OAuth2 authorization-code flow | ✅ | `routers/ehr_auth.py:250-265` (launch), `:274-432` (callback) |
| A2 | PKCE **S256 mandatory** (all clients) | ✅ | `lib/smart_auth.py:64-72`; sent `routers/ehr_auth.py:258-259` |
| A3 | `state` CSRF binding, DDB-backed (survives cold start) | ✅ | `lib/smart_auth.py:88-102`; `routers/ehr_auth.py:107-137` |
| A4 | OIDC `nonce` echoed + validated | ✅ | `lib/smart_auth.py:105-114`; `routers/ehr_auth.py:338-344` |
| A5 | `.well-known/smart-configuration` discovery, prefer live | ✅ | `lib/smart_auth.py:158-207`; `routers/ehr_auth.py:171-183` |
| A6 | EHR launch (thread `launch`, validate `iss`) | ✅ | `routers/ehr_auth.py:224-264` (iss check `:229`) |
| A7 | Standalone launch | ✅ | `routers/ehr_auth.py:246` (`launch_type`) |
| A8 | Token never in URL (one-time handoff code, POST exchange) | ✅ | `routers/ehr_auth.py:398-432, 478-508` |
| A9 | Refresh-token grant, raw token never reaches frontend | ✅ | `routers/ehr_auth.py:478-592` (opaque `refresh_handle`) |
| A10 | `private_key_jwt` confidential auth (RS384) | ⚠️ partial | `lib/smart_auth.py:470-517` — **RS384 only; ES384 rejected** `:405-410` |
| A11 | Redirect-URI allowlist (open-redirect guard) | ✅ | `routers/ehr_auth.py:78-90, 208-212` (CONSTITUTION SEC-006) |
| A12 | `aud` (FHIR base) on authorize | ✅ | `routers/ehr_auth.py:256` |
| A13 | id_token **signature** cryptographically verified vs JWKS | ⚠️ partial | `lib/smart_auth.py:524-543` decodes claims **unverified** (TLS-trust model) |

**A10 verdict**: RS384 satisfies SMART (RS384 or ES384 allowed). Register an **RSA**
key with every vendor. Only a problem if a specific tenant mandates EC keys — verify.

**A13 verdict**: acceptable per the documented threat model (id_token arrives over TLS
straight from the token endpoint), but a strict reviewer may flag it. Hardening = fetch
issuer JWKS + verify RS256.

---

## B. SMART v2 granular scopes

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| B1 | Parse/understand v2 `resource.cruds` scopes | ✅ | `lib/smart_auth.py:217-287` |
| B2 | Upgrade v1→v2 spelling internally | ✅ | `lib/smart_auth.py:248-264, 309-319` |
| B3 | Build v2 scope strings | ✅ | `lib/smart_auth.py:290-306` |
| B4 | **Request** v2 scopes to vendors | ⚠️ partial | `lib/ehr_vendors.py:56-69` ships **v1** spelling (`user/Patient.read`) to ALL vendors |
| B5 | Per-vendor / minimum-necessary scope sets | ⚠️ partial | one shared `_DEFAULT_SCOPES` for epic/cerner/athena/smart (`ehr_vendors.py:111,123,133,153`) |

**Top finding**: Solace can *speak* v2 but *requests* v1, identically across all four
vendors. Reviewers expect v2 `cruds` requests and a tailored, justified scope set per
vendor. Mechanically a small change (swap the `_DEFAULT_SCOPES` tuple, possibly per
vendor) — see remediation R1.

---

## C. US Core / USCDI data conformance

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| C1 | FHIR R4 throughout | ✅ | `lib/ehr_vendors.py:80`; all adapters R4 |
| C2 | DocumentReference: LOINC type + `category=clinical-note` | ✅ | `fhir_writer.py:79-119` |
| C3 | Condition: `category=problem-list-item`, ICD-10, SNOMED dual-code | ✅ | `fhir_writer.py:122-137`; Epic dual-code `ehr_epic.py:318-361` |
| C4 | AllergyIntolerance: clinical+verification status, RxNorm drugs | ✅ | `fhir_writer.py:140-149`; Oracle RxNorm `ehr_oracle.py:350-396` |
| C5 | Observation vitals: LOINC + UCUM `code` + `category=vital-signs` | ✅ | `fhir_writer.py:154-192` |
| C6 | Immunization: CVX + `primarySource` | ✅ | `fhir_writer.py:207-218` |
| C7 | MedicationStatement (med-rec, not order) | ✅ | `fhir_writer.py:221-258` |
| C8 | Provenance (+ HTI-1 DSI source attribute) | ✅ | `fhir_writer.py:262-325` |
| C9 | Read path normalizes US Core resources safely | ✅ | `fhir_patient_search.py:455-552` |
| C10 | **US Core profile validation** (Inferno / HL7 validator) in CI | ❌ missing | only `tests/ehr/test_fhir_writer.py` asserts builder *shape*, not US Core conformance |
| C11 | Identity-matching safety on read (no wrong-chart) | ✅ | `fhir_patient_search.py:208-289` (refuses ambiguous/DOB-conflict matches) |

**Top finding**: resource **builders** are US-Core-shaped, but there is **no automated
US Core profile validation**. Vendors run Inferno; Solace has no equivalent gate. C10 is
the biggest *data*-conformance gap.

---

## D. Per-vendor wire quirks

| # | Vendor | Requirement | Status | Evidence |
|---|--------|-------------|--------|----------|
| D1 | Epic | 201 + empty body, id in `Location` | ✅ | `ehr_epic.py:229-255` |
| D2 | Epic | OperationOutcome error parse | ✅ | `ehr_epic.py:105-130` |
| D3 | Epic | Problem-list `Condition` SNOMED-primary | ✅ | `ehr_epic.py:318-361` |
| D4 | Epic | Observation LOINC+UCUM; writable-code allowlist | ⚠️ verify | builder ✅ `ehr_epic.py:399-429`; **Epic's per-version writable LOINC list — verify on portal** |
| D5 | Oracle | Plain create, 201/Location, fhir+json | ✅ | `ehr_oracle.py:154-253` |
| D6 | Oracle | Required category/status fields, RxNorm allergy | ✅ | `ehr_oracle.py:303-443` |
| D7 | athena | Dual surface (FHIR + REST), token cache | ✅ | `ehr_athena.py:246-350` |
| D8 | athena | `client_credentials` + Basic auth | ✅ | `ehr_athena.py:268-305` |
| D9 | athena | Allergies replace-list PUT; vitals clinicalelementid | ✅ | `ehr_athena.py:393-475, 507-530` |
| D10 | Gateway | Retry/backoff, dry-run, audit hook, lazy adapters | ✅ | `ehr_gateway.py:249-301, 439-511` |

---

## E. Wiring + operational gaps (code is built but not connected)

| # | Gap | Status | Evidence |
|---|-----|--------|----------|
| E1 | Oracle adapter **not wired** into `routers/ehr.py` | ⚠️ | wiring documented but unapplied `ehr_oracle.py:483-518` |
| E2 | athena adapter **not wired** into `routers/ehr.py` | ⚠️ | `ehr_athena.py:533-574` (`ROUTER_WIRING`) |
| E3 | Gateway `read_resource` has **no vendor read adapters** | ⚠️ | returns `[]` for epic/oracle/athena `ehr_gateway.py:536-539` |
| E4 | Live writes default to **local mock store** when no base/token | ⚠️ by-design | `fhir_writer.py:332-334`; adapters fall back offline (`ehr_epic.py:187-188`, `ehr_oracle.py:201-209`) |
| E5 | Epic/Cerner/athena hidden until `client_id` set | ✅ by-design | `ehr_vendors.py:163-171` |

**E1/E2** are not blockers for *sign-in* (auth flow is fully wired in `ehr_auth.py`) but
are blockers for **write-back** through those vendors. E3 means clinician-facing reads
from a live Epic/Oracle/athena chart go through `fhir_patient_search.py` (search) rather
than the gateway, and the gateway's vendor read path is a stub.

---

## F. Program / legal gaps (NOT code — the real blockers)

| # | Gap | Status | Notes |
|---|-----|--------|-------|
| F1 | **SOC 2 Type II and/or HITRUST attestation** | ❌ missing | Solace has controls (CONSTITUTION SEC/COMP rules) but **no third-party attestation**. This is the #1 production-review blocker for Epic and Oracle. 6-12 mo lead time. |
| F2 | Production `client_id` requested from each vendor | ❌ not started | sandbox only today (`ehr_vendors.py:121,132,152`) |
| F3 | Marketplace/Showroom listing | ❌ not started | requires passed review + collateral |
| F4 | Inferno SMART STU2 + US Core pass report | ❌ missing | reviewers expect it (smart-conformance.md §3) |
| F5 | Scope-justification + data-flow doc | ❌ missing | required by all three questionnaires |
| F6 | BAA template (Solace = Business Associate) | verify | Solace is a BA, customer is CE; have template ready |
| F7 | Per-customer enablement (each hospital admin) | code-ready | env override `ehr_vendors.py:73-74` lets one binary serve many tenants |

---

## G. Prioritized remediation (code-side, quick wins first)

- **R1 (S, code)** — Request **SMART v2 `cruds`** scopes, per vendor, minimum-necessary.
  Edit `_DEFAULT_SCOPES` / add per-vendor scope tuples in `lib/ehr_vendors.py:56-69`.
  v2 builder already exists (`lib/smart_auth.py:290-306`). Closes B4/B5.
- **R2 (M, code)** — Wire Oracle + athena adapters into `routers/ehr.py` per the
  documented wiring blocks (`ehr_oracle.py:483-518`, `ehr_athena.py:533-574`). Closes
  E1/E2.
- **R3 (M, test)** — Add **US Core profile validation** (Inferno or HL7 validator) over
  the `fhir_writer.build_*` outputs in `tests/ehr/`. Closes C10; produces the F4 report.
- **R4 (S, code, optional)** — Verify id_token **JWKS signature** (`lib/smart_auth.py`)
  for strict reviewers. Closes A13.
- **R5 (L, program)** — Start **SOC 2 Type II / HITRUST** now (longest lead). Closes F1.
- **R6 (M, program)** — Request production `client_id`s + draft scope-justification &
  data-flow docs. Closes F2/F5; unblocks F3.

---

## TOP FINDINGS (for the lead)

1. **Auth flow is production-grade and the strongest part of Solace.** SMART App Launch
   v2 — PKCE S256, discovery, `state`/`nonce`, EHR + standalone launch, no-token-in-URL
   handoff, refresh via opaque handle, RS384 `private_key_jwt` — is all implemented and
   correct (`routers/ehr_auth.py`, `lib/smart_auth.py`). This clears the SMART technical
   bar for all three vendors.

2. **Scopes are requested in SMART v1 spelling, identically to every vendor**
   (`lib/ehr_vendors.py:56-69`). Solace can parse/build v2 but doesn't request it. Easy
   fix, but reviewers will notice. Per-vendor minimum-necessary scope sets are also
   missing.

3. **No US Core conformance gate.** Resource builders are US-Core-shaped
   (`fhir_writer.py`) but nothing validates them against the profiles. Vendors run
   Inferno; Solace must too, and must produce that report.

4. **Oracle and athena write adapters are built but not wired into a router**
   (`ehr_oracle.py:483-518`, `ehr_athena.py:533-574`). Sign-in works for all vendors;
   write-back only flows for the generic/Epic paths until wiring lands.

5. **The real blocker is non-code: SOC 2 Type II / HITRUST attestation (F1).** Epic and
   Oracle production reviews effectively require it for PHI access, and it has a
   6-12 month lead time. Everything else is weeks; this is the gating item to start now.

6. **Per-customer model is already handled in code.** Every vendor endpoint + client_id
   is env-overridable (`ehr_vendors.py:73-74`), so one binary serves sandbox and each
   customer tenant — no code change per hospital, only config.
