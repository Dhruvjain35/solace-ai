import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Mic, Square, Loader2, Sparkles, AlertTriangle, Activity, FileText, ClipboardCheck, Send, Hash, Check, X as XIcon, Upload, User } from "lucide-react";
import {
  scribeFromTranscript, ddxV2, calcAutoExtract, codingSuggest, drugCheck,
  buildDischarge, recordAiOverride, listSpecialtyPacks,
  getPatientDetail, createNote, ehrWrite,
  type ScribeOutput, type DdxResult, type EhrWriteResult,
} from "../lib/api";
import type { PatientDetail } from "../types";

type Tab = "transcript" | "note" | "ddx" | "calculators" | "coding" | "discharge";

export default function ClinicianScribe() {
  const { hospitalId = "demo", patientId } = useParams<{ hospitalId?: string; patientId?: string }>();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
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
  const [ehrResult, setEhrResult] = useState<EhrWriteResult | null>(null);
  const [ehrError, setEhrError] = useState<string | null>(null);
  const [savedToChart, setSavedToChart] = useState(false);
  // Inline error banner state — replaces native browser alert() so errors are
  // dismissable, themed, and don't break the doctor's flow.
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => { listSpecialtyPacks(hospitalId).then(setPacks).catch(() => {}); }, [hospitalId]);

  // Patient-bound mode: pre-fill encounter context from the patient's existing record.
  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    getPatientDetail(hospitalId, patientId).then((p) => {
      if (cancelled) return;
      setPatient(p);
      // Use clinician_prebrief as a CC hint (it's typically a one-liner)
      if (p.clinician_prebrief) setChiefComplaint(p.clinician_prebrief.slice(0, 160));
      const m = (p.medical_info?.medications || []).filter((x) => x.toLowerCase() !== "none");
      if (m.length) setMeds(m.join(", "));
      const a = (p.medical_info?.allergies || []).filter((x) => x.toLowerCase() !== "none");
      if (a.length) setAllergies(a.join(", "));
      if (p.language) setLanguage(p.language);
      // Seed the transcript with the patient's intake transcript so the doctor
      // can run AI suite immediately, even before recording bedside dialogue.
      if (p.transcript && !transcript) setTranscript(p.transcript);
    }).catch(() => {});
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId, hospitalId]);

  // ---- Recording ----------------------------------------------------------
  // Hold the in-flight Web Speech recognizer. Final results are accumulated in
  // a ref so the textarea reflects the live transcript without re-renders per
  // interim chunk. The MediaRecorder remains as the deterministic fallback —
  // when Web Speech captures text, we skip the server /transcribe call.
  const speechRecRef = useRef<any>(null);
  const speechFinalsRef = useRef<string>("");
  const usedWebSpeechRef = useRef<boolean>(false);
  // Snapshot of the transcript before the current recording session began.
  // We re-render as `preRecordingText + live` on every interim chunk so the
  // textarea grows monotonically instead of duplicating.
  const preRecordingRef = useRef<string>("");

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setAudioStream(stream);
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        // If Web Speech captured the encounter live, transcript was already
        // updated on each interim chunk — skip the server round-trip.
        if (usedWebSpeechRef.current && speechFinalsRef.current.trim().length > 0) {
          return;
        }
        // Otherwise fall back to AWS Transcribe via /transcribe.
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const form = new FormData();
        // Backend expects field name "audio_file" + a consent flag (HIPAA §164.508).
        // Clinician context implies covered-entity consent — pass it explicitly so
        // the patient-intake consent gate doesn't reject the upload.
        form.append("audio_file", blob, "encounter.webm");
        form.append("consent_granted", "true");
        form.append("preferred_language", "en");
        setBusy("Transcribing audio...");
        try {
          const r = await fetch(`/api/${hospitalId}/transcribe`, { method: "POST", body: form });
          const j = await r.json();
          if (j?.transcript) setTranscript((prev) => (prev ? prev + "\n" + j.transcript : j.transcript));
          else if (j?.detail) setErrorMsg(humanizeError(j.detail));
        } catch (e: any) {
          setErrorMsg(humanizeError(e?.message || "network error"));
        }
        setBusy(null);
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);

      // Spin up Web Speech in parallel — instant transcription with no cloud
      // round-trip. On browsers without support (older Firefox), this falls
      // straight through to the MediaRecorder path on stop().
      usedWebSpeechRef.current = false;
      speechFinalsRef.current = "";
      preRecordingRef.current = transcript;
      const SpeechCtor: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechCtor) {
        try {
          const sr = new SpeechCtor();
          sr.continuous = true;
          sr.interimResults = true;
          sr.lang = "en-US";
          sr.onresult = (e: any) => {
            usedWebSpeechRef.current = true;
            let interim = "";
            for (let i = e.resultIndex; i < e.results.length; i++) {
              const seg = e.results[i];
              const txt = seg[0]?.transcript || "";
              if (seg.isFinal) speechFinalsRef.current += txt;
              else interim += txt;
            }
            // Live preview in the textarea so doctor sees text as they speak.
            const live = (speechFinalsRef.current + " " + interim).trim();
            const base = preRecordingRef.current;
            setTranscript(base ? base + "\n" + live : live);
          };
          sr.onerror = () => { /* swallow — server fallback handles it */ };
          sr.onend = () => { /* no-op */ };
          speechRecRef.current = sr;
          sr.start();
        } catch {
          speechRecRef.current = null;
        }
      }
    } catch (e) {
      setErrorMsg("Microphone access is blocked. Allow it in your browser to use voice capture.");
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    try { speechRecRef.current?.stop(); } catch { /* ignore */ }
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
      setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "unknown"));
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

  // Save the current scribe note to the patient's chart (Solace internal notes table).
  // Distinct from "Push to EHR" — that's external FHIR write-back.
  const saveToChart = async () => {
    if (!patientId || !scribe?.soap_text) return;
    setBusy("Saving to chart...");
    try {
      await createNote(hospitalId, patientId, scribe.soap_text, "Scribe AI draft");
      setSavedToChart(true);
    } catch (e: any) {
      setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "unknown"));
    } finally { setBusy(null); }
  };

  // External FHIR write-back: DocumentReference (the note) + Conditions (from ICD-10
  // coding) + Allergies (from the allergy input). Routes through the local FHIR mock
  // store when no FHIR_BASE_URL is configured, so the demo end-to-end always works.
  const pushToEhr = async () => {
    if (!scribe?.soap_text) return;
    const patientRef = patientId ? `Patient/${patientId}` : "Patient/encounter";
    const conditions = (coding?.icd10 || [])
      .slice(0, 5)
      .map((d: any) => ({ icd10: d.code, display: d.name }));
    const allergyList = allergies
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean)
      .map((substance) => ({ substance }));
    setBusy("Pushing to EHR (FHIR)...");
    setEhrError(null);
    setEhrResult(null);
    try {
      const r = await ehrWrite(hospitalId, {
        patient_ref: patientRef,
        note_text: scribe.soap_text,
        conditions,
        allergies: allergyList,
      });
      setEhrResult(r);
      await overrideDecision("ehr_write", "accepted");
    } catch (e: any) {
      setEhrError(e?.response?.data?.detail || e?.message || "EHR write failed");
    } finally { setBusy(null); }
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
          <Link
            to={patientId ? `/${hospitalId}/clinician/patient/${patientId}` : `/${hospitalId}/clinician`}
            className="text-slate-500 hover:text-slate-900"
            title={patientId ? "Back to patient" : "Back to dashboard"}
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1 min-w-0">
            <div className="text-sm text-slate-500">Solace ambient scribe</div>
            {patient ? (
              <div className="flex items-center gap-2 font-semibold truncate">
                <User className="w-4 h-4 text-slate-400 shrink-0" />
                <span className="truncate">{patient.name}</span>
                <span className="text-xs text-slate-500 font-normal">
                  ESI {patient.refined_esi_level || patient.esi_level} · waited {patient.waited_minutes}m · {patient.language?.toUpperCase()}
                </span>
              </div>
            ) : (
              <div className="font-semibold">Encounter capture and AI assist</div>
            )}
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
      {errorMsg && (
        <div className="bg-rose-50 border-b border-rose-200 px-4 py-2 flex items-start gap-2 text-sm text-rose-900">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div className="flex-1">{errorMsg}</div>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            className="text-rose-700/70 hover:text-rose-900 text-xs font-semibold uppercase tracking-wide"
          >
            Dismiss
          </button>
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
                <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Linked Evidence note</div>
                  <div className="flex gap-1 flex-wrap">
                    <button onClick={() => overrideDecision("scribe", "accepted")} className="text-xs px-2 py-1 bg-emerald-100 text-emerald-900 rounded flex items-center gap-1"><Check className="w-3 h-3" /> Accept</button>
                    <button onClick={() => overrideDecision("scribe", "rejected")} className="text-xs px-2 py-1 bg-rose-100 text-rose-900 rounded flex items-center gap-1"><XIcon className="w-3 h-3" /> Reject</button>
                    {patientId && (
                      <button
                        onClick={saveToChart}
                        disabled={!!busy || savedToChart}
                        className="text-xs px-2 py-1 bg-slate-100 text-slate-900 rounded flex items-center gap-1 disabled:opacity-50"
                        title="Save the SOAP note to this patient's chart"
                      >
                        <FileText className="w-3 h-3" /> {savedToChart ? "Saved" : "Save to chart"}
                      </button>
                    )}
                    <button
                      onClick={pushToEhr}
                      disabled={!!busy}
                      className="text-xs px-2 py-1 bg-blue-600 text-white rounded flex items-center gap-1 disabled:opacity-50"
                      title="Write DocumentReference + Conditions + Allergies to the EHR over FHIR"
                    >
                      <Upload className="w-3 h-3" /> Push to EHR
                    </button>
                  </div>
                </div>
                {ehrResult && (
                  <div className="mb-3 rounded-md border border-emerald-300 bg-emerald-50 p-3">
                    <div className="flex items-center gap-1.5 text-sm font-semibold text-emerald-900">
                      <Check className="w-4 h-4" /> Sent to the patient's chart
                    </div>
                    <div className="mt-1 text-xs text-emerald-900/85">
                      {summarizeEhrWrite(ehrResult.writes)}
                    </div>
                  </div>
                )}
                {ehrError && (
                  <div className="mb-3 rounded-md border border-rose-300 bg-rose-50 p-2 text-xs text-rose-900">
                    Couldn't send to the chart: {humanizeError(ehrError)}
                  </div>
                )}
                {scribe.structured.sections.map((sec) => (
                  <div key={sec.name} className="mb-3">
                    <div className="text-sm font-semibold text-slate-700 capitalize">
                      {sec.name.replace(/_/g, " ").toLowerCase()}
                    </div>
                    {sec.summary.map((entry, i) => (
                      <div
                        key={i}
                        className="text-sm text-slate-900 mt-1 cursor-pointer hover:bg-yellow-50 rounded px-1.5 py-0.5 transition-colors"
                        onMouseEnter={() => setHighlightedSegments(entry.evidence_segments)}
                        onMouseLeave={() => setHighlightedSegments([])}
                        title={entry.evidence_segments.length > 0 ? "Hover to see source in conversation" : undefined}
                      >
                        {entry.text}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Source conversation</div>
                <div className="text-sm space-y-1 max-h-64 overflow-auto">
                  {scribe.structured.transcript_segments.map((s) => {
                    const isHL = highlightedSegments.includes(s.id);
                    const speakerLabel = s.speaker?.toLowerCase().includes("clinic") ? "Clinician" : "Patient";
                    return (
                      <div
                        key={s.id}
                        className={`px-2 py-1 rounded transition-colors ${isHL ? "bg-yellow-200" : ""}`}
                      >
                        <span className={`text-xs font-medium mr-2 ${speakerLabel === "Clinician" ? "text-blue-700" : "text-emerald-700"}`}>
                          {speakerLabel}:
                        </span>
                        <span className="text-slate-900">{s.content}</span>
                      </div>
                    );
                  })}
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
              {ddx.differential.map((d, i) => {
                const pct = Math.round((d.weight || 0) * 100);
                return (
                  <div key={i} className={`border rounded-md p-3 mb-2 ${d.must_not_miss ? "border-rose-300 bg-rose-50" : "border-slate-200"}`}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-semibold text-slate-900">
                        {i + 1}. {d.diagnosis}
                        {d.icd10 && <span className="ml-2 text-[11px] font-mono text-slate-400">{d.icd10}</span>}
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <div className="w-16 h-1.5 rounded bg-slate-200 overflow-hidden">
                          <div className="h-full bg-blue-500" style={{ width: `${Math.min(100, pct)}%` }} />
                        </div>
                        <div className="text-xs font-medium text-slate-600 w-9 text-right">{pct}%</div>
                      </div>
                    </div>
                    {d.rule_in.length > 0 && <div className="text-xs mt-1.5 text-slate-700"><span className="font-medium">Supports:</span> {d.rule_in.join(", ")}</div>}
                    {d.rule_out.length > 0 && <div className="text-xs text-slate-700"><span className="font-medium">Against:</span> {d.rule_out.join(", ")}</div>}
                    {d.next_step && <div className="text-xs mt-1 text-blue-900"><span className="font-medium">Next step:</span> {d.next_step}</div>}
                    {d.evidence_quote && <div className="text-xs italic text-slate-500 mt-1">"{d.evidence_quote}"</div>}
                  </div>
                );
              })}
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
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Clinical decision support</div>
              {calcs.length === 0 && (
                <div className="text-sm text-slate-500">No relevant calculators for this complaint.</div>
              )}
              {calcs.map((c, i) => (
                <div key={i} className="border border-slate-200 rounded-md p-3 mb-2">
                  <div className="font-semibold text-sm text-slate-900">{c.name}</div>
                  {c.unknown && c.unknown.length > 0 ? (
                    <div className="text-xs text-amber-700 mt-1.5">
                      <span className="font-medium">Need to compute:</span> {c.unknown.join(", ")}
                    </div>
                  ) : (
                    <CalculatorResult result={c.result} />
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

// ---------------------------------------------------------------------------------
// Small UI helpers — kept inline so the scribe page stays self-contained.
// ---------------------------------------------------------------------------------

/** Turn a backend / network error string into something a clinician can read. */
function humanizeError(raw: string): string {
  if (!raw) return "Something went wrong. Please try again.";
  const s = String(raw);
  if (/network|fetch|abort|timeout/i.test(s)) return "Network connection lost. Please check your connection and retry.";
  if (/rate.?limit|too many requests|429/i.test(s)) return "Too many requests in a row. Please wait a moment and try again.";
  if (/Consent required/i.test(s)) return "Patient consent is required before voice or AI processing.";
  if (/empty transcript|returned empty/i.test(s)) return "No speech detected. Try recording again in a quieter environment.";
  if (/permission/i.test(s)) return s; // already user-friendly
  if (s.length > 220) return "The system couldn't complete that request. Please try again.";
  // Fall through with the backend's message — the routers raise human-readable
  // HTTPException detail strings by convention (see CONSTITUTION QUAL-003).
  return s;
}

/** Render a CDS calculator's result dict as labeled rows instead of raw JSON. */
function CalculatorResult({ result }: { result: any }) {
  if (result === null || result === undefined) {
    return <div className="text-xs text-slate-500 mt-1">No result available.</div>;
  }
  if (typeof result !== "object") {
    return <div className="text-sm text-slate-900 mt-1">{String(result)}</div>;
  }
  const entries = Object.entries(result).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (entries.length === 0) {
    return <div className="text-xs text-slate-500 mt-1">No result available.</div>;
  }
  return (
    <dl className="mt-1.5 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
      {entries.map(([k, v]) => (
        <Fragment key={k}>
          <dt className="text-slate-500 capitalize">{k.replace(/_/g, " ")}:</dt>
          <dd className="text-slate-900 font-medium">{renderCalcValue(v)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** Turn a list of FHIR write results into one clinician-friendly summary line. */
function summarizeEhrWrite(writes: EhrWriteResult["writes"]): string {
  const counts: Record<string, number> = {};
  for (const w of writes) {
    const key =
      w.resource === "DocumentReference" ? "clinical note" :
      w.resource === "Condition" ? "diagnosis" :
      w.resource === "AllergyIntolerance" ? "allergy" :
      w.resource.startsWith("Observation") ? "observation" :
      w.resource === "Immunization" ? "immunization" :
      w.resource.toLowerCase();
    counts[key] = (counts[key] || 0) + 1;
  }
  return Object.entries(counts)
    .map(([k, n]) => (n === 1 ? `1 ${k}` : `${n} ${k}s`))
    .join(", ");
}

function renderCalcValue(v: any): string {
  if (Array.isArray(v)) return v.join(", ") || "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "object" && v !== null) {
    return Object.entries(v).map(([k, val]) => `${k}: ${val}`).join(", ");
  }
  return String(v);
}
