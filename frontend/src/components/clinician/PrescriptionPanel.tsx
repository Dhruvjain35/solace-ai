import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Plus, Sparkles } from "lucide-react";
import {
  createPrescription,
  listPrescriptions,
  suggestPrescriptions,
} from "../../lib/api";
import type { Prescription, PrescriptionSuggestion } from "../../types";

type Props = {
  hospitalId: string;
  patientId: string;
  pin: string;
};

const EMPTY_MANUAL: PrescriptionSuggestion = {
  drug: "",
  dose: "",
  route: "",
  frequency: "",
  duration: "",
  indication: "",
  cautions: "",
};

export function PrescriptionPanel({ hospitalId, patientId, pin }: Props) {
  const [items, setItems] = useState<Prescription[]>([]);
  const [loading, setLoading] = useState(true);
  const [suggestions, setSuggestions] = useState<PrescriptionSuggestion[]>([]);
  const [suggestBusy, setSuggestBusy] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualDraft, setManualDraft] = useState<PrescriptionSuggestion>(EMPTY_MANUAL);
  const [saving, setSaving] = useState(false);

  async function refresh() {
    try {
      const list = await listPrescriptions(hospitalId, patientId, pin);
      setItems(list);
    } catch {
      // swallow
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId]);

  async function fetchSuggestions() {
    setSuggestBusy(true);
    try {
      const s = await suggestPrescriptions(hospitalId, patientId, pin);
      setSuggestions(s);
    } finally {
      setSuggestBusy(false);
    }
  }

  async function accept(s: PrescriptionSuggestion) {
    setSaving(true);
    try {
      await createPrescription(hospitalId, patientId, pin, { ...s, source: "ai_suggested_accepted" });
      setSuggestions((prev) => prev.filter((x) => x !== s));
      await refresh();
    } finally {
      setSaving(false);
    }
  }

  async function saveManual() {
    if (!manualDraft.drug.trim()) return;
    setSaving(true);
    try {
      await createPrescription(hospitalId, patientId, pin, { ...manualDraft, source: "manual" });
      setManualDraft(EMPTY_MANUAL);
      setManualOpen(false);
      await refresh();
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Prescriptions
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchSuggestions}
            disabled={suggestBusy}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover disabled:opacity-50"
          >
            {suggestBusy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            AI suggest
          </button>
          <button
            type="button"
            onClick={() => setManualOpen((o) => !o)}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover"
          >
            <Plus size={14} /> New
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-sm text-text-muted">Loading…</div>
      ) : items.length === 0 && suggestions.length === 0 && !manualOpen ? (
        <div className="text-sm text-text-muted bg-surface-low rounded-lg p-3">
          None written yet. Use <span className="font-semibold">AI suggest</span> to see options, or{" "}
          <span className="font-semibold">New</span> to write one manually.
        </div>
      ) : null}

      {items.length > 0 && (
        <div className="flex flex-col gap-2">
          {items.map((p) => (
            <PrescriptionCard key={p.prescription_id} p={p} />
          ))}
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="mt-3 flex flex-col gap-2">
          <div className="text-[11px] uppercase tracking-[0.14em] text-primary font-semibold">
            AI suggestions — verify before prescribing
          </div>
          {suggestions.map((s, i) => (
            <div key={i} className="bg-primary-fixed/40 rounded-lg p-3 flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2">
                <div className="font-bold tracking-editorial">
                  {s.drug} {s.dose && <span className="text-sm font-normal">{s.dose}</span>}
                </div>
                <button
                  type="button"
                  onClick={() => accept(s)}
                  disabled={saving}
                  className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-primary text-white text-xs font-medium"
                >
                  <Check size={14} /> Accept
                </button>
              </div>
              <div className="text-xs font-mono text-text-muted">
                {[s.route, s.frequency, s.duration].filter(Boolean).join(" · ")}
              </div>
              {s.indication && <div className="text-sm">{s.indication}</div>}
              {s.cautions && (
                <div className="text-xs text-error flex items-start gap-1">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                  <span>{s.cautions}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {manualOpen && (
        <div className="mt-3 bg-surface-lowest rounded-lg p-3 shadow-soft flex flex-col gap-2">
          <ManualField label="Drug" value={manualDraft.drug} onChange={(v) => setManualDraft({ ...manualDraft, drug: v })} />
          <div className="grid grid-cols-2 gap-2">
            <ManualField label="Dose" value={manualDraft.dose} onChange={(v) => setManualDraft({ ...manualDraft, dose: v })} />
            <ManualField label="Route" value={manualDraft.route} onChange={(v) => setManualDraft({ ...manualDraft, route: v })} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <ManualField label="Frequency" value={manualDraft.frequency} onChange={(v) => setManualDraft({ ...manualDraft, frequency: v })} />
            <ManualField label="Duration" value={manualDraft.duration} onChange={(v) => setManualDraft({ ...manualDraft, duration: v })} />
          </div>
          <ManualField label="Indication" value={manualDraft.indication} onChange={(v) => setManualDraft({ ...manualDraft, indication: v })} />
          <div className="flex gap-2 mt-1">
            <button
              type="button"
              onClick={saveManual}
              disabled={!manualDraft.drug.trim() || saving}
              className="h-9 px-4 rounded-md bg-primary text-white text-sm font-medium disabled:opacity-50"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : "Save Rx"}
            </button>
            <button
              type="button"
              onClick={() => {
                setManualOpen(false);
                setManualDraft(EMPTY_MANUAL);
              }}
              className="h-9 px-4 rounded-md text-sm text-text-muted"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function PrescriptionCard({ p }: { p: Prescription }) {
  return (
    <div className="bg-surface-lowest rounded-lg p-3 shadow-soft">
      <div className="flex items-center justify-between gap-2">
        <div className="font-bold tracking-editorial">
          {p.drug} {p.dose && <span className="text-sm font-normal">{p.dose}</span>}
        </div>
        <span className="text-[10px] uppercase tracking-wider text-text-muted">{p.source.replace("_", " ")}</span>
      </div>
      <div className="text-xs font-mono text-text-muted">
        {[p.route, p.frequency, p.duration].filter(Boolean).join(" · ")}
      </div>
      {p.indication && <div className="text-sm mt-1">{p.indication}</div>}
      {p.cautions && (
        <div className="text-xs text-error flex items-start gap-1 mt-1">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>{p.cautions}</span>
        </div>
      )}
      <div className="text-[10px] text-text-muted mt-1">
        by {p.prescribed_by} · {new Date(p.prescribed_at).toLocaleTimeString()}
      </div>
    </div>
  );
}

function ManualField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted mb-1">{label}</div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-10 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none transition-all"
      />
    </div>
  );
}
