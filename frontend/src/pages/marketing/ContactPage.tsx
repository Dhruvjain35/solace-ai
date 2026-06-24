import { Mail, CalendarClock, ShieldCheck } from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { Reveal } from "../../components/marketing/Reveal";
import { ContactForm } from "../../components/marketing/ContactForm";

const reasons = [
  { Icon: CalendarClock, title: "Book a demo", desc: "A 30-minute walkthrough of triage, scribe, and the copilot on your workflows." },
  { Icon: ShieldCheck, title: "Security reviews", desc: "Questionnaires, architecture deep-dives, and BAA conversations." },
  { Icon: Mail, title: "Everything else", desc: "Integrations, partnerships, press, or support — same form, fast routing." },
];

export default function ContactPage() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="Contact"
        title="Talk to a human. Quickly."
        sub="Demos, security reviews, integration questions, or anything else — we respond within one business day."
      />
      <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1fr_1.2fr]">
          <div className="space-y-6">
            {reasons.map(({ Icon, title, desc }, i) => (
              <Reveal key={title} delay={i * 0.07}>
                <div className="flex items-start gap-4">
                  <span className="rounded-lg bg-primary-dim/60 p-2.5 text-primary">
                    <Icon size={18} aria-hidden="true" />
                  </span>
                  <div>
                    <h3 className="font-medium text-ink">{title}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-text-muted">{desc}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal delay={0.1}>
            <ContactForm />
          </Reveal>
        </div>
      </section>
    </MarketingLayout>
  );
}
