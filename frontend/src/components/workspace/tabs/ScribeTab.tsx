import { useEffect, useRef, useState } from "react";
import {
  Mic, Square, Loader2, AlertTriangle, ClipboardCheck, Pause, Play,
  RefreshCw, Quote,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import {
  startScribeSession, appendScribeChunk, pauseScribeSession, resumeScribeSession,
  finalizeScribeSession, regenerateScribeSection,
  type ScribeSessionStatus, type ScribeStructuredNote, type ScribeSessionSection,
  type LinkedEvidence,
} from "../../../lib/api-scribe";

/**
 * ScribeTab — ambient-scribe experience scoped to the workspace patient.
 *
 * The clinician never picks a patient here; the encounter is bound to the
 * workspace `patient` from context. The doctor runs a chunked recording
 * session (start → append → pause/resume → finalize), then reviews a
 * finalized, evidence-linked structured SOAP note with clickable Linked
 * Evidence chips and per-section regenerate.
 *
 * Ported and trimmed from pages/ClinicianScribe.tsx — no page chrome, no nav,
 * no specialty picker (defaults to the ED pack), no AI-suite/coding/discharge
 * tabs. Just the calm, clinical ambient-session core.
 */
export default function ScribeTab() {
  const { hospitalId, patient, loading, error } = usePatientWorkspace();

  // ---- Chunked ambient-scribe session state ------------------------------
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<ScribeSessionStatus | null>(null);
  const [chunkCount, setChunkCount] = useState(0);
  const [finalNote, setFinalNote] = useState<ScribeStructuredNote | null>(null);
  const [finalSoapText, setFinalSoapText] = useState("");
  const [regenSection, setRegenSection] = useState<string | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<LinkedEvidence | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Web Speech recognizer + chunk-flush plumbing for the live session.
  const sessionRecRef = useRef<SpeechRecognitionLike | null>(null);
  const sessionStreamRef = useRef<MediaStream | null>(null);
  const pendingChunkRef = useRef<string>("");
  const flushTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sessionStatusRef = useRef<ScribeSessionStatus | null>(null);

  // Tear down session capture if the tab unmounts mid-encounter.
  useEffect(() => {
    return () => {
      if (flushTimerRef.current) clearInterval(flushTimerRef.current);
      try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // ---- Chunk flush --------------------------------------------------------
  // Push whatever finalized speech we've accumulated to the server as one
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
    } catch (e: unknown) {
      // Re-queue the chunk so the next flush retries rather than losing speech.
      pendingChunkRef.current = (text + " " + pendingChunkRef.current).trim();
      setErrorMsg(humanizeError(errText(e)));
    }
  };

  // Wire a fresh Web Speech recognizer that pushes finalized phrases into the
  // pending-chunk buffer. The session API ingests text chunks, not audio.
  const attachSessionRecognizer = () => {
    const SpeechCtor = (window as unknown as SpeechWindow).SpeechRecognition
      || (window as unknown as SpeechWindow).webkitSpeechRecognition;
    if (!SpeechCtor) return;
    try {
      const sr = new SpeechCtor();
      sr.continuous = true;
      sr.interimResults = true;
      sr.lang = "en-US";
      sr.onresult = (e: SpeechResultEvent) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const seg = e.results[i];
          if (seg.isFinal) pendingChunkRef.current += (seg[0]?.transcript || "") + " ";
        }
      };
      sr.onerror = () => { /* swallow — the flush timer retries */ };
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
    setBusy("Starting scribe session…");
    setErrorMsg(null);
    setFinalNote(null);
    setFinalSoapText("");
    setActiveEvidence(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      sessionStreamRef.current = stream;
      const r = await startScribeSession(hospitalId, {
        specialty: "ed",
        session_id: sessionId || undefined,
      });
      setSessionId(r.session_id);
      sessionIdRef.current = r.session_id;
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(0);
      pendingChunkRef.current = "";
      attachSessionRecognizer();
      // Flush accumulated speech every 6s so the chunk count stays live.
      flushTimerRef.current = setInterval(() => { void flushChunk(); }, 6000);
    } catch (e: unknown) {
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
      sessionStreamRef.current = null;
      const err = e as { name?: string; message?: string };
      if (err?.name === "NotAllowedError" || /permission/i.test(err?.message || "")) {
        setErrorMsg("Microphone access is blocked. Allow it in your browser to capture the encounter.");
      } else {
        setErrorMsg(humanizeError(errText(e)));
      }
    } finally {
      setBusy(null);
    }
  };

  const pauseSession = async () => {
    if (!sessionId) return;
    await flushChunk();
    setBusy("Pausing…");
    try {
      try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
      const r = await pauseScribeSession(hospitalId, sessionId);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(r.chunk_count);
    } catch (e: unknown) {
      setErrorMsg(humanizeError(errText(e)));
    } finally {
      setBusy(null);
    }
  };

  const resumeSession = async () => {
    if (!sessionId) return;
    setBusy("Resuming…");
    try {
      const r = await resumeScribeSession(hospitalId, sessionId);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(r.chunk_count);
      attachSessionRecognizer();
    } catch (e: unknown) {
      setErrorMsg(humanizeError(errText(e)));
    } finally {
      setBusy(null);
    }
  };

  const finalizeSession = async () => {
    if (!sessionId) return;
    await flushChunk();
    setBusy("Finalizing note…");
    try {
      // Stop capture cleanly — the encounter is over.
      sessionStatusRef.current = "finalized";
      try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
      if (flushTimerRef.current) { clearInterval(flushTimerRef.current); flushTimerRef.current = null; }
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
      sessionStreamRef.current = null;
      const r = await finalizeScribeSession(hospitalId, sessionId, true);
      setFinalNote(normalizeNote(r.structured, sessionId));
      setFinalSoapText(r.soap_text || "");
      setSessionStatus("finalized");
      sessionStatusRef.current = "finalized";
    } catch (e: unknown) {
      setErrorMsg(humanizeError(errText(e)));
    } finally {
      setBusy(null);
    }
  };

  const regenerate = async (sectionName: string) => {
    if (!finalNote) return;
    setRegenSection(sectionName);
    try {
      const r = await regenerateScribeSection(hospitalId, {
        structured: finalNote,
        section_name: sectionName,
        specialty: "ed",
      });
      setFinalNote(normalizeNote(r.structured, finalNote.session_id));
      setFinalSoapText(r.soap_text || "");
    } catch (e: unknown) {
      setErrorMsg(humanizeError(errText(e)));
    } finally {
      setRegenSection(null);
    }
  };

  // ---- Guards (loading / error / null patient) ---------------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted text-sm">
        <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
        Loading patient record…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
    );
  }

  if (!patient) {
    return <div className="text-text-muted text-sm py-8">No patient record available.</div>;
  }

  const recording = sessionStatus === "recording";
  const paused = sessionStatus === "paused";

  return (
    <div className="space-y-3">
      {/* Patient-bound encounter banner */}
      <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
        <div className="flex items-center gap-2">
          <Mic size={16} className="text-primary shrink-0" aria-hidden="true" />
          <div className="text-xs uppercase tracking-wide text-text-muted font-medium">
            Ambient scribe
          </div>
        </div>
        <h2 className="text-lg font-bold tracking-editorial mt-1">Encounter for {patient.name}</h2>
        <p className="text-text-muted text-sm mt-0.5">
          Captures the bedside conversation in chunks, then finalizes an
          evidence-linked SOAP note. The encounter is bound to this patient.
        </p>
      </div>

      {/* Live status — announced to screen readers */}
      <div role="status" aria-live="polite" aria-atomic="true">
        {recording && (
          <div className="flex items-center gap-2 rounded-lg bg-error-container px-4 py-2 text-sm text-error">
            <span className="w-2.5 h-2.5 rounded-full bg-error animate-pulse" aria-hidden="true" />
            Ambient session recording — {chunkCount} chunk{chunkCount === 1 ? "" : "s"} captured.
            Pause anytime; finalize when the visit ends.
          </div>
        )}
        {paused && (
          <div className="flex items-center gap-2 rounded-lg bg-warning-container px-4 py-2 text-sm text-warning">
            <Pause size={14} aria-hidden="true" />
            Ambient session paused — {chunkCount} chunk{chunkCount === 1 ? "" : "s"} captured so far.
            Resume to keep listening.
          </div>
        )}
        {busy && (
          <div className="flex items-center gap-2 rounded-lg bg-primary-dim px-4 py-2 text-sm text-primary">
            <Loader2 size={16} className="animate-spin" aria-hidden="true" />{busy}
          </div>
        )}
      </div>

      {errorMsg && (
        <div role="alert" className="flex items-start gap-2 rounded-lg bg-error-container px-4 py-2 text-sm text-error">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div className="flex-1">{errorMsg}</div>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            aria-label="Dismiss error"
            className="rounded text-xs font-semibold uppercase tracking-wide text-error/70 hover:text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/50"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Session controls */}
      <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="text-xs uppercase tracking-wide text-text-muted font-medium">
            Recording session
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-text-muted">Chunks</span>
            <span className="inline-flex items-center justify-center min-w-8 h-7 px-2 rounded-md bg-surface-low font-mono font-semibold text-ink tabular-nums">
              {chunkCount}
            </span>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {(!sessionStatus || sessionStatus === "finalized") && (
            <button
              type="button"
              onClick={startSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-error text-surface-lowest text-sm font-medium hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/50 focus-visible:ring-offset-2 transition-opacity"
            >
              <Mic size={16} aria-hidden="true" />
              {sessionStatus === "finalized" ? "Start new session" : "Start session"}
            </button>
          )}
          {recording && (
            <button
              type="button"
              onClick={pauseSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-warning-container text-warning text-sm font-medium hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warning/50 focus-visible:ring-offset-2 transition-opacity"
            >
              <Pause size={16} aria-hidden="true" /> Pause
            </button>
          )}
          {paused && (
            <button
              type="button"
              onClick={resumeSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-success-container text-success text-sm font-medium hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success/50 focus-visible:ring-offset-2 transition-opacity"
            >
              <Play size={16} aria-hidden="true" /> Resume
            </button>
          )}
          {(recording || paused) && (
            <button
              type="button"
              onClick={finalizeSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-primary text-surface-lowest text-sm font-medium hover:bg-primary-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 transition-colors"
            >
              <Square size={16} aria-hidden="true" /> Finalize note
            </button>
          )}
        </div>
        {!sessionStatus && (
          <div className="mt-3 text-xs text-text-muted">
            No active session. Start one to capture the encounter hands-free.
          </div>
        )}
      </div>

      {/* Finalized structured note */}
      {finalNote && (
        <>
          <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
            <div className="flex items-center gap-2 mb-3">
              <ClipboardCheck size={16} className="text-success" aria-hidden="true" />
              <div className="text-xs uppercase tracking-wide text-text-muted font-medium">
                Finalized SOAP note — every line traceable to the conversation
              </div>
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
            <div className="bg-secondary-container rounded-lg p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-secondary font-medium">
                  <Quote size={14} aria-hidden="true" /> Linked evidence
                </div>
                <button
                  type="button"
                  onClick={() => setActiveEvidence(null)}
                  aria-label="Close evidence detail"
                  className="rounded text-xs font-semibold uppercase tracking-wide text-secondary/70 hover:text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/50"
                >
                  Close
                </button>
              </div>
              <div className="mt-1.5 text-xs text-secondary/80">
                {speakerLabelOf(activeEvidence.speaker)} · {fmtMs(activeEvidence.begin_ms)}–{fmtMs(activeEvidence.end_ms)}
              </div>
              <div className="mt-1 text-sm text-ink">"{activeEvidence.snippet}"</div>
            </div>
          )}

          {/* Raw SOAP text for copy / downstream use */}
          {finalSoapText && (
            <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
              <label htmlFor="scribe-final-soap" className="block text-xs uppercase tracking-wide text-text-muted font-medium mb-2">
                SOAP text
              </label>
              <textarea
                id="scribe-final-soap"
                value={finalSoapText}
                readOnly
                rows={10}
                className="w-full px-3 py-2 rounded-md bg-surface-low font-mono text-sm leading-relaxed text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              />
            </div>
          )}

          {/* Diarized source conversation */}
          {finalNote.transcript_segments.length > 0 && (
            <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
              <div className="text-xs uppercase tracking-wide text-text-muted font-medium mb-2">
                Source conversation
              </div>
              <div className="text-sm space-y-1 max-h-64 overflow-auto">
                {finalNote.transcript_segments.map((s) => {
                  const label = speakerLabelOf(s.speaker);
                  const isHL = activeEvidence?.segment_id === s.id;
                  return (
                    <div key={s.id} className={`px-2 py-1 rounded transition-colors ${isHL ? "bg-warning-container" : ""}`}>
                      <span className={`text-xs font-medium mr-2 ${label === "Clinician" ? "text-secondary" : "text-success"}`}>
                        {label}:
                      </span>
                      <span className="text-ink">{s.content}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Minimal Web Speech typings — the API is not in the default lib.dom yet.
// ---------------------------------------------------------------------------
type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechResultEvent = {
  resultIndex: number;
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
};
type SpeechWindow = {
  SpeechRecognition?: { new (): SpeechRecognitionLike };
  webkitSpeechRecognition?: { new (): SpeechRecognitionLike };
};

// ---------------------------------------------------------------------------
// Small UI helpers — kept inline so the tab stays self-contained.
// ---------------------------------------------------------------------------

/** Coerce a finalize/regenerate payload into a fully-formed note so a missing or
 *  malformed field from the backend can never crash the render (demo-safety). */
function normalizeNote(
  n: ScribeStructuredNote | null | undefined,
  sessionId: string,
): ScribeStructuredNote {
  const sections = n && Array.isArray(n.sections) ? n.sections : [];
  const segments = n && Array.isArray(n.transcript_segments) ? n.transcript_segments : [];
  return { session_id: n?.session_id ?? sessionId, sections, transcript_segments: segments };
}

/** Pull a usable message string out of an unknown thrown value. */
function errText(e: unknown): string {
  const err = e as { response?: { data?: { detail?: string } }; message?: string };
  return err?.response?.data?.detail || err?.message || "unknown";
}

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
  return s;
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
 * in-place regenerate.
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
  // Coverage tone: green when well-grounded, amber when partial, red when thin.
  const tone =
    coveragePct >= 80 ? { bar: "bg-success", text: "text-success" } :
    coveragePct >= 50 ? { bar: "bg-warning", text: "text-warning" } :
    { bar: "bg-error", text: "text-error" };
  const sectionLabel = (section.name || "section").replace(/_/g, " ").toLowerCase();
  const lines = section.lines || [];
  return (
    <div className="mb-4 last:mb-0">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm font-semibold text-ink capitalize">{sectionLabel}</div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5" title="Share of lines backed by conversation evidence">
            <div className="w-20 h-1.5 rounded bg-surface-high overflow-hidden">
              <div className={`h-full ${tone.bar}`} style={{ width: `${Math.min(100, coveragePct)}%` }} />
            </div>
            <span className={`text-xs font-medium tabular-nums ${tone.text}`}>{coveragePct}% cited</span>
          </div>
          <button
            type="button"
            onClick={onRegenerate}
            disabled={disabled}
            aria-label={`Regenerate ${sectionLabel} section`}
            className="flex items-center gap-1 h-8 px-2 rounded text-xs font-medium bg-surface-low text-text-muted hover:bg-surface-high disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 transition-colors"
          >
            {regenerating
              ? <Loader2 size={12} className="animate-spin" aria-hidden="true" />
              : <RefreshCw size={12} aria-hidden="true" />}
            {regenerating ? "Regenerating" : "Regenerate"}
          </button>
        </div>
      </div>
      <div className="mt-1.5 space-y-2">
        {lines.length === 0 && (
          <div className="text-sm text-text-muted italic">No content captured for this section.</div>
        )}
        {lines.map((line, i) => {
          const evidence = line.linked_evidence || [];
          return (
          <div key={i} className="text-sm">
            <div className="text-ink">{line.text}</div>
            {evidence.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {evidence.map((ev, j) => (
                  <button
                    key={`${ev.segment_id}-${j}`}
                    type="button"
                    onClick={() => onPickEvidence(ev)}
                    title={ev.snippet}
                    className="inline-flex items-center gap-1 max-w-full px-1.5 py-0.5 rounded border border-secondary/40 bg-secondary-container text-[11px] text-secondary hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/50 transition-opacity"
                  >
                    <Quote size={10} className="shrink-0" aria-hidden="true" />
                    <span className="font-medium">{speakerLabelOf(ev.speaker)}</span>
                    <span className="tabular-nums opacity-70">{fmtMs(ev.begin_ms)}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="mt-1 inline-flex items-center gap-1 text-[11px] text-warning">
                <AlertTriangle size={10} aria-hidden="true" />
                Not linked to the conversation — verify before signing.
              </div>
            )}
          </div>
          );
        })}
      </div>
    </div>
  );
}
