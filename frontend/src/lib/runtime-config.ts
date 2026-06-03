/**
 * Runtime config fetched from /config.json at app boot.
 *
 * Baked env vars (VITE_API_BASE_URL / VITE_PUBLIC_URL) remain the fallback,
 * but config.json wins if present. This means changing the API URL no longer
 * requires a full bundle rebuild — just redeploy config.json via Amplify.
 */
import { api } from "./api";

export type RuntimeConfig = {
  apiBaseUrl: string;
  publicUrl: string;
};

let cached: RuntimeConfig | null = null;

export function getRuntimeConfig(): RuntimeConfig {
  if (cached) return cached;
  cached = {
    apiBaseUrl: import.meta.env.VITE_API_BASE_URL || "",
    publicUrl: import.meta.env.VITE_PUBLIC_URL || "",
  };
  return cached;
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  try {
    const r = await fetch("/config.json", { cache: "no-store" });
    if (r.ok) {
      const j = await r.json();
      // In dev, force a relative API base so calls go through the Vite proxy
      // (vite.config.ts) instead of hitting the prod API cross-origin — the
      // latter is CORS-blocked from localhost. In prod we honor config.json.
      const apiBaseUrl = import.meta.env.DEV
        ? ""
        : (j.apiBaseUrl ?? import.meta.env.VITE_API_BASE_URL ?? "");
      cached = {
        apiBaseUrl,
        publicUrl: j.publicUrl ?? import.meta.env.VITE_PUBLIC_URL ?? "",
      };
      // Override axios baseURL so existing code in api.ts picks up the runtime value.
      api.defaults.baseURL = cached.apiBaseUrl;
      return cached;
    }
  } catch {
    /* ignore, fall through to env-var defaults */
  }
  return getRuntimeConfig();
}
