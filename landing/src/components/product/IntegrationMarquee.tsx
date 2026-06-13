import type { ReactNode } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Leaf, Asterisk } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';

/*
 * IntegrationMarquee — the "works with your EHR" wall, modelled on
 * app.forhims.com's integration band: an eyebrow + headline over two rows of
 * logo cards that scroll in opposite directions, fading at both edges, then a
 * one-line promise. Logos are brand-styled wordmarks (crisp at any size, no
 * broken images); drop real SVGs into public/assets/integrations to swap them.
 */

// Each brand rendered as an approximate wordmark in its signature colour.
const brand = (node: ReactNode) => node;

const ROW_A: ReactNode[] = [
  <span key="epic" className="text-[24px] font-extrabold italic tracking-tight text-[#A4123F]">Epic</span>,
  <span key="oracle" className="text-[20px] font-semibold tracking-tight text-[#C74634]">Oracle Health</span>,
  <span key="athena" className="flex items-center gap-1.5 text-[19px] font-semibold tracking-tight text-ink">
    <Leaf size={17} className="text-[#7AB800]" aria-hidden="true" />athenahealth
  </span>,
  <span key="cerner" className="text-[22px] font-semibold tracking-tight text-[#1A9CA6]">Cerner</span>,
  <span key="nextgen" className="text-[21px] font-bold lowercase tracking-tight text-[#E0531F]">nextgen<span className="text-ink">.</span></span>,
  <span key="elation" className="flex items-center text-[21px] font-medium tracking-tight text-[#16A3C7]">
    <Asterisk size={18} strokeWidth={2.5} aria-hidden="true" />Elation
  </span>,
  <span key="drchrono" className="text-[20px] font-semibold tracking-tight text-[#3CAE2B]">dr<span className="text-ink">chrono</span></span>,
];

const ROW_B: ReactNode[] = [
  <span key="eclinical" className="text-[18px] font-semibold tracking-tight text-[#1C2B4A]">eClinicalWorks</span>,
  <span key="advancedmd" className="text-[20px] font-semibold tracking-tight text-[#E8772E]">Advanced<span className="text-ink">MD</span></span>,
  <span key="veradigm" className="text-[20px] font-semibold tracking-tight text-[#5B2D8E]">Veradigm</span>,
  <span key="meditech" className="text-[18px] font-bold tracking-[0.04em] text-[#0B5FA5]">MEDITECH</span>,
  <span key="practicefusion" className="text-[18px] font-semibold tracking-tight text-[#2E7D5B]">Practice Fusion</span>,
  <span key="smart" className="text-[19px] font-semibold tracking-tight text-ink">SMART <span className="text-solace-green-600">on FHIR</span></span>,
  <span key="onc" className="text-[20px] font-semibold tracking-tight text-[#1A6BB0]">Greenway</span>,
];

function LogoCard({ children }: { children: ReactNode }) {
  return (
    <div className="mx-2 flex h-[88px] w-[200px] shrink-0 items-center justify-center rounded-2xl bg-white shadow-soft ring-1 ring-black/[0.05]">
      {children}
    </div>
  );
}

const EDGE_MASK =
  '[mask-image:linear-gradient(to_right,transparent,black_7%,black_93%,transparent)]';

function Row({ items, reverse }: { items: ReactNode[]; reverse?: boolean }) {
  const reduce = useReducedMotion();
  const strip = (
    <div className="flex shrink-0">
      {items.map((node, i) => (
        <LogoCard key={i}>{brand(node)}</LogoCard>
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
      className="overflow-hidden py-[14vh]"
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
          className="mx-auto mt-5 max-w-[15ch] font-sofia text-[clamp(34px,5vw,72px)] font-medium leading-[1.04] tracking-hims text-ink"
        >
          Works with the EHR you already run.
        </motion.h2>
      </div>

      <div className="mt-14 space-y-4">
        <Row items={ROW_A} />
        <Row items={ROW_B} reverse />
      </div>

      <motion.p
        initial={{ opacity: 0, y: reduce ? 0 : 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={rise}
        className="mx-auto mt-14 max-w-md px-6 text-center text-base text-muted md:text-lg"
      >
        Built on SMART on FHIR, so Solace connects to the chart you already keep,
        no rip-and-replace.
      </motion.p>
    </section>
  );
}
