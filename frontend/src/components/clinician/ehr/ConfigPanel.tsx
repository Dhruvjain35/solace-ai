import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { KeyRound, Loader2, Save, Trash2, X } from "lucide-react";
import type { EHRVendorOption } from "../../../lib/api";
import {
  deleteEhrConfig,
  patchEhrConfig,
  putEhrConfig,
  type EhrConfig,
  type EhrConfigInput,
  type Workspace,
} from "../../../lib/api-ehr-config";

/**
 * ConfigPanel — slide-over editor for one workspace's EHR binding. Optimistic
 * apply: the parent's config list updates immediately on save/delete, then is
 * reconciled with the server response — or rolled back on failure. Secrets
 * posture (COMP-007): only AWS Secrets Manager NAMES travel through this form;
 * inline secret values / PEMs are rejected server-side.
 */
type FormState = {
  vendor: string;
  label: string;
  fhir_base_url: string;
  authorize_url: string;
  token_url: string;
  client_id: string;
  smart_version: string;
  scopes: string; // whitespace/newline-separated in the UI
  scopes_v2: string;
  sandbox: boolean;
  status: string;
  client_secret_ref: string;
  private_key_ref: string;
  kid: string;
};

const EMPTY_FORM: FormState = {
  vendor: "smart",
  label: "",
  fhir_base_url: "",
  authorize_url: "",
  token_url: "",
  client_id: "",
  smart_version: "v2",
  scopes: "",
  scopes_v2: "",
  sandbox: true,
  status: "active",
  client_secret_ref: "",
  private_key_ref: "",
  kid: "",
};

const inputClass =
  "w-full h-9 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-2 focus:ring-primary text-sm text-ink outline-none transition-all";
const textareaClass = inputClass.replace("h-9 px-3", "px-3 py-2");

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
      {children}
    </span>
  );
}

const readError = (e: unknown): string => {
  const err = e as { response?: { data?: { detail?: string } }; message?: string };
  return err?.response?.data?.detail || err?.message || "Request failed";
};

function toForm(cfg: EhrConfig | undefined, fallbackVendor: string): FormState {
  if (!cfg) return { ...EMPTY_FORM, vendor: fallbackVendor };
  return {
    vendor: cfg.vendor || fallbackVendor,
    label: cfg.label || "",
    fhir_base_url: cfg.fhir_base_url || "",
    authorize_url: cfg.authorize_url || "",
    token_url: cfg.token_url || "",
    client_id: cfg.client_id || "",
    smart_version: cfg.smart_version || "v2",
    scopes: (cfg.scopes || []).join("\n"),
    scopes_v2: (cfg.scopes_v2 || []).join("\n"),
    sandbox: cfg.sandbox ?? true,
    status: cfg.status || "active",
    client_secret_ref: cfg.client_secret_ref || "",
    private_key_ref: cfg.private_key_ref || "",
    kid: cfg.kid || "",
  };
}

function splitScopes(raw: string): string[] {
  return raw.split(/\s+/).map((s) => s.trim()).filter(Boolean);
}

/** Build the request body. Empty strings are omitted — the backend defaults
 *  endpoint URLs from the vendor template, and PATCH cannot un-set a field
 *  (replace the binding to clear one). */
function toBody(form: FormState): EhrConfigInput {
  const body: EhrConfigInput = {
    vendor: form.vendor,
    smart_version: form.smart_version,
    sandbox: form.sandbox,
    status: form.status,
    scopes: splitScopes(form.scopes),
    scopes_v2: splitScopes(form.scopes_v2),
  };
  const strings: [keyof EhrConfigInput, string][] = [
    ["label", form.label],
    ["fhir_base_url", form.fhir_base_url],
    ["authorize_url", form.authorize_url],
    ["token_url", form.token_url],
    ["client_id", form.client_id],
    ["client_secret_ref", form.client_secret_ref],
    ["private_key_ref", form.private_key_ref],
    ["kid", form.kid],
  ];
  for (const [key, value] of strings) {
    const v = value.trim();
    if (v) (body as Record<string, unknown>)[key] = v;
  }
  return body;
}

function upsert(list: EhrConfig[], cfg: EhrConfig): EhrConfig[] {
  const idx = list.findIndex((c) => c.workspace_id === cfg.workspace_id);
  if (idx === -1) return [...list, cfg];
  const next = list.slice();
  next[idx] = cfg;
  return next;
}

export default function ConfigPanel({
  open,
  onClose,
  hospitalId,
  workspaces,
  configs,
  vendors,
  initialWorkspaceId,
  initialVendor,
  onConfigsChange,
}: {
  open: boolean;
  onClose: () => void;
  hospitalId: string;
  workspaces: Workspace[];
  configs: EhrConfig[];
  vendors: EHRVendorOption[];
  initialWorkspaceId?: string | null;
  initialVendor?: string | null;
  onConfigsChange: (next: EhrConfig[]) => void;
}) {
  const [workspaceId, setWorkspaceId] = useState("");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteArmed, setDeleteArmed] = useState(false);

  const existing = useMemo(
    () => configs.find((c) => c.workspace_id === workspaceId),
    [configs, workspaceId],
  );

  // Seed selection + form whenever the panel opens or the target workspace changes.
  useEffect(() => {
    if (!open) return;
    const ws = initialWorkspaceId || workspaces[0]?.workspace_id || "";
    setWorkspaceId(ws);
    setError(null);
    setDeleteArmed(false);
  }, [open, initialWorkspaceId, workspaces]);

  useEffect(() => {
    if (!open) return;
    setForm(toForm(existing, initialVendor || "smart"));
    setDeleteArmed(false);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, workspaceId]);

  // Escape closes the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));

  const save = useCallback(async () => {
    if (!workspaceId || busy) return;
    setBusy(true);
    setError(null);
    const snapshot = configs;
    const body = toBody(form);
    // Optimistic apply — merge the form over the existing record immediately.
    const optimistic: EhrConfig = {
      hospital_id: hospitalId,
      workspace_id: workspaceId,
      vendor: form.vendor,
      fhir_base_url: form.fhir_base_url.trim(),
      authorize_url: form.authorize_url.trim(),
      token_url: form.token_url.trim(),
      client_id: form.client_id.trim(),
      scopes: splitScopes(form.scopes),
      scopes_v2: splitScopes(form.scopes_v2),
      smart_version: form.smart_version,
      label: form.label.trim(),
      sandbox: form.sandbox,
      status: form.status,
      confidential_client: Boolean(form.client_secret_ref.trim() || form.private_key_ref.trim()),
      client_secret_ref: form.client_secret_ref.trim(),
      private_key_ref: form.private_key_ref.trim(),
      kid: form.kid.trim(),
      ...(existing ? { created_at: existing.created_at, created_by: existing.created_by } : {}),
    };
    onConfigsChange(upsert(snapshot, optimistic));
    try {
      const saved = existing
        ? await patchEhrConfig(hospitalId, workspaceId, body)
        : await putEhrConfig(hospitalId, workspaceId, body);
      onConfigsChange(upsert(snapshot, saved));
      onClose();
    } catch (e: unknown) {
      onConfigsChange(snapshot); // rollback
      setError(readError(e));
    } finally {
      setBusy(false);
    }
  }, [hospitalId, workspaceId, form, configs, existing, busy, onConfigsChange, onClose]);

  const remove = useCallback(async () => {
    if (!workspaceId || !existing || busy) return;
    if (!deleteArmed) {
      setDeleteArmed(true);
      return;
    }
    setBusy(true);
    setError(null);
    const snapshot = configs;
    onConfigsChange(snapshot.filter((c) => c.workspace_id !== workspaceId));
    try {
      await deleteEhrConfig(hospitalId, workspaceId);
      onClose();
    } catch (e: unknown) {
      onConfigsChange(snapshot); // rollback
      setError(readError(e));
      setDeleteArmed(false);
    } finally {
      setBusy(false);
    }
  }, [hospitalId, workspaceId, existing, deleteArmed, configs, busy, onConfigsChange, onClose]);

  const vendorOptions = useMemo(() => {
    const ids = vendors.map((v) => v.id);
    return form.vendor && !ids.includes(form.vendor)
      ? [...vendors, { id: form.vendor, label: form.vendor, color: "#64748b", sandbox: false }]
      : vendors;
  }, [vendors, form.vendor]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 bg-ink/30 z-40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Workspace EHR configuration"
            className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-surface-lowest shadow-card flex flex-col"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.22, ease: "easeOut" }}
          >
            <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-line">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                  Workspace EHR binding
                </div>
                <div className="text-base font-bold tracking-tight text-ink">
                  {existing ? "Edit connection" : "New connection"}
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close panel"
                className="w-9 h-9 rounded-md flex items-center justify-center text-text-muted hover:text-ink hover:bg-surface-low transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              >
                <X className="w-5 h-5" aria-hidden />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
              <label className="flex flex-col gap-1.5">
                <FieldLabel>Workspace</FieldLabel>
                <select
                  value={workspaceId}
                  onChange={(e) => setWorkspaceId(e.target.value)}
                  className={inputClass}
                >
                  {workspaces.length === 0 && <option value="">No workspaces available</option>}
                  {workspaces.map((w) => (
                    <option key={w.workspace_id} value={w.workspace_id}>
                      {w.name}
                      {configs.some((c) => c.workspace_id === w.workspace_id) ? " — bound" : ""}
                    </option>
                  ))}
                </select>
              </label>

              <div className="grid grid-cols-2 gap-2.5">
                <label className="flex flex-col gap-1.5">
                  <FieldLabel>Vendor</FieldLabel>
                  <select
                    value={form.vendor}
                    onChange={(e) => set({ vendor: e.target.value })}
                    className={inputClass}
                  >
                    {vendorOptions.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5">
                  <FieldLabel>SMART version</FieldLabel>
                  <select
                    value={form.smart_version}
                    onChange={(e) => set({ smart_version: e.target.value })}
                    className={inputClass}
                  >
                    <option value="v2">v2 (.cruds scopes)</option>
                    <option value="v1">v1 (.read scopes)</option>
                  </select>
                </label>
              </div>

              <label className="flex flex-col gap-1.5">
                <FieldLabel>Label</FieldLabel>
                <input
                  value={form.label}
                  onChange={(e) => set({ label: e.target.value })}
                  placeholder="ED — Epic production"
                  className={inputClass}
                />
              </label>

              {(["fhir_base_url", "authorize_url", "token_url"] as const).map((k) => (
                <label key={k} className="flex flex-col gap-1.5">
                  <FieldLabel>{k.replace(/_/g, " ")}</FieldLabel>
                  <input
                    value={form[k]}
                    onChange={(e) => set({ [k]: e.target.value } as Partial<FormState>)}
                    placeholder="https://… (blank = vendor default)"
                    className={inputClass}
                  />
                </label>
              ))}

              <label className="flex flex-col gap-1.5">
                <FieldLabel>OAuth client id</FieldLabel>
                <input
                  value={form.client_id}
                  onChange={(e) => set({ client_id: e.target.value })}
                  className={inputClass}
                />
              </label>

              <label className="flex flex-col gap-1.5">
                <FieldLabel>Scopes — SMART v1 (one per line)</FieldLabel>
                <textarea
                  value={form.scopes}
                  onChange={(e) => set({ scopes: e.target.value })}
                  rows={3}
                  className={`${textareaClass} font-mono text-xs`}
                  placeholder={"patient/Patient.read\nlaunch openid fhirUser"}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <FieldLabel>Scopes — SMART v2 (one per line)</FieldLabel>
                <textarea
                  value={form.scopes_v2}
                  onChange={(e) => set({ scopes_v2: e.target.value })}
                  rows={3}
                  className={`${textareaClass} font-mono text-xs`}
                  placeholder={"patient/Patient.cruds\nlaunch openid fhirUser"}
                />
              </label>

              <div className="flex items-center gap-5">
                <label className="inline-flex items-center gap-2 text-sm text-ink cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.sandbox}
                    onChange={(e) => set({ sandbox: e.target.checked })}
                    className="h-4 w-4 accent-primary"
                  />
                  Sandbox (non-PHI)
                </label>
                <label className="inline-flex items-center gap-2 text-sm text-ink">
                  <span className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                    Status
                  </span>
                  <select
                    value={form.status}
                    onChange={(e) => set({ status: e.target.value })}
                    className={`${inputClass} w-auto`}
                  >
                    <option value="active">active</option>
                    <option value="disabled">disabled</option>
                  </select>
                </label>
              </div>

              <div className="rounded-md bg-surface-low ring-1 ring-line p-3">
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                  <KeyRound className="w-3.5 h-3.5" aria-hidden />
                  Confidential client (optional)
                </div>
                <p className="text-xs text-text-muted mt-1.5">
                  Enter AWS Secrets Manager <span className="font-semibold text-ink">names</span>,
                  not values. The secret itself stays in Secrets Manager and is fetched server-side
                  at token time — pasting a raw client secret or PEM here is rejected.
                </p>
                {([
                  ["client_secret_ref", "client secret ref", "solace/ehr/epic-client-secret"],
                  ["private_key_ref", "private key ref (RS384)", "solace/ehr/epic-signing-key"],
                  ["kid", "kid", ""],
                ] as const).map(([key, label, placeholder]) => (
                  <label key={key} className="flex flex-col gap-1.5 mt-2.5">
                    <FieldLabel>{label}</FieldLabel>
                    <input
                      value={form[key]}
                      onChange={(e) => set({ [key]: e.target.value } as Partial<FormState>)}
                      placeholder={placeholder}
                      className={`${inputClass} font-mono text-xs`}
                    />
                  </label>
                ))}
              </div>

              {error && (
                <div className="rounded-md bg-error-container text-error text-sm px-3 py-2.5">
                  {error}
                </div>
              )}
            </div>

            <div className="px-4 py-3 border-t border-line flex items-center gap-2">
              <button
                type="button"
                onClick={save}
                disabled={busy || !workspaceId}
                className="flex-1 h-10 inline-flex items-center justify-center gap-1.5 rounded-md bg-primary text-white text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
              >
                {busy ? (
                  <Loader2 className="w-4 h-4 animate-spin" aria-hidden />
                ) : (
                  <Save className="w-4 h-4" aria-hidden />
                )}
                {existing ? "Save changes" : "Create binding"}
              </button>
              {existing && (
                <button
                  type="button"
                  onClick={remove}
                  disabled={busy}
                  className={`h-10 px-3 inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-semibold ring-1 transition-all disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/40 focus-visible:ring-offset-2 ${
                    deleteArmed
                      ? "bg-error-container text-error ring-error/30"
                      : "bg-surface-lowest text-error ring-line hover:bg-error-container"
                  }`}
                >
                  <Trash2 className="w-4 h-4" aria-hidden />
                  {deleteArmed ? "Confirm delete" : "Delete"}
                </button>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
