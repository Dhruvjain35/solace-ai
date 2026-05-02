import { useEffect, useState } from "react";
import { FileText, Loader2, ShieldCheck, Hash, User as UserIcon } from "lucide-react";
import { lookupEHR, type EHRLookupResult, type EHRRecord } from "../../lib/api";

type Props = {
  hospitalId: string;
  patientId: string;
};

/** Auto-fires an EHR lookup on mount. Shows match method + rich record or a clear "not in EHR" state. */
export function EHRPanel({ hospitalId, patientId }: Props) {
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState<EHRLookupResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    lookupEHR(hospitalId, patientId)
      .then((r) => {
        if (!cancelled) setResult(r);
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
    <section className="rounded-lg bg-surface-lowest p-5 shadow-soft">
      <header className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-primary">
          <FileText className="h-4 w-4" />
          EHR record
        </div>
        {result?.match_method && result.record && (
          <MatchBadge method={result.match_method} />
        )}
      </header>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          Querying EHR by insurance member ID + name…
        </div>
      )}

      {!loading && error && <div className="text-sm text-error">{error}</div>}

      {!loading && !result?.record && result?.reason && (
        <div className="text-sm text-text-muted">
          <span className="font-semibold text-primary">No EHR match.</span> {result.reason}. Likely a new patient or a name / insurance mismatch — search manually with the EHR's MRN.
        </div>
      )}

      {!loading && result?.record && <RecordView r={result.record} />}
    </section>
  );
}

function MatchBadge({ method }: { method: NonNullable<EHRLookupResult["match_method"]> }) {
  const label =
    method === "insurance_member_id+provider"
      ? "Matched by insurance + provider"
      : method === "insurance_member_id"
      ? "Matched by insurance member ID"
      : "Matched by name";
  const Icon =
    method === "insurance_member_id" || method === "insurance_member_id+provider" ? Hash : UserIcon;
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-primary-fixed text-primary">
      <Icon size={10} />
      {label}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 py-1">
      <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold pt-0.5">
        {label}
      </div>
      <div className="text-sm text-ink leading-relaxed">{children}</div>
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
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="text-base font-bold text-primary">{r.name}</div>
        <span className="font-mono text-[11px] text-text-muted">MRN {r.mrn}</span>
        <span className="text-xs text-text-muted">
          {age(r.dob)} y · {r.sex} · {r.blood_type}
        </span>
        <span className="inline-flex items-center gap-1 ml-auto text-[10px] text-text-muted">
          <ShieldCheck size={11} className="text-primary" />
          FHIR R4
        </span>
      </div>

      <div className="h-px bg-line my-1.5" />

      <Row label="Allergies">{allergies.length ? allergies.join(" · ") : "NKDA"}</Row>
      <Row label="Medications">{meds.length ? meds.join(" · ") : "none"}</Row>
      <Row label="Conditions">{conditions.length ? conditions.join(" · ") : "none"}</Row>
      <Row label="Family hx">
        {(r.family_history || []).length ? r.family_history.join(" · ") : "none documented"}
      </Row>
      <Row label="Social hx">{r.social_history || "—"}</Row>
      <Row label="Baseline">
        <span className="font-mono text-[13px]">
          {r.height_cm} cm · {r.weight_kg} kg · BMI {r.bmi}
        </span>
      </Row>
      <Row label="PCP">{r.primary_care_provider}</Row>
      <Row label="Insurance">{r.insurance}</Row>
      <Row label="Emergency">{r.emergency_contact}</Row>
      <Row label="Immunizations">
        {(r.immunizations || []).length ? r.immunizations.join(" · ") : "none on file"}
      </Row>

      {r.prior_visits && r.prior_visits.length > 0 ? (
        <div className="mt-3">
          <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-2">
            Prior encounters · {r.prior_visits.length}
          </div>
          <ul className="space-y-2">
            {r.prior_visits.map((v, i) => (
              <li key={i} className="border-l-2 border-primary-fixed pl-3 text-[13px]">
                <div className="font-semibold text-primary">
                  {v.date} · {v.type} · {v.facility}
                </div>
                <div className="text-text-muted text-[12px]">
                  CC: {v.chief_complaint} → {v.disposition}
                </div>
                <div className="text-ink mt-0.5">{v.note}</div>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="mt-2 text-[12px] text-text-muted italic">No prior encounters on file.</div>
      )}
    </div>
  );
}
