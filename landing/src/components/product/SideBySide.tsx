import { useRef } from 'react';
import {
  cubicBezier,
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
  type Transition,
} from 'framer-motion';
import { APP_SCREENS, HIMS_EXPO, himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';
import PhoneRig from './PhoneRig';

/*
 * SideBySide — the signature app.forhims.com scene: white stage, photographed
 * hand+iPhone pinned on the RIGHT, the real Solace intake recording on its
 * screen, and quiet gray copy on the LEFT that swaps as you scroll the 420vh
 * track. The composite keeps its natural orientation (hand from bottom-left);
 * placed right-of-center the wrist reads as entering from bottom-center, the
 * same way the reference's hero composite does.
 */

const EXPO_OUT = cubicBezier(...HIMS_EXPO);

// Opacity moves on HIMS_OUT (0.2s), transforms on HIMS_EXPO (0.6s).
const REVEAL: Transition = { ...himsMove, opacity: himsFade };

type Scene = {
  lead: string;
  rest: string;
  range: [number, number, number, number];
  hold?: boolean;
};

const SCENES: Scene[] = [
  {
    lead: 'Patients check in',
    rest: ' like they talk. Speak or tap, in 20 languages. Every answer is saved for your care team, and the next question always fits your story.',
    // On stage from the moment the section pins — the reference never shows
    // an empty stage.
    range: [0, 0.06, 0.32, 0.4],
  },
  {
    lead: 'Every symptom lands organized.',
    rest: ' Allergies, medications and history arrive as a clean record your clinicians can trust, not a wall of loose notes.',
    range: [0.4, 0.5, 0.62, 0.7],
  },
  {
    lead: 'Urgency, explained.',
    rest: ' Solace suggests who needs help first and shows its reasons, before the patient reaches a bed. Your clinicians always make the final call.',
    range: [0.7, 0.8, 0.95, 1.0],
    hold: true, // last scene stays on through the end of the track
  },
];

function SceneCopy({ scene }: { scene: Scene }) {
  return (
    <p className="max-w-[34ch] font-sofia text-[clamp(22px,1.9vw,30px)] font-medium leading-[1.45] tracking-[-0.01em] text-muted">
      <span className="text-ink">{scene.lead}</span>
      {scene.rest}
    </p>
  );
}

// One scroll-linked copy scene: fades/lifts in, holds, then exits upward
// (the final scene holds to the end instead of exiting).
function CopyScene({
  progress,
  scene,
  reduce,
}: {
  progress: MotionValue<number>;
  scene: Scene;
  reduce: boolean | null;
}) {
  const opacity = useTransform(progress, scene.range, scene.hold ? [0, 1, 1, 1] : [0, 1, 1, 0]);
  const y = useTransform(
    progress,
    scene.range,
    reduce ? [0, 0, 0, 0] : scene.hold ? [40, 0, 0, 0] : [40, 0, 0, -40],
  );
  return (
    <motion.div style={{ opacity, y }} className="absolute inset-0 flex items-center">
      <SceneCopy scene={scene} />
    </motion.div>
  );
}

export default function SideBySide() {
  const trackRef = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();
  // Full sticky choreography only runs ≥lg; below that the section stacks copy
  // then phone with simple in-view reveals.
  const isWide = useIsWide();

  const { scrollYProgress: p } = useScroll({
    target: trackRef,
    offset: ['start start', 'end end'],
  });

  // Phone: a short rise as the section pins (himsMove feel via the expo
  // ease), stays pinned, then drifts up -8vh over the last 5%. The card's
  // visible rounded edge crops the wrist — the forhims pattern.
  const phoneY = useTransform(
    p,
    [0, 0.06, 0.95, 1],
    reduce ? ['0vh', '0vh', '0vh', '0vh'] : ['25vh', '0vh', '0vh', '-8vh'],
    { ease: EXPO_OUT },
  );

  // The on-screen app moment cross-fades in step with the copy scenes:
  // voice intake → structured medical details → the explained plan.
  const screen1 = useTransform(p, [0, 0.42, 0.46], [1, 1, 0]);
  const screen2 = useTransform(p, [0.42, 0.46, 0.72, 0.76], [0, 1, 1, 0]);
  const screen3 = useTransform(p, [0.72, 0.76, 1], [0, 1, 1]);
  // Natural width (never side-cropped); the device screen crops the bottom
  // like a real scroll position. 12cqw top margin clears the dynamic island.
  const screenScenes = (
    <div className="relative h-full w-full">
      <motion.img
        src={APP_SCREENS.symptoms}
        alt=""
        className="absolute left-0 top-[13.5cqw] h-auto w-full"
        style={{ opacity: screen1 }}
      />
      <motion.img
        src={APP_SCREENS.medical}
        alt=""
        className="absolute left-0 top-[13.5cqw] h-auto w-full"
        style={{ opacity: screen2 }}
      />
      {/* plan.png is pre-cropped tight to the priority badge — no lift */}
      <motion.img
        src={APP_SCREENS.plan}
        alt=""
        className="absolute left-0 top-[13.5cqw] h-auto w-full"
        style={{ opacity: screen3 }}
      />
    </div>
  );

  return (
    <section
      ref={trackRef}
      aria-labelledby="side-by-side-heading"
      className="relative bg-white lg:h-[420vh]"
      style={{
        // Flat paper-white stage (the hims band rhythm): frames the pinned
        // teal card's margins >=lg and backs the stacked branch <lg, while
        // staying close enough to white that both seams read as intentional.
        backgroundImage: 'linear-gradient(180deg, #fafaf8 0%, #fafaf8 100%)',
      }}
    >
      <h2 id="side-by-side-heading" className="sr-only">
        What Your Patients See
      </h2>

      {isWide ? (
        /* ===== ≥lg: pinned stage, scroll-scrubbed scenes ===== */
        <div className="sticky top-0 h-screen w-full p-2 md:p-4">
          {/* The visible rounded card whose curved edges crop the hand —
              the forhims composite pattern. */}
          <div
            className="relative h-full w-full overflow-hidden rounded-hims"
            style={{
              backgroundImage:
                'linear-gradient(160deg, #DBF1EA 0%, #BEE4D5 45%, #9DD6C2 100%)',
            }}
          >
          {/* --- Left copy column --- */}
          <div className="absolute left-[8vw] top-1/2 z-20 w-[clamp(340px,24vw,430px)] -translate-y-1/2">
            <div className="relative h-[36vh] min-h-[260px]">
              {SCENES.map((scene) => (
                <CopyScene key={scene.lead} progress={p} scene={scene} reduce={reduce} />
              ))}
            </div>
            {/* progress hairline */}
            <div aria-hidden className="mt-8 h-[2px] w-40 overflow-hidden rounded-pill bg-ink/10">
              <motion.div
                className="h-full w-full origin-left bg-solace-green-500"
                style={{ scaleX: p }}
              />
            </div>
          </div>

          {/* --- Hand + phone, pinned right-of-center --- */}
          {/* Outer div owns static positioning; the motion.divs own y so
              framer's transform can't clobber the layout (IntakeShowcase
              pattern). The flip lives one level deeper, on the composite. */}
          <div className="absolute bottom-0 right-[16vw] z-10 w-[clamp(620px,52vw,790px)] translate-y-[10%]">
            <motion.div style={{ y: phoneY, willChange: 'transform' }}>
              <motion.div
                animate={reduce ? undefined : { y: [0, -8, 0] }}
                transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
              >
                {/* Decorative here — the copy column carries the content. */}
                <PhoneRig alt="" screen={screenScenes} />
              </motion.div>
            </motion.div>
          </div>
          </div>
        </div>
      ) : (
        /* ===== <lg: simple stack, no track ===== */
        <div className="px-6 pb-24 pt-20 sm:px-10">
          <div className="mx-auto flex max-w-xl flex-col gap-12">
            {SCENES.map((scene) => (
              <motion.div
                key={scene.lead}
                initial={{ opacity: 0, y: reduce ? 0 : 32 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.4 }}
                transition={REVEAL}
              >
                <SceneCopy scene={scene} />
              </motion.div>
            ))}
            <motion.div
              initial={{ opacity: 0, y: reduce ? 0 : 48 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={REVEAL}
              className="relative mx-auto w-[min(440px,92%)] overflow-hidden rounded-hims bg-solace-soft px-7 pt-10"
              style={{ aspectRatio: '1728 / 1910' }}
            >
              <PhoneRig
                alt=""
                screen={
                  <img src={APP_SCREENS.symptoms} alt="" className="mt-[13.5cqw] h-auto w-full" />
                }
              />
            </motion.div>
          </div>
        </div>
      )}
    </section>
  );
}
