import { useRef } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useReducedMotion,
} from 'framer-motion';
import type { ReactNode } from 'react';
import { himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';

/*
 * LaptopRig — a pure-CSS MacBook-style mockup for the dark clinician section,
 * presented Apple-product-page style: the lid scroll-tilts open (rotateX
 * 26°→4°) while a glare band sweeps across the screen, and the whole machine
 * floats on a mint under-glow against the bg-ink stage.
 *
 * ≥lg the presentation is scroll-linked (exempt from the two-curve rule, like
 * FeatureIntro's card). Below lg the laptop renders flat and rises in once on
 * the house curves. Reduced motion zeroes every transform; the glare stays
 * parked offscreen. Only the screenshot's alt is exposed to AT — every other
 * piece of the rig is decoration.
 */

// The two-curve rule for the <lg whileInView rise.
const rise = { ...himsMove, opacity: himsFade };

interface LaptopRigProps {
  /** Screenshot source; ignored when `screen` is provided. */
  src?: string;
  alt: string;
  /** Live DOM screen — vector-crisp at any size (cqw units scale inside). */
  screen?: ReactNode;
  className?: string;
}

export default function LaptopRig({ src, alt, screen, className }: LaptopRigProps) {
  const rigRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const isWide = useIsWide();

  // Progress runs 0→1 from the rig entering the bottom of the viewport until
  // it sits just above center — the lid finishes settling as you reach it.
  const { scrollYProgress } = useScroll({
    target: rigRef,
    offset: ['start end', 'center 0.45'],
  });

  const still = reduce || !isWide;
  const rotateX = useTransform(scrollYProgress, [0, 1], still ? [0, 0] : [26, 4]);
  const scale = useTransform(scrollYProgress, [0, 1], still ? [1, 1] : [0.94, 1]);
  const y = useTransform(scrollYProgress, [0, 1], still ? [0, 0] : [70, 0]);
  const glareX = useTransform(
    scrollYProgress,
    [0, 1],
    still ? ['-130%', '-130%'] : ['-130%', '160%'],
  );

  const laptop = (
    <>
      {/* --- LID / SCREEN: near-black shell, metallic ring, 10px bezel --- */}
      <div className="relative aspect-[16/10] w-full rounded-[14px] bg-[#101113] p-[10px] shadow-pop ring-1 ring-white/10">
        {/* webcam dot */}
        <span
          aria-hidden="true"
          className="absolute left-1/2 top-[4px] h-[2px] w-[2px] -translate-x-1/2 rounded-full bg-white/20"
        />
        <div className="relative h-full w-full overflow-hidden rounded-[8px] bg-ink [container-type:inline-size]">
          {screen ? (
            <>
              <span className="sr-only">{alt}</span>
              <div aria-hidden="true" className="h-full w-full">
                {screen}
              </div>
            </>
          ) : (
            <img
              src={src}
              alt={alt}
              width={1680}
              height={1050}
              loading="lazy"
              decoding="async"
              className="h-full w-full object-cover object-top"
            />
          )}
          {/* faint panel glow off the top of the screen */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                'linear-gradient(180deg, rgba(255,255,255,0.04), transparent 45%)',
            }}
          />
          {/* glare sweep — rides the same scroll progress as the tilt */}
          <motion.div
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-[-30%] left-0 w-[40%]"
            style={{
              x: glareX,
              rotate: 14,
              background:
                'linear-gradient(to right, transparent, rgba(255,255,255,0.10), transparent)',
            }}
          />
        </div>
      </div>

      {/* --- BASE: aluminum deck with thumb scoop --- */}
      <div
        aria-hidden="true"
        // Slimmer deck overhang below sm: at near-full-bleed phone widths the
        // full 112% deck would poke past the viewport edges.
        className="relative h-[14px] w-[105%] rounded-t-[3px] rounded-b-2xl sm:w-[112%]"
        style={{
          background: 'linear-gradient(180deg, #3a3d42, #26282c 55%, #17181b)',
        }}
      >
        {/* lit top edge of the deck */}
        <div className="absolute inset-x-[3px] top-0 h-px bg-white/15" />
        {/* thumb-scoop notch */}
        <div
          className="absolute left-1/2 top-0 h-[6px] w-[12%] -translate-x-1/2 rounded-b-full"
          style={{ background: 'linear-gradient(180deg, #1c1e21, #141518)' }}
        />
      </div>
    </>
  );

  return (
    <div
      ref={rigRef}
      className={['relative mx-auto w-full max-w-[1040px]', className]
        .filter(Boolean)
        .join(' ')}
    >
      {/* --- UNDER-GLOW: mint pool the machine floats on --- */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-12 left-1/2 h-28 w-[120%] -translate-x-1/2 blur-2xl"
        style={{
          background:
            'radial-gradient(50% 50% at 50% 50%, rgba(31,191,143,0.18), transparent 70%)',
        }}
      />

      {isWide ? (
        <div style={{ perspective: '1600px' }}>
          <motion.div
            style={{
              rotateX,
              scale,
              y,
              transformOrigin: 'center bottom',
              willChange: 'transform',
            }}
            className="flex flex-col items-center"
          >
            {laptop}
          </motion.div>
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0, y: reduce ? 0 : 48 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={rise}
          className="flex flex-col items-center"
        >
          {laptop}
        </motion.div>
      )}
    </div>
  );
}
