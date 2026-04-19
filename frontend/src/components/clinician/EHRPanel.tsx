import { useEffect, useState } from "react";
import { FileText, Loader2 } from "lucide-react";
import { lookupEHR, type EHRRecord } from "../../lib/api";

type Props = {
  hospitalId: string;
  patientId: string;
};

/** Auto-fires an EHR lookup on mount. Shows rich hx + prior visits or a clear "not in EHR" state. */
export function EHRPanel({ hospitalId, patientId }: Props) {
  const [loading, setLoading] = useState(true);
  const [record, setRecord] = useState<EHRRecord | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    lookupEHR(hospitalId, patientId)
      .then((r) => {
        if (cancelled) return;
        setRecord(r.record);
        setReason(r.reason ?? null);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.response?.data?.detail || "EHR lookup failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hospitalId, patientId]);

  return (
    <section className="rounded-2xl bg-surface-lowest p-5 shadow-ambient">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-primary">
        <FileText className="h-4 w-4" />
        EHR · Connected Health Record (FHIR R4 shape)
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          Querying EHR by patient name…
        </div>
      )}

      {!loading && error && <div className="text-sm text-error">{error}</div>}

      {!loading && !record && reason && (
        <div className="text-sm text-text-muted">
          <span className="font-semibold text-primary">No EHR match.</span> {reason}. New patient or
          name mismatch — EHR must be searched manually.
        </div>
      )}

      {!loading && record && <RecordView r={record} />}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[180px_1fr] gap-3 text-sm py-1">
      <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold pt-0.5">
        {label}
      </div>
      <div className="text-[13px] text-ink leading-relaxed">{children}</div>
    </div>
  );
}

function age(dob: string): number {
  const b = new Date(dob);
  const now = new Date();
  let a = now.getFullYear() - b.getFullYear();
  const m = now.getMonth() - b.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < b.getDate())) a--;
  return a;
}

function RecordView({ r }: { r: EHRRecord }) {
  const filt = (list: string[] | undefined) =>
    (list || []).filter((x) => x && x.toLowerCase() !== "none");
  const allergies = filt(r.allergies);
  const meds = filt(r.medications);
  const conditions = filt(r.conditions);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="text-lg font-bold tracking-editorial text-primary">{r.name}</div>
        <span className="font-mono text-[11px] text-text-muted">MRN {r.mrn}</span>
        <span className="text-xs text-text-muted">
          {age(r.dob)} y · {r.sex} · {r.blood_type}
        </span>
      </div>

      <div className="h-px bg-[rgba(74,85,87,0.12)] my-1" />

      <Row label="Allergies">{allergies.length ? allergies.join(" · ") : "NKDA"}</Row>
      <Row label="Current meds">{meds.length ? meds.join(" · ") : "none"}</Row>
      <Row label="Conditions">{conditions.length ? conditions.join(" · ") : "none"}</Row>
      <Row label="Family history">
        {(r.family_history || []).length ? r.family_history.join(" · ") : "none documented"}
      </Row>
      <Row label="Social history">{r.social_history || "—"}</Row>
      <Row label="Vitals baseline">
        {r.height_cm} cm · {r.weight_kg} kg · BMI {r.bmi}
      </Row>
      <Row label="Primary care">{r.primary_care_provider}</Row>
      <Row label="Insurance">{r.insurance}</Row>
      <Row label="Emergency contact">{r.emergency_contact}</Row>
      <Row label="Immunizations">
        {(r.immunizations || []).length ? r.immunizations.join(" · ") : "none on file"}
      </Row>

      {r.prior_visits && r.prior_visits.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold mb-2">
            Prior visits
          </div>
          <ul className="space-y-2">
            {r.prior_visits.map((v, i) => (
              <li key={i} className="border-l-2 border-primary-fixed pl-3 text-[12px]">
                <div className="font-semibold text-primary">
                  {v.date} · {v.type} · {v.facility}
                </div>
                <div className="text-text-muted">
                  CC: {v.chief_complaint} → {v.disposition}
                </div>
                <div className="text-ink mt-0.5">{v.note}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(!r.prior_visits || r.prior_visits.length === 0) && (
        <div className="mt-2 text-[11px] text-text-muted italic">No prior encounters on file.</div>
      )}
    </div>
  );
}
