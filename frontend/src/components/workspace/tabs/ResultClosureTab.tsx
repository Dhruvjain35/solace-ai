import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import {
  resultsDetectAbnormal,
  resultsReview,
  resultClosureOpen,
  resultClosureAdvance,
  resultClosureSummary,
} from "../../../lib/api-ops";
import type {
  AbnormalResult,
  ResultReviewDraft,
  ResultClosure,
  ClosureSummary,
} from "../../../lib/api-ops";

/**
 * Result Closure tab — abnormal-result loop-closure for the workspace patient.
 *
 * Flow:
 *   1. Clinician enters raw result rows (seeded from the patient's ordered labs).
 *   2. Detect abnormal results (resultsDetectAbnormal).
 *   3. Draft plain-language patient messages (resultsReview).
 *   4. Open a closure per abnormal result (resultClosureOpen) and walk the
 *      state machine via resultClosureAdvance.
 *
 * State machine: outstanding -> communicated -> acknowledged, plus dismissed.
 *   outstanding -> { communicated, dismissed }
 *   communicated -> { acknowledged, dismissed }
 *   terminal: acknowledged, dismissed
 * Advance buttons render only for legal transitions; illegal transitions
 * return HTTP 409 and are surfaced inline without losing local state.
 */

// --- state-machine description ------------------------------------------------

type ClosureState = "outstanding" | "communicated" | "acknowledged" | "dismissed";

const LEGAL_TRANSITIONS: Record<string, ClosureState[]> = {
  outstanding: ["communicated", "dismissed"],
  communicated: ["acknowledged", "dismissed"],
  acknowledged: [],
  dismissed: [],
};

const TERMINAL_STATES = new Set(["acknowledged", "dismissed"]);

const STATE_LABEL: Record<string, string> = {
  outstanding: "Outstanding",
  communicated: "Communicated",
  acknowledged: "Acknowledged",
  dismissed: "Dismissed",
};

const STATE_CHIP: Record<string, string> = {
  outstanding: "bg-warning-container text-warning",
  communicated: "bg-secondary-container text-primary",
  acknowledged: "bg-success-container text-success",
  dismissed: "bg-surface-high text-text-muted",
};

const TRANSITION_LABEL: Record<string, string> = {
  communicated: "Mark communicated",
  acknowledged: "Mark acknowledged",
  dismissed: "Dismiss",
};

// --- editable result rows -----------------------------------------------------

type ResultRow = {
  id: string;
  name: string;
  value: string;
  unit: string;
};

let rowSeq = 0;
function newRow(name = "", value = "", unit = ""): ResultRow {
  rowSeq += 1;
  return { id: `r${rowSeq}`, name, value, unit };
}

function errMessage(e: unknown): string {
  const err = e as {
    response?: { status?: number; data?: { detail?: string } };
    message?: string;
  };
  return err?.response?.data?.detail || err?.message || "Request failed";
}

function isConflict(e: unknown): boolean {
  const err = e as { response?: { status?: number } };
  return err?.response?.status === 409;
}

function resultLabel(r: AbnormalResult): string {
  return r.result_name || r.name || "Result";
}

function closureResultLabel(c: ResultClosure): string {
  const r = (c.result || {}) as Record<string, unknown>;
  const name = (r.result_name as string) || (r.name as string);
  return name || "Result";
}

function severityChip(severity?: string): string {
  const s = (severity || "").toLowerCase();
  if (s === "critical" || s === "high") return "bg-error-container text-error";
  if (s === "moderate") return "bg-warning-container text-warning";
  return "bg-surface-high text-text-muted";
}

export default function ResultClosureTab() {
  const { hospitalId, patientId, patient, loading, error } = usePatientWorkspace();

  // ----- pipeline state -------------------------------------------------------
  const [rows, setRows] = useState<ResultRow[]>(() => [newRow()]);
  const [seeded, setSeeded] = useState(false);

  const [abnormal, setAbnormal] = useState<AbnormalResult[] | null>(null);
  const [drafts, setDrafts] = useState<ResultReviewDraft[]>([]);
  const [closures, setClosures] = useState<ResultClosure[]>([]);
  const [summary, setSummary] = useState<ClosureSummary | null>(null);

  const [detecting, setDetecting] = useState(false);
  const [drafting, setDrafting] = useState(false);
  // closure_id (or "new:<idx>") currently mutating
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const [banner, setBanner] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Seed editable rows from the patient's ordered labs once the record loads.
  const seedRows = useCallback(() => {
    if (seeded || !patient) return;
    const labs = patient.workup_orders?.labs ?? [];
    if (labs.length > 0) {
      setRows(labs.slice(0, 12).map((l) => newRow(l)));
    }
    setSeeded(true);
  }, [seeded, patient]);
  // Run the seed lazily on first render with a patient present.
  if (!seeded && patient) seedRows();

  const draftByName = useMemo(() => {
    const m = new Map<string, ResultReviewDraft>();
    for (const d of drafts) m.set(d.result_name, d);
    return m;
  }, [drafts]);

  // ----- guards ---------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted text-sm">
        <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
        Loading patient record…
      </div>
    );
  }
  if (error) {
    return <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>;
  }
  if (!patient) {
    return <div className="text-text-muted text-sm py-8">No patient record available.</div>;
  }

  // ----- row editing ----------------------------------------------------------

  const updateRow = (id: string, field: keyof ResultRow, val: string) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [field]: val } : r)));
  };
  const addRow = () => setRows((rs) => [...rs, newRow()]);
  const removeRow = (id: string) =>
    setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.id !== id) : rs));

  const rowPayload = (): Record<string, unknown>[] =>
    rows
      .filter((r) => r.name.trim() !== "")
      .map((r) => {
        const numeric = Number(r.value);
        return {
          result_name: r.name.trim(),
          value:
            r.value.trim() !== "" && !Number.isNaN(numeric) ? numeric : r.value.trim(),
          ...(r.unit.trim() ? { unit: r.unit.trim() } : {}),
        };
      });

  // ----- pipeline actions -----------------------------------------------------

  const runDetect = async () => {
    const payload = rowPayload();
    setBanner(null);
    setNotice(null);
    if (payload.length === 0) {
      setBanner("Enter at least one result with a name before detecting.");
      return;
    }
    setDetecting(true);
    setDrafts([]);
    try {
      const res = await resultsDetectAbnormal(hospitalId, payload);
      setAbnormal(res.abnormal_results);
      if (res.count === 0) {
        setNotice("No abnormal results detected — nothing to close out.");
      }
    } catch (e) {
      setBanner(errMessage(e));
    } finally {
      setDetecting(false);
    }
  };

  const runReview = async () => {
    if (!abnormal || abnormal.length === 0) return;
    setBanner(null);
    setDrafting(true);
    try {
      const res = await resultsReview(hospitalId, {
        abnormal_results: abnormal,
        reading_level: "plain",
      });
      setDrafts(res.drafts);
    } catch (e) {
      setBanner(errMessage(e));
    } finally {
      setDrafting(false);
    }
  };

  const refreshSummary = useCallback(
    async (list: ResultClosure[]) => {
      if (list.length === 0) {
        setSummary(null);
        return;
      }
      try {
        const s = await resultClosureSummary(hospitalId, list);
        setSummary(s);
      } catch {
        // Summary is advisory — a failure here must not block the workflow.
        setSummary(null);
      }
    },
    [hospitalId],
  );

  const openClosure = async (result: AbnormalResult, idx: number) => {
    setBanner(null);
    setBusyKey(`new:${idx}`);
    try {
      const closure = await resultClosureOpen(hospitalId, {
        patient_id: patientId,
        result: result as Record<string, unknown>,
        detected_by: "clinician",
      });
      const next = [...closures, closure];
      setClosures(next);
      void refreshSummary(next);
    } catch (e) {
      setBanner(errMessage(e));
    } finally {
      setBusyKey(null);
    }
  };

  const advanceClosure = async (closure: ResultClosure, toState: ClosureState) => {
    setBanner(null);
    setBusyKey(closure.closure_id);
    const draft = draftByName.get(closureResultLabel(closure));
    try {
      const updated = await resultClosureAdvance(hospitalId, {
        closure,
        to_state: toState,
        actor: "clinician",
        ...(toState === "communicated" && draft
          ? { patient_message: draft.message }
          : {}),
      });
      const next = closures.map((c) =>
        c.closure_id === updated.closure_id ? updated : c,
      );
      setClosures(next);
      void refreshSummary(next);
    } catch (e) {
      if (isConflict(e)) {
        // The closure already moved past this state elsewhere — keep local
        // state, surface the conflict, and let the clinician retry.
        setBanner(
          `That transition is no longer legal for "${closureResultLabel(closure)}" ` +
            "(closure already advanced). Refresh to see its current state.",
        );
      } else {
        setBanner(errMessage(e));
      }
    } finally {
      setBusyKey(null);
    }
  };

  const openClosureIds = new Set(
    closures.map((c) => closureResultLabel(c).toLowerCase()),
  );

  // ----- render ---------------------------------------------------------------

  return (
    <div className="space-y-6 pb-10">
      {/* header */}
      <div>
        <h2 className="text-lg font-bold tracking-editorial flex items-center gap-2">
          <CheckCircle2 size={20} className="text-primary" aria-hidden="true" />
          Result Closure
        </h2>
        <p className="text-text-muted text-sm mt-1">
          Detect abnormal results for {patient.name}, draft plain-language patient
          messages, and close the loop through the acknowledgement workflow.
        </p>
      </div>

      {banner && (
        <div
          role="alert"
          className="p-3 rounded-md bg-error-container text-error text-sm flex items-start gap-2"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{banner}</span>
        </div>
      )}
      {notice && (
        <div className="p-3 rounded-md bg-secondary-container text-primary text-sm">
          {notice}
        </div>
      )}

      {/* step 1 — enter results */}
      <section className="bg-surface-lowest rounded-xl shadow-card p-5">
        <h3 className="font-bold text-sm flex items-center gap-2">
          <ClipboardList size={16} className="text-primary" aria-hidden="true" />
          1. Result values
        </h3>
        <p className="text-text-muted text-xs mt-1">
          Seeded from this patient's ordered labs. Enter measured values, then
          detect which results are abnormal.
        </p>
        <div className="mt-3 space-y-2">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center gap-2">
              <input
                value={row.name}
                onChange={(e) => updateRow(row.id, "name", e.target.value)}
                placeholder="Result name"
                className="flex-1 min-w-0 rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <input
                value={row.value}
                onChange={(e) => updateRow(row.id, "value", e.target.value)}
                placeholder="Value"
                className="w-24 rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <input
                value={row.unit}
                onChange={(e) => updateRow(row.id, "unit", e.target.value)}
                placeholder="Unit"
                className="w-20 rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <button
                type="button"
                onClick={() => removeRow(row.id)}
                disabled={rows.length <= 1}
                aria-label="Remove result row"
                className="p-1.5 rounded-md text-text-muted hover:bg-surface-high disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <Trash2 size={15} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            onClick={addRow}
            className="inline-flex items-center gap-1 text-sm text-primary hover:text-primary-hover font-medium"
          >
            <Plus size={15} aria-hidden="true" />
            Add result
          </button>
          <div className="flex-1" />
          <button
            type="button"
            onClick={runDetect}
            disabled={detecting}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-3.5 py-1.5 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {detecting && <Loader2 size={15} className="animate-spin" aria-hidden="true" />}
            Detect abnormal
          </button>
        </div>
      </section>

      {/* step 2 — abnormal results + drafts */}
      {abnormal && abnormal.length > 0 && (
        <section className="bg-surface-lowest rounded-xl shadow-card p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-bold text-sm flex items-center gap-2">
              <AlertTriangle size={16} className="text-warning" aria-hidden="true" />
              2. Abnormal results ({abnormal.length})
            </h3>
            <button
              type="button"
              onClick={runReview}
              disabled={drafting}
              className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-primary hover:bg-surface-high disabled:opacity-50"
            >
              {drafting && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
              Draft patient messages
            </button>
          </div>

          <div className="mt-3 space-y-3">
            {abnormal.map((r, idx) => {
              const label = resultLabel(r);
              const draft = draftByName.get(label);
              const alreadyOpen = openClosureIds.has(label.toLowerCase());
              return (
                <div
                  key={`${label}-${idx}`}
                  className="rounded-lg border border-line bg-surface p-3"
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-medium text-sm truncate">{label}</span>
                      {(r.value !== undefined && r.value !== "") && (
                        <span className="text-text-muted text-xs font-mono">
                          {String(r.value)}
                          {r.unit ? ` ${r.unit}` : ""}
                        </span>
                      )}
                      {r.severity && (
                        <span
                          className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${severityChip(
                            r.severity,
                          )}`}
                        >
                          {r.severity}
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => openClosure(r, idx)}
                      disabled={alreadyOpen || busyKey === `new:${idx}`}
                      className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-hover disabled:opacity-50"
                    >
                      {busyKey === `new:${idx}` && (
                        <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                      )}
                      {alreadyOpen ? "Closure opened" : "Open closure"}
                    </button>
                  </div>
                  {r.reason && (
                    <p className="text-text-muted text-xs mt-1.5">{r.reason}</p>
                  )}
                  {draft && (
                    <div className="mt-2 rounded-md bg-surface-low p-2.5">
                      <p className="text-[11px] font-medium text-text-muted uppercase tracking-wide">
                        Patient message · {draft.tone}
                      </p>
                      <p className="text-sm mt-1 text-ink">{draft.message}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* step 3 — closure queue */}
      {closures.length > 0 && (
        <section className="bg-surface-lowest rounded-xl shadow-card p-5">
          <h3 className="font-bold text-sm flex items-center gap-2">
            <CheckCircle2 size={16} className="text-primary" aria-hidden="true" />
            3. Closure queue
          </h3>

          {summary && (
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <SummaryStat label="Total" value={summary.total} />
              <SummaryStat label="Open" value={summary.open} tone="warning" />
              <SummaryStat label="Closed" value={summary.closed} tone="success" />
              {summary.critical_open > 0 && (
                <SummaryStat
                  label="Critical open"
                  value={summary.critical_open}
                  tone="error"
                />
              )}
            </div>
          )}

          <div className="mt-3 space-y-2.5">
            {closures.map((c) => {
              const state = c.state;
              const transitions = LEGAL_TRANSITIONS[state] ?? [];
              const isTerminal = TERMINAL_STATES.has(state);
              const mutating = busyKey === c.closure_id;
              return (
                <div
                  key={c.closure_id}
                  className="rounded-lg border border-line bg-surface p-3"
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-medium text-sm truncate">
                        {closureResultLabel(c)}
                      </span>
                      <span
                        className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${
                          STATE_CHIP[state] ?? "bg-surface-high text-text-muted"
                        }`}
                      >
                        {STATE_LABEL[state] ?? state}
                      </span>
                    </div>
                    {!isTerminal && (
                      <div className="flex items-center gap-1.5">
                        {transitions.map((to) => (
                          <button
                            key={to}
                            type="button"
                            onClick={() => advanceClosure(c, to)}
                            disabled={mutating}
                            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium disabled:opacity-50 ${
                              to === "dismissed"
                                ? "border border-line bg-surface text-text-muted hover:bg-surface-high"
                                : "bg-primary text-white hover:bg-primary-hover"
                            }`}
                          >
                            {mutating && (
                              <Loader2
                                size={12}
                                className="animate-spin"
                                aria-hidden="true"
                              />
                            )}
                            {TRANSITION_LABEL[to] ?? to}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  {c.history && c.history.length > 0 && (
                    <ol className="mt-2 space-y-0.5 border-l border-line pl-3">
                      {c.history.map((h, i) => (
                        <li key={i} className="text-[11px] text-text-muted">
                          <span className="font-medium text-ink">
                            {STATE_LABEL[h.state] ?? h.state}
                          </span>
                          {h.actor ? ` · ${h.actor}` : ""}
                          {h.at ? ` · ${h.at}` : ""}
                          {h.note ? ` — ${h.note}` : ""}
                        </li>
                      ))}
                    </ol>
                  )}
                  <p className="mt-1.5 text-[11px] text-text-muted font-mono">
                    {c.closure_id}
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "warning" | "success" | "error";
}) {
  const cls =
    tone === "warning"
      ? "bg-warning-container text-warning"
      : tone === "success"
        ? "bg-success-container text-success"
        : tone === "error"
          ? "bg-error-container text-error"
          : "bg-surface-high text-text-muted";
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md ${cls}`}>
      <span className="font-bold">{value}</span>
      <span>{label}</span>
    </span>
  );
}
