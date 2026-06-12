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
import ProductWord from './ProductWord';
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

// The pre-arrival brief, as a clinician actually receives it: a summary line,
// the vitals strip, and the patient's own words. Replaces the old row of empty
// circle buttons — same three facets, but shown as real content.
const BRIEF_ROWS = [
  {
    label: 'Summary',
    Icon: FileText,
    body: (
      <>58M, exertional chest tightness radiating to the left arm. One hour, worsening.</>
    ),
  },
  {
    label: 'Vitals',
    Icon: Activity,
    body: (
      <span className="font-mono text-[13px] tracking-[0.02em] text-white/80">
        HR 118 · BP 148/92 · SpO₂ 94% · Temp 99.1°F
      </span>
    ),
  },
  {
    label: 'Transcript',
    Icon: MessagesSquare,
    body: (
      <span className="italic text-white/75">
        “It started after I climbed the stairs and it just won't ease up.”
      </span>
    ),
  },
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
      {/* ===== 1 · Mega word — slides in from the left (Intake came from the
          right, so consecutive acts feel like panels sliding through) ===== */}
      <div className="px-4 py-[10vh] text-center lg:py-[14vh]">
        <ProductWord
          id="triage-heading"
          word="Triage."
          from="left"
          className="text-[clamp(110px,16vw,240px)] text-white"
        />
      </div>

      {/* ===== 2 + 3 · Dark feature card with the pre-arrival brief ===== */}
      <div className="px-4 sm:px-6">
        <div
          className="mx-auto grid max-w-[1180px] items-center gap-10 overflow-hidden rounded-hims p-8 sm:p-12 lg:grid-cols-2 lg:gap-16 lg:p-20"
          style={{
            // A mint bloom at the card's top-left over the dark base — the depth
            // the reference's maroon-violet card gets from its inner glow.
            backgroundImage:
              'radial-gradient(70% 70% at 18% 0%, rgba(31,191,143,0.20), rgba(31,191,143,0) 62%), linear-gradient(157deg, #11352c 0%, #0b231d 55%, #07150f 100%)',
          }}
        >
          {/* Left: the claim */}
          <div className="text-center lg:text-left">
            <motion.p
              initial={{ opacity: 0, y: reduce ? 0 : 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.6 }}
              transition={moveWithFade}
              className="text-[12px] font-semibold uppercase tracking-[0.18em] text-solace-green-300/80"
            >
              Before the patient arrives
            </motion.p>
            <motion.h3
              initial={{ opacity: 0, y: reduce ? 0 : 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.5 }}
              transition={{ ...moveWithFade, delay: 0.05 }}
              className="mt-4 font-sofia text-[clamp(28px,2.6vw,42px)] font-medium leading-[1.12] tracking-[-0.02em] text-white"
            >
              Your clinicians meet the story before the patient reaches the bed.
            </motion.h3>
            <motion.p
              initial={{ opacity: 0, y: reduce ? 0 : 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.5 }}
              transition={{ ...moveWithFade, delay: 0.1 }}
              className="mt-5 text-base leading-relaxed text-white/65 md:text-lg"
            >
              The summary, the vitals, and the patient's own words. Ready the
              moment they pick up the chart.
            </motion.p>
          </div>

          {/* Right: the brief itself, as the care team sees it */}
          <motion.div
            variants={circleRow}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, amount: 0.4 }}
            className="overflow-hidden rounded-hims-lg bg-white/[0.05] ring-1 ring-white/10 backdrop-blur-sm"
          >
            {/* Brief header: who's coming + acuity */}
            <motion.div
              variants={circleItem}
              className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4"
            >
              <div className="flex min-w-0 items-center gap-3">
                <img
                  src="/assets/faces/patient-marcus.jpg"
                  alt=""
                  loading="lazy"
                  className="h-11 w-11 shrink-0 rounded-full object-cover ring-2 ring-white/15"
                />
                <div className="min-w-0">
                  <p className="truncate font-sofia text-[17px] font-medium tracking-[-0.01em] text-white">
                    Marcus R. · 58
                  </p>
                  <p className="text-[12px] text-white/45">Arriving · ~4 min out</p>
                </div>
              </div>
              <span className="shrink-0 rounded-pill bg-solace-green-500/15 px-3 py-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-solace-green-300 ring-1 ring-solace-green-500/30">
                ESI 2 · Urgent
              </span>
            </motion.div>

            {/* The three facets, as real rows */}
            <ul className="divide-y divide-white/[0.07]">
              {BRIEF_ROWS.map(({ label, Icon, body }) => (
                <motion.li
                  key={label}
                  variants={circleItem}
                  className="flex items-start gap-4 px-6 py-5"
                >
                  <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-ink shadow-pop">
                    <Icon size={17} strokeWidth={1.9} aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-white/40">
                      {label}
                    </p>
                    <p className="mt-1.5 text-[15px] leading-relaxed text-white/90">
                      {body}
                    </p>
                  </div>
                </motion.li>
              ))}
            </ul>
          </motion.div>
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
