import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { AudioLines, FileCheck2, Lock, ShieldCheck, Database, EyeOff, ScrollText } from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { ScribeDemo } from "../../components/marketing/ScribeDemo";
import { SectionHeading } from "../../components/marketing/SectionHeading";
import { Reveal } from "../../components/marketing/Reveal";
import { StatCounter } from "../../components/marketing/StatCounter";
import { FAQAccordion } from "../../components/marketing/FAQAccordion";

const templates = [
  { name: "SOAP - Primary care", preview: "Subjective / Objective / Assessment / Plan with med reconciliation inline." },
  { name: "ED note - Emergency", preview: "Chief complaint, HPI, MDM with acuity rationale, disposition, and return precautions." },
  { name: "Progress note - Hospitalist", preview: "Interval events, exam, labs trended, problem-based A&P." },
  { name: "CHEDDAR - Specialty clinic", preview: "Chief complaint, History, Exam, Details, Drugs, Assessment, Return." },
];

function TemplateCycler() {
  const reduced = useReducedMotion();
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const t = window.setInterval(() => setActive((a) => (a + 1) % templates.length), 2400);
    return () => window.clearInterval(t);
  }, [reduced]);
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <div className="card-clean space-y-1.5 rounded-xl p-3">
        {templates.map((t, i) => (
          <button
            key={t.name}
            type="button"
            onClick={() => setActive(i)}
            className={`flex w-full items-center justify-between rounded-lg px-4 py-3 text-left text-sm transition-colors ${
              i === active ? "bg-primary-dim/60 text-primary ring-1 ring-primary/15" : "text-text-muted hover:bg-surface-low"
            }`}
          >
            <span className="font-medium">{t.name}</span>
            {i === active && <span className="font-mono text-[10px] uppercase tracking-wide">Active</span>}
          </button>
        ))}
      </div>
      <div className="card-clean rounded-xl p-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={active}
            initial={reduced ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? undefined : { opacity: 0, y: -10 }}
            transition={{ duration: 0.25 }}
          >
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-primary">{templates[active].name}</p>
            <p className="mt-3 text-sm leading-relaxed text-text-muted">{templates[active].preview}</p>
            <div className="mt-5 space-y-2" aria-hidden="true">
              {[100, 92, 78, 86].map((w, i) => (
                <div key={i} className="h-2 rounded-full bg-surface-high" style={{ width: `${w}%` }} />
              ))}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

const steps = [
  { Icon: AudioLines, title: "Capture every detail", desc: "Start the visit. Solace listens ambiently and transcribes in real time — no dictation, no templates to fill." },
  { Icon: FileCheck2, title: "Let the AI do the heavy lifting", desc: "A structured draft in your format appears seconds after the visit ends, grounded in what was actually said." },
  { Icon: ScrollText, title: "Sign with confidence", desc: "Review, edit, sign. Suggested ICD-10/CPT codes ride along, and the note writes back to your EHR." },
];

const trust = [
  { Icon: ShieldCheck, title: "HIPAA-aligned architecture", desc: "Audit trails on every action, consent-gated AI, and infrastructure designed for PHI from day one." },
  { Icon: EyeOff, title: "PHI isolation, enforced in code", desc: "Models reason over coded, de-identified data. A CI-gated test proves raw PHI never reaches the model." },
  { Icon: Database, title: "Never trained on your data", desc: "Your notes are yours. Patient data is never used to train models — contractually and architecturally." },
  { Icon: Lock, title: "Encrypted end to end", desc: "Customer-managed keys, encryption in transit and at rest, US-based infrastructure." },
];

const faqs = [
  { q: "How fast is a note ready after the visit?", a: "A structured draft appears within seconds of ending the visit. Most clinicians review and sign in under a minute." },
  { q: "Does it work for my specialty?", a: "Templates cover primary care, emergency, hospitalist, and specialty formats — SOAP, CHEDDAR, ED, and progress notes — and each can be customized to how you chart." },
  { q: "Which EHRs does the note write back to?", a: "Any SMART on FHIR R4 system — Epic, Oracle Health, athenahealth, and SMART-conformant EHRs — as a DocumentReference with codes attached." },
  { q: "What happens to the audio?", a: "Audio is processed for transcription and not retained beyond the configured window. The model only ever sees de-identified, coded content." },
  { q: "Do clinicians stay in control?", a: "Always. Nothing is signed, coded, or written to the chart without explicit clinician review and confirmation." },
];

export default function ScribePage() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="AI Scribe"
        title="No more charting after hours."
        sub="Solace listens to the visit, drafts a structured, coded note in seconds, and leaves the final word — always — with you."
        primaryCta={{ to: "/get-started", label: "Get started" }}
        secondaryCta={{ to: "/contact", label: "Book a demo" }}
      >
        <ScribeDemo />
      </MarketingHero>

      {/* How it works */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          eyebrow="How it works"
          title="From talk to chart, in three steps."
          sub="No workflow change. No dictation voice. Just the conversation you were already having."
        />
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {steps.map(({ Icon, title, desc }, i) => (
            <Reveal key={title} delay={i * 0.08}>
              <div className="card-clean h-full rounded-xl p-7">
                <span className="inline-flex rounded-lg bg-primary-dim/60 p-2.5 text-primary">
                  <Icon size={20} aria-hidden="true" />
                </span>
                <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.12em] text-text-muted">Step {i + 1}</p>
                <h3 className="mt-1 text-lg font-medium text-ink">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-muted">{desc}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Templates */}
      <section className="section-low">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading
            eyebrow="Your format"
            title="Notes the way you actually write them."
            sub="SOAP, CHEDDAR, ED, progress — pick a starting point, then tune sections, tone, and depth per clinician."
          />
          <Reveal className="mt-12">
            <TemplateCycler />
          </Reveal>
        </div>
      </section>

      {/* Stats */}
      <section className="bg-ink">
        <div className="mx-auto grid max-w-5xl gap-12 px-4 py-16 sm:grid-cols-3 sm:px-6">
          <StatCounter value={2} suffix="h" label="Returned to clinicians per day, on average" inverse />
          <StatCounter value={10} prefix="<" suffix="s" label="From end of visit to structured draft" inverse />
          <StatCounter value={100} suffix="%" label="Of notes reviewed and signed by a clinician" inverse />
        </div>
      </section>

      {/* Trust */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          eyebrow="Trust"
          title="A secure partner you can trust."
          sub="Built as a HIPAA business associate, with controls you can verify — not just claims."
        />
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {trust.map(({ Icon, title, desc }, i) => (
            <Reveal key={title} delay={i * 0.06}>
              <div className="card-clean h-full rounded-xl p-6">
                <Icon size={20} className="text-primary" aria-hidden="true" />
                <h3 className="mt-3 text-[15px] font-medium text-ink">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-text-muted">{desc}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section className="section-low">
        <div className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
          <SectionHeading eyebrow="FAQ" title="Questions, answered." />
          <Reveal className="mt-10">
            <FAQAccordion items={faqs} />
          </Reveal>
        </div>
      </section>
    </MarketingLayout>
  );
}
