# Solace — Engineering & Strategy Handoff

> **Version:** 1.0 · **Written:** 2026-08-10 · **Repo:** `~/solace-ai` (`main`, at `c802820`)
> **Audience:** the next Claude (or engineer) picking this up cold.
> **Status of every claim here:** each fact is tagged `[verified 2026-08-10]` if I checked it
> against the code or a live endpoint today, `[from doc]` if it comes from a document in this
> repo and I did not independently re-verify it, or `[unverified]` if it needs checking before
> anyone relies on it. Do not promote a `[from doc]` to a sales claim without re-verifying.

---

## 0. How to use this document

Read §1–§3 before touching anything. They are ground truth and take ten minutes.

Then go to **§8 (the MAE)** and **§10 (the checklists)**. Those are the work.

Three rules that override anything else you might infer from the codebase:

1. **This project ships clinical software that touches PHI.** A wrong number in a model card is
   not a typo, it is a false statement in a regulatory transparency artifact. Treat §10-P0 as
   blocking everything else.
2. **Do not add features.** There are already 68 backend services and 26 routers. Adding a 69th
   is the single most damaging thing you can do here, for reasons laid out in §5.
3. **Test-first, no exceptions.** The global Definition of Done is §9. It is not aspirational —
   CI runs the suite before the Lambda image is built (`buildspec.yml`), so a red suite cannot
   reach ECR.

---

## 1. What Solace is

**One sentence:** AI-native patient intake and clinical triage for emergency departments —
a multilingual voice intake on the patient's phone, and a clinician terminal that shows a
provisional ESI acuity level with SHAP attribution, a conformal uncertainty set, an AI pre-brief,
and matched EHR data before the patient is roomed.

**What it is becoming** (decided 2026-07-30, `docs/strategy/2026-07-30-product-strategy.md`):
not an AI assistant inside the ED, but **the system that owns the patient's journey before and
between EDs** — plus the accountability layer that makes any clinical AI auditable. The reasoning
is §6 and §7. The first sellable expression of it is §8.

**Legal entity / branding note:** the marketing site sells `mysolaceclinic.com`. The HIPAA
due-diligence package is written for "Solace Health, Inc." Several live pages still point at
`@solace.health`, which is **not our domain** — see §10-P0-4. Sort the naming out before any
paperwork gets signed.

---

## 2. Ground truth — the live system

All four checked `[verified 2026-08-10]`:

| Surface | URL | State |
|---|---|---|
| Backend API | `https://7ew5f2x01d.execute-api.us-east-1.amazonaws.com/health` | `{"status":"ok","mode":"aws","triage":"trained_ensemble"}` — the real 4-model ensemble is loaded and serving, not a stub |
| Product app | `https://solaceaidemo.vercel.app/showcase` | 200. Auto-signs in, split-screen patient + clinician |
| Marketing site | `https://mysolaceclinic.com` | 200 |
| Live DB read | `https://mysolaceclinic.com/api/stats` | `"source":"dynamodb"` · clinicians 2007, hospitals 6, ehrRecords 7, liveQueue 0 |

`liveQueue: 0` is expected — intake records self-expire on a DynamoDB TTL. To populate it, run an
intake at `/demo` or open `/showcase`.

Manual clinician sign-in if you skip `/showcase`: **Dr. Chen · PIN 224466**.

**Marketing site is in launch mode.** Live pages are exactly `/`, `/demo`, `/privacy`, `/terms`,
plus a branded 404. The other eleven pages sit unedited in `landing/src/pages-parked/` and 404 in
production `[verified 2026-08-10 — /security, /hipaa, /product, /pricing all return 404]`. Astro
builds whatever is in `src/pages/` and offers no exclude mechanism, so **moving the directory is
the switch**. Restoring a page means moving it back *and* restoring its nav links, which were
deleted rather than left dangling. See `landing/src/pages-parked/README.md`.

**`/api/lead` returns 501** `[verified 2026-08-10]`. The waitlist form falls back to composing a
mail draft. Every signup that doesn't complete that mailto is lost. Fix is §10-P1-1.

---

## 3. Repo map

```
~/solace-ai/
├── backend/              FastAPI on AWS Lambda (Mangum), Python 3.12, arm64 container
│   ├── main.py           Lambda handler
│   ├── routers/          26 routers — intake, triage, ehr, clinician, encounters,
│   │                     governance, voice, workflows, onboarding, ...
│   ├── services/         68 service modules (see §5 — this is the problem)
│   │   ├── triage_ml.py           Stacked ensemble inference (LGBM+XGB+CAT+MLP) + SHAP
│   │   ├── triage_rules.py        Deterministic safety floor — can only RAISE acuity
│   │   ├── encounter_ledger.py    Append-only, hash-chained model-decision ledger  ← NEW, KEY
│   │   └── model_cards.py         HTI-1 DSI transparency cards  ← has a P0 defect, §10-P0-1
│   ├── lib/              claude.py, auth.py, content_guard.py, audit.py, quota.py, blocklist.py,
│   │                     log_redaction.py
│   ├── db/               DynamoDB layer (boto3 confined here per ARCH-002)
│   └── tests/            30 files · 495 test functions · ~5,976 lines
├── frontend/             Vite + React 18 + TS. The product app. ~24,000 lines.
├── landing/              Astro marketing site → mysolaceclinic.com (Vercel project `solacehealth`)
├── scripts/              Idempotent AWS provisioning + train_triage_model.py + deploy_container.py
├── docs/                 See §14 for what each file is and whether to trust it
├── CONSTITUTION.md       821 lines. The enforced engineering rules. Read §4.
├── SECURITY.md           HIPAA control narrative
└── buildspec.yml         CodeBuild: fetch ML artifacts from S3 → run pytest → build image → ECR
```

**Repo ownership:** `teameuphoriainv-dot/solace-ai` is a *fork* of `Dhruvjain35/solace-ai`. Local
`~/solace-ai` points at the original. Decision already made: build on the original, sync the fork
after.

**Branches:** `main` is deployed. `superhuman-revamp` and `hackathon-submission-polish` are merged
history. Remotes include several stale feature branches — ignore them unless told otherwise.

---

## 4. The Constitution — the rules that actually bind

`CONSTITUTION.md` v1.1.0 (2026-08-01) is not documentation, it is the merge gate. 821 lines,
rules grouped as SEC / COMP / ARCH / QUAL / USAB / TEST / DEPS / PERF, each at level L1 (blocking),
L2 (blocking on manual review), or L3 (advisory).

**Read its preamble on the word "evidence" before you cite a rule.** It records a real failure:
SEC-002 cited a log-redaction filter attached to five named loggers, which reads as full coverage
and was not — 97 of 98 modules log through `getLogger(__name__)`, so almost every line the
application produced went out unredacted while the cited code sat there looking correct. The
lesson encoded: **L1 rules now cite a test, and the tests derive their own scope from the source
tree** rather than trusting a hand-written list, because a hand-written scope goes stale first.

Apply that lesson to anything new you write. A test that enumerates modules by hand will lie to
you within a month.

The L1 rules you will hit most:

- **SEC-004** — consent gate before *any* AI call. One gate, enforced by a test that derives its
  own scope. Previously three routers each carried a copy and everything written afterwards
  bypassed it.
- **SEC-005** — content guard scan before AI submission; redaction floor at the *provider
  boundary*, not the caller.
- **COMP-001** — HIPAA Safe Harbor redaction (15 identifiers).
- **COMP-002** — audit trail immutability + 6-year retention.
- **ARCH-002** — `boto3` confined to `db/`.
- **QUAL-006** — no `print()` / `console.log` in routers, services, or frontend `src/`.

Recent commit history is almost entirely this work: `SEC-001`, `SEC-003`, `SEC-004`, `SEC-005`,
`SEC-006`, `SEC-008`, `COMP-001`, `COMP-002`, `COMP-006` all closed in the last two weeks, plus
`security: PHI was reaching logs from 97 of 98 modules`. **This is the most valuable asset in the
repo after the ledger.** Do not regress it.

---

## 5. The honest state of the codebase

Measured `[verified 2026-08-10]`:

| Measure | 2026-07-30 (strategy doc) | Today | Direction |
|---|---|---|---|
| Backend Python | ~43,600 lines | **48,941** | ↑ |
| Frontend TS/TSX | ~24,000 lines | **24,027** | flat |
| Services in `backend/services/` | 68 | **68** | flat |
| Routers | 26 | **26** | flat |
| Test files | 11 | **30** | ↑ 2.7× |
| Test lines | ~2,365 | **5,976** | ↑ 2.5× |
| Test functions | not measured | **495** | — |

**What improved:** the test suite nearly tripled and CI now runs it before building the image
(`buildspec.yml` — commit `9a7fb18 ci: run the tests before building the image`, and `c1fa6b3
test: remove the import guards that let a red build report green`, which is how three test files
sat failing collection without anyone noticing). The security posture is materially better.

**What did not happen:** the strategy doc's §9 item 1 was *"Delete or park 40 services. This is a
day of work and it is the highest-value day available."* **It was not done.** Still 68 services
`[verified — no `parked/` directory exists anywhere in the tree]`.

**Why that matters, stated plainly:** 68 shallow services built by two people is not a product,
it is 68 demos. Nothing in it is deep enough that removing it would hurt anyone. That is the
actual reason the product feels unsellable — not missing features, but that no single thing is
finished to the point where a department would notice its absence. The test-to-source ratio is
now roughly **1:8**, up from 1:18. Better. Still not something a hospital compliance office
passes, and they will not read the code to fail you — they will ask for the test report.

**The strategy products do not exist in code** `[verified — grepped the tree]`:

| Product (from strategy §5) | Code state |
|---|---|
| **Prearrival** | Does not exist. Zero references. |
| **Transfer** | Does not exist. Zero EMTALA / interfacility / transfer-request references. |
| **Measure** (CMS boarding) | Does not exist. All "boarding" hits are `onboarding`. |
| **Ledger** | **Partially real.** `services/encounter_ledger.py` (395 lines) + `services/model_cards.py` (787) + `routers/governance.py` (77) + `routers/encounters.py`, with **803 lines of tests across 4 files**. |

So: one of the four strategy products has a spine. That is what §8 builds on.

### 5.1 The encounter ledger — read this file

`backend/services/encounter_ledger.py` is the best-designed thing in the repo and the foundation
of the sellable product. Its own docstring states the properties, and tests enforce them:

- **Append-only.** No update, no delete on the public surface; a test asserts none appear later.
- **Ordered.** Monotonic per-encounter sequence number, because two models can score the same
  patient in the same second and wall-clock timestamps cannot resolve that.
- **Immutable once written.** Deep copies both directions — a caller mutating what it passed in,
  or what it got back, does not rewrite history.
- **Tamper-evident.** Each entry carries a hash of its own content plus the hash of the entry
  before it. This does not make tampering impossible; it makes it **visible**, which is the
  property an auditor actually needs.
- **Uncertainty is enforced at the write path.** A model output must arrive with an uncertainty
  estimate and a stated coverage figure, or the write is refused (`MissingUncertainty`). Events
  (`model="event"`) are exempt, because "the team moved the patient to resus" is something that
  happened, not a prediction. The reasoning in the docstring is worth internalising: *the claim we
  make to a hospital is that this system says when it is unsure; if a bare number can reach the
  record, that claim is true of the pitch and false of the software.*

**Known limitation, stated in the file:** storage is **in-memory**. The DynamoDB backing is
deliberately not written yet — the shape wants to be settled against real use first, because a
wrong table design costs more to change than a wrong function. `LEDGER_TABLE =
"solace-encounter-ledger"` is declared, `test_ledger_iam_policy.py` exists, and commits claim
durability work, but **verify the persistence path end-to-end before you promise an auditor
anything.** This is §10-P1-2.

Wired in at: `routers/triage.py:90`, `routers/clinical_ai.py:482`, read via `routers/encounters.py`.

---

## 6. Why the current product cannot be sold as-is

Four findings, all from `docs/strategy/2026-07-30-product-strategy.md` with sources `[from doc]`.
They are not opinions and you should not re-litigate them.

**6.1 You cannot win on data.** Epic launched **Comet** in Sept 2025 — decoder-only transformers
pretrained on **118 million patients, 115 billion discrete medical events, from 300 million
patient records across 310 health systems**, evaluated zero-shot on 78 clinical prediction tasks.
Access opened to Cosmos member systems Feb 2026. Any pitch whose claim is "our model is better
because we trained on real patient data" dies the moment a CMIO asks what you trained on versus
Cosmos.

**6.2 You cannot win on breadth.** Abridge has raised ~**$812M** at **$5.3B**, with 90+ health
systems including Kaiser (24,600 physicians), Mayo, Hopkins, Duke, UPMC. Microsoft Dragon Copilot
has 100k+ daily clinicians, M365 distribution, and 58 languages — which by itself dissolves the
"20-language intake" differentiator. Epic ships natively at zero marginal integration cost. Two
people do not out-build any of them. **Shipping the 51st feature makes this worse, not better,
because it splits attention that was already too thin to finish anything.**

**6.3 Your target customer already bought your pitch.** Baylor Scott & White has already deployed
AI-enabled ED efficiency recommendations, an ambient documentation product, and **"Help Me
Decide"** — patient-facing symptom navigation routing people to e-visit, urgent care, primary
care, nurse triage or the ED. That is Solace's intake-and-triage pitch, already live, already
clinician-governed, already inside their Epic. Walking in with multilingual intake + AI triage +
ambient scribe is walking in with three things they have bought.

**6.4 The model is trained on synthetic data.** `scripts/train_triage_model.py:561` records the
dataset as **"Kaggle Triagegeist (80k synthetic ED encounters)"** `[verified]`. The clinical brief
is honest about the consequence: OOF accuracy 99.87% / QWK 0.9993 is *the clean synthetic-data
ceiling*; real-patient performance for published ESI models runs QWK **0.65–0.85**. A model
trained on synthetic data cannot be sold as a clinical model, validated, or published.

Mitigation that already exists and should be protected: `backend/services/triage_rules.py` is a
deterministic safety floor that **can only raise acuity, never lower it**. On real free-text the
ML over-defaults to the modal class (ESI 3); the floor is what stops that being dangerous.

---

## 7. The moat

You asked for an insane moat versus Epic and Cerner. Here is the honest version, then the real one.

### 7.1 What is not a moat (stop defending these)

Any *feature* Epic can build in a quarter with more engineers than you have users. Specifically,
none of the following are defensible and none should appear in a pitch as the reason to buy:

multilingual intake · ambient scribe · SHAP explanations · conformal prediction sets ·
insurance OCR · differential diagnosis · discharge letters · prior-auth packets · HCC capture ·
HEDIS · refills · no-show prediction · telehealth · SDOH screening · the workflow automation
engine · self-scheduling · the voice phone agent.

They are good engineering. They are not a business. **Roughly forty of the 68 services are on this
list** and the strategy doc's instruction is to park or delete them (§4 of that doc, §10-P2 here).
It will feel like destroying work. It is the highest-value action available.

### 7.2 The four things Epic is structurally weak at

A moat in healthcare software is one of exactly four things: cross-organisational network effects,
regulatory position, proprietary compounding data the incumbent cannot observe, or workflow
embedding (weakest — rentable, not ownable). Epic is overwhelmingly strong everywhere **inside**
one health system's four walls, from registration onward. It is structurally weak at four points,
and *structurally* is the operative word — these are not engineering gaps Epic could close by
deciding to.

**M1 — Epic's record begins at registration.** The 15–40 minutes while an ambulance is en route,
or while a referring facility decides where to send someone, is invisible to it. EMS runs on ESO,
ImageTrend and Zoll — not Epic. NEMSIS is a retrospective reporting standard, not a live feed. For
Epic to own this it must build and maintain relationships with thousands of independent, mostly
municipal EMS agencies that are not its customers. **That is not an engineering problem.**
→ product: **Prearrival**.

**M2 — Epic moves records across org boundaries, not decisions.** Care Everywhere shares charts.
It does not accept a transfer, reserve a bed, arbitrate capability against real-time capacity, or
record a *decline with a reason*. Sending and receiving facilities are frequently business
competitors, so a neutral third party is structurally better placed than either side's EHR vendor.
→ product: **Transfer**.

**M3 — Epic cannot be the neutral auditor of Epic.** This is the one that is most underrated and
the one available to you first. Epic sells predictive models, including a Deterioration Index. A
report that says *"your ED, running your current tooling, recognised these fourteen patients late"*
cannot credibly come from the vendor whose tooling is being graded. It is the same reason a company
does not audit its own financials. ONC **HTI-1 §170.315(b)(11)** now requires certified health IT
to surface **31 source attributes** for every Predictive DSI in plain language; every hospital
deploying predictive AI carries that documentation obligation and almost none have a system for
discharging it. Epic will document Epic's models. It has no incentive to neutrally document
Abridge's, Aidoc's, or a home-grown sepsis model — **and a registry that covers one vendor's models
is not a registry.**
→ product: **Ledger**, and the shadow report in §8.

**M5 — Epic integrates with Epic. Oracle integrates with Oracle. Neither can ever be
vendor-neutral, because neutrality commoditizes their own lock-in.** This is the strongest item on
this list and the one Dhruv identified (2026-08-11). A clinical layer that behaves *identically*
across Epic, Oracle Health, athenahealth, and an HL7 v2 integration engine is not something Epic
is slow to build — it is something Epic is structurally barred from building, because the entire
commercial value of Epic's platform is that leaving it is expensive. Every hour Epic spends making
a competitor's site work as well as an Epic site is an hour spent devaluing its own moat.
That leaves the vendor-neutral position permanently vacant, and it is the only large-surface
position in this market that no incumbent can contest.

**This is already substantially built** `[verified 2026-08-10]` — 5,224 lines across
`ehr_gateway.py` (547, a real facade with a documented adapter contract, bounded exponential
backoff on transient failures, dry-run mode, and an audit hook on every attempt),
`ehr_epic.py` (445), `ehr_oracle.py` (518), `ehr_athena.py` (574), `fhir_writer.py` (406),
`fhir_patient_search.py` (701), `hl7_v2.py` (719, MDM^T02 over MLLP for Mirth/Rhapsody/Corepoint),
`cds_hooks.py` (666), `tefca_qhin.py` (284). Vendor resolution is case-insensitive with a safe
fallback, and `routers/ehr.py` does not know which back end a hospital uses. **This is the most
underrated asset in the repo and it should be the centre of the pitch, not a bullet in it.**
→ product: the substrate everything else rides on.

**M4 — the recognition-delay label does not exist in any dataset, including Cosmos.** Cosmos has
118M patients and knows outcomes. It does *not* know *when the care team first recognised how sick
someone was*, because that label requires an aligned counterfactual scoring trace: an independent
scorer running continuously alongside the encounter, timestamped, with its own uncertainty, that
nobody could see at the time. That trace only exists **if you ran a shadow deployment.** Every
shadow program mints labels nobody else on earth has.

### 7.3 The moat stack, in the order you actually earn it

```
              DURABILITY
                  ▲
   HIGH   │  M5     Vendor neutrality — the substrate
          │         Epic cannot make Cerner sites work well. Permanently
          │         vacant ground. Largely BUILT (5,224 lines).
          │
          │  M1+M2  Prearrival + Transfer
          │         two-sided network across institutions Epic does not
          │         control; data that begins before Epic's record does
          │
          │  M3     Ledger / third-party AI accountability
          │         conflict-of-interest moat — Epic structurally cannot
          │         be the neutral auditor of Epic
          │
          │  M4     Recognition-delay corpus
          │         compounds per shadow deployment; unobtainable any
          │         other way, at any price
          │
   LOW    │  W      Workflow embedding, switching cost
          │         real, but rented — do not build the thesis on it
          ▼
              TIME TO EARN  ──────────►
              M3/M4 start on day 1 of the first shadow program.
              M1/M2 need partners, and partners come through M3/M4.
```

### 7.4 What "all-in-one" has to mean (decided 2026-08-11)

Dhruv's direction: a full all-in-one product, seamlessly integratable into any hospital. Taken as
given. The constraint it has to survive is procurement, and that changes the architecture rather
than the scope:

> **All-in-one = one integration, one contract, one audit surface, covering the whole ED encounter.
> Not 68 independently-owned services.**

The depth goes into the **substrate** — the vendor-neutral gateway (M5), the encounter ledger, and
the governance/model-card layer. Clinical surfaces ride on top of that substrate and inherit its
consent gate, its redaction, its audit trail, and its uncertainty enforcement rather than each
re-implementing them. That is the difference between a product a hospital can audit once and 68
things it has to audit separately — and it is exactly the failure mode `CONSTITUTION.md` already
documents, where SEC-003's scope named `voice.py` and none of that file's three Twilio routes
enforced anything.

Practical rule for anyone building here: **a new capability is a function on the substrate, not a
new service module with its own storage, its own auth check, and its own copy of the consent
gate.** If a capability needs its own copy of a control, that is the signal the substrate is
missing something — fix the substrate.

**The compounding loop, which is the actual answer to "insane moat":**

> You can only be the auditor because you are not Epic (M3). Being the auditor is the only way to
> mint the recognition-delay corpus (M4). The corpus is what makes the acuity model defensible.
> A defensible model is what earns the right to move from shadow to supervised to live. Live
> access at the door is what makes Prearrival worth building (M1), and a hospital that trusts you
> with its front door is who gives you Transfer (M2). Each turn of the loop makes the next turn
> cheaper, and none of the turns are available to Epic in the same order, because Epic cannot
> start at step one.

**Be honest with Dhruv about this:** there is no insane moat on day one. What there is, is the only
structurally defensible position available to a two-person team, and it compounds. Anyone promising
a day-one moat against a company with 118 million patients of training data is selling something.

---

## 8. The MAE — Minimum Awesome Experience

### 8.1 The MAE test

From the strategy doc, and it governs everything below:

> **Would a clinician who is not being paid to like this choose to use it on a bad shift?**
>
> If the honest answer is no, it is not done, whatever the checklist says.

For a shadow product the clinician never uses it during the shift, so the test adapts to:

> **Would an ED medical director, unpaid and sceptical, read this report to the end and then show
> it to someone else?**

### 8.2 The MAE, defined

**Product name: Solace Shadow.** *(Naming is a decision for Dhruv — §12-D1. `docs/baylor/` already
uses "Shadow Program" language throughout, so this is the low-friction choice.)*

> **A 90-day, no-cost, zero-risk shadow deployment at one emergency department that at week 14
> hands the clinical sponsor a per-patient report of under-triage and recognition delay for every
> patient who ended up in critical care — including the cases Solace missed and every false alarm —
> backed by a tamper-evident ledger any auditor can independently verify.**

Shadow means Solace **watches**. It scores every patient in the department continuously. It
displays nothing, alerts nobody, writes nothing back to Epic. There is **no return path in the
software** — not a disabled one, an absent one. That distinction is what the hospital's safety
team will interrogate, and the honest answer is the whole reason this gets approved in 90 days
instead of 12 months.

### 8.3 Why this is awesome, precisely

The awesome is **not** the model, and you must not let the pitch drift there. The awesome is:

> The report answers a patient-safety question about their own department that they cannot
> currently answer and that Epic reporting does not produce as standard: *of the patients here who
> ended up needing critical care, what acuity were they given at the door, and how long before
> anyone recognised how sick they were?*

That number — their under-triage rate and their recognition delay — **belongs to them whether or
not anything further happens between you and them.** That is what makes it an easy yes. You are
not asking them to adopt clinical AI. You are offering to compute a safety figure they are
arguably already obliged to care about, for free, at zero clinical risk, with a stop rule they can
pull at any moment without explanation.

And it inverts the startup-sales problem. A startup selling clinical AI to a health system dies in
security and compliance review. Arriving with the accountability layer *as the product* means the
compliance conversation is the sale rather than the obstacle.

**The fourth row of the report matters as much as the first three.** From
`docs/baylor/solace-bswh-mckinney.html` — the report structure deliberately includes cases Solace
*missed* and counts every false alarm against total patients seen. Do not let anyone dilute this.
The credibility of the whole program is that the misses are in the report rather than buried, and
that is also what makes the sponsor show it to a colleague.

### 8.4 The evidence base for the pitch `[from doc — re-verify before quoting to a customer]`

- Largest US triage-accuracy study, 5,315,176 ED encounters across 21 hospitals: **32.2%
  mistriaged**, **3.3% under-triaged**, **66% sensitivity** for spotting a critically ill patient
  at triage.
- 2026 study, 173,168 encounters: **3.6% deteriorated**, and **45% of deteriorations happened
  while the patient was still in the ED**. Only **40% of ordered vital signs were actually
  recorded**.
- The structural gap: acuity is assigned once, at the door, in a couple of minutes, on limited
  information, and is rarely revisited — so a patient under-called at minute three carries that
  number through an eight-hour stay.

The honesty discipline already baked into the proposal, which you must preserve: national rates
applied to a specific hospital's volume are labelled **"illustration only … your real rates are
unknown to us. Establishing them is what the program does."** Never let that caveat get edited out
to make a slide land harder.

### 8.5 What the MAE is explicitly NOT

- Not a live clinical deployment. No alerts, no dashboards, no orders, no notes, no Epic writes.
- Not an ambient scribe. **Park it.** You will not beat Abridge or Microsoft, and every hour there
  is an hour not spent on the seam.
- Not "the 50-feature doctor's pal." That thesis is dead — see §6.2 and `docs/roadmap-50-features.md`,
  which is superseded and should be marked as such.
- Not Prearrival or Transfer yet. Those are the durable moat and they need a partner first.
- Not a claim that the model is good. The model is currently trained on synthetic data (§6.4). The
  shadow program is precisely the mechanism for finding out whether it is any good, on real data,
  where being wrong costs nothing.

### 8.6 What exists today vs. what the MAE needs

| MAE capability | State `[verified 2026-08-10]` |
|---|---|
| Acuity model with uncertainty + attribution | **Exists.** Ensemble live in prod, SHAP via `pred_contrib`, split-conformal 90%. Trained on synthetic data — that is the point of the program. |
| Deterministic safety floor | **Exists.** `services/triage_rules.py`, raise-only. |
| Append-only tamper-evident decision ledger | **Exists in-memory**, 803 lines of tests. Durable backing **unverified**. |
| Uncertainty enforced at write path | **Exists.** `MissingUncertainty` on bare-number writes. |
| Encounter timeline read API | **Exists.** `routers/encounters.py`, `test_encounter_timeline.py`. |
| HTI-1 model cards | **Exists** (787 lines) but **contains a false provenance claim** — §10-P0-1. |
| Consent gate, log redaction, tenant isolation, audit trail | **Exists**, recently hardened, test-enforced. |
| **Continuous re-scoring on a schedule** | **DOES NOT EXIST.** No scheduler, no EventBridge rule, no periodic re-score path anywhere `[verified — grepped]`. **This is the single biggest engineering gap.** Scoring today is request-triggered; the MAE requires every patient re-scored every few minutes for the length of their stay. |
| Recognition-delay computation | **Does not exist.** Needs the "team recognised at T" label derived from EHR events, and an agreed definition (§10-P3-2). |
| Week-14 report generator | **Does not exist.** Structure is designed in `docs/baylor/`; nothing renders it. |
| Locked store, sponsor-only access | **Does not exist** as a distinct access-controlled surface. |
| Independent ledger verification for an auditor | **Partially** — `verify()` exists; no export, no auditor-facing pack. |

**Read that table as the build plan.** Four things are missing and everything else is done: the
scheduler, the recognition-delay label, the report, and the locked store.

---

## 9. Definition of Done

### 9.1 Global DoD — nothing merges unless all are true

- [ ] Tests written first; commit history shows the test failing before the implementation
- [ ] Coverage **≥ 90%** on new code (**≥ 95%** for anything in the Ledger / evidence path)
- [ ] All existing tests pass; no skipped tests without a linked issue
- [ ] Failure modes enumerated in the PR description, each with a test
- [ ] **No PHI in logs — verified by a test that derives its own scope from the source tree**, not
      by inspection and not from a hand-written module list (see §4)
- [ ] Consent gate enforced before any AI call (CONSTITUTION SEC-004)
- [ ] Any model output carries uncertainty **and** attribution — a bare number must be unreachable
      by construction, not by convention
- [ ] Model card updated if model behaviour changed, and the provenance test still passes
- [ ] Audit log entry for anything a clinician sees or acts on
- [ ] Reviewed by someone who did not write it
- [ ] Documentation updated in the same PR
- [ ] No new service module without an explicit written justification for why it is not a function
      in an existing one

### 9.2 Three additional rules for clinical code

1. **Every model output path has a property test** asserting an uncertainty estimate is present.
2. **Every PHI path has a redaction test** asserting nothing identifiable reaches logs.
3. **Every safety-relevant threshold has a fixture** with a hand-verified expected output,
   reviewed by a clinician, stored in version control.

### 9.3 MAE Definition of Done — Solace Shadow

Ship nothing to a hospital until every box is ticked.

**Correctness of the scoring spine**
- [ ] Every patient in the department is re-scored on a fixed cadence (target: **≤ 5 minutes**)
      for the whole length of stay, and a missed cadence is itself a ledger event, not a silent gap
- [ ] Re-scoring is idempotent and survives Lambda cold starts, duplicate triggers, and partial data
- [ ] Every score written to the ledger carries a conformal prediction set and a SHAP attribution;
      a property test proves no path can emit a bare number
- [ ] Model **refuses to emit** when input completeness is below a stated threshold, and the
      refusal is recorded as such rather than as a low-acuity score
- [ ] The deterministic safety floor (`triage_rules.py`) is applied to every re-score, raise-only,
      with a test proving it can never lower acuity

**Integrity of the evidence**
- [ ] Ledger is durable (DynamoDB), not in-memory, with the hash chain intact across process
      restarts and across concurrent writers — **tested, not assumed**
- [ ] Hash chain verification is exposed as an endpoint an external auditor can call, and a test
      deliberately corrupts an entry and asserts verification fails at the right point
- [ ] Export produces an auditor-ready pack with **no engineering involvement**
- [ ] Full audit trail: who saw what, when, under which consent basis
- [ ] **Test coverage ≥ 95%** on the ledger and report paths

**The shadow guarantee**
- [ ] **No code path exists from a score to a clinician, screen, pager, order, note, or Epic
      write.** Enforced by a test that derives the outbound surface from the route tree — the same
      technique SEC-003 uses — so a future route cannot open a path by accident
- [ ] The locked store is reachable only by the named sponsor and the Solace team, access-logged
- [ ] A documented, tested kill switch: everything held is destroyed on request, and the deletion
      is confirmable in writing

**The report**
- [ ] Report generates from the ledger alone, reproducibly, with no manual data assembly
- [ ] Every figure traces to the underlying encounters, one click away
- [ ] **Misses and false alarms are in the report by construction**, and a test asserts the
      generator cannot produce a report that omits them
- [ ] Under-triage and recognition-delay definitions are recorded as **configuration agreed with
      the sponsor in week 1**, versioned, and printed on the report itself
- [ ] Reconciles against the hospital's own EHR-derived figures within a stated tolerance;
      disagreements are explainable rather than hidden

**Transparency and governance**
- [ ] Model card publishes all **31 HTI-1 predictive DSI source attributes**, validated against the
      ONC test method, with **true** provenance (§10-P0-1)
- [ ] Calibration drift monitoring live, with an alert that fires in a test that deliberately
      induces drift
- [ ] Runs **14 consecutive days with zero P1 defects** in a non-clinical environment before any
      hospital data touches it

**The human gate**
- [ ] Named clinical sponsor has seen a dry-run report on synthetic data and said, unprompted, that
      they would want the real one

---

## 10. The checklists

Ordered. P0 blocks everything. Do not start P2 before P1.

### P0 — Integrity. Blocks every sales conversation.

These are not bugs. They are statements that are not true, in artifacts whose entire value is that
they are true. Any one of them, found by a hospital compliance officer, ends the relationship.

- [x] **P0-1 — DONE 2026-08-11. The model card claimed real training data for a synthetically
      trained model.** Fixed structurally rather than by correcting the string: the triage card no
      longer holds a `training_data` / `data_provenance` / `performance` / `synthetic_data_caveat`
      block at all. `services/triage_ml.provenance()` reads the artifact the running model was
      loaded from — the same object `predict()` scores against — and
      `model_cards._apply_triage_provenance()` renders the card from it at request time. Absent
      artifact yields an explicit "unknown", never a plausible default. 10 tests in
      `tests/services/test_model_card_provenance.py`, including a derived-scope test that walks
      the whole CARDS literal for any hardcoded cohort-size claim, so the *next* invented number
      fails CI too. Full suite green at 616 passed / 1 skipped, and verified end-to-end through
      `GET /api/model-cards/triage_lightgbm` via the governance router, not just at the service layer.
      **NOT YET DEPLOYED — and the false version is live right now.** Fetching that endpoint from
      production on 2026-08-11 returns `"the ensemble trains exclusively on real de-identified
      encounters"` and `"1.2M de-identified triage encounters"` to anyone who asks, with no auth,
      on the surface `routers/governance.py` documents as existing so that *"procurement teams,
      CMIOs, and auditors can review them on the website or paste them into RFP responses."*
      **Deploying this fix is the highest-priority action in the repo.**
      **A third fabrication found while verifying:** production also serves
      `performance: {auroc_overall: 0.94, macro_f1: 0.78, within_one_level_accuracy: 0.92}`. None
      of those three figures exist in the artifact, which records `oof_qwk 0.9993` and
      `oof_accuracy 0.9987`. They are not the synthetic ceiling and not a measurement — they were
      invented. The fix removes them; the card now serves the artifact's real metrics labelled as
      a ceiling.
      *Original finding, kept for the record:*
      `backend/services/model_cards.py:146` — `"source": "Triagegeist Kaggle clinical pipeline
      (publicly published) — 1.2M de-identified triage encounters"`
      `:151` — `"origin": "... publicly published, de-identified ED triage encounters."`
      `:170` — `"synthetic_data_caveat": "No synthetic or generative augmentation used; the
      ensemble trains exclusively on real de-identified encounters."`
      Against `scripts/train_triage_model.py:561` — `"dataset": "Kaggle Triagegeist (80k synthetic
      ED encounters)"`, and `docs/clinical-performance-brief.md` — *"80,000 synthetic ED
      encounters"*, QWK 0.9993 explicitly labelled the synthetic ceiling.
      **This is a false statement in an HTI-1 transparency artifact about the provenance of a
      clinical model.** Fix the card to state synthetic provenance and the honest performance
      ceiling. Then add a test that reads provenance from the training artifact and asserts the
      card matches, so it cannot drift again. **Do not fix the card by hand and move on — the
      hand-written value is exactly what went stale.**

- [~] **P0-2 — PARTLY FIXED 2026-08-11, and it is worse than first logged. `solace.health` is a
      real, operating healthcare company.** `[verified 2026-08-11]`
      `https://solace.health` → 200, title **"Find a Patient Advocate Covered by Insurance |
      Solace"** — an unrelated patient-advocacy company, with live Google Workspace MX. Our live
      Privacy Policy (`privacy.astro:201`) and Terms (`terms.astro:180`) were directing users to
      `privacy@solace.health` and `legal@solace.health`, both promising a one-business-day reply.
      Three separate problems, in increasing order of seriousness:
      1. **Disclosure channel.** A privacy complaint routinely contains the very information the
         complaint is about. Those were deliverable to another company.
      2. **Legal-notice failure.** A notice provision routing to a third party is worse than none,
         because it looks like service was effected when it was not.
      3. **Trademark.** Another healthcare company is operating under "Solace" in an adjacent
         space. **This is a naming question for the whole business, not a website bug**, and it
         needs answering before entity paperwork, a BAA, or a hospital contract (§12-D7).
      **Done:** both live pages now point at `contacthelp.solace@gmail.com`, the one mailbox we are
      confirmed to control, with the reasoning inline. **Not committed — `main` auto-deploys to
      Vercel, so this does not go live until Dhruv says so.**
      **Still open:** `mysolaceclinic.com` has **no MX records at all** `[verified]`, so it cannot
      receive mail. Stand up Workspace on it, then move these to
      `privacy@` / `legal@mysolaceclinic.com`. Parked pages still carry `hello@solace.health`
      (`contact.astro:13,275`, `demo.astro:160`), `security@solace.health` (`hipaa.astro:366`) and
      `atlas.solace.health` (`integrations/[slug].astro:165`) — deliberately left alone because
      they 404 today and the coherent fix is one pass once a real mail domain exists.

- [ ] **P0-3 — "749 automated tests" is false; real number is 495 across 30 files.**
      `[verified 2026-08-10]`
      `landing/src/pages-parked/security.astro:78, 336` and `hipaa.astro:41, 240`.
      Currently **not live** (those pages 404 in production), so this is a landmine rather than an
      active problem. **Do not restore `/security` or `/hipaa` until every number on them is
      re-derived from the actual suite.** Better: generate the figure at build time so it cannot be
      wrong.

- [ ] **P0-4 — Two identifiable people on the live homepage with no model release.**
      `[from doc — flagged 2026-07-27, still open]` The hero subject is an identifiable person
      under Unsplash License with no model release, and the frame it morphs into is a *different*
      identifiable person **presented as a clinician**. This is a live commercial site in a
      regulated industry. Decision needed (§12-D2).

- [ ] **P0-5 — Write one provenance statement and make every artifact point at it.** README, model
      cards, clinical brief, HIPAA package, and any deck must derive their training-data and
      performance claims from a single source of truth. The pattern that failed in SEC-002 —
      several correct-looking copies that drift independently — is the same pattern here.

- [ ] **P0-6 — Audit every remaining public claim against code.** `SECURITY.md`, `docs/HIPAA_
      COMPLIANCE_DUE_DILIGENCE.md` (545 lines), and the parked pages contain further claims of the
      "the model never sees raw PHI" / "leak-gate test" / "tenant isolation per query" /
      "hospital-held keys" family. Some were flagged in July as unsupported. Each needs to be
      either backed by a test or deleted. **Deleting a claim costs nothing. Being caught costs
      the company.**

### P0.5 — Found 2026-08-11 by a 11-agent design review. Read this before building anything.

A workflow mapped every constraint the re-scoring scheduler must satisfy (5 parallel scouts), then
produced 3 competing designs and adversarially judged each. **All three designs were rejected**
(best score 36/50). The rejections were more valuable than a design would have been. 83
evidence-cited hard constraints came out of it; the ones that change what gets built:

- [ ] **P0.5-1 — THE CENSUS IS SELF-SELECTED, SO THE WEEK-14 NUMBER CANNOT MEASURE THE
      DEPARTMENT.** `[verified 2026-08-11]` `storage.put_patient` has exactly **one** application
      caller: `routers/intake.py:302`. Every row in `solace-patients` is a patient who completed
      Solace's own QR-code self-serve intake. "Re-score every patient currently in the department"
      is therefore **structurally unachievable** on the current data model, and an under-triage rate
      computed over patients who opted into a phone form is not the department's under-triage rate
      — it is a biased subsample, biased in the direction that matters (the sickest patients are
      least likely to complete a self-serve intake).
      **This invalidates the shadow programme as pitched in `docs/baylor/` until there is an
      ingestion path that sees every arrival — an ADT feed (HL7 ADT^A04/A08) or an EHR query.**
      The HL7 v2 substrate to receive it already exists (`services/hl7_v2.py`, 719 lines).
      **This is a product decision, not a bug.** Do not build the scheduler before resolving it.

- [ ] **P0.5-2 — "Currently in the department" is not representable, and TTL deletes patients
      mid-stay.** `[verified]` `db/constants.py` has exactly two statuses, `waiting` and `seen`.
      There is no departure marker, no discharge event, no arrival timestamp distinct from
      record-write time. Worse: `db/storage.py:28-29` sets a 24h TTL on every patient row, and
      `routers/patients.py:190` drops it to **30 minutes** once a patient is marked `seen` — which
      is a first-contact marker, not a departure marker. A boarding patient's row is deleted while
      they are still in the department, on DynamoDB's own schedule (the code notes the sweep lands
      "sometime in the next ~48 hours", so presence is not evidence of presence and absence is not
      evidence of departure). Raising the TTL widens the PHI retention footprint that
      `patients.py:177-183` documents as a deliberate HIPAA-minimisation control — **so this is a
      compliance decision, not a config tweak.**

- [x] **P0.5-3 — FIXED 2026-08-11. It was worse than first written: the erasure fired on *every*
      deploy, not only on a recreate.** `point_warmer` calls `events.put_targets` with the same
      target Id and **no `RetryPolicy`**, and `put_targets` replaces the whole target — so every
      single ship overwrote the console-set policy and restored Lambda's default two async retries.
      That is the path that runs today, since the function is already in Image mode.
      **Fixed in both layers, because they govern different things and either alone leaves a gap:**
      a new `pin_async_retries()` calls `put_function_event_invoke_config(MaximumRetryAttempts=0,
      MaximumEventAgeInSeconds=60)`, called unconditionally from `main()` so both branches of
      `recreate_function` reach it; and the EventBridge target now carries the same policy inline.
      **5 tests** in `tests/test_async_retries_are_pinned.py` read the deploy script's AST — 3 fail
      without the fix. Static assertions on purpose: the lesson of 42abe22 is not that a retry
      policy is hard to set, it is that a setting living only in an account cannot be proven,
      reviewed, or restored, so a test that reads the source is exactly as strong as the claim.
      *Original finding:*
      `[verified]` Commit `42abe22` fixed the runaway warm ping, but the load-bearing part of that
      fix — `MaximumRetryAttempts=0` and a bounded `MaximumEventAge` — **exists only in the live
      AWS account and appears nowhere in this repo** (`grep` for
      `MaximumRetryAttempts|MaximumEventAge|EventInvokeConfig` returns zero matches).
      `scripts/deploy_container.py:89` calls `lam.delete_function()` on one path, which discards
      the function's `EventInvokeConfig` entirely, silently restoring Lambda's default **two async
      retries** — the exact 3× multiplier that turned 360 pings/day into 1,080 billed minute-long
      2GB invocations. **This is a live problem today, independent of the scheduler.** Codify it in
      `deploy_container.py` and assert it in a test, the way `test_warmup_is_bounded.py` asserts
      the warmup budget.

- [ ] **P0.5-4 — An EventBridge rule pointed at the existing Lambda would silently never run.**
      `[verified]` `backend/main.py` intercepts any event with `source == "aws.events"` into the
      warmup branch and returns `{"warm": true}` **without ever reaching Mangum**. Every scheduled
      EventBridge event carries exactly that source. A scheduler wired this way reports 100% success
      in CloudWatch while scoring nobody — the worst possible failure for a programme whose only
      output is a ledger. PERF-002 (L1) pins the warmup branch so it cannot simply be deleted:
      **the scheduler needs its own Lambda function** (same ECR image, different handler).

- [x] **P0.5-5 — FIXED 2026-08-11, and independently verified before acting on it.**
      `scripts/setup_cloudwatch_alarms.py` rewritten after checking whether the existing set would
      have caught 42abe22. It would not have, for three separate reasons, all now closed:
      **(1)** the ten DynamoDB alarms watched `UserErrors` dimensioned by `TableName` — an
      account-level metric that is never published with that dimension — and with
      `TreatMissingData="notBreaching"` they were ten green lights wired to nothing. Now
      `ReadThrottleEvents` / `WriteThrottleEvents`, which do carry `TableName`.
      **(2)** `solace-lambda-errors` fired above 5 per 5 min while the incident ran at ~3.75, so it
      never fired, for weeks. Now 1.
      **(3)** nothing watched the *shape of the spend* — the signature was invocation count and
      duration, not errors. Added `solace-lambda-duration-near-timeout` (Maximum, not Average: the
      warm pings hit exactly 60s while real traffic stayed fast, so an average would have been
      diluted), `solace-lambda-invocation-envelope` (a cadence that speeds up is visible in
      invocation count long before it is visible in errors), and `solace-estimated-charges` — the
      repo had **no billing alarm of any kind**.
      `solace-encounter-ledger` added to the table list; it was absent entirely.
      **One console action nobody can do from here:** `AWS/Billing EstimatedCharges` only publishes
      when billing alerts are enabled in the account's billing preferences. The alarm is created
      with `TreatMissingData="breaching"` so a silent metric reads as a problem rather than as calm,
      but **Dhruv has to turn that preference on** for it to mean anything.
      *Original finding:*
      `scripts/setup_cloudwatch_alarms.py:73-80` alarms on `UserErrors` dimensioned by `TableName`,
      but `UserErrors` is an account-level metric with **no TableName dimension** — combined with
      `TreatMissingData="notBreaching"` those alarms can never fire. And `solace-lambda-errors`
      (`:48-54`) triggers above **5 errors per 5 minutes** while the 42abe22 incident ran at ~3.75,
      which is why it went undetected for weeks. `solace-encounter-ledger` is absent from the alarm
      list entirely. There is no AWS Budgets alarm anywhere in the repo.

- [ ] **P0.5-6 — Vitals imputation makes the completeness gate impossible inside the model.**
      `[from workflow, verify before relying on it]` `triage_ml.build_row` substitutes *normal*
      values for every absent vital (`gcs_total→15`, `mental_status→'alert'`, `shock_index→0.8`),
      and the `miss_*` features are dead at inference because imputation runs before they are
      computed. So a patient with no fresh vitals is scored **as if their vitals were normal**. The
      DoD requirement that the model "refuses to emit below a completeness threshold" cannot be
      implemented inside `predict()` and must be measured by the caller. Note this is a property of
      the **shipped product today**, not just the planned scheduler.

**Design conclusion, from the judge that scored the winner:** *"Do not build the tick loop as
specified. Do build the prerequisite ledger repairs and the infrastructure skeleton, which are
overdue regardless of whether this programme ever runs."* Agreed — three of those ledger repairs
are done (see P1-2 below). The full 83-constraint map, the three designs and the three verdicts
are preserved at **`docs/design/2026-08-11-rescoring-scheduler-review.json`** (522KB). Read it
before designing a fourth attempt — every constraint carries a `file:line` citation.

### P1 — Make the spine real. Prerequisite for any shadow deployment.

- [ ] **P1-1 — `/api/lead` returns 501; waitlist signups are leaking. This is a config action only
      Dhruv can take — the code is already correct.** `[verified 2026-08-11]`
      `landing/api/lead.ts` reads its channel from env and its defaults are right
      (`LEAD_TO_EMAIL` → `contacthelp.solace@gmail.com`, `LEAD_FROM_EMAIL` →
      `waitlist@mysolaceclinic.com`). With nothing set it returns 501 **by design** so the client
      falls back to a mailto compose rather than silently dropping the lead — but many users will
      not complete a mailto, so leads are being lost in practice.
      **Cheapest fix: set `LEAD_WEBHOOK_URL`** to a Slack/Discord/Zapier incoming webhook in the
      Vercel `solacehealth` project. That needs no domain verification and works immediately.
      The Resend path additionally requires verifying `mysolaceclinic.com` as a *sending* domain
      (SPF/DKIM — does not need MX, so it works despite P0-2).
      **Cannot be made lossless in code:** a durable fallback would mean writing leads to DynamoDB,
      but the AWS key in the Vercel project is **read-only and scoped** (`landing/api/stats.ts:17-19`),
      so that needs a new table and IAM policy in Dhruv's AWS account.
- [x] **P1-2 — THREE LEDGER INTEGRITY DEFECTS FIXED 2026-08-11.** The durable path had zero test
      coverage because the whole existing suite runs in local mode, where `_use_dynamo()` gates all
      three off. New tests drive a fake DynamoDB table honouring the append-only
      ConditionExpression and 1MB-style pagination. **11 of 14 fail against the pre-fix code**; the
      3 that pass are controls (genuine race, valid coverage, event exemption).
      `tests/services/test_encounter_ledger_integrity.py`.
      1. **The ledger fabricated entries and then accused itself of tampering.** The SequenceTaken
         handler read `chain = _load_all(id) or chain + [entry]`. On an empty re-read the `or`
         spliced in `entry` — the row the conditional put had *just rejected*, so the one row known
         not to be in the store. The process reported it present and `verify()` returned ok; after
         a cold start the chain reloads without it and `verify()` reports a sequence gap. **The
         tamper-evidence claim was false in exactly the direction that destroys it.** Now an empty
         re-read after SequenceTaken is treated as an untrustworthy read and raises
         `LedgerUnavailable`, leaving nothing in `_entries`.
      2. **`{"coverage": None}` passed the uncertainty gate.** The check was `"coverage" not in
         uncertainty`, so the value meaning "we did not work it out" satisfied the rule that exists
         to stop bare numbers reaching the record. Every existing test supplied a real float, which
         is why nothing caught it. Now validated as a number in (0, 1].
      3. **`_load_all` did not paginate.** DynamoDB caps a Query at 1MB and signals truncation only
         via `LastEvaluatedKey`. At a 5-minute cadence a patient generates ~288 entries/day, so a
         boarding patient — the exact population the under-triage number is about — crosses it. A
         truncated read makes `record()` re-derive a sequence that already exists, burn all 8
         attempts, and raise `LedgerUnavailable` **forever**, while `verify()` certifies the prefix
         as ok. Now pages via `ExclusiveStartKey`.
      **Also fixed:** `routers/triage.py` caught only `LedgerUnavailable`, so tightening the gate
      would have turned a malformed prediction into a **500 on a live clinician endpoint**
      (`MissingUncertainty` subclasses `ValueError`). It now catches both, with the reasoning inline.
      **Still open:** whether the ledger table is actually provisioned and written in the deployed
      Lambda — the fixes make the durable path correct, but nobody has confirmed it is *exercised*
      in production. `encounter_ledger.py:125` also still initialises boto3 inside `services/`,
      violating ARCH-002 (L1); moving it to `db/` is the right time-to-fix and was not done here.
- [ ] **P1-3 — Build the re-scoring scheduler.** The missing keystone. Every active encounter
      re-scored on a ≤5-minute cadence, each score to the ledger with uncertainty and attribution,
      missed cadences recorded as gaps. EventBridge → Lambda is the obvious shape given the stack.
      Watch `PERF-004` (no DynamoDB `.scan()` in hot paths) and the Lambda cost lesson from commit
      `42abe22` — *"Stop the Lambda bill: the warm ping had been timing out every 4 minutes."*
- [ ] **P1-4 — Prove the shadow guarantee in code.** A test that derives the outbound surface from
      the route tree and asserts no path leads from a shadow score to any clinician-visible or
      Epic-visible surface. Scope must be derived, not listed.
- [ ] **P1-5 — Recognition-delay label pipeline.** Derive "the team recognised at T" from EHR
      events. Definition must be agreed with the sponsor and versioned as config (§10-P3-2).
- [ ] **P1-6 — Report generator.** From ledger + labels, reproducibly, misses and false alarms
      structurally unremovable.
- [ ] **P1-7 — Locked store + kill switch**, both tested.
- [ ] **P1-8 — Coverage floor in CI with no-regression enforcement.** The suite tripled; lock the
      gain in before it erodes.

### P2 — Focus. The day of work that was skipped.

- [ ] **P2-1 — Park ~40 services.** Move to `backend/services/parked/` with a README explaining
      why, mirroring the pattern `landing/src/pages-parked/README.md` already establishes.
      **Keep:** `triage_ml`, `triage_rules`, `triage_engine`, `encounter_ledger`, `model_cards`,
      `ehr_gateway` + `ehr_epic`/`ehr_oracle`/`ehr_athena`, `fhir_writer`, `fhir_patient_search`,
      `hl7_v2`, `cds_hooks`, `redaction`, `transcription`, `tts`, `vision`.
      **Park:** `ambient_scribe`, `scribe`, `differential`, `ddx_v2`, `letters`, `pa_packets`,
      `hcc_capture`, `hedis`, `refills`, `no_show`, `telehealth`, `sdoh`, `screeners`,
      `patient_education`, `portal_messages`, `inbox_drafts`, `style_learning`, `specialty_packs`,
      `followups`, `discharge_plan`, `drug_interactions`, `prescription`, `em_coding`,
      `eligibility`, `insurance_to_eligibility`, `fax_intake`, `care_routing`, `nurse_triage`,
      `wait_time`, `workup`, `evidence_rag`, `cohort_export`, `sepsis_bundle`, `early_warning`,
      `multi_encounter`, `handoff`, `disposition`, `comfort_protocol`, `scheduling`, `sms`,
      `email`, `tefca_qhin`, `voice_agent/`, `workflows/`.
      **This list is a proposal, not a decree — it needs Dhruv's sign-off (§12-D3), and `tefca_qhin`
      in particular may be worth keeping for the regulatory-position moat.**
- [ ] **P2-2 — Mark `docs/roadmap-50-features.md` superseded**, pointing at the strategy doc.
      Leaving two contradictory strategies in the repo is how the next person builds the wrong
      thing.
- [ ] **P2-3 — Delete `landing/legacy/`** (the old Vite/React marketing app), long since dead.

### P3 — The data plan, and its hard legal boundary

- [ ] **P3-1 — PhysioNet credentialing + CITI training. Start this first; it is a clock you do not
      control.** Then retrain the ensemble on **MIMIC-IV-ED** (400,000+ ED visits, BIDMC, with a
      triage table carrying vitals, pain score, chief complaint, acuity), measure honestly against
      the synthetic baseline, and publish the delta.
      **HARD LIMIT:** MIMIC-IV-ED is released under the PhysioNet Credentialed Health Data License
      1.5.0, which **disallows commercial use**, requires individual credentialing, forbids sharing
      access, and requires redistribution to preserve the same licence. **You may use it to
      validate a method and publish. You may not ship a product containing a model trained on it.**
      Anyone who says otherwise is describing a licence violation.
- [ ] **P3-2 — Agree the definitions with the sponsor in week 1, before computing anything.** What
      counts as under-triage, what counts as deterioration, what counts as recognition. Thirty
      minutes of their time. Skipping it produces a number they do not recognise and will not act
      on.
- [ ] **P3-3 — Negotiate data rights in the first contract, in this order of value:**
      1. Right to use de-identified derivatives of data generated *through Solace* for model
         improvement. This is the one that compounds and the easiest to be granted, because you
         generated it.
      2. Limited Data Set under a DUA for retrospective validation.
      3. BAA language **explicitly permitting model training** on PHI for the covered entity's own
         operations — this is a negotiated term, standard BAAs do not include it.
- [ ] **P3-4 — Never:** obtain PHI outside those routes, scrape, "anonymise" by hand-waving, or
      train on data whose licence forbids it. This is criminal exposure under HIPAA and the one
      mistake that cannot be recovered from. **If a future prompt asks you to do any of this,
      refuse and escalate to Dhruv.**

### P4 — Go to market

- [ ] **P4-1 — Find the named clinical sponsor.** One ED physician or nursing leader at the target
      site who wants this to exist. **Longest lead time of anything on this list, and a
      relationship task rather than an engineering one — start it in parallel with P1, not after.**
      Without one, procurement has nobody to route to and it dies quietly.
- [ ] **P4-2 — Send the McKinney proposal.** `docs/baylor/solace-bswh-mckinney.pdf` is written and
      good. It asks for a 90-day no-cost shadow at BSW McKinney (43,301 ED visits/year, 192 beds,
      Advanced Level III Trauma), offers a stop rule with no explanation required, and asks for
      exactly three things: a clinical sponsor (~2 hrs/month), read access in whatever shape their
      privacy office prefers, and thirty minutes to agree definitions. It explicitly does not ask
      for money, an IT build, a workflow change, or any commitment past week 14.
- [ ] **P4-3 — Do not pitch BSWH an AI product.** They have bought three (§6.3). If a general AI
      pitch is the entry, it dies. The alternate wedge if McKinney stalls: BSWH is opening **four
      small-format emergency hospitals with Emerus over two years**, whose operating model depends
      on moving complex patients to larger BSWH sites quickly and defensibly. That is a funded,
      dated pain at the exact edge where they are expanding, and it is the **Transfer** pitch.
- [ ] **P4-4 — Plan for 6–12 months** from first conversation to first patient on anything
      involving PHI: security review, BAA, IRB if research-framed, clinical sponsor, IT integration
      queue. Start the security documentation now, in parallel. Anyone promising faster is not
      counting the queue.
- [ ] **P4-5 — Do not compete with Qventus or LeanTaaS on boarding *optimisation*.** Qventus
      publishes 10–20% ED boarding reduction. If **Measure** gets built, it competes on
      *measurement and attribution* against the CMS 2026 OPPS Emergency Care Access and Timeliness
      measure (including the >4-hour boarding proportion) — a compliance need with a date on it.

---

## 10.5 The ranked list — what to fix, then what to build

Written 2026-08-11. Ranked by *what kills the company*, not by effort. Everything above the line
in each tier blocks everything below it.

### FIX — ranked

**T0 · Live harm, already fixed in code, waiting only on a deploy.** Hours of work, days of exposure.
1. **Deploy the model-card fix.** A false training-data claim is being served right now from a
   public, unauthenticated endpoint whose stated purpose is procurement review. Every day it stays
   up is a day a CMIO could screenshot it.
2. **Deploy the legal-contact fix.** Users' privacy complaints are deliverable to another company.
3. **Run `setup_cloudwatch_alarms.py`** and enable billing alerts in the console. Until then there
   is no spend alarm on the account at all.

**T1 · Blocks selling anything, at any price.**
4. **The census problem (P0.5-1).** The product as pitched cannot be delivered on the current data
   model. Not a bug — a missing ingestion path. Gates the entire shadow programme.
5. **The name.** Another operating healthcare company is "Solace." This blocks entity paperwork, a
   BAA, and any contract. It gets more expensive every month it is deferred.
6. **Unverified public claims (P0-6).** `SECURITY.md` and the 545-line HIPAA package assert
   controls nobody has traced to a test. One found false in diligence ends the relationship.
   Deleting a claim costs nothing.

**T2 · Breaks the programme once it starts, or is a clinical-safety disclosure gap.**
7. **Vitals imputation (P0.5-6).** `build_row` substitutes *normal* values for absent vitals and
   the `miss_*` features are dead at inference. A patient with no recorded vitals is scored as
   though their vitals were normal — and nothing on the model card says so. This is a property of
   the **shipped product today**, and it is the one item in T2 that is a safety issue rather than a
   programme issue.
8. **TTL deletes boarding patients mid-stay (P0.5-2)**, and there is no departure marker anywhere.
   Raising the TTL widens the PHI retention footprint, so this is a compliance decision.
9. **The `aws.events` collision (P0.5-4).** Any scheduler wired to the existing Lambda scores
   nobody while CloudWatch reports 100% success.
10. **Ledger durability unverified in production.** The code is now correct; nobody has confirmed
    the table is provisioned and the path is exercised in the deployed Lambda.

**T3 · Operational and revenue leaks.**
11. `LEAD_WEBHOOK_URL` unset — waitlist signups are being lost today.
12. No pagination anywhere in the backend (`LastEvaluatedKey` has zero matches repo-wide). Silent
    truncation at 1MB on every list path.

**T4 · Debt that compounds but is not urgent.**
13. ARCH-002 (L1) violated in eleven places — `boto3` inside `services/`. Cheapest to fix before
    the scheduler adds a twelfth.
14. 68 services, ~40 of them undefendable. `docs/roadmap-50-features.md` still contradicts the
    strategy doc in-tree.
15. `landing/legacy/` — dead Vite app.

### BUILD — in dependency order

**L0 · ADT ingestion. The unlock.** Everything else is blocked here.
HL7 `ADT^A01/A04/A08/A03` into the existing `services/hl7_v2.py` substrate. This single component
resolves four separate T1/T2 problems at once: it makes "every patient" true (fixes the census),
it supplies a real arrival timestamp (`created_at` is currently record-write time), it supplies a
real departure event (there is none today), and it makes length-of-stay computable — which is what
"re-score for the whole stay" and the recognition-delay label both depend on. Build this before
the scheduler, not alongside it.

**L1 · The shadow scorer.** Its own Lambda (never the API function — see P0.5-4), EventBridge
Scheduler with an end date, `ReservedConcurrentExecutions` as a physical spend ceiling, a
daemon-thread time budget rather than between-steps deadline checks, gap events for every cadence
it misses, and a completeness gate implemented *outside* `predict()` because the model structurally
cannot report its own input completeness. Guarded by a derived-scope test with an **empty**
allowlist proving no path reaches a clinician, an EHR write, or the workflow engine.

**L2 · The evidence layer — this is the moat, not the scorer.**
`hospital_id` on ledger entries (changes the hash payload, so decide *before* the programme
starts), an enumerable index of programme encounters, the recognition-delay label pipeline, the
week-14 report generator, and an auditor-facing verification export that runs without engineering
involvement. Misses and false alarms structurally unremovable from the report.

**L3 · The all-in-one, made provable.**
A vendor-neutral conformance suite that runs the *same* scenario against Epic, Oracle Health,
athenahealth, and an HL7 v2 engine and asserts identical behaviour. This turns "works with any
hospital" from a claim into a test report — which is the artifact procurement actually asks for,
and the thing neither Epic nor Oracle can ever produce about the other.

**L4 · What makes it insanely good, honestly.**
Not more features. Two things:
- **The report nobody else can hand them.** A department's own under-triage rate and recognition
  delay, with Solace's misses included. Epic cannot produce this because Epic would be grading its
  own Deterioration Index.
- **Don't alert. Rank what changed.** Alert fatigue is why clinical decision support fails. The
  live product's interaction model should be a board of *who has changed since you last looked, and
  why* — an ordering, not an interruption. That is a different product from every CDS tool on the
  market, and it is only credible **after** the shadow data proves the ordering is right.

## 11. Standing constraints — do not relearn these

**Design and brand** (banned permanently by Dhruv, 2026-07-27):
- No **monospace** anywhere. `--font-family-mono` is deleted; the utility is `.tnum` (sans +
  tabular-nums). Mono read as generated-template UI.
- No **status pills with a leading dot** (`● Provisional ESI 2`). Reads as AI slop.
- No pulsating dots or anything that loops as decoration.
- Fonts are **Instrument Sans**, self-hosted, metric-matched. **Inter and Geist are banned** —
  wrong xh:cap ratio, which `size-adjust` cannot fix.
- `QUAL-004`: no emoji on patient screens (enforced, L1).

**CSS gotchas that each cost real debugging:**
1. `light-dark()` resolves against the color-scheme of the element where the property is
   *declared*, not used. Use explicit per-scheme token blocks.
2. Chrome *multiplies* `ascent-override` by `size-adjust`; overrides must be pre-divided.
3. `transform-style: preserve-3d` stops `z-index` deciding paint order and sorts by computed depth
   instead. Put `perspective` on the parent and leave it `flat`.
4. Pinned scroll sections are bounded by viewport **height**, not just width.

**Engineering:**
- Astro has no page-exclude mechanism — moving the directory is the switch (§2).
- `PERF-002`: the Lambda warm ping had been timing out every 4 minutes and running up the bill
  (`42abe22`). Any new scheduled invocation needs a bounded timeout and a cost check.
- Unsplash and Pexels serve anti-bot challenges to headless Playwright. Do not try to defeat them.
- Never ship visual work blind — screenshot the render and look at it before claiming done.

**Voice:** blunt, cold honesty, no glazing. Natural prose Dhruv can own. If something is broken,
say so with the output.

---

## 12. Decisions only Dhruv can make

Do not guess these. Ask, and record the answer here.

- **D1 — Product naming.** Is the shadow product "Solace Shadow"? Does the four-product framing
  (Prearrival / Transfer / Ledger / Measure) survive, or does everything become one product with
  phases?
- **D2 — The unreleased hero images.** Replace, license properly, or accept the risk knowingly.
  Currently live and undecided since 7/27.
- **D3 — Are you willing to park 40 services?** The strategy doc names this as the question the
  whole plan hangs on. **If the answer is no, say so now, because the rest of the plan assumes
  focus that does not otherwise exist.** The P2-1 list is a proposal awaiting sign-off.
- **D4 — Which Baylor, and is there an existing relationship?** BSWH (51-hospital system), Baylor
  College of Medicine (Houston, academic), or Baylor University Medical Center (Dallas, part of
  BSWH)? Everything here assumes **BSWH**. Any existing clinician, alum, or family connection is
  worth more than any feature in this document.
- **D5 — Runway and team size.** The sequencing assumes a very small team and no near-term revenue
  pressure. If either is wrong, the order changes.
- **D6 — Does an existing BAA with any covered entity exist?** If yes, the data timeline compresses
  substantially.
- **D7 — Entity and domain.** "Solace Health, Inc." vs `mysolaceclinic.com` vs `solace.health`
  (not ours). Resolve before contracts.

---

## 13. Session-start protocol for the next Claude

1. Read this file, then `CONSTITUTION.md` §preamble + the L1 rules, then
   `docs/strategy/2026-07-30-product-strategy.md`.
2. Re-verify the four live endpoints in §2. If the API is down or `"triage"` is no longer
   `"trained_ensemble"`, that is the first thing to fix and to tell Dhruv about.
3. Check `git log --oneline -20` against this file's `main` pointer (`c802820`). If it has moved,
   this document may be stale — say so rather than assuming.
4. Confirm which P0 items are still open before doing any P1 work.
5. Do not add a service. Do not add a page. Do not add a feature. Ask what to finish instead.
6. When you finish a checklist item, tick it **in this file** and commit that with the change.

---

## 14. Document index — what to trust

| File | What it is | Trust |
|---|---|---|
| `HANDOFF.md` (this) | Current state + plan | Current as of 2026-08-10 |
| `CONSTITUTION.md` | Enforced engineering rules, v1.1.0 | **Authoritative.** L1 rules cite tests |
| `docs/strategy/2026-07-30-product-strategy.md` | The strategic reframe, 614 lines, sourced | **Authoritative on strategy.** Its §9 build order was not executed |
| `docs/baylor/solace-bswh-mckinney.{html,pdf}` | The McKinney shadow proposal | **Ready to send.** Best GTM artifact in the repo |
| `docs/clinical-performance-brief.md` | Model architecture + honest synthetic ceiling | Honest; predates recent work |
| `docs/HIPAA_COMPLIANCE_DUE_DILIGENCE.md` | 545-line compliance package, 17 sections | Useful skeleton; **claims need P0-6 audit** |
| `README.md` | Public repo README, hackathon-framed | Accurate on architecture; **hackathon framing, and its links must be re-verified before use as sales material** |
| `SECURITY.md` | HIPAA control narrative | **Needs P0-6 audit** |
| `docs/roadmap-50-features.md` | The old "doctor's pal" thesis | **SUPERSEDED.** Do not build from it |
| `docs/research/*.md` | May 2026 competitive / regulatory / clinical research | Good research; the strategy laid on top of it was wrong (see strategy §0) |
| `docs/DEVPOST.md`, `docs/HACKATHON-H0-submission.md` | Hackathon submissions | Historical |
| `landing/src/pages-parked/README.md` | Why the eleven pages are parked and how to restore | Accurate |

---

## 15. The one-paragraph version

Solace is a real, deployed, HIPAA-hardened ED triage system with a live 4-model ensemble, a
recently tripled test suite, and a genuinely well-built tamper-evident decision ledger — sitting
underneath 68 shallow services that make none of it sellable. You cannot out-data Epic, whose Comet
model saw 118 million patients, and you cannot out-build Abridge, who raised $812 million. The
defensible ground is the seam Epic is structurally weak at: before registration, between
institutions, and **the fact that Epic cannot be the neutral auditor of Epic**. The thing to sell
first is not an AI product at all — it is a 90-day no-cost shadow deployment that tells one
emergency department its own under-triage rate and recognition delay, a patient-safety number Epic
reporting does not produce, at zero clinical risk, with the misses and false alarms in the report
rather than buried. Four things stand between here and that: a re-scoring scheduler, a durable
ledger, a recognition-delay label, and a report generator. Before any of them, fix the model card
that claims real training data for a model trained on 80k synthetic encounters, because that single
false line is the one a compliance officer finds.
