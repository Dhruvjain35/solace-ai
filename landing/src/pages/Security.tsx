import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';
import {
  ShieldCheck,
  EyeOff,
  FileCheck2,
  Lock,
  KeyRound,
  Network,
  ScrollText,
  Workflow,
  TestTube2,
  Timer,
  ArrowRight,
} from 'lucide-react';
import { himsFade, himsMove } from '../lib/hims';
import { Reveal } from '../components/legal/LegalLayout';

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

type Control = {
  icon: LucideIcon;
  kicker: string;
  title: string;
  body: string;
  points: string[];
};

const CONTROLS: Control[] = [
  {
    icon: EyeOff,
    kicker: 'PHI isolation',
    title: 'The model never sees raw PHI.',
    body: 'Our AI plans and narrates over coded, de-identified metadata and {slot} tokens. Names, MRNs, dates of birth and free-text notes are stripped before any prompt is built.',
    points: [
      'Raw identifiers replaced with slot tokens at the boundary',
      'An automated leak-gate test fails the build if real PHI reaches a prompt',
      'Re-identification happens only in your trusted runtime, never in a model call',
    ],
  },
  {
    icon: ShieldCheck,
    kicker: 'Consent gate',
    title: 'No consent, no AI. Enforced at the boundary.',
    body: 'A recorded-consent chokepoint sits in front of every AI request. With no consent on file the request is refused before it leaves your environment, and the refusal is logged.',
    points: [
      'Consent state checked on every AI invocation',
      'Refusals are explicit and recorded, not silent',
      'Patient can decline; the visit still works without the AI',
    ],
  },
  {
    icon: FileCheck2,
    kicker: 'Confirm-gated writes',
    title: 'Nothing reaches the chart without a click.',
    body: 'Solace runs a Plan to Execute to Narrate pipeline. The model proposes; it never executes tools directly. Every write-back is staged for a clinician to review and approve.',
    points: [
      'The model plans actions; your runtime executes them',
      'Write-backs are confirm-gated, never automatic',
      'The clinician always makes the final call',
    ],
  },
  {
    icon: Lock,
    kicker: 'Encryption',
    title: 'Encrypted in transit and at rest.',
    body: 'Data is encrypted everywhere with customer-managed AWS KMS keys. Application secrets live in AWS Secrets Manager and are never inlined into code or configuration.',
    points: [
      'Customer-managed KMS keys, in transit and at rest',
      'TLS-only storage; no plaintext object access',
      'Secrets in AWS Secrets Manager, rotated, never hardcoded',
    ],
  },
  {
    icon: KeyRound,
    kicker: 'Access control',
    title: 'Passwordless, role-scoped, tenant-isolated.',
    body: 'Sign-in is a single-use magic link, sessions are short-lived JWTs, and admin powers are role-scoped. Every workspace query carries a tenant-isolation check.',
    points: [
      'Passwordless magic-link sign-in, JWT sessions',
      'Role-scoped admin, least-privilege by default',
      'Tenant-isolation check enforced on every workspace query',
    ],
  },
  {
    icon: Network,
    kicker: 'Network & edge',
    title: 'Hardened at the edge with CloudFront + WAF.',
    body: 'Traffic enters through CloudFront and a WAF tuned with IP-reputation filters, OWASP managed rules and rate limiting. Outbound EHR calls are guarded against SSRF.',
    points: [
      'WAF: IP reputation, OWASP managed rules, rate limiting',
      'SSRF guards on every outbound EHR request',
      'TLS-only transport end to end',
    ],
  },
  {
    icon: ScrollText,
    kicker: 'Audit trail',
    title: 'Append-only, on every sensitive action.',
    body: 'Chart reads, AI requests, write-backs, sign-ins and admin changes all land in an append-only audit log, so a covered entity can reconstruct exactly what happened and when.',
    points: [
      'Append-only log of reads, AI calls and write-backs',
      'Sign-ins and admin changes recorded',
      'Available to covered entities for review under the BAA',
    ],
  },
  {
    icon: Workflow,
    kicker: 'Interoperability',
    title: 'SMART on FHIR v2, minimum-necessary scopes.',
    body: 'We connect over SMART on FHIR v2 and request only the minimum-necessary scopes for the task, in line with HIPAA section 164.502(b). We never ask for access we do not use.',
    points: [
      'SMART on FHIR v2 authorization',
      'Minimum-necessary scopes (HIPAA 164.502(b))',
      'No standing access beyond the active workflow',
    ],
  },
  {
    icon: Timer,
    kicker: 'Data minimization',
    title: 'Short-lived sessions, automatic expiry.',
    body: 'Intake sessions are short-lived and patient records and media carry an automatic TTL. Magic-link tokens are single-use and stored only as hashes, never in the clear.',
    points: [
      'Automatic TTL expiry on patient records and media',
      'Short-lived intake sessions',
      'Single-use magic-link tokens stored as hashes only',
    ],
  },
];

type Stat = { big: string; label: string };
const STATS: Stat[] = [
  { big: '749', label: 'automated tests every release' },
  { big: '0', label: 'raw PHI tokens allowed in any prompt' },
  { big: '100%', label: 'AI write-backs confirm-gated by a clinician' },
  { big: '1', label: 'tenant-isolation check on every query' },
];

const POSTURE = [
  {
    title: 'HIPAA Business Associate',
    status: 'In place',
    body: 'Solace operates as a Business Associate and will sign a BAA before any PHI is processed. Infrastructure runs on HIPAA-eligible AWS under a BAA; model inference runs via AWS Bedrock in covered regions.',
  },
  {
    title: 'SOC 2 Type II',
    status: 'In progress',
    body: 'Our SOC 2 program is underway. Current status, scope and the most recent observation period are available on request under NDA.',
  },
  {
    title: 'Penetration testing',
    status: 'On request',
    body: 'Independent testing summaries, our security questionnaire responses and architecture diagrams are available to qualified buyers during review.',
  },
] as const;

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

      {/* ===== 2 · Trust-signal stat row ===== */}
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
              className="relative overflow-hidden rounded-tile p-6 text-center"
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
                <p className="mt-3 text-[13px] leading-snug text-muted">
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

          <div className="mt-12 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
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
                  className="flex h-full flex-col rounded-hims border border-black/5 bg-white p-7 shadow-soft"
                >
                  <span className="inline-flex h-11 w-11 items-center justify-center rounded-tile bg-solace-soft text-solace-green-700">
                    <Icon size={22} strokeWidth={1.75} aria-hidden="true" />
                  </span>
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
            <span className="inline-flex h-11 w-11 items-center justify-center rounded-tile bg-white/10 text-solace-mint ring-1 ring-white/15">
              <TestTube2 size={22} strokeWidth={1.75} aria-hidden="true" />
            </span>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="process-heading"
              className="mt-6 max-w-[20ch] font-sofia text-[clamp(28px,3.2vw,52px)] font-medium leading-[1.06] tracking-hims text-white"
            >
              Tested like the safety control it is.
            </h2>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <p className="mt-6 max-w-2xl text-base leading-relaxed text-white/65 md:text-lg">
              Every release runs 749 automated tests, including dedicated suites
              for PHI isolation, tenant isolation and the consent gate. If raw
              PHI could reach a prompt, if a tenant could read another tenant, or
              if the consent chokepoint could be bypassed, the build does not
              ship.
            </p>
          </Reveal>
          <div className="mt-10 grid gap-3 sm:grid-cols-3">
            {[
              ['PHI-isolation suite', 'Proves no raw identifier reaches a model prompt.'],
              ['Tenant-isolation suite', 'Proves one workspace can never read another.'],
              ['Consent-gate suite', 'Proves no consent means no AI, every time.'],
            ].map(([title, body], i) => (
              <Reveal
                key={title}
                index={i + 3}
                reduce={reduce}
                className="rounded-hims bg-white/[0.04] p-6 ring-1 ring-white/10"
              >
                <p className="font-sofia text-[18px] font-medium tracking-[-0.02em] text-white">
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
            <h2
              id="posture-heading"
              className="max-w-[24ch] font-sofia text-[clamp(26px,2.6vw,40px)] font-medium leading-[1.1] tracking-hims text-ink"
            >
              Where our attestations stand today.
            </h2>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <p className="mt-4 max-w-2xl text-base text-muted">
              We would rather be precise than impressive. Here is the honest
              status, and what you can ask us for during a review.
            </p>
          </Reveal>
          <div className="mt-10 grid gap-3 md:grid-cols-3">
            {POSTURE.map((p, i) => (
              <Reveal
                key={p.title}
                index={i + 2}
                reduce={reduce}
                className="rounded-hims border border-black/5 bg-white p-7 shadow-soft"
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="font-sofia text-[18px] font-medium tracking-[-0.02em] text-ink">
                    {p.title}
                  </p>
                  <span className="shrink-0 rounded-pill bg-solace-soft px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-solace-green-700">
                    {p.status}
                  </span>
                </div>
                <p className="mt-4 text-[14px] leading-relaxed text-muted">
                  {p.body}
                </p>
              </Reveal>
            ))}
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
