import { useRef } from 'react';
import {
  motion,
  useInView,
  useScroll,
  useTransform,
  useReducedMotion,
} from 'framer-motion';
import type { ReactNode } from 'react';
import { Mic } from 'lucide-react';
import { himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';

/*
 * TileGrid — the forhims full-bleed masonry band (scroll_04 reference): five
 * columns of tiles with tight 10px gutters, 20px corners, bleeding past both
 * viewport edges ≥md. No app screenshots — every tile is a typographic
 * feature card in the house palette (ink, deep green, white, pale teal),
 * each one backed by a real shipped Solace capability (see the solace-ai
 * repo: 20-language i18n, voice capture, ~7s spoken triage, 19-field
 * insurance OCR, AI follow-ups, pain re-escalation, attribution log).
 *
 * The living-wall feel comes from scroll-linked column drift — odd columns
 * float up (-6vh), even columns down (+6vh) across the band's viewport
 * transit — exactly the useScroll + useTransform idiom from IntakeShowcase.
 */

// The pale teal gradient extracted from the reference's tile backgrounds.
const PALE_GRADIENT =
  'linear-gradient(166.14deg, rgb(232,244,247) 0%, rgb(199,229,221) 100%)';

// One masonry tile: rounded-tile, clipped, with the house fade-up reveal.
// Opacity rides HIMS_OUT (0.2s), the y transform rides HIMS_EXPO (0.6s);
// the 0.04s-per-tile stagger comes from the tile's index across the band.
function Tile({
  index,
  reduce,
  className = '',
  children,
}: {
  index: number;
  reduce: boolean | null;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{
        opacity: { ...himsFade, delay: index * 0.04 },
        y: { ...himsMove, delay: index * 0.04 },
      }}
      className={`relative shrink-0 overflow-hidden rounded-tile ${className}`}
    >
      {children}
    </motion.div>
  );
}

// Tiny uppercase kicker used across the feature tiles.
function Kicker({ tone, children }: { tone: 'light' | 'dark'; children: string }) {
  return (
    <p
      className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${
        tone === 'light' ? 'text-white/55' : 'text-muted'
      }`}
    >
      {children}
    </p>
  );
}

// Animated voice bars — the "speak naturally" tile's mic level meter.
const BAR_HEIGHTS = [10, 22, 14, 30, 40, 26, 34, 18, 28, 12, 20, 9];
function VoiceBars({ still }: { still: boolean }) {
  return (
    <div aria-hidden="true" className="flex h-11 items-center gap-[5px]">
      {/* Bars 8+ only fit once the 2-col tiles widen past ~sm — below that
          they would run through the tile's right padding edge. */}
      {BAR_HEIGHTS.map((h, i) => (
        <motion.span
          key={i}
          className={`w-[4px] rounded-full bg-solace-green-700/70 ${
            i >= 7 ? 'hidden sm:block' : ''
          }`}
          style={{ height: h }}
          initial={false}
          animate={still ? { scaleY: 1 } : { scaleY: [1, 0.45, 1] }}
          transition={
            still
              ? { duration: 0 }
              : {
                  duration: 1.15,
                  ease: 'easeInOut',
                  repeat: Infinity,
                  delay: i * 0.09,
                }
          }
        />
      ))}
    </div>
  );
}

const QUESTION_PILL =
  'rounded-pill px-3.5 py-1.5 text-[13px] font-medium ring-1';
const PILL_IDLE = `${QUESTION_PILL} bg-white text-ink ring-black/[0.06]`;
const PILL_PICKED = `${QUESTION_PILL} bg-ink text-white ring-ink`;

const LANG_PILL =
  'rounded-pill border border-black/5 bg-white px-4 py-2 text-sm font-medium text-ink shadow-soft';

export default function TileGrid() {
  const sectionRef = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();

  // Column drift only runs ≥lg — below that the band stacks into fewer,
  // calmer columns.
  const isWide = useIsWide();

  // 0→1 across the band's transit through the viewport.
  const { scrollYProgress: p } = useScroll({
    target: sectionRef,
    offset: ['start end', 'end start'],
  });
  // Stop the infinite loops (voice bars, EKG trace) whenever the band is
  // off-screen — framer keyframe loops otherwise tick for the page's whole
  // lifetime, and the EKG column is display:none below lg anyway.
  const onStage = useInView(sectionRef, { amount: 0.05 });
  const still = reduce || !isWide;
  const yOdd = useTransform(p, [0, 1], still ? ['0vh', '0vh'] : ['6vh', '-6vh']);
  const yEven = useTransform(p, [0, 1], still ? ['0vh', '0vh'] : ['-6vh', '6vh']);

  const col = 'flex flex-col gap-2.5 will-change-transform';

  return (
    <section
      ref={sectionRef}
      aria-labelledby="tile-grid-heading"
      className="relative overflow-hidden bg-white py-[6vh]"
      style={{
        // Picks up FeatureIntro's faint mint stop and settles back to white,
        // so the seam between the two bands reads as one continuous wash.
        backgroundImage: 'linear-gradient(180deg, #f2f9f6 0%, #ffffff 100%)',
      }}
    >
      <h2 id="tile-grid-heading" className="sr-only">
        What The Solace App Does
      </h2>

      {/* The wall stays inside the viewport at every breakpoint so no
          tile content ever gets sliced off. */}
      <div className="grid grid-cols-2 gap-2.5 px-2.5 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {/* ---- Column 1 (drifts up) ---- */}
        <motion.div style={{ y: yOdd }} className={col}>
          {/* Voice-first capture — MicButton + Transcribe in the real app. */}
          <Tile index={0} reduce={reduce} className="h-[340px]">
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{ backgroundImage: PALE_GRADIENT }}
            />
            <div className="relative flex h-full flex-col justify-between p-6">
              <div className="flex items-center gap-4">
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-white text-ink shadow-pop">
                  <Mic size={24} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <VoiceBars still={!!reduce || !onStage} />
              </div>
              <div>
                <p className="font-sofia text-[28px] font-medium leading-tight tracking-[-0.02em] text-ink">
                  What&rsquo;s going on?
                </p>
                <p className="mt-2 text-sm text-muted">
                  speak naturally, or type if it&rsquo;s loud.
                </p>
              </div>
            </div>
          </Tile>

          <Tile index={1} reduce={reduce} className="h-[200px] bg-ink">
            <div className="flex h-full flex-col justify-center p-6">
              <p className="font-sofia text-[26px] font-medium leading-tight tracking-[-0.02em] text-white">
                Priority 2 · Urgent
              </p>
              <p className="mt-2 text-sm text-white/70">
                the sickest are always seen first
              </p>
            </div>
          </Tile>

          <Tile index={2} reduce={reduce} className="h-[240px] bg-paper">
            <div className="flex h-full flex-col items-start justify-center gap-2.5 p-5">
              <span className={LANG_PILL}>
                <span aria-hidden="true">🇺🇸 </span>English
              </span>
              <span className={LANG_PILL} lang="es">
                <span aria-hidden="true">🇪🇸 </span>Español
              </span>
              <span className={LANG_PILL} lang="ar">
                <span aria-hidden="true">🇸🇦 </span>العربية
              </span>
              <span className="rounded-pill px-4 py-1 text-sm font-medium text-muted">
                + 17 more
              </span>
            </div>
          </Tile>
        </motion.div>

        {/* ---- Column 2 (drifts down) ---- */}
        <motion.div style={{ y: yEven }} className={`${col} pt-10`}>
          {/* Insurance OCR — 19 fields via Claude Vision in the real app. */}
          <Tile
            index={3}
            reduce={reduce}
            className="h-[350px] bg-paper ring-1 ring-black/[0.06]"
          >
            <div className="flex h-full flex-col justify-between p-6">
              <div
                aria-hidden="true"
                className="mx-auto mt-2 w-[85%] -rotate-3 rounded-2xl p-4 shadow-pop"
                style={{ backgroundImage: PALE_GRADIENT }}
              >
                <div className="h-6 w-8 rounded-md bg-white/80" />
                <div className="mt-4 h-1.5 w-2/3 rounded-full bg-ink/15" />
                <div className="mt-2 h-1.5 w-1/2 rounded-full bg-ink/15" />
                <p className="mt-4 text-right font-mono text-[10px] tracking-[0.08em] text-ink/50">
                  MEMBER ID ··· 4821
                </p>
              </div>
              <div>
                <p className="font-sofia text-[26px] font-medium leading-tight tracking-[-0.02em] text-ink">
                  Snap your card.
                </p>
                <p className="mt-2 text-sm text-muted">
                  your insurance details, filled in for you.
                </p>
              </div>
            </div>
          </Tile>

          {/* ~7s submit → spoken guidance, from the live pipeline. */}
          <Tile index={4} reduce={reduce} className="h-[400px] bg-solace-green-700">
            <div className="flex h-full flex-col justify-between p-6">
              <Kicker tone="light">Spoken guidance</Kicker>
              <p className="font-sofia text-[84px] font-medium leading-none tracking-hims text-white">
                ~7<span className="text-[0.5em]">&nbsp;sec</span>
              </p>
              <p className="text-sm leading-relaxed text-white/70">
                tell your story, and Solace talks you through what happens next in your language.
              </p>
            </div>
          </Tile>
        </motion.div>

        {/* ---- Column 3 (drifts up) ---- */}
        <motion.div style={{ y: yOdd }} className={`${col} hidden pt-4 md:flex`}>
          <Tile index={5} reduce={reduce} className="h-[280px] bg-ink">
            <div className="flex h-full flex-col justify-center p-6 text-white">
              <p className="font-sofia text-[40px] font-medium leading-none tracking-[-0.02em]">
                35–45 min
              </p>
              <p className="mt-2.5 text-sm text-white/70">
                your real wait time, updated every 15 seconds
              </p>
            </div>
          </Tile>

          {/* AI follow-ups — 2–3 questions picked from the transcript. */}
          <Tile index={6} reduce={reduce} className="h-[470px]">
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{ backgroundImage: PALE_GRADIENT }}
            />
            <div className="relative flex h-full flex-col p-6">
              <div>
                <p className="font-sofia text-[26px] font-medium leading-tight tracking-[-0.02em] text-ink">
                  A few quick questions
                </p>
                <p className="mt-2 text-sm text-muted">
                  two or three, picked for your story.
                </p>
              </div>
              <div className="mt-9 space-y-6">
                <div>
                  <p className="text-[14px] font-medium text-ink">
                    Any trouble breathing right now?
                  </p>
                  <div className="mt-2.5 flex gap-2">
                    <span className={PILL_PICKED}>Yes</span>
                    <span className={PILL_IDLE}>No</span>
                  </div>
                </div>
                <div>
                  <p className="text-[14px] font-medium text-ink">
                    How severe is the pain?
                  </p>
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    <span className={PILL_IDLE}>1–3</span>
                    <span className={PILL_IDLE}>4–6</span>
                    <span className={PILL_PICKED}>7–10</span>
                  </div>
                </div>
              </div>
            </div>
          </Tile>
        </motion.div>

        {/* ---- Column 4 (drifts down) ---- */}
        <motion.div style={{ y: yEven }} className={`${col} hidden pt-14 lg:flex`}>
          <Tile index={7} reduce={reduce} className="h-[280px] bg-solace-green-700">
            <div className="flex h-full flex-col justify-center gap-1.5 p-6 text-white">
              <span
                lang="ar"
                dir="rtl"
                className="text-left font-sofia text-[28px] font-medium leading-[1.15] tracking-[-0.02em]"
              >
                العربية
              </span>
              <span lang="es" className="font-sofia text-[28px] font-medium leading-[1.15] tracking-[-0.02em]">
                Español
              </span>
              <span lang="zh" className="font-sofia text-[28px] font-medium leading-[1.15] tracking-[-0.02em]">
                中文
              </span>
              <span lang="tl" className="font-sofia text-[28px] font-medium leading-[1.15] tracking-[-0.02em]">
                Tagalog
              </span>
            </div>
          </Tile>

          <Tile index={8} reduce={reduce} className="h-[150px] bg-paper">
            <div className="flex h-full flex-col justify-between p-5">
              <p className="font-mono text-xs uppercase tracking-[0.14em] text-ink">
                HR 118 · SpO₂ 94%
              </p>
              <svg viewBox="0 0 220 64" fill="none" className="w-full" aria-hidden="true">
                <motion.polyline
                  points="0,32 40,32 52,32 62,10 74,54 84,32 118,32 128,20 138,42 148,32 196,32 220,32"
                  stroke="#1FBF8F"
                  strokeWidth={2.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  initial={false}
                  animate={still || !onStage ? { pathLength: 1 } : { pathLength: [0, 1] }}
                  transition={
                    still || !onStage
                      ? { duration: 0 }
                      : { duration: 2.2, ease: 'linear', repeat: Infinity, repeatDelay: 0.35 }
                  }
                />
              </svg>
            </div>
          </Tile>

          {/* Pain re-escalation — "My pain got worse" in the waiting room. */}
          <Tile index={9} reduce={reduce} className="h-[320px] bg-ink">
            <div className="flex h-full flex-col justify-between p-6">
              <Kicker tone="light">While you wait</Kicker>
              <span className="self-start rounded-pill bg-white/10 px-5 py-3 text-[15px] font-medium text-white ring-1 ring-white/25">
                My pain got worse
              </span>
              <p className="text-sm text-white/70">
                press it once and your care team knows right away.
              </p>
            </div>
          </Tile>
        </motion.div>

        {/* ---- Column 5 (drifts up) ---- */}
        <motion.div style={{ y: yOdd }} className={`${col} hidden pt-6 xl:flex`}>
          {/* The audit trail, in plain words. */}
          <Tile
            index={10}
            reduce={reduce}
            className="h-[420px] bg-paper ring-1 ring-black/[0.06]"
          >
            <div className="flex h-full flex-col justify-between p-6">
              <div>
                <Kicker tone="dark">Nothing hidden</Kicker>
                <p className="mt-3 font-sofia text-[30px] font-medium leading-[1.15] tracking-[-0.02em] text-ink">
                  Every AI step, written down.
                </p>
              </div>
              <p className="text-[15px] leading-relaxed text-muted">
                Whenever the AI reads your words, your card or your photo,
                that moment is saved to your record. Your clinician can always
                see exactly what the AI saw.
              </p>
            </div>
          </Tile>

          <Tile index={11} reduce={reduce} className="h-[330px] bg-ink">
            <div className="flex h-full flex-col justify-center p-6 text-white">
              <p className="font-sofia text-[64px] font-medium leading-none tracking-hims">
                98%
              </p>
              <p className="mt-2.5 text-sm text-white/70">the AI tells your care team how sure it is, every time</p>
            </div>
          </Tile>
        </motion.div>
      </div>
    </section>
  );
}
