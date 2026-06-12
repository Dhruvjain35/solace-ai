import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { SHOTS } from '../lib/shots';
import { transitions } from '../lib/motion';
import PhoneShot from './ui/PhoneShot';

const STEPS = [
  {
    n: '01',
    phase: 'Waiting room',
    agent: 'Solace Intake',
    title: 'patients describe symptoms by voice, in 30+ languages.',
    body: 'A QR code on the wall — no app, no account. Whisper transcribes, and an adaptive form branches on every answer. Photos of injuries and insurance cards auto-fill with Claude Vision.',
    shot: SHOTS.voice,
    kind: 'phone' as const,
  },
  {
    n: '02',
    phase: 'Triage',
    agent: 'Solace Triage Engine',
    title: 'six AI calls run in parallel and return an acuity score in seconds.',
    body: 'Whisper, a Claude pre-brief, the SOAP scribe, a comfort protocol and a LightGBM ensemble all fire at once — producing an ESI level with a SHAP explanation you can trust.',
    shot: SHOTS.working,
    kind: 'phone' as const,
  },
  {
    n: '03',
    phase: 'At the bedside',
    agent: 'Solace Pre-Brief',
    title: 'the clinician walks in already informed.',
    body: 'Auto-matched allergies, medications, conditions and prior visits from the connected health record — plus a provisional ESI that refines as bedside vitals come in.',
    shot: SHOTS.ehr,
    kind: 'window' as const,
  },
  {
    n: '04',
    phase: 'Discharge & after',
    agent: 'Solace Plan + Phone',
    title: 'every patient leaves with a plan, and the phones answer themselves.',
    body: 'A clear ESI, estimated wait and next steps in the patient’s language — while an inbound voice agent handles scheduling, questions and emergency escalation, 24/7.',
    shot: SHOTS.plan,
    kind: 'phone' as const,
  },
];

export default function Journey() {
  return (
    <section id="journey" className="bg-white py-24 md:py-32">
      <div className="mx-auto max-w-[1200px] px-6">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.4 }}
          transition={transitions.slow}
          className="mx-auto max-w-3xl text-center"
        >
          <span className="text-sm font-medium text-solace-green-600">Journey</span>
          <h2 className="font-display mt-3 text-4xl leading-[1.02] tracking-tight text-ink md:text-6xl">
            Solace is with you through the whole patient journey
          </h2>
        </motion.div>

        <div className="mt-20 flex flex-col gap-24 md:gap-36">
          {STEPS.map((s, i) => {
            const flip = i % 2 === 1;
            return (
              <motion.div
                key={s.n}
                initial="hidden"
                whileInView="show"
                viewport={{ once: true, amount: 0.35 }}
                variants={{ hidden: {}, show: { transition: { staggerChildren: 0.12 } } }}
                className="grid items-center gap-10 md:grid-cols-2 md:gap-16"
              >
                {/* Visual */}
                <motion.div
                  variants={{ hidden: { opacity: 0, y: 36 }, show: { opacity: 1, y: 0, transition: transitions.slow } }}
                  className={flip ? 'md:order-2' : ''}
                >
                  {s.kind === 'phone' ? (
                    <PhoneShot src={s.shot} alt={`${s.agent} — Solace`} flip={flip} className="min-h-[520px]" />
                  ) : (
                    <div className="relative">
                      <div className="pointer-events-none absolute -inset-6 -z-10 rounded-[40px] bg-gradient-to-br from-solace-mint/30 to-solace-green-700/10 blur-3xl" />
                      <img
                        src={s.shot}
                        alt={`${s.agent} — Solace`}
                        loading="lazy"
                        className="w-full rounded-2xl shadow-lift ring-1 ring-black/5"
                      />
                    </div>
                  )}
                </motion.div>

                {/* Copy */}
                <motion.div
                  variants={{ hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: transitions.slow } }}
                  className={flip ? 'md:order-1' : ''}
                >
                  <div className="flex items-center gap-3">
                    <span className="font-display text-3xl text-solace-green-300">{s.n}</span>
                    <span className="text-xs font-medium uppercase tracking-[0.16em] text-muted">{s.phase}</span>
                  </div>
                  <h3 className="mt-4 text-2xl leading-snug text-ink md:text-[28px]">
                    <span className="font-semibold text-solace-green-700">{s.agent}</span>{' '}
                    <span className="text-ink/80">{s.title}</span>
                  </h3>
                  <p className="mt-4 max-w-md text-muted">{s.body}</p>
                  <Link
                    to="/product"
                    className="mt-6 inline-flex items-center gap-2 rounded-pill border border-solace-green-100 px-5 py-2.5 text-sm font-medium text-solace-green-700 transition hover:bg-solace-soft"
                  >
                    Learn {s.agent}
                  </Link>
                </motion.div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
