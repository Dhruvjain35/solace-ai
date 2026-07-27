import { motion } from 'framer-motion';
import {
  User,
  ShieldCheck,
  BookOpen,
  PenLine,
  ArrowRight,
  ArrowDown,
  Check,
  FileText,
  Stethoscope,
  Activity,
} from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';
import EhrScreen from '../product/EhrScreen';

/*
 * Real, in-DOM product visuals for the per-platform integration guide. These
 * replace the four reused static screenshots: instead of the same PNGs on every
 * platform, each guide gets vendor-specific diagrams built from the Integration
 * record: a SMART-on-FHIR connection flow, the exact scopes Solace requests,
 * a coded write-back result, and the live Atlas EhrScreen framed in a browser
 * card. Everything rides the two house curves and respects reduced motion.
 */

// House reveal, matching shared.tsx Reveal but local so a single import wires
// the whole visual set. y is zeroed under reduced motion.
function Rise({
  reduce,
  index = 0,
  className,
  children,
}: {
  reduce: boolean | null;
  index?: number;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{
        opacity: { ...himsFade, delay: index * 0.05 },
        y: { ...himsMove, delay: index * 0.05 },
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/* ============================================================= *
 * 1 · ConnectionFlow, the SMART on FHIR handshake as a stepped  *
 *     diagram. Horizontal on desktop, vertical on mobile, the   *
 *     vendor name interpolated into the authorize + write-back  *
 *     nodes. No standing access, the closing note.              *
 * ============================================================= */

type FlowNode = {
  Icon: typeof User;
  label: string;
  sub: string;
};

export function ConnectionFlow({
  vendor,
  reduce,
  tone = 'light',
}: {
  vendor: string;
  reduce: boolean | null;
  tone?: 'light' | 'dark';
}) {
  const nodes: FlowNode[] = [
    { Icon: User, label: 'Clinician', sub: 'launches Solace in context' },
    { Icon: ShieldCheck, label: `${vendor} SSO`, sub: 'authorize · no new password' },
    { Icon: BookOpen, label: 'Solace reads the chart', sub: 'minimum-necessary v2 scopes' },
    { Icon: PenLine, label: `Write-back to ${vendor}`, sub: 'confirm-gated · coded FHIR' },
  ];

  const dark = tone === 'dark';
  const cardCls = dark
    ? 'bg-white/[0.05] ring-white/10'
    : 'bg-white ring-black/[0.06] shadow-card';
  const titleCls = dark ? 'text-white' : 'text-ink';
  const subCls = dark ? 'text-white/55' : 'text-muted';
  const chipCls = dark
    ? 'bg-solace-mint/15 text-solace-mint ring-solace-mint/25'
    : 'bg-solace-soft text-solace-green-700 ring-solace-green-300/50';
  const arrowCls = dark ? 'text-white/30' : 'text-solace-green-300';
  const noteCls = dark ? 'text-white/55' : 'text-muted';

  return (
    <div>
      {/* desktop: horizontal stepped flow; mobile: vertical stack */}
      <div className="flex flex-col gap-3 md:flex-row md:items-stretch md:gap-0">
        {nodes.map((n, i) => (
          <div
            key={n.label}
            className="flex flex-col gap-3 md:flex-1 md:flex-row md:items-center md:gap-0"
          >
            <Rise reduce={reduce} index={i} className="md:flex-1">
              <div
                className={`relative flex h-full items-start gap-3.5 rounded-tile p-4 ring-1 transition-shadow duration-[400ms] ease-hims-expo md:flex-col md:items-center md:gap-3 md:p-5 md:text-center ${cardCls}`}
              >
                <span
                  aria-hidden="true"
                  className={`absolute right-3 top-3 font-mono text-[10.5px] tabular-nums ${
                    dark ? 'text-white/30' : 'text-muted/40'
                  }`}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ring-1 ${chipCls}`}
                >
                  <n.Icon size={18} strokeWidth={1.9} aria-hidden="true" />
                </span>
                <span className="min-w-0">
                  <p
                    className={`font-sofia text-[15px] font-semibold leading-tight tracking-[-0.01em] ${titleCls}`}
                  >
                    {n.label}
                  </p>
                  <p className={`mt-1 text-[12.5px] leading-snug ${subCls}`}>
                    {n.sub}
                  </p>
                </span>
              </div>
            </Rise>
            {i < nodes.length - 1 && (
              <span
                aria-hidden="true"
                className={`flex shrink-0 items-center justify-center ${arrowCls} md:w-7`}
              >
                <ArrowDown size={18} strokeWidth={2.2} className="md:hidden" />
                <ArrowRight size={18} strokeWidth={2.2} className="hidden md:block" />
              </span>
            )}
          </div>
        ))}
      </div>

      <Rise reduce={reduce} index={4}>
        <p
          className={`mt-5 flex items-center gap-2 text-[13px] ${noteCls}`}
        >
          <ShieldCheck
            size={15}
            strokeWidth={1.9}
            aria-hidden="true"
            className={dark ? 'text-solace-mint' : 'text-solace-green-600'}
          />
          No standing access, the token is scoped to the launch and expires with
          the session.
        </p>
      </Rise>
    </div>
  );
}

/* ============================================================= *
 * 2 · ScopeCard, the exact minimum-necessary SMART v2 scopes    *
 *     Solace requests, as mono chips, with the HIPAA cite.      *
 * ============================================================= */

const SCOPES = [
  'patient/Patient.rs',
  'patient/Condition.rs',
  'patient/Observation.rs',
  'patient/MedicationRequest.rs',
  'patient/AllergyIntolerance.rs',
  'patient/DocumentReference.cu',
  'user/Encounter.rs',
] as const;

export function ScopeCard({ reduce }: { reduce: boolean | null }) {
  return (
    <Rise reduce={reduce}>
      <div className="rounded-hims bg-white p-7 shadow-card ring-1 ring-black/[0.06]">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-solace-soft text-solace-green-700">
            <ShieldCheck size={18} strokeWidth={1.9} aria-hidden="true" />
          </span>
          <h3 className="font-sofia text-[18px] font-medium leading-tight tracking-[-0.01em] text-ink">
            What Solace asks for
          </h3>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {SCOPES.map((s) => (
            <code
              key={s}
              className="rounded-md bg-[#0A0F0D] px-2.5 py-1.5 font-mono text-[12px] tracking-tight text-solace-mint ring-1 ring-white/10"
            >
              {s}
            </code>
          ))}
        </div>

        <p className="mt-5 text-[13px] leading-relaxed text-muted">
          Minimum necessary, per HIPAA{' '}
          <span className="font-medium text-ink">164.502(b)</span>. Read scopes
          for the chart, one create/update scope for the note. Nothing broad,
          nothing unused.
        </p>
      </div>
    </Rise>
  );
}

/* ============================================================= *
 * 3 · WriteBackCard, a coded write-back result: each resource   *
 *     Solace posted, with its real code system and a green tick.*
 * ============================================================= */

type WriteRow = {
  Icon: typeof FileText;
  resource: string;
  code: string;
  label: string;
};

const WRITES: WriteRow[] = [
  {
    Icon: FileText,
    resource: 'DocumentReference',
    code: 'LOINC 11506-3',
    label: 'Progress note',
  },
  {
    Icon: Stethoscope,
    resource: 'Condition',
    code: 'ICD-10 I20.9',
    label: 'Angina pectoris, unspecified',
  },
  {
    Icon: Activity,
    resource: 'Observation',
    code: 'LOINC 8867-4',
    label: 'Heart rate · 118 bpm',
  },
];

export function WriteBackCard({
  vendor,
  reduce,
}: {
  vendor: string;
  reduce: boolean | null;
}) {
  return (
    <Rise reduce={reduce}>
      <div className="rounded-hims bg-white p-7 shadow-card ring-1 ring-black/[0.06]">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-solace-soft text-solace-green-700">
            <PenLine size={18} strokeWidth={1.9} aria-hidden="true" />
          </span>
          <h3 className="font-sofia text-[18px] font-medium leading-tight tracking-[-0.01em] text-ink">
            Solace wrote to {vendor}
          </h3>
        </div>

        <div className="mt-5 space-y-2.5">
          {WRITES.map((w) => (
            <div
              key={w.resource}
              className="flex items-center gap-3 rounded-tile bg-solace-soft/50 px-4 py-3 ring-1 ring-solace-green-300/30"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-solace-green-700 ring-1 ring-black/[0.05]">
                <w.Icon size={16} strokeWidth={1.9} aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-sofia text-[14px] font-semibold leading-tight text-ink">
                  {w.resource}
                  <span className="ml-2 font-mono text-[11.5px] font-normal text-solace-green-700">
                    {w.code}
                  </span>
                </p>
                <p className="mt-0.5 truncate text-[12.5px] text-muted">
                  {w.label}
                </p>
              </div>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-solace-green-700 text-white">
                <Check size={13} strokeWidth={3} aria-hidden="true" />
              </span>
            </div>
          ))}
        </div>

        <p className="mt-5 text-[13px] leading-relaxed text-muted">
          Coded, not free text. Every write is confirm-gated by the clinician and
          saved to the audit log.
        </p>
      </div>
    </Rise>
  );
}

/* ============================================================= *
 * 4 · ChartFrame, the live Atlas EhrScreen in a clean browser   *
 *     card. This is the chart Solace reads and writes; it needs *
 *     the [container-type:inline-size] wrapper + 16/10 aspect   *
 *     for the cqw units inside EhrScreen to scale.              *
 * ============================================================= */

export function ChartFrame({
  vendor,
  reduce,
}: {
  vendor: string;
  reduce: boolean | null;
}) {
  return (
    <Rise reduce={reduce}>
      <figure className="overflow-hidden rounded-hims bg-white shadow-pop ring-1 ring-black/[0.06]">
        {/* browser chrome */}
        <div className="flex items-center gap-2 border-b border-black/[0.06] bg-[#f3f4f4]/70 px-4 py-3">
          <span aria-hidden="true" className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
            <span className="h-2.5 w-2.5 rounded-full bg-black/15" />
          </span>
          <span className="ml-2 truncate rounded-md bg-white px-3 py-1 font-mono text-[11px] text-muted ring-1 ring-black/[0.05]">
            atlas.solace.health · launched from {vendor}
          </span>
        </div>
        {/* live DOM screen, cqw scales inside the container */}
        <div className="aspect-[16/10] w-full [container-type:inline-size]">
          <span className="sr-only">
            The Solace Atlas patient snapshot Solace reads from and writes back to
            {' '}
            {vendor}: triage acuity, pre-brief, AI differential, coded workup and
            the SHAP attribution bars.
          </span>
          <div aria-hidden="true" className="h-full w-full">
            <EhrScreen />
          </div>
        </div>
      </figure>
    </Rise>
  );
}
