import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';
import {
  CalendarCheck,
  ShieldCheck,
  Plug,
  LifeBuoy,
  Newspaper,
  Mail,
  Check,
  ArrowRight,
} from 'lucide-react';
import { himsFade, himsMove } from '../lib/hims';
import { submitLead, mailtoLead } from '../lib/lead';

/*
 * Contact — a premium contact page on the Product / Company design system.
 * The landing has no backend, so the form composes a prefilled mailto: to
 * hello@solace.health and shows a graceful success state once opened. A hero,
 * a grid of contact reasons (each an icon + line), the mailto form, and a
 * primary "Book a Demo" path to /demo. Reveals run on the two house curves and
 * are reduced-motion safe; the mailto pattern needs no network.
 */

const CONTACT_EMAIL = 'hello@solace.health';

const WASH_WHITE_TO_MINT = 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';
const WASH_MINT_TO_WHITE = 'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)';

type Reason = {
  icon: LucideIcon;
  title: string;
  body: string;
  topic: string;
};

const REASONS: Reason[] = [
  {
    icon: CalendarCheck,
    title: 'Book a demo',
    body: 'See the live queue and the patient snapshot working, in about 20 minutes.',
    topic: 'Demo request',
  },
  {
    icon: ShieldCheck,
    title: 'Security review',
    body: 'Walk your security team through the architecture, our SOC 2 status and questionnaire.',
    topic: 'Security review',
  },
  {
    icon: Plug,
    title: 'Integrations',
    body: 'SMART on FHIR v2, HL7 and EHR specifics for your environment.',
    topic: 'Integrations',
  },
  {
    icon: LifeBuoy,
    title: 'Support',
    body: 'Already running Solace and need a hand? We are here.',
    topic: 'Support',
  },
  {
    icon: Newspaper,
    title: 'Press',
    body: 'Media, analyst and speaking requests for the Solace team.',
    topic: 'Press',
  },
];

const TOPICS = REASONS.map((r) => r.topic);

const INPUT_CLASS =
  'mt-2 w-full rounded-pill border border-black/10 bg-white px-5 py-3.5 text-base text-ink placeholder:text-muted/60 outline-none transition-colors duration-200 focus:border-solace-green-500';

function reveal(reduce: boolean | null, i: number) {
  return {
    initial: { opacity: 0, y: reduce ? 0 : 28 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, amount: 0.3 },
    transition: {
      opacity: { ...himsFade, delay: i * 0.04 },
      y: { ...himsMove, delay: i * 0.04 },
    },
  } as const;
}

export default function Contact() {
  const reduce = useReducedMotion();
  const uid = useId();
  const [sent, setSent] = useState(false);
  const [topic, setTopic] = useState(TOPICS[0]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const lead = {
      name: String(data.get('name') ?? '').trim(),
      email: String(data.get('email') ?? '').trim(),
      org: String(data.get('org') ?? '').trim(),
      message: String(data.get('message') ?? '').trim(),
      website: String(data.get('website') ?? ''), // honeypot
      topic,
      source: 'contact' as const,
    };
    setSent(true);
    // Try the /api/lead backend; fall back to a prefilled mailto compose if it
    // isn't configured or the network fails, so a lead is never lost.
    const ok = await submitLead(lead);
    if (!ok) mailtoLead(lead);
  }

  return (
    <div className="bg-white">
      {/* ===== 1 · Hero ===== */}
      <section
        aria-labelledby="contact-heading"
        className="bg-white px-6 pb-[6vh] pt-[16vh] text-center md:pt-[24vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <motion.p
          {...reveal(reduce, 0)}
          className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted"
        >
          Contact
        </motion.p>
        <motion.h1
          id="contact-heading"
          {...reveal(reduce, 1)}
          className="mx-auto mt-5 max-w-[15ch] font-sofia text-[clamp(42px,6.4vw,96px)] font-medium leading-[1.02] tracking-hims text-ink"
        >
          Let&rsquo;s talk.
        </motion.h1>
        <motion.p
          {...reveal(reduce, 2)}
          className="mx-auto mt-7 max-w-xl text-base text-muted md:text-lg"
        >
          Tell us what you need and the right person on our team will reach out.
          We reply within one business day.
        </motion.p>
        <motion.div
          {...reveal(reduce, 3)}
          className="mt-9 flex flex-wrap items-center justify-center gap-3"
        >
          <Link
            to="/demo"
            className="inline-flex items-center justify-center gap-2 rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
          >
            Book a demo
            <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
          </Link>
          <a
            href={`mailto:${CONTACT_EMAIL}`}
            className="inline-flex items-center justify-center gap-2 rounded-pill border border-ink/10 bg-white px-7 py-3.5 text-sm font-medium text-ink transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
          >
            <Mail size={16} strokeWidth={2} aria-hidden="true" />
            {CONTACT_EMAIL}
          </a>
        </motion.div>
      </section>

      {/* ===== 2 · Reasons grid + form ===== */}
      <section
        aria-label="Ways to reach us"
        className="bg-white px-6 pb-[10vh] pt-[6vh] md:pb-[14vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto grid max-w-[1100px] gap-12 lg:grid-cols-[1fr_minmax(0,480px)] lg:gap-16">
          {/* --- Reasons --- */}
          <div>
            <motion.h2
              {...reveal(reduce, 0)}
              className="font-sofia text-[clamp(24px,2.4vw,36px)] font-medium leading-[1.1] tracking-hims text-ink"
            >
              What can we help with?
            </motion.h2>
            <div className="mt-8 space-y-3">
              {REASONS.map((r, i) => {
                const Icon = r.icon;
                return (
                  <motion.button
                    key={r.title}
                    type="button"
                    onClick={() => setTopic(r.topic)}
                    {...reveal(reduce, i + 1)}
                    className={`flex w-full items-start gap-4 rounded-hims border bg-white p-5 text-left transition-colors duration-200 ${
                      topic === r.topic
                        ? 'border-solace-green-500 shadow-soft'
                        : 'border-black/5 hover:border-black/10'
                    }`}
                  >
                    <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-tile bg-solace-soft text-solace-green-700">
                      <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
                    </span>
                    <span>
                      <span className="block font-sofia text-[17px] font-medium tracking-[-0.02em] text-ink">
                        {r.title}
                      </span>
                      <span className="mt-1 block text-[14px] leading-relaxed text-muted">
                        {r.body}
                      </span>
                    </span>
                  </motion.button>
                );
              })}
            </div>
          </div>

          {/* --- Form (mailto, no backend) --- */}
          <motion.div
            {...reveal(reduce, 1)}
            className="h-fit rounded-hims bg-paper p-8 ring-1 ring-black/5 md:p-10 lg:sticky lg:top-32"
          >
            {sent ? (
              <div className="flex min-h-[420px] flex-col items-center justify-center text-center">
                <span className="inline-flex h-14 w-14 items-center justify-center rounded-tile bg-solace-soft text-solace-green-700">
                  <Check size={28} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <p className="mt-6 font-sofia text-2xl font-medium tracking-[-0.02em] text-ink">
                  Your email is ready.
                </p>
                <p className="mt-3 max-w-xs text-[15px] leading-relaxed text-muted">
                  We opened your mail app with the message prefilled to{' '}
                  {CONTACT_EMAIL}. Hit send and we will reply within one business
                  day.
                </p>
                <button
                  type="button"
                  onClick={() => setSent(false)}
                  className="mt-7 text-sm font-medium text-ink underline underline-offset-4 decoration-ink/30 transition-colors hover:decoration-ink"
                >
                  Compose another
                </button>
              </div>
            ) : (
              <form className="space-y-5" onSubmit={handleSubmit}>
                <div>
                  <label
                    htmlFor={`${uid}-topic`}
                    className="text-sm font-medium text-ink"
                  >
                    Topic
                  </label>
                  <select
                    id={`${uid}-topic`}
                    name="topic"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    className={`${INPUT_CLASS} appearance-none`}
                  >
                    {TOPICS.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label
                    htmlFor={`${uid}-name`}
                    className="text-sm font-medium text-ink"
                  >
                    Full name
                  </label>
                  <input
                    id={`${uid}-name`}
                    name="name"
                    required
                    type="text"
                    placeholder="Dr. Jordan Lee"
                    autoComplete="name"
                    className={INPUT_CLASS}
                  />
                </div>
                <div>
                  <label
                    htmlFor={`${uid}-email`}
                    className="text-sm font-medium text-ink"
                  >
                    Work email
                  </label>
                  <input
                    id={`${uid}-email`}
                    name="email"
                    required
                    type="email"
                    placeholder="you@hospital.org"
                    autoComplete="email"
                    className={INPUT_CLASS}
                  />
                </div>
                <div>
                  <label
                    htmlFor={`${uid}-org`}
                    className="text-sm font-medium text-ink"
                  >
                    Organization
                  </label>
                  <input
                    id={`${uid}-org`}
                    name="org"
                    type="text"
                    placeholder="North Texas ED"
                    autoComplete="organization"
                    className={INPUT_CLASS}
                  />
                </div>
                <div>
                  <label
                    htmlFor={`${uid}-message`}
                    className="text-sm font-medium text-ink"
                  >
                    How can we help?
                  </label>
                  <textarea
                    id={`${uid}-message`}
                    name="message"
                    rows={4}
                    placeholder="A line or two about what you are looking for."
                    className="mt-2 w-full rounded-hims border border-black/10 bg-white px-5 py-3.5 text-base text-ink placeholder:text-muted/60 outline-none transition-colors duration-200 focus:border-solace-green-500"
                  />
                </div>
                <button
                  type="submit"
                  className="w-full rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
                >
                  Send message
                </button>
                <p className="text-center text-[12.5px] leading-relaxed text-muted">
                  This opens your mail app with everything prefilled, or write us
                  directly at {CONTACT_EMAIL}.
                </p>
              </form>
            )}
          </motion.div>
        </div>
      </section>
    </div>
  );
}
