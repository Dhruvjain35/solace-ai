# Solace Product Strategy — July 2026

**Status:** working document. Written to be argued with, not agreed with.
**Author:** Claude (Opus 5), at Dhruv's request for a brutally honest assessment.
**Date:** 2026-07-30

---

## 0. How to read this

You asked for brutal honesty. Six of the conclusions below contradict things
currently written in `docs/roadmap-50-features.md` and
`docs/research/competitive-2026-05.md`. Where they do, I say so and give the
reason. Those documents are good research; the strategy laid on top of them is,
I think, wrong, and wrong in a way that is expensive.

Everything factual here is cited. Where I could not verify something, I say
"unverified" rather than asserting it. Where the answer depends on information
only you have, it is in §10 as an open question rather than a guess.

---

## 1. The honest state of the codebase

I read it before forming any opinion. Numbers, not impressions:

| Measure | Value |
|---|---|
| Backend Python | ~43,600 lines |
| Frontend TS/TSX | ~24,000 lines |
| Services | 68 modules in `backend/services/` |
| Routers | 26 |
| Test files | **11** |
| Test lines | ~2,365 |

**Test-to-source ratio is roughly 1:18.** For clinical software that touches
PHI and produces acuity recommendations, that is not a gap, it is a
disqualification. No hospital compliance office will pass this, and they will
not need to read the code to fail it — they will ask for the test report.

The triage model is real ML — a stacked LightGBM/XGBoost/CatBoost/MLP ensemble
with SHAP explanations and threshold optimisation (`backend/services/triage_ml.py`).
The engineering is competent. But `scripts/train_triage_model.py` and
`backend/services/model_cards.py` both record the training set as:

> **"Kaggle Triagegeist (80k synthetic ED encounters)"**

A model trained on synthetic data cannot be sold as a clinical model. It cannot
be validated, it cannot be published, it cannot survive a single question from
a Chief Medical Information Officer. You already knew this — it is why you
opened with the data problem. You are right that it is the central problem. You
are wrong about the order of operations, which is §4.

**The deeper problem is 68 services.** Sixty-eight services built by a small
team, with eleven test files, is not a product. It is sixty-eight demos. Nothing
is deep enough that removing it would hurt anyone. That is the actual reason the
product feels useless — not missing features, but that no single thing in it is
finished to the point where a department would notice its absence.

---

## 2. What the research actually says

### 2.1 You cannot win on data. That contest is already over.

Epic launched **Comet** in September 2025: a family of decoder-only transformer
models pretrained on **118 million patients, 115 billion discrete medical events,
drawn from 300 million unique patient records across 310 health systems**, and
evaluated zero-shot on 78 clinical prediction tasks. Access opened to Cosmos
member health systems in February 2026.
([Epic/HLTH](https://hlth.com/insights/news/epic-launches-comet-ai-platform-to-predict-patient-health-journeys-2025-09-04),
[Healthcare IT News](https://www.healthcareitnews.com/news/epic-unveils-ai-agents-showcases-new-foundational-models),
[paper](https://arxiv.org/html/2508.12104v1))

Read that number again. Any plan whose competitive claim is "our model is better
because we trained on real patient data" is dead the moment a CMIO asks what you
trained on versus what Cosmos trained on. You will not out-data Epic. Neither
will Abridge, and Abridge has raised roughly **$812M** at a **$5.3B** valuation.
([Sacra](https://sacra.com/c/abridge/))

**This does not mean data does not matter. It means data you can also get from
Epic does not matter.** §4 is about the data Epic structurally cannot have.

### 2.2 The full-stack strategy is already lost

`roadmap-50-features.md` says: "No single competitor ships the full stack. That
is the wedge." Your own May 2026 research already contradicts this — it notes
that Heidi, Freed, Glass, OpenEvidence, Suki and Sully all shipped scribe + CDS +
coding inside one product, and concludes "the full-stack doctor's pal framing is
no longer unoccupied."

It is worse than that now:

- **Abridge**: ~$812M raised; 90+ disclosed health systems; Kaiser (24,600
  physicians, 40 hospitals, 600 clinics), Mayo, Hopkins, Duke, UPMC; #1 Best in
  KLAS for Ambient AI in RCM two years running.
  ([Sacra](https://sacra.com/c/abridge/), [EHR Source](https://www.ehrsource.com/articles/ambient-ai-scribes-comparison/))
- **Microsoft Dragon Copilot**: 100k+ daily clinicians, M365 distribution, a
  partner marketplace, 58 languages — which by itself dissolves the "20-language
  intake" line in the roadmap.
- **Epic**: shipping natively, inside the system of record, at zero marginal
  integration cost to the customer.

A two-person team cannot beat any of them on breadth. Shipping the 51st feature
does not change this. Each additional feature makes it worse, because it splits
attention that was already too thin to finish anything.

### 2.3 There is a real regulatory tailwind, and it is dated

Two things create actual openings:

**CMS 2026 OPPS Final Rule** adopted an **Emergency Care Access and Timeliness**
measure, which includes the proportion of ED patients who board longer than
**four hours**. ([ACEP](https://www.emergencyphysicians.org/press-releases/2025/11-21-25-acep-statement-on-cms-2026-opps-final-rule-and-new-emergency-department-boarding-measure))
Boarding just became a number hospitals are measured on rather than a thing they
complain about. Anything that moves it stops being a nice-to-have and becomes a
budget line.

**ONC HTI-1** created the Decision Support Interventions criterion at
§170.315(b)(11), requiring certified health IT to surface **31 source attributes**
for every *Predictive* DSI, in plain language, so end users can judge whether it
is Fair, Appropriate, Valid, Effective and Safe.
([ONC fact sheet](https://www.healthit.gov/sites/default/files/page/2023-12/HTI-1_DSI_fact%20sheet_508.pdf),
[ONC test method](https://healthit.gov/test-method/decision-support-interventions/))
Every hospital deploying predictive AI now has a documentation obligation, and
most have no system for discharging it.

### 2.4 Baylor Scott & White already bought most of what Solace sells

This is the finding that should hurt the most, and it is the most useful one.

BSWH has already deployed: **AI-enabled ED efficiency recommendations**, an
**ambient documentation** product, and **"Help Me Decide"** — a patient-facing
symptom-navigation AI that routes people to e-visit, urgent care, primary care,
nurse triage or the ED.
([Community Impact](https://communityimpact.com/austin/lake-travis-westlake/health-care/2026/06/22/baylor-scott-white-health-integrates-ai-tool-to-help-patients-navigate-care-options/),
[Becker's CIO list](https://www.beckershospitalreview.com/healthcare-information-technology/135-hospital-and-health-system-cios-to-know-2026/))

"Help Me Decide" is Solace's patient intake and triage pitch, already live,
already clinician-governed, already inside their Epic. Walking into Baylor with
multilingual intake + AI triage + ambient scribe is walking in with three things
they have bought.

**But**: BSWH is building **four new small-format emergency hospitals across
North Texas over the next two years**, jointly operated with Emerus.
([BSWH newsroom](https://news.bswhealth.com/en-US/releases/baylor-scott-white-health-expanding-access-to-in-person-and-virtual-care))
Small-format EDs have one defining operational problem: they are not equipped for
anything complex, so their business depends on moving patients *out* — to a
bigger BSWH site — quickly, safely, and with the documentation EMTALA requires.
That is a specific, funded, dated pain, at the exact edge where they are
expanding. §5 builds on it.

### 2.5 The data you want is not legally available the way you want it

You said: "we need real patient data we can use to train our models on." Here is
the actual legal picture, because getting this wrong ends the company.

**MIMIC-IV-ED** (Beth Israel Deaconess, 400,000+ ED visits 2011–2019, with a
triage table containing vitals, pain score, chief complaint and acuity) is the
obvious candidate and the one everyone reaches for.
([PhysioNet](https://physionet.org/content/mimic-iv-ed/2.2/))

It is released under the **PhysioNet Credentialed Health Data License 1.5.0**,
which **disallows commercial use**, requires CITI training and individual
credentialing, forbids sharing access, and requires that any redistribution
preserve the same licence and access control.
([licence](https://physionet.org/about/licenses/physionet-credentialed-health-data-license-150/))

So: **you may use MIMIC to do research, validate a method, and publish. You may
not ship a product containing a model trained on it.** Anyone telling you
otherwise is describing a licence violation.

The lawful routes to trainable real data are:

1. **BAA with a covered entity.** You become a Business Associate, receive PHI
   for permitted purposes, and — critically — the BAA must explicitly permit
   *model training*, which standard BAAs usually do not. This is a negotiated
   term, not a default.
2. **Limited Data Set + Data Use Agreement.** Dates and geography above street
   level survive; direct identifiers do not. Requires an executed DUA. Research
   framing.
3. **De-identified data**, by Safe Harbor (strip the 18 identifiers) or Expert
   Determination (a qualified statistician certifies re-identification risk is
   very small, with documented method). Expert Determination retains far more
   signal and is worth paying for.
4. **Data you generate yourself** under a BAA with each customer, where the
   contract grants you rights to use de-identified derivatives.

([HIPAA Journal on LDS](https://www.hipaajournal.com/limited-data-set-under-hipaa/),
[de-identification standards](https://www.forasoft.com/learn/telemedicine/articles-telemedicine/de-identification-analytics-on-health-data),
[BAA and ML training](https://blog.promise.legal/hipaa-ai-ml-training-baa-phi-compliance/))

**The order you proposed is backwards.** You cannot get data and then win Baylor.
You win a design partner, and the data comes through the partnership, under a BAA
or DUA, as a negotiated term. Route 4 is the only one that compounds, and it is
the only one that produces data Epic does not also have.

---

## 3. Why "moat" is the wrong first question

You asked for a moat that Epic and Cerner "can't just build in one day." Almost
any *feature* they can. They have more engineers than you have users.

Software moats in healthcare are not features. There are, realistically, four:

1. **Cross-organisational network effects.** Value rises with the number of
   *separate institutions* on the network. Surescripts, Availity, Epic's own Care
   Everywhere. An incumbent inside one hospital cannot unilaterally create this.
2. **Regulatory position.** Being the certified/designated thing (a TEFCA QHIN,
   a certified module). Slow, expensive, durable.
3. **Proprietary compounding data** that the incumbent structurally cannot
   observe.
4. **Workflow embedding** with high switching cost. Weakest of the four; real,
   but rentable rather than ownable.

Epic is overwhelmingly strong at everything **inside** one health system's four
walls, from the moment of registration onward. Epic is structurally weak at
exactly two things:

- **Before registration.** Epic's record begins when the patient is registered.
  The 15–40 minutes while an ambulance is en route, or while a referring
  facility is deciding where to send someone, is invisible to it.
- **Between organisations that do not share an Epic instance.** Care Everywhere
  moves *records*. It does not make *decisions* — it does not accept a transfer,
  reserve a bed, or negotiate capability against capacity between two competing
  health systems.

**That seam is the only defensible ground available to you.** It satisfies moats
1 and 3 simultaneously: a two-sided network, generating data that begins before
Epic's record does.

This is also why it is not a one-day build for Epic. Not because the software is
hard — because Epic would have to build relationships with EMS agencies and
competing health systems that it does not have and whose incentives it does not
control.

---

## 4. The strategic reframe

> **Solace stops being an AI assistant inside the ED, and becomes the system that
> owns the patient's journey before and between EDs.**

Everything already built either serves that or gets parked. Concretely:

| Existing asset | Fate |
|---|---|
| Triage ML ensemble + SHAP + conformal sets | **Keep.** Becomes the acuity engine inside Prearrival. Must be retrained on partner data. |
| Multilingual intake | **Keep, repositioned.** Not a consumer front door — the EMS/referring-facility capture channel. |
| HL7 v2 / FHIR gateway, CDS Hooks | **Keep.** This is the integration substrate the network runs on. |
| Model cards, governance, audit log, consent gate | **Keep and promote.** Becomes Ledger (§5.3). |
| Ambient scribe | **Park.** You will not beat Abridge or Microsoft here, and every hour spent is an hour not spent on the seam. |
| Differential diagnosis, letters, PA packets, HCC, HEDIS, refills, no-show, telehealth, SDOH, ~40 others | **Park or delete.** They are not defensible and they are the reason nothing is finished. |

Parking 40 services will feel like destroying work. It is the single highest-value
action available. Sixty-eight shallow services is why the product is useless; it
is not a coincidence to be fixed alongside, it is the cause.

---

## 5. The products

Four. Each is a product with its own DoD and MAE. Two are the moat, one is the
trust layer that gets you through procurement, one is the money argument.

---

### 5.1 Solace **Prearrival** — the channel that starts before the chart

**What it is.** EMS crews and referring facilities send structured patient data
to the receiving ED *while en route*. The ED sees an inbound board: who is
coming, when, how sick, what they will need on arrival. On arrival the data is
already a chart, not a re-interview.

**Why Epic cannot do this quickly.** EMS runs on ESO, ImageTrend and Zoll, not
Epic. There is no real-time channel from an ambulance to the ED chart; NEMSIS is
a retrospective reporting standard, not a live feed. For Epic to own this it must
build and maintain relationships with thousands of independent EMS agencies,
most of which are municipal, none of which are Epic customers. That is not an
engineering problem.

**The moat mechanics.** Two-sided: each EMS agency added makes the network more
valuable to hospitals; each hospital added makes it more valuable to agencies. And
it generates a dataset that does not exist anywhere: *pre-arrival observation →
final ED outcome*, longitudinally, with consent, under a BAA. Epic's data starts
after the ambulance doors open. Yours starts twenty minutes earlier.

**MAE — Minimum Awesome Experience.**
> A charge nurse looks at one screen and knows what is walking through the door
> for the next 30 minutes, ranked by how sick, with the two things that must not
> be missed for each. When the patient arrives, their name, complaint, vitals
> trend and allergies are already in the chart, and nobody re-asked a bleeding
> patient for their date of birth.

Awesome is not the prediction. Awesome is *the re-interview not happening*.

**Definition of Done.**
- [ ] EMS partner can submit a structured pre-arrival record from a mobile client in **under 45 seconds** of interaction, one-handed, offline-tolerant with queued sync.
- [ ] Receiving-facility board updates within **5 seconds** of submission, verified under simulated 4G latency.
- [ ] Every field maps to a FHIR R4 resource; the arrival hand-off writes to the EHR via the existing gateway and is verified against an Epic sandbox and one non-Epic sandbox.
- [ ] Acuity estimate carries a conformal prediction set and a SHAP attribution, never a bare number, and refuses to emit when input completeness is below a stated threshold.
- [ ] Full audit trail: who saw what, when, under which consent basis. Log redaction verified — no PHI, no UUIDs in CloudWatch.
- [ ] **Test coverage ≥ 90% on all new modules**, including a property test that no code path emits an acuity without an accompanying uncertainty set.
- [ ] Failure mode documented and tested: network loss, partial data, duplicate patient, cancelled transport, patient diverted mid-transit.
- [ ] Model card published with all **31 HTI-1 predictive DSI source attributes** populated.
- [ ] Runs for 14 consecutive days in a non-clinical shadow deployment with zero P1 defects before any clinical exposure.

---

### 5.2 Solace **Transfer** — the acceptance decision, not the record

**What it is.** A referring facility requests transfer. The system matches
clinical need against real capability and real-time capacity across candidate
receiving facilities, produces an accept/decline with a **stated reason**, and
generates the EMTALA-required documentation as a by-product of the decision
rather than as paperwork afterwards.

**Why this is the Baylor wedge specifically.** BSWH is opening four small-format
emergency hospitals with Emerus over two years. Their entire operating model
depends on moving complex patients to larger BSWH sites fast and defensibly.
Today that is phone calls, and the transfer centre is a bottleneck nobody has
instrumented.

**Why Epic cannot do this quickly.** Transfers cross organisational and often EHR
boundaries. Care Everywhere shares records; it does not arbitrate capacity between
institutions, and it has no concept of *decline with reason*. And the sending and
receiving facilities are frequently business competitors — a neutral third party
is structurally better placed than either side's EHR vendor.

**MAE.**
> A rural physician with a sick patient makes **one** request instead of six phone
> calls, and gets a named accepting physician, a bed, and a reason — within ten
> minutes. When the transfer is declined, the reason is recorded, and for the
> first time the health system can see *why* transfers fail.

The declined-transfer dataset is, I suspect, more valuable than the accepted one.
Nobody has it.

**Definition of Done.**
- [ ] Request submitted in **under 90 seconds** by a physician who has never been trained on the product.
- [ ] Capability + capacity matching against a maintained facility registry; stale capacity data is shown as stale, never silently assumed current.
- [ ] Every decision (accept, decline, timeout) is recorded with an attributed human decision-maker and a structured reason code.
- [ ] EMTALA documentation generated automatically and reviewed by counsel before first clinical use — **counsel sign-off is a DoD item, not a follow-up.**
- [ ] Median request-to-first-response measured and displayed; the product's own SLA is a visible metric.
- [ ] **Test coverage ≥ 90%**, including adversarial tests: simultaneous requests for the last bed, decline-loop between two facilities, mid-transfer patient deterioration.
- [ ] Two-facility pilot completes 30 real transfers with zero patient-safety events and a signed clinical-sponsor attestation.

---

### 5.3 Solace **Ledger** — the AI accountability layer

**What it is.** A registry and audit system for every predictive model operating
in a hospital — including models Solace did not build. It holds the 31 HTI-1
source attributes, tracks live calibration drift, records every AI-influenced
decision and every clinician override, and produces the evidence pack a
compliance office needs.

**Why it matters more than it sounds.** Every hospital deploying predictive AI
now carries an HTI-1 documentation obligation, and almost none have a system for
it. More importantly for you: **this is what gets Solace through procurement.**
A startup selling clinical AI to a health system dies in security and compliance
review. Arriving with the accountability layer as a *product* inverts that
conversation.

**Why a third party is structurally right.** Epic will document Epic's models. It
has no incentive to neutrally document Abridge's, Aidoc's, or a home-grown sepsis
model. A registry that only covers one vendor's models is not a registry.

**Honest caveat.** I am least confident about this one as a standalone
*purchase*. It may be a feature that closes deals rather than a line item that
generates revenue. Treat it as sales infrastructure until a customer offers money
for it specifically.

**MAE.**
> A compliance officer asks "what AI is touching our patients and how do we know
> it still works?" and gets a complete, current, exportable answer in under a
> minute — covering models Solace didn't build.

**Definition of Done.**
- [ ] All 31 HTI-1 predictive DSI source attributes captured per registered model, in plain language, validated against the ONC test method.
- [ ] Live calibration monitoring with alerting on drift beyond a configured threshold; alert fires in a test that deliberately induces drift.
- [ ] Every AI-influenced decision and every override is append-only, tamper-evident, and queryable by patient, clinician, model and date.
- [ ] Export produces an auditor-ready pack without engineering involvement.
- [ ] Third-party model registration works for at least one non-Solace model end to end.
- [ ] **Test coverage ≥ 95%** — this is the component whose failure is least tolerable.

---

### 5.4 Solace **Measure** — the boarding number, computed and explained

**What it is.** Automated, auditable computation of the CMS Emergency Care Access
and Timeliness measure, including the >4-hour boarding proportion, with driver
attribution: *which* boarding hours came from which upstream cause.

**Why now.** The measure landed in the 2026 OPPS final rule. Hospitals must
report it. Most will compute it by hand out of Epic reporting, and none of them
will be able to explain *why* the number is what it is.

**Honest positioning.** Qventus and LeanTaaS already own boarding *optimisation*
— Qventus publishes 10–20% ED boarding reduction.
([Qventus](https://www.qventus.com/)) Do not compete with them on optimisation.
Compete on **measurement and attribution**, which is a compliance need with a
date on it, and which feeds Prearrival and Transfer with the operational truth
they need.

**MAE.**
> An ED director opens one page before the operations meeting and can say exactly
> what the boarding number is, which direction it is moving, and the three
> upstream causes that produced most of it — with the underlying encounters one
> click away.

**Definition of Done.**
- [ ] Measure computed per the CMS specification, with the spec version recorded; a spec change is a config change, not a code change.
- [ ] Every reported figure traces to the underlying encounters.
- [ ] Attribution model is documented, tested against hand-computed fixtures, and states its own uncertainty.
- [ ] Reconciles against the hospital's own EHR-derived figure within a stated tolerance, and disagreements are explainable.
- [ ] **Test coverage ≥ 90%**, including a full-year fixture with known-correct expected output.

---

## 6. The data plan, honestly

**Phase 0 — now, before any partnership.** Get credentialed on PhysioNet, take
the CITI training, and use MIMIC-IV-ED for *method validation only*. Retrain the
triage ensemble on real BIDMC data, compare honestly against the synthetic-trained
model, and publish the delta. This produces credibility, not a shippable model.
Respect the licence: **research and education only, no commercial use, no shipping
weights.**
([MIMIC-IV-ED](https://physionet.org/content/mimic-iv-ed/2.2/),
[licence](https://physionet.org/about/licenses/physionet-credentialed-health-data-license-150/))

**Phase 1 — the design partnership.** Data rights are a negotiated term in the
first contract, not an afterthought. What to ask for, in order of value:
1. Right to use de-identified derivatives of data generated *through Solace* for
   model improvement. This is the one that compounds and the easiest to be
   granted, because you generated it.
2. Limited Data Set under DUA for retrospective validation.
3. BAA language explicitly permitting model training on PHI for the covered
   entity's own operations.

**Phase 2 — the compounding asset.** Every pre-arrival record and every transfer
decision is a labelled example that Epic cannot observe, because it happens before
registration or between institutions. Ten partner facilities generating this for
eighteen months is a dataset nobody else can assemble at any price. That — not a
better model architecture — is the durable position.

**What I will not help with:** obtaining PHI outside these routes, scraping,
"anonymising" by hand-waving, or training on data whose licence forbids it. Not
squeamishness — it is criminal exposure under HIPAA and it is the one mistake
that cannot be recovered from.

---

## 7. The Baylor entry plan

Do not pitch Baylor an AI product. They have bought three already (§2.4).

Pitch the **four new Emerus-operated emergency hospitals**, and pitch Transfer.
The argument:

> "You are opening four small-format EDs. Their clinical model depends on moving
> complex patients to your big sites quickly and defensibly. Today that is phone
> calls, and you cannot see why transfers fail. Let us instrument that at one
> site, for free, for ninety days, and show you the declined-transfer data you
> have never had."

Why this works where a general AI pitch does not:
- It is tied to a **funded, dated expansion**, not a general efficiency claim.
- It is a workflow BSWH has not already bought a product for.
- It is small enough to approve at department level.
- The deliverable is a dataset they cannot currently produce, which is a much
  easier "yes" than a clinical AI deployment.

**Realistic timeline.** A health system pilot involving PHI takes 6–12 months
from first conversation to first patient: security review, BAA, IRB if the data
is used for research, clinical sponsor, IT integration queue. Anyone promising
faster is not counting the queue. Plan for it and start the security
documentation now, in parallel, not after.

**Prerequisite I would not skip:** a named clinical sponsor inside BSWH — an ED
physician or nursing director who wants this to exist. Without one, procurement
has nobody to route to and it dies quietly.

---

## 8. Engineering standard: TDD and the global DoD

You asked to build this test-first. Given an 11-file test suite over 43k lines,
that is the correct call. Concretely:

**Test-driven means:**
1. Write the failing test that expresses the behaviour.
2. Write the minimum code to pass it.
3. Refactor with the test as the safety net.
4. No production code without a test that failed first.

**For clinical software, three additional rules:**
- **Every model output path has a property test** asserting an uncertainty
  estimate is present. A bare number must be unreachable by construction.
- **Every PHI path has a redaction test** asserting nothing identifiable reaches
  logs. This exists today (`log_redaction.py`) and is under-tested.
- **Every safety-relevant threshold has a fixture** with a hand-verified expected
  output, reviewed by a clinician, stored in version control.

### Global Definition of Done

Nothing merges unless all of these are true:

- [ ] Tests written first; the commit history shows the test failing before the implementation
- [ ] Coverage ≥ 90% on new code (≥ 95% for Ledger)
- [ ] All existing tests pass; no skipped tests without a linked issue
- [ ] Failure modes enumerated in the PR description and each has a test
- [ ] No PHI in logs — verified by test, not by inspection
- [ ] Consent gate enforced before any AI call (CONSTITUTION SEC-004)
- [ ] Any model output carries uncertainty and attribution
- [ ] Model card updated if model behaviour changed
- [ ] Audit log entry for anything a clinician sees or acts on
- [ ] Reviewed by someone who did not write it
- [ ] Documentation updated in the same PR

### The MAE test

For each product, before it is called done, one question:

> Would a clinician who is not being paid to like this choose to use it on a bad
> shift?

If the honest answer is no, it is not done, whatever the checklist says.

---

## 9. What I would do in the next 30 days

In order. Each blocks the next.

1. **Delete or park 40 services.** Keep triage ML, the EHR gateway, governance,
   intake capture. Everything else moves to a `parked/` directory with a README.
   This is a day of work and it is the highest-value day available.
2. **Get the test suite to a real baseline** on what remains. Not 90% yet — a
   floor, with CI enforcing no regression.
3. **PhysioNet credentialing + CITI training.** Starts a clock you do not control;
   start it first.
4. **Retrain triage on MIMIC-IV-ED, measure honestly against the synthetic
   baseline, publish the delta.** Research use only.
5. **Build Prearrival to its MAE.** One EMS partner, one receiving ED, shadow
   mode, no clinical reliance.
6. **In parallel, find the named clinical sponsor at BSWH.** This is a
   relationship task, not an engineering task, and it has the longest lead time
   of anything on this list.

---

## 10. Open questions I cannot answer for you

These change the plan materially and only you have the answers:

1. **Which Baylor?** Baylor Scott & White Health (the 51-hospital system), Baylor
   College of Medicine (Houston, academic), or Baylor University Medical Center
   (Dallas, part of BSWH)? They are different institutions with different buyers,
   and I have assumed BSWH throughout.
2. **Do you have any existing relationship there** — a clinician, an alum, a
   family connection? This is worth more than any feature in this document.
3. **What is the runway and the team size?** The plan above assumes a very small
   team and no near-term revenue pressure. If either is wrong, the sequencing
   changes.
4. **Is there an existing BAA with any covered entity?** If yes, the data timeline
   compresses substantially.
5. **Are you willing to delete 40 services?** If not, say so now, because the rest
   of this plan assumes focus that does not exist otherwise.

---

## 11. The one-paragraph version

Solace's current product is sixty-eight shallow services with eleven test files
and a triage model trained on synthetic Kaggle data; it is not defensible and not
sellable. You cannot out-data Epic, whose Comet model saw 118 million patients,
and you cannot out-build Abridge, who raised $812 million. The only ground Epic
is structurally weak on is the seam **before registration and between
institutions** — the ambulance en route, and the transfer that crosses
organisational lines. Build two products there (Prearrival, Transfer), a trust
layer that gets you through procurement (Ledger), and a compliance measurement
tied to the new CMS boarding rule (Measure). Get into Baylor through their four
new Emerus emergency hospitals, whose operating model depends on transfers, not
through an AI pitch they have already bought three times. Data comes *through*
that partnership under a BAA, not before it — and the data you generate at the
seam is the only dataset Epic cannot also have.

---

## Sources

- [Epic launches Comet — HLTH](https://hlth.com/insights/news/epic-launches-comet-ai-platform-to-predict-patient-health-journeys-2025-09-04)
- [Epic unveils AI agents, foundational models — Healthcare IT News](https://www.healthcareitnews.com/news/epic-unveils-ai-agents-showcases-new-foundational-models)
- [Generative Medical Event Models Improve with Scale — arXiv](https://arxiv.org/html/2508.12104v1)
- [Abridge revenue, valuation & funding — Sacra](https://sacra.com/c/abridge/)
- [Ambient AI scribes 2026: evidence, ROI, vendor comparison — EHR Source](https://www.ehrsource.com/articles/ambient-ai-scribes-comparison/)
- [ACEP on the CMS 2026 OPPS final rule and the ED boarding measure](https://www.emergencyphysicians.org/press-releases/2025/11-21-25-acep-statement-on-cms-2026-opps-final-rule-and-new-emergency-department-boarding-measure)
- [ONC HTI-1 Decision Support Interventions fact sheet](https://www.healthit.gov/sites/default/files/page/2023-12/HTI-1_DSI_fact%20sheet_508.pdf)
- [ONC §170.315(b)(11) DSI test method](https://healthit.gov/test-method/decision-support-interventions/)
- [BSWH "Help Me Decide" — Community Impact](https://communityimpact.com/austin/lake-travis-westlake/health-care/2026/06/22/baylor-scott-white-health-integrates-ai-tool-to-help-patients-navigate-care-options/)
- [BSWH expanding in-person and virtual care (Emerus emergency hospitals)](https://news.bswhealth.com/en-US/releases/baylor-scott-white-health-expanding-access-to-in-person-and-virtual-care)
- [Becker's — 135 hospital and health system CIOs to know, 2026](https://www.beckershospitalreview.com/healthcare-information-technology/135-hospital-and-health-system-cios-to-know-2026/)
- [MIMIC-IV-ED v2.2 — PhysioNet](https://physionet.org/content/mimic-iv-ed/2.2/)
- [PhysioNet Credentialed Health Data License 1.5.0](https://physionet.org/about/licenses/physionet-credentialed-health-data-license-150/)
- [What is a Limited Data Set under HIPAA — HIPAA Journal](https://www.hipaajournal.com/limited-data-set-under-hipaa/)
- [HIPAA de-identification: Safe Harbor vs Expert Determination](https://www.forasoft.com/learn/telemedicine/articles-telemedicine/de-identification-analytics-on-health-data)
- [HIPAA and AI: when ML training crosses the BAA line](https://blog.promise.legal/hipaa-ai-ml-training-baa-phi-compliance/)
- [Aidoc FDA clearance for comprehensive AI triage — Aidoc](https://www.aidoc.com/about/news/aidoc-secures-fda-clearance-for-healthcares-first-comprehensive-foundation-model-ai/)
- [Qventus — hospital operations AI](https://www.qventus.com/)
- [LeanTaaS iQueue for Inpatient Flow](https://leantaas.com/products/inpatient-flow/)
- [Rural interfacility ED transfers: framework and qualitative analysis — PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7390588/)
- [EMTALA and patient transfers — StatPearls](https://www.ncbi.nlm.nih.gov/books/NBK557812/)
