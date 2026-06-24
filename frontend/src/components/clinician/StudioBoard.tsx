import { Component, lazy, Suspense, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Activity,
  BookOpen,
  ChevronDown,
  ClipboardList,
  FileSignature,
  FileText,
  GripVertical,
  Link2,
  ListChecks,
  Loader2,
  Mic,
  Plus,
  ScrollText,
  Search,
  Sparkles,
  Users2,
  X,
} from "lucide-react";
import { PatientWorkspaceProvider } from "../workspace/PatientWorkspaceContext";
import { ESIBadge } from "../patient/ESIBadge";
import type { PatientSummary } from "../../types";

// Solace Atlas — composable clinician workspace.
//
// Instead of click-a-patient → fixed tab page, the clinician TAGS patients in a
// search bar and BUILDS their own board of feature cards (drag to reorder, add
// from a library, remove). Every feature is the SAME self-contained tab
// component used by the old workspace — each reads the active patient from a
// single PatientWorkspaceProvider, so zero feature code is rewritten here.
// Board layout persists per clinician in localStorage.

type LazyTab = React.LazyExoticComponent<() => React.JSX.Element>;

const OverviewTab = lazy(() => import("../workspace/tabs/OverviewTab"));
const ScribeTab = lazy(() => import("../workspace/tabs/ScribeTab"));
const ReasoningTab = lazy(() => import("../workspace/tabs/ReasoningTab"));
const CopilotTab = lazy(() => import("../workspace/tabs/CopilotTab"));
const CodingTab = lazy(() => import("../workspace/tabs/CodingTab"));
const LettersTab = lazy(() => import("../workspace/tabs/LettersTab"));
const PriorAuthTab = lazy(() => import("../workspace/tabs/PriorAuthTab"));
const EhrTab = lazy(() => import("../workspace/tabs/EhrTab"));
const CareGapsTab = lazy(() => import("../workspace/tabs/CareGapsTab"));
const ResultClosureTab = lazy(() => import("../workspace/tabs/ResultClosureTab"));

type Feature = {
  id: string;
  label: string;
  icon: typeof Mic;
  kind: "queue" | "tab";
  Component?: LazyTab;
};

const FEATURES: Feature[] = [
  { id: "queue", label: "Live queue", icon: Users2, kind: "queue" },
  { id: "overview", label: "Patient snapshot", icon: Activity, kind: "tab", Component: OverviewTab },
  { id: "scribe", label: "Ambient scribe", icon: Mic, kind: "tab", Component: ScribeTab },
  { id: "copilot", label: "Copilot", icon: Sparkles, kind: "tab", Component: CopilotTab },
  { id: "reasoning", label: "Reasoning", icon: BookOpen, kind: "tab", Component: ReasoningTab },
  { id: "coding", label: "Coding", icon: ListChecks, kind: "tab", Component: CodingTab },
  { id: "letters", label: "Letters & forms", icon: FileText, kind: "tab", Component: LettersTab },
  { id: "prior-auth", label: "Prior auth", icon: FileSignature, kind: "tab", Component: PriorAuthTab },
  { id: "ehr", label: "EHR history", icon: Link2, kind: "tab", Component: EhrTab },
  { id: "care-gaps", label: "Care gaps", icon: ClipboardList, kind: "tab", Component: CareGapsTab },
  { id: "result-closure", label: "Result closure", icon: ScrollText, kind: "tab", Component: ResultClosureTab },
];
const FEATURE_MAP: Record<string, Feature> = Object.fromEntries(FEATURES.map((f) => [f.id, f]));
const DEFAULT_CARDS = ["queue", "overview", "scribe"];

const storageKey = (clinicianId: string) => `solace-atlas-board-${clinicianId}`;

type Board = { cards: string[]; collapsed: Record<string, boolean> };

const validCards = (arr: unknown[]): string[] =>
  arr.filter((id): id is string => typeof id === "string" && !!FEATURE_MAP[id]);

// Loads the persisted board. v2 format is `{ v, cards, collapsed }`; the legacy v1
// format was a bare `string[]` of card ids — we still read it so a clinician's saved
// layout is never wiped on upgrade. Collapsed keys are always pruned to the validated
// cards + FEATURE_MAP, so stale ids self-heal. A malformed `collapsed` never discards
// cards. Any failure (corrupt/blocked storage) falls back to the default board.
function loadBoard(clinicianId: string): Board {
  try {
    const raw = localStorage.getItem(storageKey(clinicianId));
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const cards = validCards(parsed);
        return { cards: cards.length ? cards : DEFAULT_CARDS, collapsed: {} };
      }
      if (parsed && Array.isArray(parsed.cards)) {
        const cards = validCards(parsed.cards);
        const safeCards = cards.length ? cards : DEFAULT_CARDS;
        const collapsed: Record<string, boolean> = {};
        const src = parsed.collapsed;
        if (src && typeof src === "object") {
          for (const [id, v] of Object.entries(src)) {
            if (FEATURE_MAP[id] && safeCards.includes(id) && typeof v === "boolean") collapsed[id] = v;
          }
        }
        return { cards: safeCards, collapsed };
      }
    }
  } catch {
    /* ignore corrupt layout */
  }
  return { cards: DEFAULT_CARDS, collapsed: {} };
}

function formatWait(mins: number | null | undefined): string {
  if (mins == null) return "";
  if (mins <= 0) return "just now";
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function StudioBoard({
  hospitalId,
  patients,
  loading,
  authenticated,
  clinicianId,
}: {
  hospitalId: string;
  patients: PatientSummary[];
  loading: boolean;
  authenticated: boolean;
  clinicianId: string;
}) {
  const [cards, setCards] = useState<string[]>(() => loadBoard(clinicianId).cards);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => loadBoard(clinicianId).collapsed);
  const [query, setQuery] = useState("");
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);

  // One atomic write carries both card order and collapsed state (v2 object format).
  useEffect(() => {
    try {
      localStorage.setItem(storageKey(clinicianId), JSON.stringify({ v: 2, cards, collapsed }));
    } catch {
      /* storage full / blocked — non-fatal */
    }
  }, [cards, collapsed, clinicianId]);

  const toggleCollapse = (id: string) => setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));
  function removeCard(id: string) {
    setCards((prev) => prev.filter((c) => c !== id));
    setCollapsed((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  const byId = useMemo(
    () => Object.fromEntries(patients.map((p) => [p.patient_id, p])) as Record<string, PatientSummary>,
    [patients],
  );
  const tagged = tagIds.map((id) => byId[id]).filter(Boolean) as PatientSummary[];
  const activePatient = activeId ? byId[activeId] : null;
  const results = query.trim()
    ? patients.filter((p) => p.name?.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 6)
    : [];
  const available = FEATURES.filter((f) => !cards.includes(f.id));

  function tagPatient(p: PatientSummary) {
    setTagIds((prev) => (prev.includes(p.patient_id) ? prev : [...prev, p.patient_id]));
    setActiveId(p.patient_id);
    setQuery("");
  }
  function untag(id: string) {
    setTagIds((prev) => prev.filter((x) => x !== id));
    setActiveId((cur) => (cur === id ? null : cur));
  }
  // Live reorder: as the dragged card ENTERS another card, splice it into that
  // slot immediately so the board reflows under the cursor (the Robinhood-Legend
  // "panels make room" feel). dragId is kept until the drag ends — finalizing only
  // on drop felt insensitive because nothing moved until you released. Fires on
  // dragEnter (once per card) rather than dragOver (continuous) to avoid thrash.
  function reorder(targetId: string) {
    if (!dragId || dragId === targetId) return;
    setCards((prev) => {
      if (prev.indexOf(dragId) === -1) return prev;
      const idx = prev.indexOf(targetId);
      if (idx === -1) return prev;
      const next = prev.filter((c) => c !== dragId);
      next.splice(next.indexOf(targetId), 0, dragId);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Patient search + tag bar */}
      <div className="card-clean rounded-2xl p-3">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search patients to tag…"
            className="w-full h-11 pl-9 pr-3 rounded-xl bg-surface-low text-sm text-ink ring-1 ring-line/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 placeholder:text-text-muted/70"
          />
          {results.length > 0 && (
            <div className="absolute z-20 left-0 right-0 mt-1 rounded-xl bg-surface-lowest ring-1 ring-line shadow-card overflow-hidden">
              {results.map((p) => (
                <button
                  key={p.patient_id}
                  type="button"
                  onClick={() => tagPatient(p)}
                  className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-surface-low transition-colors"
                >
                  <ESIBadge esiLevel={(p.refined_esi_level ?? p.esi_level) as number} size="sm" showLabel={false} />
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold truncate">{p.name}</span>
                    <span className="block text-[12px] text-text-muted">{formatWait(p.waited_minutes)} wait</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        {tagged.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2.5">
            {tagged.map((p) => {
              const active = activeId === p.patient_id;
              return (
                <span
                  key={p.patient_id}
                  className={`inline-flex items-center rounded-full text-[12px] font-semibold ring-1 transition-colors ${
                    active ? "bg-primary text-white ring-primary" : "bg-surface-low text-ink ring-line/60"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => setActiveId(p.patient_id)}
                    className="pl-3 pr-1.5 py-1"
                    title="Set as active patient"
                  >
                    {p.name}
                  </button>
                  <button
                    type="button"
                    onClick={() => untag(p.patient_id)}
                    aria-label={`Remove ${p.name}`}
                    className={`pr-2 pl-0.5 py-1 rounded-r-full ${active ? "hover:text-white/70" : "text-text-muted hover:text-error"}`}
                  >
                    <X size={12} />
                  </button>
                </span>
              );
            })}
          </div>
        )}
      </div>

      {/* Header + add feature */}
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-editorial">My workspace</h2>
          <p className="text-sm text-text-muted truncate">
            {activePatient ? `Active patient · ${activePatient.name}` : "Tag a patient above to populate your cards"}
          </p>
        </div>
        <div className="relative shrink-0">
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            className="inline-flex items-center gap-1.5 h-10 px-4 rounded-full bg-primary text-white text-sm font-semibold hover:brightness-110 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
          >
            <Plus size={16} aria-hidden /> Add feature
          </button>
          {adding && (
            <div className="absolute right-0 z-20 mt-2 w-60 rounded-xl bg-surface-lowest ring-1 ring-line shadow-card overflow-hidden py-1">
              {available.length === 0 ? (
                <div className="px-3 py-2.5 text-sm text-text-muted">All features added.</div>
              ) : (
                available.map((f) => {
                  const Icon = f.icon;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      onClick={() => {
                        setCards((prev) => (prev.includes(f.id) ? prev : [...prev, f.id]));
                        setAdding(false);
                      }}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm font-medium text-ink hover:bg-surface-low transition-colors"
                    >
                      <Icon size={15} className="text-primary" aria-hidden /> {f.label}
                    </button>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>

      {/* Board — one provider feeds every patient-bound card */}
      <PatientWorkspaceProvider hospitalId={hospitalId} patientId={activeId || ""} authenticated={authenticated}>
        <div className="grid grid-cols-1 xl:grid-cols-2 auto-rows-min gap-5 items-start">
          {cards.map((id) => {
            const f = FEATURE_MAP[id];
            if (!f) return null;
            const Comp = f.Component;
            return (
              <FeatureCard
                key={id}
                feature={f}
                collapsed={!!collapsed[id]}
                onToggleCollapse={() => toggleCollapse(id)}
                dragging={dragId === id}
                onDragStart={() => setDragId(id)}
                onDragEnd={() => setDragId(null)}
                onDragEnter={() => reorder(id)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => setDragId(null)}
                onRemove={() => removeCard(id)}
              >
                <CardErrorBoundary key={`${id}-${activeId ?? "none"}`} label={f.label}>
                  {f.kind === "queue" ? (
                    <QueueCardBody patients={patients} loading={loading} activeId={activeId} onSelect={tagPatient} />
                  ) : activeId && Comp ? (
                    <Suspense fallback={<CardSpinner />}>
                      <Comp />
                    </Suspense>
                  ) : (
                    <CardEmpty label={f.label} />
                  )}
                </CardErrorBoundary>
              </FeatureCard>
            );
          })}
        </div>
      </PatientWorkspaceProvider>
    </div>
  );
}

function FeatureCard({
  feature,
  children,
  collapsed,
  onToggleCollapse,
  onRemove,
  onDragStart,
  onDragEnd,
  onDragEnter,
  onDragOver,
  onDrop,
  dragging,
}: {
  feature: Feature;
  children: React.ReactNode;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onRemove: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragEnter: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: () => void;
  dragging: boolean;
}) {
  const Icon = feature.icon;
  const reduce = useReducedMotion();
  return (
    <motion.section
      // layout="position" glides the card to its new slot during live drag-reorder
      // (and as neighbors make room) WITHOUT animating size — collapse height stays
      // owned by the body's AnimatePresence below, so the two never fight. Disabled
      // under reduced-motion.
      layout={reduce ? false : "position"}
      transition={{ layout: { duration: reduce ? 0 : 0.22, ease: [0.4, 0, 0.2, 1] } }}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className={`card-clean rounded-2xl overflow-hidden flex flex-col transition-[opacity,box-shadow] ${
        dragging ? "opacity-40 ring-2 ring-primary/50" : ""
      } ${collapsed ? "xl:col-span-2" : ""}`}
    >
      <header
        draggable
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        className="flex items-center gap-2 px-4 py-2.5 border-b border-line/50 bg-surface-low/40 cursor-grab active:cursor-grabbing select-none"
      >
        <GripVertical size={14} className="text-text-muted shrink-0" aria-hidden />
        <Icon size={15} className="text-primary shrink-0" aria-hidden />
        <span className="text-sm font-semibold truncate">{feature.label}</span>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleCollapse();
            }}
            aria-expanded={!collapsed}
            aria-label={collapsed ? `Expand ${feature.label}` : `Collapse ${feature.label}`}
            className="h-7 w-7 rounded-md flex items-center justify-center text-text-muted hover:text-ink hover:bg-surface-low transition-colors"
          >
            <ChevronDown size={15} className={`transition-transform ${collapsed ? "" : "rotate-180"}`} aria-hidden />
          </button>
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${feature.label}`}
            className="h-7 w-7 rounded-md flex items-center justify-center text-text-muted hover:text-error hover:bg-surface-low transition-colors"
          >
            <X size={15} />
          </button>
        </div>
      </header>
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.22, ease: [0.4, 0, 0.2, 1] }}
            style={{ overflow: "hidden" }}
          >
            <div className="p-4 max-h-[560px] overflow-auto">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}

function QueueCardBody({
  patients,
  loading,
  activeId,
  onSelect,
}: {
  patients: PatientSummary[];
  loading: boolean;
  activeId: string | null;
  onSelect: (p: PatientSummary) => void;
}) {
  if (loading && !patients.length) return <CardSpinner />;
  if (!patients.length)
    return <div className="text-sm text-text-muted py-6 text-center">No patients in the queue.</div>;
  return (
    <ul className="flex flex-col gap-1.5">
      {patients.map((p) => {
        const active = activeId === p.patient_id;
        return (
          <li key={p.patient_id}>
            <button
              type="button"
              onClick={() => onSelect(p)}
              className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-xl transition-colors ${
                active ? "bg-primary-fixed/50 ring-1 ring-primary/30" : "hover:bg-surface-low"
              }`}
            >
              <ESIBadge esiLevel={(p.refined_esi_level ?? p.esi_level) as number} size="sm" showLabel={false} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold truncate">{p.name}</span>
                <span className="block text-[12px] text-text-muted">
                  {formatWait(p.waited_minutes)} wait · {p.language?.toUpperCase()}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function CardEmpty({ label }: { label: string }) {
  return (
    <div className="text-sm text-text-muted py-8 text-center leading-relaxed">
      Tag a patient above to use <span className="font-semibold text-ink">{label}</span>.
    </div>
  );
}

function CardSpinner() {
  return (
    <div className="flex items-center justify-center py-10 text-text-muted text-sm">
      <Loader2 size={18} className="animate-spin mr-2" aria-hidden /> Loading…
    </div>
  );
}

// Isolates each feature so a single card that throws can never white-screen the
// whole board (critical: a Scribe/EHR render error must not crash the demo).
class CardErrorBoundary extends Component<
  { label: string; children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error("Atlas feature card crashed:", error);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="text-sm text-text-muted py-8 text-center leading-relaxed">
          <span className="font-semibold text-ink">{this.props.label}</span> hit a snag and was paused.
          Try another patient, or remove and re-add this card.
        </div>
      );
    }
    return this.props.children;
  }
}
