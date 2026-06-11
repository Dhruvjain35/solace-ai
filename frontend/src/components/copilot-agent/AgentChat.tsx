import { useEffect, useRef, useState } from "react";
import {
  CalendarPlus,
  Check,
  ClipboardList,
  FilePen,
  FileText,
  Info,
  Pill,
  Search,
  Send,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "../../lib/api";
import { usePatientWorkspace } from "../workspace/PatientWorkspaceContext";
import {
  emit,
  replayEvents,
  update,
  type AgentAction,
  type AgentBackendEvent,
  type AgentEventKind,
  type AgentExecuteResult,
  type AgentReply,
} from "./agentTelemetry";

/**
 * AgentChat — conversational agent over the chart. The agent reads via FHIR,
 * reasons, and PROPOSES writes; nothing touches the chart until the clinician
 * confirms each action (or confirms all).
 */

const HISTORY_CAP = 12;
const STAGGER_MS = 100;

const QUICK_CHIPS = [
  { icon: FileText, label: "Summarize this patient", prompt: "Summarize this patient." },
  { icon: ShieldAlert, label: "Any care gaps?", prompt: "Any care gaps?" },
  { icon: ClipboardList, label: "Draft a progress note", prompt: "Draft a progress note." },
  { icon: Pill, label: "Check med interactions", prompt: "Check med interactions." },
  { icon: CalendarPlus, label: "Propose a follow-up order", prompt: "Propose a follow-up order." },
];

const TRACE_ICON: Record<AgentEventKind, typeof Search> = {
  fhir: Search,
  think: Sparkles,
  propose: FilePen,
  info: Info,
};

type ActionState = "pending" | "dismissed" | "writing" | "written" | "error";

interface TurnAction extends AgentAction {
  state: ActionState;
  errorText?: string;
}

interface Turn {
  role: "user" | "assistant";
  text: string;
  actions?: TurnAction[];
  trace?: AgentBackendEvent[];
  writtenSummary?: string;
}

/** Minimal **bold** rendering so model markdown reads cleanly without a lib. */
function RichText({ text }: { text: string }) {
  return (
    <div className="whitespace-pre-wrap text-sm leading-relaxed">
      {text.split(/(\*\*[^*]+\*\*)/g).map((seg, i) =>
        seg.startsWith("**") && seg.endsWith("**") ? (
          <strong key={i}>{seg.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{seg}</span>
        ),
      )}
    </div>
  );
}

/** Compress a turn's backend trace into a few readable chips. */
function traceChips(trace: AgentBackendEvent[]): { kind: AgentEventKind; label: string }[] {
  const seen = new Set<string>();
  const out: { kind: AgentEventKind; label: string }[] = [];
  for (const e of trace) {
    const key = `${e.kind}:${e.label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ kind: e.kind, label: e.label });
    if (out.length >= 6) break;
  }
  return out;
}

function stripAction(a: TurnAction): AgentAction {
  return { id: a.id, resource_type: a.resource_type, summary: a.summary, resource: a.resource };
}

export default function AgentChat() {
  const { hospitalId, patientId, patient, reloadPatient } = usePatientWorkspace();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [backendMissing, setBackendMissing] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [turns, busy]);

  async function ask(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    const history = turns
      .slice(-HISTORY_CAP)
      .map((t) => ({ role: t.role, content: t.text }));
    setTurns((t) => [...t, { role: "user", text: message }]);
    setInput("");
    setBusy(true);
    setBackendMissing(false);

    // Local pending row so the console shows life before the backend trace lands.
    const started = Date.now();
    const pending = emit({
      kind: "think",
      label: "Agent working",
      detail: message.slice(0, 60),
      status: "pending",
    });

    try {
      const r = await api.post<AgentReply>(
        `/api/${hospitalId}/patients/${patientId}/copilot/agent`,
        { message, history },
      );
      const d = r.data;
      update(pending.id, { ms: Date.now() - started, status: "ok" });

      const events = Array.isArray(d.events) ? d.events : [];
      const totalMs = replayEvents(events, STAGGER_MS);
      const u = d.usage;
      if (u && (u.input_tokens || u.output_tokens)) {
        window.setTimeout(() => {
          emit({
            kind: "info",
            label: `${(u.input_tokens + u.output_tokens).toLocaleString()} tokens · ${u.rounds} round(s)`,
            detail: `${u.input_tokens} in / ${u.output_tokens} out`,
            status: "ok",
          });
        }, totalMs + STAGGER_MS);
      }

      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          text: d.reply || "(no reply)",
          actions: (d.proposed_actions || []).map((a) => ({ ...a, state: "pending" as const })),
          trace: events,
        },
      ]);
    } catch (e: any) {
      update(pending.id, { ms: Date.now() - started, status: "error" });
      if (e?.response?.status === 404) {
        setBackendMissing(true);
        setTurns((t) => t.slice(0, -1)); // drop the unanswered user turn
        setInput(message); // keep their text so they can retry later
      } else {
        const msg = e?.response?.data?.detail || e?.message || "Agent request failed.";
        setTurns((t) => [...t, { role: "assistant", text: `Error: ${msg}` }]);
      }
    } finally {
      setBusy(false);
    }
  }

  async function executeActions(turnIdx: number, ids: string[]) {
    const turn = turns[turnIdx];
    const targets = (turn.actions || []).filter(
      (a) => ids.includes(a.id) && (a.state === "pending" || a.state === "error"),
    );
    if (targets.length === 0) return;

    const mark = (state: ActionState, perId?: Record<string, string>) =>
      setTurns((t) =>
        t.map((x, i) =>
          i === turnIdx
            ? {
                ...x,
                actions: (x.actions || []).map((a) =>
                  ids.includes(a.id) && a.state !== "dismissed" && a.state !== "written"
                    ? { ...a, state, errorText: perId?.[a.id] }
                    : a,
                ),
              }
            : x,
        ),
      );
    mark("writing");

    try {
      const r = await api.post<AgentExecuteResult>(
        `/api/${hospitalId}/patients/${patientId}/copilot/agent/execute`,
        { actions: targets.map(stripAction) },
      );
      const written = r.data.written || [];
      const errors = r.data.errors || [];
      const errById: Record<string, string> = {};
      for (const e of errors) errById[e.id] = e.error;
      const writtenIds = new Set(written.map((w) => w.id));

      setTurns((t) =>
        t.map((x, i) => {
          if (i !== turnIdx) return x;
          const actions = (x.actions || []).map((a) => {
            if (!ids.includes(a.id) || a.state !== "writing") return a;
            if (writtenIds.has(a.id)) return { ...a, state: "written" as const };
            return { ...a, state: "error" as const, errorText: errById[a.id] || "Write failed" };
          });
          const writtenSummary =
            written.length > 0
              ? `Written to chart: ${written.map((w) => w.summary).join("; ")}`
              : x.writtenSummary;
          return { ...x, actions, writtenSummary };
        }),
      );

      if (written.length > 0) {
        for (const w of written) {
          emit({ kind: "info", label: `${w.resource_type} written`, detail: w.summary, status: "ok" });
        }
        reloadPatient();
      }
    } catch (e: any) {
      if (e?.response?.status === 404) setBackendMissing(true);
      const msg = e?.response?.data?.detail || e?.message || "Write failed";
      mark(
        "error",
        Object.fromEntries(targets.map((a) => [a.id, msg])),
      );
    }
  }

  function dismiss(turnIdx: number, id: string) {
    setTurns((t) =>
      t.map((x, i) =>
        i === turnIdx
          ? {
              ...x,
              actions: (x.actions || []).map((a) =>
                a.id === id && a.state === "pending" ? { ...a, state: "dismissed" } : a,
              ),
            }
          : x,
      ),
    );
  }

  return (
    <div className="flex h-[480px] flex-col rounded-xl border border-line bg-surface-lowest p-4">
      {backendMissing && (
        <div className="mb-3 rounded-lg bg-secondary-container px-4 py-3 text-sm text-ink">
          Agent backend not available yet — the agent endpoints have not been
          deployed. Try again once the backend is up.
        </div>
      )}

      <div ref={threadRef} className="flex-1 overflow-y-auto pr-1">
        {turns.length === 0 ? (
          <div className="flex flex-col gap-3 py-2">
            <p className="text-sm text-text-muted">
              Ask anything about {patient?.name || "this patient"}, or tell the
              agent what to add to the chart. It proposes — you confirm.
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {QUICK_CHIPS.map(({ icon: Icon, label, prompt }) => (
                <button
                  key={label}
                  onClick={() => ask(prompt)}
                  disabled={busy}
                  className="flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-2 text-left text-xs text-ink transition-colors hover:bg-surface-low disabled:opacity-50"
                >
                  <Icon className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
                  {label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2.5 py-1">
            {turns.map((m, i) => (
              <div key={i} className="flex flex-col gap-1.5">
                {m.role === "user" ? (
                  <div className="max-w-[88%] self-end rounded-lg rounded-br-sm bg-primary px-3 py-2 text-sm text-white">
                    {m.text}
                  </div>
                ) : (
                  <div className="flex max-w-[90%] flex-col gap-1 self-start">
                    {m.trace && m.trace.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {traceChips(m.trace).map((c, k) => {
                          const Icon = TRACE_ICON[c.kind];
                          return (
                            <span
                              key={k}
                              className="flex items-center gap-1 rounded bg-primary-dim px-1.5 py-0.5 text-[10px] font-medium text-primary"
                            >
                              <Icon className="h-2.5 w-2.5" aria-hidden />
                              {c.label}
                            </span>
                          );
                        })}
                      </div>
                    )}
                    <div className="rounded-lg rounded-bl-sm bg-surface-low px-3 py-2 text-ink">
                      <RichText text={m.text} />
                    </div>
                  </div>
                )}

                {m.actions && m.actions.length > 0 && (
                  <div className="flex w-[90%] flex-col gap-1.5 self-start">
                    {m.actions.map((a) => (
                      <div
                        key={a.id}
                        className={`rounded-md border border-line bg-surface p-2.5 ${
                          a.state === "dismissed" ? "opacity-50" : ""
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-[10px] font-bold uppercase tracking-wide text-secondary">
                              {a.resource_type}
                            </div>
                            <div className="text-sm text-ink">{a.summary}</div>
                            {a.state === "error" && a.errorText && (
                              <div className="mt-0.5 text-xs text-error">{a.errorText}</div>
                            )}
                          </div>
                          <div className="flex shrink-0 items-center gap-1.5">
                            {a.state === "pending" || a.state === "error" ? (
                              <>
                                <button
                                  onClick={() => executeActions(i, [a.id])}
                                  className="flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-xs font-medium text-white hover:bg-primary-hover"
                                >
                                  <Check className="h-3 w-3" aria-hidden />
                                  {a.state === "error" ? "Retry" : "Confirm"}
                                </button>
                                <button
                                  onClick={() => dismiss(i, a.id)}
                                  className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-text-muted hover:bg-surface-low"
                                >
                                  <X className="h-3 w-3" aria-hidden />
                                  Dismiss
                                </button>
                              </>
                            ) : a.state === "writing" ? (
                              <span className="text-xs text-text-muted">Writing…</span>
                            ) : a.state === "written" ? (
                              <span className="flex items-center gap-1 text-xs font-medium text-success">
                                <Check className="h-3 w-3" aria-hidden /> Written
                              </span>
                            ) : (
                              <span className="text-xs text-text-muted">Dismissed</span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                    {(m.actions.filter((a) => a.state === "pending").length > 1) && (
                      <button
                        onClick={() =>
                          executeActions(
                            i,
                            (m.actions || [])
                              .filter((a) => a.state === "pending")
                              .map((a) => a.id),
                          )
                        }
                        className="self-start rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover"
                      >
                        Confirm all ({m.actions.filter((a) => a.state === "pending").length})
                      </button>
                    )}
                    {m.writtenSummary && (
                      <div className="flex items-center gap-1.5 text-xs font-medium text-success">
                        <Check className="h-3.5 w-3.5" aria-hidden />
                        {m.writtenSummary}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            {busy && (
              <div className="flex items-center gap-1.5 self-start rounded-lg bg-surface-low px-3 py-2 text-sm text-text-muted">
                <Sparkles className="h-3.5 w-3.5 animate-pulse text-primary" aria-hidden />
                Agent is working…
              </div>
            )}
          </div>
        )}
      </div>

      <div className="mt-3 flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              ask(input);
            }
          }}
          placeholder="Ask the agent anything…"
          rows={1}
          className="max-h-24 min-h-[40px] flex-1 resize-none rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <button
          onClick={() => ask(input)}
          disabled={busy || !input.trim()}
          aria-label="Send"
          className="rounded-md bg-primary p-2.5 text-white hover:bg-primary-hover disabled:opacity-50"
        >
          <Send className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </div>
  );
}
