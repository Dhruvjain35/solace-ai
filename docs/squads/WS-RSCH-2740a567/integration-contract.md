# Integration Contract — SOURCE OF TRUTH for all 5 squads

> Research squad WS-RSCH-2740a567. Base: `feature/copilot-phi-isolation` @ `9c24d23`. 5 parallel worktrees (CORE, RSCH, ATLAS, UIUX, PROD).
> This document defines file ownership, API/data contracts, the Atlas embedding seam, the AWS resource list, and a merge order that minimizes conflicts. Read the companion docs (codebase-map, tenancy-recommendation, atlas-embed-plan, aws-map) for detail.

## 1. Squads

| Squad | Workspace | Mission |
|---|---|---|
| CORE | WS-CORE-f4b89930 | `workspace_id` tenancy: storage, auth/JWT, accounts, workspaces router |
| RSCH | WS-RSCH-2740a567 | This research pack (docs only, no app code) |
| ATLAS | WS-ATLS-e7e48b60 | Embed Atlas order-entry as a backend service + Workspace tab |
| UIUX | WS-UIUX-62893b28 | UI refresh of existing pages/components |
| PROD | WS-PROD-ee835b8b | AWS IaC + deploy scripts (dry-run only) |

## 2. File ownership (authoritative — edit ONLY your column; coordinate on shared files)

### CORE owns
- `backend/db/storage.py` (workspace CRUD + `workspace_id` default-fill)
- `backend/lib/jwt_auth.py` (add `ws`/`wsids` claims, additive)
- `backend/lib/auth.py` (add `require_workspace_member`; keep `verify_clinician` unchanged)
- `backend/lib/accounts.py` (`workspace_ids` on clinician records + membership helpers)
- `backend/lib/tenant.py` (optional `assert_in_workspace`)
- `backend/routers/workspaces.py` (NEW)
- `backend/routers/hospitals.py` (create `ws-default` on provision)
- `backend/main.py` (register `workspaces` router — ONE line; see §6 conflict note)

### ATLAS owns
- `backend/services/atlas/` (NEW package: `tools.py`, `sanitize.py`, `loop.py`, `execute.py`, `context.py`)
- `backend/routers/atlas.py` (NEW)
- `backend/main.py` (register `atlas` router — ONE line; see §6 conflict note)
- `backend/tests/services/test_atlas_phi_isolation.py` (NEW, CI gate)
- `frontend/src/components/workspace/tabs/OrdersTab.tsx` (NEW)
- `frontend/src/lib/api-atlas.ts` (NEW)
- Workspace tab registry entry (extend the existing tab array — do NOT duplicate the workspace system)
- Reuses (read-only, no edits): `lib/claude.py`, `lib/content_guard.py`, `lib/audit.py`, `services/fhir_writer.py`, `services/copilot/context.py` patterns, `services/ehr_*`

### UIUX owns
- `frontend/src/components/{ui,clinician,patient}/**` (visual refresh)
- `frontend/src/pages/**` (visual refresh; NOT routing in `App.tsx` structure)
- `frontend/tailwind.config.ts`, design tokens
- MUST NOT change: `components/workspace/PatientWorkspaceContext.tsx` contract, `lib/api*.ts` function signatures, `App.tsx` route paths

### PROD owns
- `scripts/setup_*.py` (incl. NEW `scripts/setup_workspaces_table.py`)
- `scripts/setup_exec_role_iam.py` (append workspace-table actions)
- `buildspec.yml`, `Dockerfile.lambda`, `requirements-lambda.txt`, `requirements.txt`
- All IaC dry-run / deploy (no live mutation without Sriyan approval)

### RSCH owns
- `docs/squads/WS-RSCH-2740a567/**` only

## 3. API & data contracts (frozen interfaces other squads code against)

### 3.1 Tenancy (CORE → everyone)
- `hospital_id` stays the authoritative tenant + the URL segment `/api/{hospital_id}/...`. UNCHANGED.
- `workspace_id` is a CHILD of `hospital_id`; only valid within it; advisory in the JWT, re-verified server-side.
- New table `solace-workspaces`: PK `hospital_id`, SK `workspace_id`. Lookups via `boto3.dynamodb.conditions.Key()` (SEC-009).
- JWT gains additive claims `ws` (active) + `wsids` (list). Existing tokens (no claims) → treated as member of `ws-default`. No mass 401.
- New dependency `require_workspace_member(hospital_id, workspace_id)` — runs AFTER `verify_clinician`'s `hid` 403 (SEC-008). ATLAS and any workspace-scoped route depends on this.
- Default behavior: a hospital with no explicit workspaces = one implicit `ws-default`; all current routes keep working.

### 3.2 Atlas (ATLAS → UIUX/CORE)
Backend, mounted `/api/{hospital_id}/atlas`, `Depends(require_clinician)` (+ `require_workspace_member` once CORE lands):
- `POST /atlas/turn` — req `{patient_id: str, message: str(2..2000), history?: [{role, content}]}` → resp `{reply: str, proposed_actions: [{resource_type, summary, resource}], tool_log: [str]}`. Consent (SEC-004) + `content_guard.scan` (SEC-005) + `audit` (COMP-002) enforced.
- `POST /atlas/execute` — req `{patient_id: str, actions: [{resource_type∈{ServiceRequest,Condition,Observation,AllergyIntolerance,MedicationRequest}, summary, resource}]}` → resp `{written: [...], errors: [...]}`. Write-back via `services/fhir_writer`. `audit` enforced.

Frontend: `lib/api-atlas.ts` exports `postAtlasTurn(hospitalId, body)` and `postAtlasExecute(hospitalId, body)` via the shared axios instance (auto-Bearer, ARCH-007). `OrdersTab.tsx` consumes `usePatientWorkspace()` — NO props.

### 3.3 Workspace tab contract (UIUX/ATLAS — UNCHANGED, do not break)
Tabs take no props; read `{ hospitalId, patientId, patient, loading, error, reloadPatient, ehrFhirId, ehrLinked }` from `usePatientWorkspace()` (`PatientWorkspaceContext.tsx:60-69`). After any write, call `reloadPatient()`. New tabs register in the existing tab array.

## 4. The Atlas embedding seam (one place, named explicitly)

```
frontend OrdersTab.tsx ──(lib/api-atlas.ts)──► POST /api/{hid}/atlas/turn ──► routers/atlas.py
                                                                                   │
                          require_clinician + require_workspace_member (CORE)      │
                          consent (SEC-004) + content_guard.scan (SEC-005)         ▼
                                                                          services/atlas/loop.py
                                                          (lib/claude → Bedrock, COMP-005; tool-use)
                                                                                   │
                                          PHI zone: services/atlas/context.py + sanitize.py
                                          (tenant.assert_patient_in_hospital; coded-only to model)
                                                                                   ▼
   confirm ──► POST /atlas/execute ──► services/atlas/execute.py ──► services/fhir_writer.py ──► EHR
                                          audit (COMP-002) on turn AND execute
```
Atlas adds **routes + a service package + one tab + one api module**. It adds NO new infra and reuses every L1 control. It depends on CORE's `require_workspace_member` but can ship against `require_clinician` alone if CORE lands later (graceful: workspace check is additive).

## 5. AWS resource list (PROD — full detail in aws-map.md)

Existing (reuse): Lambda `solace-api` (container, Mangum), ECR `solace-api`, CodeBuild (`buildspec.yml`), DynamoDB `solace-*` tables, Secrets `solace/api-keys` + `solace/clinician-auth`, KMS `alias/solace`, S3 `solace-media-*`/`solace-lambda-deploy-*`/`solace-cloudtrail-*`, CloudFront+API GW (TLS 1.2), WAF, IAM `solace-lambda-exec` + `SolaceDeveloperAccess`/`SolaceMFARequired`.

Net-new for this effort: **exactly one** — DynamoDB `solace-workspaces` (PK `hospital_id`, SK `workspace_id`, CMK-encrypted) via new `scripts/setup_workspaces_table.py`. Plus an IAM action append to `solace-lambda-exec` (already in `solace-*` scope). Atlas needs zero new infra. **No live AWS mutation without Sriyan's approval.**

## 6. Merge / sequencing order (minimizes cross-branch conflict)

**Conflict hot-spot:** `backend/main.py` router-registration block (`main.py:128-167`) — BOTH CORE (workspaces router) and ATLAS (atlas router) add one `include_router` line. **Mitigation:** each squad appends its line at the END of the per-hospital block; the lead resolves the 2-line merge trivially. Frontend `App.tsx` is NOT touched (tabs register inside the workspace, not as routes).

Recommended merge sequence:

1. **PROD (infra first, additive, no app dependency)** — `solace-workspaces` table script + exec-role IAM append + any build pinning. Dry-run validated. Unblocks CORE's storage layer at runtime without blocking its code.
2. **CORE (tenancy spine)** — `storage.py`, `jwt_auth.py`, `auth.py`, `accounts.py`, `routers/workspaces.py`, `hospitals.py`, `main.py` (+1 line). Everything downstream depends on `require_workspace_member` and the `workspace_id` data contract. Land this before ATLAS's workspace-scoped routes.
3. **ATLAS (depends on CORE's auth dep + reuses fhir_writer/claude/content_guard)** — `services/atlas/`, `routers/atlas.py`, `main.py` (+1 line), `OrdersTab.tsx`, `api-atlas.ts`, PHI leak test. If CORE slips, ATLAS ships against `require_clinician` and adds the workspace dep in a follow-up.
4. **UIUX (touches only visual layer)** — merges last to rebase over OrdersTab + any new components. Lowest backend-conflict risk; only contention is new frontend components, resolved by the tab-registry append pattern.

Rationale: PROD and CORE are the data/auth foundation; ATLAS consumes them; UIUX is purely additive/visual and rebases cleanly on top. Backend conflicts are confined to two 1-line appends in `main.py`. Frontend conflicts are confined to the workspace tab-registry array (append-only) and net-new files.

## 7. Non-negotiable shared rules (all squads)

- Router→service→db layering (ARCH-001); boto3 only in `db/` (ARCH-002); AI adapters in `lib/` (ARCH-003).
- Consent gate before AI (SEC-004); `content_guard.scan` before AI submission (SEC-005); `audit.record` on clinician actions (COMP-002); BAA/Bedrock default (COMP-005).
- Parameterized DynamoDB keys via `Key()` (SEC-009); JWT `hid` match (SEC-008); single `alias/solace` CMK (COMP-003).
- Frontend: relative imports only (QUAL-005), API via `lib/api*.ts` (ARCH-007), no emoji on patient screens (QUAL-004), no axios in components.
- No live AWS mutation / prod deploy without Sriyan's approval. No git operations (lead commits each branch).

## 8. Key decisions (the 60-second version for the lead)

1. **`workspace_id` is a child of `hospital_id`, not a replacement.** `hospital_id` stays the HIPAA tenant/security boundary (SEC-008 unchanged); `workspace_id` is an intra-tenant feature/membership scope, advisory in the JWT, re-verified server-side.
2. **One net-new AWS resource:** DynamoDB `solace-workspaces` (PK `hospital_id`, SK `workspace_id`, CMK). Membership/patient tagging are additive attributes — no partition-key migration. Lazy `ws-default` backfill ⇒ zero-downtime, no mass 401.
3. **Atlas embeds as backend service + Workspace tab, NOT as a standalone Next.js app.** Port the tool-use loop into `backend/services/atlas/` + `routers/atlas.py`, reuse `lib/claude` (Bedrock), `content_guard`, `audit`, `fhir_writer`; surface one `OrdersTab.tsx`. Preserve Atlas's confirm-before-write safety exactly; add Solace's consent gate + content_guard + a PHI-leak CI test on top.
4. **Merge order: PROD → CORE → ATLAS → UIUX.** Only real conflict = two 1-line `include_router` appends in `main.py`; `App.tsx` untouched; new tabs register via append-only array.
5. **Workspace tab contract is frozen** (`PatientWorkspaceContext.tsx`): props-free tabs reading context. UIUX must not change it; ATLAS extends it.
