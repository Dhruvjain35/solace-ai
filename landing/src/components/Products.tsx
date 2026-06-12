import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { SHOTS } from '../lib/shots';
import { reveal, stagger, slideUp } from '../lib/motion';
import { ArrowRight } from 'lucide-react';

const PRODUCTS = [
  { name: 'Multilingual Voice Intake', body: 'Patients speak symptoms in 30+ languages — Whisper transcribes, adaptive forms branch.', shot: SHOTS.voice, kind: 'phone' as const },
  { name: 'Explainable Triage', body: 'An ESI acuity level in seconds, each score backed by a SHAP explanation.', shot: SHOTS.working, kind: 'phone' as const },
  { name: 'Clinician Pre-Brief', body: 'Matched allergies, meds and prior visits from the connected health record.', shot: SHOTS.ehr, kind: 'window' as const },
  { name: 'Plan & Discharge', body: 'A clear priority, wait time and next steps — generated in the patient’s language.', shot: SHOTS.plan, kind: 'phone' as const },
  { name: 'Vision Capture', body: 'Insurance cards and injuries photographed once, auto-filled with Claude Vision.', shot: SHOTS.insurance, kind: 'phone' as const },
];

export default function Products() {
  return (
    <section id="products" className="bg-white py-24 md:py-32">
      <div className="mx-auto max-w-[1200px] px-6">
        <motion.div {...reveal}>
          <span className="text-sm font-medium text-solace-green-600">Products</span>
          <h2 className="font-display mt-3 max-w-2xl text-4xl leading-[1.05] tracking-tight text-ink md:text-6xl">
            Co-pilots built for everyone on your floor
          </h2>
        </motion.div>

        <motion.div
          variants={stagger}
          {...reveal}
          className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3"
        >
          {PRODUCTS.map((p) => (
            <motion.div
              key={p.name}
              variants={slideUp}
              className="group flex flex-col overflow-hidden rounded-3xl border border-black/5 bg-white shadow-card transition-all duration-300 ease-standard hover:-translate-y-1.5 hover:shadow-lift"
            >
              {/* Visual header */}
              <div className="relative h-52 overflow-hidden bg-gradient-to-br from-ink to-solace-green-900">
                <div
                  className="pointer-events-none absolute left-1/2 top-1/2 h-48 w-48 -translate-x-1/2 -translate-y-1/2 rounded-blob blur-2xl"
                  style={{ background: 'radial-gradient(circle, rgba(31,191,143,0.5), rgba(31,191,143,0) 70%)' }}
                />
                {p.kind === 'phone' ? (
                  <img
                    src={p.shot}
                    alt={p.name}
                    loading="lazy"
                    className="absolute left-1/2 top-7 w-36 -translate-x-1/2 drop-shadow-2xl transition-transform duration-500 group-hover:-translate-y-1"
                  />
                ) : (
                  <img
                    src={p.shot}
                    alt={p.name}
                    loading="lazy"
                    className="absolute left-7 right-0 top-8 rounded-l-xl shadow-2xl transition-transform duration-500 group-hover:-translate-y-1"
                  />
                )}
              </div>
              <div className="flex flex-1 flex-col p-7">
                <h3 className="text-xl font-semibold text-ink">{p.name}</h3>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-muted">{p.body}</p>
                <Link
                  to="/product"
                  className="mt-6 inline-flex h-10 w-10 items-center justify-center rounded-full border border-solace-green-100 text-solace-green-700 transition group-hover:bg-solace-green-700 group-hover:text-white"
                  aria-label={`Learn ${p.name}`}
                >
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
