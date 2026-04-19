import { useEffect, useRef, useState } from "react";
import { Camera, ImagePlus, RefreshCw, X } from "lucide-react";
import { InAppCamera } from "../ui/InAppCamera";

type Props = {
  file: File | null;
  onChange: (file: File | null) => void;
  label?: string;
  description?: string;
};

function hasGetUserMedia(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

export function PhotoCapture({
  file,
  onChange,
  label = "Take a photo",
  description = "Optional — helps the clinician see what you see",
}: Props) {
  const [preview, setPreview] = useState<string | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function openPrimaryCamera() {
    if (hasGetUserMedia()) {
      setCameraOpen(true);
    } else {
      fileInputRef.current?.click();
    }
  }

  if (preview) {
    return (
      <>
        <div className="relative">
          <img src={preview} alt="Injury preview" className="w-full rounded-lg shadow-soft" />
          <div className="absolute top-3 right-3 flex gap-2">
            <button
              type="button"
              onClick={openPrimaryCamera}
              className="bg-surface-lowest/90 backdrop-blur w-10 h-10 rounded-full flex items-center justify-center shadow-soft"
              aria-label="Retake photo"
            >
              <RefreshCw size={18} />
            </button>
            <button
              type="button"
              onClick={() => onChange(null)}
              className="bg-surface-lowest/90 backdrop-blur w-10 h-10 rounded-full flex items-center justify-center shadow-soft"
              aria-label="Remove photo"
            >
              <X size={18} />
            </button>
          </div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => onChange(e.target.files?.[0] || null)}
        />
        {cameraOpen && (
          <InAppCamera
            label={label}
            onCapture={(f) => {
              onChange(f);
              setCameraOpen(false);
            }}
            onClose={() => setCameraOpen(false)}
          />
        )}
      </>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={openPrimaryCamera}
        className="w-full rounded-lg bg-surface-low hover:bg-primary-dim transition-colors py-8 flex flex-col items-center gap-2 active:scale-[0.99]"
      >
        <div className="w-14 h-14 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
          <Camera size={26} />
        </div>
        <div className="font-semibold tracking-editorial">{label}</div>
        <div className="text-xs text-text-muted text-center px-6">{description}</div>
      </button>
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        className="self-center inline-flex items-center gap-1 text-sm text-text-muted underline underline-offset-2 px-3 py-1"
      >
        <ImagePlus size={14} /> or upload from library
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => onChange(e.target.files?.[0] || null)}
      />
      {cameraOpen && (
        <InAppCamera
          label={label}
          onCapture={(f) => {
            onChange(f);
            setCameraOpen(false);
          }}
          onClose={() => setCameraOpen(false)}
        />
      )}
    </div>
  );
}
