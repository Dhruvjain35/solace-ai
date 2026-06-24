import { useRef } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { ArrowRight, ChevronDown } from "lucide-react";
import { Eyebrow } from "../Eyebrow";

// Cinematic hero: aurora field, per-word mask reveal on a giant serif headline,
// parallax exit as you scroll into the scribe scene.

const LINE1 = ["The", "calm"];
const LINE2 = ["operating", "layer"];
const LINE3 = ["for", "modern", "care."];

function MaskedWords({ words, base, italic }: { words: string[]; base: number; italic?: number[] }) {
  const reduced = useReducedMotion();
  return (
    <span className="block overflow-hidden pb-[0.08em] -mb-[0.08em]">
      <span className="flex flex-wrap justify-center gap-x-[0.26em]">
        {words.map((w, i) => (
          <span key={w + i} className="inline-block overflow-hidden">
            <motion.span
              className={`inline-block will-change-transform ${italic?.includes(i) ? "italic text-primary" : ""}`}
              initial={reduced ? false : { y: "112%" }}
              animate={{ y: 0 }}
              transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1], delay: base + i * 0.07 }}
            >
              {w}
            </motion.span>
          </span>
        ))}
      </span>
    </span>
  );
}

export function HeroCinematic() {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const exitY = useTransform(scrollYProgress, [0, 1], [0, reduced ? 0 : -120]);
  const exitOpacity = useTransform(scrollYProgress, [0, 0.85], [1, reduced ? 1 : 0]);
  const orbY = useTransform(scrollYProgress, [0, 1], [0, reduced ? 0 : 160]);

  const appear = (delay: number) =>
    reduced
      ? {}
      : {
          initial: { opacity: 0, y: 22 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1] as const, delay },
        };

  return (
    <section ref={ref} className="relative flex min-h-[96svh] flex-col overflow-hidden bg-surface">
      {/* Aurora field */}
      <motion.div aria-hidden="true" style={{ y: orbY }} className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute left-1/2 top-[-22%] h-[70vh] w-[120vw] -translate-x-1/2 rounded-[100%] opacity-[0.32] blur-[110px]"
          style={{ background: "conic-gradient(from 180deg at 50% 50%, #CBE3E9, #3B5E67 30%, #D8ECF0 55%, #CADCE7 75%, #CBE3E9)" }}
          animate={reduced ? {} : { rotate: [0, 14, 0] }}
          transition={{ duration: 34, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute -left-32 top-1/3 h-96 w-96 rounded-full bg-primary-fixed opacity-30 blur-[100px]"
          animate={reduced ? {} : { x: [0, 36, 0], y: [0, -22, 0] }}
          transition={{ duration: 26, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute -right-24 top-1/4 h-[28rem] w-[28rem] rounded-full bg-secondary-container opacity-35 blur-[110px]"
          animate={reduced ? {} : { x: [0, -30, 0], y: [0, 26, 0] }}
          transition={{ duration: 31, repeat: Infinity, ease: "easeInOut" }}
        />
        {/* hairline grid for that webflow editorial feel */}
        <div
          className="absolute inset-0 opacity-[0.05]"
          style={{
            backgroundImage:
              "linear-gradient(to right, #2A474E 1px, transparent 1px), linear-gradient(to bottom, #2A474E 1px, transparent 1px)",
            backgroundSize: "72px 72px",
            maskImage: "radial-gradient(ellipse 80% 60% at 50% 35%, black 35%, transparent 75%)",
            WebkitMaskImage: "radial-gradient(ellipse 80% 60% at 50% 35%, black 35%, transparent 75%)",
          }}
        />
      </motion.div>

      <motion.div
        style={{ y: exitY, opacity: exitOpacity }}
        className="relative mx-auto flex w-full max-w-5xl flex-1 flex-col items-center justify-center px-4 pb-24 pt-16 text-center sm:px-6"
      >
        <motion.div {...appear(0.05)}>
          <Eyebrow>Clinical AI platform</Eyebrow>
        </motion.div>

        <h1 className="mt-7 font-display text-[13.5vw] leading-[0.98] tracking-editorial-tight text-ink sm:text-[9vw] lg:text-[100px]">
          <MaskedWords words={LINE1} base={0.15} italic={[1]} />
          <MaskedWords words={LINE2} base={0.32} />
          <MaskedWords words={LINE3} base={0.48} />
        </h1>

        <motion.p {...appear(0.85)} className="mt-7 max-w-xl text-base leading-relaxed text-text-muted sm:text-lg">
          Triage that listens, notes that write themselves, and an EHR copilot that never
          moves without you. One platform — PHI isolation enforced in code.
        </motion.p>

        <motion.div {...appear(1.0)} className="mt-9 flex flex-col items-center gap-3 sm:flex-row">
          <Link
            to="/get-started"
            className="group relative inline-flex items-center gap-2 overflow-hidden rounded-full bg-primary bg-primary-gradient px-8 py-4 font-medium text-white shadow-lifted transition-transform hover:scale-[1.03] active:scale-[0.98]"
          >
            <span className="relative z-10 flex items-center gap-2">
              Get started <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </span>
            {/* shine sweep */}
            <span
              aria-hidden="true"
              className="absolute inset-y-0 -left-1/2 z-0 w-1/3 -skew-x-12 bg-white/25 opacity-0 blur-sm transition-all duration-700 group-hover:left-[120%] group-hover:opacity-100"
            />
          </Link>
          <Link
            to="/contact"
            className="inline-flex items-center gap-2 rounded-full px-8 py-4 font-medium text-ink ring-1 ring-line transition-colors hover:bg-surface-low"
          >
            Book a demo
          </Link>
        </motion.div>
      </motion.div>

      {/* scroll cue */}
      <motion.div
        {...appear(1.4)}
        className="relative mx-auto mb-8 flex flex-col items-center gap-1.5 text-text-muted"
        aria-hidden="true"
      >
        <span className="font-mono text-[10px] uppercase tracking-[0.18em]">Scroll — watch a visit chart itself</span>
        <motion.span animate={reduced ? {} : { y: [0, 6, 0] }} transition={{ duration: 1.6, repeat: Infinity }}>
          <ChevronDown size={16} />
        </motion.span>
      </motion.div>
    </section>
  );
}
