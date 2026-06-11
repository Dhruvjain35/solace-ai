import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Search,
  Sparkles,
  FilePen,
  CheckCircle2,
  ShieldCheck,
  EyeOff,
  ClipboardCheck,
  TerminalSquare,
  Workflow,
} from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { SectionHeading } from "../../components/marketing/SectionHeading";
import { Reveal } from "../../components/marketing/Reveal";
import { FAQAccordion } from "../../components/marketing/FAQAccordion";

const trace = [
  { Icon: Search, text: "Searched chart - Conditions, Medications, latest Observations" },
  { Icon: Sparkles, text: "Reasoned over coded data - no raw PHI in context" },
  { Icon: FilePen, text: "Drafted 2 orders for review" },
];

const orders = [
  { code: "CBC w/ diff", detail: "ServiceRequest - LOINC 58410-2" },
  { code: "Chest X-ray, 2 views", detail: "ServiceRequest - CPT 71046" },
];

function CopilotDemo() {
  const reduced = useReducedMotion();
  // phases: 0 idle, 1 message, 2 trace, 3 proposals, 4 confirmed
  const [phase, setPhase] = useState(reduced ? 4 : 0);
  const [traceN, setTraceN] = useState(reduced ? trace.length : 0);
  useEffect(() => {
    if (reduced) return;
    let cancelled = false;
    const timers: number[] = [];
    const at = (ms: number, fn: () => void) => timers.push(window.setTimeout(() => !cancelled && fn(), ms));
    const run = () => {
      setPhase(0);
      setTraceN(0);
      at(500, () => setPhase(1));
      at(1500, () => setPhase(2));
      trace.forEach((_, i) => at(1700 + i * 900, () => setTraceN(i + 1)));
      at(1700 + trace.length * 900 + 300, () => setPhase(3));
      at(1700 + trace.length * 900 + 2600, () => setPhase(4));
      at(1700 + trace.length * 900 + 7000, run);
    };
    run();
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [reduced]);

  return (
    <div
      className="card-clean mx-auto max-w-2xl rounded-xl p-5 text-left"
      aria-label="Animated example: a plain-English order becoming confirmed FHIR orders"
    >
      <div className="min-h-[300px] space-y-3">
        {phase >= 1 && (
          <motion.div
            initial={reduced ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="ml-auto max-w-[85%] rounded-xl bg-primary px-3.5 py-2.5 text-[13px] leading-relaxed text-white"
          >
            Order a CBC and a chest X-ray for Mr. Kihn, and check for anything I'm missing.
          </motion.div>
        )}
        {phase >= 2 && (
          <div className="space-y-1.5">
            {trace.slice(0, traceN).map(({ Icon, text }) => (
              <motion.div
                key={text}
                initial={reduced ? false : { opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex items-center gap-2 text-xs text-text-muted"
              >
                <Icon size={13} className="text-primary" aria-hidden="true" />
                {text}
              </motion.div>
            ))}
          </div>
        )}
        {phase >= 3 && (
          <div className="space-y-2">
            {orders.map((o, i) => (
              <motion.div
                key={o.code}
                initial={reduced ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: reduced ? 0 : i * 0.15 }}
                className="flex items-center justify-between rounded-lg bg-surface-low px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-ink">{o.code}</p>
                  <p className="font-mono text-[11px] text-text-muted">{o.detail}</p>
                </div>
                <AnimatePresence mode="wait">
                  {phase >= 4 ? (
                    <motion.span
                      key="ok"
                      initial={reduced ? false : { scale: 0.6, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={{ type: "spring", stiffness: 400, damping: 22 }}
                      className="flex items-center gap-1.5 text-xs font-medium text-success"
                    >
                      <CheckCircle2 size={15} aria-hidden="true" /> Written to chart
                    </motion.span>
                  ) : (
                    <motion.span
                      key="confirm"
                      exit={reduced ? undefined : { opacity: 0 }}
                      className="rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-white"
                    >
                      Confirm
                    </motion.span>
                  )}
                </AnimatePresence>
              </motion.div>
            ))}
            {phase >= 3 && phase < 4 && (
              <p className="text-center text-xs text-text-muted">Nothing is written without your confirmation.</p>
            )}
          </div>
        )}
      </div>
      <p className="mt-3 border-t border-line pt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-text-muted">
        Plan - Execute - Narrate - every step audited
      </p>
    </div>
  );
}

const features = [
  { Icon: Search, title: "Reads the whole chart", desc: "Problems, meds, allergies, labs, and history — grounded answers with the source shown, never a guess." },
  { Icon: FilePen, title: "Drafts coded orders", desc: "Plain English in, LOINC/RxNorm-coded FHIR drafts out — ServiceRequests, MedicationRequests, Conditions, and more." },
  { Icon: ClipboardCheck, title: "Confirm-gated writes", desc: "Every write is proposed, narrated, and held until you confirm. Zero autonomous chart mutations, by architecture." },
  { Icon: EyeOff, title: "PHI-isolated reasoning", desc: "The model plans over coded metadata and slot tokens — raw names, MRNs, and notes never enter the prompt. CI-enforced." },
  { Icon: TerminalSquare, title: "Shows its work", desc: "A live console streams every chart read, reasoning round, and proposed write with real latencies — trust through transparency." },
  { Icon: Workflow, title: "Catches what's missed", desc: "Care-gap scans, interaction checks, and follow-up suggestions — proactively, across the patients you're carrying." },
];

const faqs = [
  { q: "Can the copilot change the chart on its own?", a: "No. It can only propose. Writes execute exclusively after explicit clinician confirmation, and every action is individually audited." },
  { q: "What does the model actually see?", a: "Coded, de-identified data — diagnoses, codes, values, age bands. Names, MRNs, free-text notes, and contact details are stripped before any prompt, enforced by an automated test gate." },
  { q: "Which EHRs does it work with?", a: "Any SMART on FHIR R4 EHR. Solace ships adapters for Epic, Oracle Health, and athenahealth, plus the SMART sandbox for evaluation." },
  { q: "How is this different from an ambient scribe?", a: "Scribes document what happened. The copilot acts — it reads, reasons, and drafts orders and chart updates you can commit in one click." },
];

export default function CopilotPage() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="EHR Copilot"
        title="Say the order. Solace drafts it — you confirm."
        sub="An agentic copilot that reads the chart, reasons over coded data only, and never touches the record without your explicit confirmation."
        primaryCta={{ to: "/get-started", label: "Get started" }}
        secondaryCta={{ to: "/contact", label: "Book a demo" }}
      >
        <CopilotDemo />
      </MarketingHero>

      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          eyebrow="Capabilities"
          title="A resident who never sleeps. With guardrails."
          sub="Built on Solace's Plan-Execute-Narrate architecture: the model plans over coded vocabulary, deterministic executors touch the data, and you hold the pen."
        />
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {features.map(({ Icon, title, desc }, i) => (
            <Reveal key={title} delay={i * 0.06}>
              <div className="card-clean h-full rounded-xl p-7">
                <span className="inline-flex rounded-lg bg-primary-dim/60 p-2.5 text-primary">
                  <Icon size={20} aria-hidden="true" />
                </span>
                <h3 className="mt-4 text-lg font-medium text-ink">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-muted">{desc}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="bg-ink">
        <div className="mx-auto max-w-5xl px-4 py-16 text-center sm:px-6">
          <Reveal>
            <div className="flex flex-col items-center gap-4">
              <ShieldCheck size={28} className="text-primary-fixed" aria-hidden="true" />
              <p className="max-w-2xl font-display text-2xl leading-snug tracking-editorial text-white sm:text-3xl">
                "The chart is sacred. Our copilot earns its place there one confirmed action at a time."
              </p>
              <p className="text-sm text-primary-fixed/70">The principle behind every Solace write-back</p>
            </div>
          </Reveal>
        </div>
      </section>

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
