/**
 * TourOverlay — the visual layer for a running tour.
 *
 * Renders a full-viewport dimmer with a rounded "spotlight" cut-out over the
 * current anchor (via an SVG mask, so the cut-out is crisp and the dimmer is one
 * element) plus a coachmark card positioned near the anchor. When the step has
 * no anchor the card is centred as a modal and no cut-out is drawn.
 *
 * Mobile-first: on narrow viewports the card pins to the bottom of the screen
 * and respects env(safe-area-inset-bottom). Framer Motion drives the entrance.
 */

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, X } from "lucide-react";
import type { TourStep } from "../../lib/tour-types";
import type { SpotlightRect } from "../../hooks/useTour";

type Props = {
  active: boolean;
  step: TourStep | null;
  rect: SpotlightRect;
  stepIndex: number;
  stepCount: number;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
};

const PAD = 8; // spotlight padding around the anchor
const CARD_W = 320; // px; clamped to viewport on mobile
const GAP = 14; // gap between anchor and card

function useViewport() {
  const [vp, setVp] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    const on = () => setVp({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return vp;
}

/** Pick a card position next to the anchor, flipping to stay on-screen. */
function cardPosition(
  rect: SpotlightRect,
  vp: { w: number; h: number },
  preferred: TourStep["placement"],
  isMobile: boolean,
): React.CSSProperties {
  // Mobile: always dock to the bottom for thumb reach + predictable layout.
  if (isMobile || !rect) {
    if (!rect && !isMobile) {
      // Desktop modal step — centre it.
      return {
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        width: Math.min(CARD_W, vp.w - 32),
      };
    }
    return {
      left: 16,
      right: 16,
      bottom: "calc(16px + env(safe-area-inset-bottom, 0px))",
      width: "auto",
    };
  }

  const w = Math.min(CARD_W, vp.w - 32);
  const spotTop = rect.top - PAD;
  const spotLeft = rect.left - PAD;
  const spotRight = rect.left + rect.width + PAD;
  const spotBottom = rect.top + rect.height + PAD;
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;

  const spaceBelow = vp.h - spotBottom;
  const spaceAbove = spotTop;
  const spaceRight = vp.w - spotRight;
  const spaceLeft = spotLeft;

  // Resolve "auto" by choosing the side with the most room.
  let place = preferred && preferred !== "auto" ? preferred : "bottom";
  const fits = {
    bottom: spaceBelow > 180,
    top: spaceAbove > 180,
    right: spaceRight > w + GAP,
    left: spaceLeft > w + GAP,
  };
  if (preferred === "auto" || !fits[place as keyof typeof fits]) {
    place =
      (Object.entries(fits).find(([, ok]) => ok)?.[0] as typeof place) ?? "bottom";
  }

  const clampX = (x: number) => Math.max(16, Math.min(x, vp.w - w - 16));
  const clampY = (y: number) => Math.max(16, Math.min(y, vp.h - 200));

  switch (place) {
    case "top":
      return { width: w, left: clampX(centerX - w / 2), top: undefined, bottom: vp.h - spotTop + GAP };
    case "left":
      return { width: w, left: spotLeft - w - GAP, top: clampY(centerY - 90) };
    case "right":
      return { width: w, left: spotRight + GAP, top: clampY(centerY - 90) };
    case "bottom":
    default:
      return { width: w, left: clampX(centerX - w / 2), top: spotBottom + GAP };
  }
}

export function TourOverlay({
  active,
  step,
  rect,
  stepIndex,
  stepCount,
  onNext,
  onPrev,
  onClose,
}: Props) {
  const vp = useViewport();
  const isMobile = vp.w < 640;

  const maskId = "solace-tour-mask";
  const cardStyle = useMemo(
    () => (step ? cardPosition(rect, vp, step.placement, isMobile) : {}),
    [rect, vp, step, isMobile],
  );

  if (!active || !step) return null;

  const isLast = stepIndex >= stepCount - 1;
  const hasSpot = !!rect;

  return createPortal(
    <AnimatePresence>
      <motion.div
        key="solace-tour-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[1000]"
        role="dialog"
        aria-modal="true"
        aria-label={step.title}
      >
        {/* Dimmer with optional spotlight cut-out via SVG mask. Clicking the
            backdrop does nothing (prevents accidental dismissal); use Skip/X. */}
        <svg className="absolute inset-0 w-full h-full" aria-hidden="true">
          <defs>
            <mask id={maskId}>
              <rect x="0" y="0" width="100%" height="100%" fill="white" />
              {hasSpot && rect && (
                <rect
                  x={rect.left - PAD}
                  y={rect.top - PAD}
                  width={rect.width + PAD * 2}
                  height={rect.height + PAD * 2}
                  rx={12}
                  ry={12}
                  fill="black"
                />
              )}
            </mask>
          </defs>
          <rect
            x="0"
            y="0"
            width="100%"
            height="100%"
            fill="rgba(26, 32, 35, 0.55)"
            mask={`url(#${maskId})`}
          />
        </svg>

        {/* Spotlight ring around the anchor. */}
        {hasSpot && rect && (
          <motion.div
            layout
            className="absolute rounded-lg ring-2 ring-white/90 pointer-events-none"
            style={{
              top: rect.top - PAD,
              left: rect.left - PAD,
              width: rect.width + PAD * 2,
              height: rect.height + PAD * 2,
              boxShadow: "0 0 0 9999px rgba(26,32,35,0.0)",
            }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
          />
        )}

        {/* Coachmark card */}
        <motion.div
          key={step.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
          className="absolute bg-surface-lowest rounded-xl shadow-lifted p-5 flex flex-col gap-3"
          style={cardStyle}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold pt-0.5">
              Step {stepIndex + 1} of {stepCount}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close tour"
              className="w-7 h-7 -mt-1 -mr-1 rounded-md hover:bg-surface-low flex items-center justify-center text-text-muted shrink-0"
            >
              <X size={16} />
            </button>
          </div>

          <div>
            <h3 className="text-lg font-bold tracking-editorial text-ink leading-snug">
              {step.title}
            </h3>
            <p className="text-[14px] text-text-muted leading-relaxed mt-1.5">{step.body}</p>
          </div>

          {/* Progress chips — numbered, no emojis. */}
          <div className="flex items-center gap-1.5 pt-1">
            {Array.from({ length: stepCount }).map((_, i) => (
              <span
                key={i}
                className={`h-1.5 rounded-full transition-all ${
                  i === stepIndex ? "w-5 bg-primary" : "w-1.5 bg-line"
                }`}
              />
            ))}
          </div>

          <div className="flex items-center justify-between gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="text-[13px] font-semibold text-text-muted hover:text-ink transition-colors px-1"
            >
              Skip
            </button>
            <div className="flex items-center gap-2">
              {stepIndex > 0 && (
                <button
                  type="button"
                  onClick={onPrev}
                  className="inline-flex items-center gap-1 h-10 px-3 rounded-md text-sm font-semibold text-primary hover:bg-surface-low transition-colors"
                >
                  <ArrowLeft size={15} /> Back
                </button>
              )}
              <button
                type="button"
                onClick={onNext}
                className="inline-flex items-center gap-1.5 h-10 px-4 rounded-md text-sm font-semibold text-white bg-primary bg-primary-gradient shadow-soft hover:brightness-110 transition-all active:scale-[0.98]"
              >
                {isLast ? "Done" : "Next"}
                {!isLast && <ArrowRight size={15} />}
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  );
}
