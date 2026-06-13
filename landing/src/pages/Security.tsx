import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { ShieldCheck, TestTube2, ArrowRight, Check } from 'lucide-react';
import { himsFade, himsMove } from '../lib/hims';
import { Reveal } from '../components/legal/LegalLayout';
import { PhiScrub, PipelineFlow, LeakGate } from '../components/security/Visuals';
import {
  CONTROLS,
  CONTROL_CATEGORIES,
  STATS,
  POSTURE,
} from '../components/security/data';

/*
 * Security — the marketing-grade trust page (not a legal document). It runs on
 * the Product / Company design system: two-curve reveals, font-sofia display,
 * the mint band rhythm, pill CTAs. A centered hero, a trust-signal stat row,
 * a grid of icon control cards grounded 1:1 in Solace's real architecture
 * (PHI isolation in code, the consent gate, confirm-gated writes, encryption,
 * access, network/WAF, audit, interop scopes, testing), a posture / "in
 * progress" attestations strip, and a CTA to /contact. Every claim maps to a
 * control that actually ships; nothing is framed as a certification Solace
 * does not yet hold.
 */

const WASH_WHITE_TO_MINT = 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';
const WASH_MINT_TO_WHITE = 'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)';
const PALE_GRADIENT =
  'linear-gradient(166.14deg, rgb(232,244,247) 0%, rgb(199,229,221) 100%)';

const PILL_PRIMARY =
  'inline-flex items-center justify-center gap-2 rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';
const PILL_SECONDARY =
  'inline-flex items-center justify-center gap-2 rounded-pill border border-ink/10 bg-white px-7 py-3.5 text-sm font-medium text-ink transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';

export default function Security() {
  const reduce = useReducedMotion();

  return (
    <div className="bg-white">
      {/* ===== 1 · Hero ===== */}
      <section
        aria-labelledby="security-heading"
        className="bg-white px-6 pb-[8vh] pt-[16vh] text-center md:pt-[24vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <Reveal index={0} reduce={reduce}>
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted">
            Security &amp; trust
          </p>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <h1
            id="security-heading"
            className="mx-auto mt-5 max-w-[15ch] font-sofia text-[clamp(42px,6.4vw,96px)] font-medium leading-[1.02] tracking-hims text-ink"
          >
            Built so the model never touches PHI.
          </h1>
        </Reveal>
        <Reveal index={2} reduce={reduce}>
          <p className="mx-auto mt-7 max-w-2xl text-base text-muted md:text-lg">
            Solace handles the most sensitive data in medicine. So our defenses
            are not policy promises, they are enforced in code, on every request,
            and verified on every release.
          </p>
        </Reveal>
        <Reveal
          index={3}
          reduce={reduce}
          className="mt-9 flex flex-wrap items-center justify-center gap-3"
        >
          <Link to="/contact" className={PILL_PRIMARY}>
            Book a security review
            <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
          </Link>
          <Link to="/contact" className={PILL_SECONDARY}>
            Request our security docs
          </Link>
        </Reveal>
      </section>

      {/* ===== 2 · PHI isolation — the before/after demonstration ===== */}
      <section
        aria-labelledby="phiscrub-heading"
        className="bg-white px-6 py-[8vh] md:py-[12vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce}>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-solace-green-600">
              PHI isolation, shown
            </p>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="phiscrub-heading"
              className="mt-4 max-w-[20ch] font-sofia text-[clamp(28px,3.2vw,48px)] font-medium leading-[1.08] tracking-hims text-ink"
            >
              See exactly what the model receives.
            </h2>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <p className="mt-4 max-w-2xl text-base text-muted md:text-lg">
              The same patient, on both sides of the boundary. Names, MRNs, dates
              of birth and free text never cross it; the model reasons over coded
              metadata and a single slot token.
            </p>
          </Reveal>
          <Reveal index={3} reduce={reduce} className="mt-10">
            <PhiScrub />
          </Reveal>
          <Reveal index={4} reduce={reduce}>
            <p className="mt-6 text-center text-[13px] text-muted/80">
              Re-identification happens only in your trusted runtime — never in a model call.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ===== 2b · Plan / Execute / Narrate pipeline ===== */}
      <section aria-labelledby="pipeline-heading" className="bg-white px-6 py-[8vh] md:py-[11vh]">
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce}>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-solace-green-600">
              How a request flows
            </p>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="pipeline-heading"
              className="mt-4 max-w-[22ch] font-sofia text-[clamp(28px,3.2vw,48px)] font-medium leading-[1.08] tracking-hims text-ink"
            >
              The model halves never touch raw data.
            </h2>
          </Reveal>
          <Reveal index={2} reduce={reduce} className="mt-10">
            <PipelineFlow />
          </Reveal>
        </div>
      </section>

      {/* ===== 2c · The leak-gate test ===== */}
      <section aria-labelledby="leakgate-heading" className="bg-white px-6 pb-[10vh]">
        <div className="mx-auto grid max-w-[1100px] items-center gap-10 lg:grid-cols-2">
          <div>
            <Reveal index={0} reduce={reduce}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-solace-green-600">
                Enforced, not promised
              </p>
            </Reveal>
            <Reveal index={1} reduce={reduce}>
              <h2
                id="leakgate-heading"
                className="mt-4 font-sofia text-[clamp(26px,2.8vw,42px)] font-medium leading-[1.1] tracking-hims text-ink"
              >
                If PHI could reach a prompt, the build stops.
              </h2>
            </Reveal>
            <Reveal index={2} reduce={reduce}>
              <p className="mt-4 max-w-md text-base leading-relaxed text-muted">
                The isolation boundary is a test, not a guideline. It runs on
                every commit and fails the release if a single raw identifier can
                make it into a model prompt.
              </p>
            </Reveal>
          </div>
          <Reveal index={3} reduce={reduce}>
            <LeakGate />
          </Reveal>
        </div>
      </section>

      {/* ===== 3 · Trust-signal stat row ===== */}
      <section
        aria-label="Security at a glance"
        className="bg-white px-6 py-[8vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto grid max-w-[1100px] grid-cols-2 gap-3 md:grid-cols-4">
          {STATS.map((s, i) => (
            <Reveal
              key={s.label}
              index={i}
              reduce={reduce}
              className="group relative overflow-hidden rounded-tile p-6 text-center ring-1 ring-solace-green-300/30 transition-transform duration-[400ms] ease-hims-expo hover:-translate-y-1"
            >
              <div
                aria-hidden="true"
                className="absolute inset-0"
                style={{ backgroundImage: PALE_GRADIENT }}
              />
              <div className="relative">
                <p className="font-sofia text-[clamp(40px,5vw,64px)] font-medium leading-none tracking-hims text-ink">
                  {s.big}
                </p>
                <p className="mx-auto mt-3 max-w-[18ch] text-[13px] leading-snug text-muted">
                  {s.label}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ===== 3 · The controls grid ===== */}
      <section
        aria-labelledby="controls-heading"
        className="bg-white px-6 py-[10vh]"
      >
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce}>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
              The controls
            </p>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="controls-heading"
              className="mt-4 max-w-[22ch] font-sofia text-[clamp(28px,3vw,46px)] font-medium leading-[1.08] tracking-hims text-ink"
            >
              Nine layers, every one of them load-bearing.
            </h2>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <div className="mt-6 flex flex-wrap items-center gap-2.5">
              {CONTROL_CATEGORIES.map((g) => (
                <span
                  key={g}
                  className="inline-flex items-center gap-1.5 rounded-pill bg-solace-soft px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-solace-green-700 ring-1 ring-solace-green-300/40"
                >
                  {g}
                </span>
              ))}
            </div>
          </Reveal>

          <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {CONTROLS.map((c, i) => {
              const Icon = c.icon;
              return (
                <motion.div
                  key={c.title}
                  initial={{ opacity: 0, y: reduce ? 0 : 28 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.25 }}
                  transition={{
                    opacity: { ...himsFade, delay: (i % 3) * 0.04 },
                    y: { ...himsMove, delay: (i % 3) * 0.04 },
                  }}
                  className="group flex h-full flex-col rounded-hims border border-black/[0.06] bg-white p-7 shadow-soft transition-all duration-[400ms] ease-hims-expo hover:-translate-y-1 hover:border-solace-green-300/50 hover:shadow-lift"
                >
                  <div className="flex items-start justify-between">
                    <span className="inline-flex h-11 w-11 items-center justify-center rounded-tile bg-solace-soft text-solace-green-700 ring-1 ring-solace-green-300/30 transition-colors duration-[400ms] ease-hims-expo group-hover:bg-solace-green-700 group-hover:text-white group-hover:ring-transparent">
                      <Icon size={22} strokeWidth={1.75} aria-hidden="true" />
                    </span>
                    <span className="font-mono text-[12px] font-medium tabular-nums text-muted/40">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                  </div>
                  <p className="mt-5 text-[11px] font-semibold uppercase tracking-[0.16em] text-solace-green-600">
                    {c.kicker}
                  </p>
                  <h3 className="mt-2 font-sofia text-[20px] font-medium leading-[1.2] tracking-[-0.02em] text-ink">
                    {c.title}
                  </h3>
                  <p className="mt-3 text-[14.5px] leading-relaxed text-muted">
                    {c.body}
                  </p>
                  <ul className="mt-5 space-y-2 border-t border-black/5 pt-5">
                    {c.points.map((point) => (
                      <li
                        key={point}
                        className="flex items-start gap-2.5 text-[13.5px] leading-snug text-ink"
                      >
                        <ShieldCheck
                          size={15}
                          strokeWidth={2}
                          aria-hidden="true"
                          className="mt-0.5 shrink-0 text-solace-green-500"
                        />
                        {point}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-5 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted/50">
                    {c.cat}
                  </p>
                </motion.div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ===== 4 · Testing & process, on ink ===== */}
      <section
        aria-labelledby="process-heading"
        className="bg-ink px-6 py-[12vh]"
      >
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce}>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-solace-mint/70">
              Verified every release
            </p>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <span className="mt-5 inline-flex h-11 w-11 items-center justify-center rounded-tile bg-white/10 text-solace-mint ring-1 ring-white/15">
              <TestTube2 size={22} strokeWidth={1.75} aria-hidden="true" />
            </span>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <h2
              id="process-heading"
              className="mt-6 max-w-[20ch] font-sofia text-[clamp(28px,3.2vw,52px)] font-medium leading-[1.06] tracking-hims text-white"
            >
              Tested like the safety control it is.
            </h2>
          </Reveal>
          <Reveal index={3} reduce={reduce}>
            <p className="mt-6 max-w-2xl text-base leading-relaxed text-white/65 md:text-lg">
              Every release runs 749 automated tests, including dedicated suites
              for PHI isolation, tenant isolation and the consent gate. If raw
              PHI could reach a prompt, if a tenant could read another tenant, or
              if the consent chokepoint could be bypassed, the build does not
              ship.
            </p>
          </Reveal>
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {[
              ['PHI-isolation suite', 'Proves no raw identifier reaches a model prompt.'],
              ['Tenant-isolation suite', 'Proves one workspace can never read another.'],
              ['Consent-gate suite', 'Proves no consent means no AI, every time.'],
            ].map(([title, body], i) => (
              <Reveal
                key={title}
                index={i + 4}
                reduce={reduce}
                className="group rounded-hims bg-white/[0.04] p-6 ring-1 ring-white/10 transition-colors duration-[400ms] ease-hims-expo hover:bg-white/[0.07] hover:ring-solace-mint/30"
              >
                <span className="flex items-center gap-2 text-solace-mint">
                  <Check size={15} strokeWidth={2.5} aria-hidden="true" />
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-solace-mint/70">
                    Pass
                  </span>
                </span>
                <p className="mt-3 font-sofia text-[18px] font-medium tracking-[-0.02em] text-white">
                  {title}
                </p>
                <p className="mt-2 text-[14px] leading-relaxed text-white/55">
                  {body}
                </p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ===== 5 · Posture / attestations ===== */}
      <section
        aria-labelledby="posture-heading"
        className="bg-white px-6 py-[10vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <div className="mx-auto max-w-[1100px]">
          <Reveal index={0} reduce={reduce}>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
              Attestations
            </p>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="posture-heading"
              className="mt-4 max-w-[24ch] font-sofia text-[clamp(26px,2.6vw,40px)] font-medium leading-[1.1] tracking-hims text-ink"
            >
              Where our attestations stand today.
            </h2>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <p className="mt-4 max-w-2xl text-base text-muted">
              We would rather be precise than impressive. Here is the honest
              status, and what you can ask us for during a review.
            </p>
          </Reveal>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {POSTURE.map((p, i) => {
              const live = p.status === 'In place';
              const chip = live
                ? 'bg-solace-green-700 text-white ring-solace-green-700'
                : 'bg-solace-soft text-solace-green-700 ring-solace-green-300/50';
              return (
                <Reveal
                  key={p.title}
                  index={i + 3}
                  reduce={reduce}
                  className="group flex h-full flex-col rounded-hims border border-black/[0.06] bg-white p-7 shadow-soft transition-all duration-[400ms] ease-hims-expo hover:-translate-y-1 hover:shadow-lift"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-sofia text-[18px] font-medium tracking-[-0.02em] text-ink">
                      {p.title}
                    </p>
                    <span
                      className={`inline-flex shrink-0 items-center gap-1.5 rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide ring-1 ${chip}`}
                    >
                      <span
                        aria-hidden="true"
                        className={`h-1.5 w-1.5 rounded-full ${
                          live ? 'bg-solace-mint' : 'bg-solace-green-500'
                        }`}
                      />
                      {p.status}
                    </span>
                  </div>
                  <p className="mt-4 text-[14px] leading-relaxed text-muted">
                    {p.body}
                  </p>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ===== 6 · Close — CTA to contact ===== */}
      <section
        aria-labelledby="security-cta-heading"
        className="bg-white px-6 pb-[18vh] pt-[6vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
          <Reveal index={0} reduce={reduce}>
            <h2
              id="security-cta-heading"
              className="mx-auto max-w-[18ch] font-sofia text-[clamp(34px,4.4vw,68px)] font-medium leading-[1.06] tracking-hims text-ink"
            >
              Let your security team kick the tires.
            </h2>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <p className="mx-auto mt-6 max-w-md text-base text-muted md:text-lg">
              We will walk your team through the architecture, share our SOC 2
              status and questionnaire, and answer the hard questions.
            </p>
          </Reveal>
          <Reveal
            index={2}
            reduce={reduce}
            className="mt-9 flex flex-wrap items-center justify-center gap-3"
          >
            <Link to="/contact" className={PILL_PRIMARY}>
              Book a security review
              <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
            </Link>
            <Link to="/hipaa" className={PILL_SECONDARY}>
              See our HIPAA posture
            </Link>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
