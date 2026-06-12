import { useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
} from 'framer-motion';
import type { ReactNode } from 'react';
import { APP_SCREENS, himsFade, himsMove } from '../lib/hims';
import useIsWide from '../lib/useIsWide';
import BigStatement from '../components/product/BigStatement';
import PhoneRig from '../components/product/PhoneRig';

/*
 * Company — the "who we are" page, built on the Product page's design system
 * (the app.forhims.com clone): same two-curve reveals, same tile palette,
 * same pill CTAs. Scene order: white mega opening, gradient mission scrub
 * (BigStatement), the welcome screen on a phone beside the promise copy,
 * three drifting value tiles, a mega-type numbers band, the paper founder
 * note, and a centered pill-button close.
 *
 * Scroll choreography mirrors TileGrid: sections own a 0→1 progress across
 * their viewport transit, columns drift ±6vh against each other, all of it
 * gated behind useIsWide() and useReducedMotion().
 */

// The pale teal tile gradient extracted from the reference (same constant
// TileGrid uses; duplicated here because shared files stay untouched).
const PALE_GRADIENT =
  'linear-gradient(166.14deg, rgb(232,244,247) 0%, rgb(199,229,221) 100%)';

// Barely-there section washes, the hims band rhythm: adjacent sections meet
// on matching stops so the seams read as intentional. The mission scrub
// (BigStatement) stays on plain white between two white-edged washes.
const WASH_WHITE_TO_MINT = 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';
const WASH_MINT_TO_WHITE = 'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)';
const WASH_WHITE_TO_LAV = 'linear-gradient(180deg, #ffffff 0%, #f4f4fb 100%)';
const WASH_LAV_TO_WHITE = 'linear-gradient(180deg, #f4f4fb 0%, #ffffff 100%)';
const WASH_PAPER = 'linear-gradient(180deg, #fafaf8 0%, #fafaf8 100%)';

const MISSION =
  'Emergency rooms feel chaotic because nobody can see what is coming. Patients wait in the dark while care teams meet every story cold. Solace lets patients tell their story from their own phone, in their own language, so the team knows who needs help first. We build for the people in the waiting room and the people running it.';

const VALUES = [
  {
    title: 'Patients first, paperwork last.',
    sub: 'a photo of your card and your own words fill in the forms, so people get the attention.',
    tone: 'pale',
  },
  {
    title: 'The AI shows its work.',
    sub: 'everything it reads or writes is saved to the record. nothing hidden, ever.',
    tone: 'ink',
  },
  {
    title: 'Clinicians make the call.',
    sub: 'Solace prepares a clear summary. a clinician always makes the final decision.',
    tone: 'green',
  },
] as const;

// The numbers band: three typographic mega-tiles, each backed by a real
// shipped capability (20-language intake, ~7s spoken guidance, 15s wait
// refresh) — the same facts TileGrid's wall is built from.
const NUMBERS = [
  {
    kicker: 'Languages',
    big: '20',
    suffix: '',
    sub: 'speak or type in yours. your care team reads it in theirs.',
    tone: 'green',
  },
  {
    kicker: 'Spoken guidance',
    big: '~7',
    suffix: 'sec',
    sub: 'from telling your story to hearing what happens next.',
    tone: 'ink',
  },
  {
    kicker: 'Honest waits',
    big: '15',
    suffix: 'sec',
    sub: 'the wait time on your phone refreshes this often, so the number is real.',
    tone: 'pale',
  },
] as const;

const TILE_TONES = {
  pale: 'text-ink',
  ink: 'bg-ink text-white',
  green: 'bg-solace-green-700 text-white',
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

const PILL_PRIMARY =
  'inline-flex items-center justify-center rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';
const PILL_SECONDARY =
  'inline-flex items-center justify-center rounded-pill border border-ink/10 bg-white px-7 py-3.5 text-sm font-medium text-ink transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';

export default function Company() {
  const reduce = useReducedMotion();
  // Drift choreography only runs ≥lg; below that everything stacks calmly.
  const isWide = useIsWide();
  const still = reduce || !isWide;

  // ---- Welcome-phone section: the card drifts as it transits the viewport.
  const promiseRef = useRef<HTMLElement>(null);
  const { scrollYProgress: promiseP } = useScroll({
    target: promiseRef,
    offset: ['start end', 'end start'],
  });
  const phoneY = useTransform(
    promiseP,
    [0, 1],
    still ? ['0vh', '0vh'] : ['6vh', '-6vh'],
  );

  // ---- Value tiles: odd columns float up, even columns down (TileGrid idiom).
  const beliefsRef = useRef<HTMLElement>(null);
  const { scrollYProgress: beliefsP } = useScroll({
    target: beliefsRef,
    offset: ['start end', 'end start'],
  });
  const beliefsUp = useTransform(
    beliefsP,
    [0, 1],
    still ? ['0vh', '0vh'] : ['6vh', '-6vh'],
  );
  const beliefsDown = useTransform(
    beliefsP,
    [0, 1],
    still ? ['0vh', '0vh'] : ['-6vh', '6vh'],
  );

  // ---- Numbers band: same counter-drift, its own progress.
  const numbersRef = useRef<HTMLElement>(null);
  const { scrollYProgress: numbersP } = useScroll({
    target: numbersRef,
    offset: ['start end', 'end start'],
  });
  const numbersUp = useTransform(
    numbersP,
    [0, 1],
    still ? ['0vh', '0vh'] : ['6vh', '-6vh'],
  );
  const numbersDown = useTransform(
    numbersP,
    [0, 1],
    still ? ['0vh', '0vh'] : ['-6vh', '6vh'],
  );

  return (
    <div className="bg-white">
      {/* ===== 1 · Opening — white, centered mega type ===== */}
      <section
        aria-labelledby="company-heading"
        className="flex flex-col items-center px-6 pb-[8vh] pt-[26vh] text-center"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <Reveal index={0} reduce={reduce}>
          <h1
            id="company-heading"
            className="mx-auto max-w-[12ch] font-sofia text-[clamp(44px,7vw,104px)] font-medium leading-[1.02] tracking-hims text-ink"
          >
            Calm should be standard care.
          </h1>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <p className="mx-auto mt-7 max-w-md text-base text-muted md:text-lg">
            We are building emergency rooms where no one waits in the dark,
            not patients, and not the people caring for them.
          </p>
        </Reveal>
      </section>

      {/* ===== 2 · Mission — per-word gradient scrub ===== */}
      <BigStatement className="text-grad-solace" text={MISSION} />

      {/* ===== 3 · The promise — welcome screen on a phone, copy beside ===== */}
      <section
        ref={promiseRef}
        aria-labelledby="promise-heading"
        className="overflow-hidden bg-white py-[10vh]"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <div className="mx-auto grid max-w-[1180px] items-center gap-14 px-6 lg:grid-cols-2 lg:gap-10">
          {/* --- Copy column --- */}
          <div>
            <Reveal index={0} reduce={reduce}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
                Where it started
              </p>
            </Reveal>
            <Reveal index={1} reduce={reduce}>
              <h2
                id="promise-heading"
                className="mt-4 max-w-[14ch] font-sofia text-[clamp(34px,3.4vw,54px)] font-medium leading-[1.06] tracking-hims text-ink"
              >
                The first screen is a promise.
              </h2>
            </Reveal>
            <Reveal index={2} reduce={reduce}>
              <p className="mt-6 max-w-[46ch] text-base leading-relaxed text-muted md:text-lg">
                Before a single question gets asked, the app says the quiet
                part out loud: you&rsquo;re not waiting alone. A calm voice,
                your own language, and a clear picture of what happens next.
              </p>
            </Reveal>
            <Reveal index={3} reduce={reduce}>
              <p className="mt-5 max-w-[46ch] text-base leading-relaxed text-muted md:text-lg">
                Every screen we ship has to keep that promise. If it adds
                worry instead of taking worry away, it does not ship.
              </p>
            </Reveal>
          </div>

          {/* --- Welcome screen, in the hand+phone rig on a teal card.
                 The outer motion.div owns the scroll drift; the inner one
                 owns the one-time reveal (SideBySide's stacked pattern). --- */}
          <motion.div style={{ y: phoneY }} className="will-change-transform">
            <motion.div
              initial={{ opacity: 0, y: reduce ? 0 : 28 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ opacity: himsFade, y: himsMove }}
              className="relative mx-auto w-[min(440px,92%)] overflow-hidden rounded-hims px-7 pt-10"
              style={{
                backgroundImage: PALE_GRADIENT,
                aspectRatio: '1728 / 1910',
              }}
            >
              {/* Decorative — the copy column carries the message. */}
              <PhoneRig
                alt=""
                screen={
                  <img
                    src={APP_SCREENS.welcome}
                    alt=""
                    className="mt-[13.5cqw] h-auto w-full"
                  />
                }
              />
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* ===== 4 · What we believe — three drifting value tiles ===== */}
      <section
        ref={beliefsRef}
        aria-labelledby="beliefs-heading"
        className="overflow-hidden bg-white py-[10vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto max-w-[1180px] px-4 sm:px-6">
          <Reveal index={0} reduce={reduce}>
            <h2
              id="beliefs-heading"
              className="font-sofia text-[clamp(28px,2.4vw,40px)] font-medium leading-[1.04] tracking-[-0.02em] text-ink"
            >
              What we believe
            </h2>
          </Reveal>
          <div className="mt-8 grid gap-2.5 md:grid-cols-3">
            {VALUES.map((value, i) => (
              <motion.div
                key={value.title}
                style={{ y: i % 2 ? beliefsDown : beliefsUp }}
                className={`will-change-transform ${i === 1 ? 'md:pt-10' : ''}`}
              >
                <Reveal
                  index={i + 1}
                  reduce={reduce}
                  className={`relative h-[240px] overflow-hidden rounded-tile md:h-[360px] ${TILE_TONES[value.tone]}`}
                >
                  {value.tone === 'pale' ? (
                    <div
                      aria-hidden="true"
                      className="absolute inset-0"
                      style={{ backgroundImage: PALE_GRADIENT }}
                    />
                  ) : null}
                  <div className="relative flex h-full flex-col justify-end p-6">
                    <h3 className="font-sofia text-[clamp(26px,2.2vw,32px)] font-medium leading-[1.12] tracking-[-0.02em]">
                      {value.title}
                    </h3>
                    <p
                      className={`mt-3 text-sm leading-relaxed ${
                        value.tone === 'pale' ? 'text-muted' : 'text-white/70'
                      }`}
                    >
                      {value.sub}
                    </p>
                  </div>
                </Reveal>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== 5 · The numbers — three mega-type fact tiles ===== */}
      <section
        ref={numbersRef}
        aria-labelledby="numbers-heading"
        className="overflow-hidden bg-white py-[10vh]"
        style={{ backgroundImage: WASH_WHITE_TO_LAV }}
      >
        <h2 id="numbers-heading" className="sr-only">
          Solace By The Numbers
        </h2>
        <div className="mx-auto max-w-[1180px] px-4 sm:px-6">
          <div className="grid gap-2.5 md:grid-cols-3">
            {NUMBERS.map((fact, i) => (
              <motion.div
                key={fact.kicker}
                style={{ y: i % 2 ? numbersDown : numbersUp }}
                className={`will-change-transform ${i === 1 ? 'md:pt-12' : ''}`}
              >
                <Reveal
                  index={i}
                  reduce={reduce}
                  className={`relative h-[300px] overflow-hidden rounded-tile md:h-[420px] ${TILE_TONES[fact.tone]}`}
                >
                  {fact.tone === 'pale' ? (
                    <div
                      aria-hidden="true"
                      className="absolute inset-0"
                      style={{ backgroundImage: PALE_GRADIENT }}
                    />
                  ) : null}
                  <div className="relative flex h-full flex-col justify-between p-6">
                    <p
                      className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${
                        fact.tone === 'pale' ? 'text-muted' : 'text-white/55'
                      }`}
                    >
                      {fact.kicker}
                    </p>
                    <p className="font-sofia text-[clamp(72px,7.4vw,116px)] font-medium leading-none tracking-hims">
                      {fact.big}
                      {fact.suffix ? (
                        <span className="text-[0.42em]">&nbsp;{fact.suffix}</span>
                      ) : null}
                    </p>
                    <p
                      className={`text-sm leading-relaxed ${
                        fact.tone === 'pale' ? 'text-muted' : 'text-white/70'
                      }`}
                    >
                      {fact.sub}
                    </p>
                  </div>
                </Reveal>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== 6 · Founder note — paper card, signed by the team ===== */}
      <section
        aria-labelledby="note-heading"
        className="bg-white pb-[14vh] pt-[4vh]"
        style={{ backgroundImage: WASH_LAV_TO_WHITE }}
      >
        <div className="mx-auto max-w-[920px] px-4 sm:px-6">
          <Reveal index={0} reduce={reduce}>
            <div className="rounded-hims bg-paper p-10 md:p-14 lg:p-16">
              <p
                id="note-heading"
                className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted"
              >
                A note from the team
              </p>
              <p className="mt-6 font-sofia text-[clamp(22px,2.6vw,32px)] font-medium leading-[1.3] tracking-[-0.02em] text-ink">
                We started Solace after too many nights watching people wait
                in the dark. No sense of when, no one to ask, the hardest part
                of the emergency was the not knowing. So we are building the
                version of that night we wish our own families had. A calm
                voice in your language, an honest wait time, and a care team
                that already knows your story when they pull back the curtain.
              </p>
              <p className="mt-8 text-base font-medium text-muted">
                The Solace team
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ===== 7 · Close — centered CTA with pill buttons ===== */}
      <section
        aria-labelledby="cta-heading"
        className="bg-white pb-[18vh] pt-[6vh]"
        style={{ backgroundImage: WASH_PAPER }}
      >
        <div className="mx-auto flex max-w-3xl flex-col items-center px-6 text-center">
          <Reveal index={0} reduce={reduce}>
            <h2
              id="cta-heading"
              className="mx-auto max-w-[16ch] font-sofia text-[clamp(38px,4.8vw,76px)] font-medium leading-[1.06] tracking-hims text-ink"
            >
              Come see it working.
            </h2>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <p className="mx-auto mt-6 max-w-md text-base text-muted md:text-lg">
              Fifteen minutes is enough to see the whole flow, from the QR
              code in the waiting room to the note that writes itself.
            </p>
          </Reveal>
          <Reveal
            index={2}
            reduce={reduce}
            className="mt-9 flex flex-wrap items-center justify-center gap-3"
          >
            <Link to="/demo" className={PILL_PRIMARY}>
              Book a Demo
            </Link>
            <Link to="/clinicians" className={PILL_SECONDARY}>
              For Clinicians
            </Link>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
