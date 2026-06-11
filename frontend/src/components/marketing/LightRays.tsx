import { motion, useReducedMotion } from "framer-motion";

/**
 * Soft teal light field behind marketing heroes: two blurred orbs + a faint
 * conic cone, drifting very slowly. Decorative only.
 */
export function LightRays() {
  const reduced = useReducedMotion();
  const drift = (dur: number, dx: number, dy: number) =>
    reduced
      ? {}
      : {
          animate: { x: [0, dx, 0], y: [0, dy, 0] },
          transition: { duration: dur, repeat: Infinity, ease: "easeInOut" as const },
        };
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      <motion.div
        className="absolute -top-32 left-1/2 h-[480px] w-[680px] -translate-x-1/2 rounded-full opacity-[0.16] blur-[90px]"
        style={{ background: "conic-gradient(from 200deg at 50% 30%, #CBE3E9, #3B5E67 35%, #D8ECF0 70%, #CBE3E9)" }}
        {...drift(26, 18, 10)}
      />
      <motion.div
        className="absolute top-24 -left-24 h-72 w-72 rounded-full bg-primary-fixed opacity-[0.22] blur-[80px]"
        {...drift(32, 24, -14)}
      />
      <motion.div
        className="absolute top-10 -right-20 h-80 w-80 rounded-full bg-secondary-container opacity-[0.26] blur-[90px]"
        {...drift(38, -20, 16)}
      />
    </div>
  );
}
