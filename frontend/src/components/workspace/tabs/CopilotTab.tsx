import { useState } from "react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import {
  copilotAsk,
  copilotSummary,
  copilotScan,
  copilotAutopopulate,
} from "../../../lib/api-ops";
import type {
  CopilotScanItem,
  CopilotAutopopulate,
  CopilotBlock,
} from "../../../lib/api-ops";
import CopilotArtifacts from "./CopilotArtifacts";
import { AgentChat, AgentConsole } from "../../copilot-agent";

/**
 * CopilotTab — an in-app EHR Copilot with two modes:
 *  - Assist (default): four read-only flows — ask (grounded Q&A), catch-me-up
 *    summary, a proactive fixable-issue scan, and an EHR→chart autopopulation
 *    review.
 *  - Agent: a conversational agent that reads the chart, reasons, and PROPOSES
 *    writes for per-action clinician confirmation, with a live trace console.
 *
 * In both modes the Copilot proposes; the clinician decides.
 */

const SUGGESTIONS = [
  "Any prior cardiac workup or admissions?",
  "Is the patient on anticoagulants — any bleeding risk?",
  "Summarize the relevant history for this complaint.",
  "Any medication interactions I should know about?",
];

function severityClasses(sev: string): string {
  const s = sev.toLowerCase();
  if (s === "high" || s === "critical")
    return "bg-error-container text-error border-error/30";
  if (s === "moderate" || s === "medium")
    return "bg-secondary-container text-ink border-line";
  return "bg-surface-low text-text-muted border-line";
}

/** Minimal **bold** rendering so model markdown reads cleanly without a lib. */
function RichText({ text }: { text: string }) {
  return (
    <div className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
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

export default function CopilotTab() {
  const { hospitalId, patientId, patient } = usePatientWorkspace();

  const [mode, setMode] = useState<"assist" | "agent">("assist");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string>("");
  const [blocks, setBlocks] = useState<CopilotBlock[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [busy, setBusy] = useState<"" | "ask" | "summary">("");
  const [error, setError] = useState<string | null>(null);

  const [scanItems, setScanItems] = useState<CopilotScanItem[] | null>(null);
  const [scanning, setScanning] = useState(false);

  const [auto, setAuto] = useState<CopilotAutopopulate | null>(null);
  const [autoLoading, setAutoLoading] = useState(false);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});

  async function runAsk(q: string) {
    const text = q.trim();
    if (!text) return;
    setBusy("ask");
    setError(null);
    setAnswer("");
    setBlocks([]);
    setSources([]);
    try {
      const r = await copilotAsk(hospitalId, patientId, text);
      setAnswer(r.answer || "No answer returned.");
      setBlocks(r.blocks || []);
      setSources(Array.from(new Set((r.sources || []).map((s) => s.resource || s.tool || ""))).filter(Boolean));
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Copilot is unavailable.");
    } finally {
      setBusy("");
    }
  }

  async function runSummary() {
    setBusy("summary");
    setError(null);
    setAnswer("");
    setBlocks([]);
    setSources([]);
    try {
      const r = await copilotSummary(hospitalId, patientId);
      setAnswer(r.answer || "No summary returned.");
      setBlocks(r.blocks || []);
      setSources(Array.from(new Set((r.sources || []).map((s) => s.resource || s.tool || ""))).filter(Boolean));
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Copilot is unavailable.");
    } finally {
      setBusy("");
    }
  }

  async function runScan() {
    setScanning(true);
    setError(null);
    try {
      const r = await copilotScan(hospitalId, patientId);
      setScanItems(r.items || []);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Scan failed.");
    } finally {
      setScanning(false);
    }
  }

  async function runAutopopulate() {
    setAutoLoading(true);
    setError(null);
    try {
      const r = await copilotAutopopulate(hospitalId, patientId);
      setAuto(r);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Autopopulate failed.");
    } finally {
      setAutoLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-semibold text-ink">EHR Copilot</h2>
        <p className="text-sm text-text-muted">
          Ask anything about {patient?.name || "this patient"}, get a catch-me-up
          summary, scan for fixable issues, or pull data in from the linked EHR.
          The Copilot only uses data it retrieves from the chart.
        </p>
      </header>

      {/* Mode switch — Assist (read-only flows) vs Agent (propose-and-confirm) */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setMode("assist")}
          className={
            mode === "assist"
              ? "rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white"
              : "rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-surface-low"
          }
        >
          Assist
        </button>
        <button
          onClick={() => setMode("agent")}
          className={
            mode === "agent"
              ? "rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white"
              : "rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-surface-low"
          }
        >
          Agent
        </button>
      </div>

      {mode === "agent" ? (
        <div className="space-y-4">
          <AgentChat />
          <AgentConsole />
        </div>
      ) : (
        <>
      {error && (
        <div className="rounded-lg bg-error-container px-4 py-3 text-sm text-error">
          {error}
        </div>
      )}

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={runSummary}
          disabled={busy !== ""}
          className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-60"
        >
          {busy === "summary" ? "Summarizing…" : "Catch me up"}
        </button>
        <button
          onClick={runScan}
          disabled={scanning}
          className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-surface-low disabled:opacity-60"
        >
          {scanning ? "Scanning…" : "Scan for fixes"}
        </button>
        <button
          onClick={runAutopopulate}
          disabled={autoLoading}
          className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-surface-low disabled:opacity-60"
        >
          {autoLoading ? "Reading EHR…" : "Autopopulate from EHR"}
        </button>
      </div>

      {/* Ask box */}
      <div className="rounded-xl border border-line bg-surface p-4">
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runAsk(question)}
            placeholder="Ask the chart a question…"
            className="flex-1 rounded-lg border border-line bg-surface-lowest px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <button
            onClick={() => runAsk(question)}
            disabled={busy !== "" || !question.trim()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-60"
          >
            {busy === "ask" ? "Thinking…" : "Ask"}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => {
                setQuestion(s);
                runAsk(s);
              }}
              className="rounded-full border border-line bg-surface-low px-2.5 py-1 text-xs text-text-muted hover:bg-surface-high hover:text-ink"
            >
              {s}
            </button>
          ))}
        </div>

        {(blocks.length > 0 || answer) && (
          <div className="mt-4">
            {blocks.length > 0 ? (
              <CopilotArtifacts blocks={blocks} />
            ) : (
              <div className="rounded-lg bg-surface-low p-4">
                <RichText text={answer} />
              </div>
            )}
            {sources.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-2">
                <span className="text-xs font-medium text-text-muted">Sources:</span>
                {sources.map((s) => (
                  <span
                    key={s}
                    className="rounded-full bg-surface-high px-2 py-0.5 text-[11px] text-text-muted"
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Scan results */}
      {scanItems && (
        <section className="rounded-xl border border-line bg-surface p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink">
            Fixable issues {scanItems.length > 0 && `(${scanItems.length})`}
          </h3>
          {scanItems.length === 0 ? (
            <p className="text-sm text-text-muted">No open issues detected.</p>
          ) : (
            <ul className="space-y-2">
              {scanItems.map((it, i) => (
                <li
                  key={i}
                  className={`rounded-lg border px-3 py-2 ${severityClasses(it.severity)}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{it.title}</span>
                    <span className="text-[11px] font-semibold uppercase tracking-wide">
                      {it.severity}
                    </span>
                  </div>
                  {it.detail && <p className="mt-0.5 text-xs opacity-90">{it.detail}</p>}
                  {it.action && (
                    <p className="mt-1 text-xs font-medium">→ {it.action}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Autopopulate review */}
      {auto && (
        <section className="rounded-xl border border-line bg-surface p-4">
          <h3 className="mb-1 text-sm font-semibold text-ink">
            Autopopulate from EHR
          </h3>
          {!auto.linked ? (
            <p className="text-sm text-text-muted">
              {auto.note || "No linked EHR record."}
            </p>
          ) : (
            <>
              <p className="mb-3 text-xs text-text-muted">
                Review what the EHR has that isn't on the chart, then accept the
                additions you want. {auto.source && `Source: ${auto.source}.`}
              </p>
              <div className="space-y-3">
                {auto.fields.map((f) => (
                  <div key={f.field} className="rounded-lg bg-surface-low p-3">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-sm font-medium capitalize text-ink">
                        {f.field}
                      </span>
                      {f.has_changes ? (
                        <label className="flex items-center gap-1.5 text-xs text-primary">
                          <input
                            type="checkbox"
                            checked={!!accepted[f.field]}
                            onChange={(e) =>
                              setAccepted((a) => ({ ...a, [f.field]: e.target.checked }))
                            }
                          />
                          Accept {f.additions.length} from EHR
                        </label>
                      ) : (
                        <span className="text-xs text-text-muted">in sync</span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-xs">
                      <div>
                        <div className="mb-1 text-text-muted">On chart</div>
                        {f.current.length ? (
                          f.current.map((c) => <div key={c} className="text-ink">{c}</div>)
                        ) : (
                          <div className="italic text-text-muted">—</div>
                        )}
                      </div>
                      <div>
                        <div className="mb-1 text-text-muted">In EHR</div>
                        {f.ehr.length ? (
                          f.ehr.map((c) => (
                            <div
                              key={c}
                              className={
                                f.additions.includes(c)
                                  ? "font-medium text-primary"
                                  : "text-ink"
                              }
                            >
                              {c}
                              {f.additions.includes(c) && " (new)"}
                            </div>
                          ))
                        ) : (
                          <div className="italic text-text-muted">—</div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      )}
        </>
      )}
    </div>
  );
}

CopilotTab.displayName = "CopilotTab";
