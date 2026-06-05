# WS-UIUX-62893b28 — Frontend Constitution Audit

Scope: `frontend/src` (pages + components). Aesthetic preserved (teal + logo). No API
contracts or backend touched. Workspace tab contract (`PatientWorkspaceContext.tsx`,
props-free tabs reading context) left unchanged.

Method: targeted `grep` per rule + manual read of each patient-facing page/component.
Build/lint could not be executed from this sandboxed agent (see report.md → Verification).

## L1 (blocking) findings

### QUAL-004 — No emoji on patient screens
- **CLEAN.** No emoji anywhere in `frontend/src` (checked U+1F300–1FAFF, U+2600–27BF,
  U+2B00–2BFF). Flag emoji in `lib/i18n.ts` (`LANGUAGES[].flag`) are the only ones and
  are explicitly excluded by the rule + not rendered on Patient* screens.

### QUAL-005 — Frontend relative imports only (no `@/`)
- **CLEAN.** Zero `from "@/..."` imports in `src/**`. (Note: the `@` alias is still
  *defined* in `vite.config.ts:8`, but unused in source. Left as-is — config change is
  out of scope and would be a no-op for the rule, which is pattern-scoped to source.)

### USAB-001 — Actionable errors, never raw errors (patient screens) — VIOLATIONS FIXED
Raw backend `detail` / JS `e.message` were being surfaced to patients on the failure path:
- `pages/PatientIntake.tsx:258` — `setError(detail || e?.message || t("error_generic"))` → now `t("error_generic", preferredLanguage)`.
- `pages/PatientIntake.tsx:336` — `setError(e?.response?.data?.detail || e?.message || …)` → now `t("error_generic", preferredLanguage)`.
- `pages/PatientResult.tsx:455` (SMS self-serve) — `setError(e?.response?.data?.detail || "Couldn't send.")` → clean static message; also dropped `r.message` passthrough at :453.
- `pages/PatientPrintView.tsx:36` — `setError(e?.response?.data?.detail || …)` → clean static message. (Clinician-gated print view; lower risk but same intent.)
- `pages/PatientSchedule.tsx:39` — `setError(e?.message || …)` → clean static message.
- `pages/PatientSchedule.tsx:80` — `setError(detail || e?.message || …)` → clean static message (409 still mapped to friendly copy).

## L2 findings

### USAB-002 — Alt text + icon-button aria-labels
- `<img>` alt: **CLEAN** — every `<img>` in `src/**` has `alt` (LanguageGate, PatientIntake ×2, QRCard, PatientResult, ClinicianDashboard all `alt="Solace"`; PhotoCapture preview `alt="Injury preview"`).
- Icon buttons on patient screens: **CLEAN** — MicButton, PhotoCapture (retake/remove), AudioPlayer, PainEscalateButton, PatientSchedule header all have `aria-label` or visible text.

### USAB-004 — Form inputs have associated labels
- **FIXED:** `pages/PatientResult.tsx:436` SMS phone `<input>` had a section heading but no programmatic label → added `aria-label="Phone number to text your care instructions to"`.
- PatientSchedule `Field` inputs wrap a `<label>` (OK). PatientIntake medical form uses associated labels (OK).

### USAB-005 — Visible focus ring on interactive elements
- **FIXED:** `components/patient/AudioPlayer.tsx` play/pause button — added `focus-visible:ring`.
- **FIXED:** `components/patient/PhotoCapture.tsx` all 4 buttons (retake, remove, primary capture, upload) — added `focus-visible:ring`.

### USAB-003 — 44pt touch targets
- **CLEAN** on patient screens: PatientSchedule slots/day-strip/confirm `h-11`/`h-12`,
  PatientResult buttons `h-11`, AudioPlayer `w-12 h-12`, MicButton large. No sub-44pt
  interactive primary actions found on Patient* screens.

### USAB-007 — ESI badge contrast
- Not modified. `ESIBadge.tsx` + `tailwind.config.ts` ESI tones unchanged (rule requires
  axe/WAVE verification before changing; no change made, so no regression risk).

### USAB-008 — i18n for patient-facing strings
- `PatientIntake` + `LanguageGate` + patient subcomponents: fully localized via `t()`.
- **DEFERRED (pre-existing):** `PatientResult.tsx`, `PatientSchedule.tsx`,
  `PatientPrintView.tsx` use hardcoded English copy throughout (not just errors). These
  pages predate the i18n layer and are not wired to `t()`. Full translation is a larger
  effort beyond "polish" and was left to avoid scope creep / build risk. Error strings I
  touched were made clean + static rather than introducing a partial-localization mix.

### QUAL-002 — PascalCase + displayName
- All component files PascalCase. `forwardRef` components set `displayName`
  (`components/ui/Button.tsx`). Plain function components (AudioPlayer, PhotoCapture)
  don't require `displayName` per the rule's emphasis. No violation introduced.

### QUAL-007 — `any` only in catch blocks
- **DEFERRED.** Widespread `any` outside catch, concentrated in `lib/api.ts` (clinician
  AI/calculator endpoints with genuinely dynamic JSON bodies/results) and clinician pages
  (`.map((x: any) => …)` over untyped backend JSON). Fixing well requires typing dozens of
  backend response shapes — high risk of breaking the build and brushes against
  "don't change API contracts." Not touched. One incidental improvement: `PatientResult`
  SMS catch changed from `catch (e: any)` to bare `catch` (binding no longer needed).

### QUAL-008 — Tailwind class ordering
- Minor: corrected ordering on the PhotoCapture "upload from library" button
  (spacing before text, states last) while adding its focus ring. Not a systematic pass —
  most files already follow the convention.

### DEPS-006 / PERF-005 / PERF-007 — Heavy deps + bundle
- **PERF-005 CLEAN:** `hooks/usePollingPatients.ts` already ≥10s + `document.hidden` guard
  (not modified).
- **DEPS-006 / PERF-007 FIXED (partial):** `App.tsx` imported ALL 21 pages eagerly → the
  entire app (incl. **recharts** via `TrustReport` and the demo-only Studio/Showcase/Mockup
  pages) sat in the root bundle. Converted 11 non-critical routes to `React.lazy` + a
  `<Suspense>` fallback. recharts is consumed ONLY by `CoverageChart` ← `TrustReport`, so
  lazy-loading TrustReport pulls recharts into its own chunk, out of the main bundle.
- **DEFERRED:** `framer-motion` is still eagerly imported in ~18 components as inline JSX
  (`<motion.div>` / `<AnimatePresence>`). Because the critical-path pages (PatientIntake,
  PatientResult, ClinicianDashboard) legitimately use it, and it's consumed as JSX
  components (not lazy-friendly without per-component `React.lazy` wrappers), a full
  framer-motion lazy refactor was judged too invasive/risky for this pass. The route-level
  lazy split does move framer-motion usage in the 11 lazy pages into their own chunks,
  which partially addresses the spirit of DEPS-006.

## Not applicable / unchanged
- ARCH-006 (layer folders): respected — no files moved across pages/components/ui.
- ARCH-007 (API via lib/api.ts): no new axios instances; all edits use existing API fns.
- PERF-005 polling, USAB-006 loading states on existing async ops: pre-existing, left intact;
  added a Suspense busy-state for lazy chunks.
