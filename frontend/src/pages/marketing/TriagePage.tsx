import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { QrCode, MessageSquareText, Stethoscope, Activity, BellRing, Languages } from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { SectionHeading } from "../../components/marketing/SectionHeading";
import { Reveal } from "../../components/marketing/Reveal";
import { StatCounter } from "../../components/marketing/StatCounter";
import { FAQAccordion } from "../../components/marketing/FAQAccordion";

const intake = [
  { who: "patient" as const, text: "My chest has felt tight since this morning, and I'm a bit dizzy." },
  { who: "solace" as const, text: "I'm sorry — that sounds frightening. Does the tightness spread to your arm, jaw, or back?" },
  { who: "patient" as const, text: "A little into my left shoulder." },
  { who: "solace" as const, text: "Thank you. A clinician is being notified now. Please stay seated — you're in the right place." },
];

const summary = [
  "Chest tightness, onset ~2h, radiating to left shoulder",
  "Associated dizziness; no syncope reported",
  "Provisional ESI 2 - clinician notified",
];

function IntakeDemo() {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? intake.length : 0);
  const [bullets, setBullets] = useState(reduced ? summary.length : 0);
  useEffect(() => {
    if (reduced) return;
    let cancelled = false;
    const timers: number[] = [];
    const at = (ms: number, fn: () => void) => timers.push(window.setTimeout(() => !cancelled && fn(), ms));
    const run = () => {
      setShown(0);
      setBullets(0);
      intake.forEach((_, i) => at(500 + i * 1250, () => setShown(i + 1)));
      const sStart = 500 + intake.length * 1250 + 400;
      summary.forEach((_, i) => at(sStart + i * 700, () => setBullets(i + 1)));
      at(sStart + summary.length * 700 + 3600, run);
    };
    run();
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [reduced]);

  return (
    <div className="grid gap-5 lg:grid-cols-2" aria-label="Animated example: voice intake becoming a triage pre-brief">
      <div className="card-clean rounded-xl p-5 text-left">
        <p className="text-sm font-medium text-ink">Waiting-room intake</p>
        <div className="mt-4 min-h-[240px] space-y-2.5">
          {intake.slice(0, shown).map((m) => (
            <motion.div
              key={m.text}
              initial={reduced ? false : { opacity: 0, y: 10, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ type: "spring", stiffness: 320, damping: 26 }}
              className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed ${
                m.who === "patient"
                  ? "bg-surface-low text-ink"
                  : "ml-auto bg-primary text-white"
              }`}
            >
              {m.text}
            </motion.div>
          ))}
        </div>
        <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-text-muted">
          Voice or text - any language
        </p>
      </div>
      <div className="card-clean rounded-xl p-5 text-left">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-ink">Clinician pre-brief</p>
          <motion.span
            initial={reduced ? false : { opacity: 0, scale: 0.8 }}
            animate={bullets > 0 ? { opacity: 1, scale: 1 } : {}}
            className="rounded-full bg-warning-container px-2.5 py-1 font-mono text-[11px] font-medium text-warning"
          >
            ESI 2 - Emergent
          </motion.span>
        </div>
        <div className="mt-4 min-h-[150px] space-y-2.5">
          {summary.slice(0, bullets).map((b) => (
            <motion.div
              key={b}
              initial={reduced ? false : { opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex items-start gap-2 text-[13px] leading-relaxed text-text-muted"
            >
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
              {b}
            </motion.div>
          ))}
        </div>
        <div className="mt-3 border-t border-line pt-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-text-muted">
            Refined at bedside with explainable ML
          </p>
        </div>
      </div>
    </div>
  );
}

const journey = [
  { Icon: QrCode, title: "Check in with a QR code", desc: "No app, no download, no kiosk line. Patients scan and start intake from their own phone, in their own language." },
  { Icon: MessageSquareText, title: "Tell their story once", desc: "Voice-first intake captures the chief complaint, history, and symptoms — and turns them into a provisional ESI with a comfort protocol while they wait." },
  { Icon: Stethoscope, title: "Arrive at the bedside briefed", desc: "Clinicians see the pre-brief, scribe note, and acuity before walking in. Bedside vitals refine the ESI with SHAP-backed explanations — both stages shown side by side." },
];

const safety = [
  { Icon: Activity, title: "Two-stage acuity", desc: "A provisional intake ESI, then an ML-refined score from real vitals — with the contributing factors shown, never a black box." },
  { Icon: BellRing, title: "Pain escalation", desc: "Patients can flag worsening symptoms mid-wait; the dashboard raises a red-banner alert instantly." },
  { Icon: Languages, title: "Every language", desc: "Intake, explanations, and comfort protocols are generated per patient, per language." },
];

const faqs = [
  { q: "Does the AI decide who gets seen first?", a: "No. Solace produces a provisional acuity with its reasoning shown; clinicians always make the call. Bedside vitals trigger a second, explainable refinement stage." },
  { q: "What do patients need to install?", a: "Nothing. The intake is a mobile web page reached by scanning a QR code in the waiting room." },
  { q: "How does this fit our existing triage workflow?", a: "It runs ahead of your nurse triage, not instead of it — patients arrive at the desk already understood, and the bedside stage matches your standard ESI flow." },
  { q: "Is the waiting room data secure?", a: "Yes — short-lived intake sessions, encrypted storage with customer-managed keys, automatic data expiry, and full audit logging." },
];

export default function TriagePage() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="Smart Triage"
        title="Every patient seen, understood, and safe — from the first hello."
        sub="QR check-in, voice intake, and a two-stage ESI engine that explains itself — so the waiting room is never a blind spot."
        primaryCta={{ to: "/get-started", label: "Get started" }}
        secondaryCta={{ to: "/contact", label: "Book a demo" }}
      >
        <IntakeDemo />
      </MarketingHero>

      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          eyebrow="The journey"
          title="From the parking lot to the bedside."
          sub="Solace walks the patient through the wait — and walks the clinician in prepared."
        />
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {journey.map(({ Icon, title, desc }, i) => (
            <Reveal key={title} delay={i * 0.08}>
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
        <div className="mx-auto grid max-w-5xl gap-12 px-4 py-16 sm:grid-cols-3 sm:px-6">
          <StatCounter value={5} suffix=" min" label="Typical check-in to provisional acuity" inverse />
          <StatCounter value={2} label="Acuity stages - intake and explainable bedside refinement" inverse />
          <StatCounter value={90} suffix="%" label="Conformal coverage target on refined ESI sets" inverse />
        </div>
      </section>

      <section className="section-low">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading
            eyebrow="Safety first"
            title="Built for the realities of a waiting room."
          />
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {safety.map(({ Icon, title, desc }, i) => (
              <Reveal key={title} delay={i * 0.08}>
                <div className="card-clean h-full rounded-xl p-7">
                  <Icon size={20} className="text-primary" aria-hidden="true" />
                  <h3 className="mt-3 text-lg font-medium text-ink">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-text-muted">{desc}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
        <SectionHeading eyebrow="FAQ" title="Questions, answered." />
        <Reveal className="mt-10">
          <FAQAccordion items={faqs} />
        </Reveal>
      </section>
    </MarketingLayout>
  );
}
