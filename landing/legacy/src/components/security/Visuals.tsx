import { motion, useReducedMotion } from 'framer-motion';
import { ArrowRight, ArrowDown, Check } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';

/*
 * Security visuals: the demonstrations that make the page's claims concrete:
 *  - PhiScrub: the exact before/after at the PHI-isolation boundary (a real
 *    chart record on the left, the coded metadata the model actually receives
 *    on the right).
 *  - PipelineFlow: Plan -> Execute -> Narrate, labelled by WHO runs each step
 *    so it is obvious the model halves never touch raw PHI.
 *  - LeakGate: the CI test that fails the build if PHI reaches a prompt.
 * On the house two-curve reveal; reduced-motion safe.
 */

const rise = (i = 0) => ({
  initial: { opacity: 0, y: 24 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, amount: 0.3 },
  transition: {
    opacity: { ...himsFade, delay: i * 0.06 },
    y: { ...himsMove, delay: i * 0.06 },
  },
});

// One labelled key/value row inside a record card.
function Field({
  k,
  v,
  tone = 'plain',
}: {
  k: string;
  v: string;
  tone?: 'plain' | 'phi' | 'removed' | 'coded';
}) {
  const vCls =
    tone === 'phi'
      ? 'text-[#B0472E] bg-[#B0472E]/[0.08] rounded px-1.5'
      : tone === 'removed'
        ? 'text-muted/60 line-through decoration-muted/40'
        : tone === 'coded'
          ? 'text-solace-green-700 bg-solace-green-500/10 rounded px-1.5'
          : 'text-ink';
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 text-[13.5px]">
      <span className="shrink-0 font-mono text-[11px] uppercase tracking-[0.08em] text-muted/70">{k}</span>
      <span className={`text-right font-medium ${vCls}`}>{v}</span>
    </div>
  );
}

export function PhiScrub() {
  const reduce = useReducedMotion();
  const m = (i: number) => (reduce ? {} : rise(i));
  return (
    <div className="grid items-stretch gap-4 lg:grid-cols-[1fr_auto_1fr]">
      {/* Left, the real chart record */}
      <motion.div {...m(0)} className="rounded-hims border border-black/5 bg-white p-6 shadow-soft">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-[#B0472E]" aria-hidden="true" />
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#B0472E]">In the chart · contains PHI</p>
        </div>
        <div className="mt-4 divide-y divide-black/5">
          <Field k="Name" v="Marcus Reyes" tone="phi" />
          <Field k="MRN" v="MR-4821-0093" tone="phi" />
          <Field k="DOB" v="1968-03-12" tone="phi" />
          <Field k="Phone" v="(512) 555-0148" tone="phi" />
          <Field k="Problem" v="Exertional chest pain" />
          <Field k="Vitals" v="HR 118 · BP 148/92" />
          <Field k="Note" v="“58M, tightness radiating to L arm…”" tone="phi" />
        </div>
      </motion.div>

      {/* Boundary */}
      <motion.div {...m(1)} className="flex items-center justify-center lg:flex-col lg:gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-ink text-white shadow-pop">
          <ArrowRight size={18} aria-hidden="true" className="lg:hidden" />
          <ArrowDown size={18} aria-hidden="true" className="hidden lg:block" />
        </span>
        <span className="ml-3 font-mono text-[10px] uppercase tracking-[0.14em] text-muted lg:ml-0 lg:[writing-mode:vertical-rl] lg:rotate-180">
          PHI isolation boundary
        </span>
      </motion.div>

      {/* Right, what the model receives */}
      <motion.div {...m(2)} className="rounded-hims border border-solace-green-500/20 bg-solace-soft/40 p-6 shadow-soft">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-solace-green-600" aria-hidden="true" />
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-solace-green-700">What the model receives · coded only</p>
        </div>
        <div className="mt-4 divide-y divide-black/5">
          <Field k="Subject" v="[slot S1]" tone="coded" />
          <Field k="MRN" v="removed" tone="removed" />
          <Field k="Age band" v="50–59" tone="coded" />
          <Field k="Phone" v="removed" tone="removed" />
          <Field k="Problem" v="I20.9 · Angina" tone="coded" />
          <Field k="Vitals" v="LOINC 8867-4 · 118" tone="coded" />
          <Field k="Note" v="removed" tone="removed" />
        </div>
      </motion.div>
    </div>
  );
}

// Each step shows the actual artifact it emits, the real payload the model or
// runtime hands to the next stage, so the flow reads as a data pipeline, not a
// decorated three-icon row. The coded/slot tokens carry the meaning.
const STEPS = [
  {
    who: 'Model',
    io: 'in: coded catalog → out: plan',
    phi: false,
    title: 'Plan',
    body: 'The model reads the coded catalog and the question, then emits a structured query plan. No PHI is in scope.',
    artifact: 'fetch(problem) where code = I20.9\nfill {S1} from vitals.HR',
  },
  {
    who: 'Your runtime',
    io: 'in: plan + chart → out: filled slots',
    phi: true,
    title: 'Execute',
    body: 'Your trusted runtime runs the plan against the real chart, fills the slots, and keeps every identifier inside your environment.',
    artifact: 'S1 = "Marcus Reyes"   // never leaves\nHR = 118              your runtime',
  },
  {
    who: 'Model',
    io: 'in: slot tokens → out: narration',
    phi: false,
    title: 'Narrate',
    body: 'The model writes the answer over slot tokens, never the raw values, so re-identification only happens in your runtime.',
    artifact: '"{S1} presents with angina,\n HR {S1.hr}, consider ECG…"',
  },
];

export function PipelineFlow() {
  const reduce = useReducedMotion();
  const m = (i: number) => (reduce ? {} : rise(i));
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {STEPS.map((s, i) => (
        <motion.div
          key={s.title}
          {...m(i)}
          className={`relative flex h-full flex-col rounded-hims p-6 ${
            s.phi
              ? 'bg-solace-green-700 text-white'
              : 'border border-black/5 bg-white text-ink shadow-soft'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className={`font-mono text-[28px] font-medium leading-none tabular-nums tracking-[-0.04em] ${s.phi ? 'text-white/40' : 'text-solace-green-300'}`}>
              {String(i + 1).padStart(2, '0')}
            </span>
            <span className={`rounded-pill px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] ${s.phi ? 'bg-white/15 text-white' : 'bg-solace-soft text-solace-green-700'}`}>
              {s.who}
            </span>
          </div>
          <p className={`mt-5 font-mono text-[10px] uppercase tracking-[0.16em] ${s.phi ? 'text-white/60' : 'text-muted'}`}>
            {s.phi ? 'PHI stays here' : 'No PHI'}
          </p>
          <h3 className={`mt-1 font-sofia text-[22px] font-medium tracking-[-0.02em] ${s.phi ? 'text-white' : 'text-ink'}`}>
            {s.title}
          </h3>
          <p className={`mt-2 text-[14px] leading-relaxed ${s.phi ? 'text-white/75' : 'text-muted'}`}>
            {s.body}
          </p>
          <pre
            aria-hidden="true"
            className={`mt-5 overflow-hidden whitespace-pre-wrap break-words rounded-tile px-3.5 py-3 font-mono text-[10.5px] leading-relaxed ${
              s.phi
                ? 'bg-black/15 text-white/70 ring-1 ring-white/10'
                : 'bg-solace-soft/60 text-solace-green-700 ring-1 ring-solace-green-300/30'
            }`}
          >
            <span className={`mb-1.5 block text-[9px] uppercase tracking-[0.12em] ${s.phi ? 'text-white/40' : 'text-muted/60'}`}>
              {s.io}
            </span>
            {s.artifact}
          </pre>
        </motion.div>
      ))}
    </div>
  );
}

export function LeakGate() {
  const reduce = useReducedMotion();
  const m = reduce ? {} : rise(0);
  return (
    <motion.div {...m} className="overflow-hidden rounded-hims bg-ink shadow-pop ring-1 ring-white/10">
      <div className="flex items-center gap-2 border-b border-white/10 px-5 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" aria-hidden="true" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" aria-hidden="true" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" aria-hidden="true" />
        <span className="ml-3 font-mono text-[11px] text-white/45">phi-isolation.test.ts</span>
      </div>
      <pre className="overflow-x-auto px-5 py-5 font-mono text-[12.5px] leading-relaxed text-white/85">
        <code>{`// CI gate: the build fails if raw PHI can reach a prompt
test('no raw PHI in any model prompt', () => {
  const prompt = buildPrompt(chart, question);

  for (const field of RAW_PHI_FIELDS) {
    // name, MRN, DOB, address, phone, free-text notes
    expect(prompt).not.toContain(chart[field]);
  }
});`}</code>
      </pre>
      <div className="flex items-center gap-2 border-t border-white/10 px-5 py-3 text-[12.5px] text-solace-mint">
        <Check size={15} strokeWidth={2.5} aria-hidden="true" />
        <span className="font-mono">PASS · 749/749 on the latest release</span>
      </div>
    </motion.div>
  );
}
