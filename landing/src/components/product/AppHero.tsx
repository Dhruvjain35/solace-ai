import { useRef } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useReducedMotion,
  type MotionValue,
} from 'framer-motion';
import { HIMS_EXPO, himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';
import PhoneRig from './PhoneRig';

/*
 * AppHero — section 1 of the Product page, a structural clone of the
 * app.forhims.com hero ("Total care. Totally different.") remapped onto
 * Solace. A giant inset rounded card pins a full-screen stage; as you scroll
 * the 300vh track, the headline lifts away, the hand+phone rises from the
 * bottom and grows toward the camera, and three lines of ghost mega type
 * ("it's / all in / the app.") sweep vertically behind it — the reference's
 * lilac glow kept as a faint memory under a Solace mint radial.
 */

// Bottom-rising radial glow: mint with the reference's lilac remembered at 45%.
// Explicit size keywords so narrow viewports get a soft bloom, not a banded
// column (the reference floods the lower two-thirds of the hero card).
const GLOW_GRADIENT =
  'radial-gradient(95% 70% at 50% 100%, rgba(31,191,143,0.42), rgba(150,133,255,0.26) 42%, rgba(255,255,255,0) 70%)';

// Ghost-type sweep bands across track progress (start, end). Bands overlap on
// purpose — one line exits the top as the next enters the bottom, so a line
// is always on stage while the phone grows.
// Mobile bands: the 220vh track sweeps faster, so each line gets a wider
// slice and the parade ends before the section boundary enters the frame.
const GHOST_BANDS_M = [
  [0.16, 0.4],
  [0.32, 0.56],
  [0.48, 0.74],
] as const;

const GHOST_BANDS = [
  [0.14, 0.36],
  [0.32, 0.54],
  [0.5, 0.72],
] as const;

// One line of ghost mega type sweeping vertically behind the phone. Decorative
// only (the h1 carries the message), so the whole layer is aria-hidden by the
// parent. Under reduced motion the sweep is zeroed and the opacity profile
// becomes a triangle so superimposed lines never read double.
function GhostLine({
  progress,
  band,
  reduce,
  shift = '0vw',
  children,
}: {
  progress: MotionValue<number>;
  band: readonly [number, number];
  reduce: boolean | null;
  /** Horizontal offset so the word reads beside the phone, not behind it. */
  shift?: string;
  children: React.ReactNode;
}) {
  const [a, b] = band;
  const span = b - a;
  const opacity = useTransform(
    progress,
    reduce ? [a, a + span / 2, b] : [a, a + span * 0.3, b - span * 0.3, b],
    reduce ? [0, 1, 0] : [0, 1, 1, 0],
  );
  // Lateral drift across the fixed high lane — the word stays fully above
  // the device for its entire life.
  const x = useTransform(progress, [a, b], reduce ? ['0vw', '0vw'] : ['12vw', '-12vw']);
  return (
    // Outer div owns the static vertical centering; the inner motion.div owns
    // the sweep so framer's transform can't clobber the -translate-y-1/2.
    <div
      className="absolute inset-x-0 top-[3vh] flex justify-center"
      style={{ transform: `translateX(${shift})` }}
    >
      <motion.div
        style={{ opacity, x, willChange: 'transform' }}
        className="select-none whitespace-nowrap font-sofia font-medium leading-none tracking-hims text-solace-green-600/50 text-[clamp(64px,21vw,140px)] lg:text-[clamp(150px,20vw,280px)]"
      >
        {children}
      </motion.div>
    </div>
  );
}

export default function AppHero() {
  const trackRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  // The full grow-toward-camera choreography only runs ≥lg; below that the
  // track is shorter and the phone caps at a gentle 1.1 scale.
  const isWide = useIsWide();

  const { scrollYProgress: p } = useScroll({
    target: trackRef,
    offset: ['start start', 'end end'],
  });

  // ---- Headline: holds, then lifts away over the first ~20% of the track ----
  const headOpacity = useTransform(p, [0, 0.05, 0.13], [1, 1, 0]);
  const headY = useTransform(p, [0, 0.13], reduce ? [0, 0] : [0, -70]);

  // ---- Phone: peeks at rest (like the reference), rises fully into view,
  // then grows toward the camera mid-track. On mobile it rests lower so the
  // scroll cue and the bezel don't collide. ----
  // The phone holds waist-high while the ghost words parade through the
  // clear band above it, then rises and grows once the last word has left —
  // words and device never share vertical space, so the type always reads.
  const phoneY = useTransform(
    p,
    [0, 0.15, 0.68, 0.82],
    reduce
      ? ['0vh', '0vh', '0vh', '0vh']
      : isWide
        ? ['26vh', '12vh', '12vh', '0vh']
        : ['6vh', '0vh', '0vh', '0vh'],
  );
  const phoneScale = useTransform(
    p,
    [0, 0.15, 0.72, 0.95],
    reduce ? [1, 1, 1, 1] : [0.97, 1, 1, isWide ? 1.1 : 1.04],
  );



  return (
    <section
      ref={trackRef}
      aria-labelledby="app-hero-heading"
      // overflow-clip keeps the rounded-corner clipping without creating a
      // scrollport (plain overflow-hidden on this ancestor would un-stick the
      // pinned stage); overflow-hidden stays as the parse-time fallback.
      className="relative mx-2 mt-2 h-[220vh] overflow-hidden overflow-clip rounded-hims bg-white md:mx-8 md:mt-3 lg:h-[300vh]"
    >
      {/* ===== Pinned stage ===== */}
      {/* h-svh keeps the bottom-anchored phone above mobile browser chrome */}
      <div className="sticky top-0 h-screen h-svh w-full overflow-hidden">
        {/* --- Soft radial glow rising from the bottom (reference: lilac) --- */}
        <motion.div
          aria-hidden
          initial={{ opacity: 0, y: reduce ? 0 : 48 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ opacity: himsFade, y: { duration: 0.6, ease: HIMS_EXPO } }}
          className="pointer-events-none absolute inset-0"
          style={{ background: GLOW_GRADIENT }}
        />
        {/* Mint ground rising from the card's bottom edge: the crop line
            lands on a mid-tone color (like the teal cards), so the
            shadowed arm meets a low-contrast edge instead of white. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 h-[30vh]"
          style={{
            background:
              'linear-gradient(to top, #B7E0CF 0%, rgba(183,224,207,0) 100%)',
          }}
        />

        {/* --- Ghost mega type sweeping vertically behind the phone ---
            Desktop-only: the short mobile track would sweep it at ~7× scroll
            speed, so below lg the hero stays a quick, honest beat. */}
        <div aria-hidden className="pointer-events-none absolute inset-0 z-10">
          <GhostLine progress={p} band={isWide ? GHOST_BANDS[0] : GHOST_BANDS_M[0]} reduce={reduce} shift={isWide ? '-9vw' : '-5vw'}>
            it&rsquo;s
          </GhostLine>
          <GhostLine progress={p} band={isWide ? GHOST_BANDS[1] : GHOST_BANDS_M[1]} reduce={reduce} shift={isWide ? '9vw' : '5vw'}>
            all in
          </GhostLine>
          <GhostLine progress={p} band={isWide ? GHOST_BANDS[2] : GHOST_BANDS_M[2]} reduce={reduce} shift={isWide ? '-4vw' : '-2vw'}>
            the app.
          </GhostLine>
        </div>

        {/* --- Headline (the page h1) --- */}
        <motion.div
          style={{ opacity: headOpacity, y: headY }}
          className="absolute inset-x-0 top-[16vh] z-30 px-6 text-center"
        >
          <motion.h1
            id="app-hero-heading"
            initial={{ opacity: 0, y: reduce ? 0 : 28 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ opacity: himsFade, y: himsMove }}
            className="font-sofia text-[clamp(44px,7.4vw,104px)] font-medium leading-[1.02] tracking-hims text-solace-green-700"
          >
            Total intake.
            <br />
            Totally different.
          </motion.h1>
        </motion.div>

        {/* --- The hand + phone, pinned bottom-center --- */}
        {/* Outer div owns the static -translate-x-1/2 centering; the inner
            motion.div owns y/scale so framer's transform can't clobber it. */}
        <div className="absolute bottom-0 left-1/2 z-20 w-[105vw] -translate-x-[61%] translate-y-[10%] sm:w-[64vw] md:w-[52vw] lg:w-[clamp(600px,54vw,780px)]">
          <motion.div
            style={{
              y: phoneY,
              scale: phoneScale,
              transformOrigin: 'bottom center',
              willChange: 'transform',
            }}
          >
            <PhoneRig alt="A hand holding a phone running the Solace patient-intake check-in" />
          </motion.div>
        </div>

      </div>
    </section>
  );
}
