/**
 * Solace hackathon demo — ~83 s @ 30 fps = 2490 frames.
 *
 * Scenes (24-frame cross-fades via SceneWrap):
 *   0    -  270   Title                     (9 s)
 *   246  - 1326   Patient intake            (36 s, 6 sub-scenes)
 *   1302 - 1422   Time-warp                 (4 s)
 *   1398 - 1998   Clinician dashboard       (20 s)
 *   1974 - 2304   Vitals refinement         (11 s)
 *   2280 - 2580   Closing stats             (10 s)
 */
import React from "react";
import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const SOLACE_FPS = 30;
export const SOLACE_DURATION = 2580;

// Clinical Sanctuary palette
const PRIMARY = "#2A474E";
const PRIMARY_GRAD_FROM = "#3B5E67";
const PRIMARY_FIXED = "#CBE3E9";
const SURFACE = "#F8F9F9";
const SURFACE_LOWEST = "#FFFFFF";
const SURFACE_LOW = "#F3F4F4";
const TEXT_MUTED = "#4A5557";
const INK = "#1A2023";
const FONT =
  "'DM Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

const ESI_COLORS: Record<number, string> = {
  1: "#BA1A1A",
  2: "#B05436",
  3: "#B8924A",
  4: "#406372",
  5: "#557D6E",
};

const EASE_OUT = Easing.bezier(0.19, 1, 0.22, 1);
const EASE_IN_OUT = Easing.bezier(0.4, 0, 0.2, 1);

const CROSSFADE = 24;
const SceneWrap: React.FC<{ children: React.ReactNode; duration: number }> = ({ children, duration }) => {
  const frame = useCurrentFrame();
  const o = interpolate(
    frame,
    [0, CROSSFADE, duration - CROSSFADE, duration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return <AbsoluteFill style={{ opacity: o }}>{children}</AbsoluteFill>;
};

// Simple cross-fade between phone sub-scenes. Centered on the boundary,
// so at any boundary the two neighbours cross through opacity 0.5 simultaneously
// (proper crossfade, no dip to background).
const SUB_HALF = 8;
const SubScene: React.FC<{
  start: number;
  end: number;
  frame: number;
  children: React.ReactNode;
}> = ({ start, end, frame, children }) => {
  const opacity = interpolate(
    frame,
    [start - SUB_HALF, start + SUB_HALF, end - SUB_HALF, end + SUB_HALF],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  if (opacity <= 0.001) return null;
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};

const Caption: React.FC<{
  children: React.ReactNode;
  from: number;
  duration: number;
  position?: "top" | "bottom";
}> = ({ children, from, duration, position = "bottom" }) => {
  const frame = useCurrentFrame();
  const local = frame - from;
  if (local < 0 || local > duration) return null;
  const opacity = interpolate(local, [0, 18, duration - 18, duration], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: position === "top" ? "flex-start" : "flex-end",
        paddingTop: position === "top" ? 48 : 0,
        paddingBottom: position === "bottom" ? 56 : 0,
        pointerEvents: "none",
      }}
    >
      <div style={{
        opacity,
        background: "rgba(16, 24, 26, 0.90)", color: "white",
        padding: "16px 30px", borderRadius: 12, fontSize: 28, fontFamily: FONT,
        fontWeight: 600, letterSpacing: "-0.02em", maxWidth: 1400, textAlign: "center",
        backdropFilter: "blur(8px)", boxShadow: "0 12px 40px rgba(0,0,0,0.28)",
      }}>
        {children}
      </div>
    </AbsoluteFill>
  );
};

// Slow-drifting ambient background layer. No scale, just gentle x/y drift —
// that way we never pump the whole frame.
const AmbientOrbs: React.FC<{ tint?: string; opacity?: number }> = ({ tint = PRIMARY_FIXED, opacity = 0.35 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const orbs = [
    { size: 900, baseX: 15, baseY: 20, freq: 0.05, phase: 0 },
    { size: 700, baseX: 80, baseY: 60, freq: 0.04, phase: 2 },
    { size: 500, baseX: 45, baseY: 85, freq: 0.06, phase: 4 },
  ];
  return (
    <AbsoluteFill style={{ overflow: "hidden", pointerEvents: "none" }}>
      {orbs.map((o, i) => {
        const dx = Math.sin(t * o.freq * 2 * Math.PI + o.phase) * 36;
        const dy = Math.cos(t * o.freq * 2 * Math.PI + o.phase * 0.7) * 26;
        return (
          <div key={i} style={{
            position: "absolute",
            left: `${o.baseX}%`, top: `${o.baseY}%`,
            width: o.size, height: o.size, borderRadius: "50%",
            background: `radial-gradient(circle, ${tint} 0%, transparent 70%)`,
            transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`,
            opacity,
            filter: "blur(40px)",
          }} />
        );
      })}
    </AbsoluteFill>
  );
};

const PhoneFrame: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{
    position: "relative", width: 420, height: 860, borderRadius: 58,
    background: "#111", padding: 14,
    boxShadow: "0 40px 120px rgba(0,0,0,0.55), 0 0 0 2px rgba(255,255,255,0.08) inset",
  }}>
    <div style={{
      position: "absolute", top: 22, left: "50%", transform: "translateX(-50%)",
      width: 110, height: 32, borderRadius: 16, background: "#000", zIndex: 5,
    }} />
    <div style={{
      width: "100%", height: "100%", borderRadius: 46, overflow: "hidden",
      background: SURFACE_LOWEST, fontFamily: FONT, color: INK, position: "relative",
    }}>
      {children}
    </div>
  </div>
);

const LaptopFrame: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ position: "relative", width: 1480, height: 880 }}>
    <div style={{
      position: "absolute", inset: 0, borderRadius: 18, background: "#1a1a1a", padding: 12,
      boxShadow: "0 30px 80px rgba(0,0,0,0.35)",
    }}>
      <div style={{
        width: "100%", height: "100%", borderRadius: 10, overflow: "hidden",
        background: SURFACE, fontFamily: FONT, color: INK,
      }}>
        {children}
      </div>
    </div>
  </div>
);

// ---------- Scene 1 · Title (270 frames · 9 s) ----------
const TitleCard: React.FC = () => {
  const frame = useCurrentFrame();
  // Logo clip-path reveal, unhurried.
  const draw = interpolate(frame, [30, 130], [0, 100], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE_OUT,
  });
  const logoOpacity = interpolate(frame, [30, 62], [0, 1], { extrapolateRight: "clamp", easing: EASE_IN_OUT });
  // Accent line grows in before the logo.
  const accent = interpolate(frame, [16, 90], [0, 1], { extrapolateRight: "clamp", easing: EASE_OUT });
  // Tagline words stagger in.
  const taglineWords = ["You're", "not", "waiting", "alone."];
  const taglineStart = 135;
  // Subline at the end, then holds for ~1 s before the scene crossfades out.
  const sublineOpacity = interpolate(frame, [200, 225], [0, 1], { extrapolateRight: "clamp" });
  return (
    <SceneWrap duration={270}>
      <AbsoluteFill style={{
        background: `radial-gradient(1400px 900px at 30% 20%, ${PRIMARY_GRAD_FROM} 0%, ${PRIMARY} 45%, #17292e 100%)`,
        alignItems: "center", justifyContent: "center", color: "white", fontFamily: FONT,
      }}>
        {/* Subtle dotted grid for texture */}
        <AbsoluteFill style={{
          opacity: 0.16,
          backgroundImage: "radial-gradient(rgba(255,255,255,0.12) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
          maskImage: "radial-gradient(ellipse 60% 50% at 50% 50%, black 30%, transparent 85%)",
        }} />
        {/* Floating soft orbs */}
        <AmbientOrbs tint="#CBE3E9" opacity={0.08} />

        {/* Thin accent line that grows in */}
        <div style={{
          position: "absolute",
          top: "calc(50% - 150px)", left: "50%",
          transform: `translateX(-50%) scaleX(${accent})`,
          transformOrigin: "center",
          width: 260, height: 1, background: "rgba(255,255,255,0.42)",
        }} />

        {/* Logo with a sliding mask reveal */}
        <div style={{
          fontSize: 200, fontWeight: 800, letterSpacing: "-0.045em", lineHeight: 1,
          opacity: logoOpacity,
          clipPath: `inset(0 ${100 - draw}% 0 0)`,
        }}>
          Solace
        </div>

        {/* Tagline — staggered word fade */}
        <div style={{
          marginTop: 22, fontSize: 34, fontWeight: 400,
          letterSpacing: "-0.01em", color: "rgba(255,255,255,0.85)",
          display: "flex", gap: "0.3em",
        }}>
          {taglineWords.map((w, i) => {
            const start = taglineStart + i * 10;
            const o = interpolate(frame, [start, start + 22], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            return (
              <span key={i} style={{ opacity: o, display: "inline-block" }}>
                {w}
              </span>
            );
          })}
        </div>

        <div style={{
          opacity: sublineOpacity,
          marginTop: 44, fontSize: 14,
          color: "rgba(255,255,255,0.55)",
          letterSpacing: "0.22em", textTransform: "uppercase",
        }}>
          AI-assisted ER triage · Hook'em Hacks 2026
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

// ---------- Scene 2 · Patient intake (1080 frames, 6 sub-scenes) ----------
// Sub-scene windows inside SceneWrap (with SubScene cross-fades):
//   0    -  160   Welcome
//   160  -  320   Medical form
//   320  -  520   Insurance scan
//   520  -  700   Recording
//   700  -  920   Pipeline (extra dwell — models showcase)
//   920  - 1080   Result
const PatientIntakeScene: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <SceneWrap duration={1080}>
      <AbsoluteFill style={{
        background: `radial-gradient(1400px 900px at 50% 50%, ${PRIMARY_GRAD_FROM} 0%, ${PRIMARY} 100%)`,
        alignItems: "center", justifyContent: "center",
      }}>
        <AmbientOrbs tint="#CBE3E9" opacity={0.06} />
        <div style={{ transform: "scale(1.22)", transformOrigin: "center" }}>
          <PhoneFrame>
          <SubScene start={0} end={160} frame={frame}>
            <PhoneWelcome localFrame={frame} />
          </SubScene>
          <SubScene start={160} end={320} frame={frame}>
            <PhoneMedicalForm localFrame={frame - 160} />
          </SubScene>
          <SubScene start={320} end={520} frame={frame}>
            <PhoneInsuranceScan localFrame={frame - 320} />
          </SubScene>
          <SubScene start={520} end={700} frame={frame}>
            <PhoneRecording localFrame={frame - 520} />
          </SubScene>
          <SubScene start={700} end={920} frame={frame}>
            <PhonePipeline localFrame={frame - 700} />
          </SubScene>
          <SubScene start={920} end={1080} frame={frame}>
            <PhoneResult localFrame={frame - 920} />
          </SubScene>
          </PhoneFrame>
        </div>
        <Caption from={20} duration={130}>Patient scans the QR. No install.</Caption>
        <Caption from={180} duration={130}>Adaptive form — branches per answer.</Caption>
        <Caption from={340} duration={170}>Insurance card — Claude Vision auto-fills.</Caption>
        <Caption from={540} duration={150}>Speak your symptoms. Whisper transcribes.</Caption>
        <Caption from={720} duration={190}>Six AI calls in parallel. Result in seconds.</Caption>
        <Caption from={940} duration={130}>ESI + plan + wait time in under 10 seconds.</Caption>
      </AbsoluteFill>
    </SceneWrap>
  );
};

const PhoneHeader: React.FC<{ step?: string; stepIndex?: number }> = ({ step, stepIndex = 0 }) => (
  <div style={{
    padding: "60px 22px 14px", display: "flex", alignItems: "center", justifyContent: "space-between",
    borderBottom: "1px solid rgba(74,85,87,0.06)",
  }}>
    <div>
      <div style={{ fontSize: 10, color: TEXT_MUTED, letterSpacing: "0.14em", textTransform: "uppercase" }}>
        Solace
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-0.03em" }}>
        {step || "Intake"}
      </div>
    </div>
    <div style={{ display: "flex", gap: 5 }}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} style={{
          width: 7, height: 7, borderRadius: 4,
          background: i === stepIndex ? PRIMARY : "rgba(74,85,87,0.22)",
        }} />
      ))}
    </div>
  </div>
);

const PhoneWelcome: React.FC<{ localFrame: number }> = ({ localFrame }) => {
  const o = interpolate(localFrame, [0, 22], [0, 1], { extrapolateRight: "clamp", easing: EASE_OUT });
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <PhoneHeader step="Welcome" stepIndex={0} />
      <div style={{ padding: "24px 22px", flex: 1, display: "flex", flexDirection: "column", gap: 16, opacity: o }}>
        <div>
          <h1 style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.08, margin: 0 }}>
            You're not waiting alone.
          </h1>
          <p style={{ fontSize: 13.5, color: TEXT_MUTED, marginTop: 8, lineHeight: 1.5 }}>
            Tell us your story once. By the time a clinician sees you, they'll already know.
          </p>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Your first name</div>
          <div style={{
            height: 50, padding: "0 16px", borderRadius: 10, background: SURFACE_LOWEST,
            display: "flex", alignItems: "center", fontSize: 17, color: INK,
            boxShadow: "0 4px 16px rgba(42,71,78,0.06)", border: "1px solid rgba(74,85,87,0.08)",
          }}>Sriyan Bodla</div>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Preferred language</div>
          <div style={{
            height: 42, padding: "0 14px", borderRadius: 10, background: SURFACE_LOWEST,
            display: "flex", alignItems: "center", fontSize: 14,
            boxShadow: "0 4px 16px rgba(42,71,78,0.06)",
          }}>English</div>
        </div>
        <div style={{
          padding: 12, borderRadius: 12, background: SURFACE_LOWEST, border: "1px solid rgba(74,85,87,0.08)",
          display: "flex", gap: 12, fontSize: 11, lineHeight: 1.5, color: INK,
        }}>
          <div style={{
            width: 18, height: 18, borderRadius: 4, background: PRIMARY, flexShrink: 0, marginTop: 2,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3">
              <polyline points="4 12 10 18 20 6" />
            </svg>
          </div>
          <div><b>I consent to AI processing</b> by OpenAI, Anthropic, ElevenLabs for triage.</div>
        </div>
        <div style={{
          height: 50, borderRadius: 10,
          background: `linear-gradient(180deg, ${PRIMARY_GRAD_FROM}, ${PRIMARY})`,
          color: "white", display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 16, fontWeight: 600, letterSpacing: "-0.01em",
          boxShadow: "0 8px 24px rgba(42,71,78,0.22)",
        }}>Next</div>
      </div>
    </div>
  );
};

const Chip: React.FC<{ children: React.ReactNode; selected?: boolean }> = ({ children, selected }) => (
  <div style={{
    minHeight: 32, padding: "0 13px", borderRadius: 999, fontSize: 12, fontWeight: 500,
    background: selected ? PRIMARY : SURFACE_LOWEST, color: selected ? "white" : INK,
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    boxShadow: selected ? "0 4px 12px rgba(42,71,78,0.12)" : "none",
    border: selected ? "none" : "1px solid rgba(74,85,87,0.18)",
    transition: "all 0.2s",
  }}>{children}</div>
);

const PhoneMedicalForm: React.FC<{ localFrame: number }> = ({ localFrame }) => {
  const ageVisible = localFrame > 8;
  const sexSelected = localFrame > 28;
  const condSelected = localFrame > 58;
  const followupVisible = localFrame > 90;
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <PhoneHeader step="Medical details" stepIndex={1} />
      <div style={{ padding: "20px 22px", flex: 1, display: "flex", flexDirection: "column", gap: 14, overflow: "hidden" }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Age</div>
          <div style={{
            height: 40, padding: "0 12px", borderRadius: 8, background: SURFACE_LOWEST,
            display: "flex", alignItems: "center", fontSize: 14,
            border: `1px solid ${ageVisible ? PRIMARY : "rgba(74,85,87,0.1)"}`,
          }}>{ageVisible ? "19" : ""}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Sex</div>
          <div style={{ display: "flex", gap: 6 }}>
            <Chip selected={sexSelected}>Male</Chip>
            <Chip>Female</Chip>
            <Chip>Other</Chip>
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Existing conditions</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <Chip>None</Chip>
            <Chip>Diabetes</Chip>
            <Chip>Hypertension</Chip>
            <Chip selected={condSelected}>Asthma</Chip>
            <Chip>COPD</Chip>
            <Chip>Heart disease</Chip>
          </div>
        </div>
        {followupVisible && (
          <div style={{
            marginTop: 4, borderLeft: `2px solid ${PRIMARY_FIXED}`, paddingLeft: 12,
            opacity: interpolate(localFrame, [90, 115], [0, 1], { extrapolateRight: "clamp" }),
          }}>
            <div style={{ fontSize: 10, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
              Adaptive follow-up
            </div>
            <div style={{ fontSize: 12, marginBottom: 6 }}>When was your last asthma exacerbation?</div>
            <div style={{ display: "flex", gap: 6 }}>
              <Chip>{"< 1 month"}</Chip>
              <Chip>{"1–6 months"}</Chip>
              <Chip selected>{"> 1 year"}</Chip>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Insurance card capture + auto-fill (200 frames — 6.7 s).
//   0-60    Viewfinder approach, card zooms in
//   60-90   Capture flash
//   80-200  Extracted fields — unhurried stagger, then dwell
const PhoneInsuranceScan: React.FC<{ localFrame: number }> = ({ localFrame }) => {
  const inFrame = Math.max(0, Math.min(1, localFrame / 55));
  const flash = localFrame >= 62 && localFrame <= 80 ? Math.max(0, 1 - Math.abs(localFrame - 68) / 10) : 0;
  const viewfinderOpacity = interpolate(localFrame, [75, 100], [1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE_IN_OUT,
  });
  const formOpacity = interpolate(localFrame, [78, 108], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE_IN_OUT,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", position: "relative" }}>
      <PhoneHeader step="Insurance card" stepIndex={2} />

      {/* Viewfinder */}
      {viewfinderOpacity > 0.01 && (
        <div style={{
          flex: 1, position: "relative", overflow: "hidden",
          background: "#0B0E0F", opacity: viewfinderOpacity,
        }}>
          <div style={{
            position: "absolute", inset: 0,
            background: "radial-gradient(600px 400px at 50% 50%, rgba(203,227,233,0.04), transparent)",
          }} />
          {/* Card outline guide + mock card */}
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            transform: `translate(-50%, -50%) scale(${0.88 + inFrame * 0.12})`,
            width: 320, height: 200, borderRadius: 14,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)",
            border: "2px solid rgba(203,227,233,0.55)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <div style={{
              width: 300, height: 180, borderRadius: 10,
              background: `linear-gradient(135deg, #1D3339 0%, #2A474E 60%, #3B5E67 100%)`,
              color: "white", padding: "14px 16px", position: "relative",
              opacity: Math.min(1, inFrame * 1.3),
              boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
              fontFamily: FONT,
            }}>
              <div style={{ fontSize: 9, letterSpacing: "0.18em", textTransform: "uppercase", opacity: 0.7 }}>
                BlueCross · BlueShield TX
              </div>
              <div style={{ fontSize: 13, fontWeight: 700, marginTop: 4, letterSpacing: "-0.02em" }}>
                UT Austin Student Plan
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, marginTop: 18, fontSize: 9 }}>
                <div>
                  <div style={{ opacity: 0.6, letterSpacing: "0.08em", textTransform: "uppercase" }}>Member</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", marginTop: 1 }}>4K8X-9920-4411</div>
                </div>
                <div>
                  <div style={{ opacity: 0.6, letterSpacing: "0.08em", textTransform: "uppercase" }}>Group</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", marginTop: 1 }}>SB1204</div>
                </div>
              </div>
              <div style={{ marginTop: 10, fontSize: 11, fontWeight: 600, letterSpacing: "-0.01em" }}>
                SRIYAN BODLA
              </div>
            </div>
          </div>
          {/* Corner brackets */}
          {[
            { top: 230, left: 70 }, { top: 230, right: 70 },
            { bottom: 230, left: 70 }, { bottom: 230, right: 70 },
          ].map((pos, i) => (
            <div key={i} style={{
              position: "absolute", width: 20, height: 20,
              borderTop: i < 2 ? "2px solid #CBE3E9" : "none",
              borderBottom: i >= 2 ? "2px solid #CBE3E9" : "none",
              borderLeft: (i === 0 || i === 2) ? "2px solid #CBE3E9" : "none",
              borderRight: (i === 1 || i === 3) ? "2px solid #CBE3E9" : "none",
              ...pos,
            }} />
          ))}
          <div style={{
            position: "absolute", bottom: 24, left: 0, right: 0, textAlign: "center",
            color: "rgba(203,227,233,0.85)", fontSize: 11, letterSpacing: "0.18em", textTransform: "uppercase",
          }}>
            {localFrame < 55 ? "Align the card" : "Capturing…"}
          </div>
        </div>
      )}

      {/* Capture flash — softer, wider fade so it doesn't pop */}
      {flash > 0 && (
        <div style={{
          position: "absolute", inset: 0, background: "white",
          opacity: flash * 0.85, pointerEvents: "none",
        }} />
      )}

      {/* Extracted fields */}
      {formOpacity > 0.001 && (
        <div style={{
          position: "absolute", top: 120, left: 0, right: 0, bottom: 0,
          padding: "20px 22px", display: "flex", flexDirection: "column", gap: 12,
          background: SURFACE_LOWEST, opacity: formOpacity,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "8px 10px", borderRadius: 8, background: "#E8F1F1",
          }}>
            <div style={{
              width: 16, height: 16, borderRadius: 8, background: PRIMARY,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3">
                <polyline points="4 12 10 18 20 6" />
              </svg>
            </div>
            <span style={{ fontSize: 11, color: PRIMARY, fontWeight: 600 }}>Card recognized · Claude Vision</span>
          </div>
          {[
            ["Provider", "BlueCross BlueShield TX"],
            ["Plan", "UT Austin Student"],
            ["Member ID", "4K8X-9920-4411"],
            ["Group", "SB1204"],
            ["Name on card", "SRIYAN BODLA"],
          ].map(([k, v], i) => {
            const appearStart = 92 + i * 8;
            const appear = interpolate(localFrame, [appearStart, appearStart + 20], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            return (
              <div key={k} style={{
                opacity: appear,
                padding: "10px 12px", borderRadius: 8, background: SURFACE_LOW,
              }}>
                <div style={{ fontSize: 9, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.12em" }}>{k}</div>
                <div style={{ fontSize: 13, color: INK, fontWeight: 600, marginTop: 2, letterSpacing: "-0.01em" }}>{v}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const PhoneRecording: React.FC<{ localFrame: number }> = ({ localFrame }) => {
  const { fps } = useVideoConfig();
  const breathe = 1 + 0.07 * Math.sin((localFrame / fps) * Math.PI * 2);
  const seconds = Math.min(Math.floor(localFrame / fps * 1.1), 9);
  const ring1 = 0.35 + 0.25 * Math.sin((localFrame / fps) * Math.PI);
  const ring2 = 0.2 + 0.22 * Math.sin((localFrame / fps + 0.5) * Math.PI);
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <PhoneHeader step="Record symptoms" stepIndex={3} />
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 22, padding: 22,
      }}>
        <div style={{ fontSize: 14, color: TEXT_MUTED, textAlign: "center", lineHeight: 1.5 }}>
          Describe what brought you in, in your own words.
        </div>
        <div style={{ position: "relative", width: 200, height: 200 }}>
          <div style={{
            position: "absolute", inset: 0, borderRadius: "50%",
            background: PRIMARY, opacity: ring2 * 0.15, transform: `scale(${1.4 + ring2 * 0.15})`,
          }} />
          <div style={{
            position: "absolute", inset: 0, borderRadius: "50%",
            background: PRIMARY, opacity: ring1 * 0.3, transform: `scale(${1.15 + ring1 * 0.1})`,
          }} />
          <div style={{
            position: "absolute", inset: 0, borderRadius: "50%",
            background: `linear-gradient(180deg, ${PRIMARY_GRAD_FROM}, ${PRIMARY})`,
            transform: `scale(${breathe})`, display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 20px 50px rgba(42,71,78,0.35)",
          }}>
            <svg width="72" height="72" viewBox="0 0 24 24" fill="white">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zm7 11v0a7 7 0 0 1-14 0v0m7 7v4m-4 0h8"
                stroke="white" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>
        <div style={{
          fontSize: 32, fontWeight: 800, color: PRIMARY, letterSpacing: "-0.03em",
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          00:{String(seconds).padStart(2, "0")}
        </div>
        <div style={{ fontSize: 11, color: TEXT_MUTED, letterSpacing: "0.14em", textTransform: "uppercase" }}>
          Recording · tap to finish
        </div>
      </div>
    </div>
  );
};

// Pipeline (220 frames — models showcase, unhurried cascade + dwell).
const PhonePipeline: React.FC<{ localFrame: number }> = ({ localFrame }) => {
  const rows = [
    { label: "Whisper", sub: "Transcribing audio", start: 4 },
    { label: "Claude · pre-brief", sub: "Clinician summary", start: 28 },
    { label: "Claude · AI scribe", sub: "SOAP shorthand", start: 52 },
    { label: "Claude · comfort protocol", sub: "3 actions for ESI", start: 76 },
    { label: "Triage engine", sub: "ESI + conformal", start: 100 },
    { label: "ElevenLabs · voice", sub: "Empathetic audio", start: 124 },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <PhoneHeader step="Working…" stepIndex={4} />
      <div style={{ padding: "22px 22px", display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ fontSize: 13, color: TEXT_MUTED, lineHeight: 1.5 }}>
          Six AI calls running in parallel. Result in a few seconds.
        </div>
        {rows.map((r) => {
          const rowOpacity = interpolate(
            localFrame, [r.start, r.start + 14], [0.4, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );
          const completeProgress = interpolate(
            localFrame, [r.start + 18, r.start + 28], [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );
          const complete = completeProgress >= 0.95;
          const inProgress = localFrame >= r.start + 8 && !complete;
          return (
            <div key={r.label} style={{
              padding: "10px 12px", borderRadius: 10, background: SURFACE_LOWEST,
              display: "flex", alignItems: "center", gap: 12,
              opacity: rowOpacity,
              boxShadow: rowOpacity > 0.6 ? "0 4px 14px rgba(42,71,78,0.06)" : "none",
            }}>
              <div style={{
                width: 22, height: 22, borderRadius: 11,
                background: complete ? PRIMARY : (inProgress ? PRIMARY_FIXED : "rgba(74,85,87,0.12)"),
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                transition: "background 0.4s",
              }}>
                {complete && (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3">
                    <polyline points="4 12 10 18 20 6" />
                  </svg>
                )}
                {inProgress && (
                  <div style={{ width: 8, height: 8, borderRadius: 4, background: PRIMARY }} />
                )}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: PRIMARY, letterSpacing: "-0.01em" }}>{r.label}</div>
                <div style={{ fontSize: 11, color: TEXT_MUTED }}>{r.sub}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const PhoneResult: React.FC<{ localFrame: number }> = ({ localFrame }) => {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <PhoneHeader step="Your plan" stepIndex={5} />
      <div style={{ padding: "22px 22px", display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{
            width: 64, height: 64, borderRadius: 32, background: ESI_COLORS[2],
            color: "white", fontSize: 28, fontWeight: 800, letterSpacing: "-0.04em",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 12px 28px rgba(176,84,54,0.32)",
          }}>2</div>
          <div>
            <div style={{ fontSize: 10, color: TEXT_MUTED, letterSpacing: "0.14em", textTransform: "uppercase" }}>Priority</div>
            <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.03em" }}>Emergent</div>
          </div>
        </div>
        <div style={{ padding: 12, borderRadius: 10, background: SURFACE_LOW, fontSize: 12, lineHeight: 1.55, color: INK }}>
          Your symptoms suggest something serious. You'll be seen soon.
        </div>
        <div style={{
          padding: "10px 12px", borderRadius: 10, background: SURFACE_LOWEST,
          boxShadow: "0 4px 14px rgba(42,71,78,0.06)",
        }}>
          <div style={{ fontSize: 9.5, color: TEXT_MUTED, letterSpacing: "0.14em", textTransform: "uppercase" }}>
            Estimated wait
          </div>
          <div style={{ fontSize: 18, fontWeight: 800, color: PRIMARY, letterSpacing: "-0.02em" }}>10–20 min</div>
        </div>
        {[
          ["Stay still", "Sit or lie down. Avoid walking."],
          ["Slow breathing", "Inhale 4 sec, hold 4, exhale 6."],
          ["No food or water", "A doctor may order tests."],
        ].map(([t, d], i) => (
          <div key={t} style={{
            padding: 12, borderRadius: 10, background: SURFACE_LOWEST,
            display: "flex", gap: 12, boxShadow: "0 4px 14px rgba(42,71,78,0.06)",
            opacity: interpolate(localFrame, [i * 10 + 10, i * 10 + 30], [0, 1], { extrapolateRight: "clamp" }),
          }}>
            <div style={{
              width: 26, height: 26, borderRadius: 13, background: PRIMARY_FIXED,
              color: PRIMARY, fontWeight: 800, fontSize: 13,
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>{i + 1}</div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "-0.01em" }}>{t}</div>
              <div style={{ fontSize: 11, color: TEXT_MUTED, marginTop: 2 }}>{d}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ---------- Scene 3 · Time-warp (120 frames) ----------
const TimeWarpCard: React.FC = () => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [0, 30], [0, 1], { extrapolateRight: "clamp" });
  return (
    <SceneWrap duration={120}>
      <AbsoluteFill style={{
        background: "white", alignItems: "center", justifyContent: "center", fontFamily: FONT,
      }}>
        <AmbientOrbs tint="#CBE3E9" opacity={0.15} />
        <div style={{ opacity: o, textAlign: "center", position: "relative" }}>
          <div style={{
            fontSize: 26, fontWeight: 500, color: TEXT_MUTED, letterSpacing: "0.16em",
            textTransform: "uppercase", marginBottom: 20,
          }}>Meanwhile, across the ED</div>
          <div style={{ fontSize: 140, fontWeight: 800, color: PRIMARY, letterSpacing: "-0.045em", lineHeight: 1 }}>
            ~7 seconds later
          </div>
          <div style={{
            fontSize: 26, fontWeight: 400, color: TEXT_MUTED, marginTop: 16, letterSpacing: "-0.01em",
          }}>
            The same data is on the clinician's screen.
          </div>
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

// ---------- Scene 4 · Clinician dashboard (600 frames) ----------
const ClinicianDashboardScene: React.FC = () => {
  const frame = useCurrentFrame();
  const detailOpen = frame >= 170;
  const detailProgress = interpolate(frame, [170, 210], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  return (
    <SceneWrap duration={600}>
      <AbsoluteFill style={{
        background: "radial-gradient(1200px 600px at 20% -10%, rgba(203,227,233,0.35) 0%, transparent 60%), " +
                    "radial-gradient(1000px 500px at 100% 100%, rgba(203,227,233,0.22) 0%, transparent 55%), " + SURFACE,
        alignItems: "center", justifyContent: "center",
      }}>
        <AmbientOrbs tint="#CBE3E9" opacity={0.15} />
        <LaptopFrame>
          <div style={{ display: "flex", height: "100%", position: "relative" }}>
            <DesktopSidebar />
            <DesktopQueue animateArrival={frame < 170} />
            {detailOpen && (
              <div style={{
                position: "absolute", top: 12, right: 12, bottom: 12, width: 600,
                background: SURFACE_LOWEST, borderRadius: 10,
                opacity: detailProgress,
                boxShadow: "-20px 0 40px rgba(0,0,0,0.15)", overflow: "hidden",
              }}>
                <DesktopDetailPane localFrame={frame - 170} />
              </div>
            )}
          </div>
        </LaptopFrame>
        <Caption from={18} duration={140}>New arrival. Pre-brief, scribe, SHAP — before rooming.</Caption>
        <Caption from={210} duration={180}>EHR auto-matches — asthma hx, family cardiac risk, prior visits.</Caption>
        <Caption from={410} duration={170}>Clinician walks in already informed.</Caption>
      </AbsoluteFill>
    </SceneWrap>
  );
};

const DesktopSidebar: React.FC = () => (
  <div style={{
    width: 260, background: SURFACE_LOW, padding: 20, display: "flex", flexDirection: "column", gap: 18,
    borderRight: "1px solid rgba(74,85,87,0.05)",
  }}>
    <div>
      <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.04em" }}>Solace</div>
      <div style={{ fontSize: 11, color: TEXT_MUTED }}>Clinician Terminal</div>
    </div>
    <div style={{
      display: "flex", alignItems: "center", gap: 10, padding: "10px 12px",
      borderRadius: 10, background: SURFACE_LOWEST, boxShadow: "0 4px 12px rgba(42,71,78,0.05)",
    }}>
      <div style={{
        width: 34, height: 34, borderRadius: 17, background: `linear-gradient(180deg, ${PRIMARY_GRAD_FROM}, ${PRIMARY})`,
        color: "white", display: "flex", alignItems: "center", justifyContent: "center",
        fontWeight: 700, fontSize: 13,
      }}>C</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: PRIMARY, letterSpacing: "-0.01em" }}>Dr. Chen</div>
        <div style={{ fontSize: 9, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.12em" }}>Chief</div>
      </div>
    </div>
    <div>
      <div style={{
        padding: "8px 12px", borderRadius: 6, background: PRIMARY_FIXED, color: PRIMARY,
        fontSize: 12, fontWeight: 600, marginBottom: 4,
      }}>Waiting (6)</div>
      <div style={{ padding: "8px 12px", fontSize: 12, color: TEXT_MUTED }}>All</div>
    </div>
  </div>
);

const DesktopQueue: React.FC<{ animateArrival: boolean }> = ({ animateArrival }) => {
  const frame = useCurrentFrame();
  const arrivalOpacity = animateArrival
    ? interpolate(frame, [28, 52, 140, 164], [0, 1, 1, 0], {
        extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE_IN_OUT,
      })
    : 0;
  const patients = [
    { name: "Sriyan Bodla", esi: 2, brief: "19yo male c/o chest pain x 1hr post-exertion. Asthma hx. F-hx MI age 62." },
    { name: "Marcus", esi: 2, brief: "38yo male c/o chest pain, radiates to jaw. SOB + sweating. HTN hx." },
    { name: "Elena", esi: 2, brief: "33yo female c/o severe L-hand laceration, active bleeding." },
    { name: "Priya", esi: 3, brief: "36yo female c/o severe HA + vomiting x 2d. Migraine hx. Pain-flagged." },
    { name: "James", esi: 4, brief: "25yo male c/o R-ankle sprain from basketball. No weight-bearing." },
    { name: "Sofia", esi: 5, brief: "26yo female c/o medication refill, levothyroxine. Otherwise well." },
  ];
  return (
    <div style={{ flex: 1, padding: 24, overflow: "hidden" }}>
      {arrivalOpacity > 0 && (
        <div style={{
          marginBottom: 14, padding: "10px 14px", borderRadius: 8, background: PRIMARY, color: "white",
          display: "flex", alignItems: "center", gap: 12, fontSize: 13, opacity: arrivalOpacity,
          boxShadow: "0 12px 32px rgba(42,71,78,0.22)",
        }}>
          <span style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.14em" }}>New arrival</span>
          <span>Sriyan Bodla just checked in.</span>
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {patients.map((p, i) => {
          const start = i * 6;
          const appear = interpolate(frame, [start, start + 28], [0, 1], {
            extrapolateLeft: "clamp", extrapolateRight: "clamp",
          });
          return (
            <div key={p.name} style={{
              padding: 16, borderRadius: 10, background: SURFACE_LOWEST,
              boxShadow: "0 6px 18px rgba(42,71,78,0.05)",
              opacity: appear,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.02em" }}>{p.name}</div>
                  <div style={{ fontSize: 9, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.12em", marginTop: 1 }}>
                    Vitals pending
                  </div>
                </div>
                <div style={{
                  width: 32, height: 32, borderRadius: 16, background: ESI_COLORS[p.esi],
                  color: "white", fontSize: 14, fontWeight: 800, letterSpacing: "-0.03em",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>{p.esi}</div>
              </div>
              <div style={{
                fontSize: 11, color: INK, fontFamily: "'JetBrains Mono', monospace",
                lineHeight: 1.55, opacity: 0.85,
              }}>{p.brief}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const DesktopDetailPane: React.FC<{ localFrame: number }> = ({ localFrame }) => (
  <div style={{ padding: 22, height: "100%", overflow: "hidden", display: "flex", flexDirection: "column", gap: 16 }}>
    <div>
      <div style={{ fontSize: 10, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.14em" }}>
        Patient detail
      </div>
      <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.04em", marginTop: 2 }}>Sriyan Bodla</div>
      <div style={{ fontSize: 11, color: TEXT_MUTED, fontFamily: "'JetBrains Mono', monospace", marginTop: 4 }}>
        waited 0m · EN
      </div>
    </div>

    <div style={{ padding: 14, borderRadius: 10, background: SURFACE_LOWEST, boxShadow: "0 4px 14px rgba(42,71,78,0.05)" }}>
      <div style={{ fontSize: 9, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.14em", marginBottom: 10 }}>
        Triage acuity
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div>
          <div style={{ fontSize: 9, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.1em" }}>Provisional</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{ fontSize: 22, fontWeight: 800, color: PRIMARY }}>ESI 2</span>
            <span style={{ fontSize: 11, color: TEXT_MUTED, fontFamily: "'JetBrains Mono', monospace" }}>62%</span>
          </div>
        </div>
        <div style={{ fontSize: 18, color: TEXT_MUTED }}>→</div>
        <div>
          <div style={{ fontSize: 9, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.1em" }}>Refined · bedside ML</div>
          <div style={{ fontSize: 14, color: TEXT_MUTED, fontStyle: "italic" }}>take vitals to refine</div>
        </div>
      </div>
    </div>

    <div style={{
      padding: 14, borderRadius: 12, background: SURFACE_LOWEST, boxShadow: "0 8px 24px rgba(42,71,78,0.06)",
      opacity: interpolate(localFrame, [40, 75], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: PRIMARY, marginBottom: 10, letterSpacing: "-0.01em" }}>
        EHR · Connected Health Record (FHIR R4 shape)
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: PRIMARY }}>Sriyan Bodla</div>
        <span style={{ fontSize: 9, color: TEXT_MUTED, fontFamily: "'JetBrains Mono', monospace" }}>MRN SB-2026-001</span>
        <span style={{ fontSize: 10, color: TEXT_MUTED }}>· 19 y · male · O+</span>
      </div>
      <div style={{ height: 1, background: "rgba(74,85,87,0.08)", margin: "8px 0 12px" }} />
      {[
        ["Allergies", "NKDA"],
        ["Medications", "Albuterol HFA inhaler — PRN"],
        ["Conditions", "Mild intermittent asthma (childhood)"],
        ["Family history", "Father: HTN · Mother: T2DM · M. grandfather: MI age 62"],
        ["Primary care", "Dr. Anjali Patel — Austin Family Medicine"],
      ].map(([k, v], i) => (
        <div key={k} style={{
          display: "grid", gridTemplateColumns: "140px 1fr", gap: 10, padding: "3px 0", fontSize: 11,
          opacity: interpolate(localFrame, [80 + i * 8, 105 + i * 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
        }}>
          <div style={{ color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.12em", fontSize: 9, fontWeight: 600 }}>{k}</div>
          <div style={{ color: INK, lineHeight: 1.55 }}>{v}</div>
        </div>
      ))}
      <div style={{ marginTop: 10, fontSize: 10, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.12em", fontWeight: 600 }}>
        Prior visits
      </div>
      {[
        ["2022-11-03 · ED", "URI, viral; supportive care"],
        ["2019-08-12 · Urgent Care", "R wrist sprain, splint + PCP"],
      ].map(([date, note], i) => (
        <div key={date} style={{
          borderLeft: `2px solid ${PRIMARY_FIXED}`, paddingLeft: 10, marginTop: 8, fontSize: 11,
          opacity: interpolate(localFrame, [140 + i * 10, 160 + i * 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
        }}>
          <div style={{ fontWeight: 600, color: PRIMARY }}>{date}</div>
          <div style={{ color: TEXT_MUTED, marginTop: 1 }}>{note}</div>
        </div>
      ))}
    </div>
  </div>
);

// ---------- Scene 5 · Vitals refinement (330 frames) ----------
const VitalsRefineScene: React.FC = () => {
  const frame = useCurrentFrame();
  const vitalsFilled = Math.min(1, frame / 110);
  return (
    <SceneWrap duration={330}>
      <AbsoluteFill style={{
        background: "radial-gradient(900px 500px at 50% -10%, rgba(203,227,233,0.32) 0%, transparent 55%), " + SURFACE,
        alignItems: "center", justifyContent: "center",
      }}>
        <AmbientOrbs tint="#CBE3E9" opacity={0.12} />
        <div style={{
          width: 900, background: SURFACE_LOWEST, borderRadius: 16, padding: 28,
          boxShadow: "0 40px 120px rgba(42,71,78,0.14)",
          display: "flex", flexDirection: "column", gap: 18, fontFamily: FONT,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 28, height: 28, borderRadius: 14, background: PRIMARY_FIXED,
              color: PRIMARY, display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={PRIMARY} strokeWidth="2.2">
                <path d="M3 12h4l3-9 4 18 3-9h4" />
              </svg>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: PRIMARY }}>
              Bedside vitals → ML triage refinement
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
            {[
              { label: "HR", value: 132, unit: "bpm", critical: true },
              { label: "Systolic BP", value: 88, unit: "mmHg", critical: true },
              { label: "Resp rate", value: 28, unit: "/min", critical: true },
              { label: "SpO₂", value: 92, unit: "%", critical: true },
              { label: "Temp", value: "37.2", unit: "°C", critical: false },
              { label: "GCS", value: 15, unit: "", critical: false },
              { label: "Pain", value: 8, unit: "/10", critical: false },
              { label: "Mental", value: "alert", unit: "", critical: false },
            ].map((v, i) => {
              const p = Math.max(0, Math.min(1, vitalsFilled * 10 - i));
              return (
                <div key={v.label} style={{
                  padding: 12, borderRadius: 10, background: SURFACE_LOW,
                  borderLeft: v.critical && p >= 1 ? `3px solid ${ESI_COLORS[2]}` : "3px solid transparent",
                  transition: "border-left 0.4s",
                }}>
                  <div style={{ fontSize: 10, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.12em" }}>{v.label}</div>
                  <div style={{
                    fontSize: 22, fontWeight: 800,
                    color: p >= 1 ? (v.critical ? ESI_COLORS[2] : PRIMARY) : TEXT_MUTED,
                    letterSpacing: "-0.02em", marginTop: 2,
                  }}>
                    {p > 0 ? v.value : "—"}
                    <span style={{ fontSize: 11, fontWeight: 500, color: TEXT_MUTED, marginLeft: 4 }}>
                      {p > 0 && v.unit}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {frame >= 110 && (
            <div style={{
              padding: 18, borderRadius: 12, background: SURFACE_LOW,
              opacity: interpolate(frame, [110, 135], [0, 1], { extrapolateRight: "clamp" }),
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                <div style={{
                  width: 52, height: 52, borderRadius: 26, background: ESI_COLORS[2], color: "white",
                  fontSize: 24, fontWeight: 800, letterSpacing: "-0.04em",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>2</div>
                <div>
                  <div style={{ fontSize: 10, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.14em" }}>Refined</div>
                  <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-0.03em" }}>
                    ESI 2 · 76% conf · conformal {"{2}"}
                  </div>
                </div>
              </div>
              <div style={{ fontSize: 11, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 8 }}>
                SHAP feature contributions
              </div>
              {[
                { feat: "SpO₂", val: 92, shap: 0.42 },
                { feat: "shock_index", val: 1.5, shap: 0.35 },
                { feat: "num_abnormal_vitals", val: 6, shap: 0.28 },
                { feat: "pain_score", val: 8, shap: 0.12 },
                { feat: "text·\"chest pain\"", val: 1, shap: 0.09 },
              ].map((f, i) => {
                const widthPct = interpolate(
                  frame,
                  [135 + i * 10, 170 + i * 10],
                  [0, (f.shap / 0.42) * 100],
                  { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE_OUT },
                );
                return (
                  <div key={f.feat} style={{
                    display: "grid", gridTemplateColumns: "200px 60px 1fr 80px", gap: 10,
                    alignItems: "center", padding: "3px 0", fontSize: 11,
                  }}>
                    <span style={{ color: PRIMARY, fontFamily: "'JetBrains Mono', monospace" }}>{f.feat}</span>
                    <span style={{ color: TEXT_MUTED, fontFamily: "'JetBrains Mono', monospace", textAlign: "right" }}>{f.val}</span>
                    <div style={{ height: 6, background: "rgba(74,85,87,0.08)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${widthPct}%`, background: PRIMARY, borderRadius: 3 }} />
                    </div>
                    <span style={{ color: PRIMARY, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, textAlign: "right" }}>
                      +{f.shap.toFixed(3)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <Caption from={8} duration={110}>Vitals enter — shock index + hypoxia flag critical.</Caption>
        <Caption from={130} duration={190}>LightGBM refines the ESI with real SHAP + conformal coverage.</Caption>
      </AbsoluteFill>
    </SceneWrap>
  );
};

// ---------- Scene 6 · Closing stats (300 frames) ----------
const ClosingStatsScene: React.FC = () => {
  const frame = useCurrentFrame();
  const items = [
    { label: "Intake time", value: "~7 s", sub: "Parallel Claude + Whisper + TTS" },
    { label: "Clinician workflow", value: "Pre-briefed", sub: "Ready before rooming" },
    { label: "Data at rest", value: "CMK-encrypted", sub: "Your key, your audit trail" },
    { label: "AI attribution", value: "Per call", sub: "FHIR-shape · Bedrock-ready" },
  ];
  return (
    <SceneWrap duration={300}>
      <AbsoluteFill style={{
        background: `linear-gradient(180deg, #f8fafa 0%, #e9f1f1 100%)`,
        padding: 72, fontFamily: FONT, alignItems: "center", justifyContent: "center",
      }}>
        <AmbientOrbs tint="#CBE3E9" opacity={0.18} />
        <div style={{
          fontSize: 50, fontWeight: 700, color: PRIMARY, letterSpacing: "-0.035em",
          marginBottom: 32, textAlign: "center", maxWidth: 1400, lineHeight: 1.15, position: "relative",
          opacity: interpolate(frame, [8, 40], [0, 1], { extrapolateRight: "clamp" }),
        }}>
          Solace gets every ER visit started 10 minutes sooner.
        </div>
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 22, maxWidth: 1400, width: "100%",
          position: "relative",
        }}>
          {items.map((it, i) => {
            const start = 40 + i * 14;
            const appear = interpolate(frame, [start, start + 32], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            return (
              <div key={it.label} style={{
                opacity: appear,
                background: "white", borderRadius: 18, padding: 28,
                boxShadow: "0 16px 48px rgba(42,71,78,0.10)",
              }}>
                <div style={{
                  fontSize: 13, fontWeight: 600, color: TEXT_MUTED,
                  letterSpacing: "0.15em", textTransform: "uppercase",
                }}>{it.label}</div>
                <div style={{
                  fontSize: 48, fontWeight: 800, color: PRIMARY, letterSpacing: "-0.035em",
                  marginTop: 6, lineHeight: 1,
                }}>{it.value}</div>
                <div style={{ fontSize: 18, color: TEXT_MUTED, marginTop: 4 }}>{it.sub}</div>
              </div>
            );
          })}
        </div>
        <div style={{
          fontSize: 14, color: TEXT_MUTED, marginTop: 36,
          letterSpacing: "0.18em", textTransform: "uppercase", position: "relative",
          fontWeight: 600,
          opacity: interpolate(frame, [130, 160], [0, 1], { extrapolateRight: "clamp" }),
        }}>
          Solace · Hook'em Hacks 2026
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

// ---------- Composition ----------
export const Solace: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: "black" }}>
      <Sequence from={0}    durationInFrames={270}><TitleCard /></Sequence>
      <Sequence from={246}  durationInFrames={1080}><PatientIntakeScene /></Sequence>
      <Sequence from={1302} durationInFrames={120}><TimeWarpCard /></Sequence>
      <Sequence from={1398} durationInFrames={600}><ClinicianDashboardScene /></Sequence>
      <Sequence from={1974} durationInFrames={330}><VitalsRefineScene /></Sequence>
      <Sequence from={2280} durationInFrames={300}><ClosingStatsScene /></Sequence>
    </AbsoluteFill>
  );
};
