import { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';
import { INTEGRATIONS, type Integration } from '../../lib/integrations';

/*
 * IntegrationMarquee, the "works with your EHR" band. Two rows of logo cards
 * drift in opposite directions on a pure-CSS keyframe loop (.marquee-strip in
 * index.css): the strip renders twice inside a w-max flex and translates
 * exactly -50%, so the loop is seamless and immune to re-render hiccups.
 * Cards pause on hover and click through to /integrations/<slug>.
 */

const ROW_A = INTEGRATIONS.slice(0, 7);
const ROW_B = INTEGRATIONS.slice(7);

function LogoCard({ item }: { item: Integration }) {
  const [failed, setFailed] = useState(false);
  return (
    <Link
      to={`/integrations/${item.slug}`}
      aria-label={`${item.name} integration guide`}
      className="group/card mx-2 flex h-[88px] w-[200px] shrink-0 items-center justify-center rounded-2xl bg-white px-6 shadow-soft ring-1 ring-black/[0.05] transition-shadow duration-300 hover:shadow-pop hover:ring-black/10"
    >
      <span className="whitespace-nowrap transition-transform duration-300 group-hover/card:scale-[1.04]">
        {failed ? (
          item.mark
        ) : (
          <img
            src={`/assets/integrations/${item.slug}.png`}
            alt={item.name}
            loading="lazy"
            onError={() => setFailed(true)}
            className="max-h-[44px] max-w-[152px] object-contain"
          />
        )}
      </span>
    </Link>
  );
}

const EDGE_MASK =
  '[mask-image:linear-gradient(to_right,transparent,black_7%,black_93%,transparent)]';

function Row({ items, reverse }: { items: Integration[]; reverse?: boolean }) {
  const reduce = useReducedMotion();
  const strip = (
    <div className="flex shrink-0 items-center">
      {items.map((item) => (
        <LogoCard key={item.slug} item={item} />
      ))}
    </div>
  );
  if (reduce) {
    return <div className={`marquee-row overflow-x-auto ${EDGE_MASK}`}>{strip}</div>;
  }
  return (
    <div className={`marquee-row overflow-hidden ${EDGE_MASK}`}>
      <div className={`marquee-strip flex w-max ${reverse ? 'marquee-strip--reverse' : ''}`}>
        {strip}
        {strip}
      </div>
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

      <motion.div
        initial={{ opacity: 0, y: reduce ? 0 : 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={rise}
        className="mx-auto mt-12 flex max-w-xl flex-col items-center gap-5 px-6 text-center md:mt-14"
      >
        <p className="text-base text-muted md:text-lg">
          Built on SMART on FHIR, so Solace connects to the chart you already
          keep, no rip-and-replace.
        </p>
        <Link
          to="/integrations"
          className="inline-flex items-center gap-2 rounded-pill border border-ink/10 bg-white px-6 py-3 text-sm font-medium text-ink shadow-soft transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
        >
          Explore every integration
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </motion.div>
    </section>
  );
}
