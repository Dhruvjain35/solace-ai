import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Mic, Square, Loader2, Sparkles, AlertTriangle, Activity, FileText, ClipboardCheck, Send, Hash, Check, X as XIcon } from "lucide-react";
import {
  scribeFromTranscript, ddxV2, calcAutoExtract, codingSuggest, drugCheck,
  buildDischarge, recordAiOverride, listSpecialtyPacks,
  type ScribeOutput, type DdxResult,
} from "../lib/api";

type Tab = "transcript" | "note" | "ddx" | "calculators" | "coding" | "discharge";

export default function ClinicianScribe() {
  const { hospitalId = "demo" } = useParams();
  const [recording, setRecording] = useState(false);
  const [audioStream, setAudioStream] = useState<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [transcript, setTranscript] = useState("");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [specialty, setSpecialty] = useState("ed");
  const [packs, setPacks] = useState<{ key: string; name: string }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [scribe, setScribe] = useState<ScribeOutput | null>(null);
  const [ddx, setDdx] = useState<DdxResult | null>(null);
  const [calcs, setCalcs] = useState<any[] | null>(null);
  const [coding, setCoding] = useState<any | null>(null);
  const [discharge, setDischarge] = useState<any | null>(null);
  const [drugAlerts, setDrugAlerts] = useState<any | null>(null);
  const [meds, setMeds] = useState("");
  const [allergies, setAllergies] = useState("");
  const [language, setLanguage] = useState("en");
  const [tab, setTab] = useState<Tab>("transcript");
  const [highlightedSegments, setHighlightedSegments] = useState<number[]>([]);

  useEffect(() => { listSpecialtyPacks(hospitalId).then(setPacks).catch(() => {}); }, [hospitalId]);

  // ---- Recording ----------------------------------------------------------
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setAudioStream(stream);
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const form = new FormData();
        form.append("file", blob, "encounter.webm");
        setBusy("Transcribing audio...");
        try {
          const r = await fetch(`/api/${hospitalId}/transcribe`, { method: "POST", body: form });
          const j = await r.json();
          if (j?.transcript) setTranscript((prev) => (prev ? prev + "\n" + j.transcript : j.transcript));
        } catch {}
        setBusy(null);
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
    } catch (e) {
      alert("Microphone permission required");
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    audioStream?.getTracks().forEach((t) => t.stop());
    setAudioStream(null);
    setRecording(false);
  };

  // ---- AI orchestration --------------------------------------------------
  const runAll = async () => {
    if (!transcript.trim()) return;
    setBusy("Generating clinical note...");
    setScribe(null); setDdx(null); setCalcs(null); setCoding(null); setDischarge(null); setDrugAlerts(null);
    try {
      const s = await scribeFromTranscript(hospitalId, transcript);
      setScribe(s);
      setBusy("Differential + calculators + coding...");
      const [d, c, code] = await Promise.all([
        ddxV2(hospitalId, { transcript, chief_complaint: chiefComplaint, specialty }),
        calcAutoExtract(hospitalId, transcript, chiefComplaint),
        codingSuggest(hospitalId, s.soap_text || transcript),
      ]);
      setDdx(d);
      setCalcs(c.calculators || []);
      setCoding(code);
      const medList = meds.split(",").map((x) => x.trim()).filter(Boolean);
      const allergyList = allergies.split(",").map((x) => x.trim()).filter(Boolean);
      if (medList.length > 0) {
        const da = await drugCheck(hospitalId, medList, allergyList, undefined, chiefComplaint);
        setDrugAlerts(da);
      }
      setTab("note");
    } catch (e: any) {
      alert("Run failed: " + (e?.message || "unknown"));
    } finally { setBusy(null); }
  };

  const buildDischargePlan = async () => {
    setBusy("Building patient-language discharge plan...");
    try {
      const d = await buildDischarge(hospitalId, {
        scribe_note: scribe?.soap_text || "",
        transcript,
        assessment: ddx?.differential?.[0]?.diagnosis || chiefComplaint,
        patient_language: language,
      });
      setDischarge(d);
      setTab("discharge");
    } finally { setBusy(null); }
  };

  const overrideDecision = async (purpose: string, decision: "accepted" | "edited" | "rejected") => {
    try { await recordAiOverride(hospitalId, { purpose, decision }); } catch {}
  };

  const tabs: { key: Tab; label: string; icon: any }[] = [
    { key: "transcript", label: "Capture", icon: Mic },
    { key: "note", label: "Note", icon: FileText },
    { key: "ddx", label: "Differential", icon: Sparkles },
    { key: "calculators", label: "CDS", icon: Activity },
    { key: "coding", label: "Coding", icon: Hash },
    { key: "discharge", label: "Discharge", icon: Send },
  ];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to={`/${hospitalId}/clinician`} className="text-slate-500 hover:text-slate-900">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1">
            <div className="text-sm text-slate-500">Solace ambient scribe</div>
            <div className="font-semibold">Encounter capture and AI assist</div>
          </div>
          <select
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
            className="px-3 py-1.5 rounded-md border border-slate-300 bg-white text-sm"
            title="Specialty pack"
          >
            {packs.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
          </select>
        </div>
        <div className="max-w-7xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 -mb-px ${tab === key ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-900"}`}
            >
              <Icon className="w-4 h-4" />{label}
            </button>
          ))}
        </div>
      </div>

      {busy && (
        <div className="bg-blue-50 border-b border-blue-200 px-4 py-2 flex items-center gap-2 text-sm text-blue-900">
          <Loader2 className="w-4 h-4 animate-spin" />{busy}
        </div>
      )}

      <div className="max-w-7xl mx-auto p-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left rail — context */}
        <div className="lg:col-span-1 space-y-3">
          <div className="bg-white rounded-lg border border-slate-200 p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Encounter context</div>
            <label className="block text-xs text-slate-600 mt-2">Chief complaint</label>
            <input value={chiefComplaint} onChange={(e) => setChiefComplaint(e.target.value)} placeholder="e.g. chest pain x 2h" className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm" />
            <label className="block text-xs text-slate-600 mt-3">Active medications (comma-sep)</label>
            <input value={meds} onChange={(e) => setMeds(e.target.value)} placeholder="aspirin, metoprolol, sildenafil" className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm" />
            <label className="block text-xs text-slate-600 mt-3">Allergies (comma-sep)</label>
            <input value={allergies} onChange={(e) => setAllergies(e.target.value)} placeholder="penicillin" className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm" />
            <label className="block text-xs text-slate-600 mt-3">Patient language</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm">
              {["en","es","zh","tl","vi","ar","fr","ko","ru","de","ht","pt","it","pl","ja","fa","ur","hi","bn","gu"].map(l => <option key={l} value={l}>{l}</option>)}
            </select>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {!recording ? (
                <button onClick={startRecording} className="col-span-2 flex items-center justify-center gap-2 bg-rose-600 text-white py-2 rounded-md font-medium hover:bg-rose-700">
                  <Mic className="w-4 h-4" /> Start recording
                </button>
              ) : (
                <button onClick={stopRecording} className="col-span-2 flex items-center justify-center gap-2 bg-slate-900 text-white py-2 rounded-md font-medium animate-pulse">
                  <Square className="w-4 h-4" /> Stop & transcribe
                </button>
              )}
              <button onClick={runAll} disabled={!transcript.trim() || !!busy} className="col-span-2 flex items-center justify-center gap-2 bg-blue-600 text-white py-2 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50">
                <Sparkles className="w-4 h-4" /> Run AI suite
              </button>
            </div>
          </div>

          {drugAlerts && (drugAlerts.drug_drug.length > 0 || drugAlerts.drug_allergy.length > 0) && (
            <div className="bg-amber-50 border border-amber-300 rounded-lg p-4">
              <div className="text-xs uppercase tracking-wide text-amber-900 font-medium mb-2 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Drug alerts
              </div>
              {drugAlerts.drug_drug.map((a: any, i: number) => (
                <div key={i} className="text-sm text-amber-900 mb-1">{a.a} + {a.b} — <span className="font-medium">{a.severity}</span>: {a.reason}</div>
              ))}
              {drugAlerts.drug_allergy.map((a: any, i: number) => (
                <div key={`al-${i}`} className="text-sm text-rose-900 mb-1">Allergy match: {a.med}</div>
              ))}
            </div>
          )}

          {ddx?.red_flags && ddx.red_flags.length > 0 && (
            <div className="bg-rose-50 border border-rose-300 rounded-lg p-4">
              <div className="text-xs uppercase tracking-wide text-rose-900 font-medium mb-2 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Don't-miss canon
              </div>
              {ddx.red_flags.map((r, i) => (
                <div key={i} className="text-sm text-rose-900">{r.diagnosis} ({r.icd10})</div>
              ))}
            </div>
          )}
        </div>

        {/* Main column */}
        <div className="lg:col-span-2 space-y-3">
          {tab === "transcript" && (
            <div className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Transcript</div>
              <textarea
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder="Hit Start recording, or paste a transcript here..."
                rows={20}
                className="w-full px-3 py-2 border border-slate-300 rounded-md font-mono text-sm leading-relaxed"
              />
            </div>
          )}

          {tab === "note" && scribe && (
            <div className="space-y-3">
              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Linked Evidence note</div>
                  <div className="flex gap-1">
                    <button onClick={() => overrideDecision("scribe", "accepted")} className="text-xs px-2 py-1 bg-emerald-100 text-emerald-900 rounded flex items-center gap-1"><Check className="w-3 h-3" /> Accept</button>
                    <button onClick={() => overrideDecision("scribe", "rejected")} className="text-xs px-2 py-1 bg-rose-100 text-rose-900 rounded flex items-center gap-1"><XIcon className="w-3 h-3" /> Reject</button>
                  </div>
                </div>
                {scribe.structured.sections.map((sec) => (
                  <div key={sec.name} className="mb-3">
                    <div className="text-sm font-semibold text-slate-700">{sec.name.replace(/_/g, " ")}</div>
                    {sec.summary.map((entry, i) => (
                      <div
                        key={i}
                        className="text-sm text-slate-900 mt-1 cursor-pointer hover:bg-yellow-50 rounded px-1"
                        onMouseEnter={() => setHighlightedSegments(entry.evidence_segments)}
                        onMouseLeave={() => setHighlightedSegments([])}
                      >
                        - {entry.text} {entry.evidence_segments.length > 0 && (
                          <span className="text-xs text-slate-400 ml-1">[{entry.evidence_segments.join(",")}]</span>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Conversation segments</div>
                <div className="text-sm space-y-1 max-h-64 overflow-auto">
                  {scribe.structured.transcript_segments.map((s) => (
                    <div
                      key={s.id}
                      className={`px-2 py-1 rounded ${highlightedSegments.includes(s.id) ? "bg-yellow-200" : ""}`}
                    >
                      <span className="text-xs text-slate-500 mr-2">{s.speaker}</span>
                      <span>{s.content}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {tab === "ddx" && ddx && (
            <div className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Ranked differential (conformal sets)</div>
              <div className="text-xs text-slate-600 mb-3">
                90% set: {ddx.conformal.set_90.join(" | ") || "—"}<br />
                95% set: {ddx.conformal.set_95.join(" | ") || "—"}
              </div>
              {ddx.differential.map((d, i) => (
                <div key={i} className={`border rounded-md p-3 mb-2 ${d.must_not_miss ? "border-rose-300 bg-rose-50" : "border-slate-200"}`}>
                  <div className="flex items-center justify-between">
                    <div className="font-semibold">{i + 1}. {d.diagnosis} <span className="text-xs text-slate-500">{d.icd10}</span></div>
                    <div className="text-xs text-slate-600">w={d.weight.toFixed(2)}</div>
                  </div>
                  <div className="text-xs mt-1"><span className="font-medium">Rule in:</span> {d.rule_in.join(", ")}</div>
                  {d.rule_out.length > 0 && <div className="text-xs"><span className="font-medium">Rule out:</span> {d.rule_out.join(", ")}</div>}
                  {d.next_step && <div className="text-xs mt-1 text-blue-900"><span className="font-medium">Next step:</span> {d.next_step}</div>}
                  {d.evidence_quote && <div className="text-xs italic text-slate-600 mt-1">"{d.evidence_quote}"</div>}
                </div>
              ))}
              {ddx.counterfactuals.length > 0 && (
                <div className="mt-4">
                  <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Counterfactuals</div>
                  {ddx.counterfactuals.map((c, i) => (
                    <div key={i} className="text-xs text-slate-700">If {c.if_true} → {c.would_change}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "calculators" && calcs && (
            <div className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Auto-extracted CDS calculators</div>
              {calcs.length === 0 && <div className="text-sm text-slate-500">No calculators relevant to this complaint.</div>}
              {calcs.map((c, i) => (
                <div key={i} className="border border-slate-200 rounded-md p-3 mb-2">
                  <div className="font-semibold text-sm">{c.name}</div>
                  {c.unknown && c.unknown.length > 0 ? (
                    <div className="text-xs text-amber-700 mt-1">Need: {c.unknown.join(", ")}</div>
                  ) : (
                    <pre className="text-xs text-slate-700 mt-1 whitespace-pre-wrap">{JSON.stringify(c.result, null, 2)}</pre>
                  )}
                </div>
              ))}
            </div>
          )}

          {tab === "coding" && coding && (
            <div className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">E&M + ICD-10 + CPT suggestions</div>
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="border border-slate-200 rounded p-3">
                  <div className="text-xs text-slate-500">E&M primary</div>
                  <div className="font-bold text-lg">{coding.em_primary?.code} <span className="text-sm font-normal text-slate-500">({coding.em_primary?.mdm})</span></div>
                </div>
                <div className="border border-slate-200 rounded p-3">
                  <div className="text-xs text-slate-500">Alternate</div>
                  <div className="font-bold text-lg">{coding.em_alternate?.code}</div>
                </div>
              </div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mt-3 mb-1">ICD-10 candidates</div>
              {(coding.icd10 || []).map((d: any, i: number) => (
                <div key={i} className="text-sm flex justify-between border-b border-slate-100 py-1">
                  <span>{d.code} — {d.name}</span>
                  <span className="text-xs text-slate-500">{d.support}</span>
                </div>
              ))}
              {(coding.cpt_procedures || []).length > 0 && (
                <>
                  <div className="text-xs uppercase tracking-wide text-slate-500 mt-3 mb-1">CPT procedures</div>
                  {coding.cpt_procedures.map((d: any, i: number) => (
                    <div key={i} className="text-sm flex justify-between border-b border-slate-100 py-1">
                      <span>{d.code} — {d.name}</span>
                      <span className="text-xs text-slate-500">{d.support}</span>
                    </div>
                  ))}
                </>
              )}
              {(coding.modifiers || []).length > 0 && (
                <div className="text-xs text-amber-800 mt-2">Modifiers to consider: {coding.modifiers.map((m: any) => `${m.modifier} (${m.reason})`).join(" | ")}</div>
              )}
            </div>
          )}

          {tab === "discharge" && (
            <div className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">Multi-language patient discharge plan</div>
                <button onClick={buildDischargePlan} disabled={!transcript.trim()} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded">
                  <ClipboardCheck className="w-3 h-3 inline mr-1" /> Build plan
                </button>
              </div>
              {discharge && (
                <div className="space-y-2 text-sm">
                  <div className="text-xs text-slate-500">Language: {discharge.language}</div>
                  {discharge.summary?.headline && <div><span className="font-semibold">Headline:</span> {discharge.summary.headline}</div>}
                  {discharge.summary?.what_we_are_doing && <div><span className="font-semibold">Plan:</span> {discharge.summary.what_we_are_doing}</div>}
                  {discharge.red_flags?.length > 0 && (
                    <div className="bg-rose-50 border border-rose-200 rounded p-2">
                      <div className="text-xs font-semibold text-rose-900 mb-1">Return precautions</div>
                      {discharge.red_flags.map((r: string, i: number) => <div key={i} className="text-xs text-rose-900">- {r}</div>)}
                    </div>
                  )}
                  {discharge.sms_body && (
                    <div className="bg-slate-100 rounded p-2">
                      <div className="text-xs text-slate-500 mb-1">SMS body ({discharge.sms_body.length} chars)</div>
                      <div className="text-xs">{discharge.sms_body}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
