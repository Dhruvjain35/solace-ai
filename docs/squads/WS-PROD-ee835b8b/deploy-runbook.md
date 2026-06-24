# Solace Production Deploy Runbook — WS-PROD-ee835b8b

> Audience: Sriyan (the only person with credentials to run `--apply`).
> Every step below defaults to **dry-run**. Nothing here mutates AWS or deploys
> to prod until you re-run the same command with `--apply`. Do NOT wire any
> `--apply` step into CI.

All commands run from the repo root with the `solace-dev` AWS profile active
(`us-east-1`). Confirm identity first:

```bash
aws sts get-caller-identity
```

---

## 0. Pre-flight (no AWS mutations)

1. CMK exists — the deploy depends on `alias/solace` for COMP-003 encryption:
   ```bash
   aws kms describe-key --key-id alias/solace --query 'KeyMetadata.Arn'
   ```
   If missing, run `python scripts/setup_security.py` first (creates the CMK,
   enables annual rotation).

2. Core data plane exists (idempotent, safe to re-run):
   ```bash
   python scripts/setup_aws.py            # tables + media bucket
   python scripts/setup_metering_table.py # solace-billing-events
   ```

3. Lambda image deps are `==`-pinned (DEPS-001) and the base image is unchanged
   (DEPS-003 — `public.ecr.aws/lambda/python:3.12`, AL2023, arm64). Do **not**
   edit `Dockerfile.lambda`'s `FROM` line or strip arm64 wheels.

---

## 1. Provision the workspaces config table (NEW)

`solace-workspaces` is the durable per-hospital workspace config store:
partition `hospital_id`, sort `workspace_id`, CMK-encrypted, **no TTL**.

```bash
# Plan (default — zero AWS calls):
python scripts/setup_workspaces.py

# Apply (creates the table, idempotent):
python scripts/setup_workspaces.py --apply
```

The `--apply` path resolves the CMK by alias, creates the table if absent, and
asserts TTL is **DISABLED** (durable config must not expire). Re-running is a
no-op once the table exists.

---

## 2. Build the Lambda container image (local, no AWS)

```bash
docker build -f Dockerfile.lambda -t solace-lambda:latest --platform linux/arm64 .
```

Keep `requirements-lambda.txt` exact-pinned (DEPS-001) and `scipy`+`numpy`
present (DEPS-004 — SHAP inference depends on them).

---

## 3. Deploy the API container to Lambda

This is an **outward-facing prod deploy**. It pushes to ECR, deletes+recreates
the `solace-api` Lambda in image mode, and re-points API Gateway + the
EventBridge warmer.

```bash
# Plan (default):
python scripts/deploy_container.py

# Apply:
python scripts/deploy_container.py --apply
```

The deployed env now sets `CLAUDE_PROVIDER=bedrock` (COMP-005 — PHI stays inside
the AWS BAA). `direct` (third-party Anthropic, no BAA) must never be the prod
default. The script ends with a `warmup` smoke test (`ml_ok`); if it fails,
check CloudWatch and do not proceed.

---

## 4. (Optional) Pin zero cold-starts

Provisioned concurrency **bills continuously** — only enable for a demo window.

```bash
python scripts/enable_provisioned.py          # plan
python scripts/enable_provisioned.py --apply   # publish version, alias `live`, PC=1
```

---

## 5. Deploy the frontend + landing page

```bash
cd frontend && npm run build && cd ..

python scripts/deploy_amplify.py          # plan
python scripts/deploy_amplify.py --apply   # publish to live Amplify branch

python scripts/deploy_landing.py          # plan
python scripts/deploy_landing.py --apply   # publish marketing landing page
```

---

## 6. Edge security (WAF + CloudFront)

> RUNBOOK TASK — `scripts/setup_waf_cloudfront.py` is **not yet `--apply`-gated**
> (deferred; see report.md). Treat a bare run as live until that gate lands:
> read the script's `main()` before running, and do not run it unattended.
> Also outstanding from the review (MEDIUM, COMP-004): provision an ACM cert +
> custom domain so CloudFront enforces `TLSv1.2_2021` instead of the TLSv1
> default-cert fallback **before any PHI flows through the distribution**.

```bash
python scripts/setup_waf_cloudfront.py   # reads main() first — currently NOT gated
```

---

## Rollback

| What | How |
|------|-----|
| **Lambda code (image mode)** | Re-point the function/alias to a prior ECR image digest: `aws lambda update-function-code --function-name solace-api --image-uri <repo>@<prev-digest> --publish`, then re-run step 3's API Gateway re-point if needed. ECR keeps prior digests (scan-on-push, immutable refs). |
| **Lambda via alias** | If `live` alias is in use, repoint it back: `aws lambda update-alias --function-name solace-api --name live --function-version <prev-version>`. |
| **Provisioned concurrency** | `aws lambda delete-provisioned-concurrency-config --function-name solace-api --qualifier live` (stops billing, falls back to on-demand). |
| **Amplify (app or landing)** | Re-deploy a known-good zip via the same script, or in the Amplify console "Redeploy this version" on the prior successful job. |
| **CLAUDE_PROVIDER regression** | If a deploy ever ships `direct`, immediately `aws lambda update-function-configuration --function-name solace-api --environment "Variables={...,CLAUDE_PROVIDER=bedrock}"` and rotate any exposed third-party key. The committed default is now `bedrock`. |
| **workspaces table** | Durable config — do **not** delete on rollback. If a bad schema was applied, create a corrected table under a new name and migrate; never drop the live config store. |

---

## Gated for manual approval (do NOT automate)

- Every `--apply` invocation above.
- ACM cert + custom-domain provisioning for the TLS 1.2 floor (COMP-004 MEDIUM).
- Retrofitting the `--apply` gate onto `setup_waf_cloudfront.py` and the
  `setup_*` / `harden_runtime.py` mutators (tracked in report.md).
