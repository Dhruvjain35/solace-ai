/**
 * Tour step + tour definitions for the in-app product tour.
 *
 * A step either spotlights an on-page anchor (matched by `data-tour="<anchor>"`)
 * or, when `anchor` is omitted, renders as a centred modal (good for intro /
 * outro slides and for surfaces where no single element should be highlighted).
 */

export type TourStep = {
  /** Stable id for the step (used as React key). */
  id: string;
  /** Short heading shown in the coachmark card. */
  title: string;
  /** One or two sentences of body copy. No emojis — clinical tool. */
  body: string;
  /**
   * `data-tour` value of the element to spotlight. When absent the step is a
   * centred modal with no cut-out.
   */
  anchor?: string;
  /** Preferred placement of the card relative to the anchor. Auto-flips if off-screen. */
  placement?: "top" | "bottom" | "left" | "right" | "auto";
};

export type TourDefinition = {
  /** Stable tour id — part of the localStorage key. Never change once shipped. */
  id: string;
  /** Human label for the launcher button tooltip. */
  label: string;
  steps: TourStep[];
};
