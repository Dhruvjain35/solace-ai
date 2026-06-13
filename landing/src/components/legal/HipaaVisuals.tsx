import { motion, useReducedMotion } from 'framer-motion';
import { Check, ArrowRight, ArrowDown } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';

/*
 * HIPAA visuals — the two demonstrations that turn the compliance prose into
 * something you can read at a glance:
 *  - SafeguardsMatrix: the Security Rule's three safeguard categories mapped to
 *    the specific controls Solace actually ships.
 *  - TrustChain: the Business-Associate chain, covered entity -> BAA -> Solace
 *    -> AWS/Bedrock under BAA, so the obligation flow is obvious.
 * House two-curve reveal; reduced-motion safe.
 */

const reveal = (i = 0, reduce?: boolean | null) =>
  reduce
    ? {}
    : {
        initial: { opacity: 0, y: 22 },
        whileInView: { opacity: 1, y: 0 },
        viewport: { once: true, amount: 0.3 },
        transition: {
          opacity: { ...himsFade, delay: i * 0.06 },
          y: { ...himsMove, delay: i * 0.06 },
        },
      };

const COLUMNS = [
  {
    cite: '§164.308',
    label: 'Administrative',
    rows: [
      'Role-scoped admin, least-privilege defaults',
      'Tenant-isolation check on every workspace query',
      'Append-only audit log of reads, AI calls, write-backs',
      '749 tests per release; PHI / tenant / consent suites block the build',
    ],
  },
  {
    cite: '§164.312',
    label: 'Technical',
    rows: [
      'Passwordless magic-link sign-in, short-lived JWTs',
      'Customer-managed KMS encryption, in transit and at rest',
      'CloudFront + WAF edge, TLS-only, SSRF guards',
      'Confirm-gated writes — no chart change without a clinician',
    ],
  },
  {
    cite: '§164.310',
    label: 'Physical',
    rows: [
      'Inherited from HIPAA-eligible AWS under AWS’s BAA',
      'Audited data-center, facility and media controls',
      'PHI stored and processed only in covered AWS regions',
      'Solace adds the application-layer controls alongside',
    ],
  },
];

export function SafeguardsMatrix() {
  const reduce = useReducedMotion();
  return (
    <div className="not-prose grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {COLUMNS.map((col, i) => (
        <motion.div
          key={col.label}
          {...reveal(i, reduce)}
          className="flex h-full flex-col rounded-hims border border-black/5 bg-white p-6 shadow-soft"
        >
          <div className="flex items-baseline justify-between gap-3 border-b border-black/5 pb-4">
            <p className="font-sofia text-[17px] font-medium tracking-[-0.02em] text-ink">
              {col.label} <span className="text-muted">safeguards</span>
            </p>
            <span className="shrink-0 rounded-pill bg-solace-soft px-2.5 py-1 font-mono text-[11px] font-medium tabular-nums text-solace-green-700">
              {col.cite}
            </span>
          </div>
          <ul className="mt-5 space-y-2.5">
            {col.rows.map((r) => (
              <li key={r} className="flex items-start gap-2.5 text-[13.5px] leading-snug text-ink">
                <Check size={15} strokeWidth={2.4} aria-hidden="true" className="mt-0.5 shrink-0 text-solace-green-500" />
                {r}
              </li>
            ))}
          </ul>
        </motion.div>
      ))}
    </div>
  );
}

const CHAIN = [
  { tag: 'CE', label: 'Covered entity', sub: 'Hospital · ED · urgent care', tone: 'plain' as const },
  { tag: 'BAA', label: 'BAA', sub: 'Signed before any PHI', tone: 'accent' as const },
  { tag: 'BA', label: 'Solace', sub: 'Business Associate', tone: 'dark' as const },
  { tag: 'SUB', label: 'AWS · Bedrock', sub: 'Subprocessors under BAA', tone: 'plain' as const },
];

export function TrustChain() {
  const reduce = useReducedMotion();
  return (
    <div className="not-prose flex flex-col items-stretch gap-3 lg:flex-row lg:items-center">
      {CHAIN.map((node, i) => (
        <div key={node.label} className="contents">
          <motion.div
            {...reveal(i, reduce)}
            className={`flex flex-1 items-center gap-3 rounded-hims p-5 ${
              node.tone === 'dark'
                ? 'bg-ink text-white'
                : node.tone === 'accent'
                  ? 'bg-solace-green-700 text-white'
                  : 'border border-black/5 bg-white text-ink shadow-soft'
            }`}
          >
            <span
              className={`inline-flex h-10 min-w-[2.5rem] shrink-0 items-center justify-center rounded-tile px-2 font-mono text-[12px] font-semibold tracking-[0.04em] ${
                node.tone === 'plain' ? 'bg-solace-soft text-solace-green-700' : 'bg-white/15 text-white'
              }`}
            >
              {node.tag}
            </span>
            <span className="min-w-0">
              <span className={`block text-[15px] font-medium ${node.tone === 'plain' ? 'text-ink' : 'text-white'}`}>
                {node.label}
              </span>
              <span className={`block text-[12px] ${node.tone === 'plain' ? 'text-muted' : 'text-white/65'}`}>
                {node.sub}
              </span>
            </span>
          </motion.div>
          {i < CHAIN.length - 1 && (
            <span className="flex shrink-0 items-center justify-center text-muted" aria-hidden="true">
              <ArrowRight size={18} className="hidden lg:block" />
              <ArrowDown size={18} className="lg:hidden" />
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
