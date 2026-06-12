import { motion } from 'framer-motion';
import { reveal } from '../lib/motion';

type Sys = { name: string; slug: string; ext?: string };
const ROW_A: Sys[] = [
  { name: 'Epic', slug: 'epic' },
  { name: 'Cerner', slug: 'cerner' },
  { name: 'athenahealth', slug: 'athenahealth' },
  { name: 'NextGen', slug: 'nextgen' },
  { name: 'eClinicalWorks', slug: 'eclinicalworks' },
  { name: 'AWS', slug: 'aws', ext: 'svg' },
];
const ROW_B: Sys[] = [
  { name: 'MEDITECH', slug: 'meditech' },
  { name: 'AdvancedMD', slug: 'advancedmd' },
  { name: 'DrChrono', slug: 'drchrono' },
  { name: 'Elation Health', slug: 'elation' },
  { name: 'Veradigm', slug: 'veradigm' },
  { name: 'Epic', slug: 'epic' },
];

function LogoCard({ sys }: { sys: Sys }) {
  return (
    <div className="flex h-24 w-60 flex-none items-center justify-center gap-3 rounded-2xl border border-black/5 bg-white px-7 shadow-card">
      <img
        src={`/assets/logos/${sys.slug}.${sys.ext ?? 'png'}`}
        alt={sys.name}
        className="h-8 w-8 flex-none object-contain"
        onError={(e) => (e.currentTarget.style.display = 'none')}
      />
      <span className="text-lg font-semibold tracking-tight text-ink/80">{sys.name}</span>
    </div>
  );
}

function Row({ items, reverse }: { items: Sys[]; reverse?: boolean }) {
  const doubled = [...items, ...items];
  return (
    <div className="flex overflow-hidden">
      <div
        className="flex shrink-0 gap-4 pr-4"
        style={{ animation: `marquee${reverse ? '-rev' : ''} 34s linear infinite` }}
      >
        {doubled.map((s, i) => (
          <LogoCard key={`${s.slug}-${i}`} sys={s} />
        ))}
      </div>
    </div>
  );
}

export default function Integrations() {
  return (
    <section className="overflow-hidden bg-offwhite py-24 md:py-32">
      <style>{`
        @keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        @keyframes marquee-rev { from { transform: translateX(-50%); } to { transform: translateX(0); } }
        @media (prefers-reduced-motion: reduce) { [style*="marquee"] { animation: none !important; } }
      `}</style>

      <div className="mx-auto max-w-2xl px-6 text-center">
        <span className="text-sm font-medium text-solace-green-600">Integration</span>
        <motion.h2
          {...reveal}
          className="font-display mt-3 text-4xl leading-[1.05] tracking-tight text-ink md:text-6xl"
        >
          Solace connects to the systems you already run on
        </motion.h2>
      </div>

      <div className="relative mt-14 space-y-4">
        <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-32 bg-gradient-to-r from-offwhite to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-32 bg-gradient-to-l from-offwhite to-transparent" />
        <Row items={ROW_A} />
        <Row items={ROW_B} reverse />
      </div>

      <p className="mx-auto mt-12 max-w-xl px-6 text-center text-muted">
        SMART-on-FHIR OAuth into your EHR — encrypted end to end, with read-back of
        allergies, medications and prior visits.
      </p>
    </section>
  );
}
