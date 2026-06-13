import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion, useScroll, useSpring } from 'framer-motion';
import { ArrowUp } from 'lucide-react';
import type { LegalSection } from './LegalLayout';

/*
 * Reading affordances for the legal shell: a scroll-linked progress bar pinned
 * to the top of the viewport, a scroll-spy table of contents that highlights
 * the section currently in view, and a numbered "On this page" nav. Split out
 * of LegalLayout so the shell stays declarative and under budget. All three are
 * reduced-motion safe — the bar snaps instead of springs, the spy still tracks.
 */

// Slim brand-mint progress bar fixed at the very top of the page. Rides the
// document scroll; spring-smoothed unless the user prefers reduced motion.
export function ReadingProgress() {
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll();
  const smooth = useSpring(scrollYProgress, {
    stiffness: 120,
    damping: 30,
    restDelta: 0.001,
  });
  const scaleX = reduce ? scrollYProgress : smooth;
  return (
    <motion.div
      aria-hidden="true"
      className="fixed inset-x-0 top-0 z-50 h-[3px] origin-left bg-gradient-to-r from-solace-green-600 via-solace-green-500 to-solace-green-300"
      style={{ scaleX }}
    />
  );
}

// Track which section is currently in view. Returns the active section id.
// Uses an IntersectionObserver with a top-biased root margin so the spy flips
// to a heading slightly before it reaches the top of the viewport.
export function useScrollSpy(ids: string[]): string {
  const [active, setActive] = useState<string>(ids[0] ?? '');
  const seen = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    if (ids.length === 0) return;
    seen.current = new Map();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          seen.current.set(entry.target.id, entry.intersectionRatio);
        }
        // Pick the section closest to the top that is visible; fall back to
        // the last one we saw scrolling down.
        let best = '';
        let bestRatio = 0;
        for (const id of ids) {
          const ratio = seen.current.get(id) ?? 0;
          if (ratio > bestRatio) {
            best = id;
            bestRatio = ratio;
          }
        }
        if (best) setActive(best);
      },
      { rootMargin: '-20% 0px -65% 0px', threshold: [0, 0.25, 0.5, 1] },
    );
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [ids]);

  return active;
}

// The sticky scroll-spy table of contents (≥lg only). Numbered, with a mint
// left-border indicator and mint text on the active section.
export function ScrollSpyToc({ sections }: { sections: LegalSection[] }) {
  const ids = sections.map((s) => s.id);
  const active = useScrollSpy(ids);
  return (
    <aside className="hidden lg:block">
      <div className="sticky top-32">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
          On this page
        </p>
        <nav aria-label="On this page" className="mt-4">
          <ul className="space-y-0.5">
            {sections.map((s, i) => {
              const isActive = s.id === active;
              return (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    aria-current={isActive ? 'true' : undefined}
                    className={`group flex items-start gap-2.5 border-l-2 py-1.5 pl-4 text-[13.5px] leading-snug transition-colors duration-200 ease-hims-expo ${
                      isActive
                        ? 'border-solace-green-500 font-medium text-solace-green-700'
                        : 'border-black/8 text-muted hover:border-solace-green-300 hover:text-solace-green-700'
                    }`}
                  >
                    <span
                      className={`mt-px font-mono text-[10.5px] tabular-nums transition-colors ${
                        isActive
                          ? 'text-solace-green-500'
                          : 'text-muted/50 group-hover:text-solace-green-500'
                      }`}
                    >
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span>{s.title}</span>
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </aside>
  );
}

// A quiet "Back to top" affordance for the end of the document.
export function BackToTop() {
  return (
    <a
      href="#legal-heading"
      className="group mt-12 inline-flex items-center gap-2 rounded-pill border border-black/10 bg-white px-5 py-2.5 text-[13px] font-medium text-muted shadow-soft transition-colors duration-300 ease-hims-expo hover:border-solace-green-300 hover:text-solace-green-700"
    >
      <ArrowUp
        size={14}
        strokeWidth={2}
        aria-hidden="true"
        className="transition-transform duration-300 ease-hims-expo group-hover:-translate-y-0.5"
      />
      Back to top
    </a>
  );
}
