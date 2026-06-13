import { useReducedMotion } from 'framer-motion';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  FlaskConical,
  BookOpen,
} from 'lucide-react';
import { getIntegration } from '../lib/integrations';
import {
  Reveal,
  Kicker,
  Logo,
  TierChip,
  PILL_DARK,
  PILL_LIGHT,
  WASH_WHITE_TO_MINT,
  WASH_MINT_TO_WHITE,
  WASH_PAPER,
} from '../components/integrations/shared';
import { getGuideSteps } from '../components/integrations/guideSteps';
import {
  ConnectionFlow,
  ScopeCard,
  WriteBackCard,
  ChartFrame,
} from '../components/integrations/GuideVisuals';

/*
 * Per-platform integration guide. Reads the platform from the route slug. If
 * the slug is unknown it shows a friendly not-found with a link back. Otherwise:
 * breadcrumb + back-link, a big-logo header with the tier chip, a numbered
 * connect guide (vendor-specific for native tiers, generic SMART-on-FHIR for
 * smart tiers), a "what you can do once connected" band of capabilities paired
 * with real product screenshots, a security note linking to /security, and a
 * closing CTA. Layout wraps Nav + Footer; this renders content only.
 */

const SECURITY_NOTES = [
  {
    tag: 'phi-isolation',
    title: 'PHI isolation in code',
    body: 'The AI plans and narrates over coded metadata. Raw PHI never reaches the model — and a leak test gates every release.',
  },
  {
    tag: 'smart-v2-scopes',
    title: 'Minimum-necessary scopes',
    body: 'Solace requests only the SMART v2 scopes a workflow needs. Nothing broad, nothing unused.',
  },
  {
    tag: 'kms-vault',
    title: 'Secrets in a vault',
    body: 'Client secrets and tokens live in a managed vault, never in the browser or a config file.',
  },
  {
    tag: 'append-only-log',
    title: 'Every write audited',
    body: 'Every read and write the AI performs is saved to the record, with a clinician on the final call.',
  },
];

// Friendly fallback when the slug doesn't match a known platform.
function NotFound() {
  const reduce = useReducedMotion();
  return (
    <div className="bg-white">
      <section
        className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <Reveal index={0} reduce={reduce}>
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted">
            Integrations
          </p>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <h1 className="mx-auto mt-5 max-w-[16ch] font-sofia text-[clamp(34px,5vw,68px)] font-medium leading-[1.05] tracking-hims text-ink">
            We don&rsquo;t have a guide for that one yet.
          </h1>
        </Reveal>
        <Reveal index={2} reduce={reduce}>
          <p className="mx-auto mt-6 max-w-md text-base text-muted md:text-lg">
            It may be listed under a different name — every platform Solace
            connects to lives on the integrations hub.
          </p>
        </Reveal>
        <Reveal index={3} reduce={reduce} className="mt-9">
          <Link to="/integrations" className={PILL_DARK}>
            <ArrowLeft size={15} aria-hidden="true" />
            Back to all integrations
          </Link>
        </Reveal>
      </section>
    </div>
  );
}

export default function IntegrationGuide() {
  const reduce = useReducedMotion();
  const { slug } = useParams<{ slug: string }>();
  const item = slug ? getIntegration(slug) : undefined;

  if (!item) return <NotFound />;

  const steps = getGuideSteps(item);
  const native = item.tier === 'native';

  return (
    <div className="bg-white">
      {/* ===== 1 · Header: breadcrumb, big logo, tier, blurb ===== */}
      <section
        aria-labelledby="guide-heading"
        className="bg-white px-6 pb-[6vh] pt-[14vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <div className="mx-auto max-w-[1000px]">
          {/* breadcrumb + back-link */}
          <Reveal index={0} reduce={reduce}>
            <nav
              aria-label="Breadcrumb"
              className="flex items-center gap-1.5 text-[13px] text-muted"
            >
              <Link
                to="/integrations"
                className="inline-flex items-center gap-1.5 font-medium text-solace-green-700 transition-colors hover:text-solace-green-600"
              >
                <ArrowLeft size={14} aria-hidden="true" />
                Integrations
              </Link>
              <ChevronRight size={13} aria-hidden="true" className="text-muted/50" />
              <span className="text-ink">{item.name}</span>
            </nav>
          </Reveal>

          <Reveal index={1} reduce={reduce}>
            <div className="mt-8 flex h-[72px] items-center">
              <Logo item={item} size="lg" />
            </div>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <h1
                id="guide-heading"
                className="font-sofia text-[clamp(34px,4.5vw,60px)] font-medium leading-[1.04] tracking-hims text-ink"
              >
                {item.name}
              </h1>
              <TierChip tier={item.tier} />
            </div>
          </Reveal>
          <Reveal index={3} reduce={reduce}>
            <p className="mt-5 max-w-2xl text-base text-muted md:text-lg">
              {item.blurb}
            </p>
          </Reveal>
        </div>
      </section>

      {/* ===== 1.5 · The connection at a glance — SMART flow diagram ===== */}
      <section
        aria-labelledby="flow-heading"
        className="bg-white px-6 pb-[8vh] pt-[2vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <div className="mx-auto max-w-[1000px]">
          <Reveal index={0} reduce={reduce}>
            <Kicker tone="light">The connection at a glance</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="flow-heading"
              className="mt-4 max-w-[24ch] font-sofia text-[clamp(24px,2.6vw,38px)] font-medium leading-[1.12] tracking-[-0.02em] text-ink"
            >
              {native
                ? `One SMART launch, inside your ${item.name} tenant.`
                : `One SMART launch over standard FHIR R4.`}
            </h2>
          </Reveal>
          <div className="mt-10">
            <ConnectionFlow vendor={item.name} reduce={reduce} />
          </div>
        </div>
      </section>

      {/* ===== 2 · The connect guide — numbered steps ===== */}
      <section
        aria-labelledby="connect-heading"
        className="bg-white pb-[12vh] pt-[6vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto max-w-[1000px] px-6">
          <Reveal index={0} reduce={reduce}>
            <Kicker tone="light">
              {native ? `The ${item.name} pathway` : 'Connect over SMART on FHIR'}
            </Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="connect-heading"
              className="mt-4 max-w-[20ch] font-sofia text-[clamp(28px,3vw,46px)] font-medium leading-[1.1] tracking-[-0.02em] text-ink"
            >
              {native
                ? `Bring Solace into ${item.name}.`
                : 'Sandbox first, then your endpoint.'}
            </h2>
          </Reveal>

          <ol className="mt-12 space-y-4">
            {steps.map(({ title, body, Icon }, i) => (
              <Reveal key={title} index={i} reduce={reduce}>
                <li className="group flex gap-5 rounded-hims bg-white p-6 shadow-card ring-1 ring-black/[0.06] transition-all duration-[400ms] ease-hims-expo hover:shadow-lift hover:ring-solace-green-300/50 md:p-7">
                  <div className="flex shrink-0 flex-col items-center gap-3">
                    <span
                      className={`flex h-11 w-11 items-center justify-center rounded-full font-sofia text-[16px] font-semibold tabular-nums transition-transform duration-[400ms] ease-hims-expo group-hover:scale-105 ${
                        native
                          ? 'bg-solace-green-700 text-white'
                          : 'bg-solace-soft text-solace-green-700 ring-1 ring-solace-green-300/50'
                      }`}
                    >
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    {i < steps.length - 1 ? (
                      <span
                        aria-hidden="true"
                        className="hidden w-px flex-1 bg-gradient-to-b from-solace-green-300/50 to-transparent md:block"
                      />
                    ) : null}
                  </div>
                  <div className="min-w-0 pb-1">
                    <div className="flex items-center gap-2.5">
                      <Icon
                        size={18}
                        strokeWidth={1.9}
                        aria-hidden="true"
                        className="shrink-0 text-solace-green-600"
                      />
                      <h3 className="font-sofia text-[19px] font-medium leading-tight tracking-[-0.01em] text-ink">
                        {title}
                      </h3>
                    </div>
                    <p className="mt-2.5 text-[15px] leading-relaxed text-muted">
                      {body}
                    </p>
                  </div>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      {/* ===== 3 · What you can do once connected ===== */}
      <section
        aria-labelledby="capabilities-heading"
        className="bg-ink px-6 py-[9vh] md:py-[14vh]"
      >
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce}>
            <Kicker tone="dark">Once connected</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="capabilities-heading"
              className="mt-4 max-w-[20ch] font-sofia text-[clamp(28px,3vw,46px)] font-medium leading-[1.1] tracking-[-0.02em] text-white"
            >
              What {item.name} gets you.
            </h2>
          </Reveal>

          {/* Hero: the live chart Solace reads from and writes back to */}
          <div className="mt-14 grid items-center gap-10 md:grid-cols-12 md:gap-14">
            <Reveal index={0} reduce={reduce} className="md:col-span-5">
              <div>
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-solace-mint/15 text-solace-mint ring-1 ring-solace-mint/25">
                  <BookOpen size={20} strokeWidth={1.9} aria-hidden="true" />
                </span>
                <h3 className="mt-5 font-sofia text-[clamp(24px,2.4vw,34px)] font-medium leading-tight tracking-[-0.02em] text-white">
                  The chart, read and reasoned on launch.
                </h3>
                <p className="mt-4 max-w-md text-base leading-relaxed text-white/65 md:text-lg">
                  Solace matches the patient and reads demographics, problems,
                  medications and allergies over USCDI — then drafts acuity, a
                  differential and a coded workup before the clinician walks in.
                  This is the Atlas snapshot, live from {item.name}.
                </p>
              </div>
            </Reveal>
            <div className="md:col-span-7">
              <ChartFrame vendor={item.name} reduce={reduce} />
            </div>
          </div>

          {/* Supporting capability visuals: scopes + coded write-back */}
          <div className="mt-12 grid grid-cols-1 gap-6 md:mt-16 md:grid-cols-2">
            <div>
              <Reveal index={0} reduce={reduce}>
                <h3 className="mb-5 font-sofia text-[20px] font-medium leading-tight tracking-[-0.01em] text-white">
                  Only what the workflow needs.
                </h3>
              </Reveal>
              <ScopeCard reduce={reduce} />
            </div>
            <div>
              <Reveal index={1} reduce={reduce}>
                <h3 className="mb-5 font-sofia text-[20px] font-medium leading-tight tracking-[-0.01em] text-white">
                  The visit, written back coded.
                </h3>
              </Reveal>
              <WriteBackCard vendor={item.name} reduce={reduce} />
            </div>
          </div>
        </div>
      </section>

      {/* ===== 4 · Security note strip ===== */}
      <section
        aria-labelledby="security-heading"
        className="bg-white px-6 py-[9vh] md:py-[12vh]"
        style={{ backgroundImage: WASH_PAPER }}
      >
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce}>
            <Kicker tone="light">Built to be trusted</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="security-heading"
              className="mt-4 max-w-[22ch] font-sofia text-[clamp(26px,2.8vw,42px)] font-medium leading-[1.12] tracking-[-0.02em] text-ink"
            >
              Every connection is held to the same security bar.
            </h2>
          </Reveal>

          <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {SECURITY_NOTES.map(({ tag, title, body }, i) => (
              <Reveal key={title} index={i} reduce={reduce}>
                <div className="group flex h-full flex-col rounded-tile bg-white p-6 shadow-card ring-1 ring-black/[0.06] transition-all duration-[400ms] ease-hims-expo hover:-translate-y-1 hover:shadow-lift hover:ring-solace-green-300/50">
                  <div className="flex items-baseline justify-between gap-2 border-b border-black/[0.07] pb-3">
                    <span className="font-mono text-[20px] font-medium leading-none tabular-nums tracking-[-0.04em] text-solace-green-300 transition-colors duration-[400ms] ease-hims-expo group-hover:text-solace-green-600">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span className="font-mono text-[10px] tracking-[0.04em] text-muted/60">
                      {tag}
                    </span>
                  </div>
                  <h3 className="mt-4 font-sofia text-[17px] font-medium leading-tight tracking-[-0.01em] text-ink">
                    {title}
                  </h3>
                  <p className="mt-2 text-[14px] leading-relaxed text-muted">
                    {body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>

          <Reveal index={0} reduce={reduce} className="mt-9">
            <Link
              to="/security"
              className="inline-flex items-center gap-2 text-sm font-semibold text-solace-green-700 transition-colors hover:text-solace-green-600"
            >
              Read how Solace handles security and PHI
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </Reveal>
        </div>
      </section>

      {/* ===== 5 · Closing CTA ===== */}
      <section
        aria-labelledby="guide-close-heading"
        className="bg-white px-6 py-[11vh] text-center md:py-[16vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <Reveal index={0} reduce={reduce}>
          <h2
            id="guide-close-heading"
            className="mx-auto max-w-[18ch] font-sofia text-[clamp(34px,4.5vw,68px)] font-medium leading-[1.06] tracking-hims text-ink"
          >
            See Solace on {item.name}.
          </h2>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <p className="mx-auto mt-6 max-w-md text-base text-muted md:text-lg">
            Book a walkthrough on your own stack, or try the full read-and-write
            loop on the public sandbox first — no credentials.
          </p>
        </Reveal>
        <Reveal
          index={2}
          reduce={reduce}
          className="mt-9 flex flex-wrap items-center justify-center gap-3"
        >
          <Link to="/demo" className={PILL_DARK}>
            Book a Demo
          </Link>
          <a
            href="https://solaceaidemo.vercel.app"
            target="_blank"
            rel="noreferrer"
            className={PILL_LIGHT}
          >
            <FlaskConical size={15} aria-hidden="true" />
            Try the sandbox
          </a>
        </Reveal>
      </section>
    </div>
  );
}
