import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Plus, Trash2, Play, Power, Loader2, Check, X as XIcon,
  Workflow as WorkflowIcon, Sparkles, AlertCircle, Zap,
} from "lucide-react";
import {
  getWorkflowCatalog,
  listWorkflows,
  createWorkflow,
  updateWorkflow,
  deleteWorkflow,
  testWorkflow,
  workflowFromTemplate,
  type Workflow,
  type WorkflowActionDef,
  type WorkflowTrigger,
  type WorkflowTemplate,
  type WorkflowStep,
} from "../lib/api";
import { loadSession } from "../lib/session";

/**
 * No-code workflow admin.
 *
 * Layout: left rail = list, right pane = edit form. Editor is form-based
 * (not drag-drop) — admins add/remove steps from a vertical list, each with
 * type + per-action config fields rendered from the catalog schema.
 */
export default function WorkflowsAdmin() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const navigate = useNavigate();

  const [pin, setPin] = useState<string>("");
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [triggers, setTriggers] = useState<WorkflowTrigger[]>([]);
  const [actions, setActions] = useState<WorkflowActionDef[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Workflow | null>(null);
  const [draft, setDraft] = useState<Workflow | null>(null);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);

  // Auth gate
  useEffect(() => {
    const sess = loadSession();
    if (!sess) {
      navigate(`/${hospitalId}/clinician`, { replace: true });
      return;
    }
    setPin(sess.token);
  }, [hospitalId, navigate]);

  async function refresh() {
    if (!pin) return;
    setLoading(true);
    setError(null);
    try {
      const [cat, list] = await Promise.all([
        getWorkflowCatalog(hospitalId),
        listWorkflows(hospitalId),
      ]);
      setTriggers(cat.triggers);
      setActions(cat.actions);
      setTemplates(cat.templates);
      setWorkflows(list);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (pin) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pin]);

  function newDraft() {
    setSelected(null);
    setDraft({
      workflow_id: "",
      hospital_id: hospitalId,
      name: "",
      trigger: triggers[0]?.name || "patient.checked_in",
      enabled: false,
      filters: {},
      steps: [],
    });
    setTestResult(null);
  }

  async function fromTemplate(t: WorkflowTemplate) {
    if (!pin) return;
    setSaving(true);
    try {
      const wf = await workflowFromTemplate(hospitalId, t.id);
      await refresh();
      openWorkflow(wf);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't instantiate template");
    } finally {
      setSaving(false);
    }
  }

  function openWorkflow(wf: Workflow) {
    setSelected(wf);
    setDraft({ ...wf });
    setTestResult(null);
  }

  async function save() {
    if (!draft || !pin) return;
    if (!draft.name.trim()) {
      setError("Name is required");
      return;
    }
    if (draft.steps.length === 0) {
      setError("Add at least one step");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = {
        name: draft.name,
        trigger: draft.trigger,
        enabled: draft.enabled,
        filters: draft.filters || {},
        steps: draft.steps,
      };
      const saved = selected?.workflow_id
        ? await updateWorkflow(hospitalId, selected.workflow_id, body)
        : await createWorkflow(hospitalId, body);
      await refresh();
      openWorkflow(saved);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!selected || !pin) return;
    if (!window.confirm(`Delete "${selected.name}"?`)) return;
    await deleteWorkflow(hospitalId, selected.workflow_id);
    setSelected(null);
    setDraft(null);
    await refresh();
  }

  async function test() {
    if (!draft || !pin) return;
    setSaving(true);
    try {
      const r = await testWorkflow(hospitalId, {
        workflow: { ...draft, hospital_id: hospitalId } as any,
      });
      setTestResult(r);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Test failed");
    } finally {
      setSaving(false);
    }
  }

  const selectedTrigger = useMemo(
    () => triggers.find((t) => t.name === draft?.trigger),
    [triggers, draft?.trigger]
  );

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      <header className="px-5 py-3 border-b border-line bg-surface-lowest flex items-center gap-3">
        <Link
          to={`/${hospitalId}/clinician`}
          className="w-9 h-9 rounded-md hover:bg-surface-low flex items-center justify-center"
        >
          <ArrowLeft size={18} />
        </Link>
        <WorkflowIcon size={18} className="text-primary" />
        <div className="font-semibold tracking-tight">Workflows</div>
        <div className="ml-auto text-xs text-text-muted">
          {workflows.length} workflow{workflows.length === 1 ? "" : "s"} ·{" "}
          {workflows.filter((w) => w.enabled).length} enabled
        </div>
      </header>

      <div className="flex-1 grid grid-cols-[300px_1fr] min-h-0">
        {/* Left rail: workflow list */}
        <aside className="border-r border-line bg-surface-low overflow-y-auto">
          <div className="p-3 border-b border-line bg-surface-lowest">
            <button
              type="button"
              onClick={newDraft}
              className="w-full inline-flex items-center justify-center gap-1.5 h-9 rounded-md bg-primary text-white text-sm font-semibold"
            >
              <Plus size={14} /> New workflow
            </button>
          </div>

          {loading && (
            <div className="p-4 text-text-muted text-sm flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" /> Loading…
            </div>
          )}

          {!loading && workflows.length === 0 && (
            <div className="p-4 text-sm text-text-muted">
              No workflows yet. Start from a template below or hit New workflow.
            </div>
          )}

          {workflows.map((wf) => (
            <button
              key={wf.workflow_id}
              type="button"
              onClick={() => openWorkflow(wf)}
              className={`w-full text-left px-3 py-2.5 border-b border-line ${
                selected?.workflow_id === wf.workflow_id
                  ? "bg-primary-fixed"
                  : "hover:bg-surface-lowest"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block w-2 h-2 rounded-full ${
                    wf.enabled ? "bg-success" : "bg-text-muted"
                  }`}
                />
                <span className="font-semibold text-sm truncate flex-1">{wf.name}</span>
              </div>
              <div className="text-[11px] text-text-muted font-mono mt-0.5 truncate">
                {wf.trigger} · {wf.steps.length} step{wf.steps.length === 1 ? "" : "s"}
                {wf.fire_count ? ` · fired ${wf.fire_count}×` : ""}
              </div>
            </button>
          ))}

          <div className="p-3 mt-2 border-t border-line">
            <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-2">
              Templates
            </div>
            <div className="flex flex-col gap-1.5">
              {templates.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => fromTemplate(t)}
                  disabled={saving}
                  className="text-left px-2 py-2 rounded-md bg-surface-lowest hover:bg-primary-fixed text-xs"
                  title={t.description}
                >
                  <div className="font-semibold flex items-center gap-1">
                    <Sparkles size={11} className="text-primary" /> {t.label}
                  </div>
                  <div className="text-text-muted truncate">{t.description}</div>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* Right pane: editor */}
        <main className="overflow-y-auto p-6">
          {!draft ? (
            <div className="h-full flex items-center justify-center text-center text-text-muted">
              <div>
                <WorkflowIcon size={36} className="mx-auto mb-3 opacity-50" />
                <div className="font-semibold">Pick a workflow on the left</div>
                <div className="text-xs mt-1">or hit New workflow / a template to start.</div>
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto flex flex-col gap-5">
              {error && (
                <div className="p-3 rounded-md bg-error-container text-error text-sm flex items-center gap-2">
                  <AlertCircle size={14} />
                  {error}
                </div>
              )}

              <div>
                <label className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
                  Name
                </label>
                <input
                  type="text"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="Text discharge plan when patient marked seen"
                  className="w-full mt-1 h-11 px-3 rounded-md bg-surface-lowest ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none"
                />
              </div>

              <div>
                <label className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
                  When this happens
                </label>
                <select
                  value={draft.trigger}
                  onChange={(e) => setDraft({ ...draft, trigger: e.target.value })}
                  className="w-full mt-1 h-11 px-3 rounded-md bg-surface-lowest ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none"
                >
                  {triggers.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.label} ({t.name})
                    </option>
                  ))}
                </select>
                {selectedTrigger && (
                  <div className="text-xs text-text-muted mt-1.5 leading-snug">
                    {selectedTrigger.description}{" "}
                    <span className="text-primary">Available variables: </span>
                    <span className="font-mono">
                      {Object.keys(flatten(selectedTrigger.sample_context))
                        .map((p) => `{{${p}}}`)
                        .join("  ")}
                    </span>
                  </div>
                )}
              </div>

              <div className="bg-surface-lowest rounded-lg p-4 shadow-soft">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
                    Then do
                  </div>
                  <span className="text-xs text-text-muted">
                    {draft.steps.length} step{draft.steps.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="flex flex-col gap-3">
                  <AnimatePresence>
                    {draft.steps.map((step, idx) => (
                      <motion.div
                        key={idx}
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className="bg-surface-low rounded-md p-3 flex flex-col gap-2"
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[11px] text-text-muted">
                            {String(idx + 1).padStart(2, "0")}
                          </span>
                          <select
                            value={step.type}
                            onChange={(e) => {
                              const next = [...draft.steps];
                              next[idx] = { ...step, type: e.target.value, config: {} };
                              setDraft({ ...draft, steps: next });
                            }}
                            className="flex-1 h-9 px-2 rounded-md bg-surface-lowest ring-1 ring-line text-sm outline-none"
                          >
                            {actions.map((a) => (
                              <option key={a.type} value={a.type}>
                                {a.label}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            onClick={() => {
                              const next = [...draft.steps];
                              next.splice(idx, 1);
                              setDraft({ ...draft, steps: next });
                            }}
                            aria-label="Remove step"
                            className="w-9 h-9 rounded-md text-text-muted hover:text-error hover:bg-error/10 flex items-center justify-center"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                        <ActionFields
                          step={step}
                          actions={actions}
                          onChange={(config) => {
                            const next = [...draft.steps];
                            next[idx] = { ...step, config };
                            setDraft({ ...draft, steps: next });
                          }}
                        />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  <button
                    type="button"
                    onClick={() =>
                      setDraft({
                        ...draft,
                        steps: [
                          ...draft.steps,
                          { type: actions[0]?.type || "send_sms", config: {} },
                        ],
                      })
                    }
                    className="h-10 rounded-md border-2 border-dashed border-line text-text-muted hover:border-primary hover:text-primary text-sm font-semibold inline-flex items-center justify-center gap-1.5"
                  >
                    <Plus size={14} /> Add step
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="text-sm font-semibold inline-flex items-center gap-1">
                    <Power size={13} /> Enabled
                  </span>
                </label>
                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    onClick={test}
                    disabled={saving || draft.steps.length === 0}
                    className="h-10 px-4 rounded-md bg-surface-low text-ink hover:bg-surface-high text-sm font-semibold border border-line inline-flex items-center gap-1.5"
                  >
                    {saving ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    Test (dry run)
                  </button>
                  {selected?.workflow_id && (
                    <button
                      type="button"
                      onClick={remove}
                      className="h-10 px-4 rounded-md bg-surface-low text-error hover:bg-error/10 text-sm font-semibold border border-line inline-flex items-center gap-1.5"
                    >
                      <Trash2 size={14} /> Delete
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={save}
                    disabled={saving || !draft.name.trim()}
                    className="h-10 px-4 rounded-md bg-primary text-white text-sm font-semibold inline-flex items-center gap-1.5"
                  >
                    {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                    Save
                  </button>
                </div>
              </div>

              {testResult && (
                <div className="bg-surface-lowest rounded-lg p-4 shadow-soft">
                  <div className="flex items-center gap-2 mb-2">
                    <Zap size={14} className="text-primary" />
                    <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
                      Test results
                    </div>
                  </div>
                  <div className="flex flex-col gap-2">
                    {testResult.results.map((r: any, i: number) => (
                      <div
                        key={i}
                        className={`flex items-start gap-2 p-2 rounded-md text-xs ${
                          r.result.success ? "bg-success/10" : "bg-error/10"
                        }`}
                      >
                        {r.result.success ? (
                          <Check size={14} className="text-success mt-0.5 shrink-0" />
                        ) : (
                          <XIcon size={14} className="text-error mt-0.5 shrink-0" />
                        )}
                        <div>
                          <div className="font-semibold">{r.step_type}</div>
                          {!r.result.success && (
                            <div className="text-text-muted">
                              {r.result.reason} · {r.result.message || ""}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}


function ActionFields({
  step,
  actions,
  onChange,
}: {
  step: WorkflowStep;
  actions: WorkflowActionDef[];
  onChange: (config: Record<string, string>) => void;
}) {
  const def = actions.find((a) => a.type === step.type);
  if (!def) {
    return <div className="text-xs text-text-muted italic">Unknown action type</div>;
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-text-muted">{def.description}</div>
      {def.fields.map((field) => (
        <div key={field.name}>
          <label className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
            {field.label}
            {field.required && <span className="text-error ml-1">*</span>}
          </label>
          {field.type === "textarea" ? (
            <textarea
              value={step.config[field.name] || ""}
              onChange={(e) => onChange({ ...step.config, [field.name]: e.target.value })}
              rows={3}
              className="w-full mt-0.5 px-2.5 py-2 rounded-md bg-surface-lowest ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none font-mono"
              placeholder={field.help}
            />
          ) : (
            <input
              type="text"
              value={step.config[field.name] || ""}
              onChange={(e) => onChange({ ...step.config, [field.name]: e.target.value })}
              className="w-full mt-0.5 h-9 px-2.5 rounded-md bg-surface-lowest ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none font-mono"
              placeholder={field.help}
            />
          )}
          {field.help && <div className="text-[11px] text-text-muted mt-0.5">{field.help}</div>}
        </div>
      ))}
    </div>
  );
}


// flatten {a: {b: 1}} → ["a.b"]; used to show {{var}} hints
function flatten(obj: any, prefix = ""): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(obj || {})) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(out, flatten(v, path));
    } else {
      out[path] = v;
    }
  }
  return out;
}
