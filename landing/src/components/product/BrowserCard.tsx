import { motion, useReducedMotion } from 'framer-motion';
import { Lock } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';

/*
 * BrowserCard — a floating macOS-style browser window, used as the overlapping
 * secondary mockup beside the laptop on the Product page's black clinician
 * stage. Pure CSS chrome (traffic lights, URL pill, top sheen) around a real
 * dashboard screenshot, with a faint flipped reflection pooling beneath it.
 *
 * Motion follows the house two-curve rule: opacity on HIMS_OUT (~0.2s),
 * transforms on HIMS_EXPO (~0.6s). The card enters once via whileInView,
 * rising 48px while settling from -2.5° to its resting -1.5° tilt, then idles
 * on a 7s float. Under prefers-reduced-motion or <lg the card sits flat and
 * static — only the opacity fade remains; the reflection is static and stays.
 */

interface BrowserCardProps {
  src: string;
  alt: string;
  url?: string;
  className?: string;
}

const TRAFFIC_LIGHTS = ['#ff5f57', '#febc2e', '#28c840'] as const;

// The window itself, rendered twice: once for real, once flipped as the
// reflection (`ghost` strips the alt so screen readers only meet the image
// once — all surrounding chrome is aria-hidden either way).
function WindowChrome({
  src,
  alt,
  url,
  ghost = false,
}: {
  src: string;
  alt: string;
  url: string;
  ghost?: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-[12px] bg-[#15171a] shadow-pop ring-1 ring-white/10">
      {/* Title bar — decorative chrome only */}
      <div
        aria-hidden="true"
        className="relative flex h-9 items-center gap-2 border-b border-white/5 bg-[#1d2024] px-4"
      >
        {TRAFFIC_LIGHTS.map((color) => (
          <span
            key={color}
            className="h-[10px] w-[10px] shrink-0 rounded-full ring-1 ring-black/20"
            style={{ backgroundColor: color }}
          />
        ))}
        <span className="absolute left-1/2 top-1/2 inline-flex max-w-[60%] -translate-x-1/2 -translate-y-1/2 items-center gap-1.5 whitespace-nowrap rounded-pill bg-black/30 px-4 py-1 text-[11px] font-medium leading-none text-white/50">
          <Lock size={10} strokeWidth={2.5} className="shrink-0" />
          <span className="truncate">{url}</span>
        </span>
      </div>

      {/* Body — the screenshot, with a top inner sheen like lit glass */}
      <div className="relative">
        <img
          src={src}
          alt={ghost ? '' : alt}
          width={1600}
          height={1000}
          loading="lazy"
          decoding="async"
          className="block h-auto w-full object-cover"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white/[0.03] to-transparent"
        />
      </div>
    </div>
  );
}

export default function BrowserCard({
  src,
  alt,
  url = 'solace.health/clinician',
  className,
}: BrowserCardProps) {
  const reduce = useReducedMotion();
  const isWide = useIsWide();
  // Flat and motionless under reduced motion, and simplified below lg where
  // the stage stacks — only the opacity fade carries the entrance.
  const still = reduce || !isWide;

  return (
    <motion.div
      initial={{ opacity: 0, y: still ? 0 : 48, rotate: still ? 0 : -2.5 }}
      whileInView={{ opacity: 1, y: 0, rotate: still ? 0 : -1.5 }}
      viewport={{ once: true, amount: 0.35 }}
      transition={{ ...himsMove, opacity: himsFade }}
      className={className}
    >
      {/* Continuous idle float; reflection rides along inside this wrapper */}
      <motion.div
        animate={still ? undefined : { y: [0, -8, 0] }}
        transition={
          still ? undefined : { duration: 7, ease: 'easeInOut', repeat: Infinity }
        }
        style={still ? undefined : { willChange: 'transform' }}
        className="relative"
      >
        <WindowChrome src={src} alt={alt} url={url} />

        {/* Faint reflection pooled on the black stage — static, always kept.
            The mask lives on the (unflipped) wrapper so the fade reads
            top-to-bottom in screen space; positioned absolutely so the extra
            copy never adds layout height. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-full -mt-1 opacity-[0.12]"
          style={{
            WebkitMaskImage:
              'linear-gradient(to bottom, rgba(0,0,0,0.35), transparent 55%)',
            maskImage:
              'linear-gradient(to bottom, rgba(0,0,0,0.35), transparent 55%)',
          }}
        >
          <div className="-scale-y-100">
            <WindowChrome src={src} alt={alt} url={url} ghost />
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
