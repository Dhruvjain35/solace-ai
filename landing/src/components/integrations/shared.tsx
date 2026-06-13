import { useState } from 'react';
import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { himsFade, himsMove } from '../../lib/hims';
import type { Integration } from '../../lib/integrations';

/*
 * Shared building blocks for the /integrations hub and the per-platform guide
 * pages. Everything rides the two house curves from ../../lib/hims and respects
 * reduced motion, matching HowItWorks / Clinicians exactly. The two pages own
 * their own layout; this file keeps the repeated atoms (reveal, logo+fallback,
 * tier chip, framed screenshot) in one place so each page stays under 500 lines.
 */

// Barely-there section washes, the hims band rhythm shared across the site.
export const WASH_WHITE_TO_MINT =
  'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';
export const WASH_MINT_TO_WHITE =
  'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)';
export const WASH_PAPER = 'linear-gradient(180deg, #fafaf8 0%, #fafaf8 100%)';

// The pale teal tile gradient, same stops as the Product tile wall.
export const PALE_GRADIENT =
  'linear-gradient(166.14deg, rgb(232,244,247) 0%, rgb(199,229,221) 100%)';

export const PILL_DARK =
  'inline-flex items-center justify-center gap-2 rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';
export const PILL_LIGHT =
  'inline-flex items-center justify-center gap-2 rounded-pill border border-ink/10 bg-white px-7 py-3.5 text-sm font-medium text-ink shadow-soft transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]';

// House reveal: opacity on HIMS_OUT (0.2s), y on HIMS_EXPO (0.6s), siblings
// stagger 0.04s by index. y is zeroed under reduced motion.
export function Reveal({
  index = 0,
  reduce,
  className,
  children,
}: {
  index?: number;
  reduce: boolean | null;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{
        opacity: { ...himsFade, delay: index * 0.04 },
        y: { ...himsMove, delay: index * 0.04 },
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// Tiny uppercase kicker, the Product tile pattern.
export function Kicker({
  tone = 'light',
  children,
}: {
  tone?: 'light' | 'dark';
  children: string;
}) {
  return (
    <p
      className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${
        tone === 'dark' ? 'text-white/55' : 'text-muted'
      }`}
    >
      {children}
    </p>
  );
}

// The platform logo with the brand-wordmark fallback — the LogoCard image+
// fallback idiom from IntegrationMarquee, sized by `size`.
const LOGO_SIZE = {
  sm: 'max-h-[40px] max-w-[148px]',
  lg: 'max-h-[64px] max-w-[280px]',
} as const;

export function Logo({
  item,
  size = 'sm',
}: {
  item: Integration;
  size?: keyof typeof LOGO_SIZE;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="whitespace-nowrap">{item.mark}</span>;
  return (
    <img
      src={`/assets/integrations/${item.slug}.png`}
      alt={item.name}
      loading="lazy"
      onError={() => setFailed(true)}
      className={`${LOGO_SIZE[size]} object-contain`}
    />
  );
}

// The tier chip: native adapters and the SMART standard read visibly distinct
// but consistent — a filled mint chip for native, an outline chip for SMART.
export function TierChip({ tier }: { tier: Integration['tier'] }) {
  if (tier === 'native') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-pill bg-solace-soft px-3 py-1.5 text-[12px] font-semibold tracking-[0.01em] text-solace-green-700 ring-1 ring-solace-green-300/50">
        Native adapter
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-pill bg-white px-3 py-1.5 text-[12px] font-semibold tracking-[0.01em] text-muted ring-1 ring-black/[0.08]">
      SMART on FHIR
    </span>
  );
}

// A real product screenshot framed in a clean rounded shadow-card — the
// BrowserCard idiom. `caption` labels what the shot shows.
export function ShotCard({
  src,
  alt,
  caption,
  reduce,
  index = 0,
}: {
  src: string;
  alt: string;
  caption?: string;
  reduce: boolean | null;
  index?: number;
}) {
  return (
    <motion.figure
      initial={{ opacity: 0, y: reduce ? 0 : 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{
        opacity: { ...himsFade, delay: index * 0.04 },
        y: { ...himsMove, delay: index * 0.04 },
      }}
      className="overflow-hidden rounded-hims bg-white shadow-card ring-1 ring-black/[0.06]"
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className="block h-auto w-full object-cover"
      />
      {caption ? (
        <figcaption className="border-t border-black/[0.05] px-5 py-3 text-[13px] text-muted">
          {caption}
        </figcaption>
      ) : null}
    </motion.figure>
  );
}
