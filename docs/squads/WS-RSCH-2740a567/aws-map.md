# AWS Map — current wiring + what the Workspace feature needs

> Research squad WS-RSCH-2740a567. Derived from code ONLY. **No AWS command was executed.** PROD squad: all provisioning is IaC/dry-run, gated on Sriyan's approval (SQUAD_BRIEF guardrail #3).
> Account `704229156617`, region `us-east-1`.

## 1. Compute — Lambda (container image) via Mangum

- FastAPI wrapped by `Mangum(app, lifespan="off")`; `handler(event, context)` is the Lambda entry (`backend/main.py:171-240`).
- Container image (not zip) — `Dockerfile.lambda`: base `public.ecr.aws/lambda/python:3.12` (AL2023, arm64) (DEPS-003), `libgomp` via dnf for LightGBM, runs as non-root UID 993, CMD `main.handler` (`Dockerfile.lambda:3-34`).
- Function name **`solace-api`**; ECR repo `704229156617.dkr.ecr.us-east-1.amazonaws.com/solace-api` (`buildspec.yml:10,35,41`).
- Build/deploy via **CodeBuild** (`buildspec.yml`): ECR login → bake ML artifacts from `s3://solace-lambda-deploy-704229156617/models/` → `docker build` → push → `aws lambda update-function-code` → `wait function-updated` (`buildspec.yml:9-43`).
- **Warmup**: `handler` answers `event.warmup` / `source==aws.events` pings by pre-loading ML + dry-predict (PERF-002, `main.py:199-239`) — implies an EventBridge scheduled warmer (`solace-warmer` referenced in scripts).
- **Async self-invoke**: `storage.invoke_lambda_async` fires `InvocationType='Event'` back into the same function for deferred intake artifacts (`db/storage.py:151-167`, `main.py:185-197`) — requires `lambda:InvokeFunction` self-permission (`solace-self-invoke` in scripts).

## 2. Data — DynamoDB (CMK-encrypted, PAY_PER_REQUEST)

Created idempotently by `scripts/setup_aws.py` and feature-specific setup scripts; all encrypted with `alias/solace` CMK (`setup_aws.py:51-63`, COMP-003).

| Table | Key schema / GSI | Created by | Used by |
|---|---|---|---|
| `solace-patients` | PK `patient_id`; GSI `hospital_id-created_at-index` | `setup_aws.py:75-93` | `db/storage.py:180-211` |
| `solace-hospitals` | PK `hospital_id` | `setup_aws.py:94-98` | `db/storage.py:170-177` |
| `solace-prescriptions` | PK `patient_id` + SK `prescription_id` | `setup_aws.py:99-109` | `db/storage.py:215-232` |
| `solace-notes` | PK `patient_id` + SK `note_id` | `setup_aws.py:110-120` | `db/storage.py:236-253` |
| `solace-clinicians` | PK `clinician_id`; GSIs `hospital_name-index`, `hospital_email-index` | `setup_clinician_auth.py` | `lib/jwt_auth.py`, `lib/accounts.py` |
| `solace-magic-tokens` | PK `token_hash`; `expires_at` TTL | `setup_clinician_auth.py` | `lib/accounts.py:118-186` |
| `solace-access-requests` | PK `request_id`; GSI `hospital-index` | `setup_clinician_auth.py` | `lib/accounts.py:207-269` |
| `solace-appointments` | PK `appointment_id`; GSIs `confirmation_code-index`, `hospital_id-created_at-index` | `setup_voice_tables.py` | `db/storage.py:262-319` |
| `solace-oauth-states` | PK state; TTL | `setup_ehr.py` | `routers/ehr_auth.py:98-128` |
| `solace-ehr-patients` | EHR-linked patient identity | `setup_ehr.py` | EHR adapters |
| `solace-ai-overrides` | PK `hospital_id` + SK `ts_id`; 90d TTL | `setup_overrides_table.py` | `db/storage.py:326-406` |
| `solace-ml-labels` | PK `hospital_id` + SK `ts_id`; 90d TTL | `setup_labels_table.py` | `db/storage.py:420-500` |
| `solace-billing-events` | PK `hospital_id` + SK `ts_id`; ~18mo TTL | `setup_metering_table.py` | `db/storage.py:511-601` |
| `solace-blocklist`, `solace-quotas`, `solace-idempotency`, `solace-intake-nonces` | transient + TTL | `setup_abuse_prevention.py` | `lib/blocklist|quota|idempotency|intake_nonce.py` |
| `solace-calls`, `solace-polly-tts` | voice agent | `setup_voice_tables.py` | `services/voice_agent/` |
| `solace-audit-log` | PK `hospital_id`-ish + SK; 90d TTL (+ S3 6yr) | setup script | `lib/audit.py` |

## 3. Secrets — AWS Secrets Manager

- `solace/api-keys` — hydrated on cold start; required `DEMO_CLINICIAN_PIN`, optional third-party AI keys (`lib/config.py:48,113-146`, SEC-001).
- `solace/clinician-auth` — JWT signing key + algorithm + demo clinicians; fetched once per cold start, lru_cached (`lib/jwt_auth.py:53-71`).
- Both CMK-encrypted; managed by `scripts/setup_security.py:132+`.

## 4. Encryption — KMS CMK `alias/solace`

- Single symmetric CMK, alias `alias/solace`, **annual rotation enabled**, root + CloudTrail key policy (`setup_security.py:38-86`, COMP-003).
- Resolved by alias everywhere (no hardcoded UUID) — `setup_aws.py:25-35`.
- Encrypts: all DDB tables (`setup_security.py:90-110`), S3 media bucket default encryption + BucketKey (`setup_security.py:114-129`), Secrets Manager, CloudTrail.

## 5. Storage — S3

- `solace-media-704229156617` — patient media (audio/photos), pre-signed URLs in AWS mode; also the 6-year JSONL archive target for audit/overrides/labels (`db/storage.py:331-355,425-450`; `setup_security.py:114-129`).
- `solace-lambda-deploy-704229156617` — ML artifacts (`models/` prefix), baked into the image at build (`buildspec.yml:4-5,14-30`).
- `solace-cloudtrail-704229156617` — CloudTrail log bucket (`setup_security.py:20`).

## 6. Edge / TLS (COMP-004)

- **CloudFront** distribution (`solace-api-dist-v1`, `solace-apigw` refs) enforces TLS 1.2 minimum; **API Gateway** + S3 bucket policies reject `aws:SecureTransport=false` (`SECURITY.md:40-41`).
- **WAF** on CloudFront — `setup_waf_cloudfront.py` (managed rule sets `solace-waf-common`, `solace-waf-bad-inputs`, `solace-waf-ip-reputation`, rate limit `solace-waf-rate-limit`).
- Frontend served via Amplify/Vercel (CORS origins at `main.py:52-58`).

## 7. IAM (COMP-009)

- `scripts/apply_iam_scoped.py` — `SolaceDeveloperAccess` customer-managed policy scoped to `solace-*`, `SolaceMFARequired` permission boundary (`aws:MultiFactorAuthPresent`), attached to user `solace-dev`. **DRY-RUN by default**, staged flags `--apply-policy`/`--apply-boundary`/`--remove-admin` (`apply_iam_scoped.py:1-36`).
- `scripts/setup_exec_role_iam.py` — the Lambda execution role (`solace-lambda-exec`): DDB, S3, Secrets Manager, KMS (CMK), Bedrock invoke, Transcribe, Polly, `lambda:InvokeFunction` (self), CloudWatch.
- CloudWatch alarms + EventBridge alerts: `setup_cloudwatch_alarms.py`, `setup_security_alerts.py` (`solace-alert-*`, `solace-lambda-errors`, throttles, root-login, KMS-deletion).

## 8. What the **Workspace feature** needs in AWS (for PROD squad — IaC/dry-run only)

| Need | Concrete AWS change | Notes |
|---|---|---|
| Workspace table | New `solace-workspaces`: PK `hospital_id` + SK `workspace_id`, optional GSI `workspace-index` (HASH `workspace_id`). CMK-encrypted, PAY_PER_REQUEST. | New `scripts/setup_workspaces_table.py` mirroring `setup_labels_table.py`. See tenancy-recommendation.md §3. |
| Clinician membership | Add `workspace_ids` (String Set) attribute to existing `solace-clinicians` rows — **no schema change** (DynamoDB is schemaless); update via parameterized `update_item`. | No new table. |
| Patient tagging | Add `workspace_id` attribute to `solace-patients` items — no key change. Optional future GSI `hospital_workspace-index` only if scale demands (documented "later"). | Avoid a partition-key migration. |
| Exec-role IAM | Extend `solace-lambda-exec` with `dynamodb:*Item`/`Query` on `solace-workspaces` (+ its GSI). | Add to `setup_exec_role_iam.py`; scoped to `solace-*` (COMP-009). |
| Atlas embed | NO new compute (runs inside `solace-api` Lambda). Bedrock invoke is already permitted (COMP-005). FHIR write-back uses existing EHR adapters + `solace-oauth-states`/`solace-ehr-patients`. | Atlas adds routes, not infra. |
| Atlas audit | Reuses `solace-audit-log` (DDB) + S3 6yr archive — no new resource. | `workspace_id` added to audit extra. |
| Dev policy scope | `SolaceDeveloperAccess` already wildcards `solace-*`, so new `solace-workspaces` is covered without a policy edit. | Verify in dry-run. |

**No new compute, no new bucket, no new CMK, no new secret are required for Workspace or the Atlas embed.** The only net-new AWS resource is the `solace-workspaces` DynamoDB table; everything else is an additive attribute or an IAM action append, all already inside the `solace-*` scope and `alias/solace` CMK.
