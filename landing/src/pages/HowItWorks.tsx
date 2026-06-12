import { useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from 'framer-motion';
import type { CSSProperties, ReactNode } from 'react';
import { APP_SCREENS, himsFade, himsMove } from '../lib/hims';
import useIsWide from '../lib/useIsWide';
import BigStatement from '../components/product/BigStatement';
import LaptopRig from '../components/product/LaptopRig';
import EhrScreen from '../components/product/EhrScreen';
import LettersScreen from '../components/product/LettersScreen';
import PhoneRig from '../components/product/PhoneRig';

/*
 * How it works — the complete start-to-finish journey on the Product page's
 * design system (the app.forhims.com clone). The numbered steps alternate
 * with phone cards showing the matching app moment, so the journey is shown,
 * not just described: lang after 02, symptoms + questions at 03, insurance
 * after 04, the explained plan after 05. The clinician half flips to the ink
 * stage, scrubs a gradient statement word by word, then opens the Atlas
 * laptop. Reveals ride the two house curves from ../lib/hims; the phone
 * cards drift on the TileGrid scroll-parallax idiom (≥lg, motion-safe only).
 */

// The pale teal tile gradient, same stops as the Product tile wall.
const PALE_GRADIENT =
  'linear-gradient(166.14deg, rgb(232,244,247) 0%, rgb(199,229,221) 100%)';

// Deep evergreen card, the dark sibling of the teal card (DarkTriage's hue).
const DEEP_GRADIENT =
  'linear-gradient(166.14deg, #14583E 0%, #0C3D2B 55%, #07291D 100%)';

// Barely-there section washes, the hims band rhythm: adjacent sections meet
// on matching stops so the seams read as intentional. The ink act and the
// gradient statement stay untouched.
const WASH_WHITE_TO_MINT = 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';
const WASH_MINT_TO_WHITE = 'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)';
const WASH_PAPER = 'linear-gradient(180deg, #fafaf8 0%, #fafaf8 100%)';

type Step = { num: string; title: string; sub: string };

const PATIENT_STEPS: Step[] = [
  {
    num: '01',
    title: 'Scan the code.',
    sub: 'a QR code in the waiting room opens Solace on their own phone. nothing to install.',
  },
  {
    num: '02',
    title: 'Pick a language.',
    sub: 'twenty languages, spoken and written. the whole visit happens in theirs.',
  },
  {
    num: '03',
    title: 'Tell your story.',
    sub: 'talk naturally or type. the AI asks two or three follow-up questions that fit, and every answer is saved for the care team.',
  },
  {
    num: '04',
    title: 'Snap the insurance card.',
    sub: 'one photo and the details fill themselves in. no clipboard, no spelling out a member ID.',
  },
  {
    num: '05',
    title: 'Know where you stand.',
    sub: 'a clear priority, an honest wait time that updates every 15 seconds, and spoken guidance back in about 7 seconds.',
  },
  {
    num: '06',
    title: 'Never wait in the dark.',
    sub: 'pain got worse? one press and the care team knows right away.',
  },
];

const CLINICIAN_STEPS: Step[] = [
  {
    num: '07',
    title: 'The live queue.',
    sub: 'everyone waiting, who needs help first, at a glance. your clinicians always make the final call.',
  },
  {
    num: '08',
    title: 'The patient snapshot.',
    sub: 'a clear summary, the dangerous causes to rule out, and the suggested tests.',
  },
  {
    num: '09',
    title: 'Notes that write themselves.',
    sub: 'talk to your patient. the note drafts while you do.',
  },
  {
    num: '10',
    title: 'The paperwork, handled.',
    sub: 'work notes, school notes, insurance forms and two dozen more, drafted from the visit. your clinician reviews and signs.',
  },
  {
    num: '11',
    title: 'Into the chart.',
    sub: 'everything lands in your hospital system through HL7 and FHIR, and every AI step is saved to the record.',
  },
];

// Gradient statement scrubbed word by word on the ink stage, before the
// laptop opens (the DarkTriage idiom).
const CLINICIAN_STATEMENT =
  'The wait becomes a head start. The queue, the summary and the full conversation are ready before you open the door. Solace suggests, your clinicians decide.';
const STATEMENT_WORDS = CLINICIAN_STATEMENT.split(' ');

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

// Tiny uppercase kicker, the Product tile pattern.
function Kicker({ tone = 'light', children }: { tone?: 'light' | 'dark'; children: string }) {
  return (
    <p
      className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${
        tone === 'dark' ? 'text-white/55' : 'text-muted'
      }`}
    >
      {children}
    </p>
  );
}

// One numbered step as a two-column editorial row ≥lg: hairline on top, the
// dimmed numeral and display title on the left, one plain sub-line on the
// right. Index drives the 0.04s stagger within each visual group.
function StepRow({
  step,
  index,
  reduce,
  tone = 'light',
}: {
  step: Step;
  index: number;
  reduce: boolean | null;
  tone?: 'light' | 'dark';
}) {
  const dark = tone === 'dark';
  return (
    <Reveal
      index={index}
      reduce={reduce}
      className={`grid grid-cols-1 gap-x-10 gap-y-3 py-9 md:py-12 lg:grid-cols-[1fr,minmax(0,400px)] ${
        dark ? 'border-t border-white/10' : 'border-t border-black/5'
      }`}
    >
      <div className="flex items-baseline gap-x-5 md:gap-x-8">
        <span
          aria-hidden="true"
          className={`shrink-0 font-sofia text-[clamp(30px,3.4vw,52px)] font-medium leading-none tracking-[-0.02em] ${
            dark ? 'text-solace-mint/40' : 'text-solace-green-600/40'
          }`}
        >
          {step.num}
        </span>
        <h3
          className={`font-sofia text-[clamp(26px,2.6vw,40px)] font-medium leading-[1.08] tracking-[-0.02em] ${
            dark ? 'text-white' : 'text-ink'
          }`}
        >
          {step.title}
        </h3>
      </div>
      <p
        className={`max-w-xl text-base leading-relaxed md:text-lg lg:self-center lg:justify-self-end ${
          dark ? 'text-white/60' : 'text-muted'
        }`}
      >
        {step.sub}
      </p>
    </Reveal>
  );
}

// The four card skins the phone moments sit in: teal tile gradient, deep
// evergreen, plain paper, and ink. Same recipe as SideBySide's stacked card.
const CARD_VARIANTS: Record<
  'teal' | 'deep' | 'paper' | 'ink',
  { className: string; style?: CSSProperties; label: string }
> = {
  teal: {
    className: '',
    style: { backgroundImage: PALE_GRADIENT },
    label: 'bg-white/80 text-ink',
  },
  deep: {
    className: '',
    style: { backgroundImage: DEEP_GRADIENT },
    label: 'bg-white/10 text-white ring-1 ring-white/20',
  },
  paper: {
    className: 'bg-paper ring-1 ring-black/[0.06]',
    label: 'bg-white text-ink shadow-soft',
  },
  ink: {
    className: 'bg-ink',
    label: 'bg-white/10 text-white ring-1 ring-white/20',
  },
};

// One phone moment: the PhoneRig inside a rounded card whose curved bottom
// edge crops the hand (the forhims composite pattern), revealed on the two
// house curves and drifting ±6vh across its viewport transit — the TileGrid
// column-drift idiom, gated to ≥lg and motion-safe.
function PhoneCard({
  screen,
  variant,
  drift = 'up',
  label,
  widthClass = 'w-[min(460px,92%)]',
  wrapClassName = '',
}: {
  screen: string;
  variant: keyof typeof CARD_VARIANTS;
  drift?: 'up' | 'down';
  label: string;
  widthClass?: string;
  wrapClassName?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const isWide = useIsWide();

  const { scrollYProgress: p } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  });
  const still = reduce || !isWide;
  const y = useTransform(
    p,
    [0, 1],
    still ? ['0vh', '0vh'] : drift === 'up' ? ['6vh', '-6vh'] : ['-6vh', '6vh'],
  );

  const skin = CARD_VARIANTS[variant];

  return (
    <div className={wrapClassName}>
      <motion.div ref={ref} style={{ y }} className="will-change-transform">
        <motion.div
          initial={{ opacity: 0, y: reduce ? 0 : 28 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ opacity: himsFade, y: himsMove }}
          className={`relative mx-auto overflow-hidden rounded-hims px-7 pt-10 ${widthClass} ${skin.className}`}
          style={{ aspectRatio: '1728 / 1910', ...skin.style }}
        >
          <span
            className={`absolute left-7 top-7 z-20 rounded-pill px-4 py-2 text-[12px] font-medium backdrop-blur ${skin.label}`}
          >
            {label}
          </span>
          <PhoneRig
            alt=""
            screen={<img src={screen} alt="" className="mt-[13.5cqw] h-auto w-full" />}
          />
        </motion.div>
      </motion.div>
    </div>
  );
}

// One word of the clinician statement: opacity scrubs 0.16 → 1 as the scroll
// progress crosses this word's slice (the DarkTriage per-word reveal).
function ScrubWord({
  progress,
  index,
  total,
  reduce,
  children,
}: {
  progress: MotionValue<number>;
  index: number;
  total: number;
  reduce: boolean | null;
  children: string;
}) {
  const opacity = useTransform(
    progress,
    [index / total, (index + 1) / total],
    [0.16, 1],
  );
  return (
    <motion.span style={{ opacity: reduce ? 1 : opacity }} className="text-grad-dark">
      {children}{' '}
    </motion.span>
  );
}

const PILL_DARK =
  'inline-flex items-center justify-center rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';
const PILL_LIGHT =
  'inline-flex items-center justify-center rounded-pill border border-ink/10 bg-white px-7 py-3.5 text-sm font-medium text-ink shadow-soft transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';

export default function HowItWorks() {
  const reduce = useReducedMotion();
  const gradRef = useRef<HTMLDivElement>(null);

  // Per-word opacity scrub for the clinician statement through mid-viewport.
  const { scrollYProgress: gradP } = useScroll({
    target: gradRef,
    offset: ['start 0.85', 'end 0.45'],
  });

  return (
    <div className="bg-white">
      {/* ===== 1 · Opening — white, centered mega type ===== */}
      <section
        aria-labelledby="hiw-heading"
        className="bg-white px-6 pb-[10vh] pt-[26vh] text-center"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <Reveal index={0} reduce={reduce}>
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted">
            How it works
          </p>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <h1
            id="hiw-heading"
            className="mx-auto mt-5 max-w-[13ch] font-sofia text-[clamp(44px,7vw,104px)] font-medium leading-[1.02] tracking-hims text-ink"
          >
            From the front door to the chart.
          </h1>
        </Reveal>
        <Reveal index={2} reduce={reduce}>
          <p className="mx-auto mt-7 max-w-xl text-base text-muted md:text-lg">
            Every step a patient takes, and everything your team sees, in one
            calm flow.
          </p>
        </Reveal>
      </section>

      {/* ===== 2 · The patient's side — steps alternating with the app ===== */}
      <section
        aria-labelledby="patient-side-heading"
        className="overflow-hidden bg-white pb-[12vh] pt-[4vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <div className="mx-auto max-w-[1100px] px-6">
          <Reveal index={0} reduce={reduce}>
            <Kicker>The patient&rsquo;s side</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="patient-side-heading"
              className="mt-4 max-w-[20ch] font-sofia text-[clamp(28px,2.6vw,40px)] font-medium leading-[1.15] tracking-[-0.02em] text-ink"
            >
              From their own phone, in their own words.
            </h2>
          </Reveal>

          {/* 01 · 02 */}
          <div className="mt-12 md:mt-16">
            {PATIENT_STEPS.slice(0, 2).map((step, i) => (
              <StepRow key={step.num} step={step} index={i} reduce={reduce} />
            ))}
          </div>

          {/* the language picker, on the deep evergreen card */}
          <PhoneCard
            screen={APP_SCREENS.lang}
            variant="deep"
            drift="up"
            label="their language, from the first tap"
            wrapClassName="my-[8vh] lg:pr-[32%]"
          />

          {/* 03 */}
          <StepRow step={PATIENT_STEPS[2]} index={0} reduce={reduce} />

          {/* the story, told — and the follow-up questions it earns */}
          <div className="my-[8vh] grid gap-10 md:grid-cols-2 md:gap-6">
            <PhoneCard
              screen={APP_SCREENS.symptoms}
              variant="teal"
              drift="up"
              label="spoken or typed, their words"
              widthClass="w-[min(420px,92%)]"
            />
            <PhoneCard
              screen={APP_SCREENS.questions}
              variant="ink"
              drift="down"
              label="two or three questions that fit"
              widthClass="w-[min(420px,92%)]"
              wrapClassName="md:mt-16"
            />
          </div>

          {/* 04 */}
          <StepRow step={PATIENT_STEPS[3]} index={0} reduce={reduce} />

          {/* the card scan, on paper */}
          <PhoneCard
            screen={APP_SCREENS.insurance}
            variant="paper"
            drift="down"
            label="one photo, the form fills itself"
            wrapClassName="my-[8vh] lg:pl-[32%]"
          />

          {/* 05 */}
          <StepRow step={PATIENT_STEPS[4]} index={0} reduce={reduce} />

          {/* the explained plan, on teal */}
          <PhoneCard
            screen={APP_SCREENS.plan}
            variant="teal"
            drift="up"
            label="a clear place in line"
            wrapClassName="my-[8vh]"
          />

          {/* 06 */}
          <StepRow step={PATIENT_STEPS[5]} index={0} reduce={reduce} />
        </div>
      </section>

      {/* ===== Handoff · gradient mega paragraph ===== */}
      <BigStatement
        className="text-grad-solace"
        text="By the time a clinician says your name, your story is already on their screen."
      />

      {/* ===== 3 · The clinician's side — the ink stage ===== */}
      <section
        aria-labelledby="clinician-side-heading"
        className="overflow-hidden bg-ink pb-[14vh] pt-[12vh]"
      >
        <div className="mx-auto max-w-[1100px] px-6">
          <Reveal index={0} reduce={reduce}>
            <Kicker tone="dark">The clinician&rsquo;s side</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="clinician-side-heading"
              className="mt-4 max-w-[20ch] font-sofia text-[clamp(28px,2.6vw,40px)] font-medium leading-[1.15] tracking-[-0.02em] text-white"
            >
              Ready before you walk in.
            </h2>
          </Reveal>

          <div className="mt-12 md:mt-16">
            {CLINICIAN_STEPS.map((step, i) => (
              <StepRow key={step.num} step={step} index={i} reduce={reduce} tone="dark" />
            ))}
          </div>
        </div>

        {/* gradient statement, scrubbed word by word */}
        <div ref={gradRef} className="mx-auto max-w-5xl px-6 py-[12vh] md:px-12">
          <p className="font-sofia text-[clamp(34px,5vw,72px)] font-medium leading-[1.16] tracking-[-0.02em]">
            <span className="sr-only">{CLINICIAN_STATEMENT}</span>
            <span aria-hidden="true">
              {STATEMENT_WORDS.map((word, i) => (
                <ScrubWord
                  key={`${word}-${i}`}
                  progress={gradP}
                  index={i}
                  total={STATEMENT_WORDS.length}
                  reduce={reduce}
                >
                  {word}
                </ScrubWord>
              ))}
            </span>
          </p>
        </div>

        {/* the Atlas laptop, scroll-tilting open on the dark stage */}
        <div className="px-6 text-center">
          <Reveal index={0} reduce={reduce}>
            <p className="mx-auto max-w-xl text-base text-white/60 md:text-lg">
              This is the screen your team sees while the patient is still in
              the waiting room.
            </p>
          </Reveal>
        </div>
        <div className="mx-auto mt-[6vh] w-full max-w-[1100px] px-2.5 sm:px-6">
          <LaptopRig
            screen={<EhrScreen />}
            alt="The Solace clinician view: the patient summary, the causes to rule out and the reasons behind the suggested priority"
          />
        </div>

        {/* the letters workspace: the admin side nobody else shows */}
        <div className="mt-[14vh] px-6 text-center">
          <Reveal index={0} reduce={reduce}>
            <p className="mx-auto max-w-xl text-base text-white/60 md:text-lg">
              And when the visit ends, the paperwork is already waiting.
              Work notes, school notes and forms, drafted from the chart.
            </p>
          </Reveal>
        </div>
        <div className="mx-auto mt-[6vh] w-full max-w-[1100px] px-2.5 sm:px-6">
          <LaptopRig
            screen={<LettersScreen />}
            alt="The Solace letters workspace: two dozen chart-aware templates with a drafted work note ready to review and sign"
          />
        </div>
      </section>

      {/* ===== 4 · Close — centered CTA with pill buttons ===== */}
      <section
        aria-labelledby="hiw-close-heading"
        className="bg-white px-6 py-[16vh] text-center"
        style={{ backgroundImage: WASH_PAPER }}
      >
        <Reveal index={0} reduce={reduce}>
          <h2
            id="hiw-close-heading"
            className="mx-auto max-w-[16ch] font-sofia text-[clamp(38px,4.8vw,76px)] font-medium leading-[1.06] tracking-hims text-ink"
          >
            See the whole flow live.
          </h2>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <p className="mx-auto mt-6 max-w-md text-base text-muted md:text-lg">
            twenty minutes, on a workflow that looks like yours.
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
            Try the Patient Flow
          </a>
        </Reveal>
      </section>
    </div>
  );
}
