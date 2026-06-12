import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus } from 'lucide-react';
import { reveal } from '../lib/motion';

const ITEMS = [
  { q: 'Do patients need to download an app?', a: 'No. Patients scan a QR code in the waiting room and use Solace in the browser — no app, no account, no login. Intake works in 30+ languages by voice.' },
  { q: 'How does Solace assign an acuity level?', a: 'A Claude language model produces an initial assessment, then a LightGBM ensemble refines it into an ESI level. Every score ships with a SHAP explanation so clinicians can see the reasoning.' },
  { q: 'Which EHRs does Solace connect to?', a: 'Solace integrates over SMART-on-FHIR, supporting Epic, Oracle Health (Cerner), athenahealth and other FHIR R4 systems — reading back allergies, medications and prior visits.' },
  { q: 'Is Solace HIPAA compliant?', a: 'Yes. All data is encrypted at rest (KMS) and in transit (TLS), PHI is redacted before any model call, and we maintain dual-write audit logging. Solace operates under an AWS Business Associate Addendum (BAA).' },
  { q: 'How long does triage take?', a: 'Six AI calls run in parallel, returning an ESI level, plan and estimated wait in seconds — getting most ER visits started about 10 minutes sooner.' },
];

export default function FAQ() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <section className="bg-white px-6 py-24 md:py-32">
      <div className="mx-auto max-w-[820px]">
        <motion.div {...reveal} className="text-center">
          <span className="text-sm font-medium text-solace-green-600">FAQ</span>
          <h2 className="font-display mt-3 text-4xl leading-[1.05] tracking-tight text-ink md:text-6xl">
            Frequently asked questions
          </h2>
        </motion.div>

        <div className="mt-12 divide-y divide-black/8 border-y border-black/8">
          {ITEMS.map((it, i) => {
            const isOpen = open === i;
            return (
              <div key={it.q}>
                <button
                  onClick={() => setOpen(isOpen ? null : i)}
                  className="flex w-full items-center justify-between gap-6 py-6 text-left"
                >
                  <span className="text-lg text-ink">{it.q}</span>
                  <Plus
                    className={`h-5 w-5 flex-none text-solace-green-700 transition-transform duration-300 ${isOpen ? 'rotate-45' : ''}`}
                  />
                </button>
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.3, ease: [0.25, 1, 0.5, 1] }}
                      className="overflow-hidden"
                    >
                      <p className="pb-6 pr-10 text-muted">{it.a}</p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
