import { useRef } from "react";
import { motion, MotionValue, useReducedMotion, useScroll, useTransform } from "framer-motion";

// wearebrand-style statement: a giant serif paragraph whose words fill from
// ghost to ink as you scroll through the section.

const WORDS =
  "Healthcare software shouts. Ours doesn't. We build for the 3 a.m. shift — fewer clicks, quieter screens, honest uncertainty, and a chart that never comes before the patient.".split(" ");

const ACCENT = new Set(["3", "a.m.", "shift", "patient."]);

function Word({ p, i, total, children }: { p: MotionValue<number>; i: number; total: number; children: string }) {
  const start = (i / total) * 0.8;
  const opacity = useTransform(p, [start, start + 0.06], [0.16, 1]);
  return (
    <motion.span style={{ opacity }} className={ACCENT.has(children) ? "italic text-primary" : undefined}>
      {children}{" "}
    </motion.span>
  );
}

export function Manifesto() {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "end 0.45"] });

  return (
    <section ref={ref} className="bg-surface">
      <div className="mx-auto max-w-4xl px-4 py-28 sm:px-6 sm:py-36">
        <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-primary">Why we exist</p>
        <p className="mt-6 font-display text-[7.5vw] leading-[1.14] tracking-editorial text-ink sm:text-4xl lg:text-[44px]">
          {reduced
            ? WORDS.join(" ")
            : WORDS.map((w, i) => (
                <Word key={w + i} p={scrollYProgress} i={i} total={WORDS.length}>
                  {w}
                </Word>
              ))}
        </p>
      </div>
    </section>
  );
}
