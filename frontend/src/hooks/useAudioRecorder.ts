import { useCallback, useEffect, useRef, useState } from "react";

export type UseAudioRecorder = {
  isRecording: boolean;
  audioBlob: Blob | null;
  elapsed: number;
  permissionDenied: boolean;
  // Web Speech API live transcript. Populated in real-time on browsers that
  // support window.SpeechRecognition (iOS Safari 14.1+, Chrome, Edge). When
  // non-empty, callers can skip the server /transcribe round-trip entirely.
  liveTranscript: string;
  webSpeechSupported: boolean;
  start: (langHint?: string) => Promise<void>;
  stop: () => void;
  reset: () => void;
};

// API Gateway HTTP API caps integration timeout at 30s. With Whisper + Claude
// follow-ups inside the same Lambda invocation, audio over ~60s reliably blows
// past that and surfaces to the patient as a "connection hiccup" 504. Cap the
// recorder shorter than that mathematical ceiling so the worst-case patient
// never hits the timeout.
const MAX_SECONDS = 60;

// Map our internal ISO-639-1 codes to BCP-47 tags that SpeechRecognition expects.
const SPEECH_LANG_MAP: Record<string, string> = {
  en: "en-US", es: "es-US", fr: "fr-FR", de: "de-DE",
  pt: "pt-BR", it: "it-IT", vi: "vi-VN", zh: "zh-CN",
  ja: "ja-JP", ko: "ko-KR", ar: "ar-SA", hi: "hi-IN",
  ru: "ru-RU", nl: "nl-NL", pl: "pl-PL", tr: "tr-TR",
  uk: "uk-UA", ur: "ur-PK", bn: "bn-IN", tl: "fil-PH",
  ht: "fr-FR", fa: "fa-IR", gu: "gu-IN",
};

// Minimal type surface for the Web Speech API. The browser types aren't in
// lib.dom.d.ts on every TS version; declare just what we touch.
type SpeechRec = {
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: (e: any) => void;
  onerror: (e: any) => void;
  onend: () => void;
  continuous: boolean;
  interimResults: boolean;
  lang: string;
};

function getSpeechCtor(): (new () => SpeechRec) | null {
  if (typeof window === "undefined") return null;
  const w = window as any;
  return (w.SpeechRecognition || w.webkitSpeechRecognition || null) as any;
}

export function useAudioRecorder(): UseAudioRecorder {
  const [isRecording, setIsRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);
  const speechRef = useRef<SpeechRec | null>(null);
  // Accumulated FINAL results from the speech recognizer. Interim results are
  // appended to a separate scratch buffer so the user sees them update live,
  // but only finals are committed to state on stop().
  const finalChunksRef = useRef<string>("");

  const webSpeechSupported = getSpeechCtor() !== null;

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop());
      try { speechRef.current?.abort(); } catch { /* ignore */ }
    };
  }, []);

  const stopInternal = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
    try { speechRef.current?.stop(); } catch { /* ignore */ }
    setIsRecording(false);
  }, []);

  const start = useCallback(async (langHint?: string) => {
    setAudioBlob(null);
    setElapsed(0);
    setLiveTranscript("");
    finalChunksRef.current = "";
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        setAudioBlob(blob);
        stream.getTracks().forEach((t) => t.stop());
      };
      recorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);

      // Spin up the Web Speech recognizer in parallel. It uses its own mic
      // session (independent of MediaRecorder) and emits interim+final
      // transcripts as the patient speaks. Failures are swallowed — the
      // MediaRecorder path remains the canonical fallback.
      const SpeechCtor = getSpeechCtor();
      if (SpeechCtor) {
        try {
          const rec = new SpeechCtor();
          rec.continuous = true;
          rec.interimResults = true;
          rec.lang = SPEECH_LANG_MAP[(langHint || "").toLowerCase()] || "en-US";
          rec.onresult = (e: any) => {
            let interim = "";
            for (let i = e.resultIndex; i < e.results.length; i++) {
              const segment = e.results[i];
              const txt = segment[0]?.transcript || "";
              if (segment.isFinal) finalChunksRef.current += txt;
              else interim += txt;
            }
            setLiveTranscript((finalChunksRef.current + " " + interim).trim());
          };
          rec.onerror = () => { /* swallow — server path remains as fallback */ };
          rec.onend = () => { /* allow caller to read liveTranscript */ };
          speechRef.current = rec;
          rec.start();
        } catch {
          // Some browsers throw if called twice or in private mode — ignore.
          speechRef.current = null;
        }
      }

      const startedAt = Date.now();
      timerRef.current = window.setInterval(() => {
        const secs = Math.floor((Date.now() - startedAt) / 1000);
        setElapsed(secs);
        if (secs >= MAX_SECONDS) stopInternal();
      }, 250);
    } catch (err) {
      console.error("Mic permission denied or error:", err);
      setPermissionDenied(true);
    }
  }, [stopInternal]);

  const reset = useCallback(() => {
    setAudioBlob(null);
    setElapsed(0);
    setLiveTranscript("");
    finalChunksRef.current = "";
  }, []);

  return {
    isRecording,
    audioBlob,
    elapsed,
    permissionDenied,
    liveTranscript,
    webSpeechSupported,
    start,
    stop: stopInternal,
    reset,
  };
}
