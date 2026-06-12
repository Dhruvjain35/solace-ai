import { useEffect, useRef, useState } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useReducedMotion,
  type MotionValue,
} from 'framer-motion';

/*
 * IntakeShowcase — a 1:1 homage to the hims&hers "Total care. Totally different."
 * sticky-scroll hero (app.forhims.com), rebuilt for Solace.
 *
 * Mechanic: a tall scroll track pins a stage to the viewport. As you scroll the
 * track, scrollYProgress (0→1) drives the background gradient, the headline, the
 * side copy panels and the floating UI chips. The real Solace patient-intake
 * recording plays continuously inside the matted hand+phone — the same hand
 * photographed in the reference, segmented out and composited with our screen.
 *
 * Tokens (colors, gradients, easing, soft 104px shadow) extracted 1:1 from
 * app.forhims.com via designlang; remapped onto the Solace green/slate brand.
 */

// Screen-overlay rectangle, expressed as % of the hand-phone image box.
// The Solace video sits over the phone's content area; the photographed iOS
// status bar (9:41 · signal · battery) is left visible above it for realism.
// Calibrated against /assets/hand-phone.png (984×671, slight clockwise tilt).
const SCREEN = {
  left: '20.8%',
  top: '6.6%',
  width: '67.2%',
  height: '90%',
  radius: '10px',
  rotate: '-3.6deg',
  // object-position pulls the centered intake card up into the visible window.
  objectPosition: '50% 42%',
} as const;

function Chip({
  children,
  active = false,
  className = '',
  style,
}: {
  children: React.ReactNode;
  active?: boolean;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={`pointer-events-none select-none rounded-pill px-4 py-2 text-sm font-medium shadow-[0_8px_30px_rgba(0,0,0,0.10)] backdrop-blur-sm ${
        active
          ? 'bg-slate text-white'
          : 'border border-black/5 bg-white/90 text-ink'
      } ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}

// A floating chip with scroll-linked reveal + a gentle continuous drift.
function FloatChip({
  progress,
  range,
  x,
  y,
  drift = 14,
  delay = 0,
  active,
  children,
  reduce,
}: {
  progress: MotionValue<number>;
  range: [number, number, number, number];
  x: string;
  y: string;
  drift?: number;
  delay?: number;
  active?: boolean;
  children: React.ReactNode;
  reduce: boolean | null;
}) {
  const opacity = useTransform(progress, range, [0, 1, 1, 0]);
  const ty = useTransform(progress, range, [28, 0, 0, -28]);
  return (
    <motion.div
      aria-hidden
      className="absolute z-20 hidden lg:block"
      style={{ left: x, top: y, opacity, y: reduce ? 0 : ty }}
    >
      <motion.div
        animate={reduce ? undefined : { y: [0, -drift, 0] }}
        transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut', delay }}
      >
        <Chip active={active}>{children}</Chip>
      </motion.div>
    </motion.div>
  );
}

export default function IntakeShowcase() {
  const trackRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const reduce = useReducedMotion();
  // The full side-copy + chip + phone-slide experience only runs ≥lg, where
  // there's room for a left column beside the phone; below that the phone stays
  // centered and the track is shorter (no panels to scrub past). Seed from the
  // query so the very first render is already correct on narrow screens.
  const [isWide, setIsWide] = useState(
    () => (typeof window !== 'undefined' ? window.matchMedia('(min-width: 1024px)').matches : true),
  );
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    const sync = () => setIsWide(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  // Honor prefers-reduced-motion for the autoplaying recording (CSS can't pause
  // an HTML5 video). When reduced, hold the poster frame instead of looping.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (reduce) {
      v.pause();
      v.currentTime = 0;
    } else {
      void v.play().catch(() => {});
    }
  }, [reduce]);
  const { scrollYProgress: p } = useScroll({
    target: trackRef,
    offset: ['start start', 'end end'],
  });

  // ---- Background gradient cross-fades (forhims palette → Solace) ----
  const bgMint = useTransform(p, [0.12, 0.26, 0.42, 0.5], [0, 1, 1, 0]);
  const bgGreen = useTransform(p, [0.46, 0.56, 0.72, 0.8], [0, 1, 1, 0]);
  const bgDark = useTransform(p, [0.76, 0.86, 1, 1], [0, 1, 1, 1]);

  // Hero radial glow: purple/pink (forhims hero) → Solace mint.
  const glowPurple = useTransform(p, [0, 0.18, 0.3], [1, 1, 0]);
  const glowMint = useTransform(p, [0.24, 0.4, 1], [0, 1, 1]);

  // ---- Headline ----
  const headOpacity = useTransform(p, [0, 0.06, 0.16, 0.22], [1, 1, 1, 0]);
  const headY = useTransform(p, [0, 0.22], reduce ? [0, 0] : [0, -80]);

  // ---- Phone: rise, gentle parallax/scale, and a slide to the right so the
  // side-copy panels get a clear left column (mirrors forhims' phone drift) ----
  const phoneY = useTransform(p, [0, 0.12, 1], reduce ? [0, 0, 0] : [120, 0, -40]);
  const phoneScale = useTransform(p, [0, 0.12, 0.85, 1], [0.96, 1, 1, 0.92]);
  const phoneX = useTransform(p, [0.18, 0.32, 1], reduce || !isWide ? [0, 0, 0] : [0, 150, 150]);

  // ---- Side copy panels (one per scroll segment) ----
  const panel2 = {
    opacity: useTransform(p, [0.28, 0.36, 0.46, 0.52], [0, 1, 1, 0]),
    y: useTransform(p, [0.28, 0.36, 0.46, 0.52], reduce ? [0, 0, 0, 0] : [40, 0, 0, -40]),
  };
  const panel3 = {
    opacity: useTransform(p, [0.54, 0.62, 0.72, 0.78], [0, 1, 1, 0]),
    y: useTransform(p, [0.54, 0.62, 0.72, 0.78], reduce ? [0, 0, 0, 0] : [40, 0, 0, -40]),
  };
  const panel4 = {
    opacity: useTransform(p, [0.82, 0.9, 1, 1], [0, 1, 1, 1]),
    y: useTransform(p, [0.82, 0.9, 1, 1], reduce ? [0, 0, 0, 0] : [40, 0, 0, 0]),
  };

  // Text flips to light on the final dark segment.
  const lightText = useTransform(p, [0.78, 0.86], ['#0A0F0D', '#FFFFFF']);

  return (
    <section
      ref={trackRef}
      id="intake-showcase"
      aria-labelledby="intake-heading"
      className="relative h-[200vh] bg-white lg:h-[440vh]"
    >
      {/* ===== Pinned stage ===== */}
      <div className="sticky top-0 h-screen w-full overflow-hidden">
        {/* --- Background layers --- */}
        <div className="absolute inset-0 bg-offwhite" />
        <motion.div
          className="absolute inset-0"
          style={{
            opacity: bgMint,
            backgroundImage:
              'linear-gradient(166.14deg, rgb(225,242,236) 0%, rgb(199,229,221) 100%)',
          }}
        />
        <motion.div
          className="absolute inset-0"
          style={{
            opacity: bgGreen,
            backgroundImage:
              'linear-gradient(243.63deg, rgb(99,209,164) 12%, rgb(47,165,158) 78%)',
          }}
        />
        <motion.div
          className="absolute inset-0"
          style={{
            opacity: bgDark,
            backgroundImage:
              'linear-gradient(157deg, #0d2b25 8%, #0a1f1b 48%, #04100d 92%)',
          }}
        />

        {/* --- Radial glow behind the phone --- */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-[58%] h-[80vh] w-[80vh] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[80px]"
          style={{
            opacity: glowPurple,
            background:
              'radial-gradient(circle at 50% 50%, rgba(150,133,255,0.55), rgba(209,178,202,0.40) 38%, rgba(181,173,225,0) 70%)',
          }}
        />
        <motion.div
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-[58%] h-[78vh] w-[78vh] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[80px]"
          style={{
            opacity: glowMint,
            background:
              'radial-gradient(circle at 50% 50%, rgba(31,191,143,0.50), rgba(11,107,83,0.28) 42%, rgba(11,107,83,0) 72%)',
          }}
        />

        {/* --- Headline (segment 1) --- */}
        <motion.div
          style={{ opacity: headOpacity, y: headY }}
          className="absolute inset-x-0 top-[14vh] z-30 flex flex-col items-center px-6 text-center"
        >
          <span className="eyebrow mb-5">Patient intake</span>
          <h1 id="intake-heading" className="font-sofia text-[13vw] font-extrabold leading-[0.92] tracking-[-0.04em] text-solace-green-700 sm:text-[11vw] md:text-[88px]">
            Total intake.
            <br />
            Totally automated.
          </h1>
          <p className="mt-6 max-w-xl text-base text-muted md:text-lg">
            The front of your ED — from the waiting-room QR code to an explainable
            acuity score — rebuilt as one calm, AI-native flow.
          </p>
        </motion.div>

        {/* --- Side copy panels (segments 2–4) --- */}
        <div className="absolute inset-0 z-30 mx-auto hidden max-w-[1200px] items-center px-10 lg:flex">
          <motion.div style={{ opacity: panel2.opacity, y: panel2.y, color: lightText }} className="absolute max-w-sm">
            <h2 className="font-sofia text-4xl font-bold leading-[1.04] tracking-[-0.03em] lg:text-5xl">
              Check in, in any language.
            </h2>
            <p className="mt-5 text-base leading-relaxed opacity-80">
              Voice or tap, in 30+ languages. Whisper transcribes every answer and
              the adaptive form branches to the next right question — no clipboard,
              no front-desk bottleneck.
            </p>
          </motion.div>

          <motion.div style={{ opacity: panel3.opacity, y: panel3.y, color: lightText }} className="absolute max-w-sm">
            <h2 className="font-sofia text-4xl font-bold leading-[1.04] tracking-[-0.03em] lg:text-5xl">
              Every symptom, structured.
            </h2>
            <p className="mt-5 text-base leading-relaxed opacity-80">
              Allergies, medications and conditions captured as clean, coded data —
              severity and all — so your clinicians inherit a record they can trust,
              not a wall of free text.
            </p>
          </motion.div>

          <motion.div style={{ opacity: panel4.opacity, y: panel4.y }} className="absolute max-w-sm text-white">
            <h2 className="font-sofia text-4xl font-bold leading-[1.04] tracking-[-0.03em] lg:text-5xl">
              An ESI level in seconds.
            </h2>
            <p className="mt-5 text-base leading-relaxed text-white/80">
              Every acuity score arrives with a SHAP explanation — the reasons, ranked —
              ready before the patient reaches a bed. Triage aid only; clinicians always
              verify.
            </p>
          </motion.div>
        </div>

        {/* --- Floating UI chips (motion graphics) --- */}
        {/* Segment 2 — languages */}
        <FloatChip progress={p} range={[0.28, 0.37, 0.46, 0.52]} x="22%" y="13%" drift={13} delay={0.3} reduce={reduce}>🇸🇦 العربية</FloatChip>
        <FloatChip progress={p} range={[0.29, 0.38, 0.46, 0.52]} x="44%" y="11%" drift={15} delay={0.9} reduce={reduce}>Tagalog</FloatChip>
        <FloatChip progress={p} range={[0.28, 0.37, 0.46, 0.52]} x="63%" y="22%" drift={16} reduce={reduce}>🇺🇸 English</FloatChip>
        <FloatChip progress={p} range={[0.29, 0.38, 0.46, 0.52]} x="78%" y="40%" drift={12} delay={0.6} reduce={reduce}>🇪🇸 Español</FloatChip>
        <FloatChip progress={p} range={[0.3, 0.39, 0.46, 0.52]} x="68%" y="60%" drift={18} delay={1.1} reduce={reduce}>🇨🇳 中文</FloatChip>

        {/* Segment 3 — intake pills (mirroring the real Solace form) */}
        <FloatChip progress={p} range={[0.56, 0.65, 0.72, 0.78]} x="20%" y="13%" drift={15} delay={0.4} reduce={reduce}>Sulfa · anaphylaxis</FloatChip>
        <FloatChip progress={p} range={[0.56, 0.66, 0.72, 0.78]} x="46%" y="11%" drift={13} delay={0.8} reduce={reduce}>Steroids</FloatChip>
        <FloatChip progress={p} range={[0.54, 0.63, 0.72, 0.78]} x="63%" y="24%" drift={14} active reduce={reduce}>Peanuts · moderate</FloatChip>
        <FloatChip progress={p} range={[0.55, 0.64, 0.72, 0.78]} x="79%" y="43%" drift={17} delay={0.5} reduce={reduce}>Pain meds</FloatChip>
        <FloatChip progress={p} range={[0.55, 0.64, 0.72, 0.78]} x="66%" y="62%" drift={12} delay={1.0} active reduce={reduce}>Asthma</FloatChip>

        {/* Segment 4 — triage acuity badges */}
        <FloatChip progress={p} range={[0.82, 0.9, 1, 1]} x="22%" y="13%" drift={14} delay={0.3} reduce={reduce}>HR 118 · SpO₂ 94%</FloatChip>
        <FloatChip progress={p} range={[0.83, 0.91, 1, 1]} x="46%" y="11%" drift={15} delay={1.0} reduce={reduce}>Pre-brief ready</FloatChip>
        <FloatChip progress={p} range={[0.82, 0.9, 1, 1]} x="64%" y="26%" drift={16} active reduce={reduce}>ESI 2 · Emergent</FloatChip>
        <FloatChip progress={p} range={[0.83, 0.91, 1, 1]} x="78%" y="45%" drift={12} delay={0.6} reduce={reduce}>SHAP: chest pain ↑</FloatChip>

        {/* --- The hand + phone, pinned bottom-center --- */}
        {/* Outer div owns the static -translate-x-1/2 centering; the inner
            motion.div owns y/scale so framer's transform can't clobber it. */}
        <div className="absolute bottom-0 left-1/2 z-10 w-[clamp(330px,42vw,560px)] -translate-x-1/2">
        <motion.div style={{ x: phoneX, y: phoneY, scale: phoneScale, transformOrigin: 'bottom center', willChange: 'transform' }}>
          <div className="relative">
            {/* Solace intake recording, composited into the phone's screen.
                Decorative — the copy panels carry the message — so it's hidden
                from assistive tech, and it honors reduced-motion via the effect. */}
            <video
              ref={videoRef}
              src="/assets/solace-intake.mp4"
              poster="/assets/solace-intake-poster.jpg"
              autoPlay={!reduce}
              muted
              loop
              playsInline
              preload="metadata"
              aria-hidden="true"
              tabIndex={-1}
              className="pointer-events-none absolute z-20 object-cover"
              style={{
                left: SCREEN.left,
                top: SCREEN.top,
                width: SCREEN.width,
                height: SCREEN.height,
                borderRadius: SCREEN.radius,
                transform: `rotate(${SCREEN.rotate})`,
                transformOrigin: 'center center',
                objectPosition: SCREEN.objectPosition,
              }}
            />
            {/* Photographed hand + iPhone (matted from the reference), screen on top */}
            <img
              src="/assets/hand-phone.png"
              alt="A hand holding a phone running the Solace patient-intake check-in"
              className="relative z-10 w-full drop-shadow-[0_27px_104px_rgba(0,0,0,0.28)]"
            />
          </div>
        </motion.div>
        </div>

        {/* scroll hint */}
        <motion.div
          style={{ opacity: headOpacity }}
          className="absolute bottom-6 left-1/2 z-30 -translate-x-1/2 text-xs font-medium uppercase tracking-[0.2em] text-muted"
        >
          Scroll
        </motion.div>
      </div>
    </section>
  );
}
