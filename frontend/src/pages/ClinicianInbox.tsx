import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Inbox, Pill, ShieldCheck, Activity, Send, Loader2 } from "lucide-react";
import { inboxDraft, abnormalResultDraft, refillTriage, paPacket } from "../lib/api";

type Tab = "inbox" | "results" | "refills" | "pa";

export default function ClinicianInbox() {
  const { hospitalId = "demo" } = useParams();
  const [tab, setTab] = useState<Tab>("inbox");

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to={`/${hospitalId}/clinician`} className="text-slate-500 hover:text-slate-900"><ArrowLeft className="w-5 h-5" /></Link>
          <div>
            <div className="text-sm text-slate-500">Solace inbox + admin</div>
            <div className="font-semibold">Patient messages, results, refills, prior auth</div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-4 flex gap-1">
          {[
            { key: "inbox", label: "Inbox draft", icon: Inbox },
            { key: "results", label: "Result triage", icon: Activity },
            { key: "refills", label: "Refill triage", icon: Pill },
            { key: "pa", label: "Prior auth", icon: ShieldCheck },
          ].map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setTab(key as Tab)} className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 -mb-px ${tab === key ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-900"}`}>
              <Icon className="w-4 h-4" />{label}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-5xl mx-auto p-4">
        {tab === "inbox" && <InboxPane hospitalId={hospitalId} />}
        {tab === "results" && <ResultsPane hospitalId={hospitalId} />}
        {tab === "refills" && <RefillsPane hospitalId={hospitalId} />}
        {tab === "pa" && <PAPane hospitalId={hospitalId} />}
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
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Inbound patient message</div>
        <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={4} className="w-full px-3 py-2 border border-slate-300 rounded text-sm" />
        <button onClick={run} disabled={busy} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm flex items-center gap-1">{busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />} Draft reply</button>
      </div>
      {draft && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
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
          <label className="text-xs text-slate-500">Lab name</label>
          <select value={labName} onChange={(e) => setLabName(e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm">
            {["a1c", "glucose_fasting", "tsh", "ldl", "potassium", "sodium", "creatinine", "hemoglobin", "wbc", "platelets", "alt", "ast"].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-500">Value</label>
          <input type="number" value={value} onChange={(e) => setValue(Number(e.target.value))} className="w-full px-3 py-1.5 border rounded text-sm" />
        </div>
        <button onClick={run} disabled={busy} className="self-end bg-blue-600 text-white px-4 py-1.5 rounded text-sm">{busy ? "..." : "Triage + draft"}</button>
      </div>
      {out && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
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
          <label className="text-xs text-slate-500">Medication</label>
          <input value={med} onChange={(e) => setMed(e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm" />
        </div>
        <div>
          <label className="text-xs text-slate-500">Last visit (date)</label>
          <input type="date" value={lastVisit} onChange={(e) => setLastVisit(e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm" />
        </div>
        <div>
          <label className="text-xs text-slate-500">Last relevant lab (date)</label>
          <input type="date" value={labDate} onChange={(e) => setLabDate(e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm" />
        </div>
        <button onClick={run} disabled={busy} className="self-end bg-blue-600 text-white px-4 py-1.5 rounded text-sm">{busy ? "..." : "Triage"}</button>
      </div>
      {out && (
        <div className={`rounded-lg border p-4 ${out.decision === "protocol_approved" ? "bg-emerald-50 border-emerald-200" : out.decision === "physician_required" ? "bg-amber-50 border-amber-200" : "bg-slate-50 border-slate-200"}`}>
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
          <label className="text-xs text-slate-500">Encounter note</label>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} className="w-full px-3 py-2 border rounded text-sm" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)} placeholder="diagnosis" className="px-3 py-1.5 border rounded text-sm" />
          <input value={icd10} onChange={(e) => setIcd10(e.target.value)} placeholder="ICD-10" className="px-3 py-1.5 border rounded text-sm" />
          <input value={requested} onChange={(e) => setRequested(e.target.value)} placeholder="requested service" className="px-3 py-1.5 border rounded text-sm" />
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="CPT/HCPCS/NDC" className="px-3 py-1.5 border rounded text-sm" />
        </div>
        <button onClick={run} disabled={busy} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm">{busy ? "..." : "Build PA packet"}</button>
      </div>
      {out && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Narrative</div>
          <pre className="text-xs bg-slate-50 rounded p-2 whitespace-pre-wrap">{out.packet?.narrative?.clinical_rationale}</pre>
          <div className="text-xs uppercase tracking-wide text-slate-500 mt-3 mb-1">Submission channels</div>
          <div className="text-xs">{out.packet?.submission_channels?.map((s: any) => `${s.channel}: ${s.status}`).join(" | ")}</div>
          <div className="text-xs uppercase tracking-wide text-slate-500 mt-3 mb-1">Da Vinci PAS Claim (FHIR)</div>
          <pre className="text-xs bg-slate-50 rounded p-2 max-h-64 overflow-auto">{JSON.stringify(out.fhir_claim, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
