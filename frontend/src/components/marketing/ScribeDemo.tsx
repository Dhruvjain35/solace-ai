import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Mic, FileText, ArrowRight } from "lucide-react";

// The marketing scribe mock: a looping three-phase story —
// 1) live transcript lines appear while a waveform "listens"
// 2) a structured note draft types itself in on the right
// 3) billing codes chip out of the note
// All purely presentational; timings tuned for readability, not realism.

const transcript = [
  { who: "Dr. Nguyen", text: "Morning, Olivia — what brings you in today?" },
  { who: "Olivia", text: "This cough won't quit. Three weeks now, worse at night." },
  { who: "Dr. Nguyen", text: "Any fever, chest pain, or shortness of breath?" },
  { who: "Olivia", text: "No fever. A little tight when I climb stairs." },
  { who: "Dr. Nguyen", text: "We'll listen to your lungs and get a chest X-ray today." },
];

const note = [
  { h: "Subjective", t: "3-week persistent cough, nocturnal worsening. Mild exertional chest tightness. Denies fever." },
  { h: "Objective", t: "Lungs: scattered end-expiratory wheeze. SpO2 98% RA. Afebrile." },
  { h: "Assessment", t: "Subacute cough, suspect post-viral airway hyperreactivity. R/O reactive airway disease." },
  { h: "Plan", t: "Chest X-ray today. Trial albuterol MDI PRN. Return in 2 weeks or sooner if worsening." },
];

const codes = [
  { code: "R05.3", label: "Chronic cough" },
  { code: "J45.901", label: "Unspec. asthma, uncomplicated" },
  { code: "71046", label: "CPT - Chest X-ray, 2 views" },
  { code: "99214", label: "CPT - Office visit, est." },
];

const WaveBar = ({ i, active }: { i: number; active: boolean }) => (
  <motion.span
    className="w-[3px] rounded-full bg-primary"
    animate={active ? { scaleY: [0.35, 1, 0.5, 0.9, 0.35] } : { scaleY: 0.35 }}
    transition={active ? { duration: 1.1, repeat: Infinity, delay: i * 0.13, ease: "easeInOut" } : { duration: 0.2 }}
    style={{ height: 18, originY: 1 }}
  />
);

export function ScribeDemo() {
  const reduced = useReducedMotion();
  // lines shown, then note sections shown, then codes shown
  const [lines, setLines] = useState(reduced ? transcript.length : 0);
  const [sections, setSections] = useState(reduced ? note.length : 0);
  const [chips, setChips] = useState(reduced ? codes.length : 0);

  useEffect(() => {
    if (reduced) return;
    let cancelled = false;
    const timers: number[] = [];
    const at = (ms: number, fn: () => void) => timers.push(window.setTimeout(() => !cancelled && fn(), ms));
    const run = () => {
      setLines(0);
      setSections(0);
      setChips(0);
      transcript.forEach((_, i) => at(600 + i * 1050, () => setLines(i + 1)));
      const noteStart = 600 + transcript.length * 1050 + 500;
      note.forEach((_, i) => at(noteStart + i * 900, () => setSections(i + 1)));
      const codeStart = noteStart + note.length * 900 + 400;
      codes.forEach((_, i) => at(codeStart + i * 380, () => setChips(i + 1)));
      at(codeStart + codes.length * 380 + 3500, run); // loop
    };
    run();
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [reduced]);

  const listening = lines < transcript.length;

  return (
    <div className="grid gap-5 lg:grid-cols-2" aria-label="Animated example: a visit conversation becoming a coded note">
      {/* Left: live transcript */}
      <div className="card-clean rounded-xl p-5 text-left">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium text-ink">
            <span className="relative flex h-7 w-7 items-center justify-center rounded-full bg-error/10 text-error">
              <Mic size={14} aria-hidden="true" />
              {listening && !reduced && (
                <motion.span
                  className="absolute inset-0 rounded-full ring-2 ring-error/40"
                  animate={{ opacity: [0.7, 0], scale: [1, 1.45] }}
                  transition={{ duration: 1.4, repeat: Infinity }}
                />
              )}
            </span>
            Visit audio
          </div>
          <div className="flex items-end gap-[3px]" aria-hidden="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <WaveBar key={i} i={i} active={listening && !reduced} />
            ))}
          </div>
        </div>
        <div className="mt-4 min-h-[230px] space-y-2.5">
          {transcript.slice(0, lines).map((l, i) => {
            const current = i === lines - 1 && listening;
            return (
              <motion.p
                key={l.text}
                initial={reduced ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className={`text-sm leading-relaxed ${current ? "text-ink" : "text-text-muted"}`}
              >
                <span className="font-medium text-ink">{l.who}:</span> {l.text}
              </motion.p>
            );
          })}
        </div>
        <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-text-muted">
          Real-time transcription
        </p>
      </div>

      {/* Right: drafted note + codes */}
      <div className="card-clean rounded-xl p-5 text-left">
        <div className="flex items-center gap-2 text-sm font-medium text-ink">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-dim/70 text-primary">
            <FileText size={14} aria-hidden="true" />
          </span>
          Draft note
          <span className="ml-auto rounded-full bg-surface-low px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-text-muted">
            SOAP
          </span>
        </div>
        <div className="mt-4 min-h-[170px] space-y-3">
          {note.slice(0, sections).map((s) => (
            <motion.div key={s.h} initial={reduced ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-primary">{s.h}</p>
              <p className="text-[13px] leading-relaxed text-text-muted">{s.t}</p>
            </motion.div>
          ))}
        </div>
        <div className="mt-4 border-t border-line pt-3">
          <p className="mb-2 flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-muted">
            <ArrowRight size={11} aria-hidden="true" /> Suggested codes
          </p>
          <div className="flex min-h-[58px] flex-wrap content-start gap-2">
            <AnimatePresence>
              {codes.slice(0, chips).map((c) => (
                <motion.span
                  key={c.code}
                  initial={reduced ? false : { opacity: 0, scale: 0.85, y: 6 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  transition={{ type: "spring", stiffness: 380, damping: 24 }}
                  className="inline-flex items-center gap-1.5 rounded-full bg-primary-dim/60 px-2.5 py-1 text-xs text-primary ring-1 ring-primary/10"
                >
                  <span className="font-mono font-medium">{c.code}</span>
                  <span className="text-primary/75">{c.label}</span>
                </motion.span>
              ))}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}
