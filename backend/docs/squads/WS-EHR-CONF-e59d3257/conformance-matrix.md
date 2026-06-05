# EHR Conformance & Integration Matrix — WS-EHR-CONF-e59d3257

Marketplace-certification evidence for Solace's EHR integration. This documents
(1) the internal, offline conformance suite and its current pass/fail status
against the mock FHIR server, and (2) exactly how to point the same adapters at
the public vendor sandboxes once real credentials arrive.

Everything here is reproducible with **no network and no vendor account**:

```bash
cd backend
.venv/bin/python -m pytest tests/ehr/ -q          # full EHR + conformance suite
.venv/bin/python -c "import main"                 # app import sanity
```

---

## 1. What was certified

| Area | Mechanism | File |
|------|-----------|------|
| US Core 6.1.0 / USCDI v3 profiles | Inferno-style validator (cardinality, must-support, required bindings) | `backend/lib/us_core_conformance.py` |
| US Core read + write conformance | Validates static fixtures, seeded search Bundles, and every `fhir_writer` builder | `backend/tests/ehr/test_us_core_conformance.py` |
| SMART App Launch v2 | PKCE S256, discovery, state/nonce, scope grammar, launch context, private_key_jwt | `backend/tests/ehr/test_smart_v2_conformance.py` |
| id_token JWKS signature verification | `verify_id_token()` + RS256/384/512 verify, claim checks, honest fallback | `backend/lib/smart_auth.py`, `backend/tests/ehr/test_jwks_verify.py` |

---

## 2. US Core conformance status (against the mock + fixtures)

`lib/us_core_conformance.validate_resource()` separates **errors** (L1 — fail the
gate) from **warnings** (must-support advisories — a *strict* Inferno run flags
them, basic interop does not).

| Resource | Direction | Status | Required-binding checks |
|----------|-----------|--------|--------------------------|
| Patient | read | PASS | identifier(1..*), name, gender ∈ AdministrativeGender; birthDate MS |
| Condition | read + write | PASS | category(1..*), code→ICD-10-CM/SNOMED, clinicalStatus value set |
| AllergyIntolerance | read + write | PASS | patient, code, clinicalStatus value set |
| Observation (vitals/labs/social) | read + write | PASS | status value set, category, code→LOINC, value UCUM |
| MedicationStatement | write | PASS | status value set, medication→RxNorm, subject |
| Immunization | write | PASS | status value set, vaccineCode→CVX, occurrence, primarySource MS |
| DocumentReference | write | PASS | status, type→LOINC, category, content.attachment.contentType |
| Provenance | write | PASS | target, recorded, agent(1..*) |
| Encounter, Procedure | read | ADVISORY | surfaced by reader; not yet profile-gated (no error path) |

**Fixture fix applied:** `tests/ehr/fixtures/condition.json` was missing the
US Core-required `Condition.category`; added `problem-list-item`. This was a real
(latent) non-conformance in test data, now corrected.

Run: `215 passed` in `tests/ehr/` (156 pre-existing + 59 new). Full backend
suite: `657 passed, 6 skipped`.

---

## 3. SMART App Launch v2 conformance status

All assertions pass against `lib/smart_auth` + `routers/ehr_auth`:

| SMART v2 / ONC (g)(10) requirement | Status | Evidence |
|------------------------------------|--------|----------|
| PKCE mandatory, S256 only (no `plain`) | PASS | `generate_pkce`, router advertises `code_challenge_method=S256` |
| PKCE verifier length 43–128 (RFC 7636) | PASS | `test_verifier_within_rfc7636_length_bounds` |
| `.well-known/smart-configuration` discovery | PASS | `parse_smart_configuration`, capabilities/auth-methods/jwks parsed |
| `state` CSRF — unguessable + constant-time compare | PASS | `generate_state`/`validate_state` |
| `nonce` OIDC replay — echoed + validated | PASS | `generate_nonce`/`validate_nonce`, enforced in `/callback` |
| Scope grammar `resource.cruds` (+v1 upgrade) | PASS | `parse_scope`, `scope_granted`, `build_v2_scopes` |
| Launch contexts (patient/encounter/fhirContext) | PASS | `extract_launch_context` |
| Confidential asymmetric client (private_key_jwt, RS384) | PASS | `build_client_assertion` round-trips |
| id_token signature verified vs issuer JWKS | PASS (RSA) / FALLBACK (EC) | see §4 |

---

## 4. id_token JWKS verification — gap closed

**Before:** `smart_auth.decode_jwt_claims` decoded the id_token but never
verified its signature; trust rested entirely on the TLS channel from the token
endpoint (flagged in `docs/squads/WS-EHR-MKT-69eb167d/gap-checklist.md`).

**After:** added `smart_auth.verify_id_token()`:

- Verifies **RS256 / RS384 / RS512** signatures against the issuer's published
  JWKS (pure-Python `pow(sig, e, n)` + EMSA-PKCS1-v1_5 compare — no
  `cryptography` dependency, matching the existing RS384 signer).
- Always validates `iss` / `aud` / `nonce` / `exp` / `iat` claims when the
  caller supplies the expected values — a wrong audience is rejected even on the
  TLS-trust path.
- Rejects `alg=none`, tampered payloads, wrong-key signatures, and bad claims
  with `IdTokenVerificationError`.
- **Honest fallback:** when no JWKS is discoverable, or the key is EC (ES*, which
  needs EC math we do not implement offline), it returns
  `IdTokenResult(verified=False, fallback=True)` so the *pre-existing*
  TLS-channel-trust behavior is preserved rather than hard-failing a flow that
  worked before. The nonce is still enforced in the fallback.

**Wiring:** `routers/ehr_auth.launch` now stores the discovered `jwks_uri`,
`issuer`, and `client_id` in the OAuth state; `/callback` calls
`verify_id_token(...)` and rejects on `IdTokenVerificationError`, logs the
verified/fallback outcome otherwise. No PHI or token material is logged (SEC-002).

**Residual:** ES256/384 id_tokens are NOT cryptographically verified offline.
SMART permits EC keys; if a target sandbox issues ES* id_tokens, either (a) add a
minimal P-256/P-384 verify, or (b) accept TLS-trust for that issuer. Most EHRs
(Epic, Cerner, SMART Health IT) issue RS* id_tokens, so the RSA path covers them.

---

## 5. Sandbox run matrix (when real creds arrive)

The adapters are credential-driven via env vars; no code change is needed to
point them at a real sandbox. Set the per-vendor vars, then exercise the same
launch → callback → read/write flow.

### 5.1 Common env (per vendor `<V>` ∈ SMART / EPIC / CERNER / ATHENA)

```
SOLACE_<V>_CLIENT_ID         # registered client id
SOLACE_<V>_AUTHORIZE_URL     # optional; discovery overrides when present
SOLACE_<V>_TOKEN_URL         # optional; discovery overrides when present
SOLACE_<V>_FHIR_BASE_URL     # vendor FHIR R4 base
SOLACE_<V>_KID               # private_key_jwt key id (confidential clients only)
```

### 5.2 SMART Health IT reference sandbox (start here)

- FHIR base: `https://launch.smarthealthit.org/v/r4/fhir`
- Discovery: append `/.well-known/smart-configuration` — issues **RS256**
  id_tokens, so JWKS verification is fully exercised.
- Public, no registration needed for the open client. Best first target to prove
  the live discovery + JWKS path end-to-end.
- Expected: `verify_id_token` returns `verified=True`.

### 5.3 Epic on FHIR sandbox

- Register app at <https://fhir.epic.com> → get a client id.
- Sandbox FHIR base: `https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4`
- Supports SMART v2 launch + `private_key_jwt` (register an RSA-2048 public key;
  set `SOLACE_EPIC_KID`). Epic issues RS256 id_tokens → JWKS path verifies.
- US Core test patients (e.g. Camila Lopez, Derrick Lin) are documented in Epic's
  sandbox. Run `read_uscdi_summary` against one to confirm read conformance with
  live data shapes.

### 5.4 Oracle Health / Cerner sandbox

- Console: <https://code.cerner.com>; open sandbox FHIR base:
  `https://fhir-open.cerner.com/r4/<tenant>` (open) or the secure SMART base for
  authorized reads/writes.
- Register a SMART app for the secure base; supports SMART v2 + PKCE.
- Confirm `Observation`/`Condition`/`AllergyIntolerance` reads normalize, and
  that write-back lands on the correct endpoints per the adapter routing.

### 5.5 athenahealth sandbox

- Marketplace developer portal; OAuth2 `client_credentials` + SMART.
- The mock already models athena's `/oauth2/v1/token` shape (see
  `mock_fhir_server._handle`); the live token endpoint should drop in via
  `SOLACE_ATHENA_TOKEN_URL`.

### 5.6 Per-sandbox checklist (record pass/fail when run)

For each sandbox, capture:

1. Discovery doc fetched, S256 + auth methods advertised.  ☐
2. Launch → authorize → callback completes; `state` + `nonce` round-trip.  ☐
3. `verify_id_token` → `verified=True` (RS*) or documented `fallback` (ES*).  ☐
4. `read_uscdi_summary` returns conformant resources (run them through
   `us_core_conformance.validate_resource`; expect `ok=True`, note warnings).  ☐
5. Write-back (DocumentReference / Condition / Observation) accepted with
   `201 Created`; written body passes `assert_conformant`.  ☐
6. `$export` bulk kickoff → status poll → NDJSON retrieval (if entitled).  ☐

---

## 6. What still needs real sandbox credentials

The offline suite proves **shape + protocol** conformance. It cannot prove
**live-server** acceptance. Outstanding, creds-gated:

- Real `.well-known/smart-configuration` round-trip per vendor (mock returns a
  synthetic doc).
- Real authorize-screen consent + auth-code redemption (mock returns a fixed
  bearer token).
- Live JWKS fetch + RS256 id_token verification end-to-end (unit-proven with a
  test keypair; not yet against a live `jwks_uri`).
- Vendor-specific write endpoints (Epic `Condition.$add`, etc.) returning
  `201`/`200` on a real tenant.
- Bulk `$export` entitlement (most sandboxes gate `system/*.read`).
- ES256/384 id_token handling decision (see §4 residual) if any target issuer
  uses EC keys.
