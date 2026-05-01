import { AlertCircle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { DifferentialEntry } from "../../types";

type Props = {
  entries: DifferentialEntry[];
};

function likelihoodBadge(level: DifferentialEntry["likelihood"]) {
  switch (level) {
    case "high":
      return "bg-error/15 text-error";
    case "moderate":
      return "bg-warning/15 text-warning";
    default:
      return "bg-surface-low text-text-muted";
  }
}

export function DifferentialPanel({ entries }: Props) {
  const [openIdx, setOpenIdx] = useState<number | null>(0);

  if (!entries || entries.length === 0) return null;

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Differential diagnosis (AI draft)
        </div>
        <span className="text-[10px] text-text-muted">{entries.length} entries</span>
      </div>
      <div className="flex flex-col gap-2">
        {entries.map((d, i) => {
          const isOpen = openIdx === i;
          return (
            <div
              key={i}
              className="bg-surface-lowest rounded-lg shadow-soft overflow-hidden"
            >
              <button
                type="button"
                onClick={() => setOpenIdx(isOpen ? null : i)}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-surface-low transition-colors"
              >
                {isOpen ? (
                  <ChevronDown size={16} className="text-text-muted shrink-0" />
                ) : (
                  <ChevronRight size={16} className="text-text-muted shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold tracking-editorial text-[15px]">
                      {d.diagnosis}
                    </span>
                    {d.must_not_miss && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-error text-white">
                        <AlertCircle size={10} /> Must not miss
                      </span>
                    )}
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${likelihoodBadge(d.likelihood)}`}
                    >
                      {d.likelihood}
                    </span>
                    {d.icd10 && (
                      <span className="text-[10px] font-mono text-text-muted">
                        {d.icd10}
                      </span>
                    )}
                  </div>
                </div>
              </button>
              {isOpen && (
                <div className="px-3 pb-3 pt-1 grid grid-cols-1 sm:grid-cols-2 gap-3 border-t border-line">
                  {d.rule_in.length > 0 && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">
                        Rule-in
                      </div>
                      <ul className="text-[13px] leading-snug list-disc list-inside text-ink space-y-0.5">
                        {d.rule_in.map((x, j) => (
                          <li key={j}>{x}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {d.rule_out.length > 0 && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">
                        Rule-out
                      </div>
                      <ul className="text-[13px] leading-snug list-disc list-inside text-text-muted space-y-0.5">
                        {d.rule_out.map((x, j) => (
                          <li key={j}>{x}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
