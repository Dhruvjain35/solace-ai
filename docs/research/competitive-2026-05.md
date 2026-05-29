# Solace Competitive Feature Research — May 2026

**Generated:** 2026-05-16. Companion to `market-update-2026-05.md` (2026-05-12) and `roadmap-50-features.md`. This document covers the **last ~6 months of competitor feature shipping** (Nov 2025 – May 2026), identifies capabilities Solace lacks, names the remaining white space, and gives 8–12 prioritized recommendations laddered to Solace's four wedges: **ambient scribe quality / EHR breadth / doctor admin pain / AI governance**.

---

## 1. The headline shift since the May 12 market update

Two structural moves change the competitive picture:

1. **Every scribe is becoming a "doctor's pal."** Six months ago the scribes did transcription and the reasoning tools (Glass, OpenEvidence) did CDS. That wall is gone. Heidi, Freed, Glass, OpenEvidence, Suki, and Sully have all shipped scribe + CDS + coding within one product. The "full-stack doctor's pal" framing that `roadmap-50-features.md` calls "the wedge" is **no longer unoccupied** — it is now the consensus product direction. Solace's differentiation must move *down a layer*: from "we ship the whole stack" to "we ship the whole stack with calibrated, auditable, governed AI on the non-Epic 58% of the market."

2. **Epic is building directly into Solace's two remaining moats.** At HIMSS 2026, Epic previewed (a) **Diagnosis Advisor** — native differential diagnosis inside Art, and (b) **Agent Factory** — a visual builder for customer-built AI agents with local policy/knowledge bases. These are the exact analogs of Solace's Ddx engine and no-code workflow builder. Epic will not ship these well or soon for non-Epic systems, but the Epic-installed-base wedge for Ddx and workflow-builder is now closing. (Sources: [Fierce Healthcare HIMSS26](https://www.fiercehealthcare.com/ai-and-machine-learning/himss26-epic-expands-ai-roadmap-previews-factory-build-and-orchestrate-ai), [Healthcare IT News](https://www.healthcareitnews.com/news/epic-unveils-ai-agents-showcases-new-foundational-models).)

The strategic conclusion is unchanged but sharper: **sell where Epic is not, and win on calibration/governance, not on feature count.**

---

## 2. Competitor-by-competitor: last ~6 months

### Abridge
- **New features:** Real-time prior authorization via Availity partnership (JPM, Jan 2026) — compresses PA from a weeks-long post-visit process to in-encounter; Highmark/AHN co-development on AI prior auth. Abridge for Nurses (named a TIME Best Invention of 2025) now in broad deployment — at UCHealth, 1/3 of ~6,000 clinicians active by Feb 2026.
- **Funding:** $300M Series E (a16z, June 2025, $5.3B) **plus a $316M Series E extension in April 2026**.
- **EHR:** Epic-deep; expanding nursing flowsheet documentation.
- **Read:** Abridge is defending by going deeper (PA, nursing, payer co-dev), not broader. It is now a payer-connected scribe.
- Sources: [Fierce Healthcare](https://www.fiercehealthcare.com/ai-and-machine-learning/jpm26-abridge-teams-availity-scale-real-time-prior-authorization), [Becker's](https://www.beckershospitalreview.com/healthcare-information-technology/digital-health/abridge-availity-team-up-on-real-time-prior-authorization/), [Sacra](https://sacra.com/c/abridge/), [Abridge press](https://www.abridge.com/press-release/highmark-health-ahn-abridge-prior-authorization).

### Microsoft Dragon Copilot (formerly DAX)
- **New features (HIMSS 2026, March):** Agentic pivot. **Work IQ** layer links EHR data with Microsoft 365 context (email, chat, schedules, org policy). **Partner Marketplace** — third-party AI apps/agents (Canary Speech, Optum, Regard) deployable inside the Copilot UI for RCM and prior auth. Bedside nursing capture → structured flowsheet entries, med-surg templates, LDAW (lines/drains/airways) support. Role-specific workflows for physicians, nurses, radiologists. **58-language** multilingual support. ICD-10 coding assistance.
- **Scale:** 100k+ daily clinicians, 9 countries.
- **Read:** Microsoft is winning on platform + distribution (M365 install base, marketplace) and rural-hospital reach. The 58-language support **directly attacks Solace's 20-language intake wedge.**
- Sources: [HIT Consultant](https://hitconsultant.net/2026/03/05/microsoft-dragon-copilot-himss-2026-agentic-clinical-ai-nurses-radiologists/), [Fierce Healthcare](https://www.fiercehealthcare.com/ai-and-machine-learning/microsoft-debuts-dragon-copilot-ai-clinical-assistant-nurses-expands-access).

### Suki
- **New features:** MEDITECH Expanse ambient integration (first ambient AI using MEDITECH's documentation APIs). **Ambient order staging** — speak the plan, Suki structures/codes/stages prescription orders for EHR approval. Pre-visit patient summaries (prior visits, meds, labs, problems pulled from EHR). UpToDate reference content surfaced alongside notes.
- **EHR / distribution:** athenahealth Preferred Solution Partner (Jan 2026); deep Epic/Oracle/athena/MEDITECH; EHR Partnership Program now includes MEDENT, Azalea Health, WellSky (behavioral health, LTAC, rehab). KLAS study: +$1,223/provider/month incremental revenue.
- **Pricing:** $299–$399 SMB, $350–$500+ enterprise.
- **Read:** Suki has the broadest EHR footprint of any standalone scribe and is the clearest model of "ambient breadth" — the WellSky/MEDENT/Azalea long-tail is exactly Solace's target segment.
- Sources: [DeepCura](https://www.deepcura.com/resources/suki-ai-review), [Suki EHR](https://www.suki.ai/ehr-integrations/), [Fierce Healthcare WellSky](https://www.fiercehealthcare.com/ai-and-machine-learning/suki-inks-partnership-wellsky-integrate-ambient-ai-specialty-care-ehr).

### Notable Health
- **New features:** AI Agents + low-code Flow Builder continue to mature. ADR (additional documentation request) submission agents (save staff up to 80% of time). Closed-loop referral management agents that monitor EHR referrals/orders and chase unscheduled patients (claimed up to 20% referral-leakage reduction).
- **Partnerships:** Inova Health (4M annual visits — system-wide RCM/referral/access agents); Marshall Health Network (scheduling/registration). 12,000+ sites.
- **Read:** Notable owns the **administrative AI** narrative and is winning enterprise without a scribe. This is Solace's "doctor admin pain" wedge competitor, and the one most able to bundle a scribe later.
- Sources: [PRNewswire Inova](https://www.prnewswire.com/news-releases/inova-health-partners-with-notable-to-support-system-wide-ai-and-digital-transformation-strategy-302654419.html), [HLTH](https://hlth.com/insights/news/inova-health-taps-notable-to-utilize-intelligent-ai-agents-2026-01-12).

### Glass Health
- **New features:** Glass now pairs **ambient scribing with real-time CDS in one product** — ambient insights surfaced during the encounter, then differential diagnosis + assessment-and-plan + note generated from the same encounter. Developer API for ambient + CDS. EHR data summaries (notes, history, meds, labs, imaging).
- **EHR:** SMART on FHIR with Epic, eClinicalWorks, athenahealth — note push-back.
- **Pricing:** Free Lite ($0), Starter $20/mo, Pro $90/mo, Max $200/mo (includes EHR integration).
- **Read:** Glass closed its biggest gap — it is no longer "CDS only, no scribe." It now ships exactly the Ddx-inside-the-encounter pattern that `roadmap-50-features.md` item #11 proposed as a Solace differentiator.
- Sources: [Glass features](https://glass.health/features), [Glass ambient CDS](https://glass.health/ambient-cds), [Glass EHR](https://glass.health/ehr-integration).

### OpenEvidence
- **New features (the biggest mover):** Launched **Visits** — an ambient scribe — moving from pure evidence search into documentation. **Coding Intelligence** (March 2026) — inline ICD-10, E/M, CPT suggestions while documenting. **Tandem partnership** (April 2026) — prescription generation + prior-authorization submission inside the platform. **AI-Integrated Doctor Dialer** — unified HIPAA-secure calling/messaging/faxing/voicemail (37M minutes since Dec 2025 limited release).
- **Funding:** $250M Series D (Jan 2026, $12B valuation); ~$700M raised in 12 months.
- **EHR / distribution:** Mount Sinai enterprise Epic embed (March 2026, first enterprise deal); Sutter Health Epic integration (Feb 2026). ~40% of US physicians touch it; ~15M consultations/month.
- **Read:** OpenEvidence has the strongest distribution in clinical AI and is now a full-stack threat (evidence + scribe + coding + Rx/PA + comms). Its weakness remains: ad-supported (pharma CPMs), no published calibration, English-dominant, consumer-grade trust posture rather than enterprise-governed.
- Sources: [Sacra](https://sacra.com/c/openevidence/), [HIT Consultant Mount Sinai](https://hitconsultant.net/2026/04/01/mount-sinai-openevidence-ai-epic-integration-nurses-pharmacists/), [ainvest](https://www.ainvest.com/news/openevidence-ai-platform-infrastructure-powering-40-physicians-daily-clinical-workflows-2604/).

### Heidi Health
- **New features (Feb 2026):** **Heidi Evidence** — ad-free, citation-backed CDS (HealthPathways, BMJ, NICE); free for individual clinicians. **Heidi Comms** — AI patient communications: calls, scheduling, reminders, follow-ups, post-visit engagement across SMS/email/app. Acquired UK clinical-AI company **AutoMedica**. Push-to-chart integrations: athenahealth (Athena Marketplace, section-based linking), Epic (SmartSections mapping), eClinicalWorks (via Vim).
- **Pricing:** Restructured — Clinician tier now **$150/mo annual** (raised from $90). Tiers: Free, Evidence Plus, Clinician, Practice, Enterprise.
- **Funding:** ~$96.6M total raised (Point72, Blackbird, Headline, Latitude).
- **Read:** Heidi is building the Solace stack from the scribe side — scribe + CDS + patient comms. The ad-free positioning of Heidi Evidence is an explicit jab at OpenEvidence and a trust signal Solace should not cede.
- Sources: [Vero](https://www.veroscribe.com/blog/heidi-health-review-2026), [DeepCura](https://www.deepcura.com/resources/heidi-health-review), [All Health Tech](https://allhealthtech.com/heidi-launches-evidence/).

### Freed
- **New features:** **Clinical Decision Support** — evidence-based answers from 50+ verified sources with linked citations. **Coding Assistant** — CPT/ICD-10/E&M suggestions with post-visit optimization (included free). **Front Desk** AI receptionist + revenue-cycle tools in Early Access (March 2026, sales-gated).
- **Pricing:** Starter $39/mo (40 notes), Core $79/mo (unlimited), Premier $119/mo (EHR push + ICD-10). Annual Premier ≈$104/mo.
- **Read:** Freed sets the SMB price floor and has already added CDS + coding at no extra charge. Solace's $129 Clinician tier must clearly out-feature Freed Premier on calibration/intake/governance to justify the delta.
- Sources: [Freed best-AI-scribes](https://www.getfreed.ai/resources/best-ai-scribes), [Freed pricing](https://www.getfreed.ai/pricing), [DeepCura](https://www.deepcura.com/resources/freed-ai-review).

### Nabla
- **New features:** Navina partnership — Nabla's in-visit ambient documentation combined with Navina's clinician copilot for real-time, full-encounter clinical support (Navina brings HCC/care-gap intelligence). Kaiser/Permanente Medical Group rollout in Northern California. Nursing documentation expansion.
- **Pricing:** Free tier (30 consults/mo; unlimited for interns/residents); Pro $119/mo.
- **Funding:** $70M round led by HV Capital (most recent); ~$114M+ total.
- **Read:** Nabla is closing the CDS/HCC gap via the Navina partnership rather than building it. Big enterprise validation (Kaiser).
- Sources: [Fierce Healthcare Navina](https://www.fiercehealthcare.com/health-tech/navina-and-nabla-unveil-partnership-integrate-clinical-copilot-ambient-ai), [SaaSworthy](https://www.saasworthy.com/product/nabla/pricing), [Fierce Healthcare Kaiser](https://www.fiercehealthcare.com/health-tech/medical-scribe-startup-nabla-rollout-tool-kaiser-permanente-docs).

### Sully.ai
- **New features:** **SuperAgent architecture** — composable, isolated agent packages, each multimodal (voice/web/phone/SMS) on a shared auth/billing/access layer. Agent suite: AI Nurse, AI Receptionist, AI Consultant, AI Scribe, AI Pharmacist, AI Medical Coder — all under one EHR connection.
- **Funding:** ~$30–35M total (YC-backed; $21.8M Series A Jan 2025).
- **Pricing:** Undisclosed, sales-led.
- **Read:** Sully is the closest *framing* clone of Solace's "doctor's pal" — but underfunded relative to Abridge/OpenEvidence and with no published clinical validation or governance story.
- Sources: [Insight Health](https://www.insighthealth.ai/blog/sully-ai), [Sully.ai](https://www.sully.ai/), [Crunchbase](https://www.crunchbase.com/organization/sully-ai).

### Phreesia
- **New features:** AI-driven copay selection (specialty/visit-type/payer/OOP-max aware). Sub-minute automated eligibility & benefits checks. **VoiceAI** — HIPAA-compliant chat/voice in 20+ languages. New-patient intake automation: AI sends the packet via Epic, ingests responses, requests records from prior providers via HIE/fax, verifies insurance, pre-populates the chart.
- **Scale:** ~180M visits powered in 2026.
- **Read:** Phreesia's VoiceAI **now also does 20+ languages**, eroding the raw "language count" portion of Solace's intake wedge. Solace's remaining intake edge is the *combination*: 20-language intake + SHAP-explained ESI + conformal triage + no-code protocol authoring — not language count alone.
- Sources: [Phreesia eligibility](https://www.phreesia.com/products/eligibility-verification/), [Phreesia registration](https://www.phreesia.com/products/registration/).

---

## 3. Capabilities competitors ship that Solace lacks today

Ranked by how broadly the gap is now table stakes:

| Gap | Who ships it | Solace status | Severity |
|---|---|---|---|
| **Ambient scribe (any)** | All 11 competitors now | None (roadmap #1) | Critical — this is the entry ticket |
| **Differential diagnosis inside the encounter** | Glass, OpenEvidence, Epic (Diagnosis Advisor previewed) | Triage-only | High — Glass shipped exactly Solace's planned #11 |
| **Coding (E&M, ICD-10, CPT) inline** | Suki, Dragon Copilot, OpenEvidence, Heidi, Freed, Sully | None | High — now free in Freed/OpenEvidence |
| **Real-time prior authorization** | Abridge (Availity), OpenEvidence (Tandem), Notable | None | High — payer-connected PA is a 2026 defining feature |
| **Citation-backed CDS / evidence engine** | OpenEvidence, Glass, Heidi Evidence, Freed | None | High — and a trust-positioning battleground |
| **Patient communications agent (calls/reminders/follow-up)** | Heidi Comms, OpenEvidence Dialer, Notable, Freed Front Desk, Sully | None | Medium |
| **Nursing / bedside flowsheet documentation** | Abridge, Dragon Copilot, Nabla | None | Medium — large untapped clinician population |
| **Ambient order staging (speak the plan → staged orders)** | Suki, Epic Art | None | Medium |
| **Partner/agent marketplace + composable agents** | Dragon Copilot, Epic Agent Factory, Sully SuperAgent | No-code workflow builder (related, not the same) | Medium |
| **MEDITECH / long-tail EHR ambient write** | Suki (MEDITECH Expanse, MEDENT, Azalea, WellSky) | Read-only FHIR | Medium — this is Solace's *intended* breadth wedge, already contested |
| **Referral leakage / closed-loop referral agents** | Notable, Phreesia Referral Hub | None | Low–Medium |

**The hard truth:** the four-quadrant table in `roadmap-50-features.md` ("no single competitor ships the full stack") is now stale. Glass, OpenEvidence, and Heidi each ship scribe + Ddx/CDS + coding. The white space is no longer "the full stack" — it is specific quality and trust attributes within the stack.

---

## 4. White space — what *no one* fills well

These are the genuinely defensible openings as of May 2026:

1. **Calibrated, conformal, auditable clinical AI.** Not one competitor publishes a model card, calibration plot, conformal coverage guarantee, or bias audit per output. OpenEvidence is ad-funded with no transparency; Epic's ESM history is a liability; the scribes publish nothing. Solace already has calibrated LightGBM ESI + conformal prediction sets + SHAP. This is the single most defensible white space and it maps to the **AI governance** wedge.

2. **The non-Epic, non-enterprise long tail with a *governed* product.** Suki is winning the long-tail EHRs (MEDENT, Azalea, WellSky) but with an enterprise-priced, validation-via-KLAS product. FQHCs, safety-net systems, rural and community practices on eClinicalWorks/athenahealth/MEDITECH/OpenEMR want a scribe + intake + governance story at Medicaid economics. Epic AI Charting structurally cannot serve them; Notable is enterprise-only; OpenEvidence/Heidi are English-dominant. **20-language intake + conformal triage + audit trail at $79–129/clinician is unoccupied.**

3. **Provider-side prior authorization that is *integrated with the scribe and governed*.** Abridge (Availity) and OpenEvidence (Tandem) are bolting PA on via partnerships; Notable is RCM-side. Nobody ships a PA packet generator that (a) assembles from the ambient note automatically, (b) routes via Da Vinci PAS FHIR for CMS-0057-F payers, and (c) logs every AI-assembled element with Provenance for audit. CMS-0057-F + the March 31 2026 first PA performance metrics make this timely.

4. **Loop-closure on abnormal results and refills.** 7–15% of abnormal results are never communicated to patients — a malpractice gap. No competitor owns abnormal-result detection → plain-language patient message → one-click clinician send, end to end. Same for protocol-driven refill triage.

5. **Bring-your-own-protocol authoring with version control and audit.** Epic's Agent Factory will let *Epic* customers build agents. Notable's Flow Builder is enterprise low-code. Nobody offers a health system the ability to author, version, and audit *their own* triage/intake protocols with SHAP-explained outputs and Joint-Commission-ready audit trails, EHR-agnostic. This is Solace's no-code builder repositioned as a governed protocol platform.

6. **Multi-encounter / rounds / huddle capture.** Still pen-and-paper everywhere. Minor white space but genuine.

---

## 5. Prioritized feature recommendations (laddered to the four wedges)

Each recommendation names the wedge it serves, the competitor gap it closes, the effort, and where it sits in the existing roadmap waves. Ordered by priority.

### P1 — Ship now, existential

**R1. Ambient scribe MVP with Linked Evidence (HealthScribe).** *Wedge: ambient scribe quality.* Roadmap #1, #2, #9, #10. Non-negotiable entry ticket — all 11 competitors ship this. Without it Solace cannot be demoed as a doctor's pal. Effort: M. **This is the gating dependency for R2–R5.**

**R2. Conformal differential diagnosis inside the encounter.** *Wedge: AI governance + ambient quality.* Roadmap #11–#13. Glass and OpenEvidence shipped encounter-Ddx; Epic previewed Diagnosis Advisor. Solace's *only* defensible version is the calibrated/conformal one: output a 90/95% prediction set with per-diagnosis supporting/refuting evidence and a "don't-miss" red-flag check — none of them ship calibrated uncertainty. Do not ship a bare top-5 list; that is already commoditized. Effort: M.

**R3. Inline coding: E&M + ICD-10 + CPT with the rubric shown.** *Wedge: doctor admin pain.* Roadmap #41, #42. Now free in Freed and OpenEvidence — it is table stakes, not a differentiator, but its *absence* is disqualifying. Differentiate by showing the 2021/2023 MDM rubric and the documentation evidence behind each suggestion (auditability). Effort: M.

**R4. Public "Solace Trust Report" — model card + calibration plot + conformal coverage + bias audit.** *Wedge: AI governance.* Roadmap #50. This is the highest-leverage *cheap* move: it is mostly writing and templating, it directly attacks OpenEvidence's ad-funded opacity and Epic's ESM history, and it converts Solace's existing calibrated ML into a procurement weapon. Ship a public page within 90 days. Effort: M (process-heavy, low code).

**R5. Provenance + override log on every AI write and suggestion.** *Wedge: AI governance + EHR breadth.* Roadmap #29. Every Solace-authored note/code/suggestion carries a `Provenance` resource ("Solace AI vX, model Y, clinician Z signed at T") and an override log (AI suggestion vs clinician decision, per user). Required for HTI-1 DSI transparency; no competitor publishes this. Cheap, and it compounds R4. Effort: S.

### P2 — Next, breadth and admin

**R6. DocumentReference write across Epic, Oracle, athenahealth, MEDITECH + HL7 v2 MDM emitter.** *Wedge: EHR breadth.* Roadmap #22, #30. Suki already owns MEDITECH Expanse + the long tail; Solace must at least match the most reliable cross-vendor write target and the MDM^T02 path for community hospitals on Mirth/Rhapsody. Without write-back, "writes to your EHR" is not claimable. Effort: M.

**R7. Provider-side prior authorization packet generator with Da Vinci PAS routing.** *Wedge: doctor admin pain + AI governance.* Roadmap #36. Auto-assemble the PA submission from the ambient note + order; route via Da Vinci PAS FHIR for CMS-0057-F payers, Surescripts CompletEPA for meds, portal-RPA fallback for legacy; log every assembled element with Provenance. Abridge/OpenEvidence are doing PA via partnerships — Solace's integrated + governed version is differentiated. Effort: XL; start the partnership/sandbox work now even though code lands later.

**R8. Abnormal-result + refill loop-closure agents.** *Wedge: doctor admin pain.* Roadmap #33, #34. Genuine white space — nobody owns abnormal-result detection → plain-language patient message → one-click send, or protocol-driven refill triage with audit log. High malpractice-relevance, strong demo. Effort: M.

**R9. 20-language post-encounter patient package + lightweight patient comms.** *Wedge: ambient quality + admin pain.* Roadmap #35; partial answer to Heidi Comms / OpenEvidence Dialer. Solace already does 20-language intake — extend to multi-language discharge instructions, care plan, and result messages over SMS. Do *not* try to out-build Heidi Comms' full call-handling agent yet; ship the language-advantaged subset. Effort: S–M. Note: Dragon Copilot's 58 languages and Phreesia VoiceAI's 20+ mean Solace must reframe the wedge as "20-language *intake + triage + discharge* with SHAP," not language count alone.

### P3 — Differentiating, sequence after P1/P2

**R10. Bring-your-own-protocol authoring platform (governed workflow builder + CDS Hooks).** *Wedge: AI governance + admin pain.* Market-update opportunity C; roadmap #28. Reposition the existing no-code workflow builder as a *protocol authoring + execution + audit* platform: any health system encodes, versions, and audits its own triage/intake protocols, SHAP-explained, EHR-agnostic via CDS Hooks. Pre-empts Epic Agent Factory (Epic-only) and Notable Flow Builder (enterprise). Effort: M.

**R11. Citation-grounded evidence engine — ad-free by design.** *Wedge: ambient quality + AI governance.* Roadmap #20. RAG over open-license sources (PubMed Central OA, CDC, NIH, NICE, Cochrane abstracts) with primary-source citations. Differentiator vs OpenEvidence is explicit and marketable: **ad-free, no pharma CPMs** — the same wedge Heidi Evidence used. Lower priority because it is an L-effort build and Heidi/Glass/Freed already cover the basic need; ship after the scribe + Ddx + coding core. Effort: L.

**R12. Nursing / bedside ambient capture.** *Wedge: ambient quality.* Roadmap #5 (huddle mode is adjacent). Abridge, Dragon Copilot, and Nabla all moved into nursing documentation — a large clinician population the scribes are racing for. Lower priority for Solace because it needs flowsheet-structured output and bedside UX work; revisit once the physician scribe is proven. Effort: L.

---

## 6. Summary: how the wedges hold up

- **Ambient scribe quality** — *contested but defensible.* Cannot win on existence (commoditized) or raw speed; win on Linked Evidence + conformal Ddx + offline/mobile capture. R1, R2.
- **EHR breadth** — *contested by Suki, time-sensitive.* Suki is actively taking the long-tail EHRs. Solace must ship write-back + HL7 v2 fast or this wedge erodes. R6.
- **Doctor admin pain** — *partially open.* Coding is now table stakes (R3); the real white space is loop-closure (R8) and governed provider-side PA (R7). Notable is the threat.
- **AI governance** — *wide open and the strongest moat.* No competitor publishes calibration, conformal coverage, bias audits, or per-write provenance. This is the cheapest and most defensible wedge. R4, R5, and the governance framing on R2/R7/R10 are the heart of Solace's differentiation in May 2026.

**Strategic one-liner:** the "full-stack doctor's pal" is no longer empty space — Solace now wins by being the **only governed, calibrated, conformal doctor's pal for the non-Epic majority of US healthcare**, priced for FQHC and SMB economics.

---

## Sources

- Epic AI roadmap / Diagnosis Advisor / Agent Factory: [Fierce Healthcare HIMSS26](https://www.fiercehealthcare.com/ai-and-machine-learning/himss26-epic-expands-ai-roadmap-previews-factory-build-and-orchestrate-ai), [Healthcare IT News](https://www.healthcareitnews.com/news/epic-unveils-ai-agents-showcases-new-foundational-models), [Healthcare IT Today](https://www.healthcareittoday.com/2026/02/05/epic-ambient-ai-charting-released-and-more-updates-on-epics-ai-solutions/), [STAT](https://www.statnews.com/2026/02/04/epic-ai-charting-ambient-scribe-abridge-microsoft/).
- Abridge: [Fierce Healthcare JPM26](https://www.fiercehealthcare.com/ai-and-machine-learning/jpm26-abridge-teams-availity-scale-real-time-prior-authorization), [Becker's](https://www.beckershospitalreview.com/healthcare-information-technology/digital-health/abridge-availity-team-up-on-real-time-prior-authorization/), [Sacra](https://sacra.com/c/abridge/), [Abridge press](https://www.abridge.com/press-release/highmark-health-ahn-abridge-prior-authorization), [DeepCura](https://www.deepcura.com/resources/abridge-ai-review).
- Dragon Copilot: [HIT Consultant](https://hitconsultant.net/2026/03/05/microsoft-dragon-copilot-himss-2026-agentic-clinical-ai-nurses-radiologists/), [Fierce Healthcare](https://www.fiercehealthcare.com/ai-and-machine-learning/microsoft-debuts-dragon-copilot-ai-clinical-assistant-nurses-expands-access), [TechTarget](https://www.techtarget.com/searchhealthit/news/366639820/Microsoft-makes-upgrades-to-clinical-AI-assistant).
- Suki: [DeepCura](https://www.deepcura.com/resources/suki-ai-review), [Suki EHR integrations](https://www.suki.ai/ehr-integrations/), [Fierce Healthcare WellSky](https://www.fiercehealthcare.com/ai-and-machine-learning/suki-inks-partnership-wellsky-integrate-ambient-ai-specialty-care-ehr), [Healos](https://www.healos.ai/blog/suki-pricing-features-cost-and-the-best-alternatives-in-2025).
- Notable: [PRNewswire Inova](https://www.prnewswire.com/news-releases/inova-health-partners-with-notable-to-support-system-wide-ai-and-digital-transformation-strategy-302654419.html), [HLTH](https://hlth.com/insights/news/inova-health-taps-notable-to-utilize-intelligent-ai-agents-2026-01-12).
- Glass Health: [Glass features](https://glass.health/features), [Glass ambient CDS](https://glass.health/ambient-cds), [Glass EHR integration](https://glass.health/ehr-integration).
- OpenEvidence: [Sacra](https://sacra.com/c/openevidence/), [HIT Consultant Mount Sinai](https://hitconsultant.net/2026/04/01/mount-sinai-openevidence-ai-epic-integration-nurses-pharmacists/), [Becker's](https://www.beckershospitalreview.com/healthcare-information-technology/ai/mount-sinai-inks-1st-enterprise-deal-with-openevidence/), [ainvest](https://www.ainvest.com/news/openevidence-ai-platform-infrastructure-powering-40-physicians-daily-clinical-workflows-2604/).
- Heidi: [Vero](https://www.veroscribe.com/blog/heidi-health-review-2026), [DeepCura](https://www.deepcura.com/resources/heidi-health-review), [All Health Tech](https://allhealthtech.com/heidi-launches-evidence/), [Heidi pricing](https://www.heidihealth.com/en-us/pricing).
- Freed: [Freed best AI scribes](https://www.getfreed.ai/resources/best-ai-scribes), [Freed pricing](https://www.getfreed.ai/pricing), [DeepCura](https://www.deepcura.com/resources/freed-ai-review).
- Nabla: [Fierce Healthcare Navina](https://www.fiercehealthcare.com/health-tech/navina-and-nabla-unveil-partnership-integrate-clinical-copilot-ambient-ai), [Fierce Healthcare Kaiser](https://www.fiercehealthcare.com/health-tech/medical-scribe-startup-nabla-rollout-tool-kaiser-permanente-docs), [SaaSworthy](https://www.saasworthy.com/product/nabla/pricing).
- Sully.ai: [Insight Health](https://www.insighthealth.ai/blog/sully-ai), [Sully.ai](https://www.sully.ai/), [Crunchbase](https://www.crunchbase.com/organization/sully-ai).
- Phreesia: [Phreesia eligibility](https://www.phreesia.com/products/eligibility-verification/), [Phreesia registration](https://www.phreesia.com/products/registration/).
</content>
</invoke>
