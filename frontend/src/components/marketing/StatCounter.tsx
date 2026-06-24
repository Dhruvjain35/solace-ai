import { useEffect, useRef, useState } from "react";
import { useInView, useReducedMotion } from "framer-motion";

type Props = {
  value: number;
  /** Rendered before the numeral, e.g. "<". */
  prefix?: string;
  /** Rendered after the numeral, e.g. "+", "s", "%". */
  suffix?: string;
  label: string;
  /** Light text for dark inversion bands. */
  inverse?: boolean;
  durationMs?: number;
};

/** Big serif numeral that counts up the first time it scrolls into view. */
export function StatCounter({ value, prefix = "", suffix = "", label, inverse, durationMs = 1400 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(reduced ? value : 0);

  useEffect(() => {
    if (!inView || reduced) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      // easeOutCubic so the last digits settle gently
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(Math.round(value * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, reduced, value, durationMs]);

  const shown = reduced || !inView ? (reduced ? value : display) : display;
  return (
    <div ref={ref} className="text-center">
      <div
        className={`font-display text-5xl sm:text-6xl tracking-editorial-tight ${
          inverse ? "text-white" : "text-ink"
        }`}
      >
        {prefix}
        {shown.toLocaleString()}
        {suffix}
      </div>
      <div className={`mt-2 text-sm ${inverse ? "text-primary-fixed/80" : "text-text-muted"}`}>{label}</div>
    </div>
  );
}
