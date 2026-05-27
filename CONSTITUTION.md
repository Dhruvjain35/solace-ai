# Solace Project Constitution

> Version: 1.0.0 | Last Updated: 2026-05-12
> Project Type: single-app (FastAPI+Mangum Lambda backend + Vite+React+TS frontend)

Solace is a clinical triage web app handling **PHI**. Every rule here is grounded in evidence from the live codebase. Frameworks referenced: **HIPAA**, **SOC 2**, **CCPA**, **AWS Shared Responsibility**, **WCAG 2.1 AA**.

## Level System

| Level | Name | Blocking | Use Case |
|-------|------|----------|----------|
| **L1** | Must | Yes | Critical: security, compliance, correctness |
| **L2** | Should | Yes (manual review) | Important: needs human judgment |
| **L3** | May | No | Advisory: style, suggestions |

---

## Security

### SEC-001 — Secrets Manager Hydration on Startup (L1)

```yaml
level: L1
check: In AWS mode, all required secrets must be hydrated from AWS Secrets Manager before serving requests; missing keys must crash the app.
scope: backend/lib/config.py, backend/main.py
message: Secrets hydration failed in AWS mode — the app cannot serve without required keys.
```

Evidence: `backend/lib/config.py:62-110`, `backend/main.py:34`.

### SEC-002 — Log Redaction Filter Installed First (L1)

```yaml
level: L1
check: RedactPatientUUIDsFilter must be installed in main.py before any other module imports, so UUIDs and Bearer/nonce tokens never reach CloudWatch.
scope: backend/main.py
message: Log redaction filter not installed first — patient UUIDs or tokens may leak into CloudWatch.
```

Evidence: `backend/lib/log_redaction.py:1-62`, `backend/main.py:25-27`.

### SEC-003 — Blocklist Enforcement on Patient Endpoints (L1)

```yaml
level: L1
check: Every endpoint in /api/{hospital_id}/(intake|pain_flag|voice) must call blocklist.enforce(identity) as the first statement, before any request parsing.
scope: backend/routers/intake.py, backend/routers/pain_flag.py, backend/routers/voice.py
message: Patient endpoint missing blocklist.enforce() — abusive identities will not be short-circuited.
```

Evidence: `backend/routers/intake.py:69`, `backend/lib/blocklist.py:54-67`.

### SEC-004 — Consent Gate Before AI Calls (L1)

```yaml
level: L1
check: Before any AI provider call (transcription, triage, TTS, scribe, differential), verify consent_granted == "true" or reject with 403.
scope: backend/routers/intake.py, backend/services/*.py
message: Missing consent check before AI inference — violates HIPAA §164.508 authorization requirement.
```

Evidence: `backend/routers/intake.py:73-88`.

### SEC-005 — Content Guard Scan Before AI Submission (L1)

```yaml
level: L1
check: Call content_guard.scan(text, label, source_ip, user_agent) before sending any user-provided text to Claude/Whisper/Polly; reject if safe=False; use cleaned text in AI payloads.
scope: backend/services/transcription.py, backend/services/scribe.py, backend/services/differential.py
message: Transcript not scanned — prompt injection or PHI may reach third-party AI providers.
```

Evidence: `backend/lib/content_guard.py:132-192`, `backend/routers/intake.py:126-131,148-150`.

### SEC-006 — Redirect URI Allowlist (L1)

```yaml
level: L1
check: /launch and /callback endpoints must call _validate_redirect_uri(redirect_uri) and raise 400 on failure; allowlist defined at module level.
scope: backend/routers/ehr_auth.py
message: Redirect validation missing or bypassed — open-redirect attacks possible.
```

Evidence: `backend/routers/ehr_auth.py:77-79,153`.

### SEC-007 — Atomic Intake Nonces with Consistent Read (L2)

```yaml
level: L2
check: intake_nonce.require() must use ConsistentRead=True on get_item and ConditionExpression on update_item to mark used atomically; IP and UA must be hashed, not stored plaintext.
scope: backend/lib/intake_nonce.py, backend/routers/intake.py
message: Nonce check missing atomic consume or consistent read — replay or double-spend possible.
```

Evidence: `backend/lib/intake_nonce.py:89-110`.

### SEC-008 — Clinician JWT + Hospital ID Match (L2)

```yaml
level: L2
check: Clinician-only routers must use Depends(require_clinician); JWT verification must include hospital_id cross-check; no X-Clinician-PIN fallback paths.
scope: backend/routers/admin.py, backend/routers/patients.py, backend/routers/notes.py
message: Clinician endpoint missing JWT validation or hospital_id check — unauthorized cross-hospital access possible.
```

Evidence: `backend/lib/auth.py:19-53`.

### SEC-009 — Parameterized DynamoDB Keys (L2)

```yaml
level: L2
check: All DynamoDB queries must use boto3.dynamodb.conditions.Key() to build expressions; no f-string interpolation of user input into keys.
scope: backend/**/*.py
exclude: backend/.venv/**
message: Unsafe DynamoDB query — use Key() helper, not string interpolation.
```

Evidence: `backend/db/storage.py:238,269`, `backend/routers/ehr_auth.py:554`.

### SEC-010 — External HTTP Timeouts + URL Validation (L3)

```yaml
level: L3
check: requests.get() / httpx.get() must set timeout <= 30s; redirect URLs must pass _validate_redirect_uri() before use.
scope: backend/services/cohort_export.py, backend/routers/ehr_auth.py
message: External HTTP call missing timeout or URL validation — SSRF or hanging requests possible.
```

Evidence: `backend/services/cohort_export.py:66,84`, `backend/routers/ehr_auth.py:153`.

---

## Compliance

### COMP-001 — HIPAA Safe Harbor Redaction (L1, HIPAA)

```yaml
level: L1
check: All 15 HIPAA Safe Harbor identifiers (SSN, card, phone, email, DOB, address, ZIP, MRN, member_id, account, license, VIN, device, URL, IP) must be redacted from any text sent to AI providers via content_guard._PII_REDACTIONS.
scope: backend/lib/content_guard.py, backend/services/*.py
message: PHI identifier may reach AI payload — route through content_guard.scan() first.
```

Evidence: `backend/lib/content_guard.py:59-118`.

### COMP-002 — Audit Trail Immutability and 6-Year Retention (L1, HIPAA)

```yaml
level: L1
check: Every clinician action in routers must call audit.record(clinician_id, action, patient_id, source_ip) with dual-write to DynamoDB (90-day TTL) + S3 (CMK-encrypted, JSONL per day).
scope: backend/routers/*.py
exclude: backend/routers/health.py
message: Missing audit entry for patient access — HIPAA §164.530(j)(2) requires 6-year immutable audit log.
```

Evidence: `backend/lib/audit.py:25-76`.

### COMP-003 — Encryption at Rest via solace CMK (L1, HIPAA + AWS)

```yaml
level: L1
check: All patient data stores (DynamoDB, S3, Secrets Manager) must use the single solace CMK (alias/solace) for encryption; annual rotation enabled.
scope: scripts/setup_security.py, scripts/setup_aws.py, backend/lib/config.py
exclude: transient local-dev stores
message: Data resource missing solace CMK encryption — HIPAA §164.312(a)(2)(iv) and AWS shared responsibility require it.
```

Evidence: `scripts/setup_security.py:90-130`.

### COMP-004 — TLS 1.2+ Enforced in Transit (L1, HIPAA + AWS)

```yaml
level: L1
check: CloudFront enforces TLS 1.2 minimum; API Gateway and S3 bucket policies reject aws:SecureTransport=false. No cleartext paths to PHI.
scope: infrastructure (CloudFront distribution, API Gateway, S3 bucket policy)
message: Insecure transport detected — enforce TLS 1.2+ at every edge.
```

Evidence: `SECURITY.md:40-41`.

### COMP-005 — Default to BAA-Covered AWS AI Providers (L1, HIPAA)

```yaml
level: L1
check: CLAUDE_PROVIDER=bedrock, TRANSCRIPTION_PROVIDER=aws, TTS_PROVIDER=aws are defaults; direct third-party APIs are opt-in fallback only, gated by explicit env override.
scope: backend/lib/config.py
exclude: local dev overrides
message: PHI may flow to non-BAA AI provider — keep AWS-covered services as default.
```

Evidence: `backend/lib/config.py:22-32`.

### COMP-006 — Clinician Session Timeout + Brute-Force Lockout (L1, SOC 2 CC6)

```yaml
level: L1
check: ACCESS_TTL_SECONDS <= 1800 (30 min); MAX_FAILED_ATTEMPTS=5; LOCKOUT_WINDOW=900s; LOCKOUT_DURATION>=1800s.
scope: backend/lib/jwt_auth.py
exclude: local dev overrides
message: Session timeout or lockout weakened — SOC 2 CC6 logical-access controls require strict bounds.
```

Evidence: `backend/lib/jwt_auth.py:21-24`.

### COMP-007 — No Secrets in Source Control (L1, SOC 2 CC8)

```yaml
level: L1
pattern: "(api_key|apikey|secret|password|token|credential)\\s*[:=]\\s*['\"][^'\"]{8,}['\"]"
scope: "**/*.{ts,js,py,json,yaml,yml,env}"
exclude: "**/*.test.*, **/*.spec.*, .env.example, backend/.venv/**, node_modules/**"
message: Hardcoded secret detected — use AWS Secrets Manager (production) or .env (local, gitignored).
```

Evidence: `.gitignore:1-6`, `backend/lib/config.py:62-109`.

### COMP-008 — Phone Numbers Stored as SHA-256 Hash (L2, HIPAA + CCPA)

```yaml
level: L2
check: Caller phone numbers must be SHA-256 hashed before storage (last4:hash format); never persist plaintext.
scope: backend/services/voice_*.py, backend/routers/voice_*.py, backend/db/storage.py
exclude: in-memory session state
message: Plaintext phone number in storage — hash with SHA-256 (last4:hash) before DynamoDB put.
```

Evidence: `SECURITY.md:272`.

### COMP-009 — Scoped IAM with MFA Boundary (L2, SOC 2 CC6 + AWS)

```yaml
level: L2
check: Developer IAM policies scope to solace-* resources; MFA boundary enforces aws:MultiFactorAuthPresent=true; principal is never "*".
scope: scripts/apply_iam_scoped.py, scripts/setup_security.py
exclude: root account or break-glass roles (must be documented)
message: IAM policy missing scope or MFA boundary — SOC 2 least-privilege and AWS shared-responsibility require it.
```

Evidence: `scripts/apply_iam_scoped.py:1-30`.

### COMP-010 — CCPA Data Subject Affordance (L3, CCPA)

```yaml
level: L3
check: A documented path must exist for patient-initiated data export and deletion. Today only admin reset-demo exists; codify the gap and assign owner before any non-demo PII intake.
scope: backend/routers/admin.py, backend/routers/patients.py
message: CCPA §1798.105 (delete) / §1798.110 (access) right is not wired — add endpoint or document scope decision.
```

Evidence: gap noted in SECURITY.md and confirmed via router audit (no patient-facing delete endpoint today).

### COMP-011 — Demo PIN and Hospital ID Isolation (L2, SOC 2 CC6)

```yaml
level: L2
check: Demo clinician PIN is seeded separately and rotated independently of any prod credential path; cross-hospital reads are blocked at JWT layer.
scope: backend/lib/auth.py, scripts/seed_demo.py
message: Demo isolation weakened — hospital_id mismatch must always reject, even for the demo PIN flow.
```

Evidence: `backend/lib/auth.py:44`, `scripts/seed_demo.py`.

---

## Architecture

### ARCH-001 — Router → Service → DB Layering (L1)

```yaml
level: L1
check: Routers must not call DynamoDB directly; all data access flows through backend/db/storage.py.
scope: backend/routers/*.py
exclude: backend/routers/admin.py, backend/routers/ehr_auth.py
message: Router accesses DynamoDB directly — route through db.storage instead.
```

Evidence: `backend/routers/intake.py:13`, `backend/routers/triage.py:16`.

### ARCH-002 — boto3 Confined to db/ Layer (L1)

```yaml
level: L1
check: Services may import db.storage; only db/ modules initialize boto3 clients.
scope: backend/services/*.py
message: Service imports boto3 directly — request the feature via db.storage instead.
```

Evidence: `backend/services/scheduling.py:5`, `backend/db/storage.py:1`.

### ARCH-003 — AI Provider Adapters Live in lib/ (L2)

```yaml
level: L2
check: AI provider adapters (Claude, Whisper, Polly, ElevenLabs) live in backend/lib/, not backend/services/; services and routers import from lib/ only.
scope: backend/services/*.py, backend/routers/*.py
exclude: backend/lib/*.py
message: AI provider adapter outside lib/ — single swap point lives in lib/.
```

Evidence: `backend/lib/claude.py:1`, `backend/lib/ai_log.py`.

### ARCH-004 — ML Inference via triage_ml with lru_cache (L2)

```yaml
level: L2
check: LightGBM artifacts in backend/models/ are loaded only by triage_ml._load() and cached with @lru_cache(maxsize=1).
scope: backend/services/triage_ml.py
message: Model load bypasses triage_ml._load() — cold-start warmup will not cover this path.
```

Evidence: `backend/services/triage_ml.py:57-90`, `backend/main.py:159-176`.

### ARCH-005 — Pydantic Request Models Inline in Routers (L2)

```yaml
level: L2
check: Request body Pydantic classes are defined in the router file where the endpoint is declared, not in a shared models package.
scope: backend/routers/*.py
message: Request body model defined outside its router — keep inline for endpoint cohesion.
```

Evidence: `backend/routers/triage.py:27-40`, `backend/routers/auth.py:22`.

### ARCH-006 — Frontend Layer Folders (L2)

```yaml
level: L2
check: Frontend components organized as frontend/src/pages/ (page-level), frontend/src/components/{clinician,patient}/ (domain), frontend/src/components/ui/ (shared, generic).
scope: frontend/src/**/*.tsx
message: Component placed outside layer convention — pages/, components/{clinician,patient}/, components/ui/.
```

Evidence: `frontend/src/pages/PatientIntake.tsx`, `frontend/src/components/clinician/VitalsPanel.tsx`, `frontend/src/components/ui/Card.tsx`.

### ARCH-007 — All Frontend API Calls via lib/api.ts (L2)

```yaml
level: L2
check: Components import API functions from frontend/src/lib/api.ts; no axios instances created in components or pages.
scope: frontend/src/**/*.tsx
message: Direct axios in component — use the typed wrapper in lib/api.ts.
```

Evidence: `frontend/src/lib/api.ts:24-27,50+`.

### ARCH-008 — Scripts Standalone (L3)

```yaml
level: L3
check: scripts/*.py must only import backend/lib/config, backend/db, and third-party libs (AWS, ML); never routers/ or services/.
scope: scripts/**/*.py
message: Script imports app routers/services — scripts must stay standalone for idempotency.
```

Evidence: `scripts/train_triage_model.py:1-50`, `scripts/setup_aws.py`.

### ARCH-009 — Transient State in DynamoDB with TTL (L3)

```yaml
level: L3
check: Nonce, OAuth, quota, blocklist, idempotency state uses DynamoDB with short TTL in AWS mode; in-memory dicts only in local mode.
scope: backend/lib/quota.py, backend/lib/blocklist.py, backend/lib/idempotency.py, backend/lib/intake_nonce.py
message: Transient state must use atomic DynamoDB with TTL in production.
```

Evidence: `backend/db/storage.py:74-75`.

---

## Code Quality

### QUAL-001 — Python snake_case Files + Functions, PascalCase Models (L1)

```yaml
level: L1
check: Backend Python files use snake_case; module-level functions and variables snake_case; Pydantic models PascalCase.
scope: backend/**/*.py
message: Naming inconsistent — files and functions snake_case, Pydantic models PascalCase.
```

Evidence: `backend/routers/auth.py:22`, `backend/routers/patients.py:22`.

### QUAL-002 — React Components PascalCase with displayName (L1)

```yaml
level: L1
pattern: "^[A-Z][a-zA-Z0-9]*\\.tsx$"
scope: frontend/src/components/**/*.tsx, frontend/src/pages/**/*.tsx
message: Component file must be PascalCase .tsx and set displayName (esp. for forwardRef).
```

Evidence: `frontend/src/components/ui/Button.tsx:45`.

### QUAL-003 — Routers Raise HTTPException + Call audit() (L1)

```yaml
level: L1
check: Backend endpoints raise HTTPException(status_code, detail) for errors (never return error dicts); clinician routes call audit() with the action.
scope: backend/routers/**/*.py
message: Endpoint error handling must use HTTPException; clinician routes must call audit().
```

Evidence: `backend/routers/auth.py:34`, `backend/routers/triage.py:47`, `backend/routers/patients.py:14`.

### QUAL-004 — No Emoji on Patient Screens (L1)

```yaml
level: L1
pattern: "[\\U0001F300-\\U0001FAFF]|[\\u2600-\\u27BF]"
scope: frontend/src/pages/Patient*.tsx, frontend/src/components/patient/**/*.tsx
exclude: frontend/src/lib/i18n.ts, frontend/src/pages/LanguageGate.tsx
message: Emoji detected on patient screen — Solace is a clinical product, use lucide-react icons or text instead.
```

Evidence: `frontend/src/pages/PatientResult.tsx:5-7`.

### QUAL-005 — Frontend Uses Relative Imports Only (L1)

```yaml
level: L1
pattern: "import\\s+[^'\"]+from\\s+['\"]@/"
scope: frontend/src/**/*.{ts,tsx}
message: Frontend uses relative imports only — @/ alias is not configured.
```

Evidence: `frontend/src/pages/PatientIntake.tsx:2-18`.

### QUAL-006 — No console.log / print() in Routers + Services + Frontend Src (L2)

```yaml
level: L2
pattern: "console\\.(log|debug|info)|^\\s*print\\("
scope: backend/routers/**/*.py, backend/services/**/*.py, frontend/src/**/*.{ts,tsx}
exclude: backend/scripts/**, frontend/vite.config.ts, **/*.test.*, **/*.spec.*
message: Use logging.getLogger(__name__) in backend; silent error handlers / structured logging in frontend.
```

Evidence: `backend/main.py:21`, `backend/routers/auth.py:17`. Softened from L1 because 2,412 print() calls exist outside this scope; the constitution enforces the scope where reviewers can realistically clean up.

### QUAL-007 — TypeScript `any` Only in Catch Blocks (L2)

```yaml
level: L2
check: TypeScript `any` is permitted only in catch (e: any) error handlers; not in function signatures, state types, or return types.
scope: frontend/src/**/*.{ts,tsx}
message: Avoid `any` outside catch blocks — use `unknown` or precise types.
```

Evidence: `frontend/src/components/ui/InAppCamera.tsx`, `frontend/src/components/clinician/PainAlarm.tsx`.

### QUAL-008 — Tailwind Class Ordering (L2)

```yaml
level: L2
check: Tailwind classes ordered as layout (flex/grid) → sizing (w/h) → spacing (p/m/gap) → text/font → colors → states (hover/focus/disabled).
scope: frontend/src/**/*.tsx
message: Tailwind class order — layout → sizing → spacing → text → states.
```

Evidence: `frontend/src/components/ui/Button.tsx:14-27`.

### QUAL-009 — No TODO / FIXME in Shipped Code (L3)

```yaml
level: L3
pattern: "TODO|FIXME|XXX|HACK"
scope: backend/routers/**/*.py, backend/services/**/*.py, frontend/src/pages/**/*.tsx, frontend/src/components/**/*.tsx
message: Unresolved TODO — open a GitHub issue and link it instead.
```

Evidence: verified zero TODO/FIXME today in the scoped directories.

---

## Usability

### USAB-001 — Actionable Error Messages, Never Raw Errors (L1, ClinicalUX)

```yaml
level: L1
check: All user-facing errors map to an i18n key (e.g., t("error_transcription_down")); never expose HTTP status codes or stack traces to the patient/clinician UI.
scope: frontend/src/pages/**/*.tsx
exclude: console.error() in dev-only logs
message: Raw error exposed to user — map to t("error_*") for the user's language.
```

Evidence: `frontend/src/pages/PatientIntake.tsx:177-184`.

### USAB-002 — Alt Text on Images + Aria-Labels on Icon Buttons (L2, WCAG)

```yaml
level: L2
check: Every <img> has alt text; icon-only buttons (lucide icons inside a <button>) have aria-label.
scope: frontend/src/pages/**/*.tsx, frontend/src/components/**/*.tsx
exclude: decorative SVGs with aria-hidden="true"
message: Missing alt text or aria-label — add to meet WCAG 2.1 AA.
```

Evidence: `frontend/src/pages/PatientIntake.tsx:285,339`.

### USAB-003 — 44×44pt Minimum Touch Targets (L2, MobileFirst)

```yaml
level: L2
check: Interactive elements (button, input, a) on patient screens use h-11 (44px) minimum; primary actions use h-12.
scope: frontend/src/components/patient/**/*.tsx, frontend/src/pages/Patient*.tsx
message: Touch target below 44pt — increase h-* for mobile accessibility.
```

Evidence: `frontend/src/pages/PatientIntake.tsx:334,571`.

### USAB-004 — Form Inputs Have Associated Labels (L2, WCAG)

```yaml
level: L2
check: Every <input>, <textarea>, <select> has a matching <label htmlFor={id}> or aria-labelledby.
scope: frontend/src/components/patient/**/*.tsx, frontend/src/components/clinician/**/*.tsx
exclude: hidden inputs
message: Form input missing associated <label> — required for screen readers.
```

Evidence: `frontend/src/pages/PatientIntake.tsx:372-384`.

### USAB-005 — Visible Focus Ring on All Interactive Elements (L2, WCAG)

```yaml
level: L2
pattern: "focus-visible:ring|focus:ring"
scope: frontend/src/components/**/*.tsx
message: Interactive element missing focus ring — add focus-visible:ring-* for keyboard users.
```

Evidence: `frontend/src/components/ui/Button.tsx:18,20`.

### USAB-006 — Loading State on Async Operations (L2, MobileFirst)

```yaml
level: L2
check: Every async API call sets a busy state and renders Loader2 (or skeleton) while pending.
scope: frontend/src/pages/**/*.tsx
exclude: background polling under 30s cadence
message: Async operation missing busy state — add setBusy(true) + spinner.
```

Evidence: `frontend/src/pages/PatientIntake.tsx:549,571-575`.

### USAB-007 — ESI Badge Contrast Meets WCAG AA (L2, WCAG)

```yaml
level: L2
check: ESI severity color pairs meet 4.5:1 contrast (normal text) or 3:1 (large text); verify ESI_COLORS map with axe or WAVE before changes.
scope: frontend/src/components/patient/ESIBadge.tsx, frontend/tailwind.config.ts
message: Color pair fails WCAG AA — adjust ESI_COLORS tone.bg / tone.fg.
```

Evidence: `frontend/tailwind.config.ts:10-42`, `frontend/src/pages/PatientResult.tsx:196-201`.

### USAB-008 — i18n for All Patient-Facing Strings (L2, i18n)

```yaml
level: L2
check: Patient-facing strings go through t() with a language argument; raw English literals in JSX flagged.
scope: frontend/src/pages/Patient*.tsx, frontend/src/components/patient/**/*.tsx
exclude: brand names, ESI codes, units (mg, mmHg)
message: Patient-facing string not localized — wrap in t(language, "key").
```

Evidence: `frontend/src/lib/i18n.ts:17-36`.

---

## Testing

> Status today: no active test suite. pytest is installed via requirements; no `conftest.py` or test files exist. These rules codify intent.

### TEST-001 — Pytest Configured Before Claiming Coverage (L3)

```yaml
level: L3
check: A conftest.py or pyproject.toml [tool.pytest.ini_options] section must exist before any CI step claims test coverage.
scope: backend/**/*.py
message: No pytest configuration — set one up before relying on tests in CI.
```

### TEST-002 — Pytest File Naming (L3)

```yaml
level: L3
pattern: "^test_.*\\.py$"
scope: backend/**/test_*.py
message: Test files follow pytest convention: test_*.py.
```

### TEST-003 — No .only / .skip in Committed Tests (L3)

```yaml
level: L3
pattern: "\\.(only|skip)\\s*\\("
scope: backend/**/test_*.py, frontend/**/*.{test,spec}.{ts,tsx,js}
message: Remove .only() / .skip() before committing.
```

---

## Dependencies

### DEPS-001 — Python Production Deps Exact-Pinned (L1)

```yaml
level: L1
pattern: "^[a-zA-Z0-9_.\\-]+(==[\\d.]+.*)?$"
scope: backend/requirements*.txt, requirements-lambda.txt
message: Use exact `==` pinning for Python production deps.
```

Evidence: `requirements-lambda.txt:1-22`, `requirements.txt:4-18`.

### DEPS-002 — ML Deps Isolated in requirements-ml.txt (L1)

```yaml
level: L1
check: ML dependencies (numpy, scipy, scikit-learn, lightgbm, xgboost, catboost, shap) live in requirements-ml.txt only — never in the core requirements.txt.
scope: backend/requirements.txt
message: ML dependency leaked into core requirements.txt — move to requirements-ml.txt.
```

Evidence: `requirements.txt:1-21`, `requirements-ml.txt:1-10`.

### DEPS-003 — Lambda Image Stays python:3.12 AL2023 arm64 (L1)

```yaml
level: L1
check: Dockerfile.lambda uses public.ecr.aws/lambda/python:3.12 (AL2023); native libs via dnf; numpy/scipy wheels arm64-compatible.
scope: Dockerfile.lambda
message: Do not change Lambda base image or strip arm64 wheels.
```

Evidence: `Dockerfile.lambda:3`.

### DEPS-004 — scipy + numpy Required in Lambda Image (L2)

```yaml
level: L2
check: requirements-lambda.txt must include scipy and numpy pinned identically to ML training image (SHAP inference path depends on it).
scope: requirements-lambda.txt
message: scipy/numpy missing or mismatched — refine-triage SHAP will fail at runtime.
```

Evidence: `requirements-lambda.txt:15-16`, `backend/services/triage_ml.py:10,30-37`.

### DEPS-005 — Frontend Caret Ranges + Committed Lockfile (L2)

```yaml
level: L2
check: frontend/package.json uses ^ for major-version stability; frontend/package-lock.json committed.
scope: frontend/package.json, frontend/package-lock.json
message: Frontend deps must use ^ ranges and a committed lockfile.
```

Evidence: `frontend/package.json:13-20`.

### DEPS-006 — Lazy-Load Heavy Frontend Deps (L2)

```yaml
level: L2
check: framer-motion and recharts must be lazy-imported in route-level components, not in the root bundle.
scope: frontend/src/**/*.tsx
message: framer-motion or recharts in eager import path — lazy-load to keep mobile bundle small.
```

Evidence: `frontend/package.json:14,20`.

### DEPS-007 — OpenAI + Anthropic SDKs Pin Together (L3)

```yaml
level: L3
check: openai and anthropic SDK versions pinned and bumped together; regression-test the streaming/tool-use paths on every version bump.
scope: backend/requirements*.txt
message: SDK versions drifted — pin and bump together to avoid streaming/tool-use breakage.
```

Evidence: `requirements-lambda.txt:7-8`.

---

## Performance

### PERF-001 — Models Loaded via lru_cache at Module Level (L1)

```yaml
level: L1
check: LightGBM artifacts load through triage_ml._load() decorated with @lru_cache(maxsize=1); no per-request file I/O.
scope: backend/services/triage_ml.py
message: Model load must be @lru_cache'd — per-request I/O kills Lambda warm-container reuse.
```

Evidence: `backend/services/triage_ml.py:57-90`.

### PERF-002 — Lambda Warmup Handler Pre-Loads + Dry-Predicts (L1)

```yaml
level: L1
check: handler() in backend/main.py inspects event.get("warmup") or event.get("source") == "aws.events" and calls triage_ml._load() + a dry predict before returning 200.
scope: backend/main.py
message: Warmup handler must pre-load models and run a dry predict — protects cold-start latency.
```

Evidence: `backend/main.py:155-187`.

### PERF-003 — Parallel Async I/O via asyncio.gather (L2)

```yaml
level: L2
pattern: "asyncio\\.gather\\("
scope: backend/routers/*.py
exclude: backend/routers/triage.py
message: Sequential awaits in critical path — combine independent I/O with asyncio.gather().
```

Evidence: `backend/routers/intake.py:202-241`.

### PERF-004 — No DynamoDB .scan() in Hot Paths (L2)

```yaml
level: L2
check: Hot-path routers (triage, intake, patients list) use .query() with explicit KeyConditionExpression; no .scan() calls.
scope: backend/routers/triage.py, backend/routers/intake.py, backend/routers/patients.py
message: .scan() forbidden in hot paths — use .query() with sort-key conditions.
```

Evidence: `backend/routers/ehr.py`, `backend/routers/identity.py`, `backend/routers/admin.py` use `.query()` with `KeyConditionExpression`; no `.scan()` in hot triage/intake paths today.

### PERF-005 — Frontend Polling ≥ 10s + Pause When Hidden (L2)

```yaml
level: L2
check: usePollingPatients (and any polling hook) defaults to >= 10_000ms and checks document.hidden before fetching.
scope: frontend/src/hooks/usePollingPatients.ts, frontend/src/lib/constants.ts
message: Polling cadence too aggressive or missing document.hidden guard.
```

Evidence: `frontend/src/hooks/usePollingPatients.ts:8,38-44`.

### PERF-006 — refine-triage Stays Synchronous (L3)

```yaml
level: L3
check: POST /api/{hospital_id}/patients/{patient_id}/refine-triage stays a synchronous def (not async def) because the LightGBM+SHAP predict is CPU-bound and models are pre-warmed.
scope: backend/routers/triage.py
message: Do not convert refine-triage to async — CPU-bound predict will stall the event loop.
```

Evidence: `backend/routers/triage.py:43-94`.

### PERF-007 — Frontend Bundle Budget < 200KB gzipped (L3)

```yaml
level: L3
check: `npm run build && du -h frontend/dist` keeps gzipped main bundle under 200KB; add rollup-plugin-visualizer in CI when budget tightens.
scope: frontend/vite.config.ts
message: Bundle budget exceeded — split routes or lazy-load heavy deps.
```

Evidence: `frontend/vite.config.ts`, `frontend/package.json`.

---

## Custom Rules

This section is reserved for project-specific rules that don't fit standard categories. Add new sub-categories above as Solace grows (e.g., **Voice Pipeline**, **EHR Integration**).

<!-- Add custom rules here -->
