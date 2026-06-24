import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Battery,
  Download,
  Eye,
  EyeOff,
  Monitor,
  RefreshCw,
  RotateCcw,
  Signal,
  Smartphone,
  Wifi,
} from "lucide-react";
import { loginClinician, resetDemo } from "../lib/api";
import { saveSession } from "../lib/session";

// /mockups — Presentation mockup studio. Wraps the REAL, live app (the same
// same-origin iframes /showcase uses) inside an iPhone frame (patient intake)
// and a desktop-browser frame (clinician dashboard), overlays curated,
// toggleable annotation arrows, and sits everything on an exportable stage so
// you can screenshot it, drop it into Canva, and background-remove the stage.
//
// Nothing here is mock UI — the screens are the production routes, auto-signed-in
// for the clinician pane exactly like ShowcaseDemo. Only the framing, the
// annotations, and the stage are presentation chrome.
const DEMO_HOSPITAL = "demo";
const DEMO_CLINICIAN = { name: "Dr. Chen", pin: "224466" };

type DeviceKey = "phone" | "desktop";
type View = "both" | "phone" | "desktop";
type StageBg = "transparent" | "white" | "chroma" | "dark";

// An annotation = a label pill (lx,ly) and the point it points at (tx,ty),
// both as a percentage of its device CELL (the padded box around the frame,
// so labels can live in the margin and the arrow points inward). Draggable to
// nudge — the curated defaults assume the live layout but you can fine-tune.
type Anno = {
  id: string;
  device: DeviceKey;
  label: string;
  lx: number;
  ly: number;
  tx: number;
  ty: number;
  on: boolean;
};

// Coordinates are % of the device CELL. Labels live in the side margins; the
// arrow points inward to a spot on the screen. Drag to fine-tune onto the
// exact live element.
const DEFAULT_ANNOS: Anno[] = [
  // Patient iPhone — the three-beat patient story.
  { id: "p1", device: "phone", label: "Adaptive intake form — asks only what's relevant", lx: 0.5, ly: 22, tx: 36, ty: 25, on: true },
  { id: "p2", device: "phone", label: "Scan ID + insurance → EHR auto-populates these fields", lx: 73, ly: 42, tx: 64, ty: 44, on: true },
  { id: "p3", device: "phone", label: "Feeds the ESI triage engine in seconds", lx: 0.5, ly: 80, tx: 42, ty: 82, on: true },
  // Clinician desktop.
  { id: "d1", device: "desktop", label: "Live triage queue, ESI-sorted", lx: 0.5, ly: 30, tx: 22, ty: 38, on: true },
  { id: "d2", device: "desktop", label: "ESI acuity badge (1–5)", lx: 0.5, ly: 58, tx: 22, ty: 50, on: true },
  { id: "d3", device: "desktop", label: "AI pre-brief & scribe note", lx: 80, ly: 26, tx: 64, ty: 40, on: true },
  { id: "d4", device: "desktop", label: "SHAP-backed vitals refinement", lx: 80, ly: 52, tx: 66, ty: 54, on: true },
  { id: "d5", device: "desktop", label: "One-click disposition & Rx", lx: 80, ly: 78, tx: 70, ty: 70, on: true },
];

const STAGE_STYLES: Record<StageBg, { bg: string; label: string; ink: string }> = {
  transparent: { bg: "checker", label: "Transparent", ink: "#1A2023" },
  white: { bg: "#FFFFFF", label: "White", ink: "#1A2023" },
  chroma: { bg: "#00B140", label: "Chroma green", ink: "#063" },
  dark: { bg: "#0E1416", label: "Dark", ink: "#E7E8E8" },
};

export default function MockupStudio() {
  const [ready, setReady] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [resetting, setResetting] = useState(false);

  const [view, setView] = useState<View>("both");
  const [stage, setStage] = useState<StageBg>("transparent");
  const [zoom, setZoom] = useState(0.62);
  const [showArrows, setShowArrows] = useState(true);
  const [annos, setAnnos] = useState<Anno[]>(DEFAULT_ANNOS);

  // Auto sign-in so the clinician iframe is live with no click (same as /showcase).
  useEffect(() => {
    let cancelled = false;
    loginClinician(DEMO_HOSPITAL, DEMO_CLINICIAN.name, DEMO_CLINICIAN.pin)
      .then((resp) => {
        if (!cancelled) saveSession(resp);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
      setNonce((n) => n + 1);
    }
  }

  const toggleAnno = (id: string) =>
    setAnnos((prev) => prev.map((a) => (a.id === id ? { ...a, on: !a.on } : a)));
  const moveAnno = (id: string, lx: number, ly: number) =>
    setAnnos((prev) => prev.map((a) => (a.id === id ? { ...a, lx, ly } : a)));

  const showPhone = view !== "desktop";
  const showDesktop = view !== "phone";

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface-low">
      {/* Control bar — excluded from the screenshot region below */}
      <header className="sticky top-0 z-30 shrink-0 flex flex-wrap items-center gap-x-4 gap-y-2 px-4 sm:px-6 py-2.5 bg-surface-lowest border-b border-line">
        <div className="flex items-center gap-2 mr-1">
          <span className="text-base font-semibold tracking-editorial">Solace</span>
          <span className="text-[11px] uppercase tracking-wider text-text-muted font-semibold border-l border-line pl-2.5">
            Mockup studio
          </span>
        </div>

        <Segmented<View>
          value={view}
          onChange={setView}
          options={[
            { value: "both", label: "Both" },
            { value: "phone", label: "Patient", icon: Smartphone },
            { value: "desktop", label: "Clinician", icon: Monitor },
          ]}
        />

        <Segmented<StageBg>
          value={stage}
          onChange={setStage}
          options={(Object.keys(STAGE_STYLES) as StageBg[]).map((k) => ({
            value: k,
            label: STAGE_STYLES[k].label,
          }))}
        />

        <label className="flex items-center gap-2 text-[12px] font-semibold text-text-muted">
          Zoom
          <input
            type="range"
            min={0.3}
            max={1}
            step={0.02}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            className="w-24 accent-primary"
          />
        </label>

        <button
          onClick={() => setShowArrows((v) => !v)}
          className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[12px] font-semibold text-text-muted hover:text-ink hover:bg-surface-low transition-colors"
        >
          {showArrows ? <Eye size={14} /> : <EyeOff size={14} />}
          {showArrows ? "Arrows on" : "Arrows off"}
        </button>

        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={() => setNonce((n) => n + 1)}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[12px] font-semibold text-text-muted hover:text-ink hover:bg-surface-low transition-colors"
            title="Reload the live screens"
          >
            <RefreshCw size={14} /> Reload
          </button>
          <button
            onClick={handleReset}
            disabled={resetting}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[12px] font-semibold text-text-muted hover:text-error hover:bg-surface-low transition-colors disabled:opacity-50"
            title="Reset demo data"
          >
            <RotateCcw size={14} /> {resetting ? "Resetting…" : "Reset demo"}
          </button>
        </div>
      </header>

      {/* Arrow toggles — curated list */}
      {showArrows && (
        <div className="shrink-0 flex flex-wrap items-center gap-1.5 px-4 sm:px-6 py-2 bg-surface-lowest/70 border-b border-line">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-text-muted mr-1">
            Annotations
          </span>
          {annos
            .filter((a) => (a.device === "phone" ? showPhone : showDesktop))
            .map((a) => (
              <button
                key={a.id}
                onClick={() => toggleAnno(a.id)}
                className={`inline-flex items-center gap-1 h-6 px-2 rounded-full text-[11px] font-semibold ring-1 transition-colors ${
                  a.on
                    ? "bg-primary text-white ring-primary"
                    : "bg-surface-low text-text-muted ring-line hover:text-ink"
                }`}
              >
                {a.device === "phone" ? <Smartphone size={11} /> : <Monitor size={11} />}
                {a.label}
              </button>
            ))}
        </div>
      )}

      {/* ============ THE STAGE — screenshot this region ============ */}
      <main
        className="flex-1 min-h-0 overflow-auto"
        style={stageBgStyle(stage)}
      >
        <div
          className="flex flex-wrap items-start justify-center gap-2 origin-top mx-auto py-10"
          style={{ transform: `scale(${zoom})`, width: `${100 / zoom}%` }}
        >
          {showPhone && (
            <PhoneFrame nonce={nonce} stage={stage}>
              <AnnotationLayer
                device="phone"
                annos={annos}
                show={showArrows}
                onMove={moveAnno}
                inkOverride={stage === "dark" ? "#E7E8E8" : undefined}
              />
            </PhoneFrame>
          )}
          {showDesktop && (
            <DesktopFrame nonce={nonce} ready={ready} stage={stage}>
              <AnnotationLayer
                device="desktop"
                annos={annos}
                show={showArrows}
                onMove={moveAnno}
                inkOverride={stage === "dark" ? "#E7E8E8" : undefined}
              />
            </DesktopFrame>
          )}
        </div>
      </main>

      {/* Export tips */}
      <footer className="shrink-0 flex items-center gap-2 px-4 sm:px-6 py-2 bg-surface-lowest border-t border-line text-[12px] text-text-muted">
        <Download size={14} className="text-primary shrink-0" />
        <span>
          Set the stage to <b className="text-ink">Chroma green</b> or{" "}
          <b className="text-ink">Transparent</b>, screenshot the stage area
          (macOS: <kbd className="font-mono">⌘⇧4</kbd>), then drop it into Canva and use
          Background Remover. Drag any arrow label to nudge it onto the exact element.
        </span>
      </footer>
    </div>
  );
}

/* ----------------------------- device frames ----------------------------- */

function PhoneFrame({
  nonce,
  stage,
  children,
}: {
  nonce: number;
  stage: StageBg;
  children: React.ReactNode;
}) {
  const dark = stage === "dark";
  return (
    // Cell gives the annotation layer room around the device — wide side
    // margins so callout labels sit beside the phone, not over it.
    <div className="relative" style={{ width: 393 + 460, height: 852 + 120, padding: "60px 230px" }}>
      <div className="relative w-[393px] h-[852px] mx-auto">
        {/* Titanium bezel */}
        <div className="absolute inset-0 rounded-[58px] bg-[#1c1c1e] shadow-[0_30px_80px_rgba(20,30,33,0.35)] p-[14px]">
          <div className="relative w-full h-full rounded-[46px] overflow-hidden bg-white">
            {/* Status bar overlay */}
            <div className="absolute top-0 inset-x-0 z-20 h-12 flex items-end justify-between px-7 pb-1.5 pointer-events-none">
              <span className="text-[13px] font-semibold text-ink">9:41</span>
              <span className="flex items-center gap-1 text-ink">
                <Signal size={14} />
                <Wifi size={14} />
                <Battery size={16} />
              </span>
            </div>
            {/* Dynamic island */}
            <div className="absolute top-2.5 left-1/2 -translate-x-1/2 z-30 w-[120px] h-[34px] rounded-full bg-black" />
            <iframe
              key={`phone-${nonce}`}
              src={`/${DEMO_HOSPITAL}`}
              title="Patient intake"
              className="w-full h-full border-0"
              allow="microphone; camera"
            />
          </div>
        </div>
        {/* Side buttons */}
        <div className="absolute -left-[3px] top-[150px] w-[3px] h-9 rounded-l bg-[#0e0e10]" />
        <div className="absolute -left-[3px] top-[210px] w-[3px] h-14 rounded-l bg-[#0e0e10]" />
        <div className="absolute -right-[3px] top-[190px] w-[3px] h-20 rounded-r bg-[#0e0e10]" />
      </div>
      <DeviceCaption dark={dark}>Patient · waiting-room intake</DeviceCaption>
      {children}
    </div>
  );
}

function DesktopFrame({
  nonce,
  ready,
  stage,
  children,
}: {
  nonce: number;
  ready: boolean;
  stage: StageBg;
  children: React.ReactNode;
}) {
  const dark = stage === "dark";
  return (
    <div className="relative" style={{ width: 1180 + 460, height: 760 + 140, padding: "70px 230px" }}>
      <div className="relative w-[1180px] h-[760px] mx-auto rounded-[14px] overflow-hidden bg-surface-lowest ring-1 ring-line shadow-[0_30px_80px_rgba(20,30,33,0.28)]">
        {/* Browser chrome */}
        <div className="h-11 flex items-center gap-3 px-4 bg-[#e9eaea] border-b border-line">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-[#ff5f57]" />
            <span className="w-3 h-3 rounded-full bg-[#febc2e]" />
            <span className="w-3 h-3 rounded-full bg-[#28c840]" />
          </div>
          <div className="flex-1 max-w-[520px] mx-auto h-7 rounded-md bg-white ring-1 ring-line flex items-center px-3 text-[12px] text-text-muted font-medium">
            stdavids.solace.health/clinician
          </div>
          <div className="w-14" />
        </div>
        <div className="w-full h-[calc(760px-2.75rem)] bg-surface">
          {ready ? (
            <iframe
              key={`desktop-${nonce}`}
              src={`/${DEMO_HOSPITAL}/clinician`}
              title="Clinician dashboard"
              className="w-full h-full border-0"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-sm text-text-muted">
              Preparing the clinician workspace…
            </div>
          )}
        </div>
      </div>
      <DeviceCaption dark={dark}>Clinician · triage dashboard</DeviceCaption>
      {children}
    </div>
  );
}

function DeviceCaption({ dark, children }: { dark: boolean; children: React.ReactNode }) {
  return (
    <div
      className="absolute left-1/2 -translate-x-1/2 bottom-3 text-[12px] font-semibold uppercase tracking-wider"
      style={{ color: dark ? "#9aa3a5" : "#4A5557" }}
    >
      {children}
    </div>
  );
}

/* --------------------------- annotation overlay --------------------------- */

function AnnotationLayer({
  device,
  annos,
  show,
  onMove,
  inkOverride,
}: {
  device: DeviceKey;
  annos: Anno[];
  show: boolean;
  onMove: (id: string, lx: number, ly: number) => void;
  inkOverride?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<string | null>(null);
  const mine = useMemo(() => annos.filter((a) => a.device === device && a.on), [annos, device]);

  const onPointerMove = useCallback(
    (id: string, clientX: number, clientY: number) => {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const lx = ((clientX - r.left) / r.width) * 100;
      const ly = ((clientY - r.top) / r.height) * 100;
      onMove(id, clamp(lx, 0, 96), clamp(ly, 0, 98));
    },
    [onMove],
  );

  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => onPointerMove(drag, e.clientX, e.clientY);
    const up = () => setDrag(null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [drag, onPointerMove]);

  const ink = inkOverride ?? "#2A474E";
  const labelText = inkOverride ? "#0E1416" : "#FFFFFF"; // contrast against the filled pill

  return (
    <div ref={ref} className="absolute inset-0 pointer-events-none" style={{ opacity: show ? 1 : 0 }}>
      {/* Arrows */}
      <svg className="absolute inset-0 w-full h-full overflow-visible" style={{ pointerEvents: "none" }}>
        <defs>
          <marker id={`ah-${device}`} markerWidth="10" markerHeight="10" refX="7" refY="5" orient="auto">
            <path d="M0,0 L10,5 L0,10 L3.5,5 Z" fill={ink} />
          </marker>
        </defs>
        {mine.map((a) => (
          <g key={a.id}>
            {/* target dot */}
            <circle cx={`${a.tx}%`} cy={`${a.ty}%`} r={4} fill={ink} />
            <line
              x1={`${a.lx}%`}
              y1={`${a.ly}%`}
              x2={`${a.tx}%`}
              y2={`${a.ty}%`}
              stroke={ink}
              strokeWidth={2.5}
              strokeLinecap="round"
              markerEnd={`url(#ah-${device})`}
            />
          </g>
        ))}
      </svg>
      {/* Label pills — filled callouts in the margin */}
      {mine.map((a) => (
        <div
          key={a.id}
          onPointerDown={(e) => {
            e.preventDefault();
            setDrag(a.id);
          }}
          className="absolute -translate-y-1/2 select-none cursor-grab active:cursor-grabbing pointer-events-auto rounded-xl px-3 py-2 text-[13px] font-semibold leading-snug shadow-[0_6px_18px_rgba(20,30,33,0.22)]"
          style={{
            left: `${a.lx}%`,
            top: `${a.ly}%`,
            background: ink,
            color: labelText,
            maxWidth: 200,
          }}
        >
          {a.label}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------- utilities ------------------------------- */

function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; icon?: typeof Smartphone }[];
}) {
  return (
    <div className="inline-flex items-center rounded-md bg-surface-low ring-1 ring-line p-0.5">
      {options.map((o) => {
        const Icon = o.icon;
        const active = o.value === value;
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={`inline-flex items-center gap-1 h-7 px-2.5 rounded text-[11px] font-semibold transition-colors ${
              active ? "bg-surface-lowest text-ink shadow-soft" : "text-text-muted hover:text-ink"
            }`}
          >
            {Icon ? <Icon size={13} /> : null}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function stageBgStyle(stage: StageBg): React.CSSProperties {
  if (stage === "transparent") {
    // Checkerboard = visual "transparent" indicator; Canva removes the flat
    // tone after you flatten, or just use Chroma for a clean key.
    return {
      backgroundColor: "#fff",
      backgroundImage:
        "linear-gradient(45deg, #e2e5e6 25%, transparent 25%), linear-gradient(-45deg, #e2e5e6 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #e2e5e6 75%), linear-gradient(-45deg, transparent 75%, #e2e5e6 75%)",
      backgroundSize: "24px 24px",
      backgroundPosition: "0 0, 0 12px, 12px -12px, -12px 0",
    };
  }
  return { backgroundColor: STAGE_STYLES[stage].bg };
}

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}
