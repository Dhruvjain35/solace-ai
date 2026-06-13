import { useReducedMotion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { ArrowRight, AppWindow, Link2, LogIn, FlaskConical } from 'lucide-react';
import { INTEGRATIONS, type Integration } from '../lib/integrations';
import {
  Reveal,
  Kicker,
  Logo,
  TierChip,
  WASH_WHITE_TO_MINT,
  WASH_MINT_TO_WHITE,
  PALE_GRADIENT,
} from '../components/integrations/shared';

/*
 * Integrations hub: the directory of every EHR Solace talks to. A white opening
 * statement on the SMART-on-FHIR thesis, a responsive grid of clickable
 * platform cards (logo + name + blurb + tier chip + arrow, linking to the
 * per-platform guide), a three-step "how connection works" strip, and a
 * sandbox CTA. Layout wraps Nav + Footer; this renders the content only and
 * rides the two house curves from ../lib/hims via the shared Reveal.
 */

// One platform tile: the whole card is the link. Logo (or wordmark fallback)
// floats top, blurb fills the middle, tier chip + arrow pin the bottom row.
function PlatformCard({ item, index }: { item: Integration; index: number }) {
  return (
    <Reveal index={index % 3} reduce={useReducedMotion()}>
      <Link
        to={`/integrations/${item.slug}`}
        aria-label={`${item.name} integration guide`}
        className="group flex h-full flex-col rounded-tile bg-white p-6 shadow-card ring-1 ring-black/[0.06] transition-shadow duration-300 hover:shadow-pop hover:ring-black/10"
      >
        <div className="flex h-[52px] items-center">
          <Logo item={item} />
        </div>
        <h3 className="mt-5 font-sofia text-[20px] font-medium leading-tight tracking-[-0.01em] text-ink">
          {item.name}
        </h3>
        <p className="mt-2 flex-1 text-[14px] leading-relaxed text-muted">
          {item.blurb}
        </p>
        <div className="mt-6 flex items-center justify-between">
          <TierChip tier={item.tier} />
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-solace-soft text-solace-green-700 transition-transform duration-300 ease-hims-expo group-hover:translate-x-0.5">
            <ArrowRight size={16} aria-hidden="true" />
          </span>
        </div>
      </Link>
    </Reveal>
  );
}

const CONNECT_STEPS = [
  {
    Icon: AppWindow,
    title: 'Register the SMART app',
    body: 'Add Solace as a SMART on FHIR app in your vendor’s developer console, App Orchard or Marketplace.',
  },
  {
    Icon: Link2,
    title: 'Bind it to a workspace',
    body: 'Paste the FHIR base URL and client ID into Tools → EHR connections. Secrets go straight into the vault.',
  },
  {
    Icon: LogIn,
    title: 'Sign in and write back',
    body: 'A clinician signs in with vendor SSO. Solace reads the chart and writes the visit back as coded FHIR.',
  },
];

export default function Integrations() {
  const reduce = useReducedMotion();

  return (
    <div className="bg-white">
      {/* ===== 1 · Opening statement ===== */}
      <section
        aria-labelledby="integrations-heading"
        className="bg-white px-6 pb-[8vh] pt-[14vh] text-center md:pt-[18vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <Reveal index={0} reduce={reduce}>
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted">
            Integrations
          </p>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <h1
            id="integrations-heading"
            className="mx-auto mt-5 max-w-[15ch] font-sofia text-[clamp(40px,6.5vw,96px)] font-medium leading-[1.03] tracking-hims text-ink"
          >
            Connect Solace to the chart you already run.
          </h1>
        </Reveal>
        <Reveal index={2} reduce={reduce}>
          <p className="mx-auto mt-7 max-w-xl text-base text-muted md:text-lg">
            Built on SMART on FHIR R4, so Solace reads the chart and writes the
            visit back in standard codes — no rip-and-replace, no parallel
            system to keep in sync.
          </p>
        </Reveal>
      </section>

      {/* ===== 2 · The directory grid ===== */}
      <section
        aria-labelledby="directory-heading"
        className="bg-white pb-[12vh] pt-[2vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto max-w-[1200px] px-6">
          <h2 id="directory-heading" className="sr-only">
            Every platform Solace connects to
          </h2>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {INTEGRATIONS.map((item, i) => (
              <PlatformCard key={item.slug} item={item} index={i} />
            ))}
          </div>
        </div>
      </section>

      {/* ===== 3 · How connection works — three-step strip ===== */}
      <section
        aria-labelledby="how-connect-heading"
        className="bg-ink px-6 py-[9vh] md:py-[12vh]"
      >
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce} className="text-center">
            <Kicker tone="dark">How connection works</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce} className="text-center">
            <h2
              id="how-connect-heading"
              className="mx-auto mt-4 max-w-[18ch] font-sofia text-[clamp(28px,3vw,46px)] font-medium leading-[1.1] tracking-[-0.02em] text-white"
            >
              Three steps, then it just runs.
            </h2>
          </Reveal>

          <div className="mt-14 grid grid-cols-1 gap-5 md:grid-cols-3">
            {CONNECT_STEPS.map(({ Icon, title, body }, i) => (
              <Reveal key={title} index={i} reduce={reduce}>
                <div className="flex h-full flex-col rounded-hims bg-white/[0.05] p-7 ring-1 ring-white/10">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-solace-mint/15 text-solace-mint ring-1 ring-solace-mint/25">
                      <Icon size={19} strokeWidth={1.9} aria-hidden="true" />
                    </span>
                    <span className="font-sofia text-[15px] font-semibold text-white/55">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                  </div>
                  <h3 className="mt-5 font-sofia text-[20px] font-medium leading-tight tracking-[-0.01em] text-white">
                    {title}
                  </h3>
                  <p className="mt-2 text-[14px] leading-relaxed text-white/65">
                    {body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ===== 4 · Sandbox CTA card ===== */}
      <section className="bg-white px-6 py-[9vh] md:py-[12vh]">
        <Reveal index={0} reduce={reduce} className="mx-auto max-w-[1100px]">
          <div
            className="flex flex-col items-start gap-6 overflow-hidden rounded-hims p-10 md:flex-row md:items-center md:justify-between md:p-14"
            style={{ backgroundImage: PALE_GRADIENT }}
          >
            <div className="max-w-2xl">
              <span className="inline-flex items-center gap-2 rounded-pill bg-white/80 px-3.5 py-1.5 text-[12px] font-semibold text-solace-green-700 shadow-soft">
                <FlaskConical size={14} aria-hidden="true" />
                No credentials
              </span>
              <h2 className="mt-5 font-sofia text-[clamp(26px,3vw,40px)] font-medium leading-[1.12] tracking-[-0.02em] text-ink">
                Try it now on the SMART Health IT sandbox.
              </h2>
              <p className="mt-4 max-w-xl text-base text-muted md:text-lg">
                See the full read-and-write loop against public FHIR R4 data
                before you touch a single vendor credential.
              </p>
            </div>
            <a
              href="https://solaceaidemo.vercel.app"
              target="_blank"
              rel="noreferrer"
              className="inline-flex shrink-0 items-center gap-2 rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
            >
              Launch the sandbox
              <ArrowRight size={15} aria-hidden="true" />
            </a>
          </div>
        </Reveal>
      </section>
    </div>
  );
}
