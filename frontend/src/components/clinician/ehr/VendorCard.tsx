import { CheckCircle2, FlaskConical, Plug, Settings2 } from "lucide-react";
import type { EHRVendorOption } from "../../../lib/api";

/**
 * VendorCard — one EHR vendor in the connector grid.
 *
 * The tile is a neutral monogram (vendor accent color from the API + initials),
 * deliberately NOT a copyrighted vendor logo. Capability chips describe what the
 * connection supports; the badge reflects the live connection state.
 */

export type VendorStatus = "connected" | "sandbox" | "configured" | "not-configured";

/** Two-letter monogram from the vendor label: "Oracle Cerner" → "OC". */
function monogram(label: string): string {
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return (label.slice(0, 2) || "??").toUpperCase();
}

const CAPABILITIES = ["SMART on FHIR R4", "v2 scopes", "Write-back"];

function StatusBadge({ status }: { status: VendorStatus }) {
  if (status === "connected") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low text-success">
        <CheckCircle2 className="w-3 h-3 shrink-0" aria-hidden />
        Connected
      </span>
    );
  }
  if (status === "sandbox") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low text-text-muted">
        <FlaskConical className="w-3 h-3 shrink-0" aria-hidden />
        Sandbox
      </span>
    );
  }
  if (status === "configured") {
    return (
      <span className="inline-flex items-center text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low text-ink">
        Configured
      </span>
    );
  }
  return (
    <span className="inline-flex items-center text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low text-text-muted">
      Not configured
    </span>
  );
}

export default function VendorCard({
  vendor,
  status,
  bindingCount,
  onConnect,
  onConfigure,
}: {
  vendor: EHRVendorOption;
  status: VendorStatus;
  /** Workspaces bound to this vendor (shown when > 0). */
  bindingCount: number;
  onConnect: () => void;
  onConfigure: () => void;
}) {
  return (
    <div className="bg-surface-lowest rounded-lg ring-1 ring-line p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <span
            className="h-10 w-10 rounded-md shrink-0 flex items-center justify-center text-white text-sm font-bold"
            style={{ background: vendor.color }}
            aria-hidden
          >
            {monogram(vendor.label)}
          </span>
          <div className="min-w-0">
            <div className="text-sm font-bold tracking-tight text-ink truncate">
              {vendor.label}
            </div>
            <div className="text-xs text-text-muted">
              {bindingCount > 0
                ? `${bindingCount} workspace ${bindingCount === 1 ? "binding" : "bindings"}`
                : "No workspace bindings"}
            </div>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {CAPABILITIES.map((cap) => (
          <span
            key={cap}
            className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-surface-low ring-1 ring-line text-text-muted"
          >
            {cap}
          </span>
        ))}
      </div>

      <div className="flex gap-2 mt-auto">
        <button
          type="button"
          onClick={onConnect}
          className="flex-1 h-9 inline-flex items-center justify-center gap-1.5 rounded-md bg-primary text-white text-sm font-semibold transition-all hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
        >
          <Plug className="w-3.5 h-3.5" aria-hidden />
          {status === "connected" ? "Reconnect" : "Connect"}
        </button>
        <button
          type="button"
          onClick={onConfigure}
          className="flex-1 h-9 inline-flex items-center justify-center gap-1.5 rounded-md bg-surface-low ring-1 ring-line text-ink text-sm font-semibold transition-all hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
        >
          <Settings2 className="w-3.5 h-3.5" aria-hidden />
          Configure
        </button>
      </div>
    </div>
  );
}
