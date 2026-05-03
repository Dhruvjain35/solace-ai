# EHR integration (SMART-on-FHIR)

Solace clinicians sign in via SMART-on-FHIR OAuth. Vendor catalog + endpoints
live in `backend/lib/ehr_vendors.py`; OAuth flow lives in
`backend/routers/ehr_auth.py`. PKCE (S256) is enforced — required by the SMART
spec for public clients.

The default deployment ships with **SMART Health IT** as a working sandbox
(no registration required), Epic / Cerner / Athena slots are real but require
an EHR-side client registration before they're surfaced to users.

---

## What works out of the box

| Vendor | Status | Why |
|---|---|---|
| **SMART Health IT** | ✅ Live | Boston Children's-hosted public sandbox. Accepts any client_id. |
| **Epic** | ⚪ Slot | Needs `SOLACE_EPIC_CLIENT_ID` env var (free, 30-min self-service registration) |
| **Oracle Cerner** | ⚪ Slot | Needs `SOLACE_CERNER_CLIENT_ID` (free at code.cerner.com) |
| **Athenahealth** | ⚪ Slot | Needs `SOLACE_ATHENA_CLIENT_ID` (developer.athenahealth.com) |

The vendor list endpoint (`GET /api/auth/ehr/vendors`) only surfaces vendors with
a configured `client_id`. SMART is always on; the others appear once you wire them.

---

## Onboarding a real Epic client

1. Sign up at https://fhir.epic.com/Developer.
2. Apps → Create App. Pick **Backend Services** if you want server-to-server
   workflows, **Patient Facing** for SMART launch from MyChart, or **Provider
   Facing** (most common) for clinician sign-in like ours.
3. Required fields:
   - **Application audience:** Provider Facing
   - **Incorporates this technology:** SMART on FHIR
   - **OAuth redirect URI:** `https://djfjrel7b1ebi.cloudfront.net/api/auth/ehr/callback`
     (production) or your own CloudFront domain.
   - **Scopes:** select these (must match what we request in `_DEFAULT_SCOPES`):
     - openid, fhirUser, launch, online_access, profile
     - user/Patient.read, user/Practitioner.read, user/Encounter.read,
       user/Observation.read, user/MedicationRequest.read,
       user/AllergyIntolerance.read, user/Condition.read
4. Submit. Epic emails the **Sandbox Client ID** within minutes.
5. Set the env var on Lambda:
   ```bash
   aws lambda update-function-configuration \
     --function-name solace-api \
     --environment "Variables={SOLACE_EPIC_CLIENT_ID=<your-sandbox-id>,...keep existing vars...}"
   ```
6. Redeploy. The "Sign in with Epic" button now appears on the login screen.

For **production** Epic (real PHI), repeat with the production app form. Each
production hospital that wants to use Solace needs to enable your app in their
own Epic instance — that part is per-hospital, not Epic-wide.

---

## Onboarding Oracle Cerner

1. https://code.cerner.com → register a developer account.
2. My Apps → Create App. Type: **Provider** (SMART launch on EHR).
3. Same scope set as above. Redirect URI:
   `https://djfjrel7b1ebi.cloudfront.net/api/auth/ehr/callback`.
4. Cerner issues a sandbox Client ID immediately.
5. Set `SOLACE_CERNER_CLIENT_ID=<id>` on Lambda, redeploy.

The default sandbox tenant in `ehr_vendors.py` is `ec2458f2-1e24-41c8-b71b-0e701af7583d`
(Cerner's public test tenant). For a hospital's real tenant, override:
- `SOLACE_CERNER_AUTHORIZE_URL`
- `SOLACE_CERNER_TOKEN_URL`
- `SOLACE_CERNER_FHIR_URL`

---

## Onboarding Athenahealth

1. https://developer.athenahealth.com → register.
2. Apps → New App. Pick the **SMART** auth flavor.
3. Scopes + redirect URI as above.
4. Set `SOLACE_ATHENA_CLIENT_ID=<id>`.

---

## Local / offline testing

If you can't reach the SMART Health IT sandbox (airplane, locked-down network),
swap to the in-process mock provider:

```bash
SOLACE_SMART_AUTHORIZE_URL=https://djfjrel7b1ebi.cloudfront.net/api/auth/ehr/mock-authorize
SOLACE_SMART_TOKEN_URL=https://djfjrel7b1ebi.cloudfront.net/api/auth/ehr/mock-token
SOLACE_SMART_FHIR_URL=https://djfjrel7b1ebi.cloudfront.net/api/auth/ehr/mock-fhir/smart
```

The mock authorize endpoint instantly approves and returns a fake auth code; the
mock token endpoint returns a synthetic Practitioner pulled from the seeded
`solace-clinicians` table. End-to-end flow works without any external network.

---

## How the flow runs (technical)

```
Browser                   Solace API                    Vendor (Epic / SMART)
  │                          │                             │
  │  click "Sign in"         │                             │
  ├─────────────────────────>│                             │
  │                          │  GET /launch?vendor=epic    │
  │                          │  - generate PKCE pair       │
  │                          │  - store state              │
  │                          │  - 302 → vendor authorize   │
  │<─────────────────────────┤                             │
  │  user lands at vendor login + consent screen           │
  ├─────────────────────────────────────────────────────>  │
  │  vendor 302 → /callback?code=...&state=...             │
  │<─────────────────────────────────────────────────────  │
  │                          │                             │
  │  GET /callback           │                             │
  ├─────────────────────────>│                             │
  │                          │  POST token                 │
  │                          │   + PKCE verifier           │
  │                          ├────────────────────────────>│
  │                          │   <- access_token,          │
  │                          │      id_token,              │
  │                          │      fhirUser ref           │
  │                          │<────────────────────────────┤
  │                          │                             │
  │                          │  GET FHIR Practitioner/{id} │
  │                          ├────────────────────────────>│
  │                          │   <- HumanName, role        │
  │                          │<────────────────────────────┤
  │                          │                             │
  │                          │  mint Solace JWT (HS256)    │
  │                          │  with embedded EHR vendor   │
  │                          │  + FHIR base + access_token │
  │                          │                             │
  │  302 → /ehr/callback?handoff=<json>                    │
  │<─────────────────────────┤                             │
  │  parse handoff, save session, → /clinician dashboard   │
```

The dashboard sidebar then renders "Connected to {vendor.label}" using the
`session.ehr_*` fields. Downstream FHIR queries (Patient lookup, Encounter
search, etc.) re-use the same `fhir_access_token` against `fhir_base_url`.

---

## Known limitations (next session work)

- **No refresh-token handling yet.** When the FHIR access token expires (~1 hr
  on Epic, varies by vendor), downstream FHIR queries 401. Session JWT still
  valid → user thinks they're signed in but EHR data goes stale. Next step is
  to call the token endpoint with `grant_type=refresh_token` when a 401 comes
  back from a FHIR query.
- **Practitioner role parsing is naive.** We pull `qualification[0].code.text`
  which is good enough for sandboxes; real EHRs encode role via SNOMED + Epic-
  specific extension elements. Worth a Codex pass if specific roles drive
  decision-support behavior.
- **Patient lookup is still hitting our seeded `solace-ehr-patients` DDB**, not
  the connected EHR's FHIR `Patient` resource. The session has the FHIR base
  URL + access token; the next move is updating `routers/ehr.py` to issue a
  real FHIR `Patient?identifier=` query keyed on insurance member_id.
- **App Orchard / Cerner Code Console review.** The above is enough to hit
  vendor sandboxes. To touch real PHI in a real hospital, Solace needs to pass
  vendor security review (App Orchard for Epic, similar process for Cerner) —
  weeks-to-months, separate workstream from code.
