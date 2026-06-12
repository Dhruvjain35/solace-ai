import { Fragment, useMemo, useRef } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useReducedMotion,
  cubicBezier,
  type MotionValue,
} from 'framer-motion';
import { HIMS_OUT } from '../../lib/hims';

/*
 * BigStatement — the giant scroll-revealed paragraph that app.forhims.com uses
 * as connective tissue between scenes (the solid-blue "All in the app." block,
 * the mint→blue gradient manifesto, the teal gradient under the mega-card).
 * Remapped to Solace: caller colors the text via `className`, e.g.
 * "text-solace-green-600", "text-grad-solace" or "text-grad-dark".
 *
 * Mechanic: the text splits into words; each word is an inline-block span whose
 * opacity scrubs 0.16 → 1 as the section crosses the viewport (no sticky track —
 * it reveals in normal flow). Word i's band is [i/n, (i+0.8)/n] of the section's
 * scrollYProgress between 'start 0.85' and 'end 0.45'.
 *
 * Gradient note: per-word spans break background-clip continuity, so the
 * gradient class is applied PER WORD (the reference's gradient also flows
 * roughly per-line, so this reads true). Opacity lives on a wrapper span, never
 * on the clipped span itself.
 */

// Dimmed resting opacity of unrevealed words (reference scrubs from ~16%).
const DIM = 0.16;

// Opacity moves on the house out-curve.
const EASE_OUT = cubicBezier(...HIMS_OUT);

// Word i of n reveals across this slice of the section's scroll progress.
function band(i: number, n: number): [number, number] {
  return [i / n, Math.min((i + 0.8) / n, 1)];
}

function Word({
  word,
  progress,
  range,
  colorClass,
  reduce,
}: {
  word: string;
  progress: MotionValue<number>;
  range: [number, number];
  colorClass: string;
  reduce: boolean | null;
}) {
  const opacity = useTransform(progress, range, [DIM, 1], { ease: EASE_OUT });
  return (
    <motion.span
      className="inline-block"
      style={{ opacity: reduce ? 1 : opacity }}
    >
      <span className={colorClass}>{word}</span>
    </motion.span>
  );
}

export interface BigStatementProps {
  text: string;
  className?: string;
  align?: 'left' | 'center';
  lastLineBreak?: boolean;
}

export default function BigStatement({
  text,
  className = 'text-solace-green-600',
  align = 'left',
  lastLineBreak = false,
}: BigStatementProps) {
  const sectionRef = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();

  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start 0.85', 'end 0.45'],
  });

  // Paragraph blocks: split on "\n" (the "All in the app." stinger arrives as
  // its own line). If `lastLineBreak` is set and no "\n" was given, break the
  // final sentence out into its own block instead.
  const { blocks, total } = useMemo(() => {
    let parts = text
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    if (lastLineBreak && parts.length === 1) {
      const only = parts[0];
      const cut = only.lastIndexOf('. ');
      if (cut !== -1 && cut + 2 < only.length) {
        parts = [only.slice(0, cut + 1), only.slice(cut + 2)];
      }
    }
    let offset = 0;
    const blocks = parts.map((p) => {
      const words = p.split(/\s+/);
      const block = { words, offset };
      offset += words.length;
      return block;
    });
    return { blocks, total: offset };
  }, [text, lastLineBreak]);

  return (
    <section ref={sectionRef} className="relative py-[12vh] lg:py-[24vh]">
      <div className="mx-auto max-w-5xl px-6 md:px-12">
        <p
          className={`max-w-[24ch] font-sofia text-[clamp(34px,4.6vw,64px)] font-medium leading-[1.18] tracking-[-0.02em] ${
            align === 'center' ? 'mx-auto text-center' : ''
          }`}
        >
          {/* Plain copy for assistive tech; the word-split layer is decorative. */}
          <span className="sr-only">{text}</span>
          <span aria-hidden="true">
            {blocks.map(({ words, offset }, bi) => (
              <span key={bi} className={`block ${bi > 0 ? 'mt-[1.1em]' : ''}`}>
                {words.map((word, wi) => (
                  <Fragment key={offset + wi}>
                    <Word
                      word={word}
                      progress={scrollYProgress}
                      range={band(offset + wi, total)}
                      colorClass={className}
                      reduce={reduce}
                    />{' '}
                  </Fragment>
                ))}
              </span>
            ))}
          </span>
        </p>
      </div>
    </section>
  );
}
