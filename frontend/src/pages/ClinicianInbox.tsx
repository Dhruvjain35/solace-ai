import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Inbox, Pill, ShieldCheck, Activity, Send, Loader2, FileCheck2, FileText, Braces, Gavel, BookCheck, CheckCircle2, AlertTriangle, XCircle, ExternalLink } from "lucide-react";
import { inboxDraft, abnormalResultDraft, refillTriage, paPacket } from "../lib/api";
import {
  paCompleteness,
  paHumanPacket,
  paDaVinciBundle,
  paAppeal,
  evidenceGround,
  type Completeness,
  type HumanPacket,
  type FhirBundle,
  type Appeal,
  type EvidenceGrounding,
  type GroundingVerdict,
} from "../lib/api-inbox";

type Tab = "inbox" | "results" | "refills" | "pa" | "evidence";

export default function ClinicianInbox() {
  const { hospitalId = "demo" } = useParams();
  const [tab, setTab] = useState<Tab>("inbox");

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to={`/${hospitalId}/clinician`} aria-label="Back to dashboard" className="rounded-md p-1 text-slate-500 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors"><ArrowLeft className="w-5 h-5" aria-hidden="true" /></Link>
          <div>
            <div className="text-sm text-slate-500">Solace inbox + admin</div>
            <div className="font-semibold">Patient messages, results, refills, prior auth</div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-4 flex gap-1" role="tablist" aria-label="Inbox sections">
          {[
            { key: "inbox", label: "Inbox draft", icon: Inbox },
            { key: "results", label: "Result triage", icon: Activity },
            { key: "refills", label: "Refill triage", icon: Pill },
            { key: "pa", label: "Prior auth", icon: ShieldCheck },
            { key: "evidence", label: "Evidence grounding", icon: BookCheck },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`inbox-tab-${key}`}
              aria-selected={tab === key}
              aria-controls={`inbox-panel-${key}`}
              onClick={() => setTab(key as Tab)}
              className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 -mb-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-inset transition-colors ${tab === key ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-900"}`}
            >
              <Icon className="w-4 h-4" aria-hidden="true" />{label}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-5xl mx-auto p-4">
        <div id="inbox-panel-inbox" role="tabpanel" aria-labelledby="inbox-tab-inbox" hidden={tab !== "inbox"}>
          {tab === "inbox" && <InboxPane hospitalId={hospitalId} />}
        </div>
        <div id="inbox-panel-results" role="tabpanel" aria-labelledby="inbox-tab-results" hidden={tab !== "results"}>
          {tab === "results" && <ResultsPane hospitalId={hospitalId} />}
        </div>
        <div id="inbox-panel-refills" role="tabpanel" aria-labelledby="inbox-tab-refills" hidden={tab !== "refills"}>
          {tab === "refills" && <RefillsPane hospitalId={hospitalId} />}
        </div>
        <div id="inbox-panel-pa" role="tabpanel" aria-labelledby="inbox-tab-pa" hidden={tab !== "pa"}>
          {tab === "pa" && <PAPane hospitalId={hospitalId} />}
        </div>
        <div id="inbox-panel-evidence" role="tabpanel" aria-labelledby="inbox-tab-evidence" hidden={tab !== "evidence"}>
          {tab === "evidence" && <EvidencePane hospitalId={hospitalId} />}
        </div>
      </div>
    </div>
  );
}

function InboxPane({ hospitalId }: { hospitalId: string }) {
  const [msg, setMsg] = useState("Hi doctor — I've had this dull headache for 3 days, mostly behind my eyes. Tylenol helps a little. Should I be worried?");
  const [draft, setDraft] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setDraft(await inboxDraft(hospitalId, msg, {})); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <label htmlFor="inbox-msg" className="block text-xs uppercase tracking-wide text-slate-500 mb-2">Inbound patient message</label>
        <textarea id="inbox-msg" value={msg} onChange={(e) => setMsg(e.target.value)} rows={4} className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        <button type="button" onClick={run} disabled={busy} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm flex items-center gap-1 hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Send className="w-3 h-3" aria-hidden="true" />} Draft reply</button>
      </div>
      {draft && (
        <div className="bg-white rounded-lg border border-slate-200 p-4" role="status" aria-live="polite">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs uppercase tracking-wide text-slate-500">AI draft</div>
            <div className="text-xs px-2 py-0.5 rounded bg-slate-100">{draft.tone} | {draft.suggested_action}</div>
          </div>
          {draft.red_flags?.length > 0 && (
            <div className="bg-rose-50 border border-rose-200 rounded p-2 mb-2 text-xs text-rose-900">Red flags: {draft.red_flags.join(", ")}</div>
          )}
          <div className="whitespace-pre-wrap text-sm">{draft.draft}</div>
        </div>
      )}
    </div>
  );
}

function ResultsPane({ hospitalId }: { hospitalId: string }) {
  const [labName, setLabName] = useState("a1c");
  const [value, setValue] = useState(9.4);
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setOut(await abnormalResultDraft(hospitalId, labName, value)); } finally { setBusy(false); } };
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4 grid grid-cols-1 md:grid-cols-3 gap-2">
        <div>
          <label htmlFor="results-lab" className="text-xs text-slate-500">Lab name</label>
          <select id="results-lab" value={labName} onChange={(e) => setLabName(e.target.value)} className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500">
            {["a1c", "glucose_fasting", "tsh", "ldl", "potassium", "sodium", "creatinine", "hemoglobin", "wbc", "platelets", "alt", "ast"].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="results-value" className="text-xs text-slate-500">Value</label>
          <input id="results-value" type="number" value={value} onChange={(e) => setValue(Number(e.target.value))} className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <button type="button" onClick={run} disabled={busy} className="self-end bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy ? "..." : "Triage + draft"}</button>
      </div>
      {out && (
        <div className="bg-white rounded-lg border border-slate-200 p-4" role="status" aria-live="polite">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Classification</div>
          <pre className="text-xs bg-slate-50 rounded p-2">{JSON.stringify(out.classification, null, 2)}</pre>
          <div className="text-xs uppercase tracking-wide text-slate-500 mt-3 mb-1">Patient draft (urgency: <b>{out.urgency}</b>)</div>
          <div className="whitespace-pre-wrap text-sm">{out.draft}</div>
        </div>
      )}
    </div>
  );
}

function RefillsPane({ hospitalId }: { hospitalId: string }) {
  const [med, setMed] = useState("metformin");
  const [lastVisit, setLastVisit] = useState("2025-08-01");
  const [labDate, setLabDate] = useState("2025-08-01");
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setOut(await refillTriage(hospitalId, { medication_canonical: med, last_visit_iso: new Date(lastVisit).toISOString(), relevant_lab_iso: new Date(labDate).toISOString() }));
    } finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4 grid grid-cols-1 md:grid-cols-4 gap-2">
        <div>
          <label htmlFor="refill-med" className="text-xs text-slate-500">Medication</label>
          <input id="refill-med" value={med} onChange={(e) => setMed(e.target.value)} className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <div>
          <label htmlFor="refill-visit" className="text-xs text-slate-500">Last visit (date)</label>
          <input id="refill-visit" type="date" value={lastVisit} onChange={(e) => setLastVisit(e.target.value)} className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <div>
          <label htmlFor="refill-lab" className="text-xs text-slate-500">Last relevant lab (date)</label>
          <input id="refill-lab" type="date" value={labDate} onChange={(e) => setLabDate(e.target.value)} className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <button type="button" onClick={run} disabled={busy} className="self-end bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy ? "..." : "Triage"}</button>
      </div>
      {out && (
        <div role="status" aria-live="polite" className={`rounded-lg border p-4 ${out.decision === "protocol_approved" ? "bg-emerald-50 border-emerald-200" : out.decision === "physician_required" ? "bg-amber-50 border-amber-200" : "bg-slate-50 border-slate-200"}`}>
          <div className="text-xs uppercase tracking-wide mb-1">Decision: <b>{out.decision}</b></div>
          <div className="text-sm">{out.reason}</div>
          <div className="text-sm mt-2 italic">Patient message: "{out.patient_message}"</div>
        </div>
      )}
    </div>
  );
}

function PAPane({ hospitalId }: { hospitalId: string }) {
  const [note, setNote] = useState("Patient with chronic low back pain x 6mo, failed PT and 2 NSAIDs. MRI lumbar requested to evaluate for HNP given new radicular features.");
  const [diagnosis, setDiagnosis] = useState("Lumbar radiculopathy");
  const [icd10, setIcd10] = useState("M54.16");
  const [requested, setRequested] = useState("MRI lumbar spine without contrast");
  const [code, setCode] = useState("72148");
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const r = await paPacket(hospitalId, {
        note_text: note, diagnosis, icd10,
        requested_service: requested, cpt_or_hcpcs_or_ndc: code,
        patient: { name: "Jane Doe", dob: "1980-04-12", member_id: "X9981" },
        payer: { name: "BCBS" },
        provider: { name: "Dr. Smith" },
      });
      setOut(r);
    } finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-2">
        <div>
          <label htmlFor="pa-note" className="text-xs text-slate-500">Encounter note</label>
          <textarea id="pa-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)} placeholder="diagnosis" aria-label="Diagnosis" className="px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
          <input value={icd10} onChange={(e) => setIcd10(e.target.value)} placeholder="ICD-10" aria-label="ICD-10 code" className="px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
          <input value={requested} onChange={(e) => setRequested(e.target.value)} placeholder="requested service" aria-label="Requested service" className="px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="CPT/HCPCS/NDC" aria-label="CPT, HCPCS or NDC code" className="px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <button type="button" onClick={run} disabled={busy} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy ? "..." : "Build PA packet"}</button>
      </div>
      {out && (
        <div className="bg-white rounded-lg border border-slate-200 p-4" role="status" aria-live="polite">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Narrative</div>
          <pre className="text-xs bg-slate-50 rounded p-2 whitespace-pre-wrap">{out.packet?.narrative?.clinical_rationale}</pre>
          <div className="text-xs uppercase tracking-wide text-slate-500 mt-3 mb-1">Submission channels</div>
          <div className="text-xs">{out.packet?.submission_channels?.map((s: any) => `${s.channel}: ${s.status}`).join(" | ")}</div>
          <div className="text-xs uppercase tracking-wide text-slate-500 mt-3 mb-1">Da Vinci PAS Claim (FHIR)</div>
          <pre className="text-xs bg-slate-50 rounded p-2 max-h-64 overflow-auto">{JSON.stringify(out.fhir_claim, null, 2)}</pre>
        </div>
      )}
      {out?.packet && <PAFollowUp hospitalId={hospitalId} packet={out.packet} />}
    </div>
  );
}

// --- PA follow-up: completeness, human packet, FHIR bundle, denial appeal -------------
function PAFollowUp({ hospitalId, packet }: { hospitalId: string; packet: Record<string, unknown> }) {
  const [completeness, setCompleteness] = useState<Completeness | null>(null);
  const [human, setHuman] = useState<HumanPacket | null>(null);
  const [bundle, setBundle] = useState<FhirBundle | null>(null);
  const [busy, setBusy] = useState<"" | "completeness" | "human" | "bundle">("");
  const [err, setErr] = useState("");

  const runCompleteness = async () => {
    setBusy("completeness"); setErr("");
    try { setCompleteness(await paCompleteness(hospitalId, packet)); }
    catch { setErr("Could not run the readiness check. Try again in a moment."); }
    finally { setBusy(""); }
  };
  const runHuman = async () => {
    setBusy("human"); setErr("");
    try { setHuman(await paHumanPacket(hospitalId, packet)); }
    catch { setErr("Could not assemble the formatted packet. Try again in a moment."); }
    finally { setBusy(""); }
  };
  const runBundle = async () => {
    setBusy("bundle"); setErr("");
    try { setBundle(await paDaVinciBundle(hospitalId, packet)); }
    catch { setErr("Could not build the FHIR bundle. Try again in a moment."); }
    finally { setBusy(""); }
  };

  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Packet actions</div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={runCompleteness} disabled={busy !== ""} className="flex items-center gap-1 px-3 py-1.5 rounded text-sm border border-slate-300 hover:bg-slate-50 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy === "completeness" ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <FileCheck2 className="w-3 h-3" aria-hidden="true" />} Check readiness</button>
          <button type="button" onClick={runHuman} disabled={busy !== ""} className="flex items-center gap-1 px-3 py-1.5 rounded text-sm border border-slate-300 hover:bg-slate-50 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy === "human" ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <FileText className="w-3 h-3" aria-hidden="true" />} Formatted packet</button>
          <button type="button" onClick={runBundle} disabled={busy !== ""} className="flex items-center gap-1 px-3 py-1.5 rounded text-sm border border-slate-300 hover:bg-slate-50 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy === "bundle" ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Braces className="w-3 h-3" aria-hidden="true" />} FHIR bundle</button>
        </div>
        {err && <div className="mt-2 text-xs text-rose-700" role="alert">{err}</div>}
      </div>

      {completeness && (
        <div className="bg-white rounded-lg border border-slate-200 p-4" role="status" aria-live="polite">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs uppercase tracking-wide text-slate-500">Submission readiness</div>
            <div className={`text-xs px-2 py-0.5 rounded font-medium ${completeness.ready_to_submit ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-900"}`}>{completeness.ready_to_submit ? "Ready to submit" : "Not ready"}</div>
          </div>
          <div className="flex items-center gap-3 mb-3">
            <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
              <div className={`h-full rounded-full ${completeness.score >= 80 ? "bg-emerald-500" : completeness.score >= 50 ? "bg-amber-500" : "bg-rose-500"}`} style={{ width: `${Math.max(0, Math.min(100, completeness.score))}%` }} />
            </div>
            <div className="text-sm font-semibold tabular-nums">{completeness.score}/100</div>
          </div>
          {completeness.blockers?.length > 0 && (
            <div className="space-y-1.5 mb-2">
              <div className="text-xs uppercase tracking-wide text-rose-600">Blockers</div>
              {completeness.blockers.map((b, i) => (
                <div key={i} className="flex items-start gap-2 text-xs bg-rose-50 border border-rose-200 rounded p-2">
                  <XCircle className="w-3.5 h-3.5 text-rose-600 mt-0.5 shrink-0" aria-hidden="true" />
                  <div><b className="text-rose-900">{b.field}</b> — {b.message}<div className="text-rose-700 mt-0.5">Fix: {b.fix}</div></div>
                </div>
              ))}
            </div>
          )}
          {completeness.warnings?.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs uppercase tracking-wide text-amber-600">Warnings</div>
              {completeness.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 text-xs bg-amber-50 border border-amber-200 rounded p-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-600 mt-0.5 shrink-0" aria-hidden="true" />
                  <div>{w.field ? <b className="text-amber-900">{w.field} — </b> : null}{w.message}</div>
                </div>
              ))}
            </div>
          )}
          {completeness.blockers?.length === 0 && completeness.warnings?.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-emerald-800"><CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" /> No blockers or warnings — packet is clean.</div>
          )}
        </div>
      )}

      {human && (
        <div className="bg-white rounded-lg border border-slate-200 p-4" role="status" aria-live="polite">
          <div className="flex items-center justify-between mb-1">
            <div className="text-base font-semibold">{human.title}</div>
            <div className="text-xs px-2 py-0.5 rounded bg-slate-100">{human.completeness}% complete</div>
          </div>
          <div className="text-xs text-slate-500 mb-3">Generated {human.generated_at}</div>
          <div className="space-y-3">
            {human.sections?.map((s, i) => (
              <div key={i}>
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">{s.heading}</div>
                <div className="whitespace-pre-wrap text-sm text-slate-800">{s.body}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-slate-200 whitespace-pre-wrap text-sm text-slate-600">{human.signature_block}</div>
        </div>
      )}

      {bundle && (
        <div className="bg-white rounded-lg border border-slate-200 p-4" role="status" aria-live="polite">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Da Vinci FHIR Bundle ({bundle.type || "collection"})</div>
          {bundle.entry && bundle.entry.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {bundle.entry.map((e, i) => (
                <span key={i} className="text-xs px-2 py-0.5 rounded bg-slate-100">{e.resource?.resourceType || "Resource"}</span>
              ))}
            </div>
          )}
          <pre className="text-xs bg-slate-50 rounded p-2 max-h-80 overflow-auto">{JSON.stringify(bundle, null, 2)}</pre>
        </div>
      )}

      <DenialAppeal hospitalId={hospitalId} packet={packet} />
    </div>
  );
}

// --- Denial appeal form --------------------------------------------------------------
function DenialAppeal({ hospitalId, packet }: { hospitalId: string; packet: Record<string, unknown> }) {
  const [reason, setReason] = useState("Service deemed not medically necessary; conservative therapy not documented as exhausted.");
  const [category, setCategory] = useState("medical_necessity");
  const [date, setDate] = useState("");
  const [context, setContext] = useState("");
  const [appeal, setAppeal] = useState<Appeal | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    setBusy(true); setErr("");
    try {
      setAppeal(await paAppeal(hospitalId, {
        packet,
        denial_reason: reason,
        denial_category: category || undefined,
        denial_date: date ? new Date(date).toISOString() : undefined,
        appeal_level: "first",
        additional_context: context || undefined,
      }));
    } catch {
      setErr("Could not generate the appeal letter. Try again in a moment.");
    } finally { setBusy(false); }
  };

  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-2">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500"><Gavel className="w-3.5 h-3.5" aria-hidden="true" /> Denial appeal</div>
      <div>
        <label htmlFor="appeal-reason" className="text-xs text-slate-500">Denial reason (as stated by payer)</label>
        <textarea id="appeal-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div>
          <label htmlFor="appeal-category" className="text-xs text-slate-500">Denial category</label>
          <select id="appeal-category" value={category} onChange={(e) => setCategory(e.target.value)} className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500">
            {["medical_necessity", "missing_documentation", "coding_error", "non_covered_benefit", "experimental", "other"].map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="appeal-date" className="text-xs text-slate-500">Denial date</label>
          <input id="appeal-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
      </div>
      <div>
        <label htmlFor="appeal-context" className="text-xs text-slate-500">Additional context (optional)</label>
        <textarea id="appeal-context" value={context} onChange={(e) => setContext(e.target.value)} rows={2} placeholder="New labs, imaging, or clinical updates since the original request" className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
      </div>
      <button type="button" onClick={run} disabled={busy} className="flex items-center gap-1 bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Gavel className="w-3 h-3" aria-hidden="true" />} Draft appeal letter</button>
      {err && <div className="text-xs text-rose-700" role="alert">{err}</div>}
      {appeal && (
        <div className="mt-2 space-y-3" role="status" aria-live="polite">
          <div className="text-xs text-slate-500">Appeal ID: <span className="font-mono">{appeal.appeal_id}</span></div>
          <div className="bg-slate-50 border border-slate-200 rounded p-3">
            <div className="whitespace-pre-wrap text-sm text-slate-800">{appeal.letter.header}</div>
            <div className="whitespace-pre-wrap text-sm text-slate-800 mt-2">{appeal.letter.body}</div>
            <div className="whitespace-pre-wrap text-sm text-slate-600 mt-2 pt-2 border-t border-slate-200">{appeal.letter.signature}</div>
          </div>
          {appeal.rebuttal_points?.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Rebuttal points</div>
              <ul className="list-disc pl-5 text-sm space-y-0.5">{appeal.rebuttal_points.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
          {appeal.additional_evidence_requested?.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Additional evidence to attach</div>
              <ul className="list-disc pl-5 text-sm space-y-0.5">{appeal.additional_evidence_requested.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// --- Evidence grounding pane ---------------------------------------------------------
const VERDICT_STYLE: Record<GroundingVerdict, { bg: string; fg: string; label: string; Icon: typeof CheckCircle2 }> = {
  supported: { bg: "bg-emerald-100", fg: "text-emerald-900", label: "Supported", Icon: CheckCircle2 },
  partial: { bg: "bg-amber-100", fg: "text-amber-900", label: "Partially supported", Icon: AlertTriangle },
  unsupported: { bg: "bg-rose-100", fg: "text-rose-900", label: "Unsupported", Icon: XCircle },
};

function EvidencePane({ hospitalId }: { hospitalId: string }) {
  const [recommendation, setRecommendation] = useState("Start empiric ceftriaxone 1g IV daily for uncomplicated community-acquired pneumonia in an otherwise healthy adult.");
  const [context, setContext] = useState("");
  const [out, setOut] = useState<EvidenceGrounding | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    setBusy(true); setErr("");
    try { setOut(await evidenceGround(hospitalId, recommendation, context)); }
    catch { setErr("Could not check this recommendation against the evidence base. Try again in a moment."); }
    finally { setBusy(false); }
  };

  const verdict = out ? VERDICT_STYLE[out.verdict] : null;

  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-2">
        <div>
          <label htmlFor="evidence-rec" className="text-xs text-slate-500">Clinical recommendation to verify</label>
          <textarea id="evidence-rec" value={recommendation} onChange={(e) => setRecommendation(e.target.value)} rows={3} className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <div>
          <label htmlFor="evidence-ctx" className="text-xs text-slate-500">Clinical context (optional)</label>
          <textarea id="evidence-ctx" value={context} onChange={(e) => setContext(e.target.value)} rows={2} placeholder="Patient age, comorbidities, allergies, prior treatments" className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
        </div>
        <button type="button" onClick={run} disabled={busy || !recommendation.trim()} className="flex items-center gap-1 bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">{busy ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <BookCheck className="w-3 h-3" aria-hidden="true" />} Ground in evidence</button>
        {err && <div className="text-xs text-rose-700" role="alert">{err}</div>}
      </div>

      {out && verdict && (
        <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3" role="status" aria-live="polite">
          <div className="flex items-center gap-2">
            <span className={`flex items-center gap-1 text-xs px-2 py-1 rounded font-medium ${verdict.bg} ${verdict.fg}`}>
              <verdict.Icon className="w-3.5 h-3.5" aria-hidden="true" /> {verdict.label}
            </span>
            <span className="text-xs text-slate-500">Confidence {Math.round(out.confidence * 100)}%</span>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Rationale</div>
            <div className="text-sm text-slate-800 whitespace-pre-wrap">{out.rationale}</div>
          </div>
          {out.supporting_evidence?.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Supporting evidence</div>
              <ul className="list-disc pl-5 text-sm space-y-0.5">{out.supporting_evidence.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          )}
          {out.citations?.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Citations</div>
              <ul className="space-y-1">
                {out.citations.map((c, i) => (
                  <li key={i} className="text-sm flex items-start gap-1.5">
                    <span className="text-slate-400 tabular-nums shrink-0">{c.index ?? i + 1}.</span>
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-1 rounded">
                        {c.title} <ExternalLink className="w-3 h-3" aria-hidden="true" />
                      </a>
                    ) : (
                      <span className="text-slate-800">{c.title}</span>
                    )}
                    {(c.source || c.year) && <span className="text-xs text-slate-500">({[c.source, c.year].filter(Boolean).join(", ")})</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
