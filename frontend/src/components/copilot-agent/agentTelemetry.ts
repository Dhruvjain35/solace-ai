/**
 * agentTelemetry — client-side pub/sub bus for the Copilot Agent console.
 *
 * The agent backend returns a structured `events` trace with each reply; this
 * bus replays that trace (staggered so the cascade reads live) and lets the
 * chat surface local pending rows while a request is in flight. Nothing here
 * is fabricated — labels, latencies and token counts come from the backend.
 *
 * Deliberately NO global fetch/axios interceptor: this bus only carries
 * agent-trace events that components emit explicitly.
 */

/** Event kinds the agent backend emits (contract-exact). */
export type AgentEventKind = "fhir" | "think" | "propose" | "info";

/** One trace step as returned by POST .../copilot/agent (contract-exact). */
export interface AgentBackendEvent {
  kind: AgentEventKind;
  label: string;
  detail: string | null;
  ms: number | null;
  status: "ok" | "error" | null;
}

/** A proposed chart write awaiting clinician confirmation (contract-exact). */
export interface AgentAction {
  id: string;
  resource_type: string;
  summary: string;
  resource: Record<string, unknown>;
}

/** Token/round accounting for one agent turn (contract-exact). */
export interface AgentUsage {
  input_tokens: number;
  output_tokens: number;
  rounds: number;
}

/** Full response body of POST .../copilot/agent (contract-exact). */
export interface AgentReply {
  reply: string;
  proposed_actions: AgentAction[];
  events: AgentBackendEvent[];
  usage: AgentUsage;
}

/** Full response body of POST .../copilot/agent/execute (contract-exact). */
export interface AgentExecuteResult {
  written: { id: string; resource_type: string; summary: string }[];
  errors: { id: string; error: string }[];
}

/** Local console rows add an id + timestamp and may be transiently pending. */
export type TelemetryStatus = "ok" | "error" | "pending" | null;

export interface TelemetryEvent {
  id: number;
  at: number; // epoch ms
  kind: AgentEventKind;
  label: string;
  detail?: string | null;
  ms?: number | null;
  status?: TelemetryStatus;
}

type Listener = (events: TelemetryEvent[]) => void;

const MAX_EVENTS = 240;
let events: TelemetryEvent[] = [];
let seq = 0;
const listeners = new Set<Listener>();

function notify() {
  for (const l of listeners) l(events);
}

/** Push a new event onto the feed and return it (so callers can update it later). */
export function emit(
  input: Omit<TelemetryEvent, "id" | "at"> & { at?: number },
): TelemetryEvent {
  const { at, ...rest } = input;
  const ev: TelemetryEvent = { id: ++seq, at: at ?? Date.now(), ...rest };
  events = [...events, ev].slice(-MAX_EVENTS);
  notify();
  return ev;
}

/** Patch an existing event in place (used to resolve a pending row). */
export function update(id: number, patch: Partial<TelemetryEvent>): void {
  let changed = false;
  events = events.map((e) => {
    if (e.id !== id) return e;
    changed = true;
    return { ...e, ...patch };
  });
  if (changed) notify();
}

/** Subscribe to the feed; the listener is called immediately with current state. */
export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  fn(events);
  return () => {
    listeners.delete(fn);
  };
}

export function clearTelemetry(): void {
  events = [];
  notify();
}

export function getTelemetry(): TelemetryEvent[] {
  return events;
}

/**
 * Replay server-side agent events with a small stagger so they read live.
 * Returns the total replay duration in ms (use it to schedule trailing rows).
 */
export function replayEvents(evs: AgentBackendEvent[], staggerMs = 100): number {
  evs.forEach((e, i) => {
    window.setTimeout(() => {
      emit({
        kind: e.kind,
        label: e.label,
        detail: e.detail,
        ms: e.ms,
        status: e.status,
      });
    }, i * staggerMs);
  });
  return evs.length * staggerMs;
}
