# Solace — Security Architecture

**Prepared for HackFW 2026 judges.**

Solace handles real patient health information. This document details every security control in the system — from the network edge to the database row — and maps each one to the relevant HIPAA technical safeguard.

---

## Summary

| Control | Implementation |
|---|---|
| Network perimeter | AWS WAFv2 (4 managed rule groups) + CloudFront TLS 1.2+ |
| CORS | Explicit origin allowlist — no wildcards |
| Abuse prevention | IP-bound one-time nonces + identity rate limiting + auto-blocklist |
| Prompt injection | Pre-Claude content scanner (reject + sanitize + PHI redact) on all paths |
| Encryption at rest | One CMK (KMS) across all DynamoDB tables, S3, and Secrets Manager |
| Encryption in transit | TLS 1.2+ enforced at CloudFront, API Gateway, and S3 bucket policy |
| Authentication | JWT HS256 (clinicians) + brute-force lockout (5 failures → 30-min lock) |
| EHR OAuth | SMART-on-FHIR with DDB-backed state, redirect allowlist, one-time handoff codes |
| HIPAA §164.508 | Explicit consent gate — no PHI flows to AI providers without it |
| HIPAA §164.514 | 15-pattern PHI redaction before all AI payloads (Safe Harbor identifiers) |
| HIPAA §164.312 | CMK encryption, TLS, audit trail, JWT auth, AI attribution log |
| Audit trail | DynamoDB (90-day hot) + S3 archival (6-year cold, CMK-encrypted) |
| AI attribution | Provider + model + token counts persisted on every patient record |
| AI provider BAA | All AI services routed through AWS BAA perimeter (Bedrock, Transcribe, Polly) |
| Voice agent | Content guard + rate limiting + blocklist on all voice paths |
| Phone number storage | SHA-256 hashed — never stored in plaintext |

---

## Layer 1 — Network perimeter (WAFv2 + CloudFront)

All traffic enters through **AWS CloudFront** backed by **WAFv2** with four managed rule groups active before a single request reaches Lambda:

- **AWSManagedRulesAmazonIpReputationList** — blocks known botnets and bad actors at the edge
- **AWSManagedRulesKnownBadInputsRuleSet** — blocks SQLi, XSS, and known exploit patterns
- **AWSManagedRulesCommonRuleSet** — OWASP Top 10 protections
- **Rate-based rule** — hard per-IP throttle at the AWS edge, before Lambda warms up

CloudFront enforces **TLS 1.2 minimum**. The S3 media bucket has a bucket policy that rejects any non-TLS request (`aws:SecureTransport: false → Deny`). There is no cleartext path to patient data anywhere in the stack.

### CORS policy

CORS is locked to an explicit origin allowlist — no wildcards:

- `https://solaceaidemo.vercel.app` (production)
- `https://solace-page.vercel.app` (production mirror)
- `http://localhost:5173`, `http://localhost:3000` (local dev only)
- Additional origins via `SOLACE_CORS_ORIGINS` env var for staging/preview

Allowed methods and headers are explicitly enumerated (no `*` fallback).

---

## Layer 2 — Intake nonces (one-time, IP-bound tokens)

When a patient's phone loads the QR intake page, it calls `POST /start-intake` and receives a **cryptographically random 24-byte nonce** (via `secrets.token_urlsafe`). That nonce is:

- **Bound to the caller's IP** — stored as an HMAC-SHA256 hash (never plaintext) keyed on the JWT signing key from Secrets Manager
- **Bound to the caller's User-Agent** — soft binding (logged but non-blocking, since iOS Safari changes UA on add-to-home-screen)
- **Single-use** — atomically consumed via DynamoDB conditional update (`ConditionExpression: used = false`); a race between two parallel requests causes the second to fail cleanly
- **4-hour TTL** — DynamoDB TTL auto-expires unused nonces

**Attack surface closed:** a bot cannot `curl /intake` with crafted payloads — it must load the real QR page and submit from the same IP. A nonce farmed on one machine cannot be spent on another. A stolen nonce cannot be replayed after first use.

---

## Layer 3 — Identity-keyed rate limiting

API Gateway throttles by raw IP, which rotating proxies defeat. Solace adds a second layer: a stable **identity = HMAC-SHA256(IP + User-Agent)** is derived per request and tracked in DynamoDB with atomic counter increments (`ADD` expression — race-free under concurrency).

| Action | Hourly cap per identity |
|---|---|
| Start intake (page load) | 120 requests |
| Submit intake | 10 requests |
| Transcribe audio | 20 requests |
| Audio seconds consumed | 300 seconds |
| Single audio upload | 120 seconds absolute cap |
| Voice simulator | 200 requests |
| Pain flag (patient button) | 30 requests |

Rate-limit breaches return `429` with a `Retry-After` header showing the exact bucket reset time. Quota overages are audit-logged but do **not** count toward the abuse blocklist — a real patient reloading the page should not be auto-blocked.

---

## Layer 4 — Automatic abuse blocklist

An identity that triggers **5 or more abuse events within 10 minutes** is placed on a **1-hour blocklist** in `solace-blocklist` (DynamoDB). Every patient-facing endpoint calls `blocklist.enforce()` as its first action — before parsing the request body, before any DB lookup.

The blocklist check uses `ConsistentRead=True` to eliminate the eventual-consistency window between block creation and enforcement.

**Events that increment the abuse counter:**
- Invalid or missing nonce
- Nonce submitted for wrong hospital
- IP fingerprint mismatch on nonce
- Prompt injection detected in transcript
- Data exfiltration intent detected

**Events that do not increment the counter:**
- Legitimate rate-limit hits (quota exceeded) — avoids double-punishing real users
- UA mismatch on nonce (soft signal only)
- Blocklist hits themselves (avoids counter inflation)

---

## Layer 5 — Pre-Claude content guard (prompt injection + PHI redaction)

Every transcript — whether from Whisper, typed directly, or via voice agent — passes through `content_guard.scan()` before reaching any AI provider. Three tiers:

### Tier 1: Hard reject (HTTP 422)
Regex patterns matched case-insensitively. Any match aborts the request and writes an audit event:

| Pattern type | Example trigger |
|---|---|
| Ignore-previous injection | "ignore all previous instructions" |
| Persona override | "you are now DAN / unrestricted / jailbroken" |
| LLM control tokens | `[INST]`, `<\|im_start\|>`, `<\|system\|>` |
| Data exfiltration intent | "list all patients", "dump the database", "reveal your API key" |
| Direct override | "you must ignore / bypass / override" |
| Prompt leak | "reveal your system prompt", "print your hidden instructions" |

### Tier 2: Sanitize and allow
Stripped silently; request proceeds with cleaned text:
- Fenced code blocks
- Generic LLM control tokens
- Template interpolation (`{{...}}`)

### Tier 3: PHI redaction (HIPAA §164.514 Safe Harbor — 15 identifiers)
Applied to every transcript before it is sent to any AI provider:

| Pattern | Replacement |
|---|---|
| SSN (`###-##-####`) | `[REDACTED:SSN]` |
| Credit card (16-digit) | `[REDACTED:CARD]` |
| Phone number | `[REDACTED:PHONE]` |
| Email address | `[REDACTED:EMAIL]` |
| Date of birth (MM/DD/YYYY etc.) | `[REDACTED:DOB]` |
| Street address | `[REDACTED:ADDRESS]` |
| ZIP code (5 or 9-digit) | `[REDACTED:ZIP]` |
| Medical Record Number | `[REDACTED:MRN]` |
| Insurance member ID | `[REDACTED:MEMBER_ID]` |
| Account number | `[REDACTED:ACCOUNT]` |
| Driver's license | `[REDACTED:LICENSE]` |
| VIN (vehicle ID) | `[REDACTED:VIN]` |
| Device serial/identifier | `[REDACTED:DEVICE_ID]` |
| URL (potential PHI in path) | `[REDACTED:URL]` |
| IP address | `[REDACTED:IP]` |

---

## Layer 6 — HIPAA technical safeguards

Three sections of 45 CFR Part 164 implemented directly in code:

### §164.508 — Authorization for PHI disclosure to third parties
The intake, transcription, and insurance scan handlers check `consent_granted == "true"` before any PHI flows to AI providers. If the patient has not checked the consent box:
- Request is rejected with HTTP 403
- An audit event (`abuse.intake_no_consent`) is written
- The patient's identity is flagged

Consent version and grant timestamp are persisted on every patient record: `consent_granted_at` (ISO 8601 UTC), `consent_version`.

### §164.514 — Minimum-necessary standard
The content guard's PHI redaction tier (above) strips all 15 Safe Harbor identifiers from transcripts before AI calls. Claude and Transcribe receive symptom narratives, not SSNs or card numbers.

### §164.312 — Technical safeguards
- **Access control**: JWT HS256 tokens for clinicians; bcrypt PINs stored in Secrets Manager; brute-force lockout (5 failures in 15 min → 30-min lock)
- **Audit controls**: every action written to `solace-audit-log` (see Layer 8)
- **Integrity**: CMK-encrypted storage prevents silent tampering at rest
- **Transmission security**: TLS 1.2+ enforced end-to-end (CloudFront → API Gateway → S3)

---

## Layer 7 — Encryption at rest (single CMK)

One **Customer-Managed KMS Key** (`alias/solace`) encrypts every data store:

| Resource | Encryption |
|---|---|
| All DynamoDB tables (patients, hospitals, prescriptions, notes, calls, appointments, clinicians, audit-log, nonces, quotas, blocklist, idempotency) | SSE-KMS with solace CMK |
| S3 media bucket (photos, audio) | SSE-KMS with solace CMK (BucketKey enabled) |
| S3 audit archive bucket | SSE-KMS with solace CMK |
| Secrets Manager (API keys, JWT key, PINs) | CMK-encrypted |
| CloudTrail log bucket | CMK-encrypted |

Annual **automatic key rotation** is enabled. All setup scripts resolve the CMK by alias (`alias/solace`) — no hardcoded key UUIDs.

The HMAC key used for nonce fingerprinting and identity hashing reuses the JWT signing key from Secrets Manager — no additional secret surface.

---

## Layer 8 — Audit trail (HIPAA §164.530(j)(2) — 6-year retention)

Every action in the system writes a record to `solace-audit-log`. Each record contains:

| Field | Value |
|---|---|
| `clinician_id` | JWT claim or `"anonymous"` for patient-side events |
| `clinician_name` | From JWT claim |
| `action` | Namespaced string, e.g. `patient.view`, `abuse.intake_bad_nonce`, `pain_flag.triggered` |
| `patient_id` | Affected patient (if applicable) |
| `source_ip` | From `X-Forwarded-For` |
| `request_id` | AWS X-Ray trace ID |
| `status_code` | HTTP response code |
| `ts` | ISO 8601 UTC timestamp |

### Dual-write retention strategy

| Tier | Store | TTL | Purpose |
|---|---|---|---|
| Hot | DynamoDB | 90 days | Live dashboard queries, recent audit lookups |
| Cold | S3 (`audit-archive/YYYY/MM/DD/{id}.json`) | 6 years | HIPAA §164.530(j)(2) compliance |

Every audit record is dual-written: synchronously to DynamoDB and asynchronously to S3 (CMK-encrypted). S3 archival failure is non-blocking — the DynamoDB record is never lost.

Writes are non-blocking (submitted to a thread pool executor) so audit logging never adds latency to the request path.

Abuse events feed back into the blocklist counter atomically — `audit.record()` calls `blocklist.record_abuse()` automatically for any action starting with `abuse.`.

---

## Layer 9 — AI provider BAA coverage

All three AI services are routed through AWS-managed services covered under the **AWS Business Associate Agreement (BAA)**:

| Function | AWS Service | Replaces |
|---|---|---|
| LLM inference | **AWS Bedrock** (Claude via Anthropic) | Direct Anthropic API |
| Speech-to-text | **AWS Transcribe** | OpenAI Whisper API |
| Text-to-speech | **AWS Polly** (Neural voices) | ElevenLabs API |

Each service is switchable via environment variable (`CLAUDE_PROVIDER`, `TRANSCRIPTION_PROVIDER`, `TTS_PROVIDER`) — the direct API paths remain as fallback but default to the BAA-covered AWS path.

---

## Layer 10 — AI attribution log (per-patient inference record)

Every call to an AI provider for a patient appends an entry to an in-request `AILog` object:

```
provider: "bedrock"
model: "claude-sonnet-4-5"
input_tokens: 847
output_tokens: 312
duration_ms: 2341
call_type: "prebrief"
```

At the end of intake, this log is serialized as JSON and stored on the patient record itself in DynamoDB (`ai_processing_log` field). This means:

- Auditors can reconstruct exactly which AI model made which inference for which patient
- If the provider is swapped from `bedrock` to `anthropic` (one env var flip), the log reflects it
- Token counts are available for cost attribution and billing transparency

---

## Layer 11 — Voice agent security

The voice agent (Twilio + browser simulator) has its own security stack:

### Content guard on all voice paths
- **Twilio turn**: `content_guard.scan()` runs on every transcribed utterance before Claude. Prompt injection → graceful hangup.
- **Simulator turn**: same `content_guard.scan()` on user text before Claude. Injection → HTTP 422.

### Rate limiting + blocklist
- Voice simulator: 200 requests/hour per identity
- Pain flag button: 30 requests/hour per identity
- Both enforce `blocklist.enforce()` as first action

### Phone number handling
- Caller phone numbers are SHA-256 hashed before storage (`last4:hash` format)
- Appointment records store `patient_phone_hash`, never raw numbers
- Twilio recording downloads use HTTP Basic Auth (Account SID + Auth Token)

---

## Layer 12 — EHR OAuth security

SMART-on-FHIR clinician sign-in includes:

- **Redirect URI allowlist**: `_validate_redirect_uri()` prevents open-redirect attacks
- **DynamoDB-backed OAuth state**: CSRF tokens stored in `solace-idempotency` table (survives Lambda cold starts, multi-container deployments)
- **One-time handoff codes**: JWT is never passed in URLs. Backend stores the session behind a short-lived code (2-min TTL); frontend exchanges via `POST /api/auth/ehr/exchange`. Replay returns 400.

---

## Layer 13 — CloudWatch alarms + SNS alerts

13 CloudWatch alarms are configured:

- Lambda error rate, throttle count, p99 duration, cold start count
- API Gateway 5xx rate, 4xx rate, request throughput
- DynamoDB throttled requests (read + write, per critical table)
- WAF blocked request rate

All alarms notify via SNS → email. Security-specific events (abuse blocks, consent failures, injection attempts) also fire EventBridge rules → SNS independently of CloudWatch.

---

## Known gaps (honest disclosure)

| Gap | Status |
|---|---|
| AWS GuardDuty | Not enabled (cost; would add threat detection on DynamoDB + S3 + Lambda) |
| MFA on AWS root account | Not verifiable via code — assumed enabled by account policy |
| Formal penetration test | Not performed; controls are designed to standard but untested by a third party |
| Audit dead-letter queue | S3 archival failures are logged but not retried — no DLQ yet |

---

## Infrastructure scripts (reproducible setup)

All security controls are provisioned via idempotent Python scripts. Running them on a fresh AWS account produces the documented posture:

```bash
python scripts/setup_security.py           # CMK (alias/solace), Secrets Manager, CloudTrail
python scripts/setup_aws.py                # Core DynamoDB tables (all CMK-encrypted)
python scripts/setup_clinician_auth.py     # Clinician table, audit-log, JWT key, demo seeds
python scripts/setup_abuse_prevention.py   # Nonce, quota, blocklist, idempotency tables (CMK)
python scripts/setup_waf_cloudfront.py     # WAFv2 + CloudFront distribution
python scripts/setup_security_alerts.py your@email.com  # SNS + EventBridge rules
python scripts/setup_cloudwatch_alarms.py  # 13 CloudWatch alarms
```

All scripts resolve the CMK by alias (`alias/solace`) — no hardcoded key UUIDs.

---

*Solace — HackFW 2026 | Dhruv Jain & Sriyan Bodla*
