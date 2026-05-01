import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Keyboard, Loader2, Mic } from "lucide-react";
import { MicButton } from "../components/patient/MicButton";
import { MedicalInfoForm } from "../components/patient/MedicalInfoForm";
import { PhotoCapture } from "../components/patient/PhotoCapture";
import { FollowupQuestions, toAnswerList } from "../components/patient/FollowupQuestions";
import { InsuranceScanner } from "../components/patient/InsuranceScanner";
import { LanguageGate } from "../components/patient/LanguageGate";
import { Button } from "../components/ui/Button";
import { ProgressDots } from "../components/ui/ProgressDots";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { postIntake, postTranscribe, startIntake } from "../lib/api";
import { isRTL, t, type LangCode } from "../lib/i18n";
import type { FollowupQuestion, InsuranceFields, MedicalInfo } from "../types";

type Step = "language" | "welcome" | "medical" | "insurance" | "record" | "followups" | "submitting";

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

const stepOrder: Step[] = ["language", "welcome", "medical", "insurance", "record", "followups", "submitting"];

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export default function PatientIntake() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const navigate = useNavigate();
  const recorder = useAudioRecorder();

  const [step, setStep] = useState<Step>("language");
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
  const [preferredLanguage, setPreferredLanguage] = useState<LangCode>("en");
  const [followups, setFollowups] = useState<FollowupQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [intakeToken, setIntakeToken] = useState<string | null>(null);
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());
  const [consentGranted, setConsentGranted] = useState(false);
  const CONSENT_VERSION = "1.0";

  // Mirror the chosen language onto <html dir> so RTL scripts (Arabic/Persian/Urdu)
  // flow correctly without reshuffling the whole layout module.
  useEffect(() => {
    const dir = isRTL(preferredLanguage) ? "rtl" : "ltr";
    document.documentElement.setAttribute("dir", dir);
    document.documentElement.setAttribute("lang", preferredLanguage);
    return () => {
      document.documentElement.setAttribute("dir", "ltr");
      document.documentElement.setAttribute("lang", "en");
    };
  }, [preferredLanguage]);

  useEffect(() => {
    startIntake(hospitalId)
      .then((r) => setIntakeToken(r.token))
      .catch(() => { /* submit will surface a clean error */ });
  }, [hospitalId]);

  // Step counter excludes the language gate and submitting screen — keeps the dots honest.
  const userSteps = stepOrder.filter((s) => s !== "language" && s !== "submitting");
  const currentUserStep = userSteps.indexOf(step as (typeof userSteps)[number]);

  function canAdvance(): boolean {
    if (step === "language") return true;
    if (step === "welcome") return name.trim().length > 0 && consentGranted;
    if (step === "medical") return medical.age !== null && !!medical.sex;
    if (step === "insurance") return true;
    if (step === "record") {
      if (inputMode === "type" || recorder.permissionDenied) return textFallback.trim().length > 3;
      return !!recorder.audioBlob;
    }
    if (step === "followups") return followups.every((q) => answers[q.id]?.trim());
    return false;
  }

  async function transcribeWithRetry(): Promise<void> {
    const form = new FormData();
    const usingVoice =
      inputMode === "voice" && !recorder.permissionDenied && !!recorder.audioBlob;
    if (usingVoice && recorder.audioBlob) {
      form.append("audio_file", recorder.audioBlob, "intake.webm");
    } else {
      form.append("pre_transcribed_text", textFallback.trim());
    }
    form.append("medical_info", JSON.stringify(medical));
    form.append("preferred_language", preferredLanguage);

    let attempt = 0;
    while (true) {
      try {
        const resp = await postTranscribe(hospitalId, form);
        setTranscript(resp.transcript);
        setLanguage(resp.language);
        setFollowups(resp.followups);
        if (resp.followups.length === 0) {
          await finalize(resp.transcript, []);
        } else {
          setStep("followups");
        }
        return;
      } catch (e: any) {
        const status = e?.response?.status;
        // Auto-retry once on 429 (rate-limit) or transient 5xx after a short backoff.
        // Whisper/Claude can be flaky — a single retry usually clears it without
        // making the patient touch the button again.
        if (attempt < 1 && (status === 429 || status === 503 || status === 502 || status === 504)) {
          attempt += 1;
          await sleep(1500);
          continue;
        }
        throw e;
      }
    }
  }

  async function handleNext() {
    if (!canAdvance() || busy) return;
    setError(null);

    if (step === "language") return setStep("welcome");
    if (step === "welcome") return setStep("medical");
    if (step === "medical") return setStep("insurance");
    if (step === "insurance") return setStep("record");

    if (step === "record") {
      setBusy(true);
      try {
        await transcribeWithRetry();
      } catch (e: any) {
        const status = e?.response?.status;
        const detail = e?.response?.data?.detail || "";
        const isTranscriptionDown =
          /transcription/i.test(detail) || /whisper/i.test(detail) || status === 503;
        if (isTranscriptionDown && inputMode === "voice") {
          setInputMode("type");
          setError(t("error_transcription_down", preferredLanguage));
        } else if (status === 429) {
          setError(t("error_rate_limited", preferredLanguage));
        } else if (!status && /network|fetch|abort|timeout/i.test(e?.message || "")) {
          setError(t("error_network", preferredLanguage));
        } else {
          setError(detail || e?.message || t("error_generic", preferredLanguage));
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
      const status = e?.response?.status;
      if (status === 429) {
        setError(t("error_rate_limited", preferredLanguage));
      } else if (!status && /network|fetch|abort|timeout/i.test(e?.message || "")) {
        setError(t("error_network", preferredLanguage));
      } else {
        setError(e?.response?.data?.detail || e?.message || t("error_generic", preferredLanguage));
      }
      setStep("followups");
    } finally {
      setBusy(false);
    }
  }

  function handleBack() {
    const idx = stepOrder.indexOf(step);
    if (idx > 0) setStep(stepOrder[idx - 1]);
  }

  // Language gate is its own full-screen layout — bypasses the normal header/footer.
  if (step === "language") {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-surface-lowest">
        <LanguageGate
          selected={preferredLanguage}
          onSelect={setPreferredLanguage}
          onContinue={() => setStep("welcome")}
        />
      </div>
    );
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
              aria-label={t("back_button", preferredLanguage)}
              className="w-10 h-10 rounded-full hover:bg-surface-low flex items-center justify-center"
            >
              <ArrowLeft size={20} />
            </button>
          )}
          <img
            src="/solace-logo.png"
            alt="Solace"
            className="h-10 sm:h-14 md:h-20 w-auto select-none shrink-0"
            draggable={false}
          />
        </div>
        {step !== "submitting" && (
          <ProgressDots total={userSteps.length - 1} current={currentUserStep + 1} />
        )}
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
                    {t("welcome_title", preferredLanguage)}
                  </h1>
                  <p className="text-text-muted">
                    {t("welcome_subtitle", preferredLanguage)}
                  </p>
                </div>
                <div>
                  <label className="text-sm font-semibold block mb-2" htmlFor="name">
                    {t("first_name_label", preferredLanguage)}
                  </label>
                  <input
                    id="name"
                    type="text"
                    autoComplete="given-name"
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("first_name_placeholder", preferredLanguage)}
                    className="w-full h-14 px-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-lg outline-none transition-all"
                  />
                </div>

                <button
                  type="button"
                  onClick={() => setStep("language")}
                  className="text-xs text-primary underline self-start"
                >
                  {t("language_gate_title", preferredLanguage)} →
                </button>

                <div className="rounded-lg bg-surface-lowest p-4 border border-[rgba(74,85,87,0.12)]">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={consentGranted}
                      onChange={(e) => setConsentGranted(e.target.checked)}
                      className="mt-1 h-4 w-4 rounded border-line accent-primary"
                    />
                    <div className="flex-1 text-[13px] leading-relaxed text-ink">
                      <span className="font-semibold">
                        {t("consent_lead", preferredLanguage)}
                      </span>{" "}
                      {t("consent_body", preferredLanguage)}
                      <div className="mt-1.5 text-[11px] text-text-muted">
                        {t("consent_decline", preferredLanguage)} (v{CONSENT_VERSION})
                      </div>
                    </div>
                  </label>
                </div>
              </>
            )}

            {step === "medical" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">
                    {t("medical_title", preferredLanguage)}
                  </h2>
                  <p className="text-text-muted text-sm">
                    {t("medical_subtitle", preferredLanguage)}
                  </p>
                </div>
                <MedicalInfoForm value={medical} onChange={setMedical} language={preferredLanguage} />
              </>
            )}

            {step === "insurance" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">
                    {t("insurance_title", preferredLanguage)}
                  </h2>
                  <p className="text-text-muted text-sm">
                    {t("insurance_subtitle", preferredLanguage)}
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
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">
                    {t("record_title", preferredLanguage)}
                  </h2>
                  <p className="text-text-muted text-sm">
                    {inputMode === "voice"
                      ? t("record_subtitle_voice", preferredLanguage)
                      : t("record_subtitle_type", preferredLanguage)}
                  </p>
                </div>

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
                    <Mic size={14} /> {t("record_voice_tab", preferredLanguage)}
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
                    <Keyboard size={14} /> {t("record_type_tab", preferredLanguage)}
                  </button>
                </div>

                {inputMode === "type" || recorder.permissionDenied ? (
                  <div className="flex flex-col gap-2">
                    <textarea
                      value={textFallback}
                      onChange={(e) => setTextFallback(e.target.value)}
                      rows={6}
                      className="w-full p-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
                      placeholder={t("record_textarea_placeholder", preferredLanguage)}
                      autoFocus
                    />
                    {recorder.permissionDenied && (
                      <p className="text-xs text-text-muted">
                        {t("record_mic_denied", preferredLanguage)}
                      </p>
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
                        {t("record_captured", preferredLanguage)} ({recorder.elapsed}s)
                        <button type="button" className="text-text-muted underline" onClick={recorder.reset}>
                          {t("record_rerecord", preferredLanguage)}
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
                  <h2 className="text-2xl font-bold tracking-editorial mb-1">
                    {t("followups_title", preferredLanguage)}
                  </h2>
                  <p className="text-text-muted text-sm">
                    {t("followups_subtitle", preferredLanguage)}
                  </p>
                </div>
                <FollowupQuestions
                  questions={followups}
                  answers={answers}
                  onAnswer={(id, _q, a) => setAnswers((prev) => ({ ...prev, [id]: a }))}
                  language={preferredLanguage}
                />
              </>
            )}

            {step === "submitting" && (
              <div className="flex flex-col items-center justify-center py-24 gap-4">
                <Loader2 size={48} className="animate-spin text-primary" />
                <div className="text-lg font-semibold tracking-editorial">
                  {t("submitting_title", preferredLanguage)}
                </div>
                <div className="text-sm text-text-muted">
                  {t("submitting_subtitle", preferredLanguage)}
                </div>
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
                <Loader2 size={18} className="animate-spin" /> {t("working_button", preferredLanguage)}
              </>
            ) : step === "record" ? (
              <>
                {t("continue_button", preferredLanguage)} <ArrowRight size={18} />
              </>
            ) : step === "followups" ? (
              t("submit_button", preferredLanguage)
            ) : (
              <>
                {t("next_button", preferredLanguage)} <ArrowRight size={18} />
              </>
            )}
          </Button>
          <div className="text-[10px] text-text-muted text-center mt-2 leading-relaxed">
            {t("footer_disclaimer", preferredLanguage)}
          </div>
        </footer>
      )}
    </div>
  );
}
