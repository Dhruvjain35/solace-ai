# Tenancy Recommendation — `hospital_id` today, `workspace_id` design

> Research squad WS-RSCH-2740a567. Respects SEC-008 (JWT + hospital_id match) and SEC-009 (parameterized DynamoDB keys).

## 1. How `hospital_id` tenancy works today

`hospital_id` is the single tenant axis. It is set at provisioning time, equals the URL-safe slug, and threads end-to-end:

| Layer | Mechanism | Evidence |
|---|---|---|
| URL / routing | Every clinical route is `/api/{hospital_id}/...`; frontend mirrors `/h/{slug}/...` and `/{slug}/...` | `backend/main.py:129-157`, `frontend/src/App.tsx:27-61` |
| Provisioning | `POST /hospitals/provision` slugifies the name, ensures uniqueness, writes `solace-hospitals` with `hospital_id == slug` | `routers/hospitals.py:101-143` |
| Identity | JWT carries `hid` claim; `issue_token` puts `hospital_id` in `hid` | `lib/jwt_auth.py:229-238` |
| Authz | `verify_clinician` rejects 403 if `sess.hospital_id != hospital_id` from the path (SEC-008) | `lib/auth.py:44-45` |
| Data partition | Patients GSI `hospital_id-created_at-index`; clinicians/accounts/tokens/overrides/labels/billing all partition by `hospital_id` | `db/storage.py:205-211`, `lib/accounts.py:76-83`, `db/storage.py:361-406,455-500,511-601` |
| Defense in depth | `tenant.assert_patient_in_hospital()` re-checks after any `get_patient` | `lib/tenant.py:40-53`, used in `services/copilot/context.py:48-53` |
| Cross-hospital read | Both router 403 (SEC-008) AND record-level guard (COMP-011) — a patient loaded by id is rejected if its `hospital_id` mismatches | `lib/tenant.py:29-53` |

**Key facts the design must preserve:**
- `hospital_id` is a *string slug*, human-meaningful, used as a DynamoDB partition key value via `boto3.dynamodb.conditions.Key()` (SEC-009).
- Clinicians belong to exactly one `hospital_id` (`lib/accounts.py:98-109`); the JWT binds them to it.
- `demo` is a reserved, separately-seeded hospital (`storage.seed_demo_hospital`, `routers/hospitals.py:48-51`).

## 2. What a `workspace_id` adds — and what it must NOT break

The 5-squad effort introduces a **Workspace** concept. The product reality: a hospital (tenant/billing boundary) may run **multiple workspaces** — e.g. an ED workspace, a primary-care workspace, an Atlas-orders workspace — each a scoped view/config over the same tenant's data, possibly with different enabled features (triage vs. Atlas order-entry) and different clinician membership.

**Recommended model: `workspace_id` is a CHILD of `hospital_id`, never a replacement.**

```
hospital_id  (tenant / BAA / billing boundary — UNCHANGED, slug)
   └── workspace_id  (a scoped operating context inside the hospital)
         ├── enabled features (triage, copilot, atlas-orders, scribe, ...)
         ├── clinician membership (subset of the hospital's clinicians)
         └── default EHR vendor binding (optional)
```

This keeps SEC-008's `hospital_id` cross-check the **primary** isolation boundary (HIPAA tenant isolation is unchanged) and makes `workspace_id` a **secondary, intra-tenant scope** — a feature/membership filter, not a new security perimeter. Critically: **a `workspace_id` is only ever valid within its `hospital_id`.** Authorization always checks `hospital_id` first, then (if the route is workspace-scoped) confirms the workspace belongs to that hospital and the clinician is a member.

### Relationship rules (L1-equivalent intent)
1. Every `workspace_id` row stores its owning `hospital_id`. A workspace can never be addressed without its hospital in the path.
2. JWT keeps `hid` as the authoritative tenant. A new `wsids` claim (list) or `ws` claim (active) is **advisory** — the server re-verifies membership against storage, never trusts the token alone (same posture as `lib/jwt_auth.py` algorithm allowlisting).
3. Default/back-compat: a hospital with no explicit workspaces behaves exactly as today — synthesize a single implicit workspace `ws-default` (or treat `workspace_id == hospital_id`) so all current routes, tokens, and the `demo` flow keep working with zero migration.

## 3. DynamoDB key strategy

Two viable shapes; **Recommendation = Option A** for least churn.

### Option A (recommended): new `solace-workspaces` table + workspace as GSI sort dimension on existing tables

**New table `solace-workspaces`:**
- PK (HASH): `hospital_id`
- SK (RANGE): `workspace_id`
- Attributes: `name`, `slug`, `features` (string set), `created_at`, `default` (bool), `ehr_vendor` (optional), `ttl` absent (durable).
- GSI `workspace-index`: HASH `workspace_id` (for the rare reverse lookup), but prefer always querying by `(hospital_id, workspace_id)` so you never need it.
- Query by `Key("hospital_id").eq(hid) & Key("workspace_id").eq(wsid)` — parameterized (SEC-009).
- CMK-encrypted via `alias/solace` (COMP-003), created in `scripts/setup_aws.py` style.

**Workspace membership** (clinician ↔ workspace): add `workspace_ids` (DynamoDB string set) onto the existing `solace-clinicians` record (`lib/accounts.py:98-109`). No new table; membership is read on login and embedded as the advisory JWT claim. Admin add/remove updates the set with a parameterized `update_item`.

**Patient/data tagging:** add a `workspace_id` attribute to patient records at intake (defaulting to the hospital's default workspace). For listing-by-workspace, **reuse the existing `hospital_id-created_at-index`** and post-filter by `workspace_id` in `storage.list_patients_for_hospital` (the result set is already hospital-scoped and small per the polling cadence). Only if a hospital grows large workspaces do you add a dedicated GSI `hospital_workspace-index` (HASH `hospital_id#workspace_id`, RANGE `created_at`) — keep this a documented "scale later" step to avoid a costly migration now.

### Option B (NOT recommended now): composite partition `hospital_id#workspace_id` everywhere
Cleaner isolation but requires rewriting every partition key + a full data migration of `solace-patients`, `solace-clinicians`, overrides/labels/billing. High blast radius across all 5 branches. Defer.

## 4. JWT claim flow

Current claims (`lib/jwt_auth.py:229-238`): `sub`, `name`, `role`, `hid`, `iat`, `exp`.

Add, additively (no removals — existing 30-min tokens keep validating, same backward-compat posture as the `exp` hardening at `jwt_auth.py:250-257`):

```
hid   : hospital_id              # unchanged, authoritative tenant
ws    : active workspace_id      # optional; advisory
wsids : [workspace_id, ...]      # optional; the clinician's memberships (advisory)
```

Flow:
1. Login (`routers/auth.py` / magic-link) → `accounts.find_clinician*` returns the record → read `workspace_ids` → `issue_token` stamps `ws`/`wsids`.
2. `verify_clinician` (`lib/auth.py:19-53`) keeps the `hid != path hospital_id` 403 as the FIRST gate (SEC-008, unchanged).
3. For workspace-scoped routes, add a NEW dependency `require_workspace_member(hospital_id, workspace_id)` that: (a) confirms the workspace row exists under that `hospital_id`; (b) confirms `workspace_id in caller.wsids` OR re-reads membership from storage if the claim is absent (token issued before the feature). Reject 403 on miss, 404 if the workspace isn't in the hospital (no existence leak).
4. Switching active workspace re-issues a token (or is a pure client-side concern if all routes accept any member workspace).

## 5. Isolation guarantees

- **Tenant isolation (HIPAA, unchanged):** `hospital_id` JWT match (SEC-008) + record-level `tenant.assert_patient_in_hospital` (COMP-011). `workspace_id` never weakens this.
- **Intra-tenant scope:** workspace membership check is a *second* gate; a clinician in hospital H but not workspace W gets 403 on W's routes even though they share a tenant.
- **No new free-string keys:** all workspace lookups use `Key()` builders (SEC-009). `workspace_id` is generated server-side (slug + random suffix, mirroring `routers/hospitals.py:75-88`), never raw user input interpolated into a key.
- **Audit:** extend `audit.record` extra payload with `workspace_id` so the 6-year trail (COMP-002) is workspace-attributable. No PHI added.

## 6. Migration plan (zero-downtime, back-compat)

1. **Add table + GSI (PROD squad, dry-run/IaC):** `solace-workspaces` via a new `scripts/setup_workspaces_table.py` mirroring `scripts/setup_labels_table.py`. Idempotent, CMK-encrypted.
2. **Backfill default workspace:** for every existing hospital, write one `ws-default` workspace with all current features enabled. Existing patients get `workspace_id = "ws-default"` lazily on next write (storage layer fills the default if absent) — no bulk rewrite required.
3. **Membership backfill:** every existing clinician gets `workspace_ids = {"ws-default"}` on next login (lazy), or a one-shot idempotent script.
4. **Token compat:** tokens without `ws`/`wsids` are treated as "member of the hospital's default workspace," so no mass 401 on deploy.
5. **Route rollout:** new workspace-scoped routes are additive; existing `/api/{hospital_id}/...` routes keep working (they implicitly operate on the default workspace until the UI starts passing a workspace).
6. **Reserved ids:** reserve `ws-default`, `default`, `all` to avoid collisions; reuse the `_RESERVED_SLUGS` pattern (`routers/hospitals.py:48-51`).

## 7. Concrete file touch list (for CORE squad)

- `lib/jwt_auth.py` — add `ws`/`wsids` to `issue_token` claims + `Session` dataclass (additive).
- `lib/auth.py` — add `require_workspace_member` dependency; keep `verify_clinician` 403 first.
- `lib/accounts.py` — `workspace_ids` set on clinician records; `add_to_workspace` / `remove_from_workspace` helpers.
- `db/storage.py` — `put_workspace` / `get_workspace` / `list_workspaces(hospital_id)` (parameterized `Key()`), `workspace_id` default-fill on `put_patient`, optional filter in `list_patients_for_hospital`.
- `routers/workspaces.py` (NEW) — CRUD under `/api/{hospital_id}/workspaces`, `Depends(require_clinician)` + `audit()`.
- `routers/hospitals.py` — on provision, also create the `ws-default` workspace.
- `scripts/setup_workspaces_table.py` (NEW, PROD-owned) — table + GSI.

**Decision summary:** `workspace_id` is an intra-tenant child of the unchanged `hospital_id` security boundary; new `solace-workspaces` table keyed `(hospital_id, workspace_id)`; advisory JWT claims re-verified server-side; lazy backfill with an implicit `ws-default` so nothing breaks on deploy.
