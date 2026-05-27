import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft, Users, Network, Hospital, FileText, Phone, MessageCircle, Loader2, Send, Database,
  Check, X as XIcon, CheckCircle2, HeartHandshake, ClipboardList, CalendarClock, FlaskConical,
  AlertTriangle, ArrowRight,
} from "lucide-react";
import {
  cohortQuery, sepsisBundleEvaluate, encounterStitch, encounterHuddle,
  nurseTriageProtocols, nurseTriageEvaluate, tefcaQuery, telehealthSession,
  hl7MdmRender, portalThreads, portalThread, portalRespond, portalInbound,
} from "../lib/api";
import {
  sdohScreen, sdohReferralsBatch, careGapsSidebar, noShowEquityAudit,
  noShowReminderPlan, resultsDetectAbnormal, resultsReview, resultClosureOpen,
  resultClosureAdvance, resultClosureSummary,
} from "../lib/api-ops";
import type {
  SdohScreenResult, SdohReferral, CareGapSidebar, NoShowEquityAudit,
  ReminderPlan, AbnormalResult, ResultReviewDraft, ResultClosure, ClosureSummary,
} from "../lib/api-ops";

type Tab =
  | "portal" | "cohort" | "sepsis" | "longitudinal" | "triage" | "tefca" | "telehealth" | "hl7"
  | "sdoh" | "caregaps" | "noshow" | "resultloop";

// ---------------------------------------------------------------------------------
// Shared building blocks — token-backed, consistent across every ops pane.

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
  icon?: typeof Send;
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

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="text-xs bg-surface-low rounded-md p-2.5 overflow-auto text-ink">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function ClinicianOps() {
  const { hospitalId = "demo" } = useParams();
  const [tab, setTab] = useState<Tab>("portal");
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
              Solace operations
            </div>
            <div className="text-base font-bold tracking-tight">
              Portal · cohort · sepsis · triage · SDoH · care gaps · no-show · result loop
            </div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {[
            { key: "portal", label: "Portal messages", icon: MessageCircle },
            { key: "cohort", label: "Cohort builder", icon: Database },
            { key: "sepsis", label: "Sepsis bundle", icon: Hospital },
            { key: "longitudinal", label: "Longitudinal", icon: Network },
            { key: "triage", label: "Nurse triage", icon: Phone },
            { key: "tefca", label: "TEFCA / QHIN", icon: Network },
            { key: "telehealth", label: "Telehealth", icon: Phone },
            { key: "hl7", label: "HL7 v2 MDM", icon: FileText },
            { key: "sdoh", label: "SDoH", icon: HeartHandshake },
            { key: "caregaps", label: "Care gaps", icon: ClipboardList },
            { key: "noshow", label: "No-show", icon: CalendarClock },
            { key: "resultloop", label: "Result loop-closure", icon: FlaskConical },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key as Tab)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px whitespace-nowrap transition-colors ${
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
        {tab === "portal" && <PortalPane hospitalId={hospitalId} />}
        {tab === "cohort" && <CohortPane hospitalId={hospitalId} />}
        {tab === "sepsis" && <SepsisPane hospitalId={hospitalId} />}
        {tab === "longitudinal" && <LongitudinalPane hospitalId={hospitalId} />}
        {tab === "triage" && <NurseTriagePane hospitalId={hospitalId} />}
        {tab === "tefca" && <TefcaPane hospitalId={hospitalId} />}
        {tab === "telehealth" && <TelehealthPane hospitalId={hospitalId} />}
        {tab === "hl7" && <Hl7Pane hospitalId={hospitalId} />}
        {tab === "sdoh" && <SdohPane hospitalId={hospitalId} />}
        {tab === "caregaps" && <CareGapsPane hospitalId={hospitalId} />}
        {tab === "noshow" && <NoShowPane hospitalId={hospitalId} />}
        {tab === "resultloop" && <ResultLoopPane hospitalId={hospitalId} />}
      </div>
    </div>
  );
}

function PortalPane({ hospitalId }: { hospitalId: string }) {
  const [threads, setThreads] = useState<any[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [seedPatient, setSeedPatient] = useState("p001");
  const [seedBody, setSeedBody] = useState("Hi - I need a refill of my metformin please.");

  const refresh = async () => setThreads(await portalThreads(hospitalId));
  useEffect(() => {
    refresh();
  }, [hospitalId]);
  useEffect(() => {
    if (active) portalThread(hospitalId, active).then(setMessages);
  }, [active, hospitalId]);

  const seed = async () => {
    setBusy(true);
    try {
      await portalInbound(hospitalId, seedPatient, seedBody);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    const last = messages.find((m) => m.direction === "inbound");
    if (!last || !reply.trim()) return;
    await portalRespond(hospitalId, last.id, reply, "edited");
    setReply("");
    if (active) setMessages(await portalThread(hospitalId, active));
  };

  return (
    <div className="space-y-3">
      <Panel className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <input
          value={seedPatient}
          onChange={(e) => setSeedPatient(e.target.value)}
          className={inputClass}
          placeholder="patient_id"
          aria-label="Patient ID"
        />
        <input
          value={seedBody}
          onChange={(e) => setSeedBody(e.target.value)}
          className={inputClass}
          placeholder="message body"
          aria-label="Message body"
        />
        <ActionButton onClick={seed} busy={busy} icon={MessageCircle}>
          Simulate inbound
        </ActionButton>
      </Panel>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Panel title="Threads" className="md:col-span-1">
          {threads.length === 0 && (
            <div className="text-sm text-text-muted">No threads yet — simulate one above.</div>
          )}
          <div className="space-y-1">
            {threads.map((t) => (
              <button
                key={t.thread_key}
                onClick={() => setActive(t.thread_key)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                  active === t.thread_key
                    ? "bg-primary-fixed text-primary"
                    : "text-text-muted hover:bg-surface-low"
                }`}
              >
                <div className="font-semibold text-ink">{t.patient_id}</div>
                <div className="text-xs text-text-muted">
                  {t.message_count} msgs · {t.unread_count} unread
                </div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Messages" className="md:col-span-2">
          {!active && <div className="text-sm text-text-muted">Pick a thread.</div>}
          <div className="space-y-2">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`p-2.5 rounded-md text-sm ${
                  m.direction === "inbound" ? "bg-surface-low" : "bg-primary-fixed"
                }`}
              >
                <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-0.5">
                  {m.direction === "inbound"
                    ? `Patient · ${(m.tags || []).join(", ")} · routed: ${m.routing}`
                    : `Reply · ${m.sender_name}`}
                </div>
                <div className="text-ink">{m.body}</div>
                {m.ai_draft && m.direction === "inbound" && (
                  <div className="mt-2 p-2 rounded-md bg-warning-container ring-1 ring-warning/30 text-xs">
                    <div className="font-semibold text-warning mb-1 uppercase tracking-wider text-[10px]">
                      AI draft (review before send)
                    </div>
                    <div className="text-ink">{m.ai_draft}</div>
                  </div>
                )}
              </div>
            ))}
          </div>
          {active && (
            <div className="mt-3 flex gap-2">
              <input
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                className={inputClass}
                placeholder="Type or edit AI draft..."
                aria-label="Reply message"
              />
              <ActionButton onClick={send} icon={Send} className="shrink-0">
                Send
              </ActionButton>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function CohortPane({ hospitalId }: { hospitalId: string }) {
  const [icd, setIcd] = useState("E11.65");
  const [loinc, setLoinc] = useState("4548-4");
  const [thresh, setThresh] = useState(8.0);
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await cohortQuery(hospitalId, { condition_icd10: icd || null, lab_loinc_above: loinc ? [loinc, thresh] : null }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>Condition ICD-10</FieldLabel>
            <input value={icd} onChange={(e) => setIcd(e.target.value)} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>Lab LOINC</FieldLabel>
            <input value={loinc} onChange={(e) => setLoinc(e.target.value)} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>Above threshold</FieldLabel>
            <input type="number" value={thresh} onChange={(e) => setThresh(Number(e.target.value))} className={inputClass} />
          </label>
        </div>
        <ActionButton onClick={run} busy={busy} icon={Database} className="mt-3">
          Build cohort
        </ActionButton>
      </Panel>
      {out && (
        <Panel>
          <div className="flex items-baseline gap-2 mb-2">
            <span className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
              Matched
            </span>
            <span className="text-xl font-bold tracking-tight text-ink">{out.count}</span>
          </div>
          <JsonBlock value={out.patients} />
        </Panel>
      )}
    </div>
  );
}

function SepsisPane({ hospitalId }: { hospitalId: string }) {
  const t0 = new Date().toISOString();
  const [body, setBody] = useState({
    sepsis_recognition_iso: t0,
    lactate_drawn_iso: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    initial_lactate_value: 4.1,
    blood_cultures_drawn_iso: new Date(Date.now() + 25 * 60 * 1000).toISOString(),
    antibiotics_given_iso: new Date(Date.now() + 35 * 60 * 1000).toISOString(),
    fluids_started_iso: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    fluids_dose_ml_per_kg: 30,
    persistent_hypotension_after_fluids: false,
  });
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await sepsisBundleEvaluate(hospitalId, body));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <label className="flex flex-col gap-1.5">
          <FieldLabel>1-hour bundle inputs (JSON)</FieldLabel>
          <textarea
            value={JSON.stringify(body, null, 2)}
            onChange={(e) => {
              try {
                setBody(JSON.parse(e.target.value));
              } catch {
                /* keep last valid */
              }
            }}
            rows={12}
            className={`${textareaClass} font-mono text-xs`}
          />
        </label>
        <ActionButton onClick={run} busy={busy} icon={Hospital} className="mt-3">
          Evaluate 1-hour bundle
        </ActionButton>
      </Panel>
      {out && (
        <div
          className={`rounded-lg p-4 ${
            out.all_complete
              ? "bg-success-container ring-1 ring-success/30"
              : "bg-warning-container ring-1 ring-warning/30"
          }`}
        >
          <div className="flex items-baseline gap-2">
            <span className="text-xl font-bold tracking-tight text-ink">
              {Math.round((out.compliance_rate || 0) * 100)}%
            </span>
            <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
              compliance
            </span>
          </div>
          <div className="text-xs mt-1 text-text-muted">Deadline: {out.deadline_iso}</div>
          <div className="mt-3 divide-y divide-line">
            {(out.elements || []).map((e: any, i: number) => (
              <div key={i} className="flex justify-between items-center gap-3 py-1.5 text-sm">
                <span className="flex items-center gap-2 text-ink">
                  {e.completed ? (
                    <Check className="w-4 h-4 text-success shrink-0" aria-hidden />
                  ) : (
                    <XIcon className="w-4 h-4 text-error shrink-0" aria-hidden />
                  )}
                  <span className={e.completed ? "" : "text-error"}>
                    {e.name}
                    {e.required === false ? " (not required)" : ""}
                  </span>
                </span>
                <span className="text-xs text-text-muted shrink-0">
                  {e.minutes != null ? `${e.minutes} min` : "—"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function LongitudinalPane({ hospitalId }: { hospitalId: string }) {
  const [notesText, setNotesText] = useState(JSON.stringify([
    { visit_index: "v1", date: "2025-09-04", chief_complaint: "knee pain", note_text: "60yo F with R knee pain x 6mo, OA changes on imaging, started naproxen + PT." },
    { visit_index: "v2", date: "2026-01-12", chief_complaint: "knee pain follow-up", note_text: "Persistent R knee pain despite NSAIDs and PT, intra-articular cortisone given." },
    { visit_index: "v3", date: "2026-04-22", chief_complaint: "knee pain", note_text: "Pain returned 2mo after injection, now interfering with sleep. Discussing referral for arthroplasty." },
  ], null, 2));
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await encounterStitch(hospitalId, JSON.parse(notesText)));
    } finally {
      setBusy(false);
    }
  };
  const [huddle, setHuddle] = useState("Attending: Bed 4 - Mr Garcia is trending up clinically, lactate down to 1.8 from 3.4. RN: he's on 2L still. Pharmacy: vanco trough was 14, target. Resident: plan to step down to floor today. Attending: agree, sign out the floor team to recheck CXR tomorrow.");
  const [hout, setHout] = useState<any | null>(null);
  const [hbusy, setHbusy] = useState(false);
  const runH = async () => {
    setHbusy(true);
    try {
      setHout(await encounterHuddle(hospitalId, huddle));
    } finally {
      setHbusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel title="Multi-encounter stitching">
        <textarea value={notesText} onChange={(e) => setNotesText(e.target.value)} rows={8} className={`${textareaClass} font-mono text-xs`} />
        <ActionButton onClick={run} busy={busy} icon={Users} className="mt-3">
          Stitch
        </ActionButton>
      </Panel>
      {out && out.available && (
        <Panel title="Stitched summary" className="text-sm space-y-2.5">
          <div className="text-ink leading-relaxed">
            <span className="font-semibold">Narrative:</span> {out.narrative_summary}
          </div>
          <div>
            <FieldLabel>Active problems</FieldLabel>
            <JsonBlock value={out.active_problems} />
          </div>
          <div>
            <FieldLabel>Interventions tried</FieldLabel>
            <JsonBlock value={out.interventions_tried} />
          </div>
        </Panel>
      )}
      <Panel title="Huddle / rounds parser">
        <textarea value={huddle} onChange={(e) => setHuddle(e.target.value)} rows={4} className={`${textareaClass} text-xs`} />
        <ActionButton onClick={runH} busy={hbusy} variant="dark" icon={Users} className="mt-3">
          Parse huddle
        </ActionButton>
      </Panel>
      {hout && hout.available && (
        <Panel title="Parsed huddle">
          <JsonBlock value={hout} />
        </Panel>
      )}
    </div>
  );
}

function NurseTriagePane({ hospitalId }: { hospitalId: string }) {
  const [protocols, setProtocols] = useState<string[]>([]);
  const [active, setActive] = useState<string>("chest_pain");
  const [answers, setAnswers] = useState<string>(JSON.stringify({ severe_or_crushing: false, with_dyspnea: true, age_over_50: true }, null, 2));
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    nurseTriageProtocols(hospitalId).then(setProtocols).catch(() => {});
  }, [hospitalId]);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await nurseTriageEvaluate(hospitalId, active, JSON.parse(answers)));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>Protocol</FieldLabel>
            <select value={active} onChange={(e) => setActive(e.target.value)} className={inputClass}>
              {protocols.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end">
            <ActionButton onClick={run} busy={busy} icon={Phone}>
              Evaluate
            </ActionButton>
          </div>
        </div>
        <label className="flex flex-col gap-1 mt-2.5">
          <FieldLabel>Answers (JSON)</FieldLabel>
          <textarea value={answers} onChange={(e) => setAnswers(e.target.value)} rows={6} className={`${textareaClass} font-mono text-xs`} />
        </label>
      </Panel>
      {out && (
        <div
          className={`rounded-lg p-4 ${
            out.disposition === "911"
              ? "bg-error-container ring-1 ring-error/30"
              : out.disposition === "ed_now"
              ? "bg-warning-container ring-1 ring-warning/30"
              : "bg-surface-low ring-1 ring-line"
          }`}
        >
          <div className="flex items-baseline gap-2">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
              Disposition
            </span>
            <span className="text-lg font-bold tracking-tight text-ink">{out.disposition}</span>
          </div>
          <div className="text-sm mt-1 text-ink">{out.reason}</div>
          {out.sla && <div className="text-xs text-text-muted mt-1">SLA: {out.sla}</div>}
          {out.instructions && <div className="text-xs italic mt-2 text-text-muted">{out.instructions}</div>}
        </div>
      )}
    </div>
  );
}

function TefcaPane({ hospitalId }: { hospitalId: string }) {
  const [name, setName] = useState("Jane Doe");
  const [dob, setDob] = useState("1985-03-21");
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await tefcaQuery(hospitalId, name, dob));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>Patient name</FieldLabel>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>Date of birth</FieldLabel>
            <input value={dob} onChange={(e) => setDob(e.target.value)} placeholder="YYYY-MM-DD" className={inputClass} />
          </label>
          <div className="flex items-end">
            <ActionButton onClick={run} busy={busy} icon={Network}>
              Query QHIN
            </ActionButton>
          </div>
        </div>
      </Panel>
      {out && (
        <Panel title="QHIN response">
          <JsonBlock value={out} />
        </Panel>
      )}
    </div>
  );
}

function TelehealthPane({ hospitalId }: { hospitalId: string }) {
  const [provider, setProvider] = useState<"doxy" | "zoom" | "teams" | "doximity">("doxy");
  const [extra, setExtra] = useState<string>('{ "clinician_handle": "drchen" }');
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await telehealthSession(hospitalId, { provider, ...JSON.parse(extra || "{}") }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>Provider</FieldLabel>
            <select value={provider} onChange={(e) => setProvider(e.target.value as any)} className={inputClass}>
              <option value="doxy">Doxy.me</option>
              <option value="zoom">Zoom</option>
              <option value="teams">Microsoft Teams</option>
              <option value="doximity">Doximity Dialer</option>
            </select>
          </label>
          <div className="flex items-end">
            <ActionButton onClick={run} busy={busy} icon={Phone}>
              Make session
            </ActionButton>
          </div>
        </div>
        <label className="flex flex-col gap-1 mt-2.5">
          <FieldLabel>Provider parameters (JSON)</FieldLabel>
          <textarea
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            rows={3}
            className={`${textareaClass} font-mono text-xs`}
            placeholder='{"clinician_handle":"drchen"} or {"pmi":"1234567890"} etc.'
          />
        </label>
      </Panel>
      {out && (
        <Panel title="Session" className="text-sm">
          <div className="text-ink">
            Provider: <span className="font-semibold">{out.provider}</span>
          </div>
          {out.url && (
            <div className="mt-1 text-ink">
              Link:{" "}
              <a href={out.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                {out.url}
              </a>
            </div>
          )}
          {out.patient_message && (
            <div className="mt-1 text-xs italic text-text-muted">{out.patient_message}</div>
          )}
        </Panel>
      )}
    </div>
  );
}

function Hl7Pane({ hospitalId }: { hospitalId: string }) {
  const [body, setBody] = useState({
    note_text: "Pt 67yo M presented with progressive dyspnea x 3 days, baseline COPD, on albuterol PRN, started prednisone today.",
    mrn: "MRN12345", family_name: "DOE", given_name: "JANE", dob: "19850321", sex: "F",
    npi: "1234567890", provider_family: "SMITH", provider_given: "ALEX",
    receiving_app: "MEDITECH", receiving_facility: "COMMUNITY_HOSPITAL", encounter_id: "ENC-9981",
    note_type_code: "PROG", note_type_display: "Progress note", visit_class: "O",
  });
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await hl7MdmRender(hospitalId, body));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <label className="flex flex-col gap-1.5">
          <FieldLabel>MDM^T02 inputs (JSON)</FieldLabel>
          <textarea
            value={JSON.stringify(body, null, 2)}
            onChange={(e) => {
              try {
                setBody(JSON.parse(e.target.value));
              } catch {
                /* keep last valid */
              }
            }}
            rows={10}
            className={`${textareaClass} font-mono text-xs`}
          />
        </label>
        <ActionButton onClick={run} busy={busy} icon={FileText} className="mt-3">
          Render MDM^T02
        </ActionButton>
      </Panel>
      {out && (
        <Panel title="HL7 v2 message (pipe-delimited, CR-separated)">
          <pre className="bg-primary-container text-white text-xs rounded-md p-3 overflow-auto whitespace-pre-wrap">
            {out.hl7_message}
          </pre>
          <div className="flex items-center gap-1.5 text-xs text-text-muted mt-2">
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" aria-hidden />
            Send via MLLP TCP to your Mirth/Rhapsody listener — port 6661 by default.
          </div>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------
// Shared severity / risk tone helper — token-backed container colors.

function toneFor(level?: string): string {
  const l = (level || "").toLowerCase();
  if (l === "high" || l === "critical" || l === "urgent")
    return "bg-error-container ring-1 ring-error/30";
  if (l === "moderate" || l === "medium")
    return "bg-warning-container ring-1 ring-warning/30";
  return "bg-success-container ring-1 ring-success/30";
}

function Pill({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "warn" | "error" | "ok" }) {
  const map = {
    muted: "bg-surface-low text-text-muted ring-line",
    warn: "bg-warning-container text-warning ring-warning/30",
    error: "bg-error-container text-error ring-error/30",
    ok: "bg-success-container text-success ring-success/30",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ring-1 ${map[tone]}`}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------------
// SDoH — PRAPARE social-determinants screener → risk + Z-codes + consent-gated referrals.

function SdohPane({ hospitalId }: { hospitalId: string }) {
  const [answers, setAnswers] = useState<string>(JSON.stringify({
    housing_situation: "worried_about_losing",
    food_insecurity: true,
    transportation_barrier: true,
    utilities_at_risk: false,
    unsafe_relationship: false,
    employment: "unemployed",
    income_strain: "very_hard",
  }, null, 2));
  const [patientRef, setPatientRef] = useState("p001");
  const [consent, setConsent] = useState(false);
  const [screen, setScreen] = useState<SdohScreenResult | null>(null);
  const [referrals, setReferrals] = useState<SdohReferral[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [refBusy, setRefBusy] = useState(false);

  const runScreen = async () => {
    setBusy(true);
    setReferrals(null);
    try {
      setScreen(await sdohScreen(hospitalId, JSON.parse(answers), "prapare"));
    } catch {
      /* keep last result */
    } finally {
      setBusy(false);
    }
  };

  const makeReferrals = async () => {
    if (!screen) return;
    setRefBusy(true);
    try {
      const res = await sdohReferralsBatch(hospitalId, {
        screen_result: screen,
        patient_ref: patientRef,
        consent,
        network: "findhelp",
      });
      setReferrals(res.referrals);
    } finally {
      setRefBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel title="PRAPARE screener">
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Screener answers (JSON)</FieldLabel>
          <textarea
            value={answers}
            onChange={(e) => setAnswers(e.target.value)}
            rows={9}
            className={`${textareaClass} font-mono text-xs`}
            aria-label="PRAPARE screener answers JSON"
          />
        </label>
        <ActionButton onClick={runScreen} busy={busy} icon={HeartHandshake} className="mt-3">
          Score screener
        </ActionButton>
      </Panel>

      {screen && (
        <div className={`rounded-lg p-4 ${toneFor(screen.risk_level)}`}>
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-xl font-bold tracking-tight text-ink capitalize">
              {screen.risk_level} risk
            </span>
            <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
              {screen.risk_count} positive {screen.risk_count === 1 ? "domain" : "domains"} · {screen.instrument}
            </span>
            {screen.urgent && <Pill tone="error">Urgent need</Pill>}
          </div>
          {screen.positive_domains.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2.5">
              {screen.positive_domains.map((d) => (
                <Pill key={d} tone="warn">{d}</Pill>
              ))}
            </div>
          )}
          {screen.icd10_z_codes.length > 0 && (
            <div className="mt-3">
              <FieldLabel>ICD-10 Z-codes</FieldLabel>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {screen.icd10_z_codes.map((z) => (
                  <span key={z} className="px-2 py-0.5 rounded-md bg-surface-low ring-1 ring-line text-xs font-mono text-ink">
                    {z}
                  </span>
                ))}
              </div>
            </div>
          )}
          {screen.recommended_referrals.length > 0 && (
            <div className="mt-3">
              <FieldLabel>Recommended referrals</FieldLabel>
              <ul className="mt-1 text-sm text-ink list-disc list-inside space-y-0.5">
                {screen.recommended_referrals.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {screen && (
        <Panel title="Place referrals (findhelp network)">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <label className="flex flex-col gap-1">
              <FieldLabel>Patient ref</FieldLabel>
              <input
                value={patientRef}
                onChange={(e) => setPatientRef(e.target.value)}
                className={inputClass}
              />
            </label>
            <label className="flex items-center gap-2 self-end h-9">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="w-4 h-4 rounded ring-1 ring-line accent-primary focus-visible:ring-2 focus-visible:ring-primary"
              />
              <span className="text-sm text-ink">Patient consent on file</span>
            </label>
          </div>
          {!consent && (
            <div className="flex items-center gap-1.5 text-xs text-warning mt-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" aria-hidden />
              Without consent, referrals return blocked — capture consent before sharing PHI with community partners.
            </div>
          )}
          <ActionButton onClick={makeReferrals} busy={refBusy} variant="dark" icon={Send} className="mt-3">
            Create referrals
          </ActionButton>
          {referrals && (
            <div className="mt-3 divide-y divide-line">
              {referrals.length === 0 && (
                <div className="text-sm text-text-muted">No referrals generated.</div>
              )}
              {referrals.map((r) => {
                const blocked = (r.status || "").startsWith("blocked");
                return (
                  <div key={r.referral_id} className="flex justify-between items-center gap-3 py-2 text-sm">
                    <span className="text-ink">
                      {r.domain || "referral"}
                      {r.organization ? ` · ${r.organization}` : ""}
                    </span>
                    <Pill tone={blocked ? "error" : "ok"}>{r.status}</Pill>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------
// Care gaps — per-patient HEDIS sidebar.

function CareGapsPane({ hospitalId }: { hospitalId: string }) {
  const [patientId, setPatientId] = useState("p001");
  const [limit, setLimit] = useState(2);
  const [out, setOut] = useState<CareGapSidebar | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await careGapsSidebar(hospitalId, patientId, limit));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <Panel>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>Patient ID</FieldLabel>
            <input value={patientId} onChange={(e) => setPatientId(e.target.value)} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>Shown limit</FieldLabel>
            <input
              type="number"
              min={1}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className={inputClass}
            />
          </label>
          <div className="flex items-end">
            <ActionButton onClick={run} busy={busy} icon={ClipboardList}>
              Load sidebar
            </ActionButton>
          </div>
        </div>
      </Panel>
      {out && (
        <Panel title="HEDIS care-gap sidebar">
          <div className="flex items-baseline gap-2 flex-wrap mb-2.5">
            <span className="text-xl font-bold tracking-tight text-ink">{out.total_open_gaps}</span>
            <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
              open gaps{out.patient_age != null ? ` · age ${out.patient_age}` : ""}
            </span>
          </div>
          <div className="text-sm text-ink mb-3">{out.headline}</div>
          <div className="space-y-2">
            {out.gaps.length === 0 && (
              <div className="text-sm text-text-muted">No open care gaps for this patient.</div>
            )}
            {out.gaps.map((g, i) => (
              <div key={i} className="p-2.5 rounded-md bg-surface-low ring-1 ring-line">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-ink">{g.measure || g.title || "Care gap"}</span>
                  {g.priority && (
                    <Pill tone={(g.priority || "").toLowerCase() === "high" ? "error" : "warn"}>
                      {g.priority}
                    </Pill>
                  )}
                </div>
                {g.description && <div className="text-xs text-text-muted mt-1">{g.description}</div>}
              </div>
            ))}
          </div>
          {out.more_gaps > 0 && (
            <div className="text-xs text-text-muted mt-2.5">
              + {out.more_gaps} more gap{out.more_gaps === 1 ? "" : "s"} not shown — open the full care-gap report.
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------
// No-show — equity audit across groups + per-tier reminder plan.

function NoShowPane({ hospitalId }: { hospitalId: string }) {
  const [recordsText, setRecordsText] = useState<string>(JSON.stringify([
    { patient_id: "p001", group: "medicaid", no_show_probability: 0.42 },
    { patient_id: "p002", group: "medicaid", no_show_probability: 0.51 },
    { patient_id: "p003", group: "commercial", no_show_probability: 0.18 },
    { patient_id: "p004", group: "commercial", no_show_probability: 0.21 },
    { patient_id: "p005", group: "self_pay", no_show_probability: 0.39 },
  ], null, 2));
  const [groupKey, setGroupKey] = useState("group");
  const [audit, setAudit] = useState<NoShowEquityAudit | null>(null);
  const [auditBusy, setAuditBusy] = useState(false);
  const runAudit = async () => {
    setAuditBusy(true);
    try {
      setAudit(await noShowEquityAudit(hospitalId, JSON.parse(recordsText), groupKey || undefined));
    } catch {
      /* keep last result */
    } finally {
      setAuditBusy(false);
    }
  };

  const [tier, setTier] = useState<"low" | "medium" | "high">("high");
  const [apptIso, setApptIso] = useState(new Date(Date.now() + 48 * 3600 * 1000).toISOString());
  const [prob, setProb] = useState(0.45);
  const [plan, setPlan] = useState<ReminderPlan | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const runPlan = async () => {
    setPlanBusy(true);
    try {
      setPlan(await noShowReminderPlan(hospitalId, {
        tier,
        appointment_iso: apptIso,
        no_show_probability: prob,
      }));
    } finally {
      setPlanBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel title="Equity audit — fairness across groups">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>Group key</FieldLabel>
            <input value={groupKey} onChange={(e) => setGroupKey(e.target.value)} className={inputClass} />
          </label>
          <div className="flex items-end">
            <ActionButton onClick={runAudit} busy={auditBusy} icon={Users}>
              Run equity audit
            </ActionButton>
          </div>
        </div>
        <label className="flex flex-col gap-1 mt-2.5">
          <FieldLabel>No-show records (JSON array)</FieldLabel>
          <textarea
            value={recordsText}
            onChange={(e) => setRecordsText(e.target.value)}
            rows={8}
            className={`${textareaClass} font-mono text-xs`}
            aria-label="No-show records JSON"
          />
        </label>
      </Panel>
      {audit && (
        <div className={`rounded-lg p-4 ${audit.flag ? "bg-warning-container ring-1 ring-warning/30" : "bg-success-container ring-1 ring-success/30"}`}>
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-xl font-bold tracking-tight text-ink">
              {(audit.max_risk_gap * 100).toFixed(1)}%
            </span>
            <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
              max risk gap between groups
            </span>
            {audit.flag && <Pill tone="warn">Disparity flagged</Pill>}
          </div>
          <div className="text-sm text-ink mt-1">{audit.note}</div>
          <div className="mt-3">
            <FieldLabel>By group</FieldLabel>
            <JsonBlock value={audit.by_group} />
          </div>
        </div>
      )}

      <Panel title="Reminder plan">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <label className="flex flex-col gap-1">
            <FieldLabel>Risk tier</FieldLabel>
            <select value={tier} onChange={(e) => setTier(e.target.value as "low" | "medium" | "high")} className={inputClass}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>No-show probability</FieldLabel>
            <input
              type="number"
              step={0.05}
              min={0}
              max={1}
              value={prob}
              onChange={(e) => setProb(Number(e.target.value))}
              className={inputClass}
            />
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>Appointment ISO</FieldLabel>
            <input value={apptIso} onChange={(e) => setApptIso(e.target.value)} className={inputClass} />
          </label>
        </div>
        <ActionButton onClick={runPlan} busy={planBusy} variant="dark" icon={CalendarClock} className="mt-3">
          Build reminder plan
        </ActionButton>
      </Panel>
      {plan && (
        <Panel title={`Reminder schedule · ${plan.tier} tier`}>
          <div className="text-sm text-ink mb-2.5">{plan.summary}</div>
          <div className="flex flex-wrap gap-1.5 mb-2.5">
            {plan.channels.map((c) => (
              <Pill key={c}>{c}</Pill>
            ))}
          </div>
          <div className="divide-y divide-line">
            {plan.reminders.map((r, i) => (
              <div key={i} className="flex justify-between items-center gap-3 py-1.5 text-sm">
                <span className="flex items-center gap-2 text-ink">
                  {r.due
                    ? <Check className="w-4 h-4 text-success shrink-0" aria-hidden />
                    : <CalendarClock className="w-4 h-4 text-text-muted shrink-0" aria-hidden />}
                  {r.channel} · {r.offset_hours}h before
                </span>
                <span className="text-xs text-text-muted shrink-0">{r.send_iso}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------
// Result loop-closure — detect abnormal → review drafts → closure state machine.

// Mirrors the backend closure state machine in services/followups.py:
//   outstanding -> {communicated, dismissed};  communicated -> {acknowledged, dismissed}
//   acknowledged / dismissed are terminal (no further transitions).
const CLOSURE_NEXT: Record<string, { state: string; label: string }[]> = {
  outstanding: [
    { state: "communicated", label: "Mark patient notified" },
    { state: "dismissed", label: "Dismiss as insignificant" },
  ],
  communicated: [
    { state: "acknowledged", label: "Patient acknowledged" },
    { state: "dismissed", label: "Dismiss as insignificant" },
  ],
  acknowledged: [],
  dismissed: [],
};

function ResultLoopPane({ hospitalId }: { hospitalId: string }) {
  const [patientId, setPatientId] = useState("p001");
  const [resultsText, setResultsText] = useState<string>(JSON.stringify([
    { name: "Potassium", value: 6.4, unit: "mmol/L" },
    { name: "Hemoglobin A1c", value: 11.2, unit: "%" },
    { name: "TSH", value: 2.1, unit: "mIU/L" },
  ], null, 2));
  const [abnormal, setAbnormal] = useState<AbnormalResult[] | null>(null);
  const [detectBusy, setDetectBusy] = useState(false);
  const detect = async () => {
    setDetectBusy(true);
    setDrafts(null);
    try {
      const res = await resultsDetectAbnormal(hospitalId, JSON.parse(resultsText));
      setAbnormal(res.abnormal_results);
    } catch {
      /* keep last result */
    } finally {
      setDetectBusy(false);
    }
  };

  const [drafts, setDrafts] = useState<ResultReviewDraft[] | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const review = async () => {
    if (!abnormal) return;
    setReviewBusy(true);
    try {
      const res = await resultsReview(hospitalId, {
        abnormal_results: abnormal,
        reading_level: "grade_6",
        language: "en",
      });
      setDrafts(res.drafts);
    } finally {
      setReviewBusy(false);
    }
  };

  const [closures, setClosures] = useState<ResultClosure[]>([]);
  const [openBusy, setOpenBusy] = useState<string | null>(null);
  const openClosure = async (r: AbnormalResult) => {
    const key = r.result_name || r.name || JSON.stringify(r);
    setOpenBusy(key);
    try {
      const c = await resultClosureOpen(hospitalId, {
        patient_id: patientId,
        result: r,
        detected_by: "abnormal-detector",
      });
      setClosures((prev) => [...prev, c]);
    } finally {
      setOpenBusy(null);
    }
  };

  const [advanceBusy, setAdvanceBusy] = useState<string | null>(null);
  const [advanceErr, setAdvanceErr] = useState<string | null>(null);
  const advance = async (closure: ResultClosure, toState: string) => {
    setAdvanceBusy(closure.closure_id + toState);
    setAdvanceErr(null);
    try {
      const updated = await resultClosureAdvance(hospitalId, {
        closure,
        to_state: toState,
        actor: "Clinician",
        note: `Advanced to ${toState}`,
      });
      setClosures((prev) => prev.map((c) => (c.closure_id === updated.closure_id ? updated : c)));
    } catch {
      setAdvanceErr(`Cannot transition to ${toState} from ${closure.state} — illegal step.`);
    } finally {
      setAdvanceBusy(null);
    }
  };

  const [summary, setSummary] = useState<ClosureSummary | null>(null);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const runSummary = async () => {
    setSummaryBusy(true);
    try {
      setSummary(await resultClosureSummary(hospitalId, closures));
    } finally {
      setSummaryBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel title="1 · Detect abnormal results">
        <label className="flex flex-col gap-1">
          <FieldLabel>Patient ID</FieldLabel>
          <input value={patientId} onChange={(e) => setPatientId(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1.5 mt-2.5">
          <FieldLabel>Lab results (JSON array)</FieldLabel>
          <textarea
            value={resultsText}
            onChange={(e) => setResultsText(e.target.value)}
            rows={7}
            className={`${textareaClass} font-mono text-xs`}
            aria-label="Lab results JSON"
          />
        </label>
        <ActionButton onClick={detect} busy={detectBusy} icon={FlaskConical} className="mt-3">
          Detect abnormal
        </ActionButton>
      </Panel>

      {abnormal && (
        <Panel title={`Abnormal results · ${abnormal.length}`}>
          {abnormal.length === 0 && (
            <div className="text-sm text-text-muted">No abnormal results in this set.</div>
          )}
          <div className="space-y-2">
            {abnormal.map((r, i) => {
              const key = r.result_name || r.name || `result-${i}`;
              return (
                <div key={i} className={`p-2.5 rounded-md ${toneFor(r.severity)}`}>
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-ink">
                      {r.result_name || r.name}
                      {r.value != null ? ` · ${r.value}${r.unit ? ` ${r.unit}` : ""}` : ""}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {r.severity && (
                        <Pill tone={(r.severity || "").toLowerCase() === "critical" ? "error" : "warn"}>
                          {r.severity}
                        </Pill>
                      )}
                      <ActionButton
                        onClick={() => openClosure(r)}
                        busy={openBusy === key}
                        icon={ClipboardList}
                        className="!h-7 !px-2.5 !text-xs"
                      >
                        Open loop
                      </ActionButton>
                    </div>
                  </div>
                  {r.reason && <div className="text-xs text-text-muted mt-1">{r.reason}</div>}
                </div>
              );
            })}
          </div>
          {abnormal.length > 0 && (
            <ActionButton onClick={review} busy={reviewBusy} variant="dark" icon={MessageCircle} className="mt-3">
              2 · Draft patient messages
            </ActionButton>
          )}
        </Panel>
      )}

      {drafts && (
        <Panel title="Patient-message drafts (review before send)">
          <div className="space-y-2">
            {drafts.map((d, i) => (
              <div key={i} className="p-2.5 rounded-md bg-warning-container ring-1 ring-warning/30">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-ink">{d.result_name}</span>
                  <div className="flex items-center gap-1.5">
                    <Pill tone="muted">{d.tone}</Pill>
                    <Pill tone={(d.severity || "").toLowerCase() === "critical" ? "error" : "warn"}>
                      {d.severity}
                    </Pill>
                  </div>
                </div>
                <div className="text-sm text-ink mt-1.5">{d.message}</div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {closures.length > 0 && (
        <Panel title={`3 · Closure state machine · ${closures.length} open`}>
          {advanceErr && (
            <div className="flex items-center gap-1.5 text-xs text-error mb-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" aria-hidden />
              {advanceErr}
            </div>
          )}
          <div className="space-y-2.5">
            {closures.map((c) => {
              const next = CLOSURE_NEXT[c.state] || [];
              const isClosed = c.state === "closed";
              return (
                <div key={c.closure_id} className="p-3 rounded-md bg-surface-low ring-1 ring-line">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-ink">
                      {(c.result?.result_name as string) || (c.result?.name as string) || "Result"}
                    </span>
                    <Pill tone={isClosed ? "ok" : "warn"}>{c.state}</Pill>
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    {(c.history || []).map((h) => h.state).join("  ->  ")}
                  </div>
                  {next.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-2.5">
                      {next.map((n) => (
                        <ActionButton
                          key={n.state}
                          onClick={() => advance(c, n.state)}
                          busy={advanceBusy === c.closure_id + n.state}
                          icon={ArrowRight}
                          className="!h-8 !px-3 !text-xs"
                        >
                          {n.label}
                        </ActionButton>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <ActionButton onClick={runSummary} busy={summaryBusy} variant="dark" icon={ClipboardList} className="mt-3">
            Refresh closure queue summary
          </ActionButton>
        </Panel>
      )}

      {summary && (
        <div className={`rounded-lg p-4 ${summary.critical_open > 0 ? "bg-error-container ring-1 ring-error/30" : toneFor(summary.open > 0 ? "moderate" : "low")}`}>
          <div className="flex items-baseline gap-3 flex-wrap">
            <span className="text-xl font-bold tracking-tight text-ink">{summary.open}</span>
            <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">
              open · {summary.closed} closed · {summary.total} total
            </span>
            {summary.critical_open > 0 && (
              <Pill tone="error">{summary.critical_open} critical open</Pill>
            )}
          </div>
          <div className="mt-3">
            <FieldLabel>By state</FieldLabel>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {Object.entries(summary.by_state).map(([k, v]) => (
                <Pill key={k}>{k}: {v}</Pill>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
