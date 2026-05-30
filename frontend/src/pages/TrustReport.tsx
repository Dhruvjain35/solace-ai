import { Suspense, lazy, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Loader2,
  Scale,
  ShieldCheck,
  Stethoscope,
} from "lucide-react";
import { getTrustReport, type TrustReport as TrustReportData } from "../lib/api";

// DEPS-006: recharts ships in its own lazily-loaded chunk, off the main bundle.
const CoverageChart = lazy(() => import("../components/ui/CoverageChart"));

const RISK_TIER_LABEL: Record<string, string> = {
  tier_1_high: "Tier 1 — High clinical risk",
  tier_2_moderate: "Tier 2 — Moderate clinical risk",
  tier_3_low: "Tier 3 — Low clinical risk",
};

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function SectionCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg bg-surface-lowest shadow-soft ring-1 ring-line p-5 sm:p-6">
      <h2 className="flex items-center gap-2 text-base font-semibold tracking-editorial text-ink">
        <span className="text-primary" aria-hidden>
          {icon}
        </span>
        {title}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

SectionCard.displayName = "SectionCard";

export default function TrustReport() {
  const [report, setReport] = useState<TrustReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getTrustReport()
      .then((data) => {
        if (active) {
          setReport(data);
          setError(null);
        }
      })
      .catch(() => {
        if (active) setError("Could not load the Trust Report. Please try again shortly.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="min-h-[100dvh] bg-surface-low">
      <header className="bg-primary-gradient text-white">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 py-10">
          <div className="flex items-center gap-2.5">
            <Stethoscope size={22} aria-hidden />
            <span className="text-lg font-semibold tracking-editorial">Solace</span>
            <span className="text-[11px] uppercase tracking-wider opacity-80 border-l border-white/30 pl-2.5 ml-1">
              Trust Report
            </span>
          </div>
          <h1 className="mt-5 text-2xl sm:text-3xl font-semibold tracking-editorial">
            How our clinical AI is governed, calibrated, and audited
          </h1>
          <p className="mt-3 max-w-2xl text-sm sm:text-base text-white/85">
            A public, aggregate view of model transparency, uncertainty calibration, fairness
            commitments, and how often clinicians accept the AI&rsquo;s suggestions. Aligned to
            HTI-1 DSI transparency requirements (45 CFR 170.315(b)(11)).
          </p>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-4 sm:px-6 py-8 space-y-6">
        {loading && (
          <div
            className="flex items-center justify-center gap-2 py-16 text-text-muted"
            role="status"
            aria-live="polite"
          >
            <Loader2 size={20} className="animate-spin" aria-hidden />
            <span>Loading the Trust Report&hellip;</span>
          </div>
        )}

        {!loading && error && (
          <div
            className="rounded-lg bg-error-container text-error p-4 text-sm flex items-start gap-2"
            role="alert"
          >
            <AlertTriangle size={18} className="shrink-0 mt-0.5" aria-hidden />
            <span>{error}</span>
          </div>
        )}

        {!loading && !error && report && (
          <>
            {/* Honest, prominent preliminary banner — never overclaim. */}
            {report.preliminary && (
              <div
                className="rounded-lg bg-warning-container text-ink p-4 sm:p-5 ring-1 ring-warning/30"
                role="note"
              >
                <div className="flex items-start gap-3">
                  <AlertTriangle size={20} className="shrink-0 mt-0.5 text-warning" aria-hidden />
                  <div>
                    <p className="font-semibold tracking-editorial">
                      Preliminary — synthetic validation cohort; real-world clinical calibration
                      pending
                    </p>
                    <p className="mt-1.5 text-sm text-text-muted">{report.disclaimer}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Model inventory */}
            <SectionCard title="Model inventory" icon={<ShieldCheck size={18} />}>
              <p className="text-sm text-text-muted">
                {report.model_inventory.count} AI surfaces in production, each with a published
                model card, risk tier, and human-in-the-loop requirement.
              </p>
              <ul className="mt-4 divide-y divide-line">
                {report.model_inventory.models.map((m) => (
                  <li key={m.id} className="py-2.5 flex items-baseline justify-between gap-4">
                    <div>
                      <span className="font-medium text-ink">{m.name}</span>
                      <span className="ml-2 text-xs text-text-muted">{m.version}</span>
                    </div>
                    <span className="shrink-0 text-xs rounded-sm bg-surface-high px-2 py-0.5 text-text-muted">
                      {m.risk_tier ? RISK_TIER_LABEL[m.risk_tier] ?? m.risk_tier : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </SectionCard>

            {/* Calibration + conformal coverage */}
            <SectionCard title="Uncertainty calibration (triage)" icon={<Gauge size={18} />}>
              <p className="text-sm text-text-muted">
                The triage ensemble emits a conformal prediction set per patient. We measure how
                often the true ESI level falls inside that set. Figures below are on a{" "}
                <strong className="text-ink">{report.calibration.provenance}</strong> &mdash; not
                real-world clinical outcomes.
              </p>

              {report.calibration.status === "available" &&
              report.calibration.empirical_coverage ? (
                <div className="mt-5">
                  <Suspense
                    fallback={
                      <div
                        className="flex items-center justify-center gap-2 h-[260px] text-text-muted"
                        role="status"
                        aria-live="polite"
                      >
                        <Loader2 size={18} className="animate-spin" aria-hidden />
                        <span>Loading chart&hellip;</span>
                      </div>
                    }
                  >
                    <CoverageChart
                      data={Object.entries(
                        report.calibration.empirical_coverage.by_esi,
                      ).map(([esi, coverage]) => ({ esi, coverage }))}
                      target={report.calibration.target_coverage}
                    />
                  </Suspense>

                  <dl className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
                    <div className="rounded-md bg-surface-low p-3">
                      <dt className="text-text-muted">Target coverage</dt>
                      <dd className="mt-0.5 font-semibold text-ink">
                        {report.calibration.target_coverage !== null
                          ? pct(report.calibration.target_coverage)
                          : "—"}
                      </dd>
                    </div>
                    <div className="rounded-md bg-surface-low p-3">
                      <dt className="text-text-muted">Overall (synthetic)</dt>
                      <dd className="mt-0.5 font-semibold text-ink">
                        {pct(report.calibration.empirical_coverage.overall)}
                      </dd>
                    </div>
                    <div className="rounded-md bg-surface-low p-3">
                      <dt className="text-text-muted">Avg. set size</dt>
                      <dd className="mt-0.5 font-semibold text-ink">
                        {report.calibration.empirical_coverage.avg_set_size.toFixed(2)}
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-3 text-xs text-text-muted">{report.calibration.note}</p>
                </div>
              ) : (
                <p className="mt-4 text-sm text-text-muted italic">{report.calibration.note}</p>
              )}
            </SectionCard>

            {/* Fairness */}
            <SectionCard title="Fairness &amp; bias audit" icon={<Scale size={18} />}>
              <p className="text-sm text-text-muted">{report.fairness.disclosure}</p>
              <ul className="mt-4 space-y-2.5">
                {report.fairness.models.map((m) => (
                  <li key={m.model_id} className="rounded-md bg-surface-low p-3 text-sm">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="font-medium text-ink">{m.name}</span>
                      <span className="shrink-0 text-xs text-text-muted">
                        {m.subgroup_audit_applicable
                          ? `subgroup audit: ${m.groups_audited.join(", ") || "—"}`
                          : "not a patient predictor"}
                      </span>
                    </div>
                    {m.equity_note && (
                      <p className="mt-1.5 text-xs text-text-muted">{m.equity_note}</p>
                    )}
                  </li>
                ))}
              </ul>
            </SectionCard>

            {/* Override acceptance */}
            <SectionCard
              title="Clinician override acceptance (live, aggregate)"
              icon={<CheckCircle2 size={18} />}
            >
              <p className="text-sm text-text-muted">
                Aggregate rates only across {report.override_acceptance.total_decisions} logged
                decisions. {report.override_acceptance.phi_note}
              </p>
              {Object.keys(report.override_acceptance.by_purpose).length === 0 ? (
                <p className="mt-4 text-sm text-text-muted italic">
                  No override decisions recorded yet in this environment.
                </p>
              ) : (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-sm border-collapse">
                    <caption className="sr-only">
                      AI suggestion acceptance, edit, and rejection rates by purpose
                    </caption>
                    <thead>
                      <tr className="text-left text-text-muted border-b border-line">
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Purpose
                        </th>
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Accept
                        </th>
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Edit
                        </th>
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Reject
                        </th>
                        <th scope="col" className="py-2 font-medium">
                          n
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(report.override_acceptance.by_purpose).map(([p, r]) => (
                        <tr key={p} className="border-b border-line last:border-0">
                          <td className="py-2 pr-4 text-ink">{p}</td>
                          <td className="py-2 pr-4">{pct(r.accept_rate)}</td>
                          <td className="py-2 pr-4">{pct(r.edit_rate)}</td>
                          <td className="py-2 pr-4">{pct(r.reject_rate)}</td>
                          <td className="py-2 text-text-muted">{r.total}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>

            <footer className="pt-2 pb-8 text-xs text-text-muted">
              <p>
                {report.framework} &middot; as of {report.as_of} &middot; scope:{" "}
                {report.scope}. This report is aggregate-only and contains no patient or clinician
                identifiable data.
              </p>
            </footer>
          </>
        )}
      </div>
    </main>
  );
}

TrustReport.displayName = "TrustReport";
