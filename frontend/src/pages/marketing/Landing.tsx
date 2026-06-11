import { Link } from "react-router-dom";
import { ArrowRight, AudioLines, Activity, Sparkles } from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { Reveal } from "../../components/marketing/Reveal";
import { StatCounter } from "../../components/marketing/StatCounter";

// NOTE: intentionally a lean placeholder landing — the production landing is
// maintained separately. This page exists so the marketing routes have a home.
const products = [
  {
    to: "/scribe",
    Icon: AudioLines,
    title: "AI Scribe",
    desc: "Ambient documentation that turns the visit conversation into a coded, signable note.",
  },
  {
    to: "/triage",
    Icon: Activity,
    title: "Smart Triage",
    desc: "Self-serve intake to ESI acuity in minutes, refined at bedside with explainable ML.",
  },
  {
    to: "/copilot",
    Icon: Sparkles,
    title: "EHR Copilot",
    desc: "An agent that reads the chart, drafts coded orders, and never writes without your confirm.",
  },
];

export default function Landing() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="Clinical AI platform"
        title="The calm operating layer for modern care."
        sub="Triage, ambient documentation, and an EHR copilot — one platform, built clinician-first, with PHI isolation enforced in code."
        primaryCta={{ to: "/get-started", label: "Get started" }}
        secondaryCta={{ to: "/contact", label: "Book a demo" }}
      />

      {/* Product trio */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <div className="grid gap-6 md:grid-cols-3">
          {products.map(({ to, Icon, title, desc }, i) => (
            <Reveal key={to} delay={i * 0.08}>
              <Link to={to} className="card-clean group block h-full rounded-xl p-7 transition-shadow hover:shadow-lifted">
                <span className="inline-flex rounded-lg bg-primary-dim/60 p-2.5 text-primary">
                  <Icon size={20} aria-hidden="true" />
                </span>
                <h3 className="mt-5 font-display text-2xl tracking-editorial text-ink">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-muted">{desc}</p>
                <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                  Learn more
                  <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                </span>
              </Link>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Stats band */}
      <section className="bg-ink">
        <div className="mx-auto grid max-w-5xl gap-12 px-4 py-16 sm:grid-cols-3 sm:px-6">
          <StatCounter value={700} suffix="+" label="Automated checks passing on every release" inverse />
          <StatCounter value={4} label="EHR vendors supported through SMART on FHIR" inverse />
          <StatCounter value={10} prefix="<" suffix="s" label="From conversation to coded draft note" inverse />
        </div>
      </section>
    </MarketingLayout>
  );
}
