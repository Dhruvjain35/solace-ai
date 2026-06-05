# Solace Codebase Map

> Research squad WS-RSCH-2740a567 — authoritative architecture reference for the 5-workspace effort.
> All citations are `path:line` against the worktree at base commit `9c24d23` (branch `feature/copilot-phi-isolation`).

## 0. One-paragraph shape

Solace is a single FastAPI app (`backend/main.py`) deployed to **Lambda via Mangum** (`backend/main.py:11,171`), fronted by a Vite + React + TS SPA (`frontend/`). Every clinical route is mounted under `/api/{hospital_id}/...` (`backend/main.py:124-167`) — `hospital_id` is the tenant key and threads through the entire stack. Data lives in **DynamoDB** in AWS mode and **in-memory dicts** in local mode; the swap is a single `settings.solace_mode` flag, hidden behind `backend/db/storage.py`. The strict layering is `router → service → db/storage` (ARCH-001) with `boto3` confined to `db/` (ARCH-002, with documented exceptions in `routers/admin.py`, `routers/ehr_auth.py`). AI provider adapters live in `lib/` (ARCH-003) and default to BAA-covered AWS services (Bedrock/Transcribe/Polly, COMP-005).

---

## 1. Backend

### 1.1 Entrypoint & request lifecycle — `backend/main.py`

| Concern | Evidence |
|---|---|
| Log redaction installed FIRST, before any logger is used (SEC-002) | `main.py:24-28` (`log_redaction.install()`) |
| Secrets hydration at import time (cold start) (SEC-001) | `main.py:35` → `lib/config.py:97-146` |
| CORS allow-list: explicit prod origins + localhost in local; `SOLACE_CORS_ORIGINS` override | `main.py:52-83` |
| Per-request PHI-free EMF observability middleware (dimensioned by `hospital_id` + route) | `main.py:88-90` → `lib/observability.py` |
| `/health` reports `trained_ensemble` vs `clinical_simulation` by asking the real loader | `main.py:93-115` |
| Local media mount (`/media`); on AWS, S3 pre-signed URLs serve instead | `main.py:118-122` |
| Router registration — `ehr_auth` registered FIRST so fixed `/api/auth/ehr/...` wins over `/api/{hospital_id}/...` | `main.py:124-167` |
| Lambda handler: `deferred_artifacts` re-entry (async self-invoke), `warmup` path pre-loads ML + dry predict (PERF-002) | `main.py:174-240` |

**Routers are mounted with `prefix="/api/{hospital_id}"`** (`main.py:129-157`) EXCEPT four fixed-path routers: `ehr_auth` (SMART OAuth, `main.py:128`), `cds_hooks_router` (`/cds-services`, `main.py:159`), `governance` (public, `main.py:161`), `hospitals` (provisioning — it *creates* the `hospital_id`, `main.py:164`), and `voice` (Twilio routes by dialed number, `main.py:167`).

### 1.2 Config — `backend/lib/config.py`

- `Settings` (pydantic-settings) reads `.env`; `solace_mode: "local" | "aws"` is the master switch (`config.py:23`).
- AI provider defaults are **BAA-covered** (COMP-005): `CLAUDE_PROVIDER=bedrock`, `TRANSCRIPTION_PROVIDER=aws`, `TTS_PROVIDER=aws` (`config.py:25-34`). Third-party keys are opt-in only.
- Model tiers: `model_clinical` / `model_utility`, both default `claude-haiku-4-5`, flip via env without code change (`config.py:36-45`).
- DDB table names are config attrs (`config.py:52-56`); most other tables are module-level constants in their owning lib/db file (see codebase grep, §1.4).
- `hydrate_from_secrets_manager()`: AWS mode only; pulls `solace/api-keys`, crashes if required key (`DEMO_CLINICIAN_PIN`) missing (`config.py:97-146`, SEC-001).

### 1.3 Storage layer — `backend/db/storage.py` (the ONLY boto3 data path)

- Local/AWS split per entity: hospitals (`storage.py:75-101`), patients (`storage.py:105-138`), prescriptions (`storage.py:215-232`), notes (`storage.py:236-253`), appointments (`storage.py:262-319`).
- `Decimal`↔`float` conversion helpers `_to_ddb` / `_from_ddb` (`storage.py:35-54`).
- Patients keyed by `patient_id` (HASH); cross-hospital listing via GSI `hospital_id-created_at-index` with `.query()` not `.scan()` (`storage.py:205-211`, PERF-004).
- `invoke_lambda_async()` — the ONLY boto3 Lambda-invoke seam, used by deferred intake artifacts (`storage.py:151-167`).
- Durable append-only stores, all CMK-encrypted + dual-write DDB(hot TTL)+S3(6yr JSONL), partitioned by `hospital_id`, sorted by `ts_id="{epoch_ms}#{uuid}"` (PERF-004, COMP-002/003):
  - AI overrides — `solace-ai-overrides` (`storage.py:326-406`)
  - ML labels — `solace-ml-labels` (`storage.py:420-500`)
  - Billing events — `solace-billing-events`, ~18mo TTL (`storage.py:511-601`)
- `get_hospital_by_slug` / `slug_exists` back the provisioning flow (`storage.py:88-101`).

### 1.4 lib/ — cross-cutting + AI adapters (39 modules)

| Module | Role | Key evidence |
|---|---|---|
| `config.py` | Settings + secrets hydration | SEC-001, COMP-005 |
| `log_redaction.py` | Redacts UUIDs/Bearer/nonce from logs | SEC-002, installed `main.py:28` |
| `auth.py` | Clinician JWT verify + `require_clinician` Depends + `audit()` helper | `auth.py:19-93` (SEC-008) |
| `jwt_auth.py` | JWT sign/verify (HS256-only, alg-confusion-hardened), bcrypt PIN, lockout, TOTP MFA | `jwt_auth.py:21-31,241-273` (COMP-006) |
| `accounts.py` | Passwordless clinician accounts + single-use magic tokens (SHA-256 hashed) | `accounts.py:86-186` |
| `tenant.py` | Framework-agnostic cross-tenant guard `assert_patient_in_hospital` | `tenant.py:40-53` (SEC-008/COMP-011 defense-in-depth) |
| `claude.py` | Claude adapter (Bedrock vs direct), the single AI swap point | ARCH-003 |
| `content_guard.py` | `scan()` — PII redaction + injection guard before ANY AI call | SEC-005, COMP-001 (`content_guard.py:59-118,132-192`) |
| `audit.py` | `record()` dual-write DDB(90d TTL)+S3(6yr CMK) | COMP-002 (`audit.py:25-76`) |
| `blocklist.py`, `quota.py`, `idempotency.py`, `intake_nonce.py` | Transient abuse-prevention state (DDB+TTL in AWS, dict local) | SEC-003/007, ARCH-009 |
| `metering.py`, `provenance.py`, `label_store.py` | Billing / override / ML-label business logic over storage.py | — |
| `smart_auth.py`, `ehr_vendors.py` | SMART-on-FHIR discovery + vendor registry (Epic/Cerner/Athena) | backs `ehr_auth.py` |
| `mfa.py`, `conformal.py`, `json_extract.py`, `medical_format.py`, `fallbacks.py`, `observability.py`, `async_invoke.py`, `uploads.py`, `ai_log.py` | TOTP, conformal calibration, robust JSON parse, formatting, fallbacks, EMF, async fan-out, media, AI logging | — |

### 1.5 routers/ — 30 routers, all under `/api/{hospital_id}` unless noted

Patient-facing (blocklist + consent gated): `intake.py` (SEC-003/004/005 reference impl, `intake.py:69,73-88,126-131`), `pain_flag.py`, `voice.py`, `transcribe.py`, `insurance.py`, `identity.py`, `public.py`.
Clinician-facing (`Depends(require_clinician)` + `audit()`): `patients.py`, `notes.py`, `prescriptions.py`, `triage.py`, `admin.py`, `billing.py`, `clinical_ai.py`, `ehr_copilot.py`, `care_ops.py`, `wave4.py`, `governance.py`, `onboarding.py`, `appointments.py`, `workflows.py`, `ehr.py`.
Fixed-path: `ehr_auth.py` (SMART OAuth `/launch` + `/callback`, SEC-006), `hospitals.py` (provisioning), `cds_hooks_router.py`, `voice.py`.

Router conventions: inline Pydantic request models (ARCH-005), raise `HTTPException` never error dicts (QUAL-003), clinician routes call `audit()` (COMP-002).

### 1.6 services/ — domain logic (70+ modules), notably the **Copilot package**

`backend/services/copilot/` is the **Plan→Execute→Narrate PHI-isolated agent** — the architectural twin of Atlas, and the key reference for the Atlas embed:

| File | Role | PHI boundary |
|---|---|---|
| `pipeline.py` | Orchestrates 2 model calls (plan, narrate) with a deterministic PHI zone between | model NEVER sees raw PHI (`pipeline.py:29-73`) |
| `catalog.py` / `registry.py` | Coded-vocabulary primitive catalog shown to the planner | only codes, no values |
| `gate.py` | Validates the plan against the catalog BEFORE any PHI touch; rejects wholesale | smuggling guard `gate.py:67-71` |
| `context.py` | **Inside** the PHI boundary — loads real patient, asserts tenancy | `context.py:48-53` (`tenant.assert_patient_in_hospital`) |
| `executor.py` | Runs primitives over real PHI, down-projects to coded results + slot map | slots never enter a model call |
| `artifacts.py` | Hydrates the narrator's reference-only artifact tree with real slot values | `pipeline.py:142-143` |

Exposed via `routers/ehr_copilot.py` (`/copilot/ask|summary|scan|autopopulate`, all `Depends(require_clinician)` + `audit()`).

Other service clusters: triage (`triage_ml.py` LightGBM ensemble + SHAP + conformal, `triage_engine.py`, `triage_rules.py`), clinical-AI waves (scribe, ddx_v2, differential, disposition, workup, em_coding, letters, pa_packets, drug_interactions, screeners, discharge_plan), EHR adapters (`ehr_epic.py`, `ehr_oracle.py`, `ehr_athena.py`, `ehr_gateway.py`, `fhir_writer.py`, `fhir_patient_search.py`, `hl7_v2.py`), care-ops (eligibility, no_show, hedis, sdoh), voice agent (`voice_agent/`), and workflows engine (`workflows/`).

### 1.7 ML — `backend/services/triage_ml.py` + `backend/models/`

- LightGBM 5-fold ensemble (+ optional XGB/Cat folds) + SHAP + conformal calibration.
- Loaded ONLY via `triage_ml._load()` decorated `@lru_cache(maxsize=1)` (PERF-001, ARCH-004; `triage_ml.py:57-90`).
- Warmup handler pre-loads + dry-predicts + primes conformal calibration synchronously off the request path (`main.py:199-239`).
- Artifacts baked into the Lambda image at build from `s3://solace-lambda-deploy-704229156617/models/` (`buildspec.yml:14-30`).
- ML deps isolated in `backend/requirements-ml.txt` (DEPS-002); `requirements-lambda.txt` carries scipy+numpy for SHAP (DEPS-004).

---

## 2. Frontend (`frontend/src/`)

### 2.1 Routing — `App.tsx`

- `hospitalRoutes(prefix)` renders the SAME route set under both `""` (legacy `/demo`) and `/h` (provisioned workspaces) — both bind `:hospitalId` so every page reads its tenant identically via `useParams()` (`App.tsx:27-61`).
- Patient routes: `/:hospitalId` (intake), `/result/:patientId`, `/schedule`, `/qr`, `/auth/verify`.
- Clinician routes: `/:hospitalId/clinician`, `/clinician/patient/:patientId`, `/clinician/scribe|letters|inbox|tools|ops|workflows`, `/clinician/print/:patientId`.
- Standalone: `/clinicians` (landing), `/showcase`, `/mockups`, `/trust`, `/voice`, `/ehr/callback`.

### 2.2 Layers (ARCH-006)

- `pages/` — page-level (24 pages). `components/clinician/` (13), `components/patient/` (12), `components/ui/` (6 generic), `components/workspace/` (the **Patient Workspace** tab system), `components/tour/`.
- `components/workspace/PatientWorkspaceContext.tsx` — **the per-patient shared-state contract**. Tabs take NO props; they read `{ hospitalId, patientId, patient, loading, error, reloadPatient, ehrFhirId, ehrLinked }` from context (`PatientWorkspaceContext.tsx:60-69,87-154`). 12 tabs in `workspace/tabs/` (Overview, Reasoning, Scribe, Coding, CareGaps, PriorAuth, Letters, Ehr, Copilot, CopilotArtifacts, ResultClosure).
- This is the **seam the Atlas embed extends** — a new "Atlas/Orders" tab plugs in here without props.

### 2.3 API access — `frontend/src/lib/api.ts` (ARCH-007)

- Single axios instance (`api.ts:24-27`); ALL calls go through `lib/api*.ts` (no axios in components).
- Bearer token auto-attached from `localStorage["solace.session.v1"]` (`api.ts:32-48`) — the ONLY auth mechanism.
- Split modules: `api.ts` (core), `api-scribe.ts`, `api-letters.ts`, `api-inbox.ts`, `api-ops.ts`, `api-tools.ts`.
- Other lib: `session.ts`, `i18n.ts`, `constants.ts`, `runtime-config.ts`, `image.ts`, `tour-*.ts`.
- Constraints: relative imports only, no `@/` alias (QUAL-005); no emoji on patient screens (QUAL-004).

---

## 3. How the layers connect (a single intake→triage→workspace trace)

1. Patient opens `/:hospitalId` → `PatientIntake.tsx` → `postIntake(hospitalId, form)` (`api.ts:57-62`).
2. `POST /api/{hospital_id}/intake` (`routers/intake.py`): `blocklist.enforce` (SEC-003) → consent check (SEC-004) → `content_guard.scan` (SEC-005) → transcription/triage services → `storage.put_patient` → fast-path returns; slow clinician artifacts deferred via `invoke_lambda_async` re-entering `handler()` (`main.py:185-197`).
3. ML triage: `triage_ml.predict` (lru_cached load) sets `esi_level`.
4. Clinician logs in (magic link `accounts.consume_magic_token` → `jwt_auth.issue_token`) → JWT in `localStorage`.
5. `ClinicianDashboard` polls `getPatients(hospitalId)` (`usePollingPatients`, ≥10s + `document.hidden` guard, PERF-005).
6. Open patient → `PatientDetailPage` → `PatientWorkspaceProvider(hospitalId, patientId)` fetches `getPatientDetail`; tabs render. Copilot tab → `POST /copilot/ask` → `services/copilot/pipeline._run` (PHI-isolated Plan→Execute→Narrate).
7. Every clinician action: `require_clinician` (JWT + `hospital_id` match, SEC-008) → `audit()` dual-write (COMP-002).

---

## 4. Files the four build squads will touch (ownership preview — see integration-contract.md)

- **CORE** (tenancy/workspace_id): `lib/config.py`, `lib/jwt_auth.py`, `lib/auth.py`, `lib/accounts.py`, `lib/tenant.py`, `db/storage.py`, `routers/hospitals.py`, new `routers/workspaces.py`, scripts for new GSIs.
- **ATLAS** (embed): new `routers/atlas.py` + `services/atlas/`, new `frontend/src/components/workspace/tabs/OrdersTab.tsx` (or `AtlasTab`), `lib/api-atlas.ts`. Reuses `lib/claude.py`, `content_guard`, copilot PHI patterns, `services/fhir_writer.py`.
- **UIUX**: `frontend/src/components/{ui,clinician,patient}/`, `pages/`, NOT the workspace context contract (extend tabs only).
- **PROD** (AWS/deploy): `scripts/setup_*.py`, `buildspec.yml`, `Dockerfile.lambda`, `requirements-lambda.txt` — IaC/dry-run only.
