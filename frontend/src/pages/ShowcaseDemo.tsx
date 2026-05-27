import { useEffect, useRef, useState } from "react";
import { Monitor, RefreshCw, RotateCcw, Smartphone, Stethoscope } from "lucide-react";
import { loginClinician, resetDemo } from "../lib/api";
import { saveSession } from "../lib/session";

// Standalone split-screen showcase: patient intake (left) and the live clinician
// dashboard (right), side by side on one screen. Each pane is the REAL demo
// route loaded in a same-origin iframe, so the patient checks in on the left
// and shows up on the right via the dashboard's normal polling — nothing mocked.
//
// The clinician pane is signed in automatically: this shell logs in as a demo
// clinician and writes the session to localStorage (shared across same-origin
// iframes), so the dashboard iframe loads authenticated with no click. If that
// login can't run (e.g. local dev without seeded demo clinicians) the pane
// simply shows its normal sign-in screen.
const DEMO_HOSPITAL = "demo";
const DEMO_CLINICIAN = { name: "Dr. Chen", pin: "224466" };

export default function ShowcaseDemo() {
  const [ready, setReady] = useState(false);
  const [nonce, setNonce] = useState(0); // bump to remount both iframes
  const [resetting, setResetting] = useState(false);
  const patientRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    let cancelled = false;
    // Best-effort auto-sign-in so the clinician pane is live immediately.
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
          <span className="hidden md:inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-success">
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
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2">
        {/* Patient — phone-framed on large screens */}
        <section className="flex flex-col min-h-0 border-b lg:border-b-0 lg:border-r border-line">
          <PaneLabel icon={Smartphone} title="Patient" subtitle="Waiting-room intake" />
          <div className="flex-1 min-h-0 bg-surface-low flex justify-center p-0 lg:p-5">
            <div className="w-full lg:max-w-[430px] h-full lg:rounded-2xl lg:shadow-card overflow-hidden bg-surface-lowest lg:border lg:border-line">
              <iframe
                key={`patient-${nonce}`}
                ref={patientRef}
                src={`/${DEMO_HOSPITAL}`}
                title="Patient intake"
                className="w-full h-full border-0"
                allow="microphone; camera"
              />
            </div>
          </div>
        </section>

        {/* Clinician — fills its pane */}
        <section className="flex flex-col min-h-0">
          <PaneLabel icon={Monitor} title="Clinician" subtitle="Triage dashboard (auto-updates)" />
          <div className="flex-1 min-h-0 bg-surface">
            {ready ? (
              <iframe
                key={`clinician-${nonce}`}
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
        </section>
      </div>

      {/* Footer hint */}
      <footer className="shrink-0 hidden sm:block px-6 py-2 bg-surface-lowest border-t border-line text-[12px] text-text-muted text-center">
        Complete the intake on the left — the patient appears on the clinician queue at right within a
        few seconds. Enter vitals on a patient to see the ML-refined ESI and SHAP explanation.
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
