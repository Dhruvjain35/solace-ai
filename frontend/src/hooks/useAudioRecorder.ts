import { useCallback, useEffect, useRef, useState } from "react";

export type UseAudioRecorder = {
  isRecording: boolean;
  audioBlob: Blob | null;
  elapsed: number;
  permissionDenied: boolean;
  start: () => Promise<void>;
  stop: () => void;
  reset: () => void;
};

// API Gateway HTTP API caps integration timeout at 30s. With Whisper + Claude
// follow-ups inside the same Lambda invocation, audio over ~60s reliably blows
// past that and surfaces to the patient as a "connection hiccup" 504. Cap the
// recorder shorter than that mathematical ceiling so the worst-case patient
// never hits the timeout.
const MAX_SECONDS = 60;

export function useAudioRecorder(): UseAudioRecorder {
  const [isRecording, setIsRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [permissionDenied, setPermissionDenied] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const start = useCallback(async () => {
    setAudioBlob(null);
    setElapsed(0);
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
  }, []);

  const stopInternal = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
    setIsRecording(false);
  }, []);

  const reset = useCallback(() => {
    setAudioBlob(null);
    setElapsed(0);
  }, []);

  return { isRecording, audioBlob, elapsed, permissionDenied, start, stop: stopInternal, reset };
}
