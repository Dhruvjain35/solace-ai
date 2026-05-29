# Epic on FHIR — sandbox app registration

A 30-minute self-service signup at <https://fhir.epic.com/Developer/Apps> wires real Epic SMART-on-FHIR sign-in into Solace. Free, no contract, immediate access to Epic's R4 sandbox with synthetic test patients.

Below is the exact form data Epic asks for. Open this doc + the Epic developer portal side by side and copy-paste each field.

## Prerequisites

- Personal email (any domain). Epic creates one free developer account per email.
- 30 minutes.
- This doc + the live Solace API URL: `https://djfjrel7b1ebi.cloudfront.net`

## Steps

### 1. Create an Epic on FHIR account

1. Go to <https://fhir.epic.com/>
2. Click **Sign up** in the top-right
3. Verify email
4. Sign in to the developer portal

### 2. Create a new app

1. Click **Apps** → **Create**
2. Choose **R4** (FHIR version)

### 3. Fill the app form

| Field | Value |
|---|---|
| **Application Name** | `Solace Triage (Sandbox)` |
| **Application Audience** | `Clinicians or Administrative Users` |
| **Application Type** | `Confidential Client` (public client also works; confidential is more flexible) |
| **Incoming API Endpoints** | Leave empty for now |
| **SMART on FHIR Version** | `STU3` then upgrade to `R4` if presented |
| **Redirect URI** | `https://djfjrel7b1ebi.cloudfront.net/api/auth/ehr/callback` |
| **Backend OAuth client?** | No (for now — patient-app flow is user-launched) |
| **Description** | `AI-powered ER triage with patient intake, ambient scribe, and EHR auto-population. Reads Patient, AllergyIntolerance, MedicationRequest, Condition, Encounter, and Observation; writes DocumentReference and Condition.` |

### 4. Select FHIR scopes

Toggle ON every scope listed below. Solace already requests this exact set in `backend/lib/ehr_vendors.py:43-58`.

**User-level (clinician acting on behalf of patients):**
- `user/Patient.read`
- `user/Practitioner.read`
- `user/Encounter.read`
- `user/Observation.read`
- `user/MedicationRequest.read`
- `user/AllergyIntolerance.read`
- `user/Condition.read`

**Write-back (for the EHR push feature):**
- `user/DocumentReference.write`
- `user/Condition.write`

**SMART:**
- `openid`
- `fhirUser`
- `launch`
- `online_access`
- `profile`

### 5. Save and capture the client ID

Epic generates a `Non-Production Client ID` (a UUID). **Copy it.** This is the value to drop into Solace as `SOLACE_EPIC_CLIENT_ID`.

You will also see a `Production Client ID` field — leave that for the App Orchard listing later.

### 6. Flip the Lambda env var

```bash
aws lambda update-function-configuration \
  --function-name solace-api \
  --region us-east-1 \
  --environment "Variables={\
    SOLACE_MODE=aws,\
    HEALTHSCRIBE_ROLE_ARN=arn:aws:iam::704229156617:role/solace-healthscribe-data-access,\
    SOLACE_EPIC_CLIENT_ID=<paste-the-client-id-here>\
  }"
```

(Keep the existing env vars in the same update — Lambda replaces the whole env block on each call.)

### 7. Test the live flow

1. Open `https://solaceaidemo.vercel.app/demo/clinician`
2. Click **Sign in with Epic** on the login screen
3. Epic's login appears — use any of these sandbox creds:
   - Username: `fhircamila` / Password: `epicepic1` (general patient)
   - Username: `fhirderrick` / Password: `epicepic1` (alternate)
4. Consent screen → click **Allow**
5. You land back on the Solace dashboard, signed in as the Practitioner mapped to that login

### 8. Confirm a real Patient.read

Once signed in, open the clinician console and hit any patient card. The `EHRPanel` will fetch from the Epic sandbox using the access token Solace minted from the Epic OAuth response. Real Synthea-generated test data shows up.

## What this unlocks

- Real Epic SMART-on-FHIR sign-in (no more PIN-only path)
- Real Patient demographics, allergies, meds, conditions, encounters from Epic's sandbox
- Real `DocumentReference` write-back via the existing `/ehr-write` endpoint (the SOAP note from Ambient Scribe lands in the Epic test EHR)

## Cerner and Athena — same playbook, slower portals

The exact pattern repeats:

| Vendor | Portal | Time |
|---|---|---|
| **Oracle Cerner / HealtheLife** | <https://code.cerner.com/> | ~1 hour (extra IDM step) |
| **athenahealth** | <https://developer.athenahealth.com/> | 1–2 weeks (manual approval) |

For each, the redirect URI is identical (`/api/auth/ehr/callback`), the scope set is identical, and Solace already has the vendor row wired in `backend/lib/ehr_vendors.py`. After registration, set `SOLACE_CERNER_CLIENT_ID` or `SOLACE_ATHENA_CLIENT_ID` in the same Lambda env update.

## Production path (later, not for the sandbox demo)

Production requires:
1. App Orchard listing application (Epic, free, ~2 weeks)
2. SOC 2 Type II attestation (~6 months + ~$30K)
3. Customer-specific Epic instance registration per hospital

The sandbox flow above gets us through investor demos and pilot conversations. Production listing is a quarter-long project that starts after pilot signal.
