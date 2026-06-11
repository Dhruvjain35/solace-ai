import { useRef } from "react";
import { motion, MotionValue, useReducedMotion, useScroll, useSpring, useTransform } from "framer-motion";
import { Mic, FileText, Sparkles } from "lucide-react";

// Scroll-pinned scribe story (the "talking thing"): a 320vh runway with a sticky
// stage. Scroll scrubs through three acts — the visit talks, the note writes
// itself, the codes land. The waveform genuinely "speaks" while act 1 is live.

const captions = [
  { who: "Dr. Nguyen", text: "Morning, Olivia — what's been going on?" },
  { who: "Olivia", text: "This cough just won't quit. Three weeks now, worse at night." },
  { who: "Dr. Nguyen", text: "Any fever or chest pain? Short of breath on stairs?" },
  { who: "Olivia", text: "No fever — but stairs make my chest feel tight." },
];

const note = [
  { h: "Subjective", t: "3-week persistent cough, worse nocturnally. Exertional chest tightness. Denies fever." },
  { h: "Objective", t: "Scattered end-expiratory wheeze. SpO2 98% RA. Afebrile." },
  { h: "Assessment", t: "Subacute cough — suspect post-viral airway hyperreactivity." },
  { h: "Plan", t: "CXR today. Albuterol MDI PRN. Return 2 weeks, sooner if worsening." },
];

const codes = ["R05.3", "J45.901", "71046", "99214"];

// One animated equalizer bar. Heights loop on a time base; act-1 visibility is
// handled by the parent's opacity transform so bars only "speak" when on stage.
function Bar({ i }: { i: number }) {
  const reduced = useReducedMotion();
  const peaks = [0.9, 0.45, 1, 0.6, 0.8, 0.5, 0.95, 0.4][i % 8];
  return (
    <motion.span
      className="w-[3px] rounded-full bg-gradient-to-t from-primary-fixed/40 to-primary-fixed"
      style={{ height: 34, originY: 1 }}
      animate={reduced ? { scaleY: 0.5 } : { scaleY: [0.25, peaks, 0.4, peaks * 0.8, 0.25] }}
      transition={reduced ? {} : { duration: 1.15, repeat: Infinity, delay: (i % 9) * 0.09, ease: "easeInOut" }}
    />
  );
}

function CaptionLine({ p, i, who, text }: { p: MotionValue<number>; i: number; who: string; text: string }) {
  // Each caption owns a slice of act one (p 0.04 → 0.34).
  const start = 0.04 + i * 0.07;
  const opacity = useTransform(p, [start, start + 0.03], [0, 1]);
  const y = useTransform(p, [start, start + 0.03], [18, 0]);
  const dim = useTransform(p, [start + 0.07, start + 0.1], [1, 0.45]);
  const finalOpacity = useTransform([opacity, dim], ([o, d]) => (o as number) * (d as number));
  return (
    <motion.p style={{ opacity: finalOpacity, y }} className="text-[15px] leading-relaxed text-white/90 sm:text-base">
      <span className="font-medium text-primary-fixed">{who}</span>
      <span className="text-white/40"> — </span>
      {text}
    </motion.p>
  );
}

function NoteSection({ p, i, h, t }: { p: MotionValue<number>; i: number; h: string; t: string }) {
  const start = 0.42 + i * 0.06;
  const opacity = useTransform(p, [start, start + 0.04], [0, 1]);
  const y = useTransform(p, [start, start + 0.04], [14, 0]);
  return (
    <motion.div style={{ opacity, y }}>
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-primary-fixed">{h}</p>
      <p className="mt-0.5 text-[13px] leading-relaxed text-white/75">{t}</p>
    </motion.div>
  );
}

function CodeChip({ p, i, code }: { p: MotionValue<number>; i: number; code: string }) {
  const start = 0.72 + i * 0.035;
  const opacity = useTransform(p, [start, start + 0.025], [0, 1]);
  const scale = useTransform(p, [start, start + 0.035], [0.6, 1]);
  return (
    <motion.span
      style={{ opacity, scale }}
      className="inline-flex items-center rounded-full bg-primary-fixed/15 px-3 py-1.5 font-mono text-xs font-medium text-primary-fixed ring-1 ring-primary-fixed/25"
    >
      {code}
    </motion.span>
  );
}

export function ScribeScene() {
  const reduced = useReducedMotion();
  const runway = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: runway, offset: ["start start", "end end"] });
  const p = useSpring(scrollYProgress, { stiffness: 90, damping: 24, restDelta: 0.001 });

  // Stage headline crossfades per act
  const h1o = useTransform(p, [0, 0.05, 0.3, 0.38], [0, 1, 1, 0]);
  const h2o = useTransform(p, [0.38, 0.46, 0.62, 0.7], [0, 1, 1, 0]);
  const h3o = useTransform(p, [0.7, 0.78, 1], [0, 1, 1]);
  // Panels
  const micO = useTransform(p, [0, 0.06, 0.34, 0.44], [0, 1, 1, 0.25]);
  const micScale = useTransform(p, [0.34, 0.44], [1, 0.96]);
  const noteO = useTransform(p, [0.38, 0.44], [0, 1]);
  const noteY = useTransform(p, [0.38, 0.46], [44, 0]);
  const sigO = useTransform(p, [0.86, 0.92], [0, 1]);
  const barW = useTransform(p, [0, 1], ["0%", "100%"]);

  if (reduced) {
    // Static fallback: final state, no pinning.
    return (
      <section className="bg-ink px-4 py-24 text-center sm:px-6">
        <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-primary-fixed">AI Scribe</p>
        <h2 className="mx-auto mt-3 max-w-2xl font-display text-4xl tracking-editorial text-white">
          The visit talks. The note writes itself. You sign.
        </h2>
      </section>
    );
  }

  return (
    <div ref={runway} className="relative h-[320vh] bg-ink">
      <div className="sticky top-0 flex h-screen flex-col overflow-hidden">
        {/* ambient glow */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{ background: "radial-gradient(ellipse 60% 45% at 50% 38%, rgba(59,94,103,0.55), transparent 70%)" }}
        />

        {/* act headlines */}
        <div className="relative mx-auto mt-14 h-24 w-full max-w-3xl px-4 text-center sm:mt-16">
          <motion.div style={{ opacity: h1o }} className="absolute inset-x-4 top-0">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-primary-fixed">Act I - the visit</p>
            <h2 className="mt-2 font-display text-3xl tracking-editorial text-white sm:text-5xl">Just talk to your patient.</h2>
          </motion.div>
          <motion.div style={{ opacity: h2o }} className="absolute inset-x-4 top-0">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-primary-fixed">Act II - the chart</p>
            <h2 className="mt-2 font-display text-3xl tracking-editorial text-white sm:text-5xl">The note writes itself.</h2>
          </motion.div>
          <motion.div style={{ opacity: h3o }} className="absolute inset-x-4 top-0">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-primary-fixed">Act III - done</p>
            <h2 className="mt-2 font-display text-3xl tracking-editorial text-white sm:text-5xl">Coded. Signed. Go home.</h2>
          </motion.div>
        </div>

        {/* stage */}
        <div className="relative mx-auto grid w-full max-w-5xl flex-1 items-center gap-6 px-4 pb-16 sm:px-6 lg:grid-cols-2">
          {/* left: the talking card */}
          <motion.div style={{ opacity: micO, scale: micScale }} className="rounded-[28px] bg-white/[0.06] p-6 ring-1 ring-white/10 backdrop-blur-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5 text-sm font-medium text-white">
                <span className="relative flex h-9 w-9 items-center justify-center rounded-full bg-error/20 text-red-300">
                  <Mic size={15} aria-hidden="true" />
                  <motion.span
                    aria-hidden="true"
                    className="absolute inset-0 rounded-full ring-2 ring-red-400/40"
                    animate={{ opacity: [0.8, 0], scale: [1, 1.5] }}
                    transition={{ duration: 1.5, repeat: Infinity }}
                  />
                </span>
                Listening
              </div>
              <div className="flex h-9 items-end gap-[3px]" aria-hidden="true">
                {Array.from({ length: 18 }, (_, i) => (
                  <Bar key={i} i={i} />
                ))}
              </div>
            </div>
            <div className="mt-5 min-h-[190px] space-y-3">
              {captions.map((c, i) => (
                <CaptionLine key={c.text} p={p} i={i} who={c.who} text={c.text} />
              ))}
            </div>
            <p className="mt-4 font-mono text-[10px] uppercase tracking-[0.16em] text-white/35">
              Live transcription - ambient, no dictation
            </p>
          </motion.div>

          {/* right: the note assembling */}
          <motion.div style={{ opacity: noteO, y: noteY }} className="rounded-[28px] bg-white/[0.06] p-6 ring-1 ring-white/10 backdrop-blur-sm">
            <div className="flex items-center gap-2.5 text-sm font-medium text-white">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-fixed/15 text-primary-fixed">
                <FileText size={15} aria-hidden="true" />
              </span>
              Draft note
              <span className="ml-auto rounded-full bg-white/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-wide text-white/55">SOAP</span>
            </div>
            <div className="mt-5 min-h-[170px] space-y-3.5">
              {note.map((s, i) => (
                <NoteSection key={s.h} p={p} i={i} h={s.h} t={s.t} />
              ))}
            </div>
            <div className="mt-4 flex min-h-[34px] flex-wrap gap-2 border-t border-white/10 pt-4">
              {codes.map((c, i) => (
                <CodeChip key={c} p={p} i={i} code={c} />
              ))}
              <motion.span style={{ opacity: sigO }} className="ml-auto inline-flex items-center gap-1.5 text-xs font-medium text-success">
                <Sparkles size={13} aria-hidden="true" /> Ready to sign
              </motion.span>
            </div>
          </motion.div>
        </div>

        {/* progress */}
        <div className="absolute inset-x-0 bottom-0 h-[3px] bg-white/10">
          <motion.div style={{ width: barW }} className="h-full bg-gradient-to-r from-primary-container to-primary-fixed" />
        </div>
      </div>
    </div>
  );
}
