import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import type { ReactNode } from 'react';
import { himsFade, himsMove } from '../lib/hims';
import BigStatement from '../components/product/BigStatement';

/*
 * Pricing — three typographic tier cards on the Product page's design system
 * (the app.forhims.com clone). White mega opening, the paper / ink / deep
 * green cards with hairline feature rows (no checkmark lists), a gradient
 * statement about what one subscription covers, and a single FAQ-style row
 * about the demo to close. Reveals ride the two house curves from ../lib/hims
 * with the 0.04s sibling stagger, zeroed under reduced motion.
 */

// Barely-there section washes, the hims band rhythm: adjacent sections meet
// on matching stops so the seams read as intentional.
const WASH_MINT_TO_WHITE = 'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)';
const WASH_WHITE_TO_MINT = 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';

type Tier = {
  name: string;
  price: string;
  per: string;
  who: string;
  rows: string[];
  cta: string;
  popular?: boolean;
  tone: 'paper' | 'ink' | 'green';
};

// The three tiers, in the house voice: plain sentences, no per-feature
// upcharges hiding behind asterisks, and the clinician always signs.
const TIERS: Tier[] = [
  {
    name: 'Solo',
    price: 'Free',
    per: 'for one clinician',
    who: 'start tonight, on your own.',
    rows: [
      'ambient notes for up to 50 visits a month',
      'letters and forms, drafted for you',
      'the clinical calculators, built in',
    ],
    cta: 'Start free',
    tone: 'paper',
  },
  {
    name: 'Group',
    price: '$99',
    per: 'per clinician, per month',
    who: 'for practices and emergency departments.',
    rows: [
      'everything in Solo, with no visit cap',
      'the live queue and the patient snapshot',
      'write-back into your hospital system',
      'patient intake in 20 languages',
    ],
    cta: 'Book a Demo',
    popular: true,
    tone: 'ink',
  },
  {
    name: 'Health system',
    price: '$199',
    per: 'per clinician, per month',
    who: 'for hospitals and networks of them.',
    rows: [
      'everything in Group',
      'value-based care reporting',
      'single sign-on for your whole staff',
      'encryption keys your hospital holds',
      'insurance approvals, drafted and tracked',
    ],
    cta: 'Talk to us',
    tone: 'green',
  },
];

// Card skins for the three tier tones: paper with a hairline ring, ink, and
// the deep solace green. Rows and secondary text follow the tone.
const TONES = {
  paper: {
    card: 'bg-paper ring-1 ring-black/[0.06] text-ink',
    sub: 'text-muted',
    row: 'border-black/5 text-muted',
    cta: 'bg-ink text-white',
  },
  ink: {
    card: 'bg-ink text-white',
    sub: 'text-white/70',
    row: 'border-white/10 text-white/70',
    cta: 'bg-white text-ink',
  },
  green: {
    card: 'bg-solace-green-700 text-white',
    sub: 'text-white/70',
    row: 'border-white/15 text-white/70',
    cta: 'bg-white text-ink',
  },
} as const;

// House reveal: opacity rides HIMS_OUT (0.2s), y rides HIMS_EXPO (0.6s),
// siblings stagger 0.04s by index. y is zeroed under reduced motion.
function Reveal({
  index = 0,
  reduce,
  className,
  children,
}: {
  index?: number;
  reduce: boolean | null;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{
        opacity: { ...himsFade, delay: index * 0.04 },
        y: { ...himsMove, delay: index * 0.04 },
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

function TierCard({
  tier,
  index,
  reduce,
}: {
  tier: Tier;
  index: number;
  reduce: boolean | null;
}) {
  const tone = TONES[tier.tone];
  return (
    <Reveal
      index={index + 1}
      reduce={reduce}
      className={`flex h-full flex-col overflow-hidden rounded-hims p-8 md:p-9 ${tone.card}`}
    >
      <div className="flex items-center justify-between gap-4">
        <p
          className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${
            tier.tone === 'paper' ? 'text-muted' : 'text-white/55'
          }`}
        >
          {tier.name}
        </p>
        {tier.popular ? (
          <span className="rounded-pill bg-white/10 px-3.5 py-1.5 text-[11px] font-medium text-white ring-1 ring-white/20">
            Most popular
          </span>
        ) : null}
      </div>

      <p className="mt-7 font-sofia text-[clamp(52px,4.4vw,72px)] font-medium leading-none tracking-hims">
        {tier.price}
      </p>
      <p className={`mt-2.5 text-sm ${tone.sub}`}>{tier.per}</p>

      <p
        className={`mt-7 font-sofia text-lg font-medium leading-snug tracking-[-0.01em] ${
          tier.tone === 'paper' ? 'text-ink' : 'text-white'
        }`}
      >
        {tier.who}
      </p>

      <div className="mt-5">
        {tier.rows.map((row) => (
          <p
            key={row}
            className={`border-t py-3.5 text-sm leading-relaxed ${tone.row}`}
          >
            {row}
          </p>
        ))}
      </div>

      <div className="mt-auto pt-8">
        <Link
          to="/demo"
          className={`inline-flex w-full items-center justify-center rounded-pill px-7 py-3.5 text-sm font-medium transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03] ${tone.cta}`}
        >
          {tier.cta}
        </Link>
      </div>
    </Reveal>
  );
}

export default function Pricing() {
  const reduce = useReducedMotion();

  return (
    <div className="bg-white">
      {/* ===== 1 · Opening — white, centered mega type ===== */}
      <section
        aria-labelledby="pricing-heading"
        className="flex flex-col items-center px-6 pb-[8vh] pt-[24vh] text-center"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <Reveal index={0} reduce={reduce}>
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted">
            Pricing
          </p>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <h1
            id="pricing-heading"
            className="mx-auto mt-5 max-w-[13ch] font-sofia text-[clamp(44px,7vw,104px)] font-medium leading-[1.02] tracking-hims text-ink"
          >
            Simple, honest pricing.
          </h1>
        </Reveal>
        <Reveal index={2} reduce={reduce}>
          <p className="mx-auto mt-7 max-w-md text-base text-muted md:text-lg">
            Start free on your own. Bring the whole team when you are ready.
            Everything in your tier is included, nothing sold back to you
            feature by feature.
          </p>
        </Reveal>
      </section>

      {/* ===== 2 · The three tiers ===== */}
      <section aria-labelledby="tiers-heading" className="bg-white pb-[6vh]">
        <h2 id="tiers-heading" className="sr-only">
          Solace Plans
        </h2>
        <div className="mx-auto grid max-w-[1180px] items-stretch gap-2.5 px-4 sm:px-6 lg:grid-cols-3">
          {TIERS.map((tier, i) => (
            <TierCard key={tier.name} tier={tier} index={i} reduce={reduce} />
          ))}
        </div>
        <Reveal index={4} reduce={reduce}>
          <p className="mx-auto mt-10 max-w-md px-6 text-center text-sm leading-relaxed text-muted">
            Every tier keeps the same rule: Solace drafts, your clinicians
            review and sign. Nothing reaches the chart on its own.
          </p>
        </Reveal>
      </section>

      {/* ===== 3 · What one subscription covers ===== */}
      <BigStatement
        className="text-grad-solace"
        text="One subscription covers the notes, the queue, the letters and the intake. About half what the big ambient scribes charge, with the whole front door included."
      />

      {/* ===== 4 · Close — one FAQ-style row about the demo ===== */}
      <section
        aria-labelledby="pricing-close-heading"
        className="bg-white pb-[16vh] pt-[2vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <div className="mx-auto max-w-[720px] px-6">
          <Reveal index={0} reduce={reduce}>
            <div className="border-t border-ink/10 pt-8">
              <h2
                id="pricing-close-heading"
                className="font-sofia text-lg font-medium text-ink"
              >
                Do we have to talk to sales first?
              </h2>
              <p className="mt-3 leading-relaxed text-muted">
                No. Book a demo, see the whole flow on a workflow that looks
                like yours, and start the same day. A full health-system
                rollout takes a few weeks, not quarters.
              </p>
            </div>
          </Reveal>
          <Reveal index={1} reduce={reduce} className="mt-9">
            <Link
              to="/demo"
              className="inline-flex items-center justify-center rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
            >
              Book a Demo
            </Link>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
