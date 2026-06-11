import { ArrowRight, FlaskConical } from "lucide-react";

/**
 * SandboxCallout — one-click path into the SMART Health IT public sandbox.
 *
 * The "smart" vendor needs no credentials, so this is the zero-friction way to
 * see the whole launch → callback → connected-badge loop before binding a real
 * Epic / Oracle Cerner / Athenahealth client.
 */
export default function SandboxCallout({ onConnect }: { onConnect: () => void }) {
  return (
    <div className="bg-surface-lowest rounded-lg ring-1 ring-line p-4 flex flex-col sm:flex-row sm:items-center gap-3">
      <div className="flex items-start gap-3 flex-1 min-w-0">
        <span className="h-9 w-9 rounded-md bg-surface-low ring-1 ring-line shrink-0 flex items-center justify-center">
          <FlaskConical className="w-5 h-5 text-primary" aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="text-sm font-bold tracking-tight text-ink">
            Try it now with the SMART Health IT sandbox
          </div>
          <p className="text-xs text-text-muted mt-0.5">
            No credentials needed — a public R4 sandbox with synthetic patients. Run the full
            SMART on FHIR launch and come back connected.
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={onConnect}
        className="shrink-0 h-9 px-4 inline-flex items-center justify-center gap-1.5 rounded-md bg-primary text-white text-sm font-semibold transition-all hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
      >
        Connect sandbox
        <ArrowRight className="w-3.5 h-3.5" aria-hidden />
      </button>
    </div>
  );
}
