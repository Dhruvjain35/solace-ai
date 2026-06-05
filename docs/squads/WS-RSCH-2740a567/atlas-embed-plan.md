# Atlas EHR Copilot — Embed Plan

> Research squad WS-RSCH-2740a567. Source: `/Users/sriyanbodla/ehr-copilot` (src/, README.md, AGENTS.md, vision.json, package.json).
> Target seam: Solace Patient Workspace tabs. Constraints: SEC-004 (consent gate), SEC-005 (content_guard scan), COMP-001 (Safe Harbor redaction), COMP-005 (BAA AI providers).

## 1. What Atlas is

Atlas is a **browser sidecar that turns plain-English clinical intent into structured, coded FHIR orders, written back only after a one-click confirm** (`README.md:1-16`, `vision.json` product). The magic moment: *"order a CBC and a chest X-ray, and start metformin 500mg BID"* → 3 drafted coded FHIR orders → confirm once → write-back to the chart.

### Stack (`package.json`)
- **Next.js 16 (App Router)** + React 19 + Tailwind v4 (`@theme` tokens). NOTE `AGENTS.md`: this Next.js has breaking changes vs training data.
- **Claude via the Anthropic SDK** (`@anthropic-ai/sdk ^0.100.1`), server-side, **tool-use** loop.
- **FHIR R4** against public **HAPI** sandbox; mock FHIR fallback (`src/mock/fhirServer.ts`).
- No DB (in-memory audit `src/lib/audit/log.ts`), **mocked SMART-on-FHIR** login, `zod` validation, `lucide-react` icons.

### Features (`vision.json` keyCapabilities)
1. NL order entry → structured FHIR `ServiceRequest` / `MedicationRequest` with correct codes.
2. Live patient-context awareness (problems, meds, allergies read from FHIR).
3. Plain-English narration of every drafted action before it happens; one-click confirm/reject.
4. Write-back of confirmed orders to the FHIR EHR.
5. PHI-safe agent: model plans/narrates over **coded metadata only**, never raw PHI.

### AI agent design (the part that matters for the embed)
- **One agent turn = a bounded tool-use loop** (`src/lib/agent/runAgent.ts:25-154`), max 5 rounds, model default `claude-haiku-4-5-20251001` (env `ATLAS_AGENT_MODEL`).
- **Three tools** (`src/lib/agent/fhirTools.ts:4-56`): `search_fhir` (read), `read_fhir` (read), `propose_write` (queues an action — does NOT execute). Writes are **always proposed, never auto-executed**.
- **PHI isolation** is enforced two ways:
  - `toModelContext` builds the ONLY object allowed to reach the LLM: patientRef, banded age, sex, coded problems/meds/allergies — excludes name/MRN/DOB (`src/lib/phi/isolate.ts:10-19`), guarded by `src/lib/phi/isolate.test.ts` (CI gate).
  - `sanitize` / `sanitizeBundle` strip a deny-list of direct-identifier keys (`identifier,name,address,telecom,note,text,...`) and band `birthDate`→`ageBand` from every FHIR payload before it enters a tool result (`src/lib/agent/sanitize.ts:8-65`).
- **Pre-loaded chart snapshot**: Atlas fetches Condition/Observation/MedicationStatement/AllergyIntolerance/ServiceRequest in parallel, sanitizes, and inlines a ≤9KB snapshot so the agent answers in 1-2 rounds (`runAgent.ts:44-65`).
- **Execute is a separate, deterministic endpoint** (`src/app/api/agent/execute/route.ts`): zod-validates an allow-list of writable resource types, attaches the patient subject server-side, creates via FHIR client, writes an audit entry. This is the confirm step — clinician-initiated, not model-initiated.
- API routes: `/api/agent` (the turn), `/api/agent/execute` (confirm-write), `/api/patient`, `/api/patients`, `/api/draft`, `/api/orders`, `/api/vision`, `/api/audit`.

### Why it maps cleanly onto Solace
Solace already ships the same architecture in `backend/services/copilot/` — a **Plan→Execute→Narrate** loop where the model sees only coded vocabulary, a deterministic PHI zone holds real values, and a gate validates the plan before any PHI touch (`pipeline.py`, `gate.py`, `context.py`). Atlas's `propose_write` + confirm-execute is the *write* analogue of Solace Copilot's read-only `autopopulate`. **Atlas is the order-entry write capability Solace's copilot doesn't yet have.**

## 2. Embedding strategy — port the loop into Solace, do NOT bolt on the Next.js app

**Decision: re-implement Atlas's agent loop as a Solace backend service + a Workspace tab. Do not deploy the standalone Next.js app or proxy to it.** Reasons:
- Solace's auth, tenancy (`hospital_id`/`workspace_id`), audit (COMP-002), content_guard (SEC-005), and BAA AI provider routing (COMP-005, Bedrock) all live in the FastAPI backend. A separate Next.js service would have to re-create every L1 control and would not share the JWT, the CMK audit trail, or the consent gate.
- Solace already has the FHIR write-back machinery (`services/fhir_writer.py`, `services/ehr_epic.py`/`ehr_oracle.py`/`ehr_athena.py`, SMART-on-FHIR token flow in `routers/ehr_auth.py`) and a vendor registry (`lib/ehr_vendors.py`). Atlas's HAPI/mock client maps onto these.
- The frontend already has the **Workspace tab seam** (`frontend/src/components/workspace/PatientWorkspaceContext.tsx`) — an Atlas "Orders" tab drops in with zero new routing or auth.

### 2.1 Backend port (ATLAS squad owns)
New `backend/services/atlas/` mirroring `services/copilot/`:
- `tools.py` — the 3 tool definitions (`search_fhir`, `read_fhir`, `propose_write`) for `lib.claude` tool-use. Port from `fhirTools.ts`.
- `sanitize.py` — port `sanitize.ts` deny-list + `ageBand`. **In addition**, run every model-bound string through `content_guard.scan()` (SEC-005) — Solace's bar is higher than Atlas's deny-list alone and covers all 15 Safe Harbor identifiers (COMP-001).
- `loop.py` — the bounded tool-use loop (≤5 rounds) calling `lib.claude.messages_create(..., tools=...)` with `model=settings.model_clinical` (Bedrock/Haiku by default, COMP-005). Reuse the snapshot-preload optimization.
- `execute.py` — the confirm-write path, going through `services/fhir_writer.py` (NOT a fresh FHIR client) so write-back, vendor routing, and SMART tokens are reused.
- `context.py` — load the Solace patient + linked FHIR record via `services/copilot/context.build_chart` style, asserting `tenant.assert_patient_in_hospital` (SEC-008/COMP-011).

New `backend/routers/atlas.py`, mounted `/api/{hospital_id}/atlas`, all `Depends(require_clinician)` (and `require_workspace_member` once CORE lands):
- `POST /atlas/turn` — body `{patient_id, message, history?}` → consent check (SEC-004) → `content_guard.scan(message)` (SEC-005) → `atlas.loop.run` → `{reply, proposed_actions, tool_log}`. `audit(caller, "atlas.turn", patient_id=...)` (COMP-002).
- `POST /atlas/execute` — body `{patient_id, actions[]}` → re-validate writable resource types (zod→pydantic allow-list) → `services.fhir_writer` write-back → `audit(caller, "atlas.execute", patient_id=..., extra={order_summaries})`.

### 2.2 Frontend port (ATLAS + UIUX coordinate)
New `frontend/src/components/workspace/tabs/OrdersTab.tsx` (or `AtlasTab.tsx`):
- Reads `{ hospitalId, patientId, patient, ehrLinked }` from `usePatientWorkspace()` — NO props (`PatientWorkspaceContext.tsx:39-46`).
- Calls a new `frontend/src/lib/api-atlas.ts` (`postAtlasTurn`, `postAtlasExecute`) — via the shared axios instance with auto-Bearer (ARCH-007).
- UI: chat input → proposed-action cards (port `DraftOrderCard.tsx`, `ConfirmPanel.tsx` look/feel) → single Confirm. Gate the tab on `ehrLinked` for write-back, but allow draft-only when unlinked.
- No emoji (QUAL-004 if patient-facing; this is clinician-facing but keep clinical tone per Atlas anti-patterns), lucide-react icons, relative imports (QUAL-005), focus rings + aria-labels (USAB-002/005).
- Register the tab in the Workspace tab list (extend existing array — do NOT duplicate the workspace concept; SQUAD_BRIEF guardrail #4).

## 3. Shared infrastructure mapping

| Atlas concern | Atlas impl | Solace replacement (reuse, don't rebuild) |
|---|---|---|
| Auth | none / mocked SMART | Solace JWT, `Depends(require_clinician)` (SEC-008) + `require_workspace_member` |
| Tenancy | single demo patient | `hospital_id` path + `workspace_id` child (see tenancy-recommendation.md) |
| AI provider | direct Anthropic SDK | `lib/claude.py` → **Bedrock by default** (COMP-005); model from `settings.model_clinical` |
| PHI isolation | `phi/isolate.ts` + `sanitize.ts` + CI test | port + **layer `content_guard.scan` on top** (SEC-005, COMP-001); add a Solace leak-test mirroring `tests/services/test_copilot_phi_isolation.py` |
| FHIR read/write | HAPI/mock client | `services/fhir_writer.py`, `ehr_*` adapters, `fhir_patient_search.py`; vendors via `lib/ehr_vendors.py`; tokens via `routers/ehr_auth.py` |
| Audit | in-memory `audit/log.ts` | `lib/audit.record` dual-write DDB+S3 CMK 6yr (COMP-002) |
| Confirm-before-write | `propose_write` + `/api/agent/execute` | identical 2-step: turn proposes, execute writes — keep this exact safety model |

## 4. HIPAA constraints the embed MUST satisfy

1. **SEC-004 consent gate** — before ANY Atlas model call, verify consent for the patient/encounter (same pattern as `routers/intake.py:73-88`). Atlas had no consent concept; Solace adds it.
2. **SEC-005 content_guard** — every clinician message and any free-text that could reach the model goes through `content_guard.scan()`; reject if `safe=False`, use cleaned text. Atlas's deny-list is necessary but not sufficient.
3. **COMP-001 Safe Harbor** — the model context carries only coded vocab + banded age + sex (port `toModelContext`), and `content_guard._PII_REDACTIONS` covers all 15 identifiers as a backstop.
4. **COMP-005 BAA provider** — route through Bedrock (`CLAUDE_PROVIDER=bedrock`), never the direct Anthropic API in production. Atlas's direct-SDK call is replaced by `lib/claude`.
5. **COMP-002 audit** — every turn AND every execute writes an audit entry with `clinician_id`, `patient_id`, action, `workspace_id`.
6. **ARCH-001/002/003** — router→service→db layering; the FHIR write goes through `db`/service boundaries, boto3 stays in `db/`, the Claude adapter stays in `lib/claude.py`.
7. **Write-back safety** — keep Atlas's allow-list of writable resource types (`ServiceRequest, Condition, Observation, AllergyIntolerance, MedicationRequest`) and the no-guessed-dose rule; never auto-execute.
8. **CI gate** — add a Solace PHI-leak test (pytest) that asserts no name/MRN/DOB/free-text reaches the model payload, mirroring the Atlas `isolate.test.ts` gate and Solace's existing `test_copilot_phi_isolation.py`.

## 5. The embedding seam (one sentence for the other squads)

Atlas embeds as `backend/services/atlas/` + `routers/atlas.py` (`/api/{hospital_id}/atlas/{turn,execute}`) reusing `lib/claude` (Bedrock), `content_guard`, `lib/audit`, `tenant`, and `services/fhir_writer`; surfaced as one new Workspace tab (`components/workspace/tabs/OrdersTab.tsx`) reading `usePatientWorkspace()` and calling `lib/api-atlas.ts` — sharing Solace auth, `workspace_id`, and BAA AI providers, with the confirm-before-write safety model preserved exactly.
