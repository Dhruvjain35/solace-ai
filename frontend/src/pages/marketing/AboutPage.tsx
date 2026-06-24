import { Link } from "react-router-dom";
import { ArrowRight, HeartPulse, Compass, Scale } from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { SectionHeading } from "../../components/marketing/SectionHeading";
import { Reveal } from "../../components/marketing/Reveal";
import { Button } from "../../components/ui/Button";

const values = [
  {
    Icon: HeartPulse,
    title: "Clinicians first, always",
    desc: "Every feature starts from a clinician's minute, not a model's capability. If it doesn't give time back to care, we don't ship it.",
  },
  {
    Icon: Scale,
    title: "Trust is engineered",
    desc: "We treat safety claims as code: PHI isolation, consent gates, and confirm-gated writes are tests that fail the build, not lines in a deck.",
  },
  {
    Icon: Compass,
    title: "Calm over clever",
    desc: "Healthcare software shouts. Ours doesn't. We design for the 3 a.m. shift — fewer clicks, quieter screens, honest uncertainty.",
  },
];

export default function AboutPage() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="About Solace"
        title="Built so care teams can look up from the screen."
        sub="We build calm, trustworthy AI for the people who hold the front lines of medicine — and we believe the chart should never come before the patient."
        primaryCta={{ to: "/get-started", label: "Work with us" }}
        secondaryCta={{ to: "/contact", label: "Contact" }}
      />

      <section className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
        <Reveal>
          <div className="space-y-5 text-[17px] leading-relaxed text-text-muted">
            <p>
              Solace started in an emergency department waiting room — watching people wait in pain to
              repeat their story three times, and watching clinicians spend their evenings typing instead
              of going home.
            </p>
            <p>
              The diagnosis was obvious and uncomfortable: the burden wasn't medicine, it was paperwork
              and blind spots. So we built the platform we wished existed — triage that understands
              patients from the first hello, documentation that writes itself while the clinician stays
              present, and a copilot that handles the chart's busywork without ever taking the pen out of
              a clinician's hand.
            </p>
            <p>
              We're a small team that ships fast and measures itself on one number: minutes returned to
              care.
            </p>
          </div>
        </Reveal>
      </section>

      <section className="section-low">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading eyebrow="What we believe" title="Three commitments." />
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {values.map(({ Icon, title, desc }, i) => (
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
        </div>
      </section>

      <section className="mx-auto max-w-4xl px-4 py-20 text-center sm:px-6">
        <Reveal>
          <h3 className="font-display text-2xl tracking-editorial text-ink sm:text-3xl">
            If this sounds like the way healthcare software should work, let's talk.
          </h3>
          <Link to="/contact" className="mt-6 inline-block">
            <Button shape="pill" className="h-12 px-7">
              Get in touch <ArrowRight size={16} aria-hidden="true" />
            </Button>
          </Link>
        </Reveal>
      </section>
    </MarketingLayout>
  );
}
