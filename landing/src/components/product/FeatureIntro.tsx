import { useRef } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useReducedMotion,
} from 'framer-motion';
import { ClipboardList } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';

/*
 * FeatureIntro — a 1:1 structural clone of app.forhims.com's "Everything you
 * need to feel your best." sequence (scroll_03.png): giant centered statement
 * → white app-icon card floating on a soft halo → the start of a mega word,
 * remapped onto Solace ("Intake" hands off to the tile grid below).
 *
 * Normal flow on white. The card gets a scroll-linked entrance parallax
 * (scale 0.92→1, y 40→0) plus a gentle continuous float; the statement and
 * the mega word rise in with whileInView on the house two-curve rule.
 */

// The two-curve rule: opacity on HIMS_OUT (~0.2s), transform on HIMS_EXPO (~0.6s).
const rise = { ...himsMove, opacity: himsFade };

export default function FeatureIntro() {
  const cardAreaRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  // Full parallax choreography only runs ≥lg; below that the card sits still
  // (the float alone carries it).
  const isWide = useIsWide();

  // Scroll-linked entrance for the card: progress runs 0→1 from the moment the
  // card area enters the bottom of the viewport until it's centered.
  const { scrollYProgress: cardP } = useScroll({
    target: cardAreaRef,
    offset: ['start end', 'center center'],
  });
  const still = reduce || !isWide;
  const cardScale = useTransform(cardP, [0, 1], still ? [1, 1] : [0.92, 1]);
  const cardY = useTransform(cardP, [0, 1], still ? [0, 0] : [40, 0]);

  return (
    <section
      aria-labelledby="feature-intro-heading"
      className="overflow-hidden bg-white"
      style={{
        // Barely-there mint wash (the hims band rhythm): starts white against
        // the statement above, ends on the faint mint TileGrid opens with.
        backgroundImage: 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)',
      }}
    >
      {/* --- Centered statement --- */}
      <motion.h2
        id="feature-intro-heading"
        initial={{ opacity: 0, y: reduce ? 0 : 56 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.5 }}
        transition={rise}
        className="mx-auto max-w-[14ch] px-4 pt-[14vh] text-center font-sofia text-[clamp(48px,7.2vw,110px)] font-medium leading-[1.02] tracking-hims text-ink lg:pt-[20vh]"
      >
        Everything you need to run a calmer ED.
      </motion.h2>

      {/* --- App-icon card on its halo, in ~70vh of whitespace --- */}
      <div
        ref={cardAreaRef}
        aria-hidden="true"
        className="flex min-h-[40vh] items-center justify-center lg:min-h-[70vh]"
      >
        <motion.div
          style={{ scale: cardScale, y: cardY, willChange: 'transform' }}
          className="relative"
        >
          {/* Broad soft halo behind the card, like the reference's radial glow */}
          <div
            className="absolute left-1/2 top-1/2 h-[240%] w-[240%] -translate-x-1/2 -translate-y-1/2"
            style={{
              background:
                'radial-gradient(circle at 50% 50%, rgba(10,15,13,0.13), rgba(10,15,13,0.04) 55%, rgba(10,15,13,0) 78%)',
            }}
          />
          <motion.div
            animate={reduce ? undefined : { y: [0, -10, 0] }}
            transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
            className="relative flex aspect-square w-[min(46vw,368px)] items-center justify-center rounded-hims-lg bg-white shadow-halo ring-1 ring-black/5"
          >
            <ClipboardList
              strokeWidth={1.75}
              className="h-[clamp(72px,14vw,136px)] w-[clamp(72px,14vw,136px)] text-ink"
            />
          </motion.div>
        </motion.div>
      </div>

      {/* --- Mega word, sliding up to introduce the tile grid --- */}
      <motion.p
        initial={{ opacity: 0, y: reduce ? 0 : 120 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.4 }}
        transition={rise}
        className="pb-[10vh] text-center font-sofia text-[clamp(140px,28vw,430px)] font-medium leading-none tracking-hims text-ink lg:pb-[16vh]"
      >
        Intake
      </motion.p>
    </section>
  );
}
