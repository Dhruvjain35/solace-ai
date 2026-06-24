import { Link } from "react-router-dom";
import {
  ArrowRight,
  EyeOff,
  KeyRound,
  ScrollText,
  Server,
  UserCheck,
  Timer,
  Network,
} from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { SectionHeading } from "../../components/marketing/SectionHeading";
import { Reveal } from "../../components/marketing/Reveal";
import { Button } from "../../components/ui/Button";

const pillars = [
  {
    Icon: EyeOff,
    title: "PHI isolation, enforced in code",
    desc: "Our AI plans over coded metadata and slot tokens — names, MRNs, birthdates, and free text are stripped before any model prompt. An automated leak-gate test fails the build if raw PHI ever reaches a prompt.",
  },
  {
    Icon: UserCheck,
    title: "Consent before computation",
    desc: "AI features run behind a recorded-consent chokepoint. No consent on file, no model call — the request is refused at the boundary, and the refusal is logged.",
  },
  {
    Icon: ScrollText,
    title: "Audit on every action",
    desc: "Chart reads, AI requests, write-backs, sign-ins, and admin changes all land in an append-only audit log with actor, patient, and timestamp.",
  },
  {
    Icon: KeyRound,
    title: "Customer-managed encryption",
    desc: "Data is encrypted in transit and at rest under customer-managed KMS keys — databases, object storage, secrets, and container images alike.",
  },
  {
    Icon: Server,
    title: "Hardened US infrastructure",
    desc: "WAF with OWASP managed rules and rate limiting, TLS-only storage policies, locked-down CORS, SSRF guards on outbound EHR calls, and per-route throttles on sensitive endpoints.",
  },
  {
    Icon: Timer,
    title: "Data minimization by default",
    desc: "Short-lived intake sessions, automatic TTL expiry on patient records and media, single-use magic-link tokens stored only as hashes.",
  },
];

const practices = [
  { k: "Access", v: "Passwordless magic-link sign-in, JWT sessions, role-scoped admin actions, tenant isolation checks on every workspace query" },
  { k: "AI boundary", v: "Plan-Execute-Narrate pipeline; models never execute tools directly and never see raw PHI; confirm-gated writes only" },
  { k: "Network", v: "CloudFront + WAF (IP reputation, known-bad-inputs, OWASP common rules, rate limiting) in front of every API call" },
  { k: "Monitoring", v: "CloudTrail across the account, 13 CloudWatch alarms, security alert topics wired to the team" },
  { k: "Vendors", v: "HIPAA-eligible AWS services under BAA; model inference via AWS Bedrock in covered regions" },
  { k: "Process", v: "700+ automated tests on every release, including dedicated PHI-isolation, tenant-isolation, and consent-gate suites" },
];

export default function SecurityPage() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="Security & compliance"
        title="Security isn't a feature. It's the architecture."
        sub="PHI isolation enforced in code, consent-gated AI, customer-managed encryption, and an audit trail on every action."
        primaryCta={{ to: "/trust", label: "View the trust report" }}
        secondaryCta={{ to: "/contact", label: "Request our security docs" }}
      />

      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          eyebrow="Architecture"
          title="Six guarantees we build against."
          sub="Not policies on paper — controls in code, exercised by the test suite on every release."
        />
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {pillars.map(({ Icon, title, desc }, i) => (
            <Reveal key={title} delay={i * 0.05}>
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

      <section className="section-low">
        <div className="mx-auto max-w-4xl px-4 py-20 sm:px-6">
          <SectionHeading eyebrow="In practice" title="How the platform is run." />
          <Reveal className="mt-10">
            <dl className="card-clean divide-y divide-line rounded-xl">
              {practices.map(({ k, v }) => (
                <div key={k} className="grid gap-1 px-6 py-4 sm:grid-cols-[160px_1fr] sm:gap-6">
                  <dt className="font-mono text-[11px] uppercase tracking-[0.12em] text-primary sm:pt-0.5">{k}</dt>
                  <dd className="text-sm leading-relaxed text-text-muted">{v}</dd>
                </div>
              ))}
            </dl>
          </Reveal>
        </div>
      </section>

      <section className="mx-auto max-w-4xl px-4 py-20 text-center sm:px-6">
        <Reveal>
          <div className="card-clean rounded-xl p-10">
            <Network size={24} className="mx-auto text-primary" aria-hidden="true" />
            <h3 className="mt-4 font-display text-2xl tracking-editorial text-ink sm:text-3xl">
              See it for yourself.
            </h3>
            <p className="mx-auto mt-3 max-w-xl text-sm text-text-muted">
              Our public trust report shows aggregate, PHI-free operational transparency. For security
              questionnaires, architecture reviews, or a BAA conversation, talk to us directly.
            </p>
            <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
              <Link to="/trust">
                <Button shape="pill" className="h-12 px-7">
                  Open trust report <ArrowRight size={16} aria-hidden="true" />
                </Button>
              </Link>
              <Link to="/contact">
                <Button variant="secondary" shape="pill" className="h-12 px-7">
                  Contact security
                </Button>
              </Link>
            </div>
          </div>
        </Reveal>
      </section>
    </MarketingLayout>
  );
}
