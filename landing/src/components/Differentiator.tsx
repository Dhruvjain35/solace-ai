import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { reveal } from '../lib/motion';

const BARS = [
  { label: 'Time to first acuity score', pct: 92, big: '~7s', sub: 'Six AI calls in parallel', from: '#1FBF8F', to: '#7CCBB2' },
  { label: 'ER visits started sooner', pct: 80, big: '10 min', sub: 'vs. manual registration & triage', from: '#0F8A68', to: '#1FBF8F' },
];

export default function Differentiator() {
  return (
    <section className="bg-white px-6 py-24 md:py-32">
      <motion.div
        {...reveal}
        className="relative mx-auto max-w-[1100px] overflow-hidden rounded-[32px] bg-ink p-10 md:p-16"
      >
        <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-blob bg-solace-green-700/30 blur-3xl" />
        <p className="relative text-sm font-medium text-solace-mint">What sets Solace apart</p>

        <div className="relative mt-10 space-y-12">
          {BARS.map((b) => (
            <div key={b.label} className="grid items-center gap-6 md:grid-cols-[1fr_auto]">
              <div>
                <p className="text-lg font-medium text-white">{b.label}</p>
                <div className="mt-4 h-2.5 w-full overflow-hidden rounded-full bg-white/10">
                  <motion.div
                    initial={{ width: 0 }}
                    whileInView={{ width: `${b.pct}%` }}
                    viewport={{ once: true, amount: 0.6 }}
                    transition={{ duration: 1.2, ease: [0.25, 1, 0.5, 1] }}
                    className="h-full rounded-full"
                    style={{ backgroundImage: `linear-gradient(90deg, ${b.from}, ${b.to})` }}
                  />
                </div>
                <p className="mt-3 text-sm text-white/50">{b.sub}</p>
              </div>
              <div className="md:w-44 md:text-right">
                <p className="font-display text-6xl text-white">{b.big}</p>
              </div>
            </div>
          ))}
        </div>

        <Link to="/demo" className="relative mt-12 inline-flex rounded-pill bg-gradient-to-br from-solace-green-700 to-solace-mint px-7 py-3.5 text-sm font-medium text-white transition hover:scale-[1.03]">
          Book a Demo — it’s on us
        </Link>
      </motion.div>
    </section>
  );
}
