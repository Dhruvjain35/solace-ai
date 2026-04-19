import { Mic, Square } from "lucide-react";

type Props = {
  isRecording: boolean;
  elapsed: number;
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
};

export function MicButton({ isRecording, elapsed, disabled, onStart, onStop }: Props) {
  return (
    <div className="flex flex-col items-center gap-4">
      <button
        type="button"
        disabled={disabled}
        onClick={isRecording ? onStop : onStart}
        className={`w-28 h-28 rounded-full flex items-center justify-center text-white shadow-lifted transition-transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed ${
          isRecording
            ? "bg-error animate-pulse-ring"
            : "bg-primary-gradient hover:brightness-110"
        }`}
        aria-label={isRecording ? "Stop recording" : "Start recording your symptoms"}
      >
        {isRecording ? <Square size={40} fill="white" /> : <Mic size={40} />}
      </button>
      <div className="text-sm text-text-muted font-mono tracking-wide">
        {isRecording ? `Listening · ${elapsed}s · tap to stop` : "Tap to speak your symptoms"}
      </div>
    </div>
  );
}
