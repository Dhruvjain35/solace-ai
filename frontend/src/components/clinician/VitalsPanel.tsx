import { useState } from "react";
import { Activity, Info, Loader2, Sparkles } from "lucide-react";
import { refineTriage } from "../../lib/api";
import type { RefinedTriage, Vitals } from "../../types";

type Props = {
  hospitalId: string;
  patientId: string;
  pin: string;
  existing?: RefinedTriage | null;
  onRefined?: (r: RefinedTriage, v: Vitals) => void;
};

const FIELDS: { key: keyof Vitals; label: string; placeholder: string; step?: string }[] = [
  { key: "heart_rate", label: "Heart rate (bpm)", placeholder: "80", step: "1" },
  { key: "systolic_bp", label: "Systolic BP", placeholder: "120", step: "1" },
  { key: "diastolic_bp", label: "Diastolic BP", placeholder: "80", step: "1" },
  { key: "respiratory_rate", label: "Resp. rate", placeholder: "16", step: "1" },
  { key: "temperature_c", label: "Temp (°C)", placeholder: "37.0", step: "0.1" },
  { key: "spo2", label: "SpO₂ (%)", placeholder: "98", step: "1" },
  { key: "gcs_total", label: "GCS (3–15)", placeholder: "15", step: "1" },
  { key: "pain_score", label: "Pain (0–10)", placeholder: "3", step: "1" },
];

export function VitalsPanel({ hospitalId, patientId, pin, existing, onRefined }: Props) {
  const [vitals, setVitals] = useState<Vitals>({});
  const [mentalStatus, setMentalStatus] = useState<string>("alert");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RefinedTriage | null>(existing ?? null);

  function update<K extends keyof Vitals>(key: K, raw: string) {
    const num = raw === "" ? null : Number(raw);
    setVitals((v) => ({ ...v, [key]: isNaN(num as number) ? null : num }));
  }

  async function submit() {
    setLoading(true);
    setError(null);
    try {
      const payload: Vitals = { ...vitals, mental_status: mentalStatus };
      const refined = await refineTriage(hospitalId, patientId, payload, pin);
      setResult(refined);
      onRefined?.(refined, payload);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Model unavailable.");
    } finally {
      setLoading(false);
    }
  }

  const confidencePct = result ? Math.round(result.confidence * 100) : null;

  return (
    <div className="rounded-2xl bg-surface-lowest p-5 shadow-ambient">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-primary">
        <Activity className="h-4 w-4" />
        Bedside vitals → ML triage refinement
      </div>

      <div className="grid grid-cols-2 gap-3">
        {FIELDS.map(({ key, label, placeholder, step }) => (
          <label key={key} className="flex flex-col gap-1 text-xs text-secondary">
            <span className="tracking-tight">{label}</span>
            <input
              type="number"
              step={step || "any"}
              placeholder={placeholder}
              value={(vitals[key] as number | null | undefined) ?? ""}
              onChange={(e) => update(key, e.target.value)}
              className="rounded-md border border-[rgba(74,85,87,0.2)] bg-surface-low px-3 py-2 text-sm text-primary outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
        ))}
        <label className="col-span-2 flex flex-col gap-1 text-xs text-secondary">
          <span>Mental status</span>
          <select
            value={mentalStatus}
            onChange={(e) => setMentalStatus(e.target.value)}
            className="rounded-md border border-[rgba(74,85,87,0.2)] bg-surface-low px-3 py-2 text-sm text-primary outline-none focus:ring-2 focus:ring-primary/30"
          >
            {["alert", "confused", "drowsy", "agitated", "unresponsive"].map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
      </div>

      <button
        onClick={submit}
        disabled={loading}
        className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-gradient-to-r from-primary to-secondary px-4 py-2.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
        {loading ? "Running ensemble…" : "Refine triage"}
      </button>

      {error && <p className="mt-3 text-xs text-[#BA1A1A]">{error}</p>}

      {result && (
        <div className="mt-5 space-y-4 border-t border-[rgba(74,85,87,0.15)] pt-4">
          <div className="flex items-baseline gap-3">
            <div className="text-3xl font-semibold tracking-tight text-primary">
              ESI {result.esi_level}
            </div>
            <div className="text-sm text-secondary">
              {confidencePct}% confident · conformal set{" "}
              <span className="font-mono text-primary">
                {"{" + result.conformal_set.join(",") + "}"}
              </span>
            </div>
          </div>

          <div>
            <div className="mb-1 text-xs uppercase tracking-wider text-secondary">Probabilities</div>
            <div className="grid grid-cols-5 gap-1">
              {[1, 2, 3, 4, 5].map((esi) => {
                const p = result.probabilities[String(esi)] ?? 0;
                const active = esi === result.esi_level;
                return (
                  <div
                    key={esi}
                    className={`rounded-md p-2 text-center text-xs ${
                      active ? "bg-primary text-white" : "bg-surface-low text-secondary"
                    }`}
                  >
                    <div className="font-semibold">ESI {esi}</div>
                    <div className="mt-0.5 font-mono">{(p * 100).toFixed(1)}%</div>
                  </div>
                );
              })}
            </div>
          </div>

          {result.top_features.length > 0 && (() => {
            const maxAbs = Math.max(
              ...result.top_features.map((f) => Math.abs(f.shap ?? f.weight ?? 0))
            ) || 1;
            return (
              <div>
                <div className="mb-2 text-xs uppercase tracking-wider text-secondary">
                  SHAP feature contributions · why ESI {result.esi_level}
                </div>
                <ul className="space-y-1.5">
                  {result.top_features.slice(0, 5).map((f) => {
                    const val = f.shap ?? f.weight ?? 0;
                    const abs = Math.abs(val);
                    const pct = (abs / maxAbs) * 100;
                    const pushing = f.direction === "increases" || val > 0;
                    return (
                      <li key={f.feature} className="flex items-center gap-2">
                        <span className="font-mono text-[11px] text-primary truncate w-[35%]">
                          {f.feature}
                        </span>
                        <span className="font-mono text-[10px] text-secondary w-[15%] text-right">
                          {f.value.toFixed(1)}
                        </span>
                        <div className="flex-1 h-2 rounded bg-surface-low relative overflow-hidden">
                          <div
                            className={`absolute top-0 h-full rounded ${
                              pushing ? "bg-primary" : "bg-secondary/60"
                            }`}
                            style={{ width: `${pct}%`, left: 0 }}
                          />
                        </div>
                        <span
                          className={`font-mono text-[10px] w-[14%] text-right ${
                            pushing ? "text-primary" : "text-secondary"
                          }`}
                        >
                          {val >= 0 ? "+" : ""}
                          {val.toFixed(3)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <div className="mt-1 text-[10px] text-secondary/70 font-mono">
                  + pushes toward ESI {result.esi_level} · − pushes away
                </div>
              </div>
            );
          })()}

          <details className="group rounded-lg bg-surface-low/50 p-3">
            <summary className="cursor-pointer list-none flex items-center gap-2 text-[11px] font-semibold text-primary uppercase tracking-wider">
              <Info className="h-3 w-3" />
              Model card · tap for the honest caveats
            </summary>
            <div className="mt-2.5 space-y-2 text-[11px] text-secondary leading-relaxed">
              <div>
                <span className="font-semibold text-primary">Model:</span>{" "}
                {result.source} · 5-fold LightGBM with split-conformal prediction
              </div>
              {result.model_metrics?.oof_qwk !== undefined && (
                <div>
                  <span className="font-semibold text-primary">Synthetic-validation OOF:</span>{" "}
                  QWK {result.model_metrics.oof_qwk?.toFixed(3)} · accuracy{" "}
                  {(result.model_metrics.oof_accuracy || 0).toFixed(3)}
                </div>
              )}
              {result.dataset && (
                <div>
                  <span className="font-semibold text-primary">Trained on:</span> {result.dataset}
                </div>
              )}
              {result.training_data_note && (
                <div className="text-secondary/90 italic">{result.training_data_note}</div>
              )}
              <div>
                <span className="font-semibold text-primary">Conformal q̂:</span>{" "}
                {result.conformal_q_hat.toFixed(4)} · noise-perturbed calibration, 90% coverage
              </div>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
