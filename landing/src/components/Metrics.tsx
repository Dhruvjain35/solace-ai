import { motion } from 'framer-motion';
import CountUp from './ui/CountUp';
import { reveal, stagger, slideUp } from '../lib/motion';

// Numbers sourced from the Solace team's own figures. [VERIFY before launch]
const STATS = [
  { value: 90, suffix: 's', label: 'Average time to an ESI acuity score', sub: 'Two-stage triage, start to finish' },
  { value: 30, suffix: '+', label: 'Languages for spoken intake', sub: 'No app, no account, no onboarding' },
  { value: 3, suffix: '×', label: 'Faster door-to-clinician handoff', sub: 'vs. manual registration & triage' },
];

export default function Metrics() {
  return (
    <section className="relative overflow-hidden bg-ink py-24 md:py-32">
      <div className="pointer-events-none absolute inset-0 -z-0">
        <div className="absolute left-1/2 top-1/2 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2 rounded-blob bg-solace-green-700/20 blur-3xl" />
        <div className="absolute right-10 top-10 h-72 w-72 rounded-blob bg-solace-mint/10 blur-3xl" />
      </div>

      <div className="relative mx-auto max-w-[1200px] px-6">
        <div className="mx-auto max-w-2xl text-center">
          <span className="inline-flex items-center gap-2 rounded-pill bg-white/10 px-3.5 py-1.5 text-xs font-medium uppercase tracking-[0.12em] text-solace-mint">
            What sets Solace apart
          </span>
          <h2 className="h-display mt-5 text-4xl text-white md:text-6xl">
            Minutes back, on every patient.
          </h2>
          <p className="mx-auto mt-5 max-w-xl text-lg text-white/60">
            Solace eliminates the dead time between a patient walking through the ED
            door and a clinician knowing exactly what they need.
          </p>
        </div>

        <motion.div
          variants={stagger}
          {...reveal}
          className="mt-16 grid gap-6 md:grid-cols-3"
        >
          {STATS.map((s) => (
            <motion.div
              key={s.label}
              variants={slideUp}
              className="rounded-3xl border border-white/10 bg-white/[0.04] p-8 backdrop-blur-sm"
            >
              <p className="h-display text-6xl text-white">
                <CountUp to={s.value} suffix={s.suffix} />
              </p>
              <p className="mt-4 font-medium text-white">{s.label}</p>
              <p className="mt-1 text-sm text-white/50">{s.sub}</p>
            </motion.div>
          ))}
        </motion.div>

        <div className="mt-12 flex justify-center">
          <a href="#demo" className="btn-primary">
            Book a Demo — see it on your floor
          </a>
        </div>
      </div>
    </section>
  );
}
