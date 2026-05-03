import { useEffect, useRef, useState } from "react";
import { CheckCircle2, IdCard, ImagePlus, Loader2, RefreshCw, X, UserCheck } from "lucide-react";
import { InAppCamera } from "../ui/InAppCamera";
import { scanID, identityLookup, type IdFields, type IdentityLookupResult } from "../../lib/api";

type Props = {
  hospitalId: string;
  onMatched: (result: IdentityLookupResult) => void;
  onSkip: () => void;
  language: string;
};

function hasGetUserMedia(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

/**
 * Optional first step in patient intake. Patient scans their driver's license,
 * we OCR via Claude vision, then look up against the connected EHR. If we get
 * a match, we surface "welcome back" and pre-fill demographics + medical info
 * so the rest of the intake is a confirmation flow rather than a data-entry one.
 */
export function IdScanner({ hospitalId, onMatched, onSkip, language }: Props) {
  const [cameraOpen, setCameraOpen] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<IdFields | null>(null);
  const [lookup, setLookup] = useState<IdentityLookupResult | null>(null);
  const [stage, setStage] = useState<"capture" | "scanning" | "looking-up" | "matched" | "no-match">(
    "capture"
  );
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
    setError(null);
    setStage("scanning");
    try {
      const { resizeImageIfNeeded } = await import("../../lib/image");
      const sized = await resizeImageIfNeeded(file);
      const resp = await scanID(hospitalId, sized);
      if (!resp.success || !resp.fields) {
        setError(
          resp.error === "not_an_id_card"
            ? "That doesn't look like a driver's license. Try again with a clearer photo."
            : "Couldn't read the ID. Retake the photo or skip and enter your info manually."
        );
        setStage("capture");
        setFields(null);
        return;
      }
      setFields(resp.fields);
      setStage("looking-up");
      const lk = await identityLookup(hospitalId, {
        first_name: resp.fields.first_name,
        last_name: resp.fields.last_name,
        dob: resp.fields.dob,
        license_number: resp.fields.license_number,
        issuing_state: resp.fields.issuing_state,
      });
      setLookup(lk);
      setStage(lk.matched ? "matched" : "no-match");
    } catch (e: any) {
      const status = e?.response?.status;
      const detail: string | undefined = e?.response?.data?.detail;
      setError(
        status === 415
          ? "Try a JPEG or PNG — your phone's HEIC format isn't supported."
          : status === 413
          ? "Photo is too large — try a closer crop."
          : detail || e?.message || "Couldn't send the photo. Check your connection and retake."
      );
      setStage("capture");
    }
  }

  function openCamera() {
    if (hasGetUserMedia()) setCameraOpen(true);
    else fileInputRef.current?.click();
  }

  function reset() {
    setPhoto(null);
    setPreview(null);
    setFields(null);
    setLookup(null);
    setError(null);
    setStage("capture");
  }

  // dir attr for RTL languages (Arabic / Persian / Urdu)
  const isRTL = ["ar", "fa", "ur"].includes(language);

  return (
    <div className="flex flex-col gap-4" dir={isRTL ? "rtl" : "ltr"}>
      {stage === "capture" && (
        <>
          <button
            type="button"
            onClick={openCamera}
            className="w-full rounded-lg bg-surface-low hover:bg-primary-fixed transition-colors py-8 flex flex-col items-center gap-2 active:scale-[0.99]"
          >
            <div className="w-14 h-14 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
              <IdCard size={26} />
            </div>
            <div className="font-semibold">Scan your driver's license</div>
            <div className="text-xs text-text-muted px-6 text-center">
              We'll auto-fill your info and pull your medical history if you've been here before.
            </div>
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="self-center inline-flex items-center gap-1 text-sm text-text-muted underline underline-offset-2 px-3 py-1"
          >
            <ImagePlus size={14} /> or upload a photo
          </button>
          <button
            type="button"
            onClick={onSkip}
            className="text-sm text-text-muted underline self-center h-10 px-2"
          >
            Skip — I don't have my ID on me
          </button>
        </>
      )}

      {(stage === "scanning" || stage === "looking-up") && (
        <div className="w-full rounded-lg bg-primary-fixed/40 py-10 flex flex-col items-center gap-3">
          <Loader2 size={32} className="animate-spin text-primary" />
          <div className="text-sm text-primary font-medium">
            {stage === "scanning" ? "Reading your ID…" : "Checking the EHR for your record…"}
          </div>
        </div>
      )}

      {preview && stage !== "capture" && stage !== "scanning" && (
        <div className="relative">
          <img src={preview} alt="ID preview" className="w-full rounded-lg shadow-soft" />
          <div className="absolute top-3 right-3 flex gap-2">
            <button
              type="button"
              onClick={reset}
              className="bg-surface-lowest/90 backdrop-blur w-10 h-10 rounded-full flex items-center justify-center shadow-soft"
              aria-label="Rescan"
            >
              <RefreshCw size={18} />
            </button>
            <button
              type="button"
              onClick={() => {
                setPhoto(null);
                setPreview(null);
                onSkip();
              }}
              className="bg-surface-lowest/90 backdrop-blur w-10 h-10 rounded-full flex items-center justify-center shadow-soft"
              aria-label="Cancel"
            >
              <X size={18} />
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
      )}

      {stage === "matched" && lookup?.matched && lookup.ehr_record && fields && (
        <div className="rounded-lg bg-primary-fixed/60 ring-2 ring-primary p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-primary">
            <UserCheck size={20} />
            <div className="font-bold tracking-tight text-lg">
              Welcome back, {fields.first_name}.
            </div>
          </div>
          <div className="text-[13px] leading-relaxed text-ink">
            We found your record in the EHR ({lookup.match_method?.replace(/_/g, " ")}). Your{" "}
            <span className="font-semibold">
              {lookup.prefill?.allergies?.length ?? 0} allergies
            </span>
            ,{" "}
            <span className="font-semibold">
              {lookup.prefill?.medications?.length ?? 0} medications
            </span>
            , and{" "}
            <span className="font-semibold">
              {lookup.prefill?.conditions?.length ?? 0} conditions
            </span>{" "}
            will be pre-filled.
            {lookup.prefill?.prior_visits_count
              ? ` ${lookup.prefill.prior_visits_count} prior visit${
                  lookup.prefill.prior_visits_count === 1 ? "" : "s"
                } on file.`
              : ""}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onMatched(lookup)}
              className="flex-1 h-11 rounded-md bg-primary text-white font-semibold text-sm shadow-soft"
            >
              Continue with this record
            </button>
            <button
              type="button"
              onClick={() => onSkip()}
              className="h-11 px-4 rounded-md text-sm text-text-muted hover:text-error border border-line"
              title="Continue without using this record"
            >
              Not me
            </button>
          </div>
        </div>
      )}

      {stage === "no-match" && fields && (
        <div className="rounded-lg bg-surface-low p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-text-muted">
            <CheckCircle2 size={18} />
            <div className="font-semibold tracking-tight">
              ID read · no prior record on file
            </div>
          </div>
          <div className="text-[13px] leading-relaxed text-ink">
            <span className="font-semibold">{fields.first_name} {fields.last_name}</span>
            {fields.dob && <> · DOB <span className="font-mono">{fields.dob}</span></>}.
            We'll continue with a fresh intake.
          </div>
          <button
            type="button"
            onClick={() => onMatched({ matched: false, prefill: undefined, ehr_record: undefined })}
            className="h-11 rounded-md bg-primary text-white font-semibold text-sm shadow-soft"
          >
            Continue
          </button>
        </div>
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
          label="Scan your driver's license"
          aspectHint="card"
          onCapture={handleCapture}
          onClose={() => setCameraOpen(false)}
        />
      )}
    </div>
  );
}
