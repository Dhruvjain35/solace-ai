import { motion, useReducedMotion } from "framer-motion";

const ITEMS = [
  "AI Scribe",
  "Smart Triage",
  "EHR Copilot",
  "SMART on FHIR R4",
  "PHI isolation in code",
  "Confirm-gated writes",
  "Explainable ESI",
  "749 checks green",
];

/** Infinite editorial marquee strip — serif words separated by teal ticks. */
export function Marquee() {
  const reduced = useReducedMotion();
  const row = (
    <div className="flex shrink-0 items-center">
      {ITEMS.map((t) => (
        <span key={t} className="flex items-center">
          <span className="whitespace-nowrap px-6 font-display text-2xl tracking-editorial text-ink/80 sm:px-9 sm:text-3xl">
            {t}
          </span>
          <span aria-hidden="true" className="h-2 w-2 rotate-45 bg-primary/50" />
        </span>
      ))}
    </div>
  );
  return (
    <section aria-label="Solace capabilities" className="overflow-hidden border-y border-line bg-surface-lowest py-7">
      {reduced ? (
        <div className="overflow-x-auto">{row}</div>
      ) : (
        <motion.div
          className="flex w-max"
          animate={{ x: ["0%", "-50%"] }}
          transition={{ duration: 36, repeat: Infinity, ease: "linear" }}
        >
          {row}
          {row}
        </motion.div>
      )}
    </section>
  );
}
