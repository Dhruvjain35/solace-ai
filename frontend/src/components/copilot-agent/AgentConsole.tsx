import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Check,
  ChevronDown,
  Radio,
  Terminal,
  Trash2,
  X,
} from "lucide-react";
import {
  clearTelemetry,
  subscribe,
  type AgentEventKind,
  type TelemetryEvent,
} from "./agentTelemetry";

/**
 * AgentConsole — a collapsible, in-flow dark console that makes the agent's
 * behind-the-API work visible: every FHIR read, reasoning round and proposed
 * write, with the real latencies the backend reported.
 */

const KIND_STYLE: Record<AgentEventKind, { tag: string; dot: string; text: string }> = {
  fhir: { tag: "FHIR", dot: "bg-emerald-400", text: "text-emerald-300" },
  think: { tag: "THINK", dot: "bg-violet-400", text: "text-violet-300" },
  propose: { tag: "PROPOSE", dot: "bg-amber-400", text: "text-amber-300" },
  info: { tag: "INFO", dot: "bg-slate-400", text: "text-slate-400" },
};

function clock(at: number): string {
  const d = new Date(at);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function Row({ e }: { e: TelemetryEvent }) {
  const k = KIND_STYLE[e.kind];
  const pending = e.status === "pending";
  return (
    <div className="flex items-baseline gap-2 px-3 py-[3px] leading-snug hover:bg-white/5">
      <span className="shrink-0 tabular-nums text-slate-600">{clock(e.at)}</span>
      <span
        className={`mt-px h-1.5 w-1.5 shrink-0 self-center rounded-full ${k.dot} ${
          pending ? "animate-pulse" : ""
        }`}
        aria-hidden
      />
      <span className={`w-[56px] shrink-0 font-semibold ${k.text}`}>{k.tag}</span>
      <span className="min-w-0 flex-1 truncate text-slate-200">
        {e.label}
        {e.detail && <span className="text-slate-500"> · {e.detail}</span>}
      </span>
      <span className="flex shrink-0 items-center gap-1 tabular-nums text-slate-500">
        {e.status === "ok" && (
          <Check className="h-3 w-3 text-emerald-500" aria-label="ok" />
        )}
        {e.status === "error" && (
          <X className="h-3 w-3 text-rose-400" aria-label="error" />
        )}
        {pending ? (
          <span className="animate-pulse">···</span>
        ) : e.ms != null ? (
          <span className={e.status === "error" ? "text-rose-400" : ""}>{e.ms}ms</span>
        ) : null}
      </span>
    </div>
  );
}

export default function AgentConsole() {
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [open, setOpen] = useState(true);
  const feedRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => subscribe(setEvents), []);

  // Stick to the newest row unless the user has scrolled up to read history.
  useEffect(() => {
    const el = feedRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [events, open]);

  function onScroll() {
    const el = feedRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  const reads = events.filter((e) => e.kind === "fhir").length;
  const rounds = events.filter((e) => e.kind === "think").length;
  const proposals = events.filter((e) => e.kind === "propose").length;
  const live = events.some((e) => e.status === "pending");

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-[#10181a] font-mono text-[11px] shadow-card">
      {/* Title bar */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 border-b border-white/10 bg-[#0c1315] px-3 py-2 text-left"
        aria-expanded={open}
      >
        <Terminal className="h-3.5 w-3.5 text-emerald-400" aria-hidden />
        <span className="font-semibold tracking-wide text-slate-200">
          AGENT CONSOLE
        </span>
        <span className="flex items-center gap-1 text-[10px] text-emerald-400">
          <Radio
            className={`h-3 w-3 ${live ? "animate-pulse text-emerald-400" : "text-slate-600"}`}
            aria-hidden
          />
          {live ? "live" : "idle"}
        </span>
        <span className="ml-auto flex items-center gap-3 text-[10px] text-slate-500">
          <span className="flex items-center gap-1">
            <Activity className="h-3 w-3" aria-hidden /> {events.length}
          </span>
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform ${open ? "" : "-rotate-90"}`}
            aria-hidden
          />
        </span>
      </button>

      {open && (
        <>
          <div
            ref={feedRef}
            onScroll={onScroll}
            className="h-[200px] overflow-y-auto py-1"
          >
            {events.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-1 px-6 text-center text-slate-600">
                <Activity className="h-4 w-4" aria-hidden />
                <p>Waiting for activity</p>
                <p className="text-slate-700">
                  Ask the agent something — every FHIR read, reasoning round
                  and proposed write appears here.
                </p>
              </div>
            ) : (
              events.map((e) => <Row key={e.id} e={e} />)
            )}
          </div>

          {/* Footer summary */}
          <div className="flex items-center gap-3 border-t border-white/10 bg-[#0c1315] px-3 py-1.5 text-[10px] text-slate-500">
            <span>
              <span className="text-emerald-300">{reads}</span> reads
            </span>
            <span>
              <span className="text-violet-300">{rounds}</span> rounds
            </span>
            <span>
              <span className="text-amber-300">{proposals}</span> proposals
            </span>
            <button
              type="button"
              onClick={() => clearTelemetry()}
              className="ml-auto flex items-center gap-1 text-slate-500 transition-colors hover:text-rose-400"
            >
              <Trash2 className="h-3 w-3" aria-hidden /> clear
            </button>
          </div>
        </>
      )}
    </div>
  );
}
