import { motion, useReducedMotion } from 'framer-motion';
import { himsFade, himsMove } from '../../lib/hims';

/*
 * ProductWord — the giant product-type word that opens each act (Intake,
 * Triage., ...). Enters with a horizontal SLIDE inside a clipping wrapper:
 * the word travels in from one side while the mask hides the overshoot.
 * House two-curve rule holds: opacity rides himsFade, the x transform rides
 * himsMove. Direction alternates per act so consecutive products feel like
 * panels sliding through the page.
 */
export default function ProductWord({
  word,
  from = 'right',
  id,
  className = '',
}: {
  word: string;
  /** Which side the word slides in from. */
  from?: 'left' | 'right';
  id?: string;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const offset = from === 'right' ? '38%' : '-38%';
  return (
    <div className="overflow-hidden">
      <motion.h2
        id={id}
        initial={{ opacity: 0, x: reduce ? 0 : offset }}
        whileInView={{ opacity: 1, x: 0 }}
        viewport={{ once: true, amount: 0.4 }}
        transition={{ opacity: himsFade, x: himsMove }}
        className={`font-sofia font-medium leading-none tracking-hims will-change-transform ${className}`}
      >
        {word}
      </motion.h2>
    </div>
  );
}
