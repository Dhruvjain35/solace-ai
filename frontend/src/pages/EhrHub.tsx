import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  KeyRound,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
} from "lucide-react";
import { listEHRVendors, type EHRVendorOption } from "../lib/api";
import {
  buildEhrLaunchUrl,
  listEhrConfigs,
  listWorkspaces,
  type EhrConfig,
  type Workspace,
} from "../lib/api-ehr-config";
import { loadSession } from "../lib/session";
import VendorCard, { type VendorStatus } from "../components/clinician/ehr/VendorCard";
import ConfigPanel from "../components/clinician/ehr/ConfigPanel";
import SandboxCallout from "../components/clinician/ehr/SandboxCallout";

/**
 * EhrHub — the EHR Connector Hub.
 *
 * One place to see every vendor connection (SMART sandbox + configured Epic /
 * Oracle Cerner / Athenahealth clients), launch a SMART-on-FHIR sign-in, and
 * bind workspaces to their own vendor configs.
 */

type Fetch<T> = { data: T | null; loading: boolean; error: string | null };

function readError(e: unknown): string {
  const err = e as { response?: { data?: { detail?: string } }; message?: string };
  return err?.response?.data?.detail || err?.message || "Request failed";
}

function SkeletonCard() {
  return (
    <div className="bg-surface-lowest rounded-lg ring-1 ring-line p-4 animate-pulse" aria-hidden>
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-md bg-surface-low" />
        <div className="flex-1">
          <div className="h-3.5 w-28 bg-surface-low rounded" />
          <div className="h-3 w-36 bg-surface-low rounded mt-2" />
        </div>
      </div>
      <div className="h-3 w-full bg-surface-low rounded mt-4" />
      <div className="h-9 w-full bg-surface-low rounded mt-3" />
    </div>
  );
}

function FetchError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-md bg-error-container text-error text-sm px-3 py-2.5 flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 min-w-0">
        <AlertCircle className="w-4 h-4 shrink-0" aria-hidden />
        <span className="truncate">{message}</span>
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="shrink-0 inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/40 rounded"
      >
        <RefreshCw className="w-3.5 h-3.5" aria-hidden />
        Retry
      </button>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
      {children}
    </h2>
  );
}

export default function EhrHub() {
  const { hospitalId = "demo" } = useParams();
  const location = useLocation();
  const prefix = location.pathname.startsWith("/h/") ? "/h" : "";

  const [vendors, setVendors] = useState<Fetch<EHRVendorOption[]>>({
    data: null, loading: true, error: null,
  });
  const [workspaces, setWorkspaces] = useState<Fetch<Workspace[]>>({
    data: null, loading: true, error: null,
  });
  const [configs, setConfigs] = useState<Fetch<EhrConfig[]>>({
    data: null, loading: true, error: null,
  });

  const [panelOpen, setPanelOpen] = useState(false);
  const [panelVendor, setPanelVendor] = useState<string | null>(null);
  const [panelWorkspace, setPanelWorkspace] = useState<string | null>(null);

  const session = loadSession();
  const connectedVendor = session?.ehr_vendor || null;

  const loadVendors = useCallback(async () => {
    setVendors((s) => ({ ...s, loading: true, error: null }));
    try {
      setVendors({ data: await listEHRVendors(), loading: false, error: null });
    } catch (e: unknown) {
      setVendors({ data: null, loading: false, error: readError(e) });
    }
  }, []);

  const loadWs = useCallback(async () => {
    setWorkspaces((s) => ({ ...s, loading: true, error: null }));
    try {
      setWorkspaces({ data: await listWorkspaces(hospitalId), loading: false, error: null });
    } catch (e: unknown) {
      setWorkspaces({ data: null, loading: false, error: readError(e) });
    }
  }, [hospitalId]);

  const loadConfigs = useCallback(async () => {
    setConfigs((s) => ({ ...s, loading: true, error: null }));
    try {
      setConfigs({ data: await listEhrConfigs(hospitalId), loading: false, error: null });
    } catch (e: unknown) {
      setConfigs({ data: null, loading: false, error: readError(e) });
    }
  }, [hospitalId]);

  useEffect(() => {
    loadVendors();
    loadWs();
    loadConfigs();
  }, [loadVendors, loadWs, loadConfigs]);

  const configList = configs.data || [];
  const workspaceList = workspaces.data || [];
  const vendorList = vendors.data || [];
  const smartVendor = vendorList.find((v) => v.id === "smart") || null;

  const workspaceName = useCallback(
    (id: string) => workspaceList.find((w) => w.workspace_id === id)?.name || id,
    [workspaceList],
  );

  const bindingsByVendor = useMemo(() => {
    const map: Record<string, number> = {};
    for (const c of configList) map[c.vendor] = (map[c.vendor] || 0) + 1;
    return map;
  }, [configList]);

  const vendorStatus = (v: EHRVendorOption): VendorStatus => {
    if (connectedVendor === v.id) return "connected";
    if (v.sandbox) return "sandbox";
    if ((bindingsByVendor[v.id] || 0) > 0) return "configured";
    return "not-configured";
  };

  const launch = (vendorId: string, workspaceId?: string) => {
    const redirectUri = `${window.location.origin}/ehr/callback`;
    window.location.href = buildEhrLaunchUrl(vendorId, hospitalId, redirectUri, workspaceId);
  };

  const openPanel = (vendorId?: string | null, workspaceId?: string | null) => {
    setPanelVendor(vendorId || null);
    setPanelWorkspace(workspaceId || null);
    setPanelOpen(true);
  };

  return (
    <div className="min-h-screen bg-surface text-ink">
      <header className="bg-surface-lowest shadow-soft">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to={`${prefix}/${hospitalId}/clinician`}
            aria-label="Back to dashboard"
            className="w-9 h-9 rounded-md flex items-center justify-center text-text-muted hover:text-ink hover:bg-surface-low transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            <ArrowLeft className="w-5 h-5" aria-hidden />
          </Link>
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
              Solace interoperability
            </div>
            <div className="text-base font-bold tracking-tight">EHR connections</div>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto p-4 flex flex-col gap-5">
        <p className="text-sm text-text-muted -mb-1">
          Sign in through your EHR with SMART on FHIR, and bind each workspace to its own
          vendor connection — sandbox or production, public or confidential client.
        </p>

        {/* Sandbox callout ------------------------------------------------- */}
        {smartVendor && <SandboxCallout onConnect={() => launch(smartVendor.id)} />}

        {/* Vendor grid ------------------------------------------------------ */}
        <section className="flex flex-col gap-2.5" aria-label="EHR vendors">
          <SectionTitle>Vendors</SectionTitle>
          {vendors.error && <FetchError message={vendors.error} onRetry={loadVendors} />}
          {vendors.loading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </div>
          ) : vendorList.length === 0 && !vendors.error ? (
            <div className="bg-surface-lowest rounded-lg ring-1 ring-line p-4 text-sm text-text-muted">
              No EHR vendors are enabled for this deployment. Vendors appear here once a
              SMART client id is configured server-side.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {vendorList.map((v) => (
                <VendorCard
                  key={v.id}
                  vendor={v}
                  status={vendorStatus(v)}
                  bindingCount={bindingsByVendor[v.id] || 0}
                  onConnect={() => launch(v.id)}
                  onConfigure={() =>
                    openPanel(
                      v.id,
                      configList.find((c) => c.vendor === v.id)?.workspace_id || null,
                    )
                  }
                />
              ))}
            </div>
          )}
        </section>

        {/* Workspace bindings ------------------------------------------------ */}
        <section className="flex flex-col gap-2.5" aria-label="Workspace bindings">
          <div className="flex items-center justify-between gap-3">
            <SectionTitle>Workspace bindings</SectionTitle>
            <button
              type="button"
              onClick={() => openPanel(null, null)}
              disabled={workspaceList.length === 0}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-surface-lowest ring-1 ring-line text-ink text-xs font-semibold transition-all hover:bg-surface-low disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
            >
              <Plus className="w-3.5 h-3.5" aria-hidden />
              New binding
            </button>
          </div>

          {workspaces.error && <FetchError message={workspaces.error} onRetry={loadWs} />}
          {configs.error && <FetchError message={configs.error} onRetry={loadConfigs} />}

          {configs.loading || workspaces.loading ? (
            <div className="flex flex-col gap-2" aria-hidden>
              <div className="h-14 bg-surface-lowest ring-1 ring-line rounded-lg animate-pulse" />
              <div className="h-14 bg-surface-lowest ring-1 ring-line rounded-lg animate-pulse" />
            </div>
          ) : configList.length === 0 && !configs.error ? (
            <div className="bg-surface-lowest rounded-lg ring-1 ring-line p-4 text-sm text-text-muted">
              No workspace is bound to an EHR yet. A binding gives a department or clinic its
              own FHIR base URL, OAuth client, and scope set.
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {configList.map((c) => {
                const vendor = vendorList.find((v) => v.id === c.vendor);
                return (
                  <li
                    key={c.workspace_id}
                    className="bg-surface-lowest rounded-lg ring-1 ring-line px-3.5 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-2"
                  >
                    <span
                      className="h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ background: vendor?.color || "#94a3b8" }}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold text-ink truncate">
                        {workspaceName(c.workspace_id)}
                      </span>
                      <span className="block text-xs text-text-muted truncate">
                        {vendor?.label || c.vendor}
                        {c.label ? ` · ${c.label}` : ""}
                        {c.fhir_base_url ? ` · ${c.fhir_base_url}` : ""}
                      </span>
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low ring-1 ring-line text-text-muted">
                        SMART {c.smart_version}
                      </span>
                      {c.sandbox && (
                        <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low ring-1 ring-line text-text-muted">
                          Sandbox
                        </span>
                      )}
                      {c.confidential_client && (
                        <span
                          className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low ring-1 ring-line text-text-muted"
                          title="Confidential client — secret held in AWS Secrets Manager"
                        >
                          <KeyRound className="w-3 h-3" aria-hidden />
                          Confidential
                        </span>
                      )}
                      {c.status !== "active" && (
                        <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-warning-container text-warning">
                          {c.status}
                        </span>
                      )}
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      <button
                        type="button"
                        onClick={() => launch(c.vendor, c.workspace_id)}
                        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-white text-xs font-semibold transition-all hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
                      >
                        <Plug className="w-3.5 h-3.5" aria-hidden />
                        Connect
                      </button>
                      <button
                        type="button"
                        onClick={() => openPanel(c.vendor, c.workspace_id)}
                        aria-label={`Edit binding for ${workspaceName(c.workspace_id)}`}
                        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-surface-low ring-1 ring-line text-ink text-xs font-semibold transition-all hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
                      >
                        <Pencil className="w-3.5 h-3.5" aria-hidden />
                        Edit
                      </button>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </main>

      <ConfigPanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        hospitalId={hospitalId}
        workspaces={workspaceList}
        configs={configList}
        vendors={vendorList}
        initialWorkspaceId={panelWorkspace}
        initialVendor={panelVendor}
        onConfigsChange={(next) => setConfigs({ data: next, loading: false, error: null })}
      />
    </div>
  );
}
