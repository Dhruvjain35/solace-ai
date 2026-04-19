import { useEffect, useRef, useState } from "react";
import { Play, Pause } from "lucide-react";

type Props = { audioUrl: string | null };

export function AudioPlayer({ audioUrl }: Props) {
  const [playing, setPlaying] = useState(false);
  const ref = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!audioUrl) return;
    const t = window.setTimeout(() => {
      ref.current?.play().catch(() => {
        /* autoplay may be blocked; user can tap play */
      });
    }, 1500);
    return () => window.clearTimeout(t);
  }, [audioUrl]);

  if (!audioUrl) {
    return (
      <div className="mx-4 mb-4 rounded-lg bg-surface-low px-4 py-3 text-sm text-text-muted">
        Audio unavailable — please read the guidance above.
      </div>
    );
  }

  return (
    <div className="sticky bottom-0 w-full bg-surface-lowest/85 backdrop-blur-xl p-4 flex items-center gap-4 shadow-glass">
      <button
        type="button"
        className="w-12 h-12 rounded-full bg-primary-gradient text-white flex items-center justify-center shadow-soft"
        aria-label={playing ? "Pause audio" : "Play audio"}
        onClick={() => {
          if (!ref.current) return;
          if (playing) ref.current.pause();
          else void ref.current.play();
        }}
      >
        {playing ? <Pause size={22} /> : <Play size={22} fill="white" />}
      </button>
      <div className={`flex items-end gap-1 h-8 flex-1 ${playing ? "opacity-100" : "opacity-40"}`}>
        {[0, 1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className="w-1.5 bg-primary rounded"
            style={{
              height: `${12 + (i % 3) * 8}px`,
              animation: playing ? `pulse 1.2s ease-in-out ${i * 0.15}s infinite` : undefined,
            }}
          />
        ))}
      </div>
      <audio
        ref={ref}
        src={audioUrl}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />
    </div>
  );
}
