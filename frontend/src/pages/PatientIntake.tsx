import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Keyboard, Loader2, Mic } from "lucide-react";
import { MicButton } from "../components/patient/MicButton";
import { MedicalInfoForm } from "../components/patient/MedicalInfoForm";
import { PhotoCapture } from "../components/patient/PhotoCapture";
import { FollowupQuestions, toAnswerList } from "../components/patient/FollowupQuestions";
import { InsuranceScanner } from "../components/patient/InsuranceScanner";
import { Button } from "../components/ui/Button";
import { ProgressDots } from "../components/ui/ProgressDots";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { postIntake, postTranscribe, startIntake } from "../lib/api";
import type { FollowupQuestion, InsuranceFields, MedicalInfo } from "../types";

type Step = "welcome" | "medical" | "insurance" | "record" | "followups" | "submitting";

const emptyMedical: MedicalInfo = {
  age: null,
  sex: null,
  pregnant: null,
  gestational_weeks: null,
  allergies: [],
  allergy_severity: {},
  medications: [],
  blood_thinner_name: null,
  conditions: [],
  diabetes_type: null,
  heart_failure_class: null,
  smoker: null,
};

const stepOrder: Step[] = ["welcome", "medical", "insurance", "record", "followups", "submitting"];

export default function PatientIntake() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const navigate = useNavigate();
  const recorder = useAudioRecorder();

  const [step, setStep] = useState<Step>("welcome");
  const [name, setName] = useState("");
  const [medical, setMedical] = useState<MedicalInfo>(emptyMedical);
  const [insurance, setInsurance] = useState<InsuranceFields | null>(null);
  const [photo, setPhoto] = useState<File | null>(null);
  const [textFallback, setTextFallback] = useState("");
  const [inputMode, setInputMode] = useState<"voice" | "type">("voice");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [transcript, setTranscript] = useState<string>("");
  const [, setLanguage] = useState<string>("en");
  const [preferredLanguage, setPreferredLanguage] = useState<string>("en");
  const [followups, setFollowups] = useState<FollowupQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [intakeToken, setIntakeToken] = useState<string | null>(null);
  // Stable per-session idempotency key — same retry = same result from backend
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());
  const [consentGranted, setConsentGranted] = useState(false);
  const CONSENT_VERSION = "1.0";

  // Fetch a one-use intake nonce as soon as the patient lands. Required by /intake.
  useEffect(() => {
    startIntake(hospitalId)
      .then((r) => setIntakeToken(r.token))
      .catch(() => { /* submit will surface a clean error */ });
  }, [hospitalId]);

  const stepIndex = stepOrder.indexOf(step) + 1;

  function canAdvance(): boolean {
    if (step === "welcome") return name.trim().length > 0 && consentGranted;
    if (step === "medical") return medical.age !== null && !!medical.sex;
    if (step === "insurance") return true; // optional — can always continue
    if (step === "record") {
      if (inputMode === "type" || recorder.permissionDenied) return textFallback.trim().length > 3;
      return !!recorder.audioBlob;
    }
    if (step === "followups") return followups.every((q) => answers[q.id]?.trim());
    return false;
  }

  async function handleNext() {
    if (!canAdvance() || busy) return;
    setError(null);

    if (step === "welcome") return setStep("medical");
    if (step === "medical") return setStep("insurance");
    if (step === "insurance") return setStep("record");

    if (step === "record") {
      setBusy(true);
      try {
        const form = new FormData();
        const usingVoice =
          inputMode === "voice" && !recorder.permissionDenied && !!recorder.audioBlob;
        if (usingVoice && recorder.audioBlob) {
          form.append("audio_file", recorder.audioBlob, "intake.webm");
        } else {
          form.append("pre_transcribed_text", textFallback.trim());
        }
        form.append("medical_info", JSON.stringify(medical));
        const resp = await postTranscribe(hospitalId, form);
        setTranscript(resp.transcript);
        setLanguage(resp.language);
        setFollowups(resp.followups);
        if (resp.followups.length === 0) {
          await finalize(resp.transcript, []);
        } else {
          setStep("followups");
        }
      } catch (e: any) {
        const detail = e?.response?.data?.detail || "";
        const isTranscriptionDown =
          /transcription/i.test(detail) || /whisper/i.test(detail) || e?.response?.status === 503;
        if (isTranscriptionDown && inputMode === "voice") {
          setInputMode("type");
          setError(
            "Voice transcription is temporarily unavailable — please type your symptoms below and tap Next again."
          );
        } else {
          setError(detail || e?.message || "Something went wrong.");
        }
      } finally {
        setBusy(false);
      }
      return;
    }

    if (step === "followups") {
      await finalize(transcript, toAnswerList(followups, answers));
    }
  }

  async function buildIntakeForm(
    transcriptText: string,
    followupAnswers: { id: string; question: string; answer: string }[],
    tokenOverride?: string
  ): Promise<FormData> {
    const form = new FormData();
    form.append("patient_name", name.trim());
    form.append("pre_transcribed_text", transcriptText);
    form.append("medical_info", JSON.stringify(medical));
    form.append("followup_qa", JSON.stringify(followupAnswers));
    if (insurance) form.append("insurance_info", JSON.stringify(insurance));
    const tok = tokenOverride ?? intakeToken;
    if (tok) form.append("intake_token", tok);
    form.append("idempotency_key", idempotencyKeyRef.current);
    form.append("consent_granted", consentGranted ? "true" : "false");
    form.append("consent_version", CONSENT_VERSION);
    form.append("preferred_language", preferredLanguage);
    if (photo) {
      const { resizeImageIfNeeded } = await import("../lib/image");
      const sized = await resizeImageIfNeeded(photo);
      form.append("image_file", sized);
    }
    return form;
  }

  async function finalize(
    transcriptText: string,
    followupAnswers: { id: string; question: string; answer: string }[]
  ) {
    setStep("submitting");
    setBusy(true);
    try {
      const form = await buildIntakeForm(transcriptText, followupAnswers);
      let result;
      try {
        result = await postIntake(hospitalId, form);
      } catch (e: any) {
        // Nonce expired / already used / device-rebound — re-issue silently and retry
        // once. The idempotency key stays stable, so the backend dedupes if the first
        // request actually did land.
        const status = e?.response?.status;
        const detail: string = e?.response?.data?.detail || "";
        const isNonceFault =
          status === 403 && /intake token|scan the QR/i.test(detail);
        if (!isNonceFault) throw e;
        const fresh = await startIntake(hospitalId);
        setIntakeToken(fresh.token);
        const retryForm = await buildIntakeForm(transcriptText, followupAnswers, fresh.token);
        result = await postIntake(hospitalId, retryForm);
      }
      sessionStorage.setItem(`intake:${result.patient_id}`, JSON.stringify(result));
      navigate(`/${hospitalId}/result/${result.patient_id}`);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Something went wrong.");
      setStep("followups");
    } finally {
      setBusy(false);
    }
  }

  function handleBack() {
    const idx = stepOrder.indexOf(step);
    if (idx > 0) setStep(stepOrder[idx - 1]);
  }

  return (
    <div className="min-h-[100dvh] flex flex-col">
      <header
        className="flex items-center justify-between px-4 pb-3 bg-surface-lowest/85 backdrop-blur-xl sticky top-0 z-10 shadow-soft"
        style={{ paddingTop: "calc(1.25rem + env(safe-area-inset-top, 0px))" }}
      >
        <div className="flex items-center gap-2">
          {step !== "welcome" && step !== "submitting" && (
            <button
              onClick={handleBack}
              aria-label="Back"
              className="w-10 h-10 rounded-full hover:bg-surface-low flex items-center justify-center"
            >
              <ArrowLeft size={20} />
            </button>
          )}
          <img
            src="/solace-logo.png"
            alt="Solace"
            className="h-12 w-auto select-none"
            draggable={false}
          />
        </div>
        {step !== "submitting" && <ProgressDots total={stepOrder.length - 1} current={stepIndex} />}
      </header>

      <main className="flex-1 px-4 py-6 max-w-lg w-full mx-auto flex flex-col gap-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.2 }}
            className="flex flex-col gap-6"
          >
            {step === "welcome" && (
              <>
                <div>
                  <h1 className="text-3xl font-bold tracking-editorial-tight mb-2">
                    You're not waiting alone.
                  </h1>
                  <p className="text-text-muted">
                    Tell us your story once. By the time a clinician sees you, they'll already know.
                  </p>
                </div>
                <div>
                  <label className="text-sm font-semibold block mb-2" htmlFor="name">
                    Your first name
                  </label>
                  <input
                    id="name"
                    type="text"
                    autoComplete="given-name"
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Marcus"
                    className="w-full h-14 px-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-lg outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="text-sm font-semibold block mb-2" htmlFor="preferred-lang">
                    Preferred language
                  </label>
                  <select
                    id="preferred-lang"
                    value={preferredLanguage}
                    onChange={(e) => setPreferredLanguage(e.target.value)}
                    className="w-full h-12 px-3 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
                  >
                    <option value="en">English</option>
                    <option value="es">Español (Spanish)</option>
                    <option value="zh">中文 (Mandarin)</option>
                    <option value="vi">Tiếng Việt (Vietnamese)</option>
                    <option value="ar">العربية (Arabic)</option>
                    <option value="fr">Français (French)</option>
                    <option value="pt">Português (Portuguese)</option>
                    <option value="ko">한국어 (Korean)</option>
                  </select>
                  <p className="mt-1 text-[11px] text-text-muted">
                    We'll transcribe your voice and speak the comfort protocol back in this language.
                  </p>
                </div>

                <div className="rounded-lg bg-surface-lowest p-4 border border-[rgba(74,85,87,0.12)]">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={consentGranted}
                      onChange={(e) => setConsentGranted(e.target.checked)}
                      className="mt-1 h-4 w-4 rounded border-line accent-primary"
                    />
                    <div className="flex-1 text-[13px] leading-relaxed text-ink">
                      <span className="font-semibold">I consent to AI processing.</span>{" "}
                      My voice recording, symptoms, and any photos I upload will be sent to
                      third-party AI services (<span className="font-mono text-[12px]">OpenAI</span> for
                      voice transcription, <span className="font-mono text-[12px]">Anthropic</span> for
                      triage and scribe notes, <span className="font-mono text-[12px]">ElevenLabs</span>{" "}
                      for the audio response). Each patient visit appends an attribution log so the
                      clinician can see exactly which provider saw which data.
                      <div className="mt-1.5 text-[11px] text-text-muted">
                        Decline by refreshing the page and asking a front-desk worker to collect your
                        info manually. Consent version {CONSENT_VERSION}.
                      </div>
                    </div>
                  </label>
                </div>
              </>
            )}

            {step === "medical" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">A few medical details</h2>
                  <p className="text-text-muted text-sm">So the clinician doesn't have to ask later.</p>
                </div>
                <MedicalInfoForm value={medical} onChange={setMedical} />
              </>
            )}

            {step === "insurance" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">Insurance (optional)</h2>
                  <p className="text-text-muted text-sm">
                    Snap a picture and we'll auto-fill the details. You can also skip this.
                  </p>
                </div>
                <InsuranceScanner
                  hospitalId={hospitalId}
                  value={insurance}
                  onChange={setInsurance}
                  onSkip={() => setStep("record")}
                />
              </>
            )}

            {step === "record" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">What's going on?</h2>
                  <p className="text-text-muted text-sm">
                    {inputMode === "voice"
                      ? "Speak naturally for 20-60 seconds. Or type if it's loud."
                      : "Write what's happening. A few sentences is enough."}
                  </p>
                </div>

                {/* Mode toggle — mic vs keyboard */}
                <div className="inline-flex self-start rounded-md bg-surface-low p-1">
                  <button
                    type="button"
                    onClick={() => setInputMode("voice")}
                    className={`inline-flex items-center gap-1.5 h-9 px-3 rounded text-sm font-medium transition-colors ${
                      inputMode === "voice" && !recorder.permissionDenied
                        ? "bg-surface-lowest text-ink shadow-soft"
                        : "text-text-muted"
                    }`}
                    disabled={recorder.permissionDenied}
                  >
                    <Mic size={14} /> Voice
                  </button>
                  <button
                    type="button"
                    onClick={() => setInputMode("type")}
                    className={`inline-flex items-center gap-1.5 h-9 px-3 rounded text-sm font-medium transition-colors ${
                      inputMode === "type" || recorder.permissionDenied
                        ? "bg-surface-lowest text-ink shadow-soft"
                        : "text-text-muted"
                    }`}
                  >
                    <Keyboard size={14} /> Type
                  </button>
                </div>

                {inputMode === "type" || recorder.permissionDenied ? (
                  <div className="flex flex-col gap-2">
                    <textarea
                      value={textFallback}
                      onChange={(e) => setTextFallback(e.target.value)}
                      rows={6}
                      className="w-full p-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
                      placeholder="Describe your symptoms — what hurts, when it started, how bad it feels, anything else going on."
                      autoFocus
                    />
                    {recorder.permissionDenied && (
                      <p className="text-xs text-text-muted">Mic access was denied.</p>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-4 py-8 bg-primary-fixed/40 rounded-lg">
                    <MicButton
                      isRecording={recorder.isRecording}
                      elapsed={recorder.elapsed}
                      onStart={recorder.start}
                      onStop={recorder.stop}
                    />
                    {recorder.audioBlob && !recorder.isRecording && (
                      <div className="text-sm text-primary flex items-center gap-3">
                        Recording captured ({recorder.elapsed}s)
                        <button type="button" className="text-text-muted underline" onClick={recorder.reset}>
                          re-record
                        </button>
                      </div>
                    )}
                  </div>
                )}

                <PhotoCapture file={photo} onChange={setPhoto} />
              </>
            )}

            {step === "followups" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">A few quick questions</h2>
                  <p className="text-text-muted text-sm">
                    These help us give your clinician a complete picture.
                  </p>
                </div>
                <FollowupQuestions
                  questions={followups}
                  answers={answers}
                  onAnswer={(id, _q, a) => setAnswers((prev) => ({ ...prev, [id]: a }))}
                />
              </>
            )}

            {step === "submitting" && (
              <div className="flex flex-col items-center justify-center py-24 gap-4">
                <Loader2 size={48} className="animate-spin text-primary" />
                <div className="text-lg font-semibold tracking-editorial">Finalizing your assessment…</div>
                <div className="text-sm text-text-muted">Generating your pre-brief for the clinician.</div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        {error && (
          <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
        )}
      </main>

      {step !== "submitting" && (
        <footer
          className="sticky bottom-0 bg-surface-lowest/95 backdrop-blur-xl px-4 pt-4 shadow-glass"
          style={{ paddingBottom: "calc(1rem + env(safe-area-inset-bottom, 0px))" }}
        >
          <Button variant="primary" fullWidth disabled={!canAdvance() || busy} onClick={handleNext}>
            {busy ? (
              <>
                <Loader2 size={18} className="animate-spin" /> Working…
              </>
            ) : step === "record" ? (
              <>
                Continue <ArrowRight size={18} />
              </>
            ) : step === "followups" ? (
              "Submit"
            ) : (
              <>
                Next <ArrowRight size={18} />
              </>
            )}
          </Button>
          <div className="text-[10px] text-text-muted text-center mt-2 leading-relaxed">
            Triage aid only. Clinicians always verify. If life-threatening, go to the front desk now.
          </div>
        </footer>
      )}
    </div>
  );
}
