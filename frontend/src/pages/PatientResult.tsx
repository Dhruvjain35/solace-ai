import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Leaf, ShieldCheck, AlertTriangle, ArrowRight, Hospital,
  Home, Video, Clock, MessageSquare, Loader2, Check,
} from "lucide-react";
import { AudioPlayer } from "../components/patient/AudioPlayer";
import { ComfortProtocol } from "../components/patient/ComfortProtocol";
import { ESIBadge } from "../components/patient/ESIBadge";
import { PainEscalateButton } from "../components/patient/PainEscalateButton";
import { getPublicPatient, sendCareInstructionsSelfServe } from "../lib/api";
import type { IntakeResponse, PatientEducation } from "../types";

const POLL_MS = 15_000;

// Comfort guidance + the spoken audio are generated out-of-band by the backend
// AFTER the fast intake response returns (this is what keeps intake under API
// Gateway's 30s timeout). The result screen shows ESI + explanation instantly,
// then polls the public-patient endpoint on a short, capped cadence for the two
// deferred patient-facing artifacts. This is a short-lived active wait for the
// patient's OWN result — distinct from the clinician dashboard's >=10s
// background poll (PERF-005) — so we use a tighter 3s cadence with a hard cap.
const COMFORT_POLL_MS = 3_000;
const COMFORT_POLL_MAX_ATTEMPTS = 15; // ~45s ceiling, then we stop trying.

// Plain-language "what this means" for each ESI level. Written to reassure a
// stressed patient: it explains the priority number without medical jargon and
// without ever implying their wait is unsafe.
const ESI_MEANING: Record<number, { headline: string; body: string }> = {
  1: {
    headline: "You need care right now",
    body: "Our team has been alerted and is coming to you. Please stay where you are.",
  },
  2: {
    headline: "You'll be seen very soon",
    body: "Your symptoms need prompt attention. You're near the front of the line — please stay close.",
  },
  3: {
    headline: "You'll be seen as soon as a clinician is free",
    body: "Your symptoms are being taken seriously. More urgent cases may go first, but you have not been forgotten.",
  },
  4: {
    headline: "Your wait may be a little longer today",
    body: "Your symptoms appear stable. We'll bring you in as soon as we can — let the front desk know if anything changes.",
  },
  5: {
    headline: "Your symptoms appear stable",
    body: "You can be seen here, or your care team may suggest a clinic or telehealth visit instead. Either way, you'll get an answer today.",
  },
};

export default function PatientResult() {
  const { hospitalId = "demo", patientId = "" } = useParams<{ hospitalId: string; patientId: string }>();
  const [result, setResult] = useState<IntakeResponse | null>(null);
  const [education, setEducation] = useState<PatientEducation | null>(null);
  const [educationPublishedAt, setEducationPublishedAt] = useState<string | null>(null);
  const [waitRange, setWaitRange] = useState<string | null>(null);
  const [careRec, setCareRec] = useState<NonNullable<IntakeResponse["care_recommendation"]> | null>(null);
  // Deferred comfort/audio: pending until the backend worker fills them in.
  const [comfortPending, setComfortPending] = useState(true);

  useEffect(() => {
    const raw = sessionStorage.getItem(`intake:${patientId}`);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as IntakeResponse;
        setResult(parsed);
        if (parsed.care_recommendation) setCareRec(parsed.care_recommendation);
        // The fast intake response now seeds comfort/audio as pending — if a
        // (re-)mount somehow already has comfort actions, mark it loaded.
        if (parsed.comfort_protocol && parsed.comfort_protocol.length > 0) {
          setComfortPending(false);
        }
      } catch {
        /* ignore */
      }
    }
  }, [patientId]);

  // Short, capped poll for the DEFERRED comfort guidance + audio. Stops as soon
  // as comfort actions arrive (audio may stay null if TTS is disabled) or once
  // the attempt cap is hit, so we never poll forever for a hospital with TTS off.
  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    let timer: number | null = null;
    let attempts = 0;

    async function tick() {
      attempts += 1;
      try {
        const p = await getPublicPatient(hospitalId, patientId);
        if (cancelled) return;
        const ready = (p.comfort_protocol && p.comfort_protocol.length > 0) || p.comfort_ready;
        const failed = p.artifacts_status === "failed";
        if (ready || failed) {
          setResult((prev) =>
            prev
              ? { ...prev, comfort_protocol: p.comfort_protocol ?? [], audio_url: p.audio_url ?? null }
              : prev
          );
          setComfortPending(false);
          return; // done — stop polling
        }
      } catch {
        // swallow — retry on the next tick (within the cap)
      } finally {
        if (!cancelled && attempts < COMFORT_POLL_MAX_ATTEMPTS) {
          timer = window.setTimeout(tick, COMFORT_POLL_MS);
        } else if (!cancelled) {
          // Cap reached without comfort — drop the spinner so the section
          // doesn't spin indefinitely.
          setComfortPending(false);
        }
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [hospitalId, patientId]);

  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    let timer: number | null = null;

    async function tick() {
      try {
        const p = await getPublicPatient(hospitalId, patientId);
        if (cancelled) return;
        if (p.patient_education) {
          setEducation(p.patient_education);
          setEducationPublishedAt(p.patient_education_published_at);
        }
        if (p.wait_estimate_range) setWaitRange(p.wait_estimate_range);
        if (p.care_recommendation && !careRec) setCareRec(p.care_recommendation);
      } catch {
        // swallow — we'll try again next tick
      } finally {
        if (!cancelled) timer = window.setTimeout(tick, POLL_MS);
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [hospitalId, patientId]);

  if (!result) {
    return (
      <div className="min-h-[100dvh] flex flex-col items-center justify-center gap-3 p-6 text-center">
        <Loader2 size={28} className="animate-spin text-primary" aria-hidden="true" />
        <div className="text-[15px] font-semibold text-ink">Preparing your assessment</div>
        <div className="text-sm text-text-muted">This only takes a moment.</div>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface">
      <div className="flex-1 px-5 pb-32 max-w-lg w-full mx-auto flex flex-col gap-8">
        <header
          className="flex items-start justify-between pt-6"
          style={{ paddingTop: "calc(1.5rem + env(safe-area-inset-top, 0px))" }}
        >
          <img
            src="/solace-logo.png"
            alt="Solace"
            className="h-12 sm:h-16 md:h-20 w-auto select-none"
            draggable={false}
          />
          {result.language && result.language !== "en" && (
            <span
              className="text-[11px] uppercase tracking-wide text-text-muted bg-surface-low px-2 py-1 rounded font-mono"
              aria-label={`Results shown in language: ${result.language}`}
            >
              {result.language}
            </span>
          )}
        </header>

        <section className="flex flex-col gap-4 -ml-1">
          <div className="ml-1">
            <div className="text-[11px] uppercase tracking-[0.16em] text-text-muted mb-2">Your priority</div>
            <ESIBadge esiLevel={result.esi_level} size="lg" />
          </div>

          {ESI_MEANING[result.esi_level] && (
            <div className="ml-1 rounded-xl bg-surface-lowest shadow-soft p-4 flex flex-col gap-1">
              <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold">
                What this means
              </div>
              <div className="text-[15px] font-bold tracking-editorial leading-snug text-ink">
                {ESI_MEANING[result.esi_level].headline}
              </div>
              <p className="text-[14px] leading-relaxed text-ink/85">
                {ESI_MEANING[result.esi_level].body}
              </p>
            </div>
          )}

          <p className="text-[17px] leading-relaxed text-ink/90">{result.patient_explanation}</p>
          {result.confidence_band && (
            <p className="text-[11px] text-text-muted font-mono">{result.confidence_band}</p>
          )}
        </section>

        {careRec && <CareRecommendationCard rec={careRec} hospitalId={hospitalId} />}

        <SmsSelfServe hospitalId={hospitalId} patientId={patientId} />

        {education ? (
          <motion.section
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col gap-3 bg-surface-lowest rounded-xl p-5 shadow-soft"
          >
            <div className="flex items-center gap-2 text-primary">
              <ShieldCheck size={16} />
              <div className="text-[11px] uppercase tracking-[0.14em] font-semibold">
                From your care team
                {educationPublishedAt && (
                  <span className="font-mono ml-1 text-text-muted normal-case tracking-normal">
                    · {new Date(educationPublishedAt).toLocaleTimeString()}
                  </span>
                )}
              </div>
            </div>
            <h2 className="text-xl font-bold tracking-editorial leading-snug">{education.headline}</h2>
            <p className="text-[15px] leading-relaxed">{education.what_we_are_doing}</p>
            {education.things_to_do_at_home?.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold mt-1 mb-1">
                  At home
                </div>
                <ul className="text-[15px] leading-relaxed list-disc ml-5 flex flex-col gap-1">
                  {education.things_to_do_at_home.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold mt-1 mb-1">
                Come back if
              </div>
              <p className="text-[15px] leading-relaxed">{education.when_to_come_back}</p>
            </div>
            {education.closing && (
              <p className="text-[14px] italic text-text-muted">{education.closing}</p>
            )}
          </motion.section>
        ) : (
          <section className="flex flex-col gap-3">
            <div className="flex items-center gap-2 text-text-muted">
              <Leaf size={14} strokeWidth={1.5} />
              <div className="text-[11px] uppercase tracking-[0.14em] font-semibold">While you wait</div>
            </div>
            {waitRange && (
              <div className="rounded-lg bg-surface-lowest px-4 py-3 shadow-soft">
                <div className="text-[10px] uppercase tracking-[0.14em] text-text-muted font-semibold">
                  Estimated wait to clinician
                </div>
                <div className="text-xl font-bold tracking-editorial text-primary mt-0.5">
                  {waitRange}
                </div>
                <div className="text-[11px] text-text-muted mt-0.5">
                  Updates every 15s based on current queue. Your acuity band can move you up.
                </div>
              </div>
            )}
            {comfortPending && result.comfort_protocol.length === 0 ? (
              <div
                className="flex items-center gap-2 rounded-lg bg-surface-lowest px-4 py-4 shadow-soft text-text-muted"
                aria-live="polite"
                aria-busy="true"
              >
                <Loader2 size={16} className="animate-spin text-primary" aria-hidden="true" />
                <span className="text-[14px]">Preparing your guidance…</span>
              </div>
            ) : (
              <ComfortProtocol actions={result.comfort_protocol} />
            )}
          </section>
        )}

        <PainEscalateButton hospitalId={hospitalId} patientId={patientId} />

        <footer
          className="text-[11px] text-text-muted leading-relaxed pt-2"
          style={{ paddingBottom: "calc(0.5rem + env(safe-area-inset-bottom, 0px))" }}
        >
          Triage aid only. Clinicians verify every decision. If your condition feels immediately
          life-threatening, go to the front desk now.
        </footer>
      </div>

      {comfortPending && !result.audio_url ? (
        <div
          className="mx-4 mb-4 flex items-center gap-2 rounded-lg bg-surface-low px-4 py-3 text-sm text-text-muted"
          aria-live="polite"
          aria-busy="true"
        >
          <Loader2 size={14} className="animate-spin text-primary" aria-hidden="true" />
          Preparing your audio guidance…
        </div>
      ) : (
        <AudioPlayer audioUrl={result.audio_url} />
      )}
    </div>
  );
}


// -----------------------------------------------------------------------------

function CareRecommendationCard({
  rec,
  hospitalId,
}: {
  rec: NonNullable<IntakeResponse["care_recommendation"]>;
  hospitalId: string;
}) {
  const navigate = useNavigate();
  // Schedulable destinations route to self-scheduling; ED destinations are
  // informational — the patient is already on-site, so the CTA sends them to
  // the front desk rather than dead-ending.
  const isSchedulable =
    rec.destination === "telehealth" ||
    rec.destination === "self_care" ||
    rec.destination === "schedule";

  const tone = {
    critical: { bg: "bg-error", fg: "text-white", Icon: AlertTriangle, ring: "ring-error" },
    high:     { bg: "bg-error/15", fg: "text-error", Icon: Hospital, ring: "ring-error/40" },
    moderate: { bg: "bg-warning/15", fg: "text-warning", Icon: Clock, ring: "ring-warning/40" },
    low:      { bg: "bg-success/15", fg: "text-success", Icon: Home, ring: "ring-success/40" },
  }[rec.severity];

  const DestinationIcon = {
    ed_now:     Hospital,
    ed:         Hospital,
    urgent:     Hospital,
    telehealth: Video,
    self_care:  Home,
    schedule:   Clock,
  }[rec.destination] || Hospital;

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex flex-col gap-3 rounded-xl p-5 shadow-soft ring-2 ${tone.ring} ${tone.bg}`}
    >
      <div className={`flex items-center gap-2 ${tone.fg}`}>
        <tone.Icon size={16} strokeWidth={2.5} />
        <div className="text-[10px] uppercase tracking-wider font-bold">
          What you should do
        </div>
      </div>
      <h2 className={`text-2xl font-bold tracking-tight ${tone.fg}`}>{rec.label}</h2>
      <p className="text-[15px] leading-relaxed text-ink">{rec.rationale}</p>
      <div className="mt-1">
        {isSchedulable ? (
          <button
            type="button"
            onClick={() => navigate(`/${hospitalId}/schedule`)}
            className="w-full inline-flex items-center justify-center gap-2 h-12 px-4 rounded-md font-semibold text-sm text-white bg-primary shadow-soft transition-all hover:brightness-110 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
          >
            <DestinationIcon size={16} aria-hidden="true" />
            {rec.action_cta}
            <ArrowRight size={14} aria-hidden="true" />
          </button>
        ) : (
          // ED / urgent: patient is already on-site — this is a directive, not a
          // navigable action. Render as a non-interactive callout.
          <div
            className={`w-full inline-flex items-center justify-center gap-2 h-12 px-4 rounded-md font-semibold text-sm shadow-soft ${
              rec.severity === "critical" || rec.severity === "high"
                ? "bg-error text-white"
                : "bg-primary text-white"
            }`}
          >
            <DestinationIcon size={16} aria-hidden="true" />
            {rec.action_cta}
          </div>
        )}
      </div>
    </motion.section>
  );
}


function SmsSelfServe({
  hospitalId,
  patientId,
}: {
  hospitalId: string;
  patientId: string;
}) {
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center justify-center gap-1.5 h-11 rounded-md text-sm font-semibold text-primary bg-primary-fixed/40 hover:bg-primary-fixed transition-colors"
      >
        <MessageSquare size={14} /> Text me my care instructions
      </button>
    );
  }
  if (done) {
    return (
      <div className="inline-flex items-center justify-center gap-1.5 h-11 rounded-md text-sm font-semibold text-success bg-success/10">
        <Check size={14} /> Sent — check your messages
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 bg-surface-lowest rounded-lg p-3 shadow-soft">
      <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
        Text my care instructions
      </div>
      <div className="flex gap-2">
        <input
          type="tel"
          inputMode="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="(512) 555-0177"
          className="flex-1 h-11 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none"
          autoFocus
        />
        <button
          type="button"
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              const r = await sendCareInstructionsSelfServe(hospitalId, patientId, phone);
              if (r.success) setDone(true);
              else setError(r.message || (r.reason === "not_configured" ? "SMS isn't enabled for this hospital yet." : "Couldn't send. Try again."));
            } catch (e: any) {
              setError(e?.response?.data?.detail || "Couldn't send.");
            } finally {
              setBusy(false);
            }
          }}
          disabled={busy || phone.length < 7}
          className="h-11 px-4 rounded-md bg-primary text-white font-semibold text-sm disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <MessageSquare size={14} />}
          Send
        </button>
      </div>
      {error && <div className="text-xs text-error">{error}</div>}
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="text-[11px] text-text-muted underline self-start"
      >
        Cancel
      </button>
    </div>
  );
}
