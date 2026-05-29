import { useCallback, useEffect, useRef, useState } from "react";
import {
  GripVertical,
  Monitor,
  PanelLeft,
  PanelRight,
  RefreshCw,
  RotateCcw,
  Smartphone,
  Stethoscope,
} from "lucide-react";
import { loginClinician, resetDemo } from "../lib/api";
import { saveSession } from "../lib/session";

// Standalone split-screen showcase: patient intake (left) and the live clinician
// dashboard (right) side by side, each a same-origin iframe of the real /demo
// routes. A draggable divider resizes the two panes; preset buttons jump to
// common splits. On narrow screens the panes stack and the divider is hidden.
//
// The clinician pane is signed in automatically: this shell logs in as a demo
// clinician and writes the session to localStorage (shared across same-origin
// iframes), so the dashboard iframe loads authenticated with no click.
const DEMO_HOSPITAL = "demo";
const DEMO_CLINICIAN = { name: "Dr. Chen", pin: "224466" };
const MIN_PCT = 20; // never let a pane get narrower than this
const MAX_PCT = 80;

export default function ShowcaseDemo() {
  const [ready, setReady] = useState(false);
  const [nonce, setNonce] = useState(0); // bump to remount both iframes
  const [resetting, setResetting] = useState(false);

  // Resizable split — leftPct is the patient pane's share of the width.
  const [leftPct, setLeftPct] = useState(45);
  const [dragging, setDragging] = useState(false);
  const [isWide, setIsWide] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches,
  );
  const splitRef = useRef<HTMLDivElement>(null);

  // Track the lg breakpoint so the divider only applies when side-by-side.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const onChange = (e: MediaQueryListEvent) => setIsWide(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    // Best-effort auto-sign-in so the clinician pane is live immediately.
    let cancelled = false;
    loginClinician(DEMO_HOSPITAL, DEMO_CLINICIAN.name, DEMO_CLINICIAN.pin)
      .then((resp) => {
        if (!cancelled) saveSession(resp);
      })
      .catch(() => {
        /* fall back to the dashboard's own sign-in screen */
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onPointerMove = useCallback((clientX: number) => {
    const el = splitRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const pct = ((clientX - rect.left) / rect.width) * 100;
    setLeftPct(Math.min(MAX_PCT, Math.max(MIN_PCT, pct)));
  }, []);

  // Window-level listeners during a drag so the pointer can travel over the
  // iframes (which are made non-interactive while dragging) without losing it.
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => onPointerMove(e.clientX);
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [dragging, onPointerMove]);

  function reloadBoth() {
    setNonce((n) => n + 1);
  }

  async function handleReset() {
    if (resetting) return;
    if (!window.confirm("Reset the demo? Clears walk-in patients and restores the seeded ones.")) return;
    setResetting(true);
    try {
      await resetDemo(DEMO_HOSPITAL);
    } catch {
      /* non-fatal */
    } finally {
      setResetting(false);
      reloadBoth();
    }
  }

  const leftStyle = isWide ? { width: `${leftPct}%` } : undefined;
  const iframeInteractivity = dragging ? ("none" as const) : ("auto" as const);

  return (
    <div className="h-[100dvh] flex flex-col bg-surface-low overflow-hidden">
      {/* Top bar */}
      <header className="h-14 shrink-0 flex items-center justify-between px-4 sm:px-6 bg-surface-lowest border-b border-line">
        <div className="flex items-center gap-2.5 min-w-0">
          <Stethoscope size={20} className="text-primary shrink-0" aria-hidden />
          <span className="text-base font-semibold tracking-editorial">Solace</span>
          <span className="hidden sm:inline text-[11px] uppercase tracking-wider text-text-muted font-semibold border-l border-line pl-2.5 ml-1 truncate">
            Live walkthrough · patient to clinician
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Split presets — only meaningful on wide screens */}
          {isWide && (
            <div className="hidden md:inline-flex items-center rounded-md bg-surface-low ring-1 ring-line p-0.5 mr-1">
              <PresetButton label="Bigger patient screen" icon={PanelLeft} active={leftPct >= 60} onClick={() => setLeftPct(65)} />
              <PresetButton label="Even split" icon={null} active={leftPct > 40 && leftPct < 60} onClick={() => setLeftPct(50)} text="50/50" />
              <PresetButton label="Bigger clinician screen" icon={PanelRight} active={leftPct <= 40} onClick={() => setLeftPct(32)} />
            </div>
          )}
          <span className="hidden lg:inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-success">
            <span className="h-2 w-2 rounded-full bg-success animate-pulse" /> Live
          </span>
          <button
            onClick={reloadBoth}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[12px] font-semibold text-text-muted hover:text-ink hover:bg-surface-low transition-colors"
            title="Reload both panels"
          >
            <RefreshCw size={14} aria-hidden /> Reload
          </button>
          <button
            onClick={handleReset}
            disabled={resetting}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[12px] font-semibold text-text-muted hover:text-error hover:bg-surface-low transition-colors disabled:opacity-50"
            title="Reset demo data"
          >
            <RotateCcw size={14} aria-hidden /> {resetting ? "Resetting…" : "Reset demo"}
          </button>
        </div>
      </header>

      {/* Split panes */}
      <div
        ref={splitRef}
        className={`flex-1 min-h-0 flex flex-col lg:flex-row ${dragging ? "select-none cursor-col-resize" : ""}`}
      >
        {/* Patient — phone-framed on large screens */}
        <section
          style={leftStyle}
          className="flex flex-col min-h-0 flex-1 lg:flex-none border-b lg:border-b-0 border-line"
        >
          <PaneLabel icon={Smartphone} title="Patient" subtitle="Waiting-room intake" />
          <div className="flex-1 min-h-0 bg-surface-low flex justify-center p-0 lg:p-5">
            <div className="w-full lg:max-w-[430px] h-full lg:rounded-2xl lg:shadow-card overflow-hidden bg-surface-lowest lg:border lg:border-line">
              <iframe
                key={`patient-${nonce}`}
                src={`/${DEMO_HOSPITAL}`}
                title="Patient intake"
                className="w-full h-full border-0"
                style={{ pointerEvents: iframeInteractivity }}
                allow="microphone; camera"
              />
            </div>
          </div>
        </section>

        {/* Drag handle — wide screens only */}
        {isWide && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize panels"
            onPointerDown={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDoubleClick={() => setLeftPct(50)}
            className={`relative w-1.5 shrink-0 cursor-col-resize bg-line hover:bg-primary/50 transition-colors ${
              dragging ? "bg-primary" : ""
            }`}
            title="Drag to resize · double-click for 50/50"
          >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-10 w-5 rounded-full bg-surface-lowest ring-1 ring-line shadow-soft flex items-center justify-center">
              <GripVertical size={14} className="text-text-muted" aria-hidden />
            </div>
          </div>
        )}

        {/* Clinician — fills the remaining space */}
        <section className="flex flex-col min-h-0 flex-1">
          <PaneLabel icon={Monitor} title="Clinician" subtitle="Triage dashboard (auto-updates)" />
          <div className="flex-1 min-h-0 bg-surface">
            {ready ? (
              <iframe
                key={`clinician-${nonce}`}
                src={`/${DEMO_HOSPITAL}/clinician`}
                title="Clinician dashboard"
                className="w-full h-full border-0"
                style={{ pointerEvents: iframeInteractivity }}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-sm text-text-muted">
                Preparing the clinician workspace…
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Footer hint */}
      <footer className="shrink-0 hidden sm:block px-6 py-2 bg-surface-lowest border-t border-line text-[12px] text-text-muted text-center">
        Drag the divider to resize either screen. Complete the intake on the left — the patient
        appears on the clinician queue at right within a few seconds.
      </footer>
    </div>
  );
}

function PaneLabel({
  icon: Icon,
  title,
  subtitle,
}: {
  icon: typeof Smartphone;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="shrink-0 flex items-center gap-2 px-4 py-2.5 bg-surface-lowest border-b border-line">
      <Icon size={15} className="text-primary shrink-0" aria-hidden />
      <span className="text-sm font-semibold text-ink">{title}</span>
      <span className="text-[11px] text-text-muted truncate">· {subtitle}</span>
    </div>
  );
}

function PresetButton({
  label,
  icon: Icon,
  active,
  onClick,
  text,
}: {
  label: string;
  icon: typeof PanelLeft | null;
  active: boolean;
  onClick: () => void;
  text?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={`inline-flex items-center justify-center gap-1 h-7 px-2 rounded text-[11px] font-semibold transition-colors ${
        active ? "bg-surface-lowest text-ink shadow-soft" : "text-text-muted hover:text-ink"
      }`}
    >
      {Icon ? <Icon size={14} aria-hidden /> : null}
      {text ? <span>{text}</span> : null}
    </button>
  );
}
