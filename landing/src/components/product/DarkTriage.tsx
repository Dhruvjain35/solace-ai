import { useRef } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useReducedMotion,
  type MotionValue,
  type Transition,
  type Variants,
} from 'framer-motion';
import { FileText, Activity, MessagesSquare, HeartPulse } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';
import LaptopRig from './LaptopRig';
import QueueScreen from './QueueScreen';
import EhrScreen from './EhrScreen';

/*
 * DarkTriage — the clinician act of the Product page, cloning the black "Care"
 * band of app.forhims.com (mega word → dark feature card with pinned circle
 * actions → app-window screenshots → purple gradient mega paragraph → white
 * app-icon tease), remapped onto Solace's triage terminal. Runs in normal
 * flow on bg-ink; only the screenshot pair and the gradient paragraph are
 * scroll-linked (parallax drift + per-word opacity scrub).
 */

// transforms ride HIMS_EXPO (600ms), opacity rides HIMS_OUT (200ms) — the
// same two-curve split every Product section uses.
const moveWithFade: Transition = { ...himsMove, opacity: himsFade };

const GRADIENT_COPY =
  'No more guessing from the doorway. Want the story before you walk in? Read one line, or read every word the patient said. Whatever works for you, works for us.';
const WORDS = GRADIENT_COPY.split(' ');

const CIRCLES = [
  { label: 'Summary', Icon: FileText },
  { label: 'Vitals', Icon: Activity },
  { label: 'Transcript', Icon: MessagesSquare },
] as const;

// One word of the gradient paragraph: opacity scrubs 0.16 → 1 as the scroll
// progress crosses this word's slice, exactly the reference's per-word reveal.
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

export default function DarkTriage() {
  const shotsRef = useRef<HTMLDivElement>(null);
  const gradRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  // Full parallax choreography only runs ≥lg.
  const isWide = useIsWide();

  // ---- Screenshot pair: two parallax rates so the cards drift apart ----
  const { scrollYProgress: shotsP } = useScroll({
    target: shotsRef,
    offset: ['start end', 'end start'],
  });
  const still = reduce || !isWide;
  // The laptop drives its own 3D entrance; only the browser card parallaxes.
  const shotY2 = useTransform(shotsP, [0, 1], still ? [0, 0] : [130, -90]);

  // ---- Gradient paragraph: per-word opacity scrub through mid-viewport ----
  const { scrollYProgress: gradP } = useScroll({
    target: gradRef,
    offset: ['start 0.85', 'end 0.45'],
  });

  // Circle pop-in: scale on HIMS_EXPO, fade on HIMS_OUT, staggered.
  const circleRow: Variants = {
    hidden: {},
    show: { transition: { staggerChildren: 0.12, delayChildren: 0.1 } },
  };
  const circleItem: Variants = {
    hidden: { opacity: 0, scale: reduce ? 1 : 0.6 },
    show: { opacity: 1, scale: 1, transition: moveWithFade },
  };

  return (
    <section
      aria-labelledby="triage-heading"
      className="overflow-hidden bg-ink"
    >
      {/* ===== 1 · Mega word ===== */}
      <div className="px-4 py-[10vh] text-center lg:py-[14vh]">
        <motion.h2
          id="triage-heading"
          initial={{ opacity: 0, y: reduce ? 0 : 90 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.4 }}
          transition={moveWithFade}
          className="font-sofia text-[clamp(110px,16vw,240px)] font-medium leading-none tracking-hims text-white"
        >
          Triage.
        </motion.h2>
      </div>

      {/* ===== 2 + 3 · Dark feature card with circle actions ===== */}
      <div className="px-4 sm:px-6">
        <div
          className="mx-auto flex min-h-[64vh] max-w-[1180px] flex-col items-center justify-center overflow-hidden rounded-hims p-12 text-center lg:p-24"
          style={{
            // A mint bloom at the card's top over the dark base — the depth
            // the reference's maroon-violet card gets from its inner glow.
            backgroundImage:
              'radial-gradient(80% 60% at 50% 0%, rgba(31,191,143,0.18), rgba(31,191,143,0) 65%), linear-gradient(157deg, #11352c 0%, #0b231d 55%, #07150f 100%)',
          }}
        >
          <motion.h3
            initial={{ opacity: 0, y: reduce ? 0 : 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={moveWithFade}
            className="max-w-2xl font-sofia text-[clamp(28px,2.6vw,40px)] font-medium leading-[1.2] tracking-[-0.02em] text-white"
          >
            Your clinicians meet the story before the patient
            reaches the bed.
          </motion.h3>
          <motion.p
            initial={{ opacity: 0, y: reduce ? 0 : 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={{ ...moveWithFade, delay: 0.08 }}
            className="mt-5 max-w-xl text-base text-white/70 md:text-lg"
          >
            The summary, the vitals and the full conversation. One tap each.
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
                <span className="text-sm font-medium text-white/80">
                  {label}
                </span>
              </motion.li>
            ))}
          </motion.ul>
        </div>
      </div>

      {/* ===== 4 · Clinician hardware: 3D laptop + floating EHR window ===== */}
      {/* Near full-bleed below sm so the DOM screens (cqw units) render as
          large as the viewport allows — the dashboards stay legible. */}
      <div
        ref={shotsRef}
        className="mx-auto mt-[8vh] w-full max-w-[1100px] px-3 sm:px-6"
      >
        <LaptopRig
          screen={<EhrScreen />}
          alt="Solace Atlas patient snapshot: the AI summary, possible causes with must-not-miss flags, and the reasons behind the urgency score"
        />
        {/* Second full laptop — the live workspace — mirroring the first. */}
        <motion.div
          style={{ y: still ? 0 : shotY2 }}
          className="relative z-10 mt-[6vh]"
        >
          <LaptopRig
            screen={<QueueScreen />}
            alt="Solace Atlas workspace: the live patient queue, ambient scribe and patient snapshot"
          />
        </motion.div>
      </div>

      {/* ===== 5 · Gradient mega paragraph, per-word scrub ===== */}
      <div ref={gradRef} className="mx-auto max-w-5xl px-6 py-[12vh] md:px-12">
        <p className="font-sofia text-[clamp(38px,5.8vw,84px)] font-medium leading-[1.16] tracking-[-0.02em]">
          {/* Screen readers get one continuous sentence; the word-split scrub
              layer is decorative (same pattern as BigStatement). */}
          <span className="sr-only">{GRADIENT_COPY}</span>
          <span aria-hidden="true">
            {WORDS.map((word, i) => (
              <ScrubWord
                key={`${word}-${i}`}
                progress={gradP}
                index={i}
                total={WORDS.length}
                reduce={reduce}
              >
                {word}
              </ScrubWord>
            ))}
          </span>
        </p>
      </div>

      {/* ===== 6 · Exit tease — hands off to the light closing act ===== */}
      <div className="flex justify-center py-[10vh]">
        <motion.div
          initial={{ opacity: 0, y: reduce ? 0 : 70 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.4 }}
          transition={moveWithFade}
          aria-hidden="true"
          className="flex aspect-square w-[min(40vw,320px)] items-center justify-center rounded-hims-lg bg-white shadow-halo"
        >
          <HeartPulse size={96} strokeWidth={1.5} className="text-ink" />
        </motion.div>
      </div>
    </section>
  );
}
