import { useMemo, useState } from "react";
import { Beaker, ScanLine, Activity, UserPlus, Check } from "lucide-react";
import type { WorkupOrders } from "../../types";

type Props = {
  orders: WorkupOrders;
};

type Section = {
  key: keyof Pick<WorkupOrders, "labs" | "imaging" | "monitoring" | "consults">;
  title: string;
  Icon: typeof Beaker;
};

const SECTIONS: Section[] = [
  { key: "labs",       title: "Labs",       Icon: Beaker },
  { key: "imaging",    title: "Imaging",    Icon: ScanLine },
  { key: "monitoring", title: "Monitoring", Icon: Activity },
  { key: "consults",   title: "Consults",   Icon: UserPlus },
];

export function WorkupPanel({ orders }: Props) {
  const all = useMemo(() => {
    return SECTIONS.flatMap((s) => (orders[s.key] || []).map((o) => `${s.key}:${o}`));
  }, [orders]);

  const [accepted, setAccepted] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setAccepted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const total = all.length;
  if (total === 0) return null;

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Workup order set (AI draft)
        </div>
        <button
          type="button"
          onClick={() => setAccepted(new Set(all))}
          className="text-[11px] font-medium text-primary hover:text-primary-hover"
        >
          Accept all ({total})
        </button>
      </div>
      <div className="bg-surface-lowest rounded-lg p-3 shadow-soft flex flex-col gap-3">
        {SECTIONS.map((s) => {
          const items = orders[s.key] || [];
          if (items.length === 0) return null;
          return (
            <div key={s.key}>
              <div className="flex items-center gap-1.5 mb-1.5">
                <s.Icon size={13} className="text-text-muted" />
                <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                  {s.title}
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {items.map((order) => {
                  const id = `${s.key}:${order}`;
                  const isAccepted = accepted.has(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => toggle(id)}
                      className={`inline-flex items-center gap-1 px-2.5 h-7 rounded-md text-[12px] font-medium transition-colors ${
                        isAccepted
                          ? "bg-primary text-white"
                          : "bg-surface-low text-ink hover:bg-primary-fixed"
                      }`}
                    >
                      {isAccepted && <Check size={11} />}
                      {order}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
        {orders.rationale && (
          <div className="text-[12px] text-text-muted italic border-t border-line pt-2">
            {orders.rationale}
          </div>
        )}
      </div>
    </section>
  );
}
