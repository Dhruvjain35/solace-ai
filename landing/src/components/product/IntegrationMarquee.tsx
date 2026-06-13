import { useState, type ReactNode } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Leaf, Asterisk } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';

/*
 * IntegrationMarquee — the "works with your EHR" wall, modelled on
 * app.forhims.com's integration band: an eyebrow + headline over two rows of
 * logo cards scrolling in opposite directions, faded at both edges, then a
 * one-line promise.
 *
 * Each brand shows a real logo from public/assets/integrations/<key>.png when
 * present, and otherwise falls back to a brand-styled wordmark — so dropping a
 * transparent PNG into that folder swaps it in with zero code changes.
 */

type Brand = { key: string; alt: string; mark: ReactNode };

const ROW_A: Brand[] = [
  { key: 'epic', alt: 'Epic', mark: <span className="text-[24px] font-extrabold italic tracking-tight text-[#A4123F]">Epic</span> },
  { key: 'oracle-health', alt: 'Oracle Health', mark: <span className="text-[20px] font-semibold tracking-tight text-[#C74634]">Oracle Health</span> },
  { key: 'athenahealth', alt: 'athenahealth', mark: (
    <span className="flex items-center gap-1.5 text-[19px] font-semibold tracking-tight text-[#582C83]">
      <Leaf size={17} className="text-[#7AB800]" aria-hidden="true" />athenahealth
    </span>
  ) },
  { key: 'cerner', alt: 'Cerner', mark: <span className="text-[22px] font-semibold tracking-tight text-[#1A9CA6]">Cerner</span> },
  { key: 'nextgen', alt: 'NextGen Healthcare', mark: <span className="text-[21px] font-bold lowercase tracking-tight text-[#E0531F]">nextgen<span className="text-ink">.</span></span> },
  { key: 'elation', alt: 'Elation Health', mark: (
    <span className="flex items-center text-[21px] font-medium tracking-tight text-[#16A3C7]">
      <Asterisk size={18} strokeWidth={2.5} aria-hidden="true" />Elation
    </span>
  ) },
  { key: 'drchrono', alt: 'DrChrono', mark: <span className="text-[20px] font-semibold tracking-tight text-[#3CAE2B]">dr<span className="text-ink">chrono</span></span> },
];

const ROW_B: Brand[] = [
  { key: 'eclinicalworks', alt: 'eClinicalWorks', mark: <span className="text-[18px] font-semibold italic tracking-tight text-[#1C2B4A]">eClinicalWorks</span> },
  { key: 'advancedmd', alt: 'AdvancedMD', mark: <span className="text-[20px] font-semibold tracking-tight text-[#3C4651]">Advanced<span className="text-[#E8772E]">MD</span></span> },
  { key: 'veradigm', alt: 'Veradigm', mark: <span className="text-[20px] font-semibold tracking-tight text-[#2A1A57]">veradigm</span> },
  { key: 'meditech', alt: 'MEDITECH', mark: <span className="text-[18px] font-bold tracking-[0.04em] text-[#3FAE6B]">MEDITECH</span> },
  { key: 'practice-fusion', alt: 'Practice Fusion', mark: <span className="text-[18px] font-semibold tracking-tight text-[#1C3D6E]">practice<span className="text-[#3AA6E0]">fusion</span></span> },
  { key: 'greenway', alt: 'Greenway Health', mark: <span className="text-[19px] font-bold tracking-tight text-[#3C4651]">Greenway <span className="text-[#2BB673]">Health</span></span> },
  { key: 'smart-on-fhir', alt: 'SMART on FHIR', mark: <span className="text-[19px] font-semibold tracking-tight text-ink">SMART <span className="text-solace-green-600">on FHIR</span></span> },
];

function LogoSlot({ brand }: { brand: Brand }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="mx-2 flex h-[88px] w-[200px] shrink-0 items-center justify-center rounded-2xl bg-white px-6 shadow-soft ring-1 ring-black/[0.05]">
      {failed ? (
        brand.mark
      ) : (
        <img
          src={`/assets/integrations/${brand.key}.png`}
          alt={brand.alt}
          loading="lazy"
          onError={() => setFailed(true)}
          className="max-h-[44px] max-w-[152px] object-contain"
        />
      )}
    </div>
  );
}

const EDGE_MASK =
  '[mask-image:linear-gradient(to_right,transparent,black_7%,black_93%,transparent)]';

function Row({ items, reverse }: { items: Brand[]; reverse?: boolean }) {
  const reduce = useReducedMotion();
  const strip = (
    <div className="flex shrink-0">
      {items.map((b) => (
        <LogoSlot key={b.key} brand={b} />
      ))}
    </div>
  );
  if (reduce) {
    return <div className={`overflow-x-auto ${EDGE_MASK}`}>{strip}</div>;
  }
  return (
    <div className={`overflow-hidden ${EDGE_MASK}`}>
      <motion.div
        className="flex w-max"
        animate={{ x: reverse ? ['-50%', '0%'] : ['0%', '-50%'] }}
        transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}
      >
        {strip}
        {strip}
      </motion.div>
    </div>
  );
}

export default function IntegrationMarquee() {
  const reduce = useReducedMotion();
  const rise = { ...himsMove, opacity: himsFade };
  return (
    <section
      aria-labelledby="integrations-heading"
      className="overflow-hidden py-[10vh] md:py-[14vh]"
      style={{ backgroundImage: 'linear-gradient(180deg, #ffffff 0%, #f3f5f4 100%)' }}
    >
      <div className="mx-auto max-w-4xl px-6 text-center">
        <motion.p
          initial={{ opacity: 0, y: reduce ? 0 : 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.6 }}
          transition={rise}
          className="text-[13px] font-semibold uppercase tracking-[0.18em] text-solace-green-600"
        >
          Integrations
        </motion.p>
        <motion.h2
          id="integrations-heading"
          initial={{ opacity: 0, y: reduce ? 0 : 32 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.5 }}
          transition={{ ...rise, delay: 0.05 }}
          className="mx-auto mt-5 max-w-[15ch] font-sofia text-[clamp(30px,5vw,72px)] font-medium leading-[1.04] tracking-hims text-ink"
        >
          Works with the EHR you already run.
        </motion.h2>
      </div>

      <div className="mt-12 space-y-4 md:mt-14">
        <Row items={ROW_A} />
        <Row items={ROW_B} reverse />
      </div>

      <motion.p
        initial={{ opacity: 0, y: reduce ? 0 : 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={rise}
        className="mx-auto mt-12 max-w-md px-6 text-center text-base text-muted md:mt-14 md:text-lg"
      >
        Built on SMART on FHIR, so Solace connects to the chart you already keep,
        no rip-and-replace.
      </motion.p>
    </section>
  );
}
