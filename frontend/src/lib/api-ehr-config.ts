/**
 * EHR Connector Hub — typed client for per-workspace EHR bindings.
 *
 * Mirrors backend/routers/ehr_config.py + services/ehr_config._public_view:
 *   - GET    /api/{hospitalId}/ehr-configs                              → { configs }
 *   - GET    /api/{hospitalId}/workspaces/{workspaceId}/ehr-config      → EhrConfig
 *   - PUT    /api/{hospitalId}/workspaces/{workspaceId}/ehr-config      → EhrConfig
 *   - PATCH  /api/{hospitalId}/workspaces/{workspaceId}/ehr-config      → EhrConfig
 *   - DELETE /api/{hospitalId}/workspaces/{workspaceId}/ehr-config      → { deleted }
 *   - GET    /api/{hospitalId}/workspaces                               → { workspaces }
 *
 * Secrets posture (COMP-007): `client_secret_ref` / `private_key_ref` are AWS
 * Secrets Manager NAMES — pointers only. Secret values and inline PEMs are
 * rejected server-side and never appear in any response here.
 */
import { api } from "./api";

// ---- Types mirroring backend public views -----------------------------------------

export type Workspace = {
  workspace_id: string;
  name: string;
  description?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
};

export type EhrConfig = {
  hospital_id: string;
  workspace_id: string;
  vendor: string; // "smart" | "epic" | "cerner" | "athena" | custom
  fhir_base_url: string;
  authorize_url: string;
  token_url: string;
  client_id: string;
  scopes: string[]; // SMART v1 (.read) tokens
  scopes_v2: string[]; // SMART v2 (.cruds) tokens
  smart_version: string; // "v1" | "v2"
  label: string;
  sandbox: boolean;
  status: string; // "active" | "disabled"
  confidential_client: boolean;
  client_secret_ref: string; // Secrets Manager name — never a value
  private_key_ref: string; // Secrets Manager name — never a PEM
  kid: string;
  created_at?: string | null;
  created_by?: string | null;
  updated_at?: string | null;
};

/** Create/replace + patch body. All fields optional; vendor required on first create. */
export type EhrConfigInput = Partial<{
  vendor: string;
  fhir_base_url: string;
  authorize_url: string;
  token_url: string;
  client_id: string;
  scopes: string[];
  scopes_v2: string[];
  smart_version: string;
  label: string;
  sandbox: boolean;
  status: string;
  client_secret_ref: string;
  private_key_ref: string;
  kid: string;
}>;

// ---- Workspaces --------------------------------------------------------------------

export async function listWorkspaces(hospitalId: string): Promise<Workspace[]> {
  const { data } = await api.get<{ workspaces: Workspace[] }>(
    `/api/${hospitalId}/workspaces`,
  );
  return data.workspaces || [];
}

// ---- EHR configs -------------------------------------------------------------------

export async function listEhrConfigs(hospitalId: string): Promise<EhrConfig[]> {
  const { data } = await api.get<{ configs: EhrConfig[] }>(
    `/api/${hospitalId}/ehr-configs`,
  );
  return data.configs || [];
}

export async function getEhrConfig(
  hospitalId: string,
  workspaceId: string,
): Promise<EhrConfig> {
  const { data } = await api.get<EhrConfig>(
    `/api/${hospitalId}/workspaces/${workspaceId}/ehr-config`,
  );
  return data;
}

export async function putEhrConfig(
  hospitalId: string,
  workspaceId: string,
  body: EhrConfigInput,
): Promise<EhrConfig> {
  const { data } = await api.put<EhrConfig>(
    `/api/${hospitalId}/workspaces/${workspaceId}/ehr-config`,
    body,
  );
  return data;
}

export async function patchEhrConfig(
  hospitalId: string,
  workspaceId: string,
  body: EhrConfigInput,
): Promise<EhrConfig> {
  const { data } = await api.patch<EhrConfig>(
    `/api/${hospitalId}/workspaces/${workspaceId}/ehr-config`,
    body,
  );
  return data;
}

export async function deleteEhrConfig(
  hospitalId: string,
  workspaceId: string,
): Promise<{ deleted: boolean; workspace_id: string }> {
  const { data } = await api.delete<{ deleted: boolean; workspace_id: string }>(
    `/api/${hospitalId}/workspaces/${workspaceId}/ehr-config`,
  );
  return data;
}

// ---- SMART launch ------------------------------------------------------------------

/**
 * OAuth launch URL — the browser navigates here and the backend 302s to the
 * vendor's authorize endpoint. `redirectUri` must be `${origin}/ehr/callback`
 * (allowlisted; pages/EHRCallback.tsx completes the exchange). Passing a
 * `workspaceId` routes the launch through that workspace's EHR binding.
 */
export function buildEhrLaunchUrl(
  vendor: string,
  hospitalId: string,
  redirectUri: string,
  workspaceId?: string,
): string {
  const base =
    import.meta.env.VITE_API_BASE_URL && import.meta.env.VITE_API_BASE_URL !== ""
      ? import.meta.env.VITE_API_BASE_URL
      : "";
  const qs = new URLSearchParams({
    vendor,
    hospital_id: hospitalId,
    redirect_uri: redirectUri,
  });
  if (workspaceId) qs.set("workspace_id", workspaceId);
  return `${base}/api/auth/ehr/launch?${qs.toString()}`;
}
