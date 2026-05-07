import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BookOpen, Activity, Coins, Users2, AlertCircle, Loader2, Search } from "lucide-react";
import { evidenceAnswer, sepsisEws, deteriorationIndex, hccEvaluate, handoffIpass, handoffSbar, resultLoopOverdue } from "../lib/api";

type Tab = "evidence" | "ews" | "hcc" | "handoff" | "loops";

export default function ClinicianTools() {
  const { hospitalId = "demo" } = useParams();
  const [tab, setTab] = useState<Tab>("evidence");

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to={`/${hospitalId}/clinician`} className="text-slate-500 hover:text-slate-900"><ArrowLeft className="w-5 h-5" /></Link>
          <div>
            <div className="text-sm text-slate-500">Solace clinical decision support</div>
            <div className="font-semibold">Evidence, early warning, HCC, handoff, loop closure</div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {[
            { key: "evidence", label: "Evidence", icon: BookOpen },
            { key: "ews", label: "Early warning", icon: Activity },
            { key: "hcc", label: "HCC capture", icon: Coins },
            { key: "handoff", label: "Handoff", icon: Users2 },
            { key: "loops", label: "Open loops", icon: AlertCircle },
          ].map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setTab(key as Tab)} className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 -mb-px ${tab === key ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-900"}`}>
              <Icon className="w-4 h-4" />{label}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-5xl mx-auto p-4">
        {tab === "evidence" && <EvidencePane hospitalId={hospitalId} />}
        {tab === "ews" && <EwsPane hospitalId={hospitalId} />}
        {tab === "hcc" && <HccPane hospitalId={hospitalId} />}
        {tab === "handoff" && <HandoffPane hospitalId={hospitalId} />}
        {tab === "loops" && <LoopsPane hospitalId={hospitalId} />}
      </div>
    </div>
  );
}

function EvidencePane({ hospitalId }: { hospitalId: string }) {
  const [q, setQ] = useState("Best initial workup for chest pain in adults?");
  const [out, setOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setOut(await evidenceAnswer(hospitalId, q)); } finally { setBusy(false); } };

  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <label className="text-xs text-slate-500">Clinical question</label>
        <div className="flex gap-2 mt-1">
          <input value={q} onChange={(e) => setQ(e.target.value)} className="flex-1 px-3 py-2 border rounded text-sm" />
          <button onClick={run} disabled={busy} className="bg-blue-600 text-white px-4 py-2 rounded text-sm flex items-center gap-1">{busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />} Ask</button>
        </div>
      </div>
      {out && (
        <>
          <div className="bg-white rounded-lg border border-slate-200 p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Synthesis</div>
            <div className="whitespace-pre-wrap text-sm">{out.answer}</div>
            {out.key_recommendations?.length > 0 && (
              <div className="mt-3">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Key recommendations</div>
                {out.key_recommendations.map((r: string, i: number) => <div key={i} className="text-sm">- {r}</div>)}
              </div>
            )}
            {out.uncertainty && <div className="text-xs text-amber-700 mt-2">Uncertainty: {out.uncertainty}</div>}
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Evidence snippets</div>
            {out.snippets.map((s: any) => (
              <div key={s.index} className="border-b border-slate-100 py-2">
                <div className="font-semibold text-sm">[{s.index}] {s.title}</div>
                <div className="text-xs text-slate-500">{s.source} · {s.year} · score {s.score}</div>
                <div className="text-sm mt-1">{s.body}</div>
                <a href={s.url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 hover:underline">{s.url}</a>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function EwsPane({ hospitalId }: { hospitalId: string }) {
  const [v, setV] = useState({ hr: 124, rr: 26, temp_c: 39.2, sbp: 92, mental_status: "confused", spo2: 92, on_oxygen: true, wbc: 18, lactate: 3.2, suspected_infection: true });
  const [out, setOut] = useState<any | null>(null);
  const [d] = useState({
    vitals_now: { hr: 130, rr: 26, sbp: 88, spo2: 91, temp_c: 39.2 },
    vitals_4h_ago: { hr: 105, rr: 18, sbp: 118, spo2: 96, temp_c: 38.0 },
    new_oxygen_requirement: true,
    gcs_drop_at_least_2: false,
    new_arrhythmia: false,
  });
  const [dout, setDout] = useState<any | null>(null);

  const run = async () => setOut(await sepsisEws(hospitalId, v));
  const runD = async () => setDout(await deteriorationIndex(hospitalId, d));

  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Sepsis EWS inputs</div>
        <div className="grid grid-cols-3 gap-2 text-sm">
          {(["hr","rr","temp_c","sbp","spo2","wbc","lactate"] as const).map(k => (
            <label key={k} className="block"><span className="text-xs text-slate-500">{k}</span>
              <input type="number" value={(v as any)[k] ?? ""} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} className="w-full px-2 py-1 border rounded" />
            </label>
          ))}
          <label className="block"><span className="text-xs text-slate-500">mental_status</span>
            <input value={v.mental_status} onChange={(e) => setV({ ...v, mental_status: e.target.value })} className="w-full px-2 py-1 border rounded" />
          </label>
          <label className="block"><span className="text-xs text-slate-500">on_oxygen</span>
            <input type="checkbox" checked={v.on_oxygen} onChange={(e) => setV({ ...v, on_oxygen: e.target.checked })} />
          </label>
          <label className="block"><span className="text-xs text-slate-500">suspected_infection</span>
            <input type="checkbox" checked={v.suspected_infection} onChange={(e) => setV({ ...v, suspected_infection: e.target.checked })} />
          </label>
        </div>
        <button onClick={run} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm">Run sepsis EWS</button>
      </div>
      {out && (
        <div className={`rounded-lg border p-4 ${out.band === "critical" ? "bg-rose-50 border-rose-300" : out.band === "high" ? "bg-amber-50 border-amber-300" : "bg-slate-50 border-slate-200"}`}>
          <div className="font-semibold">EWS {out.score} ({out.band})</div>
          <div className="text-sm mt-1">{out.action}</div>
          <div className="mt-3 text-xs">
            {out.contributions.map((c: any, i: number) => <div key={i}>+{c.points} {c.feature}: {c.why}</div>)}
          </div>
          <div className="text-xs italic mt-2 text-slate-500">{out.calibration_note}</div>
        </div>
      )}

      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Deterioration index — 4h trend</div>
        <pre className="text-xs bg-slate-50 rounded p-2 overflow-auto">{JSON.stringify(d, null, 2)}</pre>
        <button onClick={runD} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm">Run deterioration index</button>
        {dout && (
          <div className={`mt-3 rounded p-3 ${dout.band === "critical" ? "bg-rose-50" : dout.band === "high" ? "bg-amber-50" : "bg-slate-50"}`}>
            <div className="font-semibold">DI {dout.score} ({dout.band})</div>
            <div className="text-sm">{dout.action}</div>
            <div className="text-xs mt-2">{dout.contributions.map((c: any, i: number) => <div key={i}>+{c.points} {c.feature}: {c.why}</div>)}</div>
          </div>
        )}
      </div>
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
    try { setOut(await hccEvaluate(hospitalId, { conditions: JSON.parse(conds), prior_notes: [notes] })); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <label className="text-xs text-slate-500">Active problem list (JSON)</label>
        <textarea value={conds} onChange={(e) => setConds(e.target.value)} rows={6} className="w-full font-mono text-xs px-3 py-2 border rounded" />
        <label className="text-xs text-slate-500 mt-2 block">Prior notes (free text)</label>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="w-full text-xs px-3 py-2 border rounded" />
        <button onClick={run} disabled={busy} className="mt-2 bg-blue-600 text-white px-4 py-1.5 rounded text-sm">{busy ? "..." : "Evaluate HCCs"}</button>
      </div>
      {out && (
        <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
          <div className="text-xs text-slate-500">RAF total: <b className="text-base text-slate-900">{out.raf_total}</b></div>
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Documented HCCs ({out.documented_hccs.length})</div>
            {out.documented_hccs.map((h: any, i: number) => (
              <div key={i} className="text-sm border-b border-slate-100 py-1">
                {h.hcc_code} · {h.description} · RAF {h.raf} · last {h.last_documented_year}
                {h.needs_recapture && <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-900">needs recapture</span>}
              </div>
            ))}
          </div>
          {out.suspected_undocumented?.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Suspected undocumented (from prior notes)</div>
              {out.suspected_undocumented.map((s: any, i: number) => (
                <div key={i} className="text-sm border-b border-slate-100 py-1">
                  <span className="font-medium">{s.icd10}</span> · {s.display}
                  <div className="text-xs italic text-slate-500">"{s.evidence_quote}"</div>
                </div>
              ))}
            </div>
          )}
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">MEAT checklist for documentation</div>
            {out.meat_checklist.map((m: string, i: number) => <div key={i} className="text-xs">- {m}</div>)}
          </div>
        </div>
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
  const [specialty, setSpecialty] = useState("nephrology");
  const [reason, setReason] = useState("AKI on CKD3b unresponsive to fluids");

  const runI = async () => setIout(await handoffIpass(hospitalId, JSON.parse(chart)));
  const runS = async () => setSout(await handoffSbar(hospitalId, JSON.parse(chart), specialty, reason));

  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <label className="text-xs text-slate-500">Chart context (JSON)</label>
        <textarea value={chart} onChange={(e) => setChart(e.target.value)} rows={8} className="w-full font-mono text-xs px-3 py-2 border rounded" />
        <div className="mt-2 flex flex-wrap gap-2">
          <button onClick={runI} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm">Generate I-PASS</button>
          <input value={specialty} onChange={(e) => setSpecialty(e.target.value)} className="px-2 py-1 border rounded text-sm" placeholder="consult specialty" />
          <input value={reason} onChange={(e) => setReason(e.target.value)} className="px-2 py-1 border rounded text-sm flex-1" placeholder="reason for consult" />
          <button onClick={runS} className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm">Generate SBAR</button>
        </div>
      </div>
      {iout && iout.available && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">I-PASS sign-out</div>
          <pre className="whitespace-pre-wrap font-serif text-sm">{iout.rendered_text}</pre>
        </div>
      )}
      {sout && sout.available && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">SBAR consult</div>
          <pre className="whitespace-pre-wrap font-serif text-sm">{sout.rendered_text}</pre>
        </div>
      )}
    </div>
  );
}

function LoopsPane({ hospitalId }: { hospitalId: string }) {
  const [items, setItems] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = async () => { setBusy(true); try { setItems(await resultLoopOverdue(hospitalId)); } finally { setBusy(false); } };
  useEffect(() => { refresh(); }, [hospitalId]);
  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="flex items-center justify-between">
          <div className="text-xs uppercase tracking-wide text-slate-500">Overdue abnormal results — closed-loop worklist</div>
          <button onClick={refresh} className="text-xs px-3 py-1 bg-slate-900 text-white rounded">{busy ? "..." : "Refresh"}</button>
        </div>
        {items === null && <div className="text-sm text-slate-500 mt-3">Loading...</div>}
        {items && items.length === 0 && (
          <div className="text-sm text-emerald-700 mt-3">No overdue loops. Every abnormal result has been acted on.</div>
        )}
        {items && items.length > 0 && (
          <div className="mt-3 space-y-2">
            {items.map((it) => (
              <div key={it.tracking_id} className="border border-amber-200 bg-amber-50 rounded p-3 text-sm">
                <div className="flex justify-between">
                  <div className="font-semibold">{it.test_name}: {it.value}</div>
                  <div className="text-xs">{it.severity} · {it.days_overdue}d overdue</div>
                </div>
                <div className="text-xs text-slate-600">patient {it.patient_id} · clinician {it.clinician_id} · opened {it.opened_at}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
