// Motion presets — values extracted 1:1 from cruisenow.ai via designlang.
// Easing is easeOutQuart, the single curve the reference uses everywhere.
import type { Variants, Transition } from 'framer-motion';

export const EASE = [0.25, 1, 0.5, 1] as const;

export const DURATION = { fast: 0.15, base: 0.3, slow: 0.54 } as const;

export const transitions = {
  base: { duration: DURATION.base, ease: EASE },
  fast: { duration: DURATION.fast, ease: EASE },
  slow: { duration: DURATION.slow, ease: EASE },
  spring: { type: 'spring', stiffness: 320, damping: 30 },
} satisfies Record<string, Transition>;

export const fade: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: transitions.base },
};

export const slideUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: transitions.slow },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  show: { opacity: 1, scale: 1, transition: transitions.base },
};

export const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.075, delayChildren: 0.05 } },
};

// Standard in-view reveal props for a section wrapper.
export const reveal = {
  initial: 'hidden',
  whileInView: 'show',
  viewport: { once: true, amount: 0.25 },
} as const;
