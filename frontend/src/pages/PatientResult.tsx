import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Leaf, ShieldCheck } from "lucide-react";
import { AudioPlayer } from "../components/patient/AudioPlayer";
import { ComfortProtocol } from "../components/patient/ComfortProtocol";
import { ESIBadge } from "../components/patient/ESIBadge";
import { PainEscalateButton } from "../components/patient/PainEscalateButton";
import { getPublicPatient } from "../lib/api";
import type { IntakeResponse, PatientEducation } from "../types";

const POLL_MS = 15_000;

export default function PatientResult() {
  const { hospitalId = "demo", patientId = "" } = useParams<{ hospitalId: string; patientId: string }>();
  const [result, setResult] = useState<IntakeResponse | null>(null);
  const [education, setEducation] = useState<PatientEducation | null>(null);
  const [educationPublishedAt, setEducationPublishedAt] = useState<string | null>(null);
  const [waitRange, setWaitRange] = useState<string | null>(null);

  useEffect(() => {
    const raw = sessionStorage.getItem(`intake:${patientId}`);
    if (raw) {
      try {
        setResult(JSON.parse(raw));
      } catch {
        /* ignore */
      }
    }
  }, [patientId]);

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
      <div className="min-h-[100dvh] flex items-center justify-center p-6">
        <div className="text-text-muted">Loading your result…</div>
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
          <div className="flex flex-col gap-1">
            <div className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
              Your ER companion
            </div>
            <img
              src="/solace-logo.png"
              alt="Solace"
              className="h-12 w-auto -ml-1 select-none"
              draggable={false}
            />
          </div>
          {result.language && result.language !== "en" && (
            <span className="text-[11px] uppercase tracking-wide text-text-muted bg-surface-low px-2 py-1 rounded font-mono">
              {result.language}
            </span>
          )}
        </header>

        <section className="flex flex-col gap-4 -ml-1">
          <div className="ml-1">
            <div className="text-[11px] uppercase tracking-[0.16em] text-text-muted mb-2">Your priority</div>
            <ESIBadge esiLevel={result.esi_level} size="lg" />
          </div>
          <p className="text-[17px] leading-relaxed text-ink/90">{result.patient_explanation}</p>
          {result.confidence_band && (
            <p className="text-[11px] text-text-muted font-mono">{result.confidence_band}</p>
          )}
        </section>

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
            <ComfortProtocol actions={result.comfort_protocol} />
          </section>
        )}

        <PainEscalateButton hospitalId={hospitalId} patientId={patientId} />

        <footer className="text-[11px] text-text-muted leading-relaxed pt-2">
          Triage aid only. Clinicians verify every decision. If your condition feels immediately
          life-threatening, go to the front desk now.
        </footer>
      </div>

      <AudioPlayer audioUrl={result.audio_url} />
    </div>
  );
}
