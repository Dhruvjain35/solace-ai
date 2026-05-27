import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  Activity,
  Coins,
  Users2,
  AlertCircle,
  Loader2,
  Search,
  CheckCircle2,
  Database,
  ShieldAlert,
  ClipboardList,
  Scale,
} from "lucide-react";
import { evidenceAnswer, sepsisEws, deteriorationIndex, hccEvaluate, handoffIpass, handoffSbar, resultLoopOverdue } from "../lib/api";
import {
  ehrVendorStatus,
  ehrWriteBack,
  ehrPatientMatch,
  workupSafetyCheck,
  detailedDischargePlan,
  earlyWarningBiasAudit,
  sepsisBundleBiasAudit,
  type EhrVendorStatus,
  type EhrWriteBackResult,
  type PatientMatchResult,
  type WorkupSafetyResult,
  type DetailedDischargeResult,
  type BiasAuditResult,
} from "../lib/api-tools";

type Tab =
  | "evidence"
  | "ews"
  | "hcc"
  | "handoff"
  | "loops"
  | "ehr"
  | "safety"
  | "discharge"
  | "bias";

// ---------------------------------------------------------------------------------
// Shared building blocks — keep every pane visually consistent with the design tokens.

function Panel({ title, children, className = "" }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-surface-lowest rounded-lg shadow-card p-4 ${className}`}>
      {title && (
        <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-2.5">
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

const inputClass =
  "w-full h-9 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-2 focus:ring-primary text-sm text-ink outline-none transition-all";
const textareaClass =
  "w-full px-3 py-2 rounded-md bg-surface-low ring-1 ring-line focus:ring-2 focus:ring-primary text-sm text-ink outline-none transition-all";

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
      {children}
    </span>
  );
}

function ActionButton({
  onClick,
  busy,
  variant = "primary",
  icon: Icon,
  children,
  className = "",
}: {
  onClick: () => void;
  busy?: boolean;
  variant?: "primary" | "dark";
  icon?: typeof Search;
  children: React.ReactNode;
  className?: string;
}) {
  const tone =
    variant === "dark"
      ? "bg-primary-container text-white hover:brightness-110"
      : "bg-primary bg-primary-gradient text-white hover:brightness-110";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`inline-flex items-center justify-center gap-1.5 h-9 px-4 rounded-md text-sm font-semibold transition-all shadow-soft hover:shadow-card disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 ${tone} ${className}`}
    >
      {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden /> : Icon && <Icon className="w-3.5 h-3.5" aria-hidden />}
      {children}
    </button>
  );
}

// Severity band → token-backed surface + accent. Used by EWS, DI, sepsis bundle.
function bandClasses(band: string): string {
  if (band === "critical") return "bg-error-container ring-1 ring-error/30";
  if (band === "high") return "bg-warning-container ring-1 ring-warning/30";
  return "bg-surface-low ring-1 ring-line";
}

// Generic severity word → band. Tolerant of "absolute"/"major"/"minor" wording.
function severityBand(severity: string): string {
  const s = (severity || "").toLowerCase();
  if (["critical", "absolute", "contraindicated", "severe", "high"].includes(s)) return "critical";
  if (["major", "moderate", "relative", "caution", "warning"].includes(s)) return "high";
  return "low";
}

// Small uppercase status pill keyed to a band.
function StatusPill({ band, children }: { band: string; children: React.ReactNode }) {
  const tone =
    band === "critical"
      ? "bg-error-container text-error"
      : band === "high"
        ? "bg-warning-container text-warning"
        : "bg-surface-low text-text-muted";
  return (
    <span className={`text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ${tone}`}>
      {children}
    </span>
  );
}

// Pretty-prints whichever of a small set of keys a loosely-typed object carries.
function pickText(obj: Record<string, unknown>, keys: string[]): string {
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return "";
}

export default function ClinicianTools() {
  const { hospitalId = "demo" } = useParams();
  const [tab, setTab] = useState<Tab>("evidence");

  return (
    <div className="min-h-screen bg-surface text-ink">
      <header className="bg-surface-lowest shadow-soft">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to={`/${hospitalId}/clinician`}
            aria-label="Back to dashboard"
            className="w-9 h-9 rounded-md flex items-center justify-center text-text-muted hover:text-ink hover:bg-surface-low transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
              Solace clinical decision support
            </div>
            <div className="text-base font-bold tracking-tight">
              Evidence, early warning, HCC, handoff, loop closure
            </div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {[
            { key: "evidence", label: "Evidence", icon: BookOpen },
            { key: "ews", label: "Early warning", icon: Activity },
            { key: "hcc", label: "HCC capture", icon: Coins },
            { key: "handoff", label: "Handoff", icon: Users2 },
            { key: "loops", label: "Open loops", icon: AlertCircle },
            { key: "ehr", label: "EHR write-back", icon: Database },
            { key: "safety", label: "Workup safety", icon: ShieldAlert },
            { key: "discharge", label: "Detailed discharge", icon: ClipboardList },
            { key: "bias", label: "Bias audit", icon: Scale },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key as Tab)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors ${
                tab === key
                  ? "border-primary text-primary font-semibold"
                  : "border-transparent text-text-muted hover:text-ink"
              }`}
            >
              <Icon className="w-4 h-4" aria-hidden />
              {label}
            </button>
          ))}
        </div>
      </header>

      <div className="max-w-5xl mx-auto p-4">
        {tab === "evidence" && <EvidencePane hospitalId={hospitalId} />}
        {tab === "ews" && <EwsPane hospitalId={hospitalId} />}
        {tab === "hcc" && <HccPane hospitalId={hospitalId} />}
        {tab === "handoff" && <HandoffPane hospitalId={hospitalId} />}
        {tab === "loops" && <LoopsPane hospitalId={hospitalId} />}
        {tab === "ehr" && <EhrPane hospitalId={hospitalId} />}
        {tab === "safety" && <SafetyPane hospitalId={hospitalId} />}
        {tab === "discharge" && <DischargePane hospitalId={hospitalId} />}
        {tab === "bias" && <BiasPane hospitalId={hospitalId} />}
      </div>
    </div>
  );
}

function EvidencePane({ hospitalId }: { hospitalId: string }) {
  const [q, setQ] = useState("Best initial workup for chest pain in adults?");
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setOut(await evidenceAnswer(hospitalId, q));
    } catch {
      setErr("Could not retrieve evidence. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel>
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Clinical question</FieldLabel>
          <div className="flex gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
              className={inputClass}
            />
            <ActionButton onClick={run} busy={busy} icon={Search} className="shrink-0">
              Ask
            </ActionButton>
          </div>
        </label>
      </Panel>
      {err && <div className="rounded-md bg-error-container text-error text-sm px-3 py-2.5">{err}</div>}
      {out && (
        <>
          <Panel title="Synthesis">
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{out.answer}</div>
            {out.key_recommendations?.length > 0 && (
              <div className="mt-3 pt-3 border-t border-line">
                <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1.5">
                  Key recommendations
                </div>
                <ul className="space-y-1">
                  {out.key_recommendations.map((r: string, i: number) => (
                    <li key={i} className="text-sm text-ink flex gap-2">
                      <span className="text-primary font-mono shrink-0">{i + 1}.</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {out.uncertainty && (
              <div className="mt-3 rounded-md bg-warning-container text-warning text-xs px-3 py-2">
                Uncertainty: {out.uncertainty}
              </div>
            )}
          </Panel>
          <Panel title="Evidence snippets">
            <div className="divide-y divide-line">
              {out.snippets.map((s: any) => (
                <div key={s.index} className="py-2.5 first:pt-0 last:pb-0">
                  <div className="font-semibold text-sm text-ink">
                    <span className="text-primary font-mono">[{s.index}]</span> {s.title}
                  </div>
                  <div className="text-xs text-text-muted mt-0.5">
                    {s.source} · {s.year} · score {s.score}
                  </div>
                  <div className="text-sm mt-1 text-ink leading-relaxed">{s.body}</div>
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-primary hover:underline mt-1 inline-block"
                  >
                    {s.url}
                  </a>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

function EwsPane({ hospitalId }: { hospitalId: string }) {
  const [v, setV] = useState({ hr: 124, rr: 26, temp_c: 39.2, sbp: 92, mental_status: "confused", spo2: 92, on_oxygen: true, wbc: 18, lactate: 3.2, suspected_infection: true });
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [d] = useState({
    vitals_now: { hr: 130, rr: 26, sbp: 88, spo2: 91, temp_c: 39.2 },
    vitals_4h_ago: { hr: 105, rr: 18, sbp: 118, spo2: 96, temp_c: 38.0 },
    new_oxygen_requirement: true,
    gcs_drop_at_least_2: false,
    new_arrhythmia: false,
  });
  const [dout, setDout] = useState<any | null>(null);
  const [dbusy, setDbusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setOut(await sepsisEws(hospitalId, v));
    } finally {
      setBusy(false);
    }
  };
  const runD = async () => {
    setDbusy(true);
    try {
      setDout(await deteriorationIndex(hospitalId, d));
    } finally {
      setDbusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel title="Sepsis EWS inputs">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 text-sm">
          {(["hr", "rr", "temp_c", "sbp", "spo2", "wbc", "lactate"] as const).map((k) => (
            <label key={k} className="flex flex-col gap-1">
              <FieldLabel>{k}</FieldLabel>
              <input
                type="number"
                value={(v as any)[k] ?? ""}
                onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })}
                className={inputClass}
              />
            </label>
          ))}
          <label className="flex flex-col gap-1">
            <FieldLabel>mental_status</FieldLabel>
            <input
              value={v.mental_status}
              onChange={(e) => setV({ ...v, mental_status: e.target.value })}
              className={inputClass}
            />
          </label>
          <label className="flex items-center gap-2 mt-5">
            <input
              type="checkbox"
              checked={v.on_oxygen}
              onChange={(e) => setV({ ...v, on_oxygen: e.target.checked })}
              className="accent-primary"
            />
            <FieldLabel>on_oxygen</FieldLabel>
          </label>
          <label className="flex items-center gap-2 mt-5">
            <input
              type="checkbox"
              checked={v.suspected_infection}
              onChange={(e) => setV({ ...v, suspected_infection: e.target.checked })}
              className="accent-primary"
            />
            <FieldLabel>suspected_infection</FieldLabel>
          </label>
        </div>
        <ActionButton onClick={run} busy={busy} icon={Activity} className="mt-3">
          Run sepsis EWS
        </ActionButton>
      </Panel>
      {out && (
        <div className={`rounded-lg p-4 ${bandClasses(out.band)}`}>
          <div className="flex items-baseline gap-2">
            <span className="text-xl font-bold tracking-tight text-ink">EWS {out.score}</span>
            <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
              {out.band}
            </span>
          </div>
          <div className="text-sm mt-1 text-ink">{out.action}</div>
          <div className="mt-3 space-y-0.5 text-xs text-text-muted">
            {out.contributions.map((c: any, i: number) => (
              <div key={i}>
                <span className="font-mono text-ink">+{c.points}</span> {c.feature}: {c.why}
              </div>
            ))}
          </div>
          <div className="text-xs italic mt-2 text-text-muted">{out.calibration_note}</div>
        </div>
      )}

      <Panel title="Deterioration index — 4h trend">
        <pre className="text-xs bg-surface-low rounded-md p-2.5 overflow-auto text-ink">
          {JSON.stringify(d, null, 2)}
        </pre>
        <ActionButton onClick={runD} busy={dbusy} icon={Activity} className="mt-2.5">
          Run deterioration index
        </ActionButton>
        {dout && (
          <div className={`mt-3 rounded-md p-3 ${bandClasses(dout.band)}`}>
            <div className="flex items-baseline gap-2">
              <span className="font-bold text-ink">DI {dout.score}</span>
              <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
                {dout.band}
              </span>
            </div>
            <div className="text-sm text-ink">{dout.action}</div>
            <div className="text-xs mt-2 space-y-0.5 text-text-muted">
              {dout.contributions.map((c: any, i: number) => (
                <div key={i}>
                  <span className="font-mono text-ink">+{c.points}</span> {c.feature}: {c.why}
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

function HccPane({ hospitalId }: { hospitalId: string }) {
  const [conds, setConds] = useState(JSON.stringify([
    { icd10: "E11.65", display: "T2DM with hyperglycemia", last_documented_year: 2024 },
    { icd10: "I50.32", display: "Chronic diastolic HF", last_documented_year: 2025 },
    { icd10: "N18.4", display: "CKD stage 3b", last_documented_year: 2023 },
  ], null, 2));
  const [notes, setNotes] = useState("Patient with longstanding tobacco use, persistent dyspnea on exertion. Notes indicate intermittent atrial fibrillation. Per old records, type 2 diabetes with peripheral neuropathy.");
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await hccEvaluate(hospitalId, { conditions: JSON.parse(conds), prior_notes: [notes] }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Active problem list (JSON)</FieldLabel>
          <textarea value={conds} onChange={(e) => setConds(e.target.value)} rows={6} className={`${textareaClass} font-mono text-xs`} />
        </label>
        <label className="flex flex-col gap-1.5 mt-2.5">
          <FieldLabel>Prior notes (free text)</FieldLabel>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={`${textareaClass} text-xs`} />
        </label>
        <ActionButton onClick={run} busy={busy} icon={Coins} className="mt-3">
          Evaluate HCCs
        </ActionButton>
      </Panel>
      {out && (
        <Panel>
          <div className="flex items-baseline gap-2 mb-3">
            <span className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
              RAF total
            </span>
            <span className="text-xl font-bold tracking-tight text-ink">{out.raf_total}</span>
          </div>
          <div className="space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1.5">
                Documented HCCs ({out.documented_hccs.length})
              </div>
              <div className="divide-y divide-line">
                {out.documented_hccs.map((h: any, i: number) => (
                  <div key={i} className="text-sm py-1.5 first:pt-0 text-ink">
                    {h.hcc_code} · {h.description} · RAF {h.raf} · last {h.last_documented_year}
                    {h.needs_recapture && (
                      <span className="ml-2 text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-warning-container text-warning">
                        needs recapture
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            {out.suspected_undocumented?.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1.5">
                  Suspected undocumented (from prior notes)
                </div>
                <div className="divide-y divide-line">
                  {out.suspected_undocumented.map((s: any, i: number) => (
                    <div key={i} className="text-sm py-1.5 first:pt-0 text-ink">
                      <span className="font-semibold">{s.icd10}</span> · {s.display}
                      <div className="text-xs italic text-text-muted mt-0.5">"{s.evidence_quote}"</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1.5">
                MEAT checklist for documentation
              </div>
              <ul className="space-y-0.5">
                {out.meat_checklist.map((m: string, i: number) => (
                  <li key={i} className="text-xs text-ink flex gap-2">
                    <span className="text-primary font-mono shrink-0">{i + 1}.</span>
                    <span>{m}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}

function HandoffPane({ hospitalId }: { hospitalId: string }) {
  const [chart, setChart] = useState(JSON.stringify({
    hospital_day: 3, age: 67, sex: "M",
    principal_dx: "Sepsis from urinary source",
    comorbidities: ["DM2", "CKD3b", "Afib on apixaban"],
    vitals_today: { hr: 102, sbp: 108, temp_c: 38.4, spo2: 95 },
    pending_results: ["repeat lactate at 02:00", "blood culture day 2"],
    abx: "ceftriaxone day 2 of 5",
  }, null, 2));
  const [iout, setIout] = useState<any | null>(null);
  const [sout, setSout] = useState<any | null>(null);
  const [ibusy, setIbusy] = useState(false);
  const [sbusy, setSbusy] = useState(false);
  const [specialty, setSpecialty] = useState("nephrology");
  const [reason, setReason] = useState("AKI on CKD3b unresponsive to fluids");

  const runI = async () => {
    setIbusy(true);
    try {
      setIout(await handoffIpass(hospitalId, JSON.parse(chart)));
    } finally {
      setIbusy(false);
    }
  };
  const runS = async () => {
    setSbusy(true);
    try {
      setSout(await handoffSbar(hospitalId, JSON.parse(chart), specialty, reason));
    } finally {
      setSbusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel>
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Chart context (JSON)</FieldLabel>
          <textarea value={chart} onChange={(e) => setChart(e.target.value)} rows={8} className={`${textareaClass} font-mono text-xs`} />
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <ActionButton onClick={runI} busy={ibusy} icon={Users2}>
            Generate I-PASS
          </ActionButton>
          <input
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
            className={`${inputClass} w-40`}
            placeholder="consult specialty"
            aria-label="Consult specialty"
          />
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={`${inputClass} flex-1 min-w-[12rem]`}
            placeholder="reason for consult"
            aria-label="Reason for consult"
          />
          <ActionButton onClick={runS} busy={sbusy} variant="dark" icon={Users2}>
            Generate SBAR
          </ActionButton>
        </div>
      </Panel>
      {iout && iout.available && (
        <Panel title="I-PASS sign-out">
          <pre className="whitespace-pre-wrap font-serif text-sm text-ink leading-relaxed">
            {iout.rendered_text}
          </pre>
        </Panel>
      )}
      {sout && sout.available && (
        <Panel title="SBAR consult">
          <pre className="whitespace-pre-wrap font-serif text-sm text-ink leading-relaxed">
            {sout.rendered_text}
          </pre>
        </Panel>
      )}
    </div>
  );
}

function LoopsPane({ hospitalId }: { hospitalId: string }) {
  const [items, setItems] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try {
      setItems(await resultLoopOverdue(hospitalId));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    refresh();
  }, [hospitalId]);
  return (
    <div className="space-y-3">
      <Panel>
        <div className="flex items-center justify-between gap-3">
          <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
            Overdue abnormal results — closed-loop worklist
          </div>
          <ActionButton onClick={refresh} busy={busy} variant="dark" className="h-8 px-3">
            Refresh
          </ActionButton>
        </div>
        {items === null && (
          <div className="flex items-center gap-2 text-sm text-text-muted mt-4">
            <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
            Loading worklist…
          </div>
        )}
        {items && items.length === 0 && (
          <div className="flex items-center gap-2 text-sm text-success mt-4">
            <CheckCircle2 className="w-4 h-4 shrink-0" aria-hidden />
            No overdue loops. Every abnormal result has been acted on.
          </div>
        )}
        {items && items.length > 0 && (
          <div className="mt-3 space-y-2">
            {items.map((it) => (
              <div
                key={it.tracking_id}
                className="rounded-md bg-warning-container ring-1 ring-warning/30 p-3 text-sm"
              >
                <div className="flex justify-between gap-3">
                  <div className="font-semibold text-ink">
                    {it.test_name}: {it.value}
                  </div>
                  <div className="text-[10px] uppercase tracking-wider font-semibold text-warning shrink-0">
                    {it.severity} · {it.days_overdue}d overdue
                  </div>
                </div>
                <div className="text-xs text-text-muted mt-0.5">
                  patient {it.patient_id} · clinician {it.clinician_id} · opened {it.opened_at}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------
// EHR write-back — vendor status, dry-run write-back tester, patient matching.

function EhrPane({ hospitalId }: { hospitalId: string }) {
  const [status, setStatus] = useState<EhrVendorStatus | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);

  const [resourceJson, setResourceJson] = useState(JSON.stringify({
    resourceType: "Condition",
    code: { coding: [{ system: "http://hl7.org/fhir/sid/icd-10-cm", code: "E11.65", display: "T2DM with hyperglycemia" }] },
    clinicalStatus: { coding: [{ code: "active" }] },
  }, null, 2));
  const [writeOut, setWriteOut] = useState<EhrWriteBackResult | null>(null);
  const [writeBusy, setWriteBusy] = useState(false);
  const [writeErr, setWriteErr] = useState<string | null>(null);

  const [query, setQuery] = useState({ given: "Maria", family: "Gonzalez", birth_date: "1971-03-14", gender: "female", phone: "", mrn: "" });
  const [candidatesJson, setCandidatesJson] = useState(JSON.stringify([
    { resourceType: "Patient", id: "pat-1", name: [{ given: ["Maria"], family: "Gonzalez" }], birthDate: "1971-03-14", gender: "female" },
    { resourceType: "Patient", id: "pat-2", name: [{ given: ["Maria"], family: "Gonzales" }], birthDate: "1971-03-15", gender: "female" },
  ], null, 2));
  const [matchOut, setMatchOut] = useState<PatientMatchResult | null>(null);
  const [matchBusy, setMatchBusy] = useState(false);
  const [matchErr, setMatchErr] = useState<string | null>(null);

  const loadStatus = async () => {
    setStatusBusy(true);
    try {
      setStatus(await ehrVendorStatus(hospitalId));
    } catch {
      setStatus(null);
    } finally {
      setStatusBusy(false);
    }
  };
  useEffect(() => {
    loadStatus();
  }, [hospitalId]);

  const runWrite = async (dryRun: boolean) => {
    setWriteBusy(true);
    setWriteErr(null);
    setWriteOut(null);
    try {
      const resource = JSON.parse(resourceJson);
      setWriteOut(await ehrWriteBack(hospitalId, resource, dryRun));
    } catch {
      setWriteErr("Could not submit the write-back. Check that the resource is valid FHIR JSON.");
    } finally {
      setWriteBusy(false);
    }
  };

  const runMatch = async () => {
    setMatchBusy(true);
    setMatchErr(null);
    setMatchOut(null);
    try {
      const q = Object.fromEntries(Object.entries(query).filter(([, v]) => v));
      const candidates = JSON.parse(candidatesJson);
      setMatchOut(await ehrPatientMatch(hospitalId, q, candidates));
    } catch {
      setMatchErr("Could not run patient matching. Check the candidate list is valid JSON.");
    } finally {
      setMatchBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel title="Vendor connection">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-text-muted">
            Live status of the configured EHR adapter.
          </div>
          <ActionButton onClick={loadStatus} busy={statusBusy} variant="dark" className="h-8 px-3">
            Refresh
          </ActionButton>
        </div>
        {status && (
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-2.5">
            {([
              ["vendor", status.vendor],
              ["backend", status.backend],
              ["adapter", status.adapter_available ? "available" : "missing"],
              ["online", status.online ? "online" : "offline"],
              ["configured", status.configured ? "yes" : "no"],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} className="rounded-md bg-surface-low ring-1 ring-line px-3 py-2">
                <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">{k}</div>
                <div className="text-sm font-semibold text-ink mt-0.5">{v}</div>
              </div>
            ))}
          </div>
        )}
        {status && (
          <div className="mt-2.5 flex items-center gap-2 text-sm">
            {status.online ? (
              <span className="flex items-center gap-1.5 text-success">
                <CheckCircle2 className="w-4 h-4 shrink-0" aria-hidden />
                Adapter reachable — write-backs route to {status.vendor}.
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-warning">
                <AlertCircle className="w-4 h-4 shrink-0" aria-hidden />
                Adapter offline — use dry-run to preview routing.
              </span>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Write-back tester">
        <label className="flex flex-col gap-1.5">
          <FieldLabel>FHIR resource (JSON)</FieldLabel>
          <textarea
            value={resourceJson}
            onChange={(e) => setResourceJson(e.target.value)}
            rows={9}
            className={`${textareaClass} font-mono text-xs`}
            aria-label="FHIR resource JSON"
          />
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton onClick={() => runWrite(true)} busy={writeBusy} variant="dark" icon={Database}>
            Preview (dry-run)
          </ActionButton>
          <ActionButton onClick={() => runWrite(false)} busy={writeBusy} icon={Database}>
            Commit write-back
          </ActionButton>
        </div>
        {writeErr && <div className="mt-3 rounded-md bg-error-container text-error text-sm px-3 py-2.5">{writeErr}</div>}
        {writeOut && (
          <div className="mt-3 rounded-md bg-surface-low ring-1 ring-line p-3">
            <div className="flex items-center gap-2 mb-2">
              <StatusPill band={writeOut.ok ? "low" : "critical"}>
                {writeOut.dry_run ? "dry-run" : writeOut.ok ? "committed" : "failed"}
              </StatusPill>
              <span className="text-sm text-ink">
                {writeOut.dry_run
                  ? `${writeOut.resource_type} routed to ${writeOut.routed_to}`
                  : `${writeOut.stored ?? "stored"} as ${writeOut.id ?? "—"} via ${writeOut.vendor ?? "vendor"}`}
              </span>
            </div>
            {writeOut.url && (
              <a href={writeOut.url} target="_blank" rel="noreferrer" className="text-xs text-primary hover:underline">
                {writeOut.url}
              </a>
            )}
            <pre className="text-xs bg-surface-lowest rounded-md p-2.5 mt-2 overflow-auto text-ink">
              {JSON.stringify(writeOut, null, 2)}
            </pre>
          </div>
        )}
      </Panel>

      <Panel title="Patient matching">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          {(["given", "family", "birth_date", "gender", "phone", "mrn"] as const).map((k) => (
            <label key={k} className="flex flex-col gap-1">
              <FieldLabel>{k}</FieldLabel>
              <input
                value={query[k]}
                onChange={(e) => setQuery({ ...query, [k]: e.target.value })}
                className={inputClass}
                aria-label={`Match query ${k}`}
              />
            </label>
          ))}
        </div>
        <label className="flex flex-col gap-1.5 mt-2.5">
          <FieldLabel>Candidate FHIR Patients (JSON array)</FieldLabel>
          <textarea
            value={candidatesJson}
            onChange={(e) => setCandidatesJson(e.target.value)}
            rows={7}
            className={`${textareaClass} font-mono text-xs`}
            aria-label="Candidate patients JSON"
          />
        </label>
        <ActionButton onClick={runMatch} busy={matchBusy} icon={Search} className="mt-3">
          Run patient match
        </ActionButton>
        {matchErr && <div className="mt-3 rounded-md bg-error-container text-error text-sm px-3 py-2.5">{matchErr}</div>}
        {matchOut && (
          <div
            className={`mt-3 rounded-md p-3 ${
              matchOut.status === "matched"
                ? "bg-surface-low ring-1 ring-line"
                : matchOut.status === "needs_review"
                  ? "bg-warning-container ring-1 ring-warning/30"
                  : "bg-error-container ring-1 ring-error/30"
            }`}
          >
            <div className="flex items-baseline gap-2">
              <StatusPill band={matchOut.status === "matched" ? "low" : matchOut.status === "needs_review" ? "high" : "critical"}>
                {matchOut.status.replace("_", " ")}
              </StatusPill>
              <span className="text-sm font-semibold text-ink">
                confidence {Math.round(matchOut.confidence * 100)}%
              </span>
            </div>
            <div className="text-sm text-ink mt-1">{matchOut.reason}</div>
            {matchOut.patient && (
              <pre className="text-xs bg-surface-lowest rounded-md p-2.5 mt-2 overflow-auto text-ink">
                {JSON.stringify(matchOut.patient, null, 2)}
              </pre>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------
// Workup safety — order set with contraindications surfaced by severity.

function SafetyPane({ hospitalId }: { hospitalId: string }) {
  const [transcript, setTranscript] = useState(
    "62-year-old with crushing substernal chest pain radiating to the left arm, diaphoretic. History of CKD stage 4 and prior contrast allergy. On metformin."
  );
  const [esiLevel, setEsiLevel] = useState(2);
  const [out, setOut] = useState<WorkupSafetyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setOut(null);
    try {
      setOut(await workupSafetyCheck(hospitalId, { transcript, esi_level: esiLevel }));
    } catch {
      setErr("Could not run the safety check. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel title="Workup inputs">
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Encounter transcript</FieldLabel>
          <textarea
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            rows={5}
            className={`${textareaClass} text-sm`}
            aria-label="Encounter transcript"
          />
        </label>
        <label className="flex flex-col gap-1 mt-2.5 max-w-[8rem]">
          <FieldLabel>ESI level</FieldLabel>
          <input
            type="number"
            min={1}
            max={5}
            value={esiLevel}
            onChange={(e) => setEsiLevel(Number(e.target.value))}
            className={inputClass}
            aria-label="ESI level"
          />
        </label>
        <ActionButton onClick={run} busy={busy} icon={ShieldAlert} className="mt-3">
          Run safety check
        </ActionButton>
      </Panel>
      {err && <div className="rounded-md bg-error-container text-error text-sm px-3 py-2.5">{err}</div>}
      {out && (
        <>
          <div
            className={`rounded-lg p-4 ${
              out.has_critical_contraindication
                ? "bg-error-container ring-1 ring-error/30"
                : "bg-surface-low ring-1 ring-line"
            }`}
          >
            <div className="flex items-center gap-2">
              {out.has_critical_contraindication ? (
                <AlertCircle className="w-5 h-5 text-error shrink-0" aria-hidden />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-success shrink-0" aria-hidden />
              )}
              <span className="text-sm font-semibold text-ink">
                {out.has_critical_contraindication
                  ? "Critical contraindication present — review before ordering."
                  : "No critical contraindications detected."}
              </span>
            </div>
          </div>
          <Panel title={`Contraindications (${out.contraindications.length})`}>
            {out.contraindications.length === 0 ? (
              <div className="text-sm text-text-muted">The proposed order set has no flagged conflicts.</div>
            ) : (
              <div className="space-y-2">
                {out.contraindications.map((c, i) => {
                  const band = severityBand(c.severity);
                  return (
                    <div key={i} className={`rounded-md p-3 ${bandClasses(band)}`}>
                      <div className="flex justify-between gap-3">
                        <div className="font-semibold text-sm text-ink">{c.order}</div>
                        <StatusPill band={band}>{c.severity}</StatusPill>
                      </div>
                      <div className="text-xs text-text-muted mt-0.5">{c.section}</div>
                      <div className="text-sm text-ink mt-1">{c.reason}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>
          <Panel title="Full order set">
            <pre className="text-xs bg-surface-low rounded-md p-2.5 overflow-auto text-ink">
              {JSON.stringify(out, null, 2)}
            </pre>
          </Panel>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------
// Detailed discharge — full plan with tiered return precautions.

function DischargePane({ hospitalId }: { hospitalId: string }) {
  const [form, setForm] = useState({
    condition: "Community-acquired pneumonia",
    clinician_note: "CAP, mild. CURB-65 of 1. Tolerating oral intake, SpO2 96% on room air.",
    scribe_note: "Patient counseled on antibiotic course and return precautions.",
    transcript: "Patient reports productive cough for 4 days, low-grade fever, no chest pain at rest.",
    assessment: "Stable for outpatient management with oral amoxicillin-clavulanate.",
    patient_language: "en",
    hospital_name: "Solace General",
    follow_up: "Primary care in 3-5 days; sooner if symptoms worsen.",
  });
  const [out, setOut] = useState<DetailedDischargeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setOut(null);
    try {
      setOut(await detailedDischargePlan(hospitalId, form));
    } catch {
      setErr("Could not build the discharge plan. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  const tieredBand = (tier: string): string => {
    const t = (tier || "").toLowerCase();
    if (["emergency", "critical", "911", "immediate"].some((w) => t.includes(w))) return "critical";
    if (["urgent", "soon", "same-day", "same day"].some((w) => t.includes(w))) return "high";
    return "low";
  };

  return (
    <div className="space-y-3">
      <Panel title="Discharge inputs">
        {(["condition", "hospital_name", "patient_language", "follow_up"] as const).map((k) => (
          <label key={k} className="flex flex-col gap-1.5 mb-2.5">
            <FieldLabel>{k.replace(/_/g, " ")}</FieldLabel>
            <input
              value={form[k]}
              onChange={(e) => setForm({ ...form, [k]: e.target.value })}
              className={inputClass}
              aria-label={k.replace(/_/g, " ")}
            />
          </label>
        ))}
        {(["assessment", "clinician_note", "scribe_note", "transcript"] as const).map((k) => (
          <label key={k} className="flex flex-col gap-1.5 mb-2.5">
            <FieldLabel>{k.replace(/_/g, " ")}</FieldLabel>
            <textarea
              value={form[k]}
              onChange={(e) => setForm({ ...form, [k]: e.target.value })}
              rows={3}
              className={`${textareaClass} text-sm`}
              aria-label={k.replace(/_/g, " ")}
            />
          </label>
        ))}
        <ActionButton onClick={run} busy={busy} icon={ClipboardList}>
          Build discharge plan
        </ActionButton>
      </Panel>
      {err && <div className="rounded-md bg-error-container text-error text-sm px-3 py-2.5">{err}</div>}
      {out && (
        <>
          <Panel title={`Plan sections (${out.sections.length})`}>
            <div className="divide-y divide-line">
              {out.sections.map((s, i) => (
                <div key={i} className="py-2.5 first:pt-0 last:pb-0">
                  <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1">
                    {pickText(s, ["title", "name"]) || `Section ${i + 1}`}
                  </div>
                  <div className="whitespace-pre-wrap text-sm text-ink leading-relaxed">
                    {pickText(s, ["body", "text"]) || JSON.stringify(s)}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title={`Tiered return precautions (${out.tiered_precautions.length})`}>
            <div className="space-y-2">
              {out.tiered_precautions.map((p, i) => {
                const tier = pickText(p, ["tier", "level"]) || `tier ${i + 1}`;
                const band = tieredBand(tier);
                return (
                  <div key={i} className={`rounded-md p-3 ${bandClasses(band)}`}>
                    <div className="flex items-center gap-2 mb-1">
                      <StatusPill band={band}>{tier}</StatusPill>
                      {pickText(p, ["label"]) && (
                        <span className="text-sm font-semibold text-ink">{pickText(p, ["label"])}</span>
                      )}
                    </div>
                    <div className="text-sm text-ink">
                      {pickText(p, ["instruction", "text"]) || JSON.stringify(p)}
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------
// Bias audit — fairness check across strata for EWS and sepsis bundle cohorts.

function BiasPane({ hospitalId }: { hospitalId: string }) {
  const [cohortJson, setCohortJson] = useState(JSON.stringify([
    { age: 71, sex: "female", race: "Black", hr: 118, rr: 24, sbp: 96, temp_c: 38.9, lactate: 3.1, suspected_infection: true },
    { age: 58, sex: "male", race: "White", hr: 92, rr: 18, sbp: 122, temp_c: 37.6, lactate: 1.4, suspected_infection: false },
    { age: 66, sex: "female", race: "Hispanic", hr: 130, rr: 28, sbp: 88, temp_c: 39.4, lactate: 4.0, suspected_infection: true },
    { age: 49, sex: "male", race: "Asian", hr: 104, rr: 20, sbp: 110, temp_c: 38.1, lactate: 2.0, suspected_infection: true },
  ], null, 2));
  const [encountersJson, setEncountersJson] = useState(JSON.stringify([
    { encounter_id: "e1", race: "Black", sex: "female", bundle_completed: false, antibiotics_within_1h: false, lactate_drawn: true },
    { encounter_id: "e2", race: "White", sex: "male", bundle_completed: true, antibiotics_within_1h: true, lactate_drawn: true },
    { encounter_id: "e3", race: "Hispanic", sex: "female", bundle_completed: false, antibiotics_within_1h: false, lactate_drawn: false },
    { encounter_id: "e4", race: "White", sex: "female", bundle_completed: true, antibiotics_within_1h: true, lactate_drawn: true },
  ], null, 2));
  const [strata, setStrata] = useState("race, sex");
  const [threshold, setThreshold] = useState(0.15);

  const [ewsOut, setEwsOut] = useState<BiasAuditResult | null>(null);
  const [ewsBusy, setEwsBusy] = useState(false);
  const [ewsErr, setEwsErr] = useState<string | null>(null);

  const [bundleOut, setBundleOut] = useState<BiasAuditResult | null>(null);
  const [bundleBusy, setBundleBusy] = useState(false);
  const [bundleErr, setBundleErr] = useState<string | null>(null);

  const strataList = () => strata.split(",").map((s) => s.trim()).filter(Boolean);

  const runEws = async () => {
    setEwsBusy(true);
    setEwsErr(null);
    setEwsOut(null);
    try {
      setEwsOut(
        await earlyWarningBiasAudit(hospitalId, {
          cohort: JSON.parse(cohortJson),
          strata: strataList(),
          score_fn: "sepsis_ews",
          disparity_threshold: threshold,
        })
      );
    } catch {
      setEwsErr("Could not run the early-warning audit. Check the cohort is valid JSON.");
    } finally {
      setEwsBusy(false);
    }
  };

  const runBundle = async () => {
    setBundleBusy(true);
    setBundleErr(null);
    setBundleOut(null);
    try {
      setBundleOut(
        await sepsisBundleBiasAudit(hospitalId, {
          encounters: JSON.parse(encountersJson),
          strata: strataList(),
          disparity_threshold: threshold,
        })
      );
    } catch {
      setBundleErr("Could not run the sepsis-bundle audit. Check the encounters are valid JSON.");
    } finally {
      setBundleBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel title="Audit settings">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>strata (comma-separated)</FieldLabel>
            <input value={strata} onChange={(e) => setStrata(e.target.value)} className={inputClass} aria-label="Strata" />
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>disparity threshold</FieldLabel>
            <input
              type="number"
              step={0.05}
              min={0}
              max={1}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className={inputClass}
              aria-label="Disparity threshold"
            />
          </label>
        </div>
      </Panel>

      <Panel title="Early-warning bias audit">
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Cohort (JSON array)</FieldLabel>
          <textarea
            value={cohortJson}
            onChange={(e) => setCohortJson(e.target.value)}
            rows={8}
            className={`${textareaClass} font-mono text-xs`}
            aria-label="Cohort JSON"
          />
        </label>
        <ActionButton onClick={runEws} busy={ewsBusy} icon={Scale} className="mt-3">
          Audit EWS cohort
        </ActionButton>
        {ewsErr && <div className="mt-3 rounded-md bg-error-container text-error text-sm px-3 py-2.5">{ewsErr}</div>}
        {ewsOut && <BiasResult result={ewsOut} />}
      </Panel>

      <Panel title="Sepsis bundle bias audit">
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Encounters (JSON array)</FieldLabel>
          <textarea
            value={encountersJson}
            onChange={(e) => setEncountersJson(e.target.value)}
            rows={8}
            className={`${textareaClass} font-mono text-xs`}
            aria-label="Encounters JSON"
          />
        </label>
        <ActionButton onClick={runBundle} busy={bundleBusy} variant="dark" icon={Scale} className="mt-3">
          Audit sepsis bundle
        </ActionButton>
        {bundleErr && <div className="mt-3 rounded-md bg-error-container text-error text-sm px-3 py-2.5">{bundleErr}</div>}
        {bundleOut && <BiasResult result={bundleOut} />}
      </Panel>
    </div>
  );
}

function BiasResult({ result }: { result: BiasAuditResult }) {
  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-text-muted">{result.count} records</span>
        <span className="text-text-muted">·</span>
        <span className="text-text-muted">{result.strata.length} strata</span>
        {result.flags.length === 0 ? (
          <span className="flex items-center gap-1.5 text-success">
            <CheckCircle2 className="w-4 h-4 shrink-0" aria-hidden />
            No subgroups exceed the disparity threshold.
          </span>
        ) : (
          <StatusPill band="high">{result.flags.length} flagged</StatusPill>
        )}
      </div>
      {result.flags.length > 0 && (
        <div className="space-y-2">
          {result.flags.map((f, i) => (
            <div key={i} className="rounded-md bg-warning-container ring-1 ring-warning/30 p-3">
              <div className="flex justify-between gap-3">
                <div className="font-semibold text-sm text-ink">
                  {pickText(f, ["stratum", "group"]) || `Flag ${i + 1}`}
                </div>
                {typeof f.disparity === "number" && (
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-warning shrink-0">
                    disparity {f.disparity.toFixed(2)}
                  </span>
                )}
              </div>
              {pickText(f, ["metric"]) && (
                <div className="text-xs text-text-muted mt-0.5">metric: {pickText(f, ["metric"])}</div>
              )}
              {pickText(f, ["reason"]) && <div className="text-sm text-ink mt-1">{pickText(f, ["reason"])}</div>}
            </div>
          ))}
        </div>
      )}
      {Array.isArray(result.errors) && result.errors.length > 0 && (
        <div className="rounded-md bg-error-container text-error text-xs px-3 py-2">
          {result.errors.length} record(s) could not be scored and were skipped.
        </div>
      )}
      <details className="text-xs">
        <summary className="cursor-pointer text-text-muted">Provenance & raw output</summary>
        <pre className="text-xs bg-surface-low rounded-md p-2.5 mt-1.5 overflow-auto text-ink">
          {JSON.stringify({ strata: result.strata, provenance: result.provenance }, null, 2)}
        </pre>
      </details>
    </div>
  );
}
