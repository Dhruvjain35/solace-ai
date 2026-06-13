import { useEffect, useRef, useState } from 'react';
import {
  AnimatePresence,
  motion,
  useReducedMotion,
  useScroll,
  useSpring,
} from 'framer-motion';
import { ArrowUp, ChevronDown } from 'lucide-react';
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

// Mobile section nav (<lg): a sticky pill that names the section you're in and
// drops down the full numbered list to jump. Mirrors the desktop scroll-spy so
// long legal docs are navigable on a phone, where the sidebar TOC is hidden.
export function MobileToc({ sections }: { sections: LegalSection[] }) {
  const ids = sections.map((s) => s.id);
  const active = useScrollSpy(ids);
  const [open, setOpen] = useState(false);
  const activeIdx = Math.max(
    0,
    sections.findIndex((s) => s.id === active),
  );
  const activeTitle = sections[activeIdx]?.title ?? 'On this page';

  return (
    <div className="sticky top-[72px] z-30 -mx-6 mb-8 px-6 lg:hidden">
      <div className="overflow-hidden rounded-pill border border-black/10 bg-white/90 shadow-soft backdrop-blur-md">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left"
        >
          <span className="flex min-w-0 items-center gap-2.5">
            <span className="font-mono text-[10.5px] tabular-nums text-solace-green-500">
              {String(activeIdx + 1).padStart(2, '0')}
            </span>
            <span className="truncate text-[13.5px] font-medium text-ink">{activeTitle}</span>
          </span>
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={`shrink-0 text-muted transition-transform duration-300 ease-hims-expo ${
              open ? 'rotate-180' : ''
            }`}
          />
        </button>
      </div>
      <AnimatePresence>
        {open ? (
          <motion.nav
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            aria-label="On this page"
            className="mt-2 overflow-hidden rounded-hims border border-black/10 bg-white shadow-lift"
          >
            <ul className="max-h-[58vh] overflow-y-auto py-2">
              {sections.map((s, i) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    onClick={() => setOpen(false)}
                    aria-current={s.id === active ? 'true' : undefined}
                    className={`flex items-center gap-2.5 px-5 py-2.5 text-[13.5px] transition-colors ${
                      s.id === active
                        ? 'font-medium text-solace-green-700'
                        : 'text-muted hover:text-solace-green-700'
                    }`}
                  >
                    <span className="font-mono text-[10.5px] tabular-nums text-solace-green-500/70">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    {s.title}
                  </a>
                </li>
              ))}
            </ul>
          </motion.nav>
        ) : null}
      </AnimatePresence>
    </div>
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
