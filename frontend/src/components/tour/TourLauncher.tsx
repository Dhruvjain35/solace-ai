/**
 * TourLauncher — drop-in, self-contained product-tour entry point.
 *
 * Mount one per page that should have a tour:
 *
 *   <TourLauncher tourId="clinician-dashboard-v1" />
 *
 * It renders:
 *   - a small HelpCircle affordance (fixed, top-right by default) to launch /
 *     replay the tour on demand
 *   - the <TourOverlay /> while the tour is running
 *
 * It auto-starts the tour once per subject (clinician or patient bucket) on
 * first run, then never again unless re-launched from the button.
 *
 * The launcher is purely additive: it touches no page state. Add the matching
 * `data-tour="<anchor>"` attributes to the page elements named in the tour
 * definition (see src/lib/tours.ts).
 */

import { useEffect, useMemo, useRef } from "react";
import { HelpCircle } from "lucide-react";
import { useTour } from "../../hooks/useTour";
import { TourOverlay } from "./TourOverlay";
import { TOUR_REGISTRY } from "../../lib/tours";
import { isFirstRun } from "../../lib/tour-storage";
import { loadSession } from "../../lib/session";

type Props = {
  /** Id of a tour in TOUR_REGISTRY. */
  tourId: string;
  /**
   * Override the persistence subject. Defaults to the signed-in clinician_id,
   * falling back to "patient" for unauthenticated surfaces (patient intake).
   */
  subjectId?: string;
  /** Auto-run on first visit. Default true. */
  autoStart?: boolean;
  /**
   * Where to pin the help button. Defaults to top-right, respecting safe-area
   * insets. Set "none" to hide the button entirely (tour only auto-runs).
   */
  buttonPosition?: "top-right" | "bottom-right" | "none";
  /** Extra classes for the help button (e.g. to nudge it for a sidebar layout). */
  buttonClassName?: string;
};

function resolveSubject(explicit?: string): string {
  if (explicit) return explicit;
  const sess = loadSession();
  return sess?.clinician_id || "patient";
}

const POSITIONS: Record<string, string> = {
  "top-right":
    "fixed top-[calc(0.75rem+env(safe-area-inset-top,0px))] right-[calc(0.75rem+env(safe-area-inset-right,0px))]",
  "bottom-right":
    "fixed bottom-[calc(0.75rem+env(safe-area-inset-bottom,0px))] right-[calc(0.75rem+env(safe-area-inset-right,0px))]",
};

export function TourLauncher({
  tourId,
  subjectId,
  autoStart = true,
  buttonPosition = "top-right",
  buttonClassName = "",
}: Props) {
  const def = TOUR_REGISTRY[tourId];
  const subject = useMemo(() => resolveSubject(subjectId), [subjectId]);
  const tour = useTour(def ?? { id: tourId, label: "", steps: [] }, subject);
  const autoRanRef = useRef(false);

  // First-run auto-start. Defer briefly so the page (and any anchors) have
  // mounted before the first step measures its target.
  useEffect(() => {
    if (!def || !autoStart || autoRanRef.current) return;
    if (!isFirstRun(tourId, subject)) return;
    autoRanRef.current = true;
    const t = window.setTimeout(() => tour.start(), 600);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [def, autoStart, tourId, subject]);

  if (!def) return null;

  const posClass = buttonPosition === "none" ? "" : POSITIONS[buttonPosition];

  return (
    <>
      {buttonPosition !== "none" && (
        <button
          type="button"
          onClick={tour.start}
          aria-label={`${def.label} — open product tour`}
          title={def.label}
          data-tour="tour-launcher"
          className={`${posClass} z-[60] w-10 h-10 rounded-full bg-surface-lowest shadow-card ring-1 ring-line text-text-muted hover:text-primary hover:ring-primary/40 flex items-center justify-center transition-colors ${buttonClassName}`}
        >
          <HelpCircle size={20} strokeWidth={1.75} />
        </button>
      )}

      <TourOverlay
        active={tour.active}
        step={tour.step}
        rect={tour.rect}
        stepIndex={tour.stepIndex}
        stepCount={tour.stepCount}
        onNext={tour.next}
        onPrev={tour.prev}
        onClose={tour.finish}
      />
    </>
  );
}
