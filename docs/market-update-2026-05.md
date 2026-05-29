# Solace Market Update — May 2026

**Generated:** 2026-05-12. Anchors against `project_solace_strategy.md` (2026-05-06). Only deltas and second-order implications below — re-read the strategy doc for baseline.

---

## 1. What's changed since 2026-05-06

### Epic AI Charting — the asteroid (Feb 5, 2026)
Epic released native ambient AI ("AI Charting," part of the **Art** AI suite) on Feb 5, 2026. Listens to encounters, drafts notes, suggests orders, accepts voice-formatting commands. Bundled inside Epic licensing — pricing not publicly disclosed but widely characterized as effectively free or near-free for Epic customers ([STAT](https://www.statnews.com/2026/02/04/epic-ai-charting-ambient-scribe-abridge-microsoft/), [HITConsultant](https://hitconsultant.net/2026/02/05/epic-releases-ai-charting-ambient-ai-market-implications/), [MedCity](https://medcitynews.com/2026/02/ambient-scribe-ai-startups-epic/)). Epic also ended its startup co-development program ([Beckers](https://www.beckershospitalreview.com/healthcare-information-technology/ai/epic-to-end-startup-codevelopment-program/)). **This commoditizes the "good-enough scribe inside Epic."** Standalone scribes now must be *radically* better, not marginally.

### Abridge — defending via depth, not breadth
- Highmark co-development on AI prior auth; Availity partnership (Jan 2026) for real-time PA ([STAT, Feb 10](https://www.statnews.com/2026/02/10/abridge-ai-scribe-cto-talks-epic-microsoft-rebranding/)).
- Pushed into nursing documentation.
- Valuation steady at $5.3B (Series E, June 2025, $300M) ([Sacra](https://sacra.com/c/abridge/)). CEO publicly rebranding as "more than an AI scribe."

### Microsoft Dragon Copilot — agentic pivot at HIMSS 2026
DAX is now **Dragon Copilot**. At HIMSS 2026 (March), Microsoft pitched the move from passive transcription to an "agentic clinical assistant" with Microsoft 365 Copilot / Work IQ integration, a partner Marketplace, and role-specific features for nurses and radiologists ([Windows Forum HIMSS recap](https://windowsforum.com/threads/dragon-copilot-at-himss-2026-from-ambient-scribe-to-agentic-clinical-assistant.404128/)). 100k+ daily clinician users across 9 countries.

### Suki — distribution wins, not product
Named athenahealth Preferred Solution Partner (Jan 2026); KLAS validation study showing **+$1,223/provider/month incremental revenue** at three health systems ([FierceHealthcare](https://www.fiercehealthcare.com/ai-and-machine-learning/rush-mcleod-health-and-fmol-health-report-revenue-gains-suki-ai-scribe)). Pricing now $299–$399 SMB, $350–$500+ enterprise.

### Notable — riding the access/RCM wedge
Major wins in Q1 2026: **Inova Health** (4M annual visits, system-wide AI agents for RCM + referrals + access; [PRNewswire](https://www.prnewswire.com/news-releases/inova-health-partners-with-notable-to-support-system-wide-ai-and-digital-transformation-strategy-302654419.html)) and **Marshall Health Network** (scheduling/registration; [March 18, 2026](https://news.marshallhealth.org/2026/03/18/marshall-health-network-partners-with-notable-to-launch-online-scheduling-and-registration-platform/)). Deployed at 12,000+ sites. They're winning the *administrative* AI market while the scribes fight each other.

### Heidi — surprise vertical expansion (Feb 2026)
Heidi launched two new products: **Heidi Evidence** (ad-free CDS with HealthPathways/BMJ/NICE) and **Heidi Comms** (AI patient comms — calls, bookings, reminders). Pricing jumped from $90 → **$150/mo annual** ([Vero review](https://www.veroscribe.com/blog/heidi-health-review-2026), [DeepCura](https://www.deepcura.com/resources/heidi-health-review)). They are quietly building exactly the Solace stack from the scribe side.

### OpenEvidence — distribution monster
$250M Series D Jan 2026 at **$12B valuation**. ~15M consultations/month. **Embedded into Mount Sinai's Epic in March 2026** ([iatroX clinical AI landscape](https://www.iatrox.com/blog/clinical-ai-landscape-2026-chatgpt-openevidence-iatrox-medwise)). Pharma-ad CPMs $70–150. Glass Health remains free-for-individuals, Epic/Athena/eCW SMART integration, but no comparable distribution.

### Sully — agent-shaped, Speechmatics/NVIDIA infra partnership
Speechmatics partnership Jan 2026 for medical-grade speech + agentic workflows on NVIDIA infra ([BusinessWire](https://www.businesswire.com/news/home/20260112368009/en/Speechmatics-and-Sully.ai-Partner-to-Scale-Healthcare-AI-Infrastructure-Globally)). Ships AI Scribe + Coder + Receptionist + Nurse + Interpreter — closest functional clone of Solace's "doctor's pal" framing. ~$35M total raised, still SMB-priced.

### Freed — aggressive SMB pricing
Public tiers $39 / $79 / $119 per provider per month ([Freed](https://www.getfreed.ai/resources/best-ai-scribes)). Sets the floor for solo-practitioner pricing.

### Phreesia / Clearstep / Keragon
No material announcements found in Q2 2026. Phreesia powering 180M visits in 2026. Clearstep still positioning on nurse-protocol triage. Treat as stable baseline.

---

## 2. Three sharp 90-day opportunities for Solace

### A. "The post-Epic-AI-Charting differentiator": calibrated, conformal, auditable triage that Epic Art cannot match
Epic's AI Charting is a transcription/note tool with no published calibration, no conformal prediction sets, no per-output uncertainty. Solace already has **calibrated LightGBM ESI + conformal prediction sets + SHAP per output**. Position Solace as **the only ambient + intake system that ships a model card, calibration plot, and conformal coverage guarantee with every encounter** — this is the regulatory wedge as FDA SaMD scrutiny intensifies and the first public CMS PA performance metrics are due March 31, 2026. *Moat: calibrated LightGBM + conformal.* Ship a public "Solace Trust Report" page within 90 days.

### B. The 20-language intake wedge for FQHCs and safety-net systems
Phreesia, Notable, and Clearstep ship 6–10 languages. Heidi Comms and OpenEvidence are English-dominant. **FQHCs and Medicaid-heavy systems are explicitly excluded from Epic-AI-Charting's near-term economics** (most run smaller EHRs or shared Epic instances). 20-language patient screens + SHAP-explained ESI + no-code workflow builder is a credible FQHC stack that no incumbent can match in Q3 2026. *Moat: 20-language intake + no-code workflows.* Concrete move: get one FQHC reference customer signed by end of Q3.

### C. "Bring-your-own-protocol" workflow builder — neutralize Clearstep's Schmitt-Thompson trust moat
Clearstep's defensibility is licensed nurse protocols. Solace's no-code workflow builder + SHAP can let any health system encode and version-control their **own** triage protocols with full audit trails — superior for Joint Commission and CMS PA performance reporting. Combine with CDS Hooks (Wave 2 roadmap item) and Solace becomes a **protocol authoring + execution platform**, not just a vendor of one protocol. *Moat: no-code workflow builder + SHAP.* This also pre-empts Notable's expansion into intake.

---

## 3. Pricing / packaging moves

### Confirmed competitor pricing (May 2026)
| Vendor | Per-clinician/mo |
|---|---|
| DAX / Dragon Copilot | $369–$830+ ([Vero](https://www.veroscribe.com/blog/nuance-dax-review-2026)) |
| Abridge | ~$208 baseline, $250–$500 with depth ([DeepCura](https://www.deepcura.com/resources/abridge-ai-review)) |
| Suki | $299–$399 SMB / $350–$500+ enterprise ([Healos](https://www.healos.ai/blog/suki-pricing-features-cost-and-the-best-alternatives-in-2025)) |
| Notable | Enterprise only, undisclosed |
| Heidi | $150/mo annual (just raised from $90) |
| Freed | $39 / $79 / $119 published |
| Nabla | Free tier + paid |
| Epic AI Charting | Bundled inside Epic licensing |

### Recommended Solace packaging
1. **Solo / Free tier:** unlimited triage intake + scribe up to 30 notes/mo + 1 workflow + 5 languages. Mirrors Freed Starter + Nabla free. Critical for OpenEvidence/Heidi-style viral acquisition.
2. **Clinician:** **$129/mo** (annual) — undercuts Heidi's $150 and Freed Premier's $119 by adding scribe + Ddx + 20-language intake + SHAP. The $129 number signals "fewer than Heidi, more than Freed."
3. **Practice (5–25 clinicians):** **$169/clinician/mo** — under Abridge baseline ($208), with no-code workflow builder + conformal triage that Abridge can't ship.
4. **Enterprise / Health System:** **$199–$249/clinician/mo** + per-encounter PA automation fee — *revise the memory's $150–200 target upward* given Suki's KLAS validation showing $1,223/mo incremental revenue per provider. ROI math supports $249.
5. **FQHC / Safety-Net SKU:** **$79/clinician/mo** — explicit Medicaid-economics tier. Anchors the 20-language story.

The strategy memo's $150–200 target is **directionally right but flat-priced**. Move to a 5-tier ladder with FQHC-specific pricing — that's defensible against Epic (free, but Epic-only) and against Abridge (premium-enterprise-only).

---

## 4. Two strategic risks (6-month horizon)

### Risk 1: Epic adds Ddx + intake to Art before Solace closes its first enterprise design partner
Epic's Art roadmap is opaque, but they've already shipped charting and order suggestion. Differential diagnosis and structured intake are the obvious next modules. If Epic ships an Art "intake" or "reasoning" module by HIMSS 2027 (March), Solace's wedge inside Epic systems collapses to "calibration + 20-language + FQHC." **Mitigation:** explicitly *avoid* selling against Epic head-on; sell to non-Epic systems (athenahealth, eClinicalWorks, Oracle, MEDITECH, FQHC homegrown stacks) where Suki and Abridge are weakest. The 42% Epic share means 58% of the market is fair game.

### Risk 2: Notable bundles a "good-enough" scribe into its access/RCM stack and dominates the doctor's-pal positioning
Notable already owns the workflow-agent enterprise narrative (Inova, 12k sites) and has the easiest distribution to add a scribe — either acqui-hire one of Heidi/Freed/Sully or buy from a hyperscaler. If Notable ships a bundled scribe + intake + PA at enterprise pricing in late 2026, they become *the* "doctor's pal" by default, and Solace's positioning becomes redundant. **Mitigation:** move fast on the FQHC + non-Epic SMB segments where Notable is structurally absent, and lean on the calibrated/conformal/SHAP story Notable does not have and would need years to build credibly.

---

**Honest gaps in this update:** I did not find Q2 2026 funding rounds for Heidi, Freed, Nabla, Clearstep, or Keragon — likely no major events, but worth a follow-up search in 4–6 weeks. No public confirmation of Epic AI Charting's pricing model; treating it as effectively free is the consensus read, not a citation.

