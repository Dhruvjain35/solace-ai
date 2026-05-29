# Solace Infrastructure & Dependency Security Audit

> Date: 2026-05-16
> Scope: `Dockerfile.lambda`, `.dockerignore`, `scripts/setup_security.py`,
> `scripts/setup_waf_cloudfront.py`, `scripts/setup_abuse_prevention.py`,
> `requirements-lambda.txt` (CVE review only).
> Frameworks: HIPAA §164.312, SOC 2 CC6/CC8, AWS Shared Responsibility.

---

## 1. Summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F1 | Lambda container runs as root | High | Fixed |
| F2 | No `.dockerignore` — secrets/keys/`.env` could enter build context | High | Fixed |
| F3 | Build-time `requirements-lambda.txt` shipped inside the runtime image | Low | Fixed |
| F4 | `dnf` metadata cache baked into image layer | Low | Fixed |
| F5 | CloudFront `MinimumProtocolVersion` pinned to `TLSv1` (violates COMP-004) | High | Mitigated (ACM branch added) |
| F6 | Stale docstrings vs. live rate-limit / throttle values | Low | Fixed |
| F7 | `starlette==0.38.6` — CVE-2025-54121 multipart DoS | High | CVE bump recommended |
| F8 | `python-multipart==0.0.10` — CVE-2024-53981 logging DoS | High | CVE bump recommended |
| F9 | `requests==2.32.3` — CVE-2024-47081 `.netrc` credential leak | Medium | CVE bump recommended |
| F10 | `Pillow==11.0.0` — DDS encode heap overflow class (CVE-2025-48379) | Medium | CVE bump recommended |
| F11 | CloudFront access logging disabled | Medium | Manual action |
| F12 | CloudFront forwards all headers/cookies/querystring | Low | Advisory |

---

## 2. Findings detail

### F1 — Lambda container ran as root (High)
`Dockerfile.lambda` had no `USER` directive, so the handler executed as UID 0.
If application code is compromised (e.g. through a dependency CVE), the attacker
inherits root inside the container. Although Lambda's microVM provides a strong
boundary, dropping privileges is defence-in-depth and a SOC 2 CC6 expectation.

**Fix applied:** added `USER 993` (the AL2023 Lambda base image's pre-created
non-root `sbx_user1051`). Runtime task files stay world-readable so the handler
still loads.

### F2 — Missing `.dockerignore` (High)
With no `.dockerignore`, any `COPY . .` or broad context send would pull `.env`
(real API keys — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`,
`DEMO_CLINICIAN_PIN`), `.git/` history, the `data/` training set, `frontend/`,
and `.venv/` into the build context and potentially into image layers. This
risks COMP-007 (no secrets in source control / artifacts).

**Fix applied:** created `.dockerignore` excluding `.env*`, `*.pem`/`*.key`/
certs, `keys/`/`secrets/`/`credentials*`, `.venv/`, `__pycache__/`, `.git/`,
`data/`, `demo/`, `build/`, `frontend/`, `landing/`, `node_modules/`, `docs/`,
and `*.md`. The current Dockerfile only `COPY`s explicit paths, but the ignore
file makes the guarantee independent of future Dockerfile edits.

### F3 — Build manifest shipped in runtime image (Low)
`requirements-lambda.txt` was copied to `/tmp` and left there. The pinned
dependency list is low-sensitivity but unnecessary at runtime and aids an
attacker fingerprinting installed versions.

**Fix applied:** `rm -f /tmp/requirements-lambda.txt` in the same `RUN` layer
as `pip install`.

### F4 — dnf cache baked into layer (Low)
`dnf clean all` clears the package cache contents but the directory tree can
remain. Added explicit `rm -rf /var/cache/dnf` in the same `RUN` to keep the
layer minimal.

### F5 — CloudFront TLS floor at TLSv1 (High, COMP-004)
`ViewerCertificate` used `CloudFrontDefaultCertificate=True` with
`MinimumProtocolVersion="TLSv1"`. Constitution **COMP-004** requires CloudFront
to enforce TLS 1.2 minimum. AWS does **not** allow raising the floor above
`TLSv1` while using the shared `*.cloudfront.net` default certificate — a custom
ACM certificate (in `us-east-1`) is required to select `TLSv1.2_2021`.

**Fix applied:** added `_find_acm_cert()` and `_viewer_certificate()` plus a
`CUSTOM_DOMAIN` config knob. When a custom domain is set and an ISSUED ACM cert
exists in `us-east-1`, the distribution is built with
`MinimumProtocolVersion="TLSv1.2_2021"`, `SSLSupportMethod="sni-only"`, and the
domain as a CloudFront alias. Without a custom domain it falls back to the
default cert (still `TLSv1`, with a `[warn]`).

**Residual:** until a custom domain + ACM cert are provisioned and
`CUSTOM_DOMAIN` is set, the edge still presents `TLSv1` as the floor. This is an
AWS-platform limitation, not a code gap — see §4. Note API Gateway and the S3
bucket policy already reject `aws:SecureTransport=false`, so PHI is never served
over true cleartext; the gap is only the *minimum negotiated TLS version* at the
CloudFront viewer edge.

### F6 — Stale docstrings (Low)
- `setup_waf_cloudfront.py` docstring said `SolaceRateLimit 10000/5min/IP`;
  `_rules()` actually sets `Limit: 50000`. Docstring corrected to 50000 with the
  rationale (hospital NAT egress sharing).
- `setup_abuse_prevention.py` docstring listed per-route throttles as
  `30 req/min … burst 5`; `ROUTE_THROTTLES` actually sets 100 rps / burst 300
  (and 50/200 rps for scan-insurance / public-patients). Docstring corrected to
  match the live values and the in-code rationale.

These were documentation drift, not behavioural bugs — the live values were
already the intended ones (see the explanatory comments next to each).

### F11 — CloudFront access logging disabled (Medium)
`Logging.Enabled` is `False`. For a PHI-handling edge, request-level logs feed
incident response and abuse forensics (SOC 2 CC7). Recommend enabling logging to
a dedicated, CMK/AES256-encrypted, access-blocked S3 bucket with a retention
lifecycle. Not changed here — requires provisioning a log bucket (AWS-side).

### F12 — Over-broad cache-key forwarding (Low / advisory)
`ForwardedValues` forwards all headers (`["*"]`), all cookies, and querystring.
For an API origin with `TTL=0` this is functionally correct (nothing is cached)
but `ForwardedValues` is the legacy model. Migrating to an
origin-request-policy + cache-policy pair (`AllViewerExceptHostHeader`) is
cleaner and avoids forwarding the `Host` header to the origin. Advisory only.

---

## 3. CVE bump recommendations (NOT applied — no package installs permitted)

All four live in `requirements-lambda.txt`. Bump and rebuild the Lambda
container image; re-run any multipart upload / image scan smoke tests after.

| Package | Current | Recommended | CVE | Severity | Notes |
|---------|---------|-------------|-----|----------|-------|
| `starlette` | `0.38.6` | `>=0.47.2` | CVE-2025-54121 | High | Multipart large-file rollover blocks the event loop (DoS). Solace accepts multipart intake uploads — directly exposed. Bumping past 0.40 may require a FastAPI bump for compatibility; verify against `fastapi==0.115.0` or bump FastAPI in lockstep. |
| `python-multipart` | `0.0.10` | `>=0.0.18` | CVE-2024-53981 | High | Per-byte logging on malformed `multipart/form-data` boundaries causes CPU-bound DoS. Solace parses multipart on intake/transcribe/scan-insurance routes — directly exposed. Latest is 0.0.28. |
| `requests` | `2.32.3` | `>=2.32.4` | CVE-2024-47081 | Medium | `.netrc` credential leak via maliciously-crafted URLs. Low live exposure (no `.netrc` expected in the Lambda image and SSRF is mitigated by `_validate_redirect_uri` per SEC-010), but a free, low-risk patch bump. |
| `Pillow` | `11.0.0` | `>=11.3.0` | CVE-2025-48379 | Medium | Heap buffer overflow when *saving* large DDS images. Solace decodes uploaded insurance-card images; it does not save DDS, so live exposure is low. Still recommend the bump to clear the scanner and pick up other 11.1–11.3 fixes. |

**Coordinated-bump notes (DEPS-007, DEPS-003/004):**
- `starlette` + `fastapi` must move together — pick a FastAPI release whose
  pinned `starlette` range already includes `>=0.47.2`.
- Do NOT change the Lambda base image or strip arm64 wheels (DEPS-003).
- `scipy`/`numpy` pins must stay identical to the ML training image (DEPS-004) —
  none of the four bumps above touch those.

---

## 4. AWS-side manual actions

1. **Provision a custom domain + ACM certificate** (`us-east-1`, DNS-validated)
   for the Solace API edge, then set `CUSTOM_DOMAIN` in
   `setup_waf_cloudfront.py` and re-run it. This is the only way to satisfy
   COMP-004's TLS 1.2 minimum at the CloudFront viewer edge.
2. **Enable CloudFront access logging** to a dedicated encrypted, public-access-
   blocked S3 bucket with a retention lifecycle (F11).
3. **Confirm the deployed Lambda image** was rebuilt after the `USER` change so
   the running function actually executes as non-root.
4. **Rebuild + redeploy the Lambda container image** after applying the CVE
   bumps in §3.
5. **Rotate any credentials** that may have been exposed if prior images were
   built without `.dockerignore` and pushed to a shared/public ECR repo
   (precautionary — verify ECR repo visibility).

---

## 5. Remediation checklist

- [x] Add non-root `USER` to `Dockerfile.lambda`
- [x] Remove dnf cache (`rm -rf /var/cache/dnf`) in the install layer
- [x] Remove `/tmp/requirements-lambda.txt` after `pip install`
- [x] Create `.dockerignore` excluding secrets / keys / `.venv` / `__pycache__` /
      `.git` / `data` / `frontend`
- [x] Reconcile WAF rate-limit docstring (`10000` → `50000`)
- [x] Reconcile per-route throttle docstring (`30/min burst 5` → live rps/burst)
- [x] Add ACM-cert branch so `MinimumProtocolVersion` can be `TLSv1.2_2021`
- [ ] Bump `starlette` to `>=0.47.2` (with coordinated `fastapi` bump) — CVE-2025-54121
- [ ] Bump `python-multipart` to `>=0.0.18` — CVE-2024-53981
- [ ] Bump `requests` to `>=2.32.4` — CVE-2024-47081
- [ ] Bump `Pillow` to `>=11.3.0` — CVE-2025-48379
- [ ] Provision custom domain + ACM cert; set `CUSTOM_DOMAIN`; re-run WAF script
- [ ] Enable CloudFront access logging to an encrypted log bucket
- [ ] Rebuild + redeploy Lambda image; confirm it runs as non-root
- [ ] Migrate CloudFront `ForwardedValues` to cache/origin-request policies (advisory)
