import { Link } from "react-router-dom";
import { MessageSquare, Printer, Mic } from "lucide-react";
import type { PatientDetail } from "../../types";
import { Button } from "../ui/Button";
import { PrescriptionPanel } from "./PrescriptionPanel";
import { NotesPanel } from "./NotesPanel";
import { VitalsPanel } from "./VitalsPanel";
import { EHRPanel } from "./EHRPanel";
import { DifferentialPanel } from "./DifferentialPanel";
import { WorkupPanel } from "./WorkupPanel";
import { DispositionPanel } from "./DispositionPanel";
import { markSeen, sendDischargeSMS } from "../../lib/api";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-2">
        {title}
      </div>
      {children}
    </section>
  );
}

function InsRow({
  label,
  value,
  mono = false,
  primary = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  primary?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">{label}</div>
      <div
        className={`text-sm leading-tight ${mono ? "font-mono" : ""} ${
          primary ? "font-bold text-primary" : "text-ink"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function formatMedicalInfo(info: NonNullable<PatientDetail["medical_info"]>): string {
  const parts: string[] = [];
  if (info.age) parts.push(`${info.age}yo`);
  if (info.sex) parts.push(info.sex);
  if (info.pregnant) {
    parts.push(info.gestational_weeks ? `pregnant ${info.gestational_weeks}w` : "pregnant");
  }
  if (info.smoker) parts.push("smoker");
  const allergies = (info.allergies || []).filter((x) => x.toLowerCase() !== "none");
  if (allergies.length) {
    const labeled = allergies.map((a) => {
      const sev = info.allergy_severity?.[a];
      return sev ? `${a} (${sev})` : a;
    });
    parts.push(`allergies: ${labeled.join(", ")}`);
  }
  const meds = (info.medications || []).filter((x) => x.toLowerCase() !== "none");
  if (meds.length) {
    const labeled = meds.map((m) =>
      m === "Blood thinners" && info.blood_thinner_name ? `${m} (${info.blood_thinner_name})` : m,
    );
    parts.push(`meds: ${labeled.join(", ")}`);
  }
  const conds = (info.conditions || []).filter((x) => x.toLowerCase() !== "none");
  if (conds.length) {
    const labeled = conds.map((c) => {
      if (c === "Diabetes" && info.diabetes_type) return `${c} (${info.diabetes_type})`;
      if (c === "Heart failure" && info.heart_failure_class) return `${c} (NYHA ${info.heart_failure_class})`;
      return c;
    });
    parts.push(`hx: ${labeled.join(", ")}`);
  }
  return parts.join(" · ") || "none reported";
}

type Props = {
  detail: PatientDetail;
  hospitalId: string;
  authenticated: boolean;
  showScribeLink?: boolean;
  onDetailChange: (updater: (d: PatientDetail | null) => PatientDetail | null) => void;
  onAfterMarkSeen: () => void | Promise<void>;
};

/**
 * The full clinical detail JSX shared between the dashboard drawer and the
 * full-page patient view. Everything inside this component assumes `detail`
 * is loaded.
 */
export function PatientDetailBody({
  detail,
  hospitalId,
  authenticated,
  showScribeLink = true,
  onDetailChange,
  onAfterMarkSeen,
}: Props) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm text-text-muted font-mono">
          waited {detail.waited_minutes}m · {detail.language.toUpperCase()}
        </div>
        {showScribeLink && (
          <Link
            to={`/${hospitalId}/clinician/patient/${detail.patient_id}/scribe`}
            className="inline-flex items-center gap-1.5 px-3 h-9 rounded-md bg-primary text-white text-sm font-semibold hover:opacity-90"
            title="Open the ambient scribe bound to this patient"
          >
            <Mic size={14} /> Open scribe
          </Link>
        )}
      </div>

      {/* ESI reconciliation banner — provisional vs refined */}
      <div className="bg-surface-lowest rounded-lg p-4 shadow-soft">
        <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-2">
          Triage acuity
        </div>
        <div className="flex items-center gap-3">
          <div className="flex flex-col gap-0.5">
            <div className="text-[10px] uppercase tracking-wider text-text-muted">Provisional · on intake</div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-primary">ESI {detail.esi_level}</span>
              {detail.esi_confidence != null && (
                <span className="text-xs font-mono text-text-muted">
                  {(detail.esi_confidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
          </div>
          <div className="text-xl text-text-muted mx-1">→</div>
          <div className="flex flex-col gap-0.5">
            <div className="text-[10px] uppercase tracking-wider text-text-muted">
              {detail.refined_esi_level ? "Refined · bedside ML" : "Refined · vitals pending"}
            </div>
            <div className="flex items-baseline gap-2">
              {detail.refined_esi_level ? (
                <>
                  <span className="text-2xl font-bold text-primary">ESI {detail.refined_esi_level}</span>
                  {detail.refined_confidence != null && (
                    <span className="text-xs font-mono text-text-muted">
                      {(detail.refined_confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </>
              ) : (
                <span className="text-base text-text-muted italic">take vitals to refine</span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-primary-fixed/40 rounded-lg p-4">
        <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-1">
          Pre-brief
        </div>
        <div className="text-[15px] leading-relaxed text-ink">{detail.clinician_prebrief}</div>
      </div>

      {detail.clinical_scribe_note && (
        <Section title="Scribe note (AI draft)">
          <div className="bg-surface-low rounded-lg p-4 text-[14px] leading-relaxed whitespace-pre-wrap text-ink">
            {detail.clinical_scribe_note}
          </div>
        </Section>
      )}

      {detail.clinical_flags.length > 0 && (
        <Section title="Clinical flags">
          <div className="flex flex-wrap gap-2">
            {detail.clinical_flags.map((f) => (
              <span key={f} className="px-2.5 py-1 rounded-full text-xs font-medium bg-error/10 text-error">
                {f}
              </span>
            ))}
          </div>
        </Section>
      )}

      {detail.refined_esi_level && detail.measured_vitals ? (
        <Section title="Risk scores · from measured vitals">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm">
            {([
              { k: "qsofa", label: "qSOFA" },
              { k: "sirs", label: "SIRS" },
              { k: "shock_index", label: "Shock index" },
              { k: "cv_risk", label: "CV risk" },
            ] as const).map(({ k, label }) => (
              <div key={k} className="bg-surface-lowest rounded-lg p-3 shadow-soft">
                <div className="text-[10px] uppercase tracking-wider text-text-muted">{label}</div>
                <div className="text-lg font-bold tracking-editorial text-ink mt-0.5">
                  {detail.composites[k] ?? "—"}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ) : (
        <Section title="Risk scores">
          <div className="bg-surface-lowest rounded-lg p-4 text-[13px] text-text-muted shadow-soft italic">
            Awaiting bedside vitals. Enter heart rate, blood pressure, respiratory rate, and SpO₂ below and the system will refine the triage score automatically.
          </div>
        </Section>
      )}

      {detail.triage_recommendation && (
        <Section title="Recommended next steps">
          <div className="bg-surface-lowest rounded-lg p-4 text-[14px] leading-relaxed shadow-soft">
            {detail.triage_recommendation}
          </div>
        </Section>
      )}

      {detail.differential && detail.differential.length > 0 && (
        <DifferentialPanel entries={detail.differential} />
      )}

      {detail.workup_orders && <WorkupPanel orders={detail.workup_orders} />}

      {detail.disposition && detail.disposition.disposition && (
        <DispositionPanel disposition={detail.disposition} />
      )}

      <Section title="Patient's words">
        <div className="bg-surface-low rounded-lg p-4 text-[14px] leading-relaxed whitespace-pre-wrap text-ink italic">
          "{detail.transcript}"
        </div>
      </Section>

      {detail.followup_qa.length > 0 && (
        <Section title="Follow-up Q&A">
          <div className="flex flex-col gap-2">
            {detail.followup_qa.map((qa, i) => (
              <div key={i} className="text-sm">
                <span className="text-text-muted">Q: </span>
                <span className="font-medium">{qa.question}</span>
                <br />
                <span className="text-text-muted">A: </span>
                <span className="font-mono">{qa.answer}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {detail.medical_info && (
        <Section title="Reported history">
          <div className="text-sm leading-relaxed text-ink">{formatMedicalInfo(detail.medical_info)}</div>
        </Section>
      )}

      {detail.insurance_info && (
        <Section title="Insurance">
          <div className="bg-surface-lowest rounded-lg p-4 shadow-soft flex flex-col gap-2">
            {detail.insurance_info.provider && <InsRow label="Insurer" value={detail.insurance_info.provider} primary />}
            {detail.insurance_info.plan_name && <InsRow label="Plan" value={detail.insurance_info.plan_name} />}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              {detail.insurance_info.member_id && <InsRow label="Member ID" value={detail.insurance_info.member_id} mono />}
              {detail.insurance_info.group_number && <InsRow label="Group" value={detail.insurance_info.group_number} mono />}
              {detail.insurance_info.name_on_card && <InsRow label="Name on card" value={detail.insurance_info.name_on_card} />}
              {detail.insurance_info.effective_date && <InsRow label="Effective" value={detail.insurance_info.effective_date} mono />}
              {detail.insurance_info.bin && <InsRow label="BIN" value={detail.insurance_info.bin} mono />}
              {detail.insurance_info.pcn && <InsRow label="PCN" value={detail.insurance_info.pcn} mono />}
              {detail.insurance_info.rx_group && <InsRow label="Rx group" value={detail.insurance_info.rx_group} mono />}
              {detail.insurance_info.phone && <InsRow label="Phone" value={detail.insurance_info.phone} mono />}
            </div>
          </div>
        </Section>
      )}

      <EHRPanel hospitalId={hospitalId} patientId={detail.patient_id} />

      <VitalsPanel
        hospitalId={hospitalId}
        patientId={detail.patient_id}
        existing={
          detail.refined_esi_level
            ? {
                esi_level: detail.refined_esi_level,
                confidence: detail.refined_confidence ?? 0,
                probabilities: detail.refined_probabilities ? JSON.parse(detail.refined_probabilities) : {},
                conformal_set: detail.refined_conformal_set
                  ? JSON.parse(detail.refined_conformal_set)
                  : [detail.refined_esi_level],
                conformal_q_hat: 0,
                top_features: detail.refined_top_features ? JSON.parse(detail.refined_top_features) : [],
                source: detail.refined_source ?? "lgbm",
              }
            : null
        }
        onRefined={(r, v) =>
          onDetailChange((d) =>
            d
              ? {
                  ...d,
                  refined_esi_level: r.esi_level,
                  refined_confidence: r.confidence,
                  refined_probabilities: JSON.stringify(r.probabilities),
                  refined_conformal_set: JSON.stringify(r.conformal_set),
                  refined_top_features: JSON.stringify(r.top_features),
                  refined_source: r.source,
                  measured_vitals: d.measured_vitals ?? JSON.stringify(v),
                }
              : d,
          )
        }
      />

      <NotesPanel
        hospitalId={hospitalId}
        patientId={detail.patient_id}
        initialNotes={detail.notes}
        initialEducation={detail.patient_education}
        publishedAt={detail.patient_education_published_at}
      />

      <PrescriptionPanel
        hospitalId={hospitalId}
        patientId={detail.patient_id}
        medicalInfo={detail.medical_info}
      />

      {detail.photo_url && (
        <Section title="Photo">
          <img src={detail.photo_url} alt="Injury" className="max-w-full rounded-lg shadow-soft" />
          {detail.photo_analysis?.description && (
            <p className="text-sm text-ink mt-2">{detail.photo_analysis.description}</p>
          )}
        </Section>
      )}

      {detail.shap_values && Object.keys(detail.shap_values).length > 0 && (
        <Section title="What drove this ESI">
          <div className="flex flex-col gap-1.5 font-mono text-xs">
            {Object.entries(detail.shap_values)
              .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
              .slice(0, 8)
              .map(([feature, value]) => (
                <div key={feature} className="flex items-center gap-2">
                  <span className="w-48 truncate text-text-muted">{feature}</span>
                  <div className="flex-1 h-4 bg-surface-low rounded-sm relative">
                    <div
                      className="h-full rounded-sm"
                      style={{
                        background: value >= 0 ? "#B05436" : "#557D6E",
                        width: `${Math.min(100, Math.abs(value) * 100)}%`,
                      }}
                    />
                  </div>
                  <span className="w-12 text-right">{value.toFixed(2)}</span>
                </div>
              ))}
          </div>
          {detail.triage_source === "heuristic_stub" && (
            <p className="text-xs text-text-muted mt-2 italic">
              Triage drivers are estimated. Bedside vitals will sharpen these.
            </p>
          )}
        </Section>
      )}

      <div className="flex flex-col gap-2">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() =>
              window.open(`/${hospitalId}/clinician/print/${detail.patient_id}`, "_blank", "noopener")
            }
            className="inline-flex items-center justify-center gap-1.5 h-11 px-4 rounded-md bg-surface-low text-ink hover:bg-surface-high text-sm font-semibold border border-line"
            title="Open a printable copy of this record in a new tab"
          >
            <Printer size={14} /> Print notes
          </button>
          <button
            type="button"
            onClick={async () => {
              if (!authenticated) return;
              const phone = window.prompt("Send discharge SMS to (leave blank to use phone on file):", "");
              if (phone === null) return;
              const r = await sendDischargeSMS(hospitalId, detail.patient_id, phone || undefined);
              alert(
                r.success
                  ? "Discharge SMS sent."
                  : r.reason === "not_configured"
                  ? "Twilio SMS not configured for this hospital."
                  : r.reason === "invalid_number"
                  ? "Invalid phone number — try again with a valid 10-digit US number."
                  : `Couldn't send: ${r.message || r.reason}`,
              );
            }}
            className="inline-flex items-center justify-center gap-1.5 h-11 px-4 rounded-md bg-surface-low text-ink hover:bg-surface-high text-sm font-semibold border border-line"
            title="Text the patient their discharge plan"
          >
            <MessageSquare size={14} /> Text discharge
          </button>
        </div>
        <Button
          variant="primary"
          fullWidth
          onClick={async () => {
            if (!authenticated) return;
            await markSeen(hospitalId, detail.patient_id, "Clinician");
            await onAfterMarkSeen();
          }}
        >
          Mark Seen
        </Button>
      </div>
    </div>
  );
}
