# Security Review — WS-PROD-ee835b8b (AWS wiring)

Reviewer: security-architect
Date: 2026-06-05
Scope: AWS provisioning / deploy scripts + IaC under `scripts/` and `Dockerfile.lambda`.
Mandate: audit against COMP-003 (CMK), COMP-004 (TLS 1.2+), COMP-009 (scoped IAM + MFA),
SEC-009 (parameterized keys), COMP-007 (no secrets in source), DEPS-003 (Lambda image);
and confirm nothing performs a live/destructive AWS action or prod deploy **by default**.

No `SendMessage` from `prod-tester` arrived (no SendMessage tool available in this
environment), and `git` is blocked by the sandbox, so I reviewed the AWS-wiring files
directly rather than a computed diff. Findings below are file/line-grounded.

---

## Verdict: BLOCK

Two blocking issues must be resolved before this workspace is approved. Both are L1
guardrail violations (SQUAD_BRIEF L1 #3 "Do NOT run real AWS mutations or production
deploys ... by default", and COMP-005). The KMS/TLS/IAM/secrets posture is otherwise
strong.

---

## Findings (severity-ranked)

### [BLOCK-1 / CRITICAL] Deploy + provisioning scripts execute live AWS mutations with no gating flag (SQUAD_BRIEF L1 #3)

The brief requires that nothing perform a live/destructive AWS action or prod deploy
*by default*. The IAM-mutating scripts get this right (DRY-RUN default), but every
deploy/provisioning script runs irreversible, outward-facing AWS mutations the moment
`python scripts/<x>.py` is invoked — no `--apply`, no dry-run, no confirmation:

- `scripts/deploy_container.py:187` `main()` — pushes a live ECR image, **deletes and
  recreates the prod `solace-api` Lambda** (`recreate_function` → `lam.delete_function`,
  line 89), re-points API Gateway + EventBridge, then invokes it. This is a full prod
  deploy on a bare run.
- `scripts/deploy_amplify.py:115` / `scripts/deploy_landing.py:90` — build + push a zip
  and `start_deployment` to the live Amplify hosting branch (`PRODUCTION` stage).
- `scripts/enable_provisioned.py:141` — publishes a new Lambda version, repoints the
  `live` alias, and bills provisioned concurrency.
- `scripts/setup_waf_cloudfront.py:249` — creates/updates a CloudFront distribution +
  WAF webACL.
- `scripts/setup_aws.py:241`, `scripts/setup_security.py:363`, `scripts/harden_runtime.py:105`
  — create tables/buckets/KMS/CloudTrail and mutate API Gateway throttle/CORS live.

Contrast with the correctly-gated scripts that DO default to safe:
`scripts/apply_iam_scoped.py:104-106` (DRY-RUN default), `scripts/setup_exec_role_iam.py:120`
(`--apply` required), `scripts/rotate_pins.py:96` (`--apply` required).

Required fix: gate the destructive/deploy scripts behind an explicit `--apply` (default to
a dry-run that prints the plan), matching the pattern already established in
`apply_iam_scoped.py` / `setup_exec_role_iam.py`. At minimum, `deploy_container.py`,
`deploy_amplify.py`, `deploy_landing.py`, and `enable_provisioned.py` (the outward-facing
prod-deploy paths) must not act on a bare run. This is the blocking item for the brief's
"dry-run only" mandate.

Note: I did NOT execute any of these scripts. No live action was taken during this review.

### [BLOCK-2 / HIGH] Prod Lambda env hardcodes `CLAUDE_PROVIDER=direct` — PHI to non-BAA provider (COMP-005, L1)

`scripts/deploy_container.py:111` sets `"CLAUDE_PROVIDER": "direct"` in the Lambda
environment. `backend/lib/config.py:28` documents the secure default as `bedrock` (BAA-
covered), and COMP-005 (L1) requires AWS-covered AI providers as the default in
production. As written, a live container deploy ships `direct`, routing clinical text to
the third-party Anthropic API outside the AWS BAA. The inline comment ("flip to bedrock
after AWS BAA + model access") acknowledges this, but the committed value is the unsafe
one. Set the deployed default to `bedrock`, or make the provider an explicit, reviewed
deploy parameter that defaults to `bedrock`. (Tie-in: BLOCK-1 — because this script
deploys on a bare run, the unsafe provider would reach prod automatically.)

### [MEDIUM] CloudFront viewer TLS floor can land on TLSv1 (COMP-004, L1)

`scripts/setup_waf_cloudfront.py:45` sets `CUSTOM_DOMAIN = None`, and `_viewer_certificate()`
(lines 82-89) then falls back to the CloudFront default cert with
`MinimumProtocolVersion: "TLSv1"`. COMP-004 (L1) requires TLS 1.2+ at every edge. The
code correctly enforces `TLSv1.2_2021` *only when* a custom domain + ISSUED ACM cert
exist, but the shipped configuration (no custom domain) leaves the viewer-facing floor at
TLSv1. Origin leg is fine (`OriginSslProtocols: ["TLSv1.2"]`, line 190). Resolve before
any PHI flows through this distribution: provision the ACM cert + custom domain so the
`TLSv1.2_2021` branch is taken, and treat the TLSv1 fallback as non-production.

### [LOW] Misleading CORS log + permissive CORS (SEC posture, advisory)

`scripts/harden_runtime.py:69-85` sets API Gateway `AllowOrigins: ["*"]` but prints
`"CORS locked to {AMPLIFY_ORIGIN}"` (line 85) — the log contradicts the action. The
wildcard is defended in-comment (WAF + per-identity quota + JWT do the real bounding,
`AllowCredentials: False`), which is a defensible posture for a token-authenticated API,
so this is advisory, not blocking. Fix the misleading log line; consider scoping origins
if the front-end host set is stable.

### [LOW] Hardcoded account ID + CMK key UUID in IaC (SEC-009-adjacent, advisory)

`scripts/iam_solace_developer_policy.json` and `scripts/deploy_container.py:28` embed the
account `704229156617` and CMK key UUID `66c32010-...`. This is acceptable for account-
specific IaC and is NOT a SEC-009 violation (SEC-009 targets f-string interpolation of
**user input** into DynamoDB keys — none found; all writes use parameterized
`ExpressionAttributeValues`). Preferred pattern is alias resolution, which `setup_aws.py`
(`alias/solace`, line 28) and `setup_security.py` already do. Advisory: resolve the CMK by
alias in `deploy_container.py` too, for cross-account reproducibility.

---

## Passing controls (verified)

- **COMP-003 (CMK, L1) — PASS.** `setup_security.py` creates the `alias/solace` CMK with
  `enable_key_rotation` (annual, line 83), encrypts DynamoDB (line 99), S3 media
  (line 115), Secrets Manager (line 154), and CloudTrail (line 249) with it.
  `setup_aws.py` resolves the CMK by alias and applies SSE-KMS to tables + bucket.
- **COMP-004 (TLS, L1) — PARTIAL/PASS at rest-in-transit edges.** S3 `DenyInsecureTransport`
  on `aws:SecureTransport=false` (`setup_security.py:325`); CloudFront viewer
  `redirect-to-https` + origin `https-only`/`TLSv1.2`. Outstanding: viewer min-protocol
  floor (see MEDIUM above).
- **COMP-007 (no secrets, L1) — PASS.** Pattern scan of `scripts/` + `Dockerfile.lambda`
  returned zero hardcoded secrets. `setup_security.py:133` hydrates secrets from `.env`
  into Secrets Manager at deploy time; nothing committed.
- **COMP-009 (scoped IAM + MFA, L2) — PASS.** `iam_solace_developer_policy.json` scopes
  every statement to `solace-*` ARNs; the few `Resource: "*"` entries are list/auth-token
  actions that AWS cannot ARN-scope (ECR GetAuthorizationToken, CloudFront/WAF/Amplify
  control-plane, KMS list). Principal is never `"*"` in any grant policy. The S3
  `DenyInsecureTransport` statement uses `Principal: "*"` correctly (a Deny, the intended
  pattern). `iam_mfa_boundary.json` enforces `aws:MultiFactorAuthPresent=false` deny with a
  minimal MFA-enrollment NotAction allowlist. Exec-role policy
  (`setup_exec_role_iam.py`) is scoped to `solace-*` tables + self-ARN; only `polly:
  SynthesizeSpeech` is `"*"` (Polly has no resource-level scoping — standard).
- **SEC-009 (parameterized keys, L2) — PASS.** No f-string interpolation of user input
  into DynamoDB keys/expressions anywhere in `scripts/`. All updates use
  `UpdateExpression` placeholders + `ExpressionAttributeValues`.
- **DEPS-003 (Lambda image, L1) — PASS.** `Dockerfile.lambda:3` uses
  `public.ecr.aws/lambda/python:3.12` (AL2023); native `libgomp` via `dnf`; arm64 wheels
  preserved (`deploy_container.py` builds `--platform linux/arm64`, `Architectures=
  ["arm64"]`). Bonus hardening: drops to non-root UID 993, clears dnf cache, removes the
  requirements manifest from the image layer.

---

## Required actions before approval

1. Gate `deploy_container.py`, `deploy_amplify.py`, `deploy_landing.py`,
   `enable_provisioned.py` (and ideally the `setup_*` / `harden_runtime` mutators) behind
   `--apply`, defaulting to dry-run. (BLOCK-1)
2. Change the deployed `CLAUDE_PROVIDER` default to `bedrock` in `deploy_container.py:111`.
   (BLOCK-2)
3. Before any PHI traffic: provision ACM cert + custom domain so CloudFront enforces
   `TLSv1.2_2021`, not the TLSv1 default-cert fallback. (MEDIUM)
4. Fix the misleading CORS log in `harden_runtime.py:85`. (LOW)
