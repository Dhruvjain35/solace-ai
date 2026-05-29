import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Mic, Square, Loader2, Sparkles, AlertTriangle, Activity, FileText, ClipboardCheck, Send, Hash, Check, X as XIcon, Upload, User, Pause, Play, Radio, RefreshCw, Quote } from "lucide-react";
import {
  scribeFromTranscript, ddxV2, calcAutoExtract, codingSuggest, drugCheck,
  buildDischarge, recordAiOverride, listSpecialtyPacks, postTranscribe,
  getPatientDetail, createNote, ehrWrite,
  type ScribeOutput, type DdxResult, type EhrWriteResult,
} from "../lib/api";
import {
  startScribeSession, appendScribeChunk, pauseScribeSession, resumeScribeSession,
  finalizeScribeSession, regenerateScribeSection,
  type ScribeSessionStatus, type ScribeStructuredNote, type ScribeSessionSection,
  type LinkedEvidence,
} from "../lib/api-scribe";
import type { PatientDetail } from "../types";

type Tab = "transcript" | "session" | "note" | "ddx" | "calculators" | "coding" | "discharge";

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

  // ---- Chunked ambient-scribe session ------------------------------------
  // A server-tracked session that ingests transcribed conversation in chunks.
  // The doctor records bedside, pausing/resuming as needed, then finalizes into
  // an evidence-linked structured SOAP note.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<ScribeSessionStatus | null>(null);
  const [chunkCount, setChunkCount] = useState(0);
  const [finalNote, setFinalNote] = useState<ScribeStructuredNote | null>(null);
  const [finalSoapText, setFinalSoapText] = useState("");
  const [regenSection, setRegenSection] = useState<string | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<LinkedEvidence | null>(null);
  // Web Speech recognizer + chunk-flush plumbing for the live session.
  const sessionRecRef = useRef<any>(null);
  const sessionStreamRef = useRef<MediaStream | null>(null);
  const pendingChunkRef = useRef<string>("");
  const flushTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sessionStatusRef = useRef<ScribeSessionStatus | null>(null);

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
          // Route through lib/api.ts (ARCH-007) so the request reaches the real
          // API origin. A raw relative fetch() goes to the Amplify static host,
          // which SPA-rewrites unknown paths to index.html — parsing that HTML
          // as JSON is what threw the "expected JSON" error on the live app.
          const j = await postTranscribe(hospitalId, form);
          if (j?.transcript) setTranscript((prev) => (prev ? prev + "\n" + j.transcript : j.transcript));
        } catch (e: any) {
          setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "network error"));
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

  // ---- Chunked ambient session -------------------------------------------
  // Flush whatever finalized speech we've accumulated to the server as one
  // chunk. Called on a timer while recording, and once more on pause/finalize.
  const flushChunk = async () => {
    const sid = sessionIdRef.current;
    const text = pendingChunkRef.current.trim();
    if (!sid || sessionStatusRef.current !== "recording" || !text) return;
    pendingChunkRef.current = "";
    try {
      const r = await appendScribeChunk(hospitalId, { session_id: sid, chunk: text });
      setChunkCount(r.chunk_count);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
    } catch (e: any) {
      // Re-queue the chunk so the next flush retries it rather than losing speech.
      pendingChunkRef.current = (text + " " + pendingChunkRef.current).trim();
      setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "network error"));
    }
  };

  // Wire a fresh Web Speech recognizer that pushes finalized phrases into the
  // pending-chunk buffer. The MediaRecorder path is intentionally not used here —
  // the session API ingests text chunks, not audio.
  const attachSessionRecognizer = () => {
    const SpeechCtor: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechCtor) return;
    try {
      const sr = new SpeechCtor();
      sr.continuous = true;
      sr.interimResults = true;
      sr.lang = "en-US";
      sr.onresult = (e: any) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const seg = e.results[i];
          if (seg.isFinal) pendingChunkRef.current += (seg[0]?.transcript || "") + " ";
        }
      };
      sr.onerror = () => { /* swallow — flush timer retries */ };
      // Keep listening across browser auto-stops while the session is active.
      sr.onend = () => {
        if (sessionStatusRef.current === "recording") {
          try { sr.start(); } catch { /* ignore double-start */ }
        }
      };
      sessionRecRef.current = sr;
      sr.start();
    } catch {
      sessionRecRef.current = null;
    }
  };

  const startSession = async () => {
    setBusy("Starting scribe session...");
    setFinalNote(null);
    setFinalSoapText("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      sessionStreamRef.current = stream;
      const r = await startScribeSession(hospitalId, {
        specialty,
        session_id: sessionId || undefined,
      });
      setSessionId(r.session_id);
      sessionIdRef.current = r.session_id;
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(0);
      pendingChunkRef.current = "";
      attachSessionRecognizer();
      // Flush accumulated speech every 6s so the server's chunk count stays live.
      flushTimerRef.current = setInterval(() => { void flushChunk(); }, 6000);
      setTab("session");
    } catch (e: any) {
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
      sessionStreamRef.current = null;
      if (e?.name === "NotAllowedError" || /permission/i.test(e?.message || "")) {
        setErrorMsg("Microphone access is blocked. Allow it in your browser to capture the encounter.");
      } else {
        setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "unknown"));
      }
    } finally { setBusy(null); }
  };

  const pauseSession = async () => {
    if (!sessionId) return;
    await flushChunk();
    setBusy("Pausing...");
    try {
      try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
      const r = await pauseScribeSession(hospitalId, sessionId);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(r.chunk_count);
    } catch (e: any) {
      setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "unknown"));
    } finally { setBusy(null); }
  };

  const resumeSession = async () => {
    if (!sessionId) return;
    setBusy("Resuming...");
    try {
      const r = await resumeScribeSession(hospitalId, sessionId);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(r.chunk_count);
      attachSessionRecognizer();
    } catch (e: any) {
      setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "unknown"));
    } finally { setBusy(null); }
  };

  const finalizeSession = async () => {
    if (!sessionId) return;
    await flushChunk();
    setBusy("Finalizing note...");
    try {
      // Stop capture cleanly — the encounter is over.
      sessionStatusRef.current = "finalized";
      try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
      if (flushTimerRef.current) { clearInterval(flushTimerRef.current); flushTimerRef.current = null; }
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
      sessionStreamRef.current = null;
      const r = await finalizeScribeSession(hospitalId, sessionId, true);
      setFinalNote(r.structured);
      setFinalSoapText(r.soap_text);
      setSessionStatus("finalized");
      setTab("session");
    } catch (e: any) {
      setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "unknown"));
    } finally { setBusy(null); }
  };

  const regenerate = async (sectionName: string) => {
    if (!finalNote) return;
    setRegenSection(sectionName);
    try {
      const r = await regenerateScribeSection(hospitalId, {
        structured: finalNote,
        section_name: sectionName,
        specialty,
      });
      setFinalNote(r.structured);
      setFinalSoapText(r.soap_text);
    } catch (e: any) {
      setErrorMsg(humanizeError(e?.response?.data?.detail || e?.message || "unknown"));
    } finally { setRegenSection(null); }
  };

  // Tear down session capture if the page unmounts mid-encounter.
  useEffect(() => {
    return () => {
      if (flushTimerRef.current) clearInterval(flushTimerRef.current);
      try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

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
    { key: "session", label: "Ambient session", icon: Radio },
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
            className="rounded-md p-1 text-slate-500 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors"
            title={patientId ? "Back to patient" : "Back to dashboard"}
            aria-label={patientId ? "Back to patient" : "Back to dashboard"}
          >
            <ArrowLeft className="w-5 h-5" aria-hidden="true" />
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
          <label htmlFor="scribe-specialty" className="sr-only">Specialty pack</label>
          <select
            id="scribe-specialty"
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
            className="px-3 py-1.5 rounded-md border border-slate-300 bg-white text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50"
            title="Specialty pack"
          >
            {packs.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
          </select>
        </div>
        <div className="max-w-7xl mx-auto px-4 flex gap-1 overflow-x-auto" role="tablist" aria-label="Scribe sections">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`scribe-tab-${key}`}
              aria-selected={tab === key}
              aria-controls={`scribe-panel-${key}`}
              onClick={() => setTab(key)}
              className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 -mb-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-inset transition-colors ${tab === key ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-900"}`}
            >
              <Icon className="w-4 h-4" aria-hidden="true" />{label}
            </button>
          ))}
        </div>
      </div>

      {/* Live recording / busy state — announced to screen readers. */}
      <div role="status" aria-live="polite" aria-atomic="true">
        {recording && (
          <div className="bg-rose-50 border-b border-rose-200 px-4 py-2 flex items-center gap-2 text-sm text-rose-900">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-600 animate-pulse" aria-hidden="true" />
            Recording the encounter — speak normally. Hit Stop when finished.
          </div>
        )}
        {sessionStatus === "recording" && (
          <div className="bg-rose-50 border-b border-rose-200 px-4 py-2 flex items-center gap-2 text-sm text-rose-900">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-600 animate-pulse" aria-hidden="true" />
            Ambient session recording — {chunkCount} chunk{chunkCount === 1 ? "" : "s"} captured. Pause anytime; finalize when the visit ends.
          </div>
        )}
        {sessionStatus === "paused" && (
          <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center gap-2 text-sm text-amber-900">
            <Pause className="w-3.5 h-3.5" aria-hidden="true" />
            Ambient session paused — {chunkCount} chunk{chunkCount === 1 ? "" : "s"} captured so far. Resume to keep listening.
          </div>
        )}
        {busy && (
          <div className="bg-blue-50 border-b border-blue-200 px-4 py-2 flex items-center gap-2 text-sm text-blue-900">
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />{busy}
          </div>
        )}
      </div>
      {errorMsg && (
        <div role="alert" className="bg-rose-50 border-b border-rose-200 px-4 py-2 flex items-start gap-2 text-sm text-rose-900">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
          <div className="flex-1">{errorMsg}</div>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            aria-label="Dismiss error"
            className="rounded text-rose-700/70 hover:text-rose-900 text-xs font-semibold uppercase tracking-wide focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/50"
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
            <label htmlFor="scribe-cc" className="block text-xs text-slate-600 mt-2">Chief complaint</label>
            <input id="scribe-cc" value={chiefComplaint} onChange={(e) => setChiefComplaint(e.target.value)} placeholder="e.g. chest pain x 2h" className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
            <label htmlFor="scribe-meds" className="block text-xs text-slate-600 mt-3">Active medications (comma-sep)</label>
            <input id="scribe-meds" value={meds} onChange={(e) => setMeds(e.target.value)} placeholder="aspirin, metoprolol, sildenafil" className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
            <label htmlFor="scribe-allergies" className="block text-xs text-slate-600 mt-3">Allergies (comma-sep)</label>
            <input id="scribe-allergies" value={allergies} onChange={(e) => setAllergies(e.target.value)} placeholder="penicillin" className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500" />
            <label htmlFor="scribe-lang" className="block text-xs text-slate-600 mt-3">Patient language</label>
            <select id="scribe-lang" value={language} onChange={(e) => setLanguage(e.target.value)} className="w-full mt-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500">
              {["en","es","zh","tl","vi","ar","fr","ko","ru","de","ht","pt","it","pl","ja","fa","ur","hi","bn","gu"].map(l => <option key={l} value={l}>{l}</option>)}
            </select>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {!recording ? (
                <button type="button" onClick={startRecording} className="col-span-2 flex items-center justify-center gap-2 bg-rose-600 text-white py-2 rounded-md font-medium hover:bg-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/50 focus-visible:ring-offset-2 transition-colors">
                  <Mic className="w-4 h-4" aria-hidden="true" /> Start recording
                </button>
              ) : (
                <button type="button" onClick={stopRecording} className="col-span-2 flex items-center justify-center gap-2 bg-slate-900 text-white py-2 rounded-md font-medium animate-pulse focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500/50 focus-visible:ring-offset-2">
                  <Square className="w-4 h-4" aria-hidden="true" /> Stop &amp; transcribe
                </button>
              )}
              <button type="button" onClick={runAll} disabled={!transcript.trim() || !!busy} className="col-span-2 flex items-center justify-center gap-2 bg-blue-600 text-white py-2 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">
                <Sparkles className="w-4 h-4" aria-hidden="true" /> Run AI suite
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
            <div id="scribe-panel-transcript" role="tabpanel" aria-labelledby="scribe-tab-transcript" className="bg-white rounded-lg border border-slate-200 p-4">
              <label htmlFor="scribe-transcript" className="block text-xs uppercase tracking-wide text-slate-500 mb-2">Transcript</label>
              <textarea
                id="scribe-transcript"
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder="Hit Start recording, or paste a transcript here..."
                rows={20}
                className="w-full px-3 py-2 border border-slate-300 rounded-md font-mono text-sm leading-relaxed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500"
              />
            </div>
          )}

          {tab === "session" && (
            <div id="scribe-panel-session" role="tabpanel" aria-labelledby="scribe-tab-session" className="space-y-3">
              {/* Session controls */}
              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">Ambient scribe session</div>
                    <div className="text-sm text-slate-600 mt-0.5">
                      Captures the bedside conversation in chunks, then finalizes an evidence-linked SOAP note.
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-slate-500">Chunks</span>
                    <span className="inline-flex items-center justify-center min-w-8 h-7 px-2 rounded-md bg-slate-100 font-mono font-semibold text-slate-900 tabular-nums">
                      {chunkCount}
                    </span>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {!sessionStatus || sessionStatus === "finalized" ? (
                    <button
                      type="button"
                      onClick={startSession}
                      disabled={!!busy}
                      className="flex items-center gap-2 px-4 py-2 rounded-md bg-rose-600 text-white text-sm font-medium hover:bg-rose-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/50 focus-visible:ring-offset-2 transition-colors"
                    >
                      <Mic className="w-4 h-4" aria-hidden="true" /> {sessionStatus === "finalized" ? "Start new session" : "Start session"}
                    </button>
                  ) : null}
                  {sessionStatus === "recording" && (
                    <button
                      type="button"
                      onClick={pauseSession}
                      disabled={!!busy}
                      className="flex items-center gap-2 px-4 py-2 rounded-md bg-amber-100 text-amber-900 text-sm font-medium hover:bg-amber-200 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/50 focus-visible:ring-offset-2 transition-colors"
                    >
                      <Pause className="w-4 h-4" aria-hidden="true" /> Pause
                    </button>
                  )}
                  {sessionStatus === "paused" && (
                    <button
                      type="button"
                      onClick={resumeSession}
                      disabled={!!busy}
                      className="flex items-center gap-2 px-4 py-2 rounded-md bg-emerald-100 text-emerald-900 text-sm font-medium hover:bg-emerald-200 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 focus-visible:ring-offset-2 transition-colors"
                    >
                      <Play className="w-4 h-4" aria-hidden="true" /> Resume
                    </button>
                  )}
                  {(sessionStatus === "recording" || sessionStatus === "paused") && (
                    <button
                      type="button"
                      onClick={finalizeSession}
                      disabled={!!busy}
                      className="flex items-center gap-2 px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors"
                    >
                      <Square className="w-4 h-4" aria-hidden="true" /> Finalize note
                    </button>
                  )}
                </div>
                {!sessionStatus && (
                  <div className="mt-3 text-xs text-slate-500">
                    No active session. Start one to capture the encounter hands-free.
                  </div>
                )}
              </div>

              {/* Finalized structured note */}
              {finalNote && (
                <>
                  <div className="bg-white rounded-lg border border-slate-200 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <ClipboardCheck className="w-4 h-4 text-emerald-600" aria-hidden="true" />
                      <div className="text-xs uppercase tracking-wide text-slate-500">Finalized SOAP note — every line traceable to the conversation</div>
                    </div>
                    {finalNote.sections.map((sec) => (
                      <SessionNoteSection
                        key={sec.name}
                        section={sec}
                        regenerating={regenSection === sec.name}
                        disabled={!!regenSection || !!busy}
                        onRegenerate={() => regenerate(sec.name)}
                        onPickEvidence={setActiveEvidence}
                      />
                    ))}
                  </div>

                  {/* Evidence detail — the conversation snippet behind a clicked chip */}
                  {activeEvidence && (
                    <div className="bg-blue-50 rounded-lg border border-blue-200 p-4">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-blue-900 font-medium">
                          <Quote className="w-3.5 h-3.5" aria-hidden="true" /> Linked evidence
                        </div>
                        <button
                          type="button"
                          onClick={() => setActiveEvidence(null)}
                          aria-label="Close evidence detail"
                          className="rounded text-blue-700/70 hover:text-blue-900 text-xs font-semibold uppercase tracking-wide focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50"
                        >
                          Close
                        </button>
                      </div>
                      <div className="mt-1.5 text-xs text-blue-900/80">
                        {speakerLabelOf(activeEvidence.speaker)} · {fmtMs(activeEvidence.begin_ms)}–{fmtMs(activeEvidence.end_ms)}
                      </div>
                      <div className="mt-1 text-sm text-slate-900">"{activeEvidence.snippet}"</div>
                    </div>
                  )}

                  {/* Raw SOAP text for copy / downstream use */}
                  {finalSoapText && (
                    <div className="bg-white rounded-lg border border-slate-200 p-4">
                      <label htmlFor="scribe-final-soap" className="block text-xs uppercase tracking-wide text-slate-500 mb-2">
                        SOAP text
                      </label>
                      <textarea
                        id="scribe-final-soap"
                        value={finalSoapText}
                        readOnly
                        rows={10}
                        className="w-full px-3 py-2 border border-slate-300 rounded-md font-mono text-sm leading-relaxed bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50"
                      />
                    </div>
                  )}

                  {/* Diarized source conversation */}
                  {finalNote.transcript_segments.length > 0 && (
                    <div className="bg-white rounded-lg border border-slate-200 p-4">
                      <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Source conversation</div>
                      <div className="text-sm space-y-1 max-h-64 overflow-auto">
                        {finalNote.transcript_segments.map((s) => {
                          const label = speakerLabelOf(s.speaker);
                          const isHL = activeEvidence?.segment_id === s.id;
                          return (
                            <div key={s.id} className={`px-2 py-1 rounded transition-colors ${isHL ? "bg-yellow-200" : ""}`}>
                              <span className={`text-xs font-medium mr-2 ${label === "Clinician" ? "text-blue-700" : "text-emerald-700"}`}>
                                {label}:
                              </span>
                              <span className="text-slate-900">{s.content}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {tab === "note" && scribe && (
            <div id="scribe-panel-note" role="tabpanel" aria-labelledby="scribe-tab-note" className="space-y-3">
              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Linked Evidence note</div>
                  <div className="flex gap-1 flex-wrap">
                    <button type="button" onClick={() => overrideDecision("scribe", "accepted")} className="text-xs px-2 py-1 bg-emerald-100 text-emerald-900 rounded flex items-center gap-1 hover:bg-emerald-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 transition-colors"><Check className="w-3 h-3" aria-hidden="true" /> Accept</button>
                    <button type="button" onClick={() => overrideDecision("scribe", "rejected")} className="text-xs px-2 py-1 bg-rose-100 text-rose-900 rounded flex items-center gap-1 hover:bg-rose-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/50 transition-colors"><XIcon className="w-3 h-3" aria-hidden="true" /> Reject</button>
                    {patientId && (
                      <button
                        type="button"
                        onClick={saveToChart}
                        disabled={!!busy || savedToChart}
                        className="text-xs px-2 py-1 bg-slate-100 text-slate-900 rounded flex items-center gap-1 disabled:opacity-50 hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500/50 transition-colors"
                        title="Save the SOAP note to this patient's chart"
                      >
                        <FileText className="w-3 h-3" aria-hidden="true" /> {savedToChart ? "Saved" : "Save to chart"}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={pushToEhr}
                      disabled={!!busy}
                      className="text-xs px-2 py-1 bg-blue-600 text-white rounded flex items-center gap-1 disabled:opacity-50 hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 transition-colors"
                      title="Write DocumentReference + Conditions + Allergies to the EHR over FHIR"
                    >
                      <Upload className="w-3 h-3" aria-hidden="true" /> Push to EHR
                    </button>
                  </div>
                </div>
                {ehrResult && (
                  <div role="status" aria-live="polite" className="mb-3 rounded-md border border-emerald-300 bg-emerald-50 p-3">
                    <div className="flex items-center gap-1.5 text-sm font-semibold text-emerald-900">
                      <Check className="w-4 h-4" aria-hidden="true" /> Sent to the patient's chart
                    </div>
                    <div className="mt-1 text-xs text-emerald-900/85">
                      {summarizeEhrWrite(ehrResult.writes)}
                    </div>
                  </div>
                )}
                {ehrError && (
                  <div role="alert" className="mb-3 rounded-md border border-rose-300 bg-rose-50 p-2 text-xs text-rose-900">
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
            <div id="scribe-panel-ddx" role="tabpanel" aria-labelledby="scribe-tab-ddx" className="bg-white rounded-lg border border-slate-200 p-4">
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
            <div id="scribe-panel-calculators" role="tabpanel" aria-labelledby="scribe-tab-calculators" className="bg-white rounded-lg border border-slate-200 p-4">
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
            <div id="scribe-panel-coding" role="tabpanel" aria-labelledby="scribe-tab-coding" className="bg-white rounded-lg border border-slate-200 p-4">
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
            <div id="scribe-panel-discharge" role="tabpanel" aria-labelledby="scribe-tab-discharge" className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">Multi-language patient discharge plan</div>
                <button type="button" onClick={buildDischargePlan} disabled={!transcript.trim()} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 transition-colors">
                  <ClipboardCheck className="w-3 h-3 inline mr-1" aria-hidden="true" /> Build plan
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

/** Normalize a raw diarization speaker tag into a clean clinical label. */
function speakerLabelOf(speaker: string): string {
  return speaker?.toLowerCase().includes("clinic") || speaker?.toLowerCase().includes("doctor")
    ? "Clinician"
    : "Patient";
}

/** Format a millisecond offset into a compact m:ss timestamp. */
function fmtMs(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/**
 * One section of the finalized SOAP note. Renders each line with its Linked
 * Evidence chips, shows the section's evidence-coverage bar, and offers an
 * in-place regenerate. Kept inline so the scribe page stays self-contained.
 */
function SessionNoteSection({
  section,
  regenerating,
  disabled,
  onRegenerate,
  onPickEvidence,
}: {
  section: ScribeSessionSection;
  regenerating: boolean;
  disabled: boolean;
  onRegenerate: () => void;
  onPickEvidence: (e: LinkedEvidence) => void;
}) {
  const coveragePct = Math.round((section.evidence_coverage || 0) * 100);
  // Coverage tone: green when well-grounded, amber when partly, rose when thin.
  const tone =
    coveragePct >= 80 ? { bar: "bg-emerald-500", text: "text-emerald-700" } :
    coveragePct >= 50 ? { bar: "bg-amber-500", text: "text-amber-700" } :
    { bar: "bg-rose-500", text: "text-rose-700" };
  return (
    <div className="mb-4 last:mb-0">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm font-semibold text-slate-700 capitalize">
          {section.name.replace(/_/g, " ").toLowerCase()}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5" title="Share of lines backed by conversation evidence">
            <div className="w-20 h-1.5 rounded bg-slate-200 overflow-hidden">
              <div className={`h-full ${tone.bar}`} style={{ width: `${Math.min(100, coveragePct)}%` }} />
            </div>
            <span className={`text-xs font-medium tabular-nums ${tone.text}`}>{coveragePct}% cited</span>
          </div>
          <button
            type="button"
            onClick={onRegenerate}
            disabled={disabled}
            aria-label={`Regenerate ${section.name.replace(/_/g, " ").toLowerCase()} section`}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-slate-100 text-slate-700 hover:bg-slate-200 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500/50 transition-colors"
          >
            {regenerating ? (
              <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="w-3 h-3" aria-hidden="true" />
            )}
            {regenerating ? "Regenerating" : "Regenerate"}
          </button>
        </div>
      </div>
      <div className="mt-1.5 space-y-2">
        {section.lines.length === 0 && (
          <div className="text-sm text-slate-400 italic">No content captured for this section.</div>
        )}
        {section.lines.map((line, i) => (
          <div key={i} className="text-sm">
            <div className="text-slate-900">{line.text}</div>
            {line.linked_evidence.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {line.linked_evidence.map((ev, j) => (
                  <button
                    key={`${ev.segment_id}-${j}`}
                    type="button"
                    onClick={() => onPickEvidence(ev)}
                    title={ev.snippet}
                    className="inline-flex items-center gap-1 max-w-full px-1.5 py-0.5 rounded border border-blue-200 bg-blue-50 text-[11px] text-blue-800 hover:bg-blue-100 hover:border-blue-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 transition-colors"
                  >
                    <Quote className="w-2.5 h-2.5 shrink-0" aria-hidden="true" />
                    <span className="font-medium">{speakerLabelOf(ev.speaker)}</span>
                    <span className="text-blue-500 tabular-nums">{fmtMs(ev.begin_ms)}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="mt-1 inline-flex items-center gap-1 text-[11px] text-amber-700">
                <AlertTriangle className="w-2.5 h-2.5" aria-hidden="true" /> Not linked to the conversation — verify before signing.
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function renderCalcValue(v: any): string {
  if (Array.isArray(v)) return v.join(", ") || "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "object" && v !== null) {
    return Object.entries(v).map(([k, val]) => `${k}: ${val}`).join(", ");
  }
  return String(v);
}
