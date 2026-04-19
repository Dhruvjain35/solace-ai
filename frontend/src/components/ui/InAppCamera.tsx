import { useEffect, useRef, useState } from "react";
import { Camera, X, RotateCcw } from "lucide-react";

type Props = {
  onCapture: (file: File) => void;
  onClose: () => void;
  label?: string;
  aspectHint?: "card" | "free"; // "card" = insurance card overlay guides
};

/** Full-screen in-app camera. Uses getUserMedia → <video> preview → canvas capture → File. */
export function InAppCamera({ onCapture, onClose, label, aspectHint = "free" }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = s;
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          await videoRef.current.play().catch(() => undefined);
        }
        setReady(true);
      } catch (e: any) {
        setError(e?.message || "Camera unavailable. Check browser permissions.");
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  function capture() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !ready) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const file = new File([blob], `capture-${Date.now()}.jpg`, { type: "image/jpeg" });
        onCapture(file);
      },
      "image/jpeg",
      0.92
    );
  }

  async function flipCamera() {
    // Best-effort: stop current stream, restart with the other facing mode.
    const current = streamRef.current?.getVideoTracks()[0]?.getSettings().facingMode;
    const next = current === "user" ? "environment" : "user";
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setReady(false);
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: next } },
        audio: false,
      });
      streamRef.current = s;
      if (videoRef.current) {
        videoRef.current.srcObject = s;
        await videoRef.current.play().catch(() => undefined);
      }
      setReady(true);
    } catch {
      // swallow — keep the error state visible
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black flex flex-col">
      <div className="flex items-center justify-between px-4 py-4 bg-black text-white"
           style={{ paddingTop: "calc(1rem + env(safe-area-inset-top, 0px))" }}>
        <button
          onClick={onClose}
          className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center"
          aria-label="Close camera"
        >
          <X size={20} />
        </button>
        <div className="text-sm font-medium">{label || "Camera"}</div>
        <button
          onClick={flipCamera}
          className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center"
          aria-label="Flip camera"
        >
          <RotateCcw size={18} />
        </button>
      </div>

      <div className="relative flex-1 bg-black flex items-center justify-center">
        {error ? (
          <div className="text-white text-center p-6 max-w-sm">
            <p className="mb-2">{error}</p>
            <p className="text-xs opacity-70">
              Safari/Chrome need camera permission. Try Settings → Safari → Camera.
            </p>
          </div>
        ) : (
          <video
            ref={videoRef}
            playsInline
            muted
            autoPlay
            className="max-w-full max-h-full object-contain"
          />
        )}
        {aspectHint === "card" && ready && !error && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-[86%] aspect-[1.586] border-2 border-white/70 rounded-lg shadow-lifted" />
          </div>
        )}
        <canvas ref={canvasRef} className="hidden" />
      </div>

      <div
        className="bg-black flex items-center justify-center p-6"
        style={{ paddingBottom: "calc(1.5rem + env(safe-area-inset-bottom, 0px))" }}
      >
        <button
          onClick={capture}
          disabled={!ready || !!error}
          className="w-20 h-20 rounded-full bg-white ring-4 ring-white/40 disabled:opacity-40 active:scale-95 transition-transform flex items-center justify-center"
          aria-label="Capture"
        >
          <Camera size={28} className="text-black" />
        </button>
      </div>
    </div>
  );
}
