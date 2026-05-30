import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { CopilotBlock } from "../../../lib/api-ops";

/**
 * CopilotArtifacts — renders the model-composed artifact tree as polished,
 * interactive components. The model chose the block types and bound data by
 * reference; every real value here was hydrated server-side by the deterministic
 * renderer (the model never saw it). See services/copilot/ for the boundary.
 */

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};
const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 320, damping: 26 } },
};

function humanize(key: string): string {
  return key
    .replace(/_slot$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function asText(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const SEVERITY_TONE: Record<string, string> = {
  high: "text-error",
  critical: "text-error",
  contraindicated: "text-error",
  moderate: "text-ink",
  medium: "text-ink",
  low: "text-text-muted",
};

/* -------------------------------------------------------------- callout/card */

function Callout({ text, tone = "info" }: { text: string; tone?: string }) {
  const styles: Record<string, string> = {
    info: "bg-surface-low border-line text-ink",
    success: "bg-secondary-container border-line text-ink",
    warning: "bg-error-container/60 border-error/20 text-ink",
    critical: "bg-error-container border-error/30 text-error",
  };
  const dot: Record<string, string> = {
    info: "bg-primary",
    success: "bg-primary",
    warning: "bg-error",
    critical: "bg-error",
  };
  return (
    <div className={`flex gap-3 rounded-xl border px-4 py-3 ${styles[tone] || styles.info}`}>
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dot[tone] || dot.info}`} />
      <p className="text-sm leading-relaxed">{text}</p>
    </div>
  );
}

function Card({ title, text }: { title?: string; text?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      {title && <h4 className="mb-1 text-sm font-semibold text-ink">{title}</h4>}
      {text && <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{text}</p>}
    </div>
  );
}

function Stat({ label, value, unit }: { label?: string; value?: unknown; unit?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-text-muted">{label || "Value"}</div>
      <div className="mt-0.5 text-2xl font-semibold text-ink">
        {asText(value)}
        {unit && <span className="ml-1 text-sm font-normal text-text-muted">{unit}</span>}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- risk gauge */

function RiskGauge({ title, value, conformal }: { title?: string; value?: unknown; conformal?: unknown }) {
  const { pct, display } = useMemo(() => {
    const n = typeof value === "number" ? value : parseFloat(asText(value));
    if (Number.isNaN(n)) return { pct: 0, display: asText(value) };
    const p = n <= 1 ? n * 100 : n <= 100 ? n : 100;
    return { pct: Math.max(0, Math.min(100, p)), display: n <= 1 ? `${Math.round(n * 100)}%` : asText(value) };
  }, [value]);
  const tone = pct >= 66 ? "bg-error" : pct >= 33 ? "bg-primary" : "bg-secondary-container";

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-ink">{title || "Risk score"}</span>
        <span className="text-sm font-semibold text-ink">{display}</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-high">
        <motion.div
          className={`h-full rounded-full ${tone}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ type: "spring", stiffness: 120, damping: 20, delay: 0.1 }}
        />
      </div>
      {conformal != null && (
        <div className="mt-1.5 text-xs text-text-muted">
          Conformal set: {asText(conformal)}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- table */

function Table({ title, rows = [], columns }: { title?: string; rows?: Record<string, unknown>[]; columns?: string[] }) {
  const cols = columns?.length ? columns : rows.length ? Object.keys(rows[0]) : [];
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => {
      const av = asText(a[sort.key]);
      const bv = asText(b[sort.key]);
      return av.localeCompare(bv) * sort.dir;
    });
  }, [rows, sort]);

  if (!rows.length) return null;
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      {title && <div className="border-b border-line px-4 py-2.5 text-sm font-semibold text-ink">{title}</div>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-surface-low">
              {cols.map((c) => (
                <th
                  key={c}
                  onClick={() => setSort((s) => ({ key: c, dir: s?.key === c && s.dir === 1 ? -1 : 1 }))}
                  className="cursor-pointer select-none px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-text-muted hover:text-ink"
                >
                  {humanize(c)}
                  {sort?.key === c && <span className="ml-1">{sort.dir === 1 ? "▲" : "▼"}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0 hover:bg-surface-low">
                {cols.map((c) => {
                  const tone = SEVERITY_TONE[asText(r[c]).toLowerCase()];
                  return (
                    <td key={c} className={`px-4 py-2 ${tone || "text-ink"}`}>
                      {asText(r[c])}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- timeline */

function Timeline({ title, events = [] }: { title?: string; events?: Record<string, unknown>[] }) {
  if (!events.length) return null;
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      {title && <h4 className="mb-3 text-sm font-semibold text-ink">{title}</h4>}
      <ol className="relative ml-2 border-l border-line">
        {events.map((e, i) => {
          const date = asText(e.date ?? e.date_slot ?? e.when);
          const rest = Object.entries(e).filter(([k]) => !/^(date|when)/.test(k));
          return (
            <motion.li
              key={i}
              variants={item}
              className="mb-4 ml-4 last:mb-0"
            >
              <span className="absolute -left-[5px] mt-1 h-2.5 w-2.5 rounded-full bg-primary ring-4 ring-surface" />
              <div className="text-xs font-medium text-text-muted">{date}</div>
              {rest.map(([k, v]) => (
                <div key={k} className="text-sm text-ink">
                  <span className="text-text-muted">{humanize(k)}: </span>
                  {asText(v)}
                </div>
              ))}
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}

/* ------------------------------------------------------------- differential */

type Dx = {
  diagnosis?: string;
  icd10?: string;
  likelihood?: string;
  must_not_miss?: boolean;
  discriminator?: string;
};

function Differential({ title, ranked = [] }: { title?: string; ranked?: Dx[] }) {
  const [open, setOpen] = useState<number | null>(0);
  if (!ranked.length) return null;
  const likeTone: Record<string, string> = {
    high: "bg-error-container text-error",
    moderate: "bg-secondary-container text-ink",
    low: "bg-surface-high text-text-muted",
  };
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h4 className="mb-3 text-sm font-semibold text-ink">{title || "Differential diagnosis"}</h4>
      <div className="space-y-2">
        {ranked.map((d, i) => (
          <div key={i} className="overflow-hidden rounded-lg border border-line">
            <button
              onClick={() => setOpen((o) => (o === i ? null : i))}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-surface-low"
            >
              <span className="flex items-center gap-2">
                <span className="text-xs font-semibold text-text-muted">{i + 1}</span>
                <span className="text-sm font-medium text-ink">{d.diagnosis || "—"}</span>
                {d.must_not_miss && (
                  <span className="rounded-full bg-error-container px-1.5 py-0.5 text-[10px] font-semibold uppercase text-error">
                    must not miss
                  </span>
                )}
              </span>
              <span className="flex items-center gap-2">
                {d.likelihood && (
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${likeTone[d.likelihood.toLowerCase()] || likeTone.low}`}>
                    {d.likelihood}
                  </span>
                )}
                <span className="text-text-muted">{open === i ? "−" : "+"}</span>
              </span>
            </button>
            {open === i && (d.discriminator || d.icd10) && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                className="border-t border-line bg-surface-low px-3 py-2 text-xs text-ink"
              >
                {d.icd10 && <div className="text-text-muted">ICD-10: {d.icd10}</div>}
                {d.discriminator && <div className="mt-0.5">Key discriminator: {d.discriminator}</div>}
              </motion.div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- the renderer */

function Block({ block }: { block: CopilotBlock }) {
  switch (block.type) {
    case "callout":
      return <Callout text={block.text} tone={block.tone} />;
    case "card":
      return <Card title={block.title} text={block.text} />;
    case "stat":
      return <Stat label={block.label} value={block.value} unit={block.unit} />;
    case "risk_gauge":
      return <RiskGauge title={block.title} value={block.value} conformal={block.conformal} />;
    case "table":
      return <Table title={block.title} rows={block.rows} columns={block.columns} />;
    case "timeline":
      return <Timeline title={block.title} events={block.events} />;
    case "differential":
      return <Differential title={block.title} ranked={block.ranked} />;
    default:
      return null;
  }
}

export default function CopilotArtifacts({ blocks }: { blocks: CopilotBlock[] }) {
  if (!blocks?.length) return null;
  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-3">
      {blocks.map((b, i) => (
        <motion.div key={i} variants={item}>
          <Block block={b} />
        </motion.div>
      ))}
    </motion.div>
  );
}

CopilotArtifacts.displayName = "CopilotArtifacts";
