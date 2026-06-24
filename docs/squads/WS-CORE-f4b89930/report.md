# WS-CORE-f4b89930 — Multi-tenant Workspace feature

## 1. Research: how tenancy works today
- `hospital_id` is the top-level tenant boundary (URL-safe slug minted by
  routers/hospitals.py::provision_hospital; slug == hospital_id). Per-hospital routes
  mount under prefix="/api/{hospital_id}" in main.py.
- Isolation is enforced at the JWT layer: lib/jwt_auth.py puts `hid` in the token;
  lib/auth.py::verify_clinician returns 403 "hospital mismatch" when sess.hospital_id !=
  path hospital_id (SEC-008 / COMP-011). require_clinician is the shared dependency.
- Defense-in-depth already exists in lib/tenant.py::assert_patient_in_hospital. Mirrored
  for workspaces.
- The frontend components/workspace/ concept is the per-PATIENT working surface
  (PatientWorkspaceContext + tabs), NOT tenancy. Not touched, not duplicated.

Decision: a Workspace is a SUB-TENANT scope WITHIN a hospital (department/clinic/team).
hospital_id stays org-level; workspace_id is a child scope owned by exactly one hospital.
Flow: /api/{hospital_id} path -> require_clinician JWT hospital check -> service-layer
ownership assertion before any read/mutation.

## 2. Design
- Entity: { hospital_id, workspace_id, name, description, status, created_by, created_at,
  updated_at } — NON-PHI tenant config only.
- workspace_id: ^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$, 3-48 chars, reserved words blocked,
  generated from name with random suffix on collision (scoped to hospital partition).
- DDB table solace-workspaces: partition hospital_id, sort workspace_id. List = single
  .query() (PERF-004). Parameterized Key={...} / Key().eq() — no f-string interpolation
  (SEC-009). NO TTL (durable config, not transient -> ARCH-009 N/A). CMK-at-rest via IaC.
- Isolation: structural key + assert_owned() guard; cross-hospital ops -> 404 (existence
  hidden, extends SEC-008). DDB mutations carry ConditionExpression -> fail closed.
- Audit (COMP-002): every mutation calls audit(); reads too. Only hospital_id/workspace_id
  in extra (NON-PHI).

## 3. Implementation — files changed
- backend/db/storage.py: NEW put/get/list/update/delete_workspace, WORKSPACES_TABLE,
  in-memory _workspaces, extended _reset_for_tests(). boto3 stays here (ARCH-002), Key() (SEC-009).
- backend/services/workspaces.py: NEW service layer — id validation/generation,
  assert_owned cross-tenant guard, CRUD, typed WorkspaceError hierarchy. No boto3 (ARCH-001/002).
- backend/routers/workspaces.py: NEW 5 endpoints under /api/{hospital_id}. Inline Pydantic
  (ARCH-005), require_clinician (SEC-008), HTTPException + audit() (QUAL-003/COMP-002),
  logging not print (QUAL-006).
- backend/main.py: imported + mounted workspaces.router with prefix="/api/{hospital_id}".
- backend/tests/test_workspaces.py: NEW 31 tests.

## 4. Verify (honest)
- cd backend && .venv/bin/python -m pytest tests/test_workspaces.py -q  -> 31 passed
- cd backend && .venv/bin/python -m pytest -q  -> 509 passed, 6 skipped, 1 warning
  (warning is pre-existing OverrideBody, unrelated)
- cd backend && .venv/bin/python -c "import main"  -> OK
Coverage: CRUD, requested_id + generated id, auth gating (401), id validation (400 vs 404,
reserved), duplicate->409, cross-hospital isolation (get/update/delete all 404, no mutation
of the other tenant; same id under two hospitals isolated), service-level assert_owned + id gen.

## 5. L1 self-review
ARCH-001 PASS (router->service->db). ARCH-002 PASS (no boto3 in router/service).
ARCH-005 PASS (inline Pydantic). SEC-008 PASS+extended (JWT + assert_owned, cross-tenant 404).
SEC-009 PASS (parameterized Key). COMP-002 PASS (audit on mutations). QUAL-003 PASS
(HTTPException). QUAL-006 PASS (logging, no print). SEC-004/005 N/A (no AI, no PHI).
ARCH-009 N/A (durable config, intentionally no TTL).

## Assumptions / notes for the lead
1. Workspace = sub-tenant within a hospital; NOT a rename of hospital_id and NOT the
   frontend PatientWorkspace. Flag if product meant the hospital-level tenant.
2. solace-workspaces DDB table not yet provisioned — needs IaC in scripts/setup_aws.py
   (partition hospital_id, sort workspace_id, CMK alias/solace, no TTL). Local mode works.
   No AWS mutation was run (per L1).
3. No frontend wiring (out of scope for solace-core). Future FE squad adds lib/api.ts (ARCH-007).
4. workspace_id is the container entity; associating clinicians/patients to a workspace
   (add workspace_id attr + GSI) is the natural next step, not in scope here.
5. git not run (sandbox-blocked). Lead commits the worktree branch.
