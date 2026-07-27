import { motion } from 'framer-motion';
import { himsFade, himsMove } from '../../lib/hims';

/*
 * ExpandingLogo, the navbar mark. Idle is the standalone "S" (solace-mark.png);
 * when `expanded` (hover, or the one-shot intro on first load) the "solace"
 * wordmark unfurls to its right by animating the clip width, on the house
 * curves. Sizes keep the real logo's proportions: the box sits a touch taller
 * than the wordmark's letters, exactly like the full lockup.
 */

// mark 80x99 (aspect 0.808); word 206x70 (aspect 2.943). The word renders
// shorter than the mark so its letters match the box's lockup proportions.
const MARK_H = 36;
const MARK_W = Math.round(MARK_H * 0.808); // 29
const WORD_H = 26;
const WORD_W = Math.round(WORD_H * 2.943); // 77
const GAP = 10;
const REVEAL_W = WORD_W + GAP;

type Props = {
  expanded: boolean;
  reduce: boolean | null;
  light?: boolean;
  className?: string;
};

export default function ExpandingLogo({ expanded, reduce, light = false, className = '' }: Props) {
  const tint = light ? '[filter:brightness(0)_invert(1)]' : '';
  // Reduced motion: show the full lockup, no unfurl.
  const open = reduce ? true : expanded;

  return (
    <span className={`flex items-center ${className}`} style={{ height: MARK_H }}>
      <img
        src="/assets/solace-mark.png"
        alt=""
        draggable={false}
        className={`select-none ${tint}`}
        style={{ height: MARK_H, width: MARK_W }}
      />
      <motion.span
        aria-hidden="true"
        className="flex items-center overflow-hidden"
        style={{ height: MARK_H }}
        initial={reduce ? false : { width: 0, opacity: 0 }}
        animate={open ? { width: REVEAL_W, opacity: 1 } : { width: 0, opacity: 0 }}
        transition={reduce ? { duration: 0 } : { width: himsMove, opacity: himsFade }}
      >
        <img
          src="/assets/solace-word.png"
          alt="Solace"
          draggable={false}
          className={`w-auto max-w-none select-none ${tint}`}
          style={{ height: WORD_H, marginLeft: GAP }}
        />
      </motion.span>
    </span>
  );
}
