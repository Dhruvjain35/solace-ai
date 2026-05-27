import { useMemo, useState } from "react";
import {
  Stethoscope,
  AlertTriangle,
  Loader2,
  Sparkles,
  ShieldAlert,
  Target,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import { DifferentialPanel } from "../../clinician/DifferentialPanel";
import { WorkupPanel } from "../../clinician/WorkupPanel";
import { DispositionPanel } from "../../clinician/DispositionPanel";
import { ddxV2 } from "../../../lib/api";
import type { DdxResult } from "../../../lib/api";

/** Map an enhanced DdxResult weight to the panel's likelihood bucket. */
function weightToLikelihood(weight: number): "high" | "moderate" | "low" {
  if (weight >= 0.66) return "high";
  if (weight >= 0.33) return "moderate";
  return "low";
}

export default function ReasoningTab() {
  const { hospitalId, patient, loading, error } = usePatientWorkspace();

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [ddx, setDdx] = useState<DdxResult | null>(null);

  // The differential the panel renders: prefer a freshly-run enhanced result,
  // otherwise fall back to whatever the patient record already carries.
  const differential = useMemo(() => {
    if (ddx) {
      return ddx.differential.map((d) => ({
        diagnosis: d.diagnosis,
        icd10: d.icd10,
        likelihood: weightToLikelihood(d.weight),
        rule_in: d.rule_in,
        rule_out: d.rule_out,
        must_not_miss: d.must_not_miss,
      }));
    }
    return patient?.differential ?? [];
  }, [ddx, patient]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={22} className="animate-spin text-text-muted" aria-hidden="true" />
      </div>
    );
  }

  if (error || !patient) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <AlertTriangle size={26} className="mx-auto mb-3 text-error" aria-hidden="true" />
          <h2 className="text-lg font-bold tracking-tight">Clinical Reasoning</h2>
          <p className="text-text-muted text-sm mt-1">
            {error || "Patient record is unavailable."}
          </p>
        </div>
      </div>
    );
  }

  const hasDifferential = differential.length > 0;
  const hasWorkup =
    !!patient.workup_orders &&
    (patient.workup_orders.labs?.length > 0 ||
      patient.workup_orders.imaging?.length > 0 ||
      patient.workup_orders.monitoring?.length > 0 ||
      patient.workup_orders.consults?.length > 0);
  const hasDisposition = !!patient.disposition && !!patient.disposition.disposition;

  async function runReasoning() {
    if (!patient) return;
    setRunning(true);
    setRunError(null);
    try {
      const result = await ddxV2(hospitalId, {
        transcript: patient.transcript || "",
        medical_info: patient.medical_info ?? undefined,
      });
      setDdx(result);
    } catch (e: any) {
      setRunError(
        e?.response?.data?.detail || e?.message || "Could not generate clinical reasoning.",
      );
    } finally {
      setRunning(false);
    }
  }

  const canRun = !!(patient.transcript && patient.transcript.trim().length > 0);

  return (
    <div className="flex flex-col gap-5 max-w-3xl mx-auto py-2">
      {/* Header + run action */}
      <div className="bg-surface-lowest rounded-xl shadow-card p-4 flex items-start gap-3">
        <div className="rounded-lg bg-primary/10 p-2 shrink-0">
          <Stethoscope size={18} className="text-primary" aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-base font-bold tracking-tight">Clinical Reasoning</h2>
          <p className="text-text-muted text-[13px] mt-0.5 leading-snug">
            Ranked differential, suggested workup, and disposition for {patient.name}.
            Derived from the intake transcript — nothing to re-enter.
          </p>
          <button
            type="button"
            onClick={runReasoning}
            disabled={running || !canRun}
            className="mt-3 inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-[13px] font-semibold bg-primary text-white transition-colors hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {running ? (
              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles size={14} aria-hidden="true" />
            )}
            {running
              ? "Generating…"
              : ddx
                ? "Re-run reasoning"
                : "Run reasoning"}
          </button>
          {!canRun && (
            <p className="text-text-muted text-[11px] mt-1.5">
              No intake transcript on file — reasoning needs the patient narrative.
            </p>
          )}
          {runError && (
            <p className="text-error text-[12px] mt-1.5" role="alert">
              {runError}
            </p>
          )}
        </div>
      </div>

      {/* Don't-miss red flags (enhanced run only) */}
      {ddx && ddx.red_flags.length > 0 && (
        <section className="bg-error/5 border border-error/30 rounded-xl p-4">
          <div className="flex items-center gap-1.5 mb-2">
            <ShieldAlert size={14} className="text-error" aria-hidden="true" />
            <div className="text-[11px] uppercase tracking-[0.14em] text-error font-semibold">
              Don't-miss red flags
            </div>
          </div>
          <ul className="flex flex-col gap-1.5">
            {ddx.red_flags.map((rf, i) => (
              <li key={i} className="flex items-center gap-2 text-[13px] text-ink">
                <AlertTriangle size={12} className="text-error shrink-0" aria-hidden="true" />
                <span className="font-medium">{rf.diagnosis}</span>
                {rf.icd10 && (
                  <span className="text-[10px] font-mono text-text-muted">{rf.icd10}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Conformal prediction sets (enhanced run only) */}
      {ddx && (ddx.conformal.set_90.length > 0 || ddx.conformal.set_95.length > 0) && (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-4">
          <div className="flex items-center gap-1.5 mb-2">
            <Target size={14} className="text-primary" aria-hidden="true" />
            <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold">
              Conformal prediction sets
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              { label: "90% coverage", items: ddx.conformal.set_90 },
              { label: "95% coverage", items: ddx.conformal.set_95 },
            ].map((set) => (
              <div key={set.label}>
                <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">
                  {set.label}
                </div>
                {set.items.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {set.items.map((dx, j) => (
                      <span
                        key={j}
                        className="inline-flex items-center px-2 h-6 rounded-md text-[12px] font-medium bg-surface-low text-ink"
                      >
                        {dx}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-[12px] text-text-muted italic">No entries</span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Differential diagnosis */}
      {hasDifferential ? (
        <DifferentialPanel entries={differential} />
      ) : (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-5 text-center">
          <p className="text-text-muted text-[13px]">
            No differential on file. Run reasoning to generate one.
          </p>
        </section>
      )}

      {/* Suggested workup */}
      {hasWorkup ? (
        <WorkupPanel orders={patient.workup_orders} />
      ) : (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-5 text-center">
          <p className="text-text-muted text-[13px]">No workup order set on file.</p>
        </section>
      )}

      {/* Disposition */}
      {hasDisposition ? (
        <DispositionPanel disposition={patient.disposition} />
      ) : (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-5 text-center">
          <p className="text-text-muted text-[13px]">No disposition recommendation on file.</p>
        </section>
      )}
    </div>
  );
}

ReasoningTab.displayName = "ReasoningTab";
