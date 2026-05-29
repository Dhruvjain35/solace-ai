/**
 * useTour — headless driver for the in-app product tour.
 *
 * Responsibilities:
 *  - track the active step index
 *  - resolve the spotlight rect for the current step's `data-tour` anchor
 *  - skip steps whose anchor is not currently in the DOM (e.g. a closed drawer)
 *  - persist progress (resume / done) per tour + subject in localStorage
 *  - keep the spotlight aligned on scroll / resize
 *
 * Rendering lives in <TourOverlay />. This hook owns no JSX so it stays testable.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { TourDefinition, TourStep } from "../lib/tour-types";
import { writeProgress } from "../lib/tour-storage";

export type SpotlightRect = {
  top: number;
  left: number;
  width: number;
  height: number;
} | null;

function findAnchor(anchor: string | undefined): HTMLElement | null {
  if (!anchor) return null;
  return document.querySelector<HTMLElement>(`[data-tour="${anchor}"]`);
}

function rectOf(el: HTMLElement | null): SpotlightRect {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

export type UseTour = {
  active: boolean;
  step: TourStep | null;
  stepIndex: number;
  stepCount: number;
  rect: SpotlightRect;
  start: () => void;
  next: () => void;
  prev: () => void;
  finish: () => void;
};

export function useTour(def: TourDefinition, subjectId: string): UseTour {
  const [active, setActive] = useState(false);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<SpotlightRect>(null);
  const indexRef = useRef(index);
  indexRef.current = index;

  const steps = def.steps;
  const step = active ? steps[index] ?? null : null;

  // Return the index of the next step (from `from`, inclusive, in `dir`) whose
  // anchor exists — or whose anchor is undefined (modal step). Returns -1 when
  // none remain in that direction.
  const resolveIndex = useCallback(
    (from: number, dir: 1 | -1): number => {
      let i = from;
      while (i >= 0 && i < steps.length) {
        const s = steps[i];
        if (!s.anchor || findAnchor(s.anchor)) return i;
        i += dir;
      }
      return -1;
    },
    [steps],
  );

  const start = useCallback(() => {
    const first = resolveIndex(0, 1);
    if (first === -1) return;
    setIndex(first);
    setActive(true);
    writeProgress(def.id, subjectId, { step: first, status: "active" });
  }, [def.id, subjectId, resolveIndex]);

  const finish = useCallback(() => {
    setActive(false);
    writeProgress(def.id, subjectId, { step: indexRef.current, status: "done" });
  }, [def.id, subjectId]);

  const next = useCallback(() => {
    const candidate = resolveIndex(indexRef.current + 1, 1);
    if (candidate === -1) {
      finish();
      return;
    }
    setIndex(candidate);
    writeProgress(def.id, subjectId, { step: candidate, status: "active" });
  }, [def.id, subjectId, resolveIndex, finish]);

  const prev = useCallback(() => {
    const candidate = resolveIndex(indexRef.current - 1, -1);
    if (candidate === -1) return;
    setIndex(candidate);
    writeProgress(def.id, subjectId, { step: candidate, status: "active" });
  }, [def.id, subjectId, resolveIndex]);

  // Measure the current anchor, scrolling it into view first. Re-measure on
  // scroll/resize while the tour is active so the spotlight tracks the element.
  useLayoutEffect(() => {
    if (!active || !step) {
      setRect(null);
      return;
    }
    const el = findAnchor(step.anchor);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    }
    // Defer one frame so smooth-scroll has begun before the first measurement.
    const raf = requestAnimationFrame(() => setRect(rectOf(el)));

    const remeasure = () => setRect(rectOf(findAnchor(step.anchor)));
    window.addEventListener("scroll", remeasure, true);
    window.addEventListener("resize", remeasure);
    const interval = window.setInterval(remeasure, 250); // catch layout settling

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", remeasure, true);
      window.removeEventListener("resize", remeasure);
      window.clearInterval(interval);
    };
  }, [active, step, index]);

  // Escape closes the tour.
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, finish, next, prev]);

  return {
    active,
    step,
    stepIndex: index,
    stepCount: steps.length,
    rect,
    start,
    next,
    prev,
    finish,
  };
}
