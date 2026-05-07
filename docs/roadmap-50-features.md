# Solace 50-Feature Roadmap — "The Doctor's Pal"

A synthesis of five parallel competitive research passes (ambient scribes, EHR auto-population, clinical NLP, intake competitors, physician burnout). Goal: become the only product that ships Abridge-grade ambient + Glass-grade differential + Notable-breadth automation + OpenEvidence-grade recall, on top of Solace's existing moats (calibrated ML triage, SHAP, no-code workflow builder, 20-language intake).

The 2026 timing is not accidental. CMS-0057-F's FHIR Prior Auth APIs went live January 1; HealthScribe's BAA-covered ambient pipeline is mature; Epic's Auto-Generated Reply has trained the market on AI-drafted clinician messages. The window is open.

## Competitive thesis

| Capability | Abridge | Suki | DAX | Notable | Glass | Solace today | Solace target |
|---|---|---|---|---|---|---|---|
| Ambient scribe | Best | Strong | Strong | Decent | None | None | Best |
| Differential dx | None | None | None | None | Best | Triage only | Best |
| EHR write-back | Epic-deep | Multi | Epic-deep | Multi | None | Read-only | Multi-vendor |
| Coding (E&M, ICD, HCC) | Yes | Yes | Yes | Yes | No | No | Yes |
| Prior auth automation | No | No | No | Yes | No | No | Yes |
| Inbox auto-draft | No | Limited | Yes (Epic) | Limited | No | No | Yes |
| Document/letter gen | Limited | Limited | Limited | Limited | No | No | Yes |
| Patient intake | No | No | No | Yes | No | Yes (multi-lang) | Yes |
| No-code workflow | No | No | No | Yes (Flow Builder) | No | Yes | Yes |
| Conformal uncertainty | No | No | No | No | No | Yes | Yes |
| Pricing | $200-300/mo | $199/mo | $300-600/mo | Enterprise | Free + Pro | n/a | $99-199/mo + free tier |

No single competitor ships the full stack. That is the wedge.

---

## The 50 features

Grouped by ten themes, ten features per group of five themes mostly. Each feature notes what it is, why it beats competitors, and rough implementation effort (S/M/L/XL).

### Theme A — Ambient scribe (the encounter)

1. **HealthScribe-anchored ambient capture** — browser MediaRecorder + iOS native recorder → S3 (KMS) → AWS HealthScribe job → diarized transcript + SOAP sections + evidence-linked summary. Beats: nobody outside Microsoft has BAA-clean batch + evidence linking. Effort: M.
2. **Linked Evidence audit trail** — every line of the generated note is hyperlinked to the supporting transcript timestamp; click a line, hear the patient. Beats: Abridge's signature feature, Solace matches for free using HealthScribe output. Effort: S.
3. **Per-clinician note style learning** — collect (HealthScribe draft, clinician-final) pairs and fine-tune a small Llama 3.3 8B / Meditron 8B LoRA per clinician once we have ≥300 edited pairs. Beats: DeepScribe is the only one with this; Solace adds it later but architects for it now. Effort: L (post-PMF).
4. **Specialty packs** — configurable templates for ED, primary care, cardiology, peds, psych, ortho, derm, OB/GYN, surgery, oncology. Each pack is a section schema + few-shot exemplars + specialty-aware Ddx priors. Beats: Abridge ships 50+ specialties at enterprise price; Solace ships a smaller but configurable set as part of the workflow builder. Effort: M per pack.
5. **Multi-encounter stitching + huddle mode** — concatenate related visits (same complaint, follow-ups), team-rounds capture with 3+ speaker diarization. Beats: nobody ships this well; rounds are still pen-and-paper. Effort: M.
6. **Mobile + desktop + telehealth capture** — iOS/Android background recording with lock-screen control, Apple Watch quick-capture, Zoom/Teams/Doximity SDK plugins. Beats: most competitors are desktop-first; Solace already mobile-first. Effort: L.
7. **Offline capture with later sync** — iOS recorder with deferred upload for rural ED, ambulance, ICU. Beats: nobody ships this. Effort: M.
8. **Auto-redaction of off-record segments** — VAD + LLM classifier strips small talk, side conversations, sensitive non-clinical content. Beats: clinicians cite this gap by name. Effort: M.
9. **Sub-30-second draft latency target** — for non-HealthScribe path, run streaming Deepgram Nova-3 Medical + Claude two-stage prompt to hit <30s draft. Beats: HealthScribe is batch-only; this is the speed pitch. Effort: M.
10. **Pause / resume / re-do this section** — clinician controls during/after capture; "regenerate the assessment" without re-recording. Beats: Heidi/Freed do this well; Solace matches. Effort: S.

### Theme B — Clinical reasoning (Ddx + decision support)

11. **Ranked differential diagnosis with reasoning** — extend the existing two-stage triage into a Glass-style ranked Ddx that runs on the encounter transcript. Per-diagnosis reasoning, supporting symptoms, refuting symptoms. Beats: Glass ships this standalone; Solace embeds it inside the encounter. Effort: M.
12. **Conformal prediction sets on Ddx** — output the calibrated 90%/95% set, not just a top-1. Solace already has this on triage; extend to Ddx. Beats: nobody else ships calibrated uncertainty for Ddx. Effort: S (extension of existing).
13. **"Don't-miss" red-flag surfacing** — embedded canonical lists for chest pain (ACS, PE, dissection, tamponade), stroke, sepsis, peds fever, ectopic, testicular torsion, GCA, etc. Beats: every clinician's top liability concern; nobody surfaces this proactively in the scribe stream. Effort: M.
14. **Counterfactual prompts** — "what would change this differential?" surfaces additional history/exam questions that would discriminate the top three diagnoses. Beats: research-only feature today; novel in product. Effort: M.
15. **CDS calculator auto-population** — Wells, HEART, CHA2DS2-VASc, CURB-65, PERC, NIHSS, GCS, MEWS, NEWS2, Glasgow-Blatchford, Ottawa rules, Centor, qSOFA — auto-extracted from the encounter, surfaced inline, written discrete to the note. Beats: every EHR has these as hand-jammed sidebars; Solace fills them automatically. Effort: M (each calculator is small; the harness matters).
16. **Validated PRO/screener auto-fill** — PHQ-9, GAD-7, AUDIT-C, EPDS, CRAFFT, Vanderbilt, PCL-5, fall risk, ACE, Edinburgh — auto-extracted from intake or encounter, scored, written discrete to EHR with clinician alerts on red scores. Beats: Phreesia ships 100+ of these via patient self-report; Solace adds clinician-extracted versions. Effort: M.
17. **Sepsis early-warning score (better than Epic ESM)** — externally validated MEWS+SOFA hybrid with conformal sets, transparent feature importances, and a published bias audit. Beats: Epic ESM was famously found to miss 67% of sepsis at U-Mich; this is a credibility moat. Effort: L.
18. **Deterioration index** — Rothman-style continuous score from vitals + labs + nursing notes. Beats: Epic's is paywalled and opaque. Effort: L.
19. **Drug-drug + drug-allergy + renal/hepatic dosing checks** — RxNorm + DrugBank academic for MVP, FDB or Medi-Span for production. Inline at the moment of order/prescription suggestion, not as a separate alert avalanche. Beats: every EHR has these but they fire so often they're ignored; Solace's are gated by encounter context. Effort: M (MVP), L (production-grade).
20. **Evidence-grounded recommendation engine** — RAG over PubMed Central OA + CDC + NIH guidelines + DailyMed + WHO + NICE + Cochrane abstracts (all open-license). BGE-M3 hybrid embeddings + BM25. Every recommendation cites primary source. Beats: OpenEvidence is the standalone leader; Solace embeds it in the encounter context. Effort: L.

### Theme C — EHR auto-population (the integration moat)

21. **SMART App Launch v2** — EHR-launch + standalone, PKCE, JWT backend service auth. Solace already has the foundation; harden to v2 + asymmetric client auth. Beats: most scribes are SMART v1 only. Effort: S.
22. **DocumentReference write** across Epic, Oracle Health, Athena, MEDITECH Expanse — note pushed as base64 PDF + structured text with vendor-specific note-type codes. The single most reliable cross-vendor write target. Beats: this is table stakes; nobody can claim "writes to your EHR" without it. Effort: M.
23. **Condition (problem list) write** — Epic `Condition.$add`, Oracle POST, Athena proprietary `/chart/{patientid}/problems`, single internal abstraction. Beats: only Abridge and DAX do this in Epic; Solace covers the long tail too. Effort: M.
24. **AllergyIntolerance write** across all four. Effort: S.
25. **Observation write for vitals + smoking + social history** — LOINC-coded, Epic / Oracle / Athena. Effort: S.
26. **Immunization write** — Epic / Oracle / Athena. Effort: S.
27. **MedicationStatement write for med reconciliation** — explicit "this is reconciliation, not a new prescription" framing. Effort: M.
28. **CDS Hooks service** — `patient-view`, `order-select`, `order-sign`, `encounter-discharge` — return Cards with diagnosis suggestions, drug-interaction warnings, care-gap closures, and `link.type: smart` jump to Solace. Beats: this is the only portable injection point for AI suggestions inside live EHR workflow; few startups ship it. Effort: M.
29. **Provenance resource on every write** — every Solace-authored resource gets a `Provenance` linking to "Solace AI vX, model Y, clinician Z signed at T." Beats: legal/compliance differentiator; required for HTI-1 DSI transparency. Effort: S.
30. **HL7 v2 MDM^T02 emitter** — for MEDITECH legacy, NextGen, eClinicalWorks, Allscripts, OSCAR, and the long-tail community hospitals on Mirth/Rhapsody/Corepoint engines. Beats: only Suki and DAX ship this at scale; required to win community hospitals. Effort: M.

### Theme D — Document & letter automation (the unsexy goldmine)

31. **Letter & form generator library** — FMLA (WH-380-E/F), school/sports/camp notes, work notes, return-to-activity, LMN, PA appeal, peer-to-peer prep, referral letters, disability carrier forms (Unum/Lincoln/Cigna), travel/controlled substance letters, ESA, court/competency, jury duty. EHR pull-through (demographics, dx codes, last visit summary), one-click PDF + e-fax via Documo or Concord. Beats: Doximity GPT dominates this category but doesn't touch the EHR; Solace owns the integrated path. Effort: L (each form is small; the library is the work).
32. **MyChart-style inbox auto-draft replies** — ingest inbound patient messages from Epic In-Basket / Athena patient portal / Healow / NexHealth, draft replies grounded in the chart, hand to clinician for one-click send/edit. FDA-safe under the human-in-loop carve-out. Beats: Epic's Auto-Generated Reply is Epic-only; Solace covers the non-Epic 50% of ambulatory care. Effort: L.
33. **Refill triage agent** — auto-classifies each refill request as protocol-eligible (auto-approve with audit log), needs-labs/visit (auto-draft response), or physician-decision-required. Beats: AMA cites refill protocols as highest-ROI / lowest-adopted office reform. Effort: M.
34. **Abnormal result patient communication** — auto-detect abnormal labs/imaging, draft plain-language patient message at appropriate reading level, flag clinician for one-click send. Closes the malpractice-relevant "loop closure" gap (7-15% of abnormal results never communicated). Beats: nobody owns this end-to-end. Effort: M.
35. **Discharge instructions in patient's language** — Solace already does multi-language intake; extend to multi-language post-encounter summary + care plan SMS. Beats: Phreesia patient-instruction handouts are English-first. Effort: S.
36. **Prior authorization packet generator** — given the encounter note + the order, auto-assemble the PA submission (LMN, supporting evidence, ICD-10, CPT, prior treatment history). Output goes to: (a) Da Vinci PAS FHIR API (CMS-0057-F payers, live Jan 2026), (b) Surescripts CompletEPA for meds, (c) payer portal RPA fallback for legacy. Beats: Cohere/Rhyme are payer-side; Solace is provider-side and integrated with the scribe. Effort: XL.
37. **Denial appeal letter draft** — given a denial reason, auto-draft the appeal grounded in clinical evidence + guidelines. Effort: M.
38. **Referral letters with relevant Hx + data** — given a destination specialist + reason for referral, auto-draft the letter pulling relevant labs/imaging/notes. Beats: Phreesia's Referral Hub is faxed-referral ingestion; Solace adds outbound generation. Effort: M.
39. **Inbound fax → digitization** — fax-as-a-service (Concord/Documo/eFax) + Claude/HealthScribe parsing → structured referral / record / form. Beats: Notable and Phreesia ship this at enterprise; Solace adds it for SMB. Effort: M.
40. **Patient instruction handouts** — auto-generated, plain-language, condition-specific, with red-flag return-precautions. Beats: every visit produces these by hand or template. Effort: S.

### Theme E — Coding, billing, RCM

41. **E&M level suggestion (99202–99215, 99221–99239)** — extracts MDM components from the note (problems addressed, data reviewed, risk), maps to 2021/2023 CPT guideline rubric. Top-3 ranked suggestions with supporting documentation flagged. Beats: Suki ships this at ~85-90% senior-coder agreement; Solace matches and shows the rubric. Effort: M.
42. **ICD-10 + CPT auto-suggest** — LLM candidate generation + deterministic NCCI edit + bundling validators. Top-3 with confidence; never auto-submit. Effort: M.
43. **HCC capture for Medicare Advantage** — recapture worklist surfaces undocumented HCCs from prior notes, MEAT-criteria checklist, hierarchical category logic. Beats: Notable and Apixio ship this at enterprise; major MA recapture revenue. Effort: L.
44. **Modifier suggestions (25, 59, 95)** — auto-flag when the documentation supports a modifier the coder might miss. Effort: S.
45. **Real-time eligibility (270/271)** via Stedi or Availity — surface copay, deductible remaining, OOP max, prior-auth-required flag at scheduling. Beats: Phreesia owns this; Solace makes it FOSS-pricing-tier. Effort: M.

### Theme F — Care-gap closure & population health

46. **HEDIS care-gap surfacing at encounter** — top-10 measures (BCS, CCS, COL, CDC-A1c, CBP, IMA, MAC, AWV, DEP, FUH) computed against the patient's last-12-months data, surfaced as 1-2 highest-impact gaps in the encounter sidebar. Beats: Navina is the closest analog; Solace integrates with the scribe stream. Effort: M.
47. **SDoH screener (PRAPARE / AHC HRSN / Health Leads)** with closed-loop community-resource referral via FindHelp / Unite Us API. Z-code documentation for billing. Beats: Joint Commission standard + CMS IPPS measure — RFP-mandatory. Effort: M.

### Theme G — Patient ops (intake, scheduling, payments)

48. **Insurance card OCR + 270/271 eligibility chain** — Mindee/Claude vision OCR on card photo → seed the eligibility request → parse 271 response. Beats: Phreesia and Notable do this; Solace already has card-OCR groundwork from ID-scan flow. Effort: M.
49. **No-show prediction with risk-tiered reminders** — gradient-boosted model on prior no-shows, lead time, day-of-week, weather, distance, deprivation index. Risk-tiered reminder cadence (SMS + voice for high-risk). Equity audit (Black-patient gap from prior literature). Beats: ~50% no-show reduction in primary-care AI deployments; explainability differentiator. Effort: M.

### Theme H — AI governance & safety (free competitive moat)

50. **Model card + bias audit + override log + MRM artifacts** — every Solace AI model ships with a published model card (training data, limitations, demographics), a bias audit (FNR/FPR by race/sex/age/insurance), an override log (clinician decisions vs AI suggestions, by user), and Model Risk Management documentation per CMS guidance and HTI-1 DSI transparency. Beats: nobody publishes these openly; Notable / Hyro do not. The Epic Sepsis Model controversy made this a procurement requirement post-2024. Effort: M (mostly process and writing; templates exist).

---

## Build waves

The right move is not "implement all 50 in a sprint." That produces broken work. Instead three waves, each shippable:

### Wave 1 — codeable now, no external dependencies (4-6 weeks)

1. Ambient scribe MVP using HealthScribe (#1, #2, #9, #10) — wire AWS HealthScribe API into a new `/api/{hospital_id}/scribe` route, S3 audio upload, polling, store transcript + summary on patient. Add a `ClinicianScribe` page with capture UI and Linked Evidence renderer. Already have the AWS account + IAM scaffolding.
2. Ddx engine extension (#11, #12, #13, #14) — extend `services/triage_ml.py` with a Ddx mode that runs on encounter transcripts, returns ranked diagnoses + conformal sets + red-flag check.
3. CDS calculator harness + 6 calculators (#15) — Wells, HEART, NIHSS, CURB-65, qSOFA, MEWS. Auto-extracted from transcript via Claude.
4. Validated screener auto-extraction (#16) — PHQ-9, GAD-7, AUDIT-C from transcript with red-score alerts.
5. Letter/form library v1 (#31) — 10 forms: FMLA WH-380-E, school note, work note, sports clearance, LMN, PA appeal, referral letter, ESA, travel letter, jury excuse. PDF render + Documo e-fax.
6. Discharge instructions in patient's language (#35) — extension of existing multi-lang intake.
7. E&M + ICD-10 candidate suggestion (#41, #42) on encounter notes.
8. Patient instruction handouts (#40) — auto-generated post-encounter.
9. Provenance + audit log on every AI write (#29).
10. Model card + bias audit + override log starter (#50).

### Wave 2 — needs sandbox accounts / API keys / partner work (8-12 weeks after Wave 1)

11. SMART v2 hardening (#21) + DocumentReference write to Epic/Oracle/Athena/OpenEMR (#22) — register Epic/Oracle sandboxes, run OpenEMR Docker in CI.
12. Condition / Allergy / Observation / Immunization writes (#23–#26).
13. CDS Hooks service (#28) — `patient-view`, `order-select`.
14. Real-time eligibility (270/271) via Stedi (#45, #48) — sign up for Stedi developer account.
15. Insurance card OCR (#48) — extend ID-scan service.
16. No-show prediction (#49) — needs historical scheduling data; build the model and feature pipeline.
17. HEDIS care-gap module v1 (#46) — top-5 measures.
18. SDoH PRAPARE screener (#47) with FindHelp integration.
19. Inbox auto-draft replies (#32) — start with Athena/Healow/NexHealth (Epic In-Basket needs Workshop partnership).
20. Refill triage agent (#33) and abnormal result communication (#34).
21. Specialty packs for ED + Primary Care (#4, two of them).
22. Multi-encounter / huddle mode (#5).
23. Multi-vendor coding rules engine (NCCI edits) for #42 + HCC capture worklist (#43).

### Wave 3 — needs external partnerships / regulatory / commercial (12+ weeks, mostly non-code)

24. Epic Showroom / Oracle partner / Athena Marketplace listings (#30 includes HL7 v2 MDM emitter).
25. Surescripts EPCS for prescription writes.
26. Da Vinci PAS for live FHIR PA against CMS-0057-F payers (#36).
27. FDB or Medi-Span drug-interaction license (#19 production-grade).
28. HITRUST r2 + SOC 2 Type II audit.
29. Sepsis / deterioration model external validation (#17, #18) — partner with one academic medical center.
30. Per-clinician note-style fine-tunes (#3) — gated on collecting ≥10k physician-edited pairs from Wave 1/2 deployments.

---

## What this gets us

If we ship Wave 1 cleanly we have a defensible pitch *today*: "Solace is the only product that records the visit, ranks the differential with calibrated uncertainty, fills out the FMLA form, drafts the discharge instructions in the patient's language, and suggests E&M + ICD-10 — for $99/clinician/month with a free solo-practitioner tier." That story does not exist in a single product on the market in May 2026. The window is open because (a) CMS-0057-F just turned PA into a tractable problem, (b) HealthScribe is BAA-clean and cheap, (c) Epic's Auto-Generated Reply trained the market on AI-drafted clinician communication.

Wave 2 turns Solace into a procurement contender against Notable for mid-market practices. Wave 3 lets us compete with Abridge / DAX for enterprise health systems.

---

## Open questions for the user

1. Which Wave 1 feature do you want me to start on first? My recommendation: **ambient scribe MVP (#1, #2)** — it is the single largest unlock, anchors every downstream feature, and is the credibility piece for any clinician demo.
2. AWS BAA status: is it filed yet? HealthScribe needs the BAA. Without it, Wave 1 can still ship using a non-PHI development bucket and synthetic transcripts, but production needs the BAA.
3. Do you want a free solo-practitioner tier from day one (the OpenEvidence / Heidi growth playbook), or hospital-only enterprise sales?
4. Specialty focus: pick one specialty for Wave 1 polish — ED is the existing Solace beachhead, primary care is the largest TAM, psych and peds have the highest forms-per-visit ratio. Which?
