import { useEffect, useRef, useState } from "react";
import { CheckCircle2, CreditCard, ImagePlus, Loader2, RefreshCw, X } from "lucide-react";
import { InAppCamera } from "../ui/InAppCamera";
import { scanInsurance } from "../../lib/api";
import type { InsuranceFields } from "../../types";

type Props = {
  hospitalId: string;
  value: InsuranceFields | null;
  onChange: (fields: InsuranceFields | null) => void;
  onSkip?: () => void;
};

const EMPTY: InsuranceFields = {
  provider: null,
  plan_name: null,
  member_id: null,
  group_number: null,
  name_on_card: null,
  bin: null,
  pcn: null,
  rx_group: null,
  effective_date: null,
  phone: null,
};

function hasGetUserMedia(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

export function InsuranceScanner({ hospitalId, value, onChange, onSkip }: Props) {
  const [cameraOpen, setCameraOpen] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!photo) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  async function handleCapture(file: File) {
    setCameraOpen(false);
    setPhoto(file);
    setBusy(true);
    setError(null);
    try {
      const { resizeImageIfNeeded } = await import("../../lib/image");
      const sized = await resizeImageIfNeeded(file);
      const resp = await scanInsurance(hospitalId, sized);
      if (!resp.success || !resp.fields) {
        setError(
          resp.error === "not_an_insurance_card"
            ? "Couldn't read this as an insurance card. Try a clearer, well-lit photo."
            : "We couldn't read the card. Retake or fill in the fields manually."
        );
        onChange({ ...EMPTY });
      } else {
        onChange({ ...EMPTY, ...resp.fields });
      }
    } catch (e: any) {
      setError(e?.message || "Scan failed.");
      onChange({ ...EMPTY });
    } finally {
      setBusy(false);
    }
  }

  function openPrimaryCamera() {
    if (hasGetUserMedia()) {
      setCameraOpen(true);
    } else {
      fileInputRef.current?.click();
    }
  }

  function update<K extends keyof InsuranceFields>(key: K, val: string) {
    onChange({ ...(value || EMPTY), [key]: val || null });
  }

  const scanned = !!value;

  return (
    <div className="flex flex-col gap-4">
      {!scanned && !busy && (
        <>
          <button
            type="button"
            onClick={openPrimaryCamera}
            className="w-full rounded-lg bg-surface-low hover:bg-primary-dim transition-colors py-8 flex flex-col items-center gap-2 active:scale-[0.99]"
          >
            <div className="w-14 h-14 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
              <CreditCard size={26} />
            </div>
            <div className="font-semibold tracking-editorial">Scan your insurance card</div>
            <div className="text-xs text-text-muted px-6 text-center">
              We'll read the fields automatically.
            </div>
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="self-center inline-flex items-center gap-1 text-sm text-text-muted underline underline-offset-2 px-3 py-1"
          >
            <ImagePlus size={14} /> or upload a photo
          </button>
        </>
      )}

      {busy && (
        <div className="w-full rounded-lg bg-primary-fixed/40 py-10 flex flex-col items-center gap-3">
          <Loader2 size={32} className="animate-spin text-primary" />
          <div className="text-sm text-primary font-medium">Reading your card…</div>
        </div>
      )}

      {preview && !busy && (
        <div className="relative">
          <img src={preview} alt="Insurance card" className="w-full rounded-lg shadow-soft" />
          <div className="absolute top-3 right-3 flex gap-2">
            <button
              type="button"
              onClick={openPrimaryCamera}
              className="bg-surface-lowest/90 backdrop-blur w-10 h-10 rounded-full flex items-center justify-center shadow-soft"
              aria-label="Rescan"
            >
              <RefreshCw size={18} />
            </button>
            <button
              type="button"
              onClick={() => {
                setPhoto(null);
                onChange(null);
                setError(null);
              }}
              className="bg-surface-lowest/90 backdrop-blur w-10 h-10 rounded-full flex items-center justify-center shadow-soft"
              aria-label="Remove"
            >
              <X size={18} />
            </button>
          </div>
        </div>
      )}

      {error && !busy && (
        <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
      )}

      {scanned && !busy && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 text-sm text-primary">
              <CheckCircle2 size={16} /> Confirm the details
            </div>
            <button
              type="button"
              onClick={openPrimaryCamera}
              className="inline-flex items-center gap-1 text-sm text-primary font-medium hover:text-primary-hover"
            >
              <RefreshCw size={14} /> Rescan card
            </button>
          </div>
          <Row label="Insurer" value={value!.provider} onChange={(v) => update("provider", v)} />
          <Row label="Plan" value={value!.plan_name} onChange={(v) => update("plan_name", v)} />
          <Row label="Member ID" value={value!.member_id} onChange={(v) => update("member_id", v)} />
          <Row label="Group" value={value!.group_number} onChange={(v) => update("group_number", v)} />
          <Row
            label="Name on card"
            value={value!.name_on_card}
            onChange={(v) => update("name_on_card", v)}
          />
        </div>
      )}

      {!scanned && !busy && onSkip && (
        <button
          type="button"
          onClick={onSkip}
          className="text-sm text-text-muted underline self-center h-10 px-2"
        >
          Skip — I don't have it on me
        </button>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleCapture(f);
        }}
      />

      {cameraOpen && (
        <InAppCamera
          label="Scan your insurance card"
          aspectHint="card"
          onCapture={handleCapture}
          onClose={() => setCameraOpen(false)}
        />
      )}
    </div>
  );
}

function Row({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted mb-1">{label}</div>
      <input
        type="text"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder="—"
        className="w-full h-11 px-3 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
      />
    </div>
  );
}
