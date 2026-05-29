# Solace — Healthcare Regulatory Research Brief

**Date:** May 16, 2026
**Prepared by:** Solace Engineering — regulatory research pass
**Scope:** CMS-0057-F prior auth, ONC HTI-1/HTI-2/HTI-5 and predictive-DSI transparency, FDA clinical-AI/CDS stance, TEFCA/QHIN, HIPAA Security Rule NPRM and LLM-vendor BAA requirements
**Status:** Current as of May 2026. All claims cited to primary or near-primary sources.

---

## 0. Executive summary — what changed and what it means for Solace

The regulatory ground shifted materially in the four months before this brief, almost all of it in a **deregulatory** direction. Three things matter most:

1. **The roadmap is wrong about CMS-0057-F timing.** The roadmap (`roadmap-50-features.md`, lines 5 and 77) claims the FHIR Prior Auth APIs "went live January 1" 2026 and that the Da Vinci PAS API is "live Jan 2026." This is incorrect. Only the *operational* PA requirements (shorter decision timeframes, denial-reason specificity, metric reporting) took effect January 1, 2026. The **four FHIR APIs — including the Prior Authorization API built on Da Vinci PAS — are not required until January 1, 2027.** As of late 2025 only ~9% of payers reported they could support the ePA API by the 2027 deadline. The PA wedge is real but the rails will be sparse through 2026; plan for a multi-year payer-coverage ramp, not a 2026 switch-on.

2. **Predictive-DSI transparency ("AI model card") rules are being repealed, not expanded.** HTI-1's § 170.315(b)(11) source-attribute requirements for predictive DSIs — the thing the roadmap leans on for feature #29 and #50 — are slated for elimination under the HTI-5 proposed rule (Dec 29, 2025; comment period closed Feb 27, 2026). ASTP/ONC withdrew the non-finalized HTI-2 proposals entirely. The regulatory *mandate* for model cards is weakening. This does not kill feature #50; it converts it from a compliance checkbox into a **voluntary trust differentiator** — which is arguably a stronger competitive position.

3. **FDA gave clinical AI a friendlier CDS guidance in January 2026**, including a new enforcement-discretion path for single-recommendation CDS. The non-device carve-out is more usable than it was under the 2022 guidance, but generative-AI/LLM-based recommendation engines remain the highest-risk category and the four non-device criteria still bind. Solace's "doctor's pal / human-in-the-loop" framing is the correct posture and should be made explicit in product copy and labeling.

The net: the compliance burden from federal AI-transparency rules is *decreasing*, the prior-auth opportunity is *delayed* (2027 not 2026), and the HIPAA Security Rule is the one area where obligations are about to get materially *heavier*.

---

## 1. CMS-0057-F — Interoperability and Prior Authorization Final Rule

### 1.1 What the rule actually requires and when

CMS-0057-F was finalized January 17, 2024. It applies to "impacted payers": Medicare Advantage organizations, state Medicaid and CHIP fee-for-service programs, Medicaid/CHIP managed care plans, and QHP issuers on the federally facilitated Exchanges. It does **not** directly regulate providers or provider-facing software vendors like Solace — but it defines the rails Solace's PA features must ride.

**Two distinct compliance dates — this is the correction the roadmap needs:**

| Effective date | Requirement |
|---|---|
| **January 1, 2026** | *Operational only.* Standard PA decisions within 7 calendar days; expedited within 72 hours. Specific denial reasons required. Payers must publicly report PA metrics (first public report due March 31, 2026, covering CY2025). **No API is required to be live on this date.** |
| **January 1, 2027** | *Technical.* All four FHIR APIs must be implemented and maintained: (1) Patient Access API enhancements, (2) Provider Access API, (3) Payer-to-Payer API, (4) **Prior Authorization API**. The PA API must expose covered items/services, identify documentation requirements, and accept/return PA requests with approve/deny/more-info responses. |

The roadmap's claim that "CMS-0057-F's FHIR Prior Auth APIs went live January 1" (line 5) and that Da Vinci PAS is "live Jan 2026" (line 77) is factually wrong and should be corrected. The window that "just opened" in 2026 is the operational-pressure window (payers under decision-speed pressure), not an API-availability window.

**Source:** CMS, *CMS Interoperability and Prior Authorization Final Rule (CMS-0057-F)* fact sheet — https://www.cms.gov/newsroom/fact-sheets/cms-interoperability-prior-authorization-final-rule-cms-0057-f ; CMS APIs and Implementation Guides page — https://www.cms.gov/priorities/burden-reduction/overview/interoperability/implementation-guides-standards/application-programming-interfaces-apis-relevant-standards-implementation-guides-igs

### 1.2 Da Vinci IGs and the X12 278 enforcement discretion

The rule names but does not strictly *mandate* the Da Vinci implementation guides — CRD (Coverage Requirements Discovery), DTR (Documentation Templates and Rules), and PAS (Prior Authorization Support). CMS "points to" them as the preferred path. The PA API requirement is outcome-defined; Da Vinci is the de facto standard to meet it.

Separately, on **February 28, 2024** HHS's National Standards Group announced **enforcement discretion** allowing HIPAA covered entities to use an all-FHIR PA workflow (Da Vinci PAS) in place of the mandated X12 278 transaction. This matters for Solace: it means a FHIR-native PA submission path (roadmap feature #36) is legally clean and does not have to also produce an X12 278.

**Source:** Da Vinci PAS IG v2.1.0 — https://hl7.org/fhir/us/davinci-pas/STU2.1/ ; CMS APIs/IGs page (above).

### 1.3 Implications for Solace

- **Compliance must-do:** None *directly* — Solace is not an impacted payer. But the **Provenance** discipline (feature #29) and FHIR R4 + SMART-on-FHIR + OAuth2/OIDC stack are the correct technical bets regardless.
- **Competitive opening (real, but timed):** Provider-side PA assembly (#36) is genuine white space — Cohere, Rhyme, and Availity sit on the payer side. But because payer PA APIs are sparse until 2027, the *defensible MVP* in 2026 is the **packet generator + Surescripts CompletEPA for drugs + portal/RPA fallback for legacy payers**, with the Da Vinci PAS FHIR path wired as a per-payer capability that lights up as payers go live. Pitch it as "PA-ready," not "PA-automated across all payers today."
- **Landmine:** Do not market Solace as "CMS-0057-F compliant." The rule does not apply to Solace. Marketing a provider tool as compliant with a payer rule invites procurement-team skepticism and is technically false.

---

## 2. ONC / ASTP — HTI-1, HTI-2, HTI-5 and predictive-DSI transparency

### 2.1 The deregulatory pivot

ASTP/ONC (the renamed ONC) made a sharp deregulatory turn at the end of 2025:

- **HTI-2 non-finalized proposals withdrawn**, effective December 29, 2025.
- **HTI-5 Proposed Rule** issued December 29, 2025; 60-day comment period closed February 27, 2026. Final rule pending as of May 2026.

**Source:** Federal Register, *HTI: Patient Engagement... Withdrawal* (Dec 29, 2025) — https://www.federalregister.gov/documents/2025/12/29/2025-23890/health-data-technology-and-interoperability-patient-engagement-information-sharing-and-public-health ; ASTP/ONC HTI-5 fact sheet — https://www.healthit.gov/topic/laws-regulation-and-policy/hti-5-proposed-rule-fact-sheet

### 2.2 Predictive DSI transparency — the "AI model card" requirement is being repealed

HTI-1 (finalized 2024) added § 170.315(b)(11), the **Decision Support Intervention** certification criterion. For **predictive DSIs** (AI/ML-driven, including generative models) supplied as part of *certified health IT*, developers must today expose 31 "source attributes" — intended use, target population, end users, known risks, training-data nature, external-validation processes, fairness/bias approach, etc. This is the de facto federal "AI model card."

**HTI-5 proposes to eliminate this entirely** — both the source-attribute disclosure requirement *and* the associated intervention risk-management practices (IRMP) for predictive DSIs. ASTP's stated rationale: in over a year of availability, it has "no publicly available evidence indicating that a single doctor, nurse, or administrator has accessed, recorded, or modified a single source attribute."

**Critical scoping point for Solace:** § 170.315(b)(11) only ever applied to DSIs *supplied as part of ONC-certified Health IT Modules*. Solace is a standalone clinical application, not (today) a certified Health IT Module. The predictive-DSI transparency mandate was **never legally binding on Solace** in the first place. HTI-5 repealing it changes Solace's *competitive context*, not its *legal obligations*.

One date still stands: Health IT Modules certified to § 170.315(b)(11) must also meet authentication/access-control/authorization criteria **on and after January 1, 2028** — relevant only if Solace later pursues ONC certification.

**Source:** Covington Digital Health, *HHS Proposes Changes... HTI-5 Proposed Rule* (Jan 2026) — https://www.covingtondigitalhealth.com/2026/01/hhs-proposes-changes-to-the-health-it-certification-program-and-information-blocking-regulations-in-hti-5-proposed-rule/ ; Holland & Knight, *ASTP/ONC's Year-End Moves* (Jan 2026) — https://www.hklaw.com/en/insights/publications/2026/01/astp-oncs-year-end-moves-mark-a-strategic-pivot

### 2.3 Implications for Solace

- **Roadmap features #29 (Provenance) and #50 (model card / bias audit / override log) are NOT compliance-mandated.** The roadmap's framing — #29 "required for HTI-1 DSI transparency" (line 67) and #50 "per CMS guidance and HTI-1 DSI transparency" (line 103) — overstates the regulatory hook. With HTI-5, that hook is being removed, and it never bound a non-certified product anyway.
- **This is a feature, not a bug, for Solace's strategy.** Build #50 *anyway*, and reposition it: voluntary transparency that the federal government just declared too burdensome for certified vendors becomes a genuine procurement differentiator when a hospital's risk/compliance committee is still — post-Epic-Sepsis-Model — asking every AI vendor for exactly these artifacts. The market demand for model cards and bias audits is driven by **hospital procurement and malpractice-risk committees**, not by a federal mandate, and that demand did not go away. Sell it as "we publish what the rule no longer makes anyone publish."
- **Landmine:** Do not cite HTI-1 § 170.315(b)(11) as a *requirement Solace meets* in sales material. It does not apply, and a competitor's compliance counsel will catch it. Frame transparency artifacts as voluntary best practice aligned with NIST AI RMF and the (now-withdrawn) intent of the DSI criterion.
- **Information blocking still applies.** HTI-5 refines but does not repeal the information-blocking regulations. Any Solace feature that touches data exchange (EHR write-back, referral generation, fax ingestion) must not itself become an information-blocking practice — e.g., do not lock a hospital's data inside Solace in a way that impedes access, exchange, or use.

---

## 3. FDA — Clinical AI and Clinical Decision Support

### 3.1 The January 2026 revised CDS guidance

On **January 6, 2026**, FDA's CDRH issued revised final guidance, *Clinical Decision Support Software*, superseding the September 2022 guidance. (A related Town Hall and a "Final Guidance March 11, 2026" media posting accompanied it.) The revision is broadly *deregulatory* — FDA framed it as "cutting red tape."

**Source:** FDA, *Clinical Decision Support Software* guidance page — https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software ; Covington & Burling, *5 Key Takeaways from FDA's Revised CDS Software Guidance* (Jan 2026) — https://www.cov.com/en/news-and-insights/insights/2026/01/5-key-takeaways-from-fdas-revised-clinical-decision-support-cds-software-guidance ; Faegre Drinker, *Key Updates in FDA's 2026 General Wellness and CDS Software Guidance* — https://www.faegredrinker.com/en/insights/publications/2026/1/key-updates-in-fdas-2026-general-wellness-and-clinical-decision-support-software-guidance

### 3.2 The four non-device CDS criteria (still binding)

To be **non-device CDS** (outside FDA medical-device regulation) under section 520(o)(1)(E) of the FD&C Act, software must meet **all four**:

1. **Not** intended to acquire, process, or analyze a medical image, signal from an in-vitro diagnostic, or a pattern/signal from a signal-acquisition system.
2. Intended to display, analyze, or print medical information about a patient or other medical information (e.g., guidelines, peer-reviewed literature).
3. Intended to **support or provide recommendations** to a healthcare professional — *not* to replace or direct the HCP's judgment.
4. Intended to enable the HCP to **independently review the basis** for the recommendation, so the HCP does not rely *primarily* on the software for a diagnosis or treatment decision.

Criterion 4 is the human-in-the-loop core. The 2026 guidance puts heavy new emphasis on **usability**: the basis must be presented in a way that prioritizes decision-relevant detail and avoids information overload — a recommendation buried in an unreadable evidence dump fails Criterion 4.

### 3.3 The new single-recommendation enforcement discretion

Under the 2022 guidance, software that emitted a **single** recommendation generally failed Criterion 3 (it "directs" rather than "supports") and was a device. The 2026 guidance softens this: FDA will now **exercise enforcement discretion** for single-recommendation CDS *when only one option is clinically appropriate* and all other non-device criteria (meaningful practitioner review, transparency) are met. FDA still expects a list of clinically appropriate outputs — it simply accepts that a correct list may legitimately contain only one item.

If a system shows one recommendation but other appropriate options exist, it still fails Criterion 3 and is a regulated device.

### 3.4 Where Solace features land

| Solace feature | FDA posture | Notes |
|---|---|---|
| Ambient scribe / note generation (#1–10) | Non-device | Transcription and documentation; not a recommendation. Lowest risk. |
| Ranked differential diagnosis (#11) | **Non-device only if Criterion 4 holds.** | A *ranked list* with per-diagnosis supporting/refuting reasoning and clickable evidence is the textbook non-device design. The reasoning *is* the "independent review basis." Conformal sets (#12) reinforce this — they show uncertainty rather than asserting a single answer. |
| Triage / ESI level (#existing) | **Higher scrutiny.** | Acuity scoring that drives disposition can look device-like. Keep it advisory, show the basis, require clinician confirmation. |
| Sepsis early-warning, deterioration index (#17, #18) | **Likely device territory.** | Predictive risk scores that analyze patterns from physiological signals can implicate Criterion 1 and Criterion 3. The Epic Sepsis Model is a 510(k)-adjacent cautionary tale. Treat #17/#18 as candidates for a regulatory pathway, not as casual non-device features. |
| Drug-interaction / dosing checks (#19) | Non-device (reference). | Established non-device category — displaying known interaction data. |
| CDS calculator auto-population (#15) | Non-device. | Wells/HEART/etc. are validated published rules; auto-extraction + display is documentation, not new analysis. |
| Inbox auto-draft, refill triage, abnormal-result comms (#32–34) | Non-device **if** clinician reviews before send. | The human-in-loop send step is load-bearing. Auto-send would change the analysis. |

### 3.5 The generative-AI caveat

Industry counsel (Faegre Drinker, Nixon Law Group, the FDA Law Blog) all flag that **LLM/generative-AI CDS is the highest-risk slice** of the non-device space. A generative model that synthesizes a novel recommendation, can hallucinate, and cannot fully expose its "basis" strains Criterion 4. Solace's evidence-grounded recommendation engine (#20) and Ddx reasoning (#11) must be architected so the *cited primary sources are the reviewable basis* — RAG with visible citations is not just a quality feature, it is the FDA Criterion-4 compliance mechanism.

### 3.6 Implications for Solace

- **Compliance must-do:** Adopt an explicit, documented **non-device CDS posture** for each AI feature. Maintain an internal "CDS criteria mapping" doc (one row per AI feature, showing how all four criteria are met). This is cheap, and it is the artifact FDA or a hospital compliance officer will ask for.
- **Compliance must-do:** Every recommendation surface must show its **basis** (supporting evidence, transcript timestamps, cited guidelines) and require an explicit clinician action before anything is finalized or sent. Make "the clinician is in the loop" a hard architectural invariant, not a UX preference.
- **Landmine:** Sepsis/deterioration scoring (#17, #18) should not ship under the same "non-device CDS" assumption as the scribe. Get regulatory counsel before building these. They are the single biggest FDA exposure in the 50-feature roadmap.
- **Opening:** The relaxed single-recommendation discretion makes features like refill auto-classification (#33) and abnormal-result drafting (#34) cleaner to ship — when the protocol genuinely yields one appropriate action, a single recommendation is now defensible.

---

## 4. TEFCA / QHIN

### 4.1 Status

TEFCA is operational and growing. As of early 2026 **eleven QHINs** are designated (more than double the count at TEFCA go-live in late 2023). Oracle Health Information Network was designated in November 2025 (the 11th). The RCE (The Sequoia Project) continues to designate QHINs on a rolling basis. HTI-2's *finalized* portions codified QHIN requirements, governance, and appeal rights into regulation.

**Source:** The Sequoia Project RCE, *Designated QHINs* — https://rce.sequoiaproject.org/designated-qhins/ ; Oracle, *Oracle Health Secures TEFCA QHIN Designation* (Nov 20, 2025) — https://www.oracle.com/news/announcement/oracle-health-secures-tefca-qhin-designation-2025-11-20/ ; HIMSS, *HTI-2 Final Rule Fact Sheet: TEFCA and QHIN Designations* — https://www.himss.org/resources/hti-2-final-rule-fact-sheet-tefca-and-qhin-designations-governance-and-appeal-rights/

### 4.2 Implications for Solace

- Solace does not need to *become* a QHIN. The realistic path is to connect as a **participant or subparticipant** under an existing QHIN, or to use a connectivity vendor (e.g., Kno2, which is itself a QHIN and resells TEFCA access to EHR vendors like RXNT).
- **Opening:** TEFCA query exchange is a cheaper way to pull a patient's outside records (prior notes, problem lists, meds) than negotiating per-EHR FHIR access. For a referral-letter generator (#38) or HCC recapture worklist (#43) that needs longitudinal history, a QHIN query is a strong data-acquisition layer. Not Wave 1, but the right Wave 3 architecture bet.
- **Not a near-term must-do.** TEFCA carries no compliance obligation for Solace; it is an optional connectivity opportunity.

---

## 5. HIPAA Security Rule NPRM — the one place obligations are getting heavier

### 5.1 Status

OCR published the HIPAA Security Rule NPRM in the Federal Register on **January 6, 2025** (a 60-day comment period followed; ~4,700 comments received). The NPRM is a major overhaul of the 23-year-old Security Rule — it would make many currently "addressable" specifications **mandatory** and add prescriptive controls.

A **May 2026** final-rule target appears on OCR's regulatory agenda, **but OCR has not confirmed it**. A 2026 finalization is possible but not guaranteed; industry groups have pushed back hard on cost and feasibility. If finalized, covered entities and business associates get **240 days from publication** to comply.

**Source:** HIPAA Journal, *Final Rule Implementing HIPAA Security Rule Updates Edges Closer* — https://www.hipaajournal.com/final-rule-implementing-hipaa-security-rule-updates-edges-closer/ ; BankInfoSecurity, *What's Next for the Proposed HIPAA Security Rule Overhaul?* — https://www.bankinfosecurity.com/whats-next-for-proposed-hipaa-security-rule-overhaul-a-31692

### 5.2 What the NPRM would add (high-confidence items from the proposal)

The NPRM removes the "addressable vs. required" distinction (most controls become required) and adds prescriptive obligations including:

- **Mandatory encryption** of ePHI at rest and in transit (few exceptions).
- **Mandatory MFA** for systems accessing ePHI.
- **Network segmentation** requirements.
- **Annual** technical control verification and **compliance audits**.
- **Asset inventory and network map**, updated at least every 12 months.
- **Vulnerability scanning every 6 months** and **penetration testing every 12 months**.
- **Written incident response and contingency plans** with **72-hour** restoration targets for critical systems.
- **Business associates must verify** — via written analysis and certification by a subject-matter expert — the adequacy of their safeguards, and notify covered entities within **24 hours** of activating contingency plans.

### 5.3 Gap analysis vs. Solace's current HIPAA package

Solace's `HIPAA_COMPLIANCE_DUE_DILIGENCE.md` is already strong and largely ahead of the NPRM. Encryption (CMK/AES-256), MFA for AWS access, audit logging, PITR, and an incident-response plan are all in place. Remaining gaps relative to the NPRM:

| NPRM requirement | Solace status | Action |
|---|---|---|
| Encryption at rest + in transit, mandatory | Met (CMK + TLS 1.2+) | None |
| MFA for ePHI-system access | Met for AWS console; clinician app uses bcrypt PIN + JWT | **Gap:** clinician *application* login is single-factor. NPRM would require MFA for systems accessing ePHI. Add MFA (TOTP or SMART-on-FHIR-mediated) to clinician login. |
| Asset inventory + network map, ≤12-month refresh | Partial — data inventory exists; no formal network map | Produce and date a network diagram; commit to annual refresh. |
| Vulnerability scan every 6 months | Dependabot/Snyk run continuously; no scheduled infra scan | Schedule semi-annual infra vulnerability scans; document. |
| Penetration test every 12 months | Planned (REM-007, "60 days after first BAA") | Move to a fixed annual cadence; first test before NPRM compliance window. |
| 72-hour critical-system restoration | RTO < 1 hour claimed | Met; document the test evidence (REM-009). |
| BA written certification of safeguards by SME | Due-diligence package exists; no SME attestation | Have a qualified third party (or named SME) attest to the safeguard analysis. |
| 24-hour contingency-activation notice to covered entity | BAA says 30-day breach notice | **Gap:** add a 24-hour contingency-activation notification clause to the BAA template, distinct from breach notice. |

### 5.4 LLM-vendor / subprocessor BAA requirements

The 2026 standard for "HIPAA-compliant AI" — per industry counsel and vendor documentation — is no longer "encryption + a signed BAA." It now requires, and procurement teams now ask for:

1. **A signed BAA with every subprocessor that touches PHI**, named explicitly. Solace's chain runs: covered entity → Solace → AWS (Bedrock/Transcribe/Polly/etc.). The AWS BAA covers the HIPAA-eligible AWS services. **Solace must verify HealthScribe is HIPAA-eligible and BAA-covered before the Wave-1 ambient-scribe MVP touches real PHI** — the roadmap's own open question #2 flags this; it is a hard gate.
2. **Ephemeral processing / zero data retention** at the model layer. Bedrock provides this (no retention, no training on inputs). Direct OpenAI/Anthropic API use is permissible *only with a signed BAA* — OpenAI's free tier explicitly has no BAA and must never see PHI; Anthropic signs BAAs per-use-case after review. Solace's fallback providers (OpenAI Whisper, ElevenLabs, Anthropic direct) are correctly disabled by default; **R-008 in the risk register stays open until each fallback has an executed BAA.**
3. **Subprocessor breach notification** — the modern expectation, and a likely NPRM requirement, is **24-hour** notification through the BA chain, tighter than the 30-day breach-report clause in Solace's current BAA template (Section 12, item 4).
4. **Patient consent + audit trail** for AI processing — Solace already gates AI processing on `consent_granted` and logs every inference call. This is ahead of most competitors.

**Source:** Aptible, *Is Claude HIPAA-Compliant? BAA, Coverage, and Gaps* — https://www.aptible.com/hipaa/claude-baa ; Twofold, *What "HIPAA-Compliant" Should Actually Mean for AI Documentation Tools in 2026* — https://www.trytwofold.com/blog/what-hipaa-compliant-means-for-tools-in-2026 ; AWS, *HIPAA compliance for generative AI solutions on AWS* — https://aws.amazon.com/blogs/industries/hipaa-compliance-for-generative-ai-solutions-on-aws/

### 5.5 Implications for Solace

- **Compliance must-do:** Add MFA to clinician application login. This is the clearest concrete gap against the NPRM and is also straightforwardly good security.
- **Compliance must-do:** Update the BAA template to add a **24-hour contingency-activation / incident notification** clause and align subprocessor-breach timing to 24 hours.
- **Compliance must-do:** Verify AWS HealthScribe HIPAA eligibility and BAA coverage **before** any real-PHI scribe pipeline. Until then, Wave 1 must use synthetic transcripts / a non-PHI dev bucket (the roadmap's own caveat).
- **Watch item:** Track the HIPAA Security Rule final rule. If it publishes in 2026, the 240-day clock starts. Solace is well-positioned but should not assume the May 2026 target slips.

---

## 6. Consolidated guidance

### 6.1 Top compliance must-dos

1. **Verify AWS HealthScribe (and every AI subprocessor) is HIPAA-eligible and under the AWS BAA before any real PHI flows.** Hard gate on the Wave-1 ambient-scribe MVP; use synthetic data until confirmed. Keep risk-register R-008 open until every enabled provider has an executed BAA.
2. **Add MFA to clinician application login.** Current bcrypt-PIN + JWT is single-factor; the HIPAA Security Rule NPRM would require MFA for systems accessing ePHI. Closest concrete gap to a likely-2026 rule.
3. **Adopt and document an explicit non-device CDS posture per AI feature** — a "CDS criteria mapping" doc showing how each feature meets all four FDA non-device criteria, with the clinician-review step and visible "basis" as hard invariants. Treat sepsis/deterioration scoring (#17, #18) separately — likely device territory, get counsel first.
4. **Update the BAA template** for 24-hour contingency-activation / subprocessor-incident notification (current template is 30-day breach notice only), and complete the open HIPAA remediation items — designate Security/Privacy Officers (REM-001), formalize policies (REM-004), schedule the annual pen test (REM-007).
5. **Stop citing payer/certification rules as Solace obligations.** Do not market Solace as "CMS-0057-F compliant" (it regulates payers, not Solace) or as meeting "HTI-1 DSI transparency" (§ 170.315(b)(11) applies only to certified Health IT Modules, and HTI-5 proposes to repeal it). Reframe transparency artifacts (#29, #50) as voluntary best practice.

### 6.2 Top competitive openings

1. **Voluntary AI transparency as a procurement differentiator.** HTI-5 is repealing the federal predictive-DSI "model card" mandate because no clinician used it — but hospital risk and procurement committees, post-Epic-Sepsis-Model, still demand model cards, bias audits, and override logs. Build feature #50 anyway and sell it as "we publish what the rule no longer makes anyone publish." The mandate is gone; the buyer demand is not.
2. **Provider-side prior-auth, staged for the 2027 payer ramp.** PA automation white space is real (Cohere/Rhyme/Availity are payer-side), but FHIR PA APIs are not required until Jan 1, 2027 and ~9% of payers are ready. The defensible 2026 product is a PA *packet generator* + Surescripts CompletEPA for drugs + portal/RPA fallback, with Da Vinci PAS wired as a per-payer capability that lights up over 2026-2027. Pitch "PA-ready," not "PA-automated everywhere."
3. **Friendlier FDA CDS guidance lowers the bar for human-in-the-loop automation.** The Jan 2026 guidance's single-recommendation enforcement discretion makes refill triage (#33) and abnormal-result drafting (#34) cleaner to ship when a protocol genuinely yields one appropriate action. Solace's "doctor's pal" positioning is exactly the posture FDA rewards — lean into it explicitly in product copy and labeling, and use it as a wedge against competitors whose tools blur the human-in-loop line.

### 6.3 Top landmines

- Marketing Solace as compliant with rules that regulate other parties (CMS-0057-F payers; HTI-1 certified-module DSI criteria). Factually wrong and a credibility risk in front of hospital compliance counsel.
- Shipping sepsis/deterioration predictive scores (#17, #18) under the same non-device assumption as the scribe. Highest FDA exposure in the roadmap.
- Treating the ambient-scribe MVP as PHI-ready before the HealthScribe BAA coverage is confirmed.
- Assuming the HIPAA Security Rule final rule slips past 2026 — if it lands on the May 2026 agenda target, the 240-day compliance clock starts immediately.

---

## 7. Corrections applied to `roadmap-50-features.md`

The following factual errors in the roadmap were corrected as part of this research pass:

| Location | Original (incorrect) | Correction |
|---|---|---|
| Line 5 (timing paragraph) | "CMS-0057-F's FHIR Prior Auth APIs went live January 1" | FHIR Prior Auth APIs are not required until **Jan 1, 2027**; only operational PA requirements took effect Jan 1, 2026. |
| Line 77 (feature #36) | "Da Vinci PAS FHIR API (CMS-0057-F payers, live Jan 2026)" | Da Vinci PAS API required of payers by **Jan 1, 2027**, not live in 2026. |
| Line 67 (feature #29) | "required for HTI-1 DSI transparency" | HTI-1 § 170.315(b)(11) applies only to **certified Health IT Modules** (Solace is not one), and HTI-5 proposes to repeal the predictive-DSI source-attribute requirement. Provenance reframed as voluntary best practice. |
| Line 103 (feature #50) | "per CMS guidance and HTI-1 DSI transparency" | Same — reframed as voluntary; the federal mandate is being withdrawn under HTI-5. |
| Line 154 (closing) | "CMS-0057-F just turned PA into a tractable problem" | Softened — PA pressure (operational rule) is live in 2026, but the API rails arrive 2027. |

---

*Prepared for internal strategy use. Citations are to primary CMS/FDA/ASTP/Federal Register sources where available and to specialist legal/industry analysis where primary text was not directly retrievable. Re-verify the HIPAA Security Rule final-rule status and the HTI-5 final rule before relying on this brief after Q3 2026.*
