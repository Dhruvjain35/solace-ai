import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Link2, Link2Off, Loader2, TriangleAlert } from "lucide-react";
import { loadSession, type Session } from "../lib/session";
import { ESI_COLORS } from "../lib/constants";
import {
  PatientWorkspaceProvider,
  usePatientWorkspace,
} from "../components/workspace/PatientWorkspaceContext";

const OverviewTab = lazy(() => import("../components/workspace/tabs/OverviewTab"));
const ScribeTab = lazy(() => import("../components/workspace/tabs/ScribeTab"));
const ReasoningTab = lazy(() => import("../components/workspace/tabs/ReasoningTab"));
const CopilotTab = lazy(() => import("../components/workspace/tabs/CopilotTab"));
const CodingTab = lazy(() => import("../components/workspace/tabs/CodingTab"));
const LettersTab = lazy(() => import("../components/workspace/tabs/LettersTab"));
const PriorAuthTab = lazy(() => import("../components/workspace/tabs/PriorAuthTab"));
const EhrTab = lazy(() => import("../components/workspace/tabs/EhrTab"));
const CareGapsTab = lazy(() => import("../components/workspace/tabs/CareGapsTab"));
const ResultClosureTab = lazy(() => import("../components/workspace/tabs/ResultClosureTab"));

type TabDef = {
  id: string;
  label: string;
  Component: React.LazyExoticComponent<() => React.JSX.Element>;
};

const TABS: TabDef[] = [
  { id: "overview", label: "Overview", Component: OverviewTab },
  { id: "copilot", label: "Copilot", Component: CopilotTab },
  { id: "scribe", label: "Scribe", Component: ScribeTab },
  { id: "reasoning", label: "Reasoning", Component: ReasoningTab },
  { id: "coding", label: "Coding", Component: CodingTab },
  { id: "letters", label: "Letters", Component: LettersTab },
  { id: "prior-auth", label: "Prior Auth", Component: PriorAuthTab },
  { id: "ehr", label: "EHR", Component: EhrTab },
  { id: "care-gaps", label: "Care Gaps", Component: CareGapsTab },
  { id: "result-closure", label: "Result Closure", Component: ResultClosureTab },
];

/** Small ESI pill used in the sticky header. */
function EsiPill({ label, level }: { label: string; level: number | null | undefined }) {
  if (level == null) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-surface-low text-text-muted">
        {label}: pending
      </span>
    );
  }
  const cfg = ESI_COLORS[level] || { bg: "#4A5557", onDark: true };
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: cfg.bg, color: cfg.onDark ? "#fff" : "#1A1A1A" }}
    >
      {label}: ESI {level}
    </span>
  );
}

/** Sticky patient-identity header — reads the workspace context. */
function WorkspaceHeader({
  hospitalId,
  activeTab,
  onSelectTab,
  tablistId,
}: {
  hospitalId: string;
  activeTab: string;
  onSelectTab: (id: string) => void;
  tablistId: string;
}) {
  const { patient, loading, error, ehrLinked } = usePatientWorkspace();
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const info = patient?.medical_info;
  const ageSex = [
    info?.age != null ? `${info.age}yo` : null,
    info?.sex || null,
  ]
    .filter(Boolean)
    .join(" ");
  const mrn = patient?.patient_id || "—";

  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    let next = index;
    if (e.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = TABS.length - 1;
    else return;
    e.preventDefault();
    const id = TABS[next].id;
    onSelectTab(id);
    tabRefs.current[id]?.focus();
  };

  return (
    <header
      className="border-b border-line bg-surface-lowest sticky top-0 z-30"
      style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
    >
      <div className="max-w-6xl mx-auto px-6 pt-3">
        <div className="flex items-start gap-3">
          <Link
            to={`/${hospitalId}/clinician`}
            className="inline-flex items-center gap-1.5 mt-0.5 rounded text-text-muted hover:text-ink text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
          >
            <ArrowLeft size={16} aria-hidden="true" /> Dashboard
          </Link>

          <div className="flex-1 min-w-0">
            <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
              Patient workspace
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-lg font-bold tracking-tight truncate">
                {patient?.name || (loading ? "Loading…" : error ? "Patient" : "—")}
              </h1>
              {ageSex && <span className="text-sm text-text-muted">{ageSex}</span>}
            </div>

            <div className="flex items-center gap-2 flex-wrap mt-1.5">
              {patient && (
                <>
                  <EsiPill label="Provisional" level={patient.esi_level} />
                  <EsiPill label="Refined" level={patient.refined_esi_level} />
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-mono bg-surface-low text-text-muted">
                    MRN {mrn}
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      ehrLinked
                        ? "bg-primary-fixed/50 text-primary"
                        : "bg-surface-low text-text-muted"
                    }`}
                  >
                    {ehrLinked ? (
                      <Link2 size={11} aria-hidden="true" />
                    ) : (
                      <Link2Off size={11} aria-hidden="true" />
                    )}
                    {ehrLinked ? "EHR linked" : "EHR not linked"}
                  </span>
                  {patient.pain_flagged && (
                    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-error/10 text-error">
                      <TriangleAlert size={11} aria-hidden="true" />
                      Pain flagged
                    </span>
                  )}
                </>
              )}
            </div>
          </div>
        </div>

        {/* Tab bar */}
        <div
          role="tablist"
          id={tablistId}
          aria-label="Patient workspace tabs"
          className="flex items-center gap-1 mt-3 -mb-px overflow-x-auto"
        >
          {TABS.map((t, i) => {
            const selected = t.id === activeTab;
            return (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[t.id] = el;
                }}
                role="tab"
                id={`${tablistId}-tab-${t.id}`}
                aria-selected={selected}
                aria-controls={`${tablistId}-panel-${t.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => onSelectTab(t.id)}
                onKeyDown={(e) => onTabKeyDown(e, i)}
                className={`whitespace-nowrap rounded-t-md px-3 py-2 text-sm font-semibold border-b-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1 ${
                  selected
                    ? "border-primary text-primary"
                    : "border-transparent text-text-muted hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>
    </header>
  );
}

function WorkspaceBody({ hospitalId, tablistId }: { hospitalId: string; tablistId: string }) {
  const [activeTab, setActiveTab] = useState<string>(TABS[0].id);

  return (
    <div className="min-h-screen bg-surface-low">
      <WorkspaceHeader
        hospitalId={hospitalId}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        tablistId={tablistId}
      />
      <main className="max-w-6xl mx-auto px-6 py-6">
        {TABS.map((t) => {
          const selected = t.id === activeTab;
          const { Component } = t;
          return (
            <div
              key={t.id}
              role="tabpanel"
              id={`${tablistId}-panel-${t.id}`}
              aria-labelledby={`${tablistId}-tab-${t.id}`}
              hidden={!selected}
            >
              {selected && (
                <Suspense
                  fallback={
                    <div className="flex items-center justify-center py-16 text-text-muted text-sm">
                      <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
                      Loading…
                    </div>
                  }
                >
                  <Component />
                </Suspense>
              )}
            </div>
          );
        })}
      </main>
    </div>
  );
}

export default function PatientDetailPage() {
  const { hospitalId = "demo", patientId = "" } = useParams<{
    hospitalId?: string;
    patientId?: string;
  }>();
  const [session, setSession] = useState<Session | null>(null);
  const tablistId = useId();

  useEffect(() => {
    setSession(loadSession());
  }, []);

  if (!session?.token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-low">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <h1 className="text-xl font-bold mb-2">Sign in required</h1>
          <p className="text-text-muted text-sm mb-4">
            Open the clinician dashboard to sign in first.
          </p>
          <Link
            to={`/${hospitalId}/clinician`}
            className="inline-flex items-center gap-1.5 h-11 px-4 rounded-md bg-primary text-white text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
          >
            Go to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <PatientWorkspaceProvider
      hospitalId={hospitalId}
      patientId={patientId}
      authenticated={!!session?.token}
    >
      <WorkspaceBody hospitalId={hospitalId} tablistId={tablistId} />
    </PatientWorkspaceProvider>
  );
}
