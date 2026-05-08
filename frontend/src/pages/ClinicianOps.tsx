import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Users, Network, Hospital, FileText, Phone, MessageCircle, Loader2, Send, Database } from "lucide-react";
import {
  cohortQuery, sepsisBundleEvaluate, encounterStitch, encounterHuddle,
  nurseTriageProtocols, nurseTriageEvaluate, tefcaQuery, telehealthSession,
  hl7MdmRender, portalThreads, portalThread, portalRespond, portalInbound,
} from "../lib/api";

type Tab = "portal" | "cohort" | "sepsis" | "longitudinal" | "triage" | "tefca" | "telehealth" | "hl7";

export default function ClinicianOps() {
  const { hospitalId = "demo" } = useParams();
  const [tab, setTab] = useState<Tab>("portal");
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to={`/${hospitalId}/clinician`} className="text-slate-500 hover:text-slate-900"><ArrowLeft className="w-5 h-5" /></Link>
          <div>
            <div className="text-sm text-slate-500">Solace operations</div>
            <div className="font-semibold">Portal · cohort · sepsis bundle · nurse triage · TEFCA · telehealth · HL7</div>
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
          ].map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setTab(key as Tab)} className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 -mb-px ${tab === key ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-900"}`}>
              <Icon className="w-4 h-4" />{label}
            </button>
          ))}
        </div>
      </div>
      <div className="max-w-5xl mx-auto p-4">
        {tab === "portal" && <PortalPane hospitalId={hospitalId} />}
        {tab === "cohort" && <CohortPane hospitalId={hospitalId} />}
        {tab === "sepsis" && <SepsisPane hospitalId={hospitalId} />}
        {tab === "longitudinal" && <LongitudinalPane hospitalId={hospitalId} />}
        {tab === "triage" && <NurseTriagePane hospitalId={hospitalId} />}
        {tab === "tefca" && <TefcaPane hospitalId={hospitalId} />}
        {tab === "telehealth" && <TelehealthPane hospitalId={hospitalId} />}
        {tab === "hl7" && <Hl7Pane hospitalId={hospitalId} />}
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
  useEffect(() => { refresh(); }, [hospitalId]);
  useEffect(() => { if (active) portalThread(hospitalId, active).then(setMessages); }, [active, hospitalId]);

  const seed = async () => {
    setBusy(true);
    try { await portalInbound(hospitalId, seedPatient, seedBody); await refresh(); } finally { setBusy(false); }
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
      <div className="bg-white rounded-lg border border-slate-200 p-3 grid grid-cols-1 md:grid-cols-3 gap-2">
        <input value={seedPatient} onChange={(e) => setSeedPatient(e.target.value)} className="px-3 py-1.5 border rounded text-sm" placeholder="patient_id" />
        <input value={seedBody} onChange={(e) => setSeedBody(e.target.value)} className="px-3 py-1.5 border rounded text-sm md:col-span-1" placeholder="message body" />
        <button onClick={seed} disabled={busy} className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm">{busy ? "..." : "Simulate inbound"}</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="bg-white rounded-lg border border-slate-200 p-3 md:col-span-1">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Threads</div>
          {threads.length === 0 && <div className="text-sm text-slate-500">No threads yet — simulate one above.</div>}
          {threads.map((t) => (
            <button key={t.thread_key} onClick={() => setActive(t.thread_key)} className={`w-full text-left px-3 py-2 rounded mb-1 text-sm ${active === t.thread_key ? "bg-blue-50 border border-blue-200" : "hover:bg-slate-50"}`}>
              <div className="font-medium">{t.patient_id}</div>
              <div className="text-xs text-slate-500">{t.message_count} msgs · {t.unread_count} unread</div>
            </button>
          ))}
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-3 md:col-span-2">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Messages</div>
          {!active && <div className="text-sm text-slate-500">Pick a thread.</div>}
          {messages.map((m) => (
            <div key={m.id} className={`mb-2 p-2 rounded text-sm ${m.direction === "inbound" ? "bg-slate-50" : "bg-blue-50"}`}>
              <div className="text-xs text-slate-500">{m.direction === "inbound" ? `Patient · ${(m.tags || []).join(", ")} · routed: ${m.routing}` : `Reply · ${m.sender_name}`}</div>
              <div>{m.body}</div>
              {m.ai_draft && m.direction === "inbound" && (
                <div className="mt-2 p-2 rounded bg-amber-50 border border-amber-200 text-xs">
                  <div className="font-semibold text-amber-900 mb-1">AI draft (review before send)</div>
                  <div>{m.ai_draft}</div>
                </div>
              )}
            </div>
          ))}
          {active && (
            <div className="mt-3 flex gap-2">
              <input value={reply} onChange={(e) => setReply(e.target.value)} className="flex-1 px-3 py-1.5 border rounded text-sm" placeholder="Type or edit AI draft..." />
              <button onClick={send} className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm flex items-center gap-1"><Send className="w-3 h-3" /> Send</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CohortPane({ hospitalId }: { hospitalId: string }) {
  const [icd, setIcd] = useState("E11.65");
  const [loinc, setLoinc] = useState("4548-4");
  const [thresh, setThresh] = useState(8.0);
  const [out, setOut] = useState<any | null>(null);
  const run = async () => setOut(await cohortQuery(hospitalId, { condition_icd10: icd || null, lab_loinc_above: loinc ? [loinc, thresh] : null }));
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4 grid grid-cols-3 gap-2">
        <label className="block"><span className="text-xs text-slate-500">Condition ICD-10</span><input value={icd} onChange={(e) => setIcd(e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm" /></label>
        <label className="block"><span className="text-xs text-slate-500">Lab LOINC</span><input value={loinc} onChange={(e) => setLoinc(e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm" /></label>
        <label className="block"><span className="text-xs text-slate-500">Above threshold</span><input type="number" value={thresh} onChange={(e) => setThresh(Number(e.target.value))} className="w-full px-3 py-1.5 border rounded text-sm" /></label>
        <button onClick={run} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm col-span-3">Build cohort</button>
      </div>
      {out && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Matched: <b className="text-slate-900">{out.count}</b></div>
          <pre className="text-xs bg-slate-50 rounded p-2 overflow-auto">{JSON.stringify(out.patients, null, 2)}</pre>
        </div>
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
  const run = async () => setOut(await sepsisBundleEvaluate(hospitalId, body));
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <textarea value={JSON.stringify(body, null, 2)} onChange={(e) => { try { setBody(JSON.parse(e.target.value)); } catch {} }} rows={12} className="w-full font-mono text-xs px-3 py-2 border rounded" />
        <button onClick={run} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm">Evaluate 1-hour bundle</button>
      </div>
      {out && (
        <div className={`rounded-lg border p-4 ${out.all_complete ? "bg-emerald-50 border-emerald-200" : "bg-amber-50 border-amber-200"}`}>
          <div className="font-semibold">Compliance {Math.round((out.compliance_rate || 0) * 100)}%</div>
          <div className="text-xs mt-2">Deadline: {out.deadline_iso}</div>
          <div className="mt-3 space-y-1 text-sm">
            {(out.elements || []).map((e: any, i: number) => (
              <div key={i} className={`flex justify-between border-b border-slate-100 py-1 ${e.completed ? "" : "text-rose-700"}`}>
                <span>{e.completed ? "✓" : "✗"} {e.name}{e.required === false ? " (not required)" : ""}</span>
                <span className="text-xs text-slate-500">{e.minutes != null ? `${e.minutes} min` : "—"}</span>
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
  const run = async () => { setBusy(true); try { setOut(await encounterStitch(hospitalId, JSON.parse(notesText))); } finally { setBusy(false); } };
  const [huddle, setHuddle] = useState("Attending: Bed 4 - Mr Garcia is trending up clinically, lactate down to 1.8 from 3.4. RN: he's on 2L still. Pharmacy: vanco trough was 14, target. Resident: plan to step down to floor today. Attending: agree, sign out the floor team to recheck CXR tomorrow.");
  const [hout, setHout] = useState<any | null>(null);
  const runH = async () => { setBusy(true); try { setHout(await encounterHuddle(hospitalId, huddle)); } finally { setBusy(false); } };
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Multi-encounter stitching</div>
        <textarea value={notesText} onChange={(e) => setNotesText(e.target.value)} rows={8} className="w-full font-mono text-xs px-3 py-2 border rounded" />
        <button onClick={run} disabled={busy} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm flex items-center gap-1">{busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Users className="w-3 h-3" />} Stitch</button>
      </div>
      {out && out.available && (
        <div className="bg-white rounded-lg border border-slate-200 p-4 text-sm space-y-2">
          <div><b>Narrative:</b> {out.narrative_summary}</div>
          <div><b>Active problems:</b><pre className="text-xs bg-slate-50 rounded p-2">{JSON.stringify(out.active_problems, null, 2)}</pre></div>
          <div><b>Interventions:</b><pre className="text-xs bg-slate-50 rounded p-2">{JSON.stringify(out.interventions_tried, null, 2)}</pre></div>
        </div>
      )}
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Huddle / rounds parser</div>
        <textarea value={huddle} onChange={(e) => setHuddle(e.target.value)} rows={4} className="w-full text-xs px-3 py-2 border rounded" />
        <button onClick={runH} disabled={busy} className="mt-2 bg-slate-900 text-white px-4 py-1.5 rounded text-sm">Parse huddle</button>
      </div>
      {hout && hout.available && (
        <pre className="bg-white border border-slate-200 rounded-lg p-4 text-xs overflow-auto">{JSON.stringify(hout, null, 2)}</pre>
      )}
    </div>
  );
}

function NurseTriagePane({ hospitalId }: { hospitalId: string }) {
  const [protocols, setProtocols] = useState<string[]>([]);
  const [active, setActive] = useState<string>("chest_pain");
  const [answers, setAnswers] = useState<string>(JSON.stringify({ severe_or_crushing: false, with_dyspnea: true, age_over_50: true }, null, 2));
  const [out, setOut] = useState<any | null>(null);
  useEffect(() => { nurseTriageProtocols(hospitalId).then(setProtocols).catch(() => {}); }, [hospitalId]);
  const run = async () => setOut(await nurseTriageEvaluate(hospitalId, active, JSON.parse(answers)));
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="grid grid-cols-2 gap-2">
          <select value={active} onChange={(e) => setActive(e.target.value)} className="px-3 py-1.5 border rounded text-sm">
            {protocols.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <button onClick={run} className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm">Evaluate</button>
        </div>
        <textarea value={answers} onChange={(e) => setAnswers(e.target.value)} rows={6} className="w-full mt-2 font-mono text-xs px-3 py-2 border rounded" />
      </div>
      {out && (
        <div className={`rounded-lg border p-4 ${out.disposition === "911" ? "bg-rose-50 border-rose-300" : out.disposition === "ed_now" ? "bg-amber-50 border-amber-300" : "bg-slate-50 border-slate-200"}`}>
          <div className="font-semibold">Disposition: {out.disposition}</div>
          <div className="text-sm">{out.reason}</div>
          {out.sla && <div className="text-xs text-slate-500 mt-1">SLA: {out.sla}</div>}
          {out.instructions && <div className="text-xs italic mt-2">{out.instructions}</div>}
        </div>
      )}
    </div>
  );
}

function TefcaPane({ hospitalId }: { hospitalId: string }) {
  const [name, setName] = useState("Jane Doe");
  const [dob, setDob] = useState("1985-03-21");
  const [out, setOut] = useState<any | null>(null);
  const run = async () => setOut(await tefcaQuery(hospitalId, name, dob));
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4 grid grid-cols-3 gap-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Patient name" className="px-3 py-1.5 border rounded text-sm" />
        <input value={dob} onChange={(e) => setDob(e.target.value)} placeholder="YYYY-MM-DD" className="px-3 py-1.5 border rounded text-sm" />
        <button onClick={run} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm">Query QHIN</button>
      </div>
      {out && <pre className="bg-white border border-slate-200 rounded-lg p-4 text-xs overflow-auto">{JSON.stringify(out, null, 2)}</pre>}
    </div>
  );
}

function TelehealthPane({ hospitalId }: { hospitalId: string }) {
  const [provider, setProvider] = useState<"doxy" | "zoom" | "teams" | "doximity">("doxy");
  const [extra, setExtra] = useState<string>('{ "clinician_handle": "drchen" }');
  const [out, setOut] = useState<any | null>(null);
  const run = async () => setOut(await telehealthSession(hospitalId, { provider, ...JSON.parse(extra || "{}") }));
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="grid grid-cols-2 gap-2">
          <select value={provider} onChange={(e) => setProvider(e.target.value as any)} className="px-3 py-1.5 border rounded text-sm">
            <option value="doxy">Doxy.me</option>
            <option value="zoom">Zoom</option>
            <option value="teams">Microsoft Teams</option>
            <option value="doximity">Doximity Dialer</option>
          </select>
          <button onClick={run} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm">Make session</button>
        </div>
        <textarea value={extra} onChange={(e) => setExtra(e.target.value)} rows={3} className="w-full mt-2 font-mono text-xs px-3 py-2 border rounded" placeholder='{"clinician_handle":"drchen"} or {"pmi":"1234567890"} etc.' />
      </div>
      {out && (
        <div className="bg-white border border-slate-200 rounded-lg p-4 text-sm">
          <div>Provider: <b>{out.provider}</b></div>
          {out.url && <div className="mt-1">Link: <a href={out.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{out.url}</a></div>}
          {out.patient_message && <div className="mt-1 text-xs italic">{out.patient_message}</div>}
        </div>
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
  const run = async () => setOut(await hl7MdmRender(hospitalId, body));
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <textarea value={JSON.stringify(body, null, 2)} onChange={(e) => { try { setBody(JSON.parse(e.target.value)); } catch {} }} rows={10} className="w-full font-mono text-xs px-3 py-2 border rounded" />
        <button onClick={run} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm">Render MDM^T02</button>
      </div>
      {out && (
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">HL7 v2 message (pipe-delimited, CR-separated)</div>
          <pre className="bg-slate-900 text-slate-100 text-xs rounded p-3 overflow-auto whitespace-pre-wrap">{out.hl7_message}</pre>
          <div className="text-xs text-slate-500 mt-2">Send via MLLP TCP to your Mirth/Rhapsody listener — port 6661 by default.</div>
        </div>
      )}
    </div>
  );
}
