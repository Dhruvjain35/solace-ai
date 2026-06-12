import { useRef } from 'react';
import { motion, useScroll, useTransform } from 'framer-motion';

const CARDS = [
  {
    n: '01',
    title: 'HIPAA-compliant by design',
    body: 'Explicit consent tracking and dual-write audit logging — 90 days hot, six years cold. Built for PHI from the very first commit, not bolted on after.',
    tint: 'from-solace-green-900 to-ink',
  },
  {
    n: '02',
    title: 'Encrypted end to end',
    body: 'Every record is encrypted at rest with AWS KMS and in transit over TLS, across every service in the pipeline — phone, browser, model and EHR.',
    tint: 'from-solace-green-700 to-solace-green-900',
  },
  {
    n: '03',
    title: 'PHI redacted before any model call',
    body: 'Protected health information is stripped before it ever reaches an LLM. The model sees the clinical signal it needs — and nothing it doesn’t.',
    tint: 'from-[#0d5f4a] to-ink',
  },
  {
    n: '04',
    title: 'AWS BAA signed',
    body: 'Solace runs on AWS under a signed Business Associate Addendum, with explainable, auditable triage — every ESI score backed by a SHAP breakdown a clinician can check.',
    tint: 'from-solace-green-900 to-[#06302a]',
  },
];

function Card({ card, i }: { card: (typeof CARDS)[number]; i: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start center', 'end start'] });
  // As the next card scrolls over this one, ease it down + fade slightly.
  const scale = useTransform(scrollYProgress, [0, 1], [1, 0.92]);
  const opacity = useTransform(scrollYProgress, [0, 0.6, 1], [1, 1, 0.35]);

  return (
    <div ref={ref} className="sticky" style={{ top: `${110 + i * 18}px` }}>
      <motion.div
        style={{ scale, opacity }}
        initial={{ y: 60, opacity: 0 }}
        whileInView={{ y: 0, opacity: 1 }}
        viewport={{ once: false, amount: 0.4 }}
        transition={{ duration: 0.6, ease: [0.25, 1, 0.5, 1] }}
        className={`relative overflow-hidden rounded-[32px] bg-gradient-to-br ${card.tint} p-10 shadow-lift ring-1 ring-white/10 md:p-14`}
      >
        <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-blob bg-solace-mint/20 blur-3xl" />
        <div className="relative grid items-center gap-8 md:grid-cols-[auto_1fr]">
          <span className="font-display text-7xl text-white/30 md:text-8xl">{card.n}</span>
          <div>
            <h3 className="font-display text-3xl text-white md:text-4xl">{card.title}</h3>
            <p className="mt-4 max-w-xl text-white/70">{card.body}</p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

export default function Trust() {
  return (
    <section id="trust" className="bg-white px-6 py-24 md:py-32">
      <div className="mx-auto max-w-[1000px]">
        <div className="mx-auto max-w-2xl text-center">
          <span className="text-sm font-medium text-solace-green-600">Trust &amp; Security</span>
          <h2 className="font-display mt-3 text-4xl leading-[1.05] tracking-tight text-ink md:text-6xl">
            Built for PHI from day one
          </h2>
          <p className="mt-5 text-lg text-muted">
            An ED platform earns trust before it earns adoption. Scroll through the
            controls your compliance team will ask about.
          </p>
        </div>

        <div className="mt-16 space-y-6 pb-[20vh]">
          {CARDS.map((c, i) => (
            <Card key={c.n} card={c} i={i} />
          ))}
        </div>
      </div>
    </section>
  );
}
