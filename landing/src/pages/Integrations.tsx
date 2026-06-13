import { useReducedMotion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { ArrowRight, FlaskConical } from 'lucide-react';
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
import { ConnectionFlow } from '../components/integrations/GuideVisuals';

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
        className="group flex h-full flex-col rounded-tile bg-white p-6 shadow-card ring-1 ring-black/[0.06] transition-all duration-[400ms] ease-hims-expo hover:-translate-y-1 hover:shadow-lift hover:ring-solace-green-300/60"
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
        <div className="mt-6 flex items-center justify-between gap-3 border-t border-black/[0.05] pt-5">
          <TierChip tier={item.tier} />
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-solace-soft text-solace-green-700 transition-all duration-[400ms] ease-hims-expo group-hover:bg-solace-green-700 group-hover:text-white group-hover:translate-x-0.5">
            <ArrowRight size={16} aria-hidden="true" />
          </span>
        </div>
      </Link>
    </Reveal>
  );
}

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
          <Reveal index={0} reduce={reduce}>
            <div className="flex items-baseline justify-between gap-4 border-b border-black/[0.06] pb-5">
              <h2
                id="directory-heading"
                className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted"
              >
                The directory
              </h2>
              <span className="font-mono text-[12px] tabular-nums text-muted/60">
                {String(INTEGRATIONS.length).padStart(2, '0')} platforms
              </span>
            </div>
          </Reveal>
          <div className="mt-8 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
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
              One SMART launch, then it just runs.
            </h2>
          </Reveal>

          <div className="mt-14">
            <ConnectionFlow vendor="your EHR" reduce={reduce} tone="dark" />
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
