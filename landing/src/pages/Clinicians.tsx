import { useRef } from 'react';
import {
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
  type Variants,
} from 'framer-motion';
import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { FileText, Activity, MessagesSquare } from 'lucide-react';
import { APP_SCREENS, himsFade, himsMove } from '../lib/hims';
import useIsWide from '../lib/useIsWide';
import BigStatement from '../components/product/BigStatement';
import PhoneRig from '../components/product/PhoneRig';
import LaptopRig from '../components/product/LaptopRig';
import EhrScreen from '../components/product/EhrScreen';
import QueueScreen from '../components/product/QueueScreen';

/*
 * Clinicians: the "For Clinicians" page on the Product page's design system
 * (the app.forhims.com clone). Hims category rhythm: white opening statement →
 * waiting-room phones drifting beside copy → Atlas laptop showcase → parallax
 * feature tile band → gradient mega paragraph → dark queue act with circle
 * actions → white close. Every reveal rides the two house curves from
 * ../lib/hims; the only scroll-linked motion is the TileGrid drift idiom and
 * the rigs' own choreography.
 */

// The pale teal tile gradient, same stops as the Product tile wall.
const PALE_GRADIENT =
  'linear-gradient(166.14deg, rgb(232,244,247) 0%, rgb(199,229,221) 100%)';

// Deep green card variant for the second phone still.
const DEEP_GRADIENT =
  'linear-gradient(166.14deg, #1A7A5E 0%, #0F5132 55%, #0A3B25 100%)';

// Barely-there section washes, the hims band rhythm: each white band gets a
// faint tint, and adjacent sections meet on matching stops so the seams read
// as intentional. Strong-bg acts (ink, teal, the dark queue) stay untouched.
const WASH_WHITE_TO_MINT = 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';
const WASH_MINT_TO_WHITE = 'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)';
const WASH_WHITE_TO_LAV = 'linear-gradient(180deg, #ffffff 0%, #f4f4fb 100%)';
const WASH_LAV_TO_WHITE = 'linear-gradient(180deg, #f4f4fb 0%, #ffffff 100%)';
const WASH_PAPER = 'linear-gradient(180deg, #fafaf8 0%, #fafaf8 100%)';

// House reveal: opacity on HIMS_OUT (0.2s), y on HIMS_EXPO (0.6s), with the
// 0.04s-per-sibling stagger from the Product sections.
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
function Kicker({ tone, children }: { tone: 'light' | 'dark'; children: string }) {
  return (
    <p
      className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${
        tone === 'light' ? 'text-white/55' : 'text-muted'
      }`}
    >
      {children}
    </p>
  );
}

// The forhims phone card: a rounded gradient card whose curved edge crops the
// hand, with a real app still corner-pinned onto the glass.
function PhoneCard({
  screen,
  gradient,
  width = 'w-[min(440px,92%)]',
  reduce,
  delay = 0,
}: {
  screen: string;
  gradient: string;
  width?: string;
  reduce: boolean | null;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 48 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{
        opacity: { ...himsFade, delay },
        y: { ...himsMove, delay },
      }}
      className={`relative mx-auto ${width} overflow-hidden rounded-hims px-7 pt-10`}
      style={{ backgroundImage: gradient, aspectRatio: '1728 / 1910' }}
    >
      <PhoneRig
        alt=""
        screen={<img src={screen} alt="" className="mt-[13.5cqw] h-auto w-full" />}
      />
    </motion.div>
  );
}

// One typographic feature tile: rounded-tile, clipped, house fade-up reveal
// with the per-tile stagger.
function Tile({
  index,
  reduce,
  className = '',
  style,
  children,
}: {
  index: number;
  reduce: boolean | null;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{
        opacity: { ...himsFade, delay: index * 0.04 },
        y: { ...himsMove, delay: index * 0.04 },
      }}
      style={style}
      className={`relative overflow-hidden rounded-tile ${className}`}
    >
      {children}
    </motion.div>
  );
}

const PILL_DARK =
  'inline-flex items-center justify-center rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';
const PILL_LIGHT =
  'inline-flex items-center justify-center rounded-pill border border-ink/10 bg-white px-7 py-3.5 text-sm font-medium text-ink shadow-soft transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';

/* ===== 2 · Waiting room: copy beside two drifting phone cards ===== */
function WaitingRoom({ reduce }: { reduce: boolean | null }) {
  const ref = useRef<HTMLElement>(null);
  const isWide = useIsWide();
  const { scrollYProgress: p } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  });
  const still = reduce || !isWide;
  // Gentle counter-drift only: the cards live in separate grid columns, so
  // +-3vh in opposite directions can never bring them into contact.
  const yA = useTransform(p, [0, 1], still ? ['0vh', '0vh'] : ['3vh', '-3vh']);
  const yB = useTransform(p, [0, 1], still ? ['0vh', '0vh'] : ['-3vh', '3vh']);

  return (
    <section
      ref={ref}
      aria-labelledby="waiting-heading"
      className="overflow-hidden bg-white pb-[12vh] pt-[8vh] lg:pb-[18vh]"
      style={{ backgroundImage: WASH_MINT_TO_WHITE }}
    >
      <div className="mx-auto grid max-w-[1180px] items-center gap-14 px-6 lg:grid-cols-2 lg:gap-12">
        {/* --- Copy column --- */}
        <div>
          <Reveal index={0} reduce={reduce}>
            <Kicker tone="dark">Before you walk in</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="waiting-heading"
              className="mt-4 max-w-[14ch] font-sofia text-[clamp(34px,3.8vw,58px)] font-medium leading-[1.05] tracking-[-0.02em] text-ink"
            >
              It starts in the waiting room.
            </h2>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <p className="mt-7 max-w-[34ch] font-sofia text-[clamp(20px,1.7vw,26px)] font-medium leading-[1.45] tracking-[-0.01em] text-muted">
              <span className="text-ink">Your patient tells their story once,</span>{' '}
              on their own phone, in their own language. Medications, allergies
              and history land as a clean record, not a wall of loose notes.
            </p>
          </Reveal>
          <Reveal index={3} reduce={reduce}>
            <p className="mt-6 max-w-[36ch] text-base leading-relaxed text-muted">
              By the time you open the chart, it reads like a colleague already
              took the history for you.
            </p>
          </Reveal>
        </div>

        {/* --- Phone column: two cards side by side, two app moments. Each
               card owns a grid column, with a modest stagger on the second,
               so the gentle counter-drift can never make them touch. --- */}
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <motion.div style={{ y: yA }} className="will-change-transform">
            <PhoneCard
              screen={APP_SCREENS.meds}
              gradient={PALE_GRADIENT}
              width="w-full max-w-[440px]"
              reduce={reduce}
            />
          </motion.div>
          <motion.div style={{ y: yB }} className="will-change-transform md:mt-24">
            <PhoneCard
              screen={APP_SCREENS.medical}
              gradient={DEEP_GRADIENT}
              width="w-full max-w-[440px]"
              reduce={reduce}
              delay={0.08}
            />
          </motion.div>
        </div>
      </div>
    </section>
  );
}

/* ===== 4 · Feature tile band with the TileGrid drift idiom ===== */

const WATCH_LIST = ['Collapsed lung', 'Blood clot'] as const;
const TEST_CHIPS = ['ECG', 'Chest X-ray', 'Blood tests', 'Heart monitor'] as const;

function FeatureTiles({ reduce }: { reduce: boolean | null }) {
  const ref = useRef<HTMLElement>(null);
  const isWide = useIsWide();
  const { scrollYProgress: p } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  });
  const still = reduce || !isWide;
  const yUp = useTransform(p, [0, 1], still ? ['0vh', '0vh'] : ['6vh', '-6vh']);
  const yDown = useTransform(p, [0, 1], still ? ['0vh', '0vh'] : ['-6vh', '6vh']);

  return (
    <section
      ref={ref}
      aria-labelledby="tiles-heading"
      className="overflow-hidden bg-white py-[8vh]"
      style={{ backgroundImage: WASH_LAV_TO_WHITE }}
    >
      <h2 id="tiles-heading" className="sr-only">
        What Solace Atlas Does For Clinicians
      </h2>
      <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-2.5 px-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {/* --- The snapshot summary (ink, drifts up) --- */}
        <motion.div style={{ y: yUp }} className="will-change-transform">
          <Tile index={0} reduce={reduce} className="h-[340px] bg-ink sm:h-[380px]">
            <div className="flex h-full flex-col justify-between p-6">
              <div>
                <Kicker tone="light">The snapshot</Kicker>
                <div aria-hidden="true" className="mt-6 space-y-2.5">
                  <div className="h-2 w-[92%] rounded-full bg-white/15" />
                  <div className="h-2 w-[72%] rounded-full bg-white/15" />
                  <div className="h-2 w-[48%] rounded-full bg-white/15" />
                </div>
              </div>
              <div>
                <p className="font-sofia text-[28px] font-medium leading-tight tracking-[-0.02em] text-white">
                  The whole story, one glance.
                </p>
                <p className="mt-2 text-sm text-white/70">
                  what your patient said, summed up before you walk in.
                </p>
              </div>
            </div>
          </Tile>
        </motion.div>

        {/* --- The watch-list (deep green, drifts down) --- */}
        <motion.div style={{ y: yDown }} className="will-change-transform lg:pt-12">
          <Tile index={1} reduce={reduce} className="h-[340px] bg-solace-green-700 sm:h-[380px]">
            <div className="flex h-full flex-col justify-between p-6">
              <div>
                <Kicker tone="light">The watch-list</Kicker>
                <div className="mt-5 space-y-2">
                  {WATCH_LIST.map((name) => (
                    <div
                      key={name}
                      className="flex items-center gap-2 rounded-pill bg-white/10 px-3.5 py-2 ring-1 ring-white/15"
                    >
                      <span className="text-[13px] font-medium text-white">
                        {name}
                      </span>
                      <span className="ml-auto rounded-full bg-[#ba1a1a] px-2 py-[3px] text-[9px] font-bold uppercase tracking-[0.08em] text-white">
                        must not miss
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="font-sofia text-[28px] font-medium leading-tight tracking-[-0.02em] text-white">
                  Dangerous causes, never buried.
                </p>
                <p className="mt-2 text-sm text-white/70">
                  the ones to rule out, flagged on every patient.
                </p>
              </div>
            </div>
          </Tile>
        </motion.div>

        {/* --- Suggested tests (paper, drifts up) --- */}
        <motion.div style={{ y: yUp }} className="will-change-transform">
          <Tile
            index={2}
            reduce={reduce}
            className="h-[340px] bg-paper ring-1 ring-black/[0.06] sm:h-[380px]"
          >
            <div className="flex h-full flex-col justify-between p-6">
              <div>
                <Kicker tone="dark">Ready to order</Kicker>
                <div className="mt-5 flex flex-wrap gap-2">
                  {TEST_CHIPS.map((chip) => (
                    <span
                      key={chip}
                      className="rounded-pill bg-white px-3.5 py-1.5 text-[13px] font-medium text-ink ring-1 ring-black/[0.06]"
                    >
                      {chip}
                    </span>
                  ))}
                  <span className="rounded-pill px-2 py-1.5 text-[13px] font-medium text-muted">
                    + 7 more
                  </span>
                </div>
              </div>
              <div>
                <p className="font-sofia text-[28px] font-medium leading-tight tracking-[-0.02em] text-ink">
                  Tests, suggested.
                </p>
                <p className="mt-2 text-sm text-muted">
                  accept the ones you agree with, skip the rest.
                </p>
              </div>
            </div>
          </Tile>
        </motion.div>

        {/* --- Letters and inbox (pale teal, drifts down) --- */}
        <motion.div style={{ y: yDown }} className="will-change-transform lg:pt-12">
          <Tile
            index={3}
            reduce={reduce}
            className="h-[340px] sm:h-[380px]"
            style={{ backgroundImage: PALE_GRADIENT }}
          >
            <div className="relative flex h-full flex-col justify-between p-6">
              <div>
                <Kicker tone="dark">After the visit</Kicker>
                <div
                  aria-hidden="true"
                  className="mx-auto mt-5 w-[82%] -rotate-3 rounded-2xl bg-white p-4 shadow-pop"
                >
                  <div className="h-1.5 w-2/3 rounded-full bg-ink/15" />
                  <div className="mt-2 h-1.5 w-1/2 rounded-full bg-ink/15" />
                  <div className="mt-2 h-1.5 w-3/5 rounded-full bg-ink/15" />
                  <span className="mt-3 inline-block rounded-pill bg-ink px-3 py-1 text-[10px] font-semibold text-white">
                    Sign and send
                  </span>
                </div>
              </div>
              <div>
                <p className="font-sofia text-[28px] font-medium leading-tight tracking-[-0.02em] text-ink">
                  Letters and replies, drafted.
                </p>
                <p className="mt-2 text-sm text-muted">
                  you read, you sign, you send.
                </p>
              </div>
            </div>
          </Tile>
        </motion.div>
      </div>
    </section>
  );
}

/* ===== 6 · Dark act: mega type, circle actions, the live queue ===== */

const CIRCLES = [
  { label: 'Summary', Icon: FileText },
  { label: 'Vitals', Icon: Activity },
  { label: 'Transcript', Icon: MessagesSquare },
] as const;

function DarkAct({ reduce }: { reduce: boolean | null }) {
  // Circle pop-in: scale on HIMS_EXPO, fade on HIMS_OUT, staggered.
  const circleRow: Variants = {
    hidden: {},
    show: { transition: { staggerChildren: 0.12, delayChildren: 0.1 } },
  };
  const circleItem: Variants = {
    hidden: { opacity: 0, scale: reduce ? 1 : 0.6 },
    show: { opacity: 1, scale: 1, transition: { ...himsMove, opacity: himsFade } },
  };

  return (
    <section aria-labelledby="queue-heading" className="overflow-hidden bg-ink">
      {/* --- Mega type --- */}
      <div className="px-6 pt-[14vh] text-center">
        <Reveal index={0} reduce={reduce}>
          <h2
            id="queue-heading"
            className="mx-auto max-w-[10ch] font-sofia text-[clamp(52px,8.5vw,136px)] font-medium leading-[1.02] tracking-hims text-white"
          >
            Less typing. More medicine.
          </h2>
        </Reveal>
      </div>

      {/* --- Dark feature card with circle actions --- */}
      <div className="mt-[8vh] px-4 sm:px-6">
        <div
          className="mx-auto flex min-h-[56vh] max-w-[1180px] flex-col items-center justify-center overflow-hidden rounded-hims p-12 text-center lg:p-24"
          style={{
            backgroundImage:
              'radial-gradient(80% 60% at 50% 0%, rgba(31,191,143,0.18), rgba(31,191,143,0) 65%), linear-gradient(157deg, #11352c 0%, #0b231d 55%, #07150f 100%)',
          }}
        >
          <motion.h3
            initial={{ opacity: 0, y: reduce ? 0 : 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={{ ...himsMove, opacity: himsFade }}
            className="max-w-2xl font-sofia text-[clamp(28px,2.6vw,40px)] font-medium leading-[1.2] tracking-[-0.02em] text-white"
          >
            Everything about this patient, one tap away.
          </motion.h3>
          <motion.p
            initial={{ opacity: 0, y: reduce ? 0 : 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={{ ...himsMove, opacity: himsFade, delay: 0.08 }}
            className="mt-5 max-w-xl text-base text-white/70 md:text-lg"
          >
            The summary, the vitals and the full conversation. Open one, read
            it, move on.
          </motion.p>

          <motion.ul
            variants={circleRow}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, amount: 0.5 }}
            className="mt-14 flex flex-nowrap items-start justify-center gap-x-6 gap-y-8 sm:gap-x-10 lg:mt-16"
          >
            {CIRCLES.map(({ label, Icon }) => (
              <motion.li
                key={label}
                variants={circleItem}
                className="flex flex-col items-center gap-3"
              >
                <span className="flex h-16 w-16 items-center justify-center rounded-full bg-white text-ink shadow-pop sm:h-20 sm:w-20">
                  <Icon size={28} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <span className="text-sm font-medium text-white/80">{label}</span>
              </motion.li>
            ))}
          </motion.ul>
        </div>
      </div>

      {/* --- The live queue on the laptop --- */}
      <div className="mx-auto mt-[10vh] max-w-2xl px-6 text-center">
        <Reveal index={0} reduce={reduce}>
          <p className="text-base text-white/70 md:text-lg">
            The live queue shows who needs help first, with wait times that
            update every 15 seconds. When a patient presses My pain got worse,
            your team knows right away.
          </p>
        </Reveal>
      </div>
      <div className="mx-auto mt-[6vh] w-full max-w-[1100px] px-2.5 pb-[14vh] sm:px-6">
        <LaptopRig
          screen={<QueueScreen />}
          alt="Solace Atlas workspace: the live patient queue, wait times and pain alerts"
        />
      </div>
    </section>
  );
}

export default function Clinicians() {
  const reduce = useReducedMotion();

  return (
    <div className="bg-white">
      {/* ===== 1 · Opening statement ===== */}
      <section
        aria-labelledby="clinicians-heading"
        className="bg-white px-6 pb-[6vh] pt-[16vh] text-center"
        style={{ backgroundImage: WASH_WHITE_TO_MINT }}
      >
        <Reveal index={0} reduce={reduce}>
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted">
            For clinicians
          </p>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <h1
            id="clinicians-heading"
            className="mx-auto mt-5 max-w-[13ch] font-sofia text-[clamp(44px,7vw,104px)] font-medium leading-[1.02] tracking-hims text-ink"
          >
            Meet the story before the patient.
          </h1>
        </Reveal>
        <Reveal index={2} reduce={reduce}>
          <p className="mx-auto mt-7 max-w-xl text-base text-muted md:text-lg">
            A clear summary, the dangerous causes to rule out and the suggested
            tests, ready while your patient is still in the waiting room.
          </p>
        </Reveal>
        <Reveal index={3} reduce={reduce} className="mt-9">
          <Link to="/demo" className={PILL_DARK}>
            Book a Demo
          </Link>
        </Reveal>
      </section>

      {/* ===== 2 · Waiting room: copy + drifting phone cards ===== */}
      <WaitingRoom reduce={reduce} />

      {/* ===== 3 · Atlas showcase: the patient snapshot on the laptop ===== */}
      <section
        aria-labelledby="atlas-heading"
        className="overflow-hidden bg-white pb-[12vh]"
        style={{ backgroundImage: WASH_WHITE_TO_LAV }}
      >
        <div className="px-6 text-center">
          <Reveal index={0} reduce={reduce}>
            <Kicker tone="dark">Solace Atlas</Kicker>
          </Reveal>
          <Reveal index={1} reduce={reduce}>
            <h2
              id="atlas-heading"
              className="mx-auto mt-4 max-w-[22ch] font-sofia text-[clamp(28px,2.6vw,40px)] font-medium leading-[1.2] tracking-[-0.02em] text-ink"
            >
              Open the chart and the work is already started.
            </h2>
          </Reveal>
          <Reveal index={2} reduce={reduce}>
            <p className="mx-auto mt-5 max-w-xl text-base text-muted md:text-lg">
              The summary on top, the causes to rule out under it, the tests
              ready to order. Review it, change it, make it yours.
            </p>
          </Reveal>
        </div>
        <div className="mx-auto mt-[7vh] w-full max-w-[1100px] px-2.5 sm:px-6">
          <LaptopRig
            screen={<EhrScreen />}
            alt="Solace Atlas patient snapshot: a clear summary, the dangerous causes to rule out and the suggested tests"
          />
        </div>
      </section>

      {/* ===== 4 · Feature tile band ===== */}
      <FeatureTiles reduce={reduce} />

      {/* ===== 5 · Gradient mega paragraph, scrubbed word by word ===== */}
      <BigStatement
        className="text-grad-solace"
        text="It suggests, you decide. Everything the AI reads or writes is saved to the record, and a clinician always makes the final call."
      />

      {/* ===== 6 · Dark act: the live queue ===== */}
      <DarkAct reduce={reduce} />

      {/* ===== 7 · Close ===== */}
      <section
        aria-labelledby="close-heading"
        className="bg-white px-6 py-[16vh] text-center"
        style={{ backgroundImage: WASH_PAPER }}
      >
        <Reveal index={0} reduce={reduce}>
          <h2
            id="close-heading"
            className="mx-auto max-w-[16ch] font-sofia text-[clamp(38px,4.8vw,76px)] font-medium leading-[1.06] tracking-hims text-ink"
          >
            Bring Atlas to your team.
          </h2>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <p className="mx-auto mt-6 max-w-md text-base text-muted md:text-lg">
            Connects to your hospital systems through HL7 and FHIR. HIPAA-grade
            on AWS, with a public model card for every AI we ship. A clinician
            always makes the final call.
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
