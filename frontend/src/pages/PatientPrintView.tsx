import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Loader2, Printer, X } from "lucide-react";
import { getPatientDetail } from "../lib/api";
import { loadSession } from "../lib/session";
import type { PatientDetail } from "../types";

/**
 * Letter-paper print view of a patient's full clinical record.
 *
 * Opens in a new tab from the dashboard. The on-screen render shows everything
 * + a "Print this page" button. When the user prints, the @media print rules
 * hide the toolbar so the printout is just the clinical content.
 *
 * Authoritative data source: re-fetches via the same /patients/{id} endpoint the
 * dashboard uses, so the print is always current at the moment of export.
 */
export default function PatientPrintView() {
  const { hospitalId = "demo", patientId = "" } = useParams<{
    hospitalId: string;
    patientId: string;
  }>();
  const [detail, setDetail] = useState<PatientDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const sess = loadSession();
    if (!sess) {
      setError("Sign in to the clinician dashboard first, then re-open this print view.");
      setLoading(false);
      return;
    }
    getPatientDetail(hospitalId, patientId, sess.token)
      .then(setDetail)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load record"))
      .finally(() => setLoading(false));
  }, [hospitalId, patientId]);

  // Auto-trigger the print dialog as soon as the record is rendered. Wrapped in
  // a slight delay so the layout settles first; the toolbar is hidden by the
  // @media print rules so the dialog shows just the document.
  useEffect(() => {
    if (!detail) return;
    const t = window.setTimeout(() => window.print(), 350);
    return () => window.clearTimeout(t);
  }, [detail]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-text-muted">
        <Loader2 className="animate-spin mr-2" size={18} /> Loading record…
      </div>
    );
  }
  if (error || !detail) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6 text-center text-error">
        {error || "Record not found."}
      </div>
    );
  }

  const arrived = new Date(detail.created_at).toLocaleString();
  const printedAt = new Date().toLocaleString();

  return (
    <>
      {/* Print-only stylesheet — strips the screen toolbar and resets to letter paper. */}
      <style>{`
        @page { size: letter; margin: 0.6in; }
        @media print {
          .no-print { display: none !important; }
          body { background: white !important; }
          .print-page { box-shadow: none !important; padding: 0 !important; max-width: none !important; }
        }
      `}</style>

      {/* Toolbar — screen only */}
      <div className="no-print sticky top-0 z-10 bg-surface-lowest border-b border-line">
        <div className="max-w-[8.5in] mx-auto flex items-center justify-between px-4 py-3">
          <div className="text-sm text-text-muted">
            Print preview · <span className="font-mono text-ink">{detail.patient_id.slice(0, 8)}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.print()}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md bg-primary text-white text-sm font-semibold"
            >
              <Printer size={14} /> Print
            </button>
            <button
              type="button"
              onClick={() => window.close()}
              className="inline-flex items-center gap-1 h-9 px-3 rounded-md text-sm text-text-muted hover:text-error"
              title="Close tab"
            >
              <X size={14} /> Close
            </button>
          </div>
        </div>
      </div>

      <main
        className="print-page max-w-[8.5in] mx-auto bg-white p-10 my-6 shadow-soft text-ink"
        style={{ fontFamily: "var(--font-sans, 'DM Sans', system-ui, sans-serif)" }}
      >
        {/* Header */}
        <header className="border-b-2 border-ink pb-4 mb-5">
          <div className="flex items-start justify-between gap-6">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-text-muted font-bold">
                Solace · Clinical Encounter Note
              </div>
              <h1 className="text-3xl font-bold tracking-tight mt-1">{detail.name}</h1>
              <div className="text-sm text-text-muted mt-1">
                Hospital: <span className="text-ink font-mono">{hospitalId}</span> ·
                Encounter: <span className="text-ink font-mono">{detail.patient_id.slice(0, 8)}</span>
              </div>
            </div>
            <div className="text-right text-[11px] text-text-muted leading-tight">
              <div>Arrived: <span className="text-ink font-mono">{arrived}</span></div>
              <div>Printed: <span className="text-ink font-mono">{printedAt}</span></div>
              <div>Language: <span className="text-ink font-mono">{(detail.language || "en").toUpperCase()}</span></div>
              <div className="mt-2">
                <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider font-bold bg-error text-white">
                  AI draft — clinician verification required
                </span>
              </div>
            </div>
          </div>
        </header>

        {/* Triage acuity */}
        <Section title="Triage Acuity">
          <table className="w-full text-sm">
            <tbody>
              <tr>
                <td className="font-semibold text-text-muted w-40 align-top py-1">Provisional ESI</td>
                <td className="py-1">
                  <span className="font-bold text-primary">ESI {detail.esi_level}</span>
                  {detail.esi_confidence != null && (
                    <span className="text-text-muted font-mono ml-2">
                      ({(detail.esi_confidence * 100).toFixed(0)}% conf)
                    </span>
                  )}
                </td>
              </tr>
              {detail.refined_esi_level && (
                <tr>
                  <td className="font-semibold text-text-muted align-top py-1">Refined ESI (ML)</td>
                  <td className="py-1">
                    <span className="font-bold text-primary">ESI {detail.refined_esi_level}</span>
                    {detail.refined_confidence != null && (
                      <span className="text-text-muted font-mono ml-2">
                        ({(detail.refined_confidence * 100).toFixed(0)}% conf)
                      </span>
                    )}
                  </td>
                </tr>
              )}
              {detail.clinical_flags?.length > 0 && (
                <tr>
                  <td className="font-semibold text-text-muted align-top py-1">Flags</td>
                  <td className="py-1">{detail.clinical_flags.join(", ")}</td>
                </tr>
              )}
              {detail.triage_recommendation && (
                <tr>
                  <td className="font-semibold text-text-muted align-top py-1">Recommendation</td>
                  <td className="py-1">{detail.triage_recommendation}</td>
                </tr>
              )}
            </tbody>
          </table>
        </Section>

        {/* Pre-brief */}
        {detail.clinician_prebrief && (
          <Section title="Pre-brief">
            <p className="text-[14px] leading-relaxed">{detail.clinician_prebrief}</p>
          </Section>
        )}

        {/* Scribe note */}
        {detail.clinical_scribe_note && (
          <Section title="Clinical Scribe Note (AI draft)">
            <pre className="whitespace-pre-wrap text-[13px] leading-relaxed font-mono">
              {detail.clinical_scribe_note}
            </pre>
          </Section>
        )}

        {/* Differential */}
        {detail.differential?.length > 0 && (
          <Section title="Differential Diagnosis">
            <ol className="list-decimal list-inside space-y-2 text-[13px]">
              {detail.differential.map((d, i) => (
                <li key={i}>
                  <span className="font-bold">{d.diagnosis}</span>
                  {d.icd10 && <span className="ml-2 font-mono text-text-muted">[{d.icd10}]</span>}
                  <span className="ml-2 text-text-muted uppercase text-[10px] font-semibold tracking-wider">
                    {d.likelihood}
                  </span>
                  {d.must_not_miss && (
                    <span className="ml-2 inline-block px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider font-bold bg-error text-white">
                      must not miss
                    </span>
                  )}
                  {(d.rule_in?.length > 0 || d.rule_out?.length > 0) && (
                    <div className="ml-5 mt-1 grid grid-cols-2 gap-x-6 text-[12px]">
                      {d.rule_in?.length > 0 && (
                        <div>
                          <span className="text-text-muted font-semibold uppercase text-[10px] tracking-wider">
                            Rule-in
                          </span>
                          <ul className="list-disc list-inside">
                            {d.rule_in.map((x, j) => <li key={j}>{x}</li>)}
                          </ul>
                        </div>
                      )}
                      {d.rule_out?.length > 0 && (
                        <div>
                          <span className="text-text-muted font-semibold uppercase text-[10px] tracking-wider">
                            Rule-out
                          </span>
                          <ul className="list-disc list-inside">
                            {d.rule_out.map((x, j) => <li key={j}>{x}</li>)}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </Section>
        )}

        {/* Workup */}
        {detail.workup_orders &&
          (detail.workup_orders.labs?.length > 0 ||
            detail.workup_orders.imaging?.length > 0 ||
            detail.workup_orders.monitoring?.length > 0 ||
            detail.workup_orders.consults?.length > 0) && (
            <Section title="Workup Order Set">
              <table className="w-full text-[13px]">
                <tbody>
                  {detail.workup_orders.labs?.length > 0 && (
                    <OrderRow label="Labs" items={detail.workup_orders.labs} />
                  )}
                  {detail.workup_orders.imaging?.length > 0 && (
                    <OrderRow label="Imaging" items={detail.workup_orders.imaging} />
                  )}
                  {detail.workup_orders.monitoring?.length > 0 && (
                    <OrderRow label="Monitoring" items={detail.workup_orders.monitoring} />
                  )}
                  {detail.workup_orders.consults?.length > 0 && (
                    <OrderRow label="Consults" items={detail.workup_orders.consults} />
                  )}
                </tbody>
              </table>
              {detail.workup_orders.rationale && (
                <p className="text-[12px] text-text-muted italic mt-2">
                  {detail.workup_orders.rationale}
                </p>
              )}
            </Section>
          )}

        {/* Disposition */}
        {detail.disposition?.disposition && (
          <Section title="Disposition">
            <table className="w-full text-[13px]">
              <tbody>
                <tr>
                  <td className="font-semibold text-text-muted w-40 align-top py-1">Disposition</td>
                  <td className="py-1 uppercase font-bold">{detail.disposition.disposition}</td>
                </tr>
                {detail.disposition.level_of_care && (
                  <tr>
                    <td className="font-semibold text-text-muted align-top py-1">Level of care</td>
                    <td className="py-1">{detail.disposition.level_of_care}</td>
                  </tr>
                )}
                {detail.disposition.expected_los_hours > 0 && (
                  <tr>
                    <td className="font-semibold text-text-muted align-top py-1">Expected LOS</td>
                    <td className="py-1 font-mono">~{detail.disposition.expected_los_hours} hours</td>
                  </tr>
                )}
                {detail.disposition.rationale && (
                  <tr>
                    <td className="font-semibold text-text-muted align-top py-1">Rationale</td>
                    <td className="py-1">{detail.disposition.rationale}</td>
                  </tr>
                )}
                {detail.disposition.discharge_criteria?.length > 0 && (
                  <tr>
                    <td className="font-semibold text-text-muted align-top py-1">Discharge criteria</td>
                    <td className="py-1">
                      <ul className="list-disc list-inside">
                        {detail.disposition.discharge_criteria.map((c, i) => <li key={i}>{c}</li>)}
                      </ul>
                    </td>
                  </tr>
                )}
                {detail.disposition.return_precautions?.length > 0 && (
                  <tr>
                    <td className="font-semibold text-text-muted align-top py-1">Return precautions</td>
                    <td className="py-1">
                      <ul className="list-disc list-inside">
                        {detail.disposition.return_precautions.map((c, i) => <li key={i}>{c}</li>)}
                      </ul>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Section>
        )}

        {/* Prescriptions */}
        {detail.prescriptions?.length > 0 && (
          <Section title="Prescriptions">
            <table className="w-full text-[13px] border-collapse">
              <thead>
                <tr className="border-b border-text-muted">
                  <th className="text-left py-1 font-semibold">Drug</th>
                  <th className="text-left py-1 font-semibold">Dose</th>
                  <th className="text-left py-1 font-semibold">Route</th>
                  <th className="text-left py-1 font-semibold">Frequency</th>
                  <th className="text-left py-1 font-semibold">Indication</th>
                </tr>
              </thead>
              <tbody>
                {detail.prescriptions.map((p) => (
                  <tr key={p.prescription_id} className="border-b border-line">
                    <td className="py-1.5 font-semibold">{p.drug}</td>
                    <td className="py-1.5 font-mono">{p.dose}</td>
                    <td className="py-1.5 font-mono">{p.route}</td>
                    <td className="py-1.5 font-mono">{p.frequency}</td>
                    <td className="py-1.5">{p.indication}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        )}

        {/* Reported history */}
        {detail.medical_info && (
          <Section title="Reported History">
            <ReportedHistory info={detail.medical_info} />
          </Section>
        )}

        {/* Insurance */}
        {detail.insurance_info && (
          <Section title="Insurance">
            <table className="w-full text-[13px]">
              <tbody>
                <InsRow label="Insurer" value={detail.insurance_info.provider} />
                <InsRow label="Plan" value={detail.insurance_info.plan_name} />
                <InsRow label="Member ID" value={detail.insurance_info.member_id} mono />
                <InsRow label="Group" value={detail.insurance_info.group_number} mono />
                <InsRow label="Name on card" value={detail.insurance_info.name_on_card} />
                <InsRow label="BIN" value={detail.insurance_info.bin} mono />
                <InsRow label="PCN" value={detail.insurance_info.pcn} mono />
                <InsRow label="Rx group" value={detail.insurance_info.rx_group} mono />
                <InsRow label="Effective" value={detail.insurance_info.effective_date} />
                <InsRow label="Phone" value={detail.insurance_info.phone} mono />
              </tbody>
            </table>
          </Section>
        )}

        {/* Transcript */}
        {detail.transcript && (
          <Section title="Patient transcript (verbatim)">
            <p className="text-[13px] leading-relaxed italic">"{detail.transcript}"</p>
          </Section>
        )}

        {/* Follow-up Q&A */}
        {detail.followup_qa?.length > 0 && (
          <Section title="Follow-up Q&A">
            <ul className="space-y-1.5 text-[13px]">
              {detail.followup_qa.map((qa, i) => (
                <li key={i}>
                  <span className="text-text-muted">Q.</span> {qa.question}
                  <br />
                  <span className="text-text-muted">A.</span> <span className="font-mono">{qa.answer}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Clinician notes */}
        {detail.notes?.length > 0 && (
          <Section title="Clinician Notes">
            {detail.notes.map((n) => (
              <div key={n.note_id} className="mb-3 text-[13px]">
                <div className="text-[10px] uppercase tracking-wider text-text-muted">
                  {n.author} · {new Date(n.created_at).toLocaleString()}
                </div>
                <div className="leading-relaxed mt-0.5">{n.text}</div>
              </div>
            ))}
          </Section>
        )}

        {/* Footer signature line */}
        <footer className="mt-10 pt-6 border-t border-text-muted text-[12px] text-text-muted">
          <div className="grid grid-cols-2 gap-8">
            <div>
              <div className="border-b border-ink pb-1 mb-1 h-10" />
              <div>Clinician signature</div>
            </div>
            <div>
              <div className="border-b border-ink pb-1 mb-1 h-10" />
              <div>Date / time</div>
            </div>
          </div>
          <div className="mt-4 text-[10px] leading-relaxed">
            Generated by Solace · AI-assisted clinical documentation. All AI-drafted content
            (pre-brief, scribe note, differential, workup, disposition, prescription suggestions)
            requires clinician verification before any care decision is made.
          </div>
        </footer>
      </main>
    </>
  );
}

// -- helpers --------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5 break-inside-avoid">
      <div className="text-[11px] uppercase tracking-wider text-text-muted font-bold border-b border-text-muted pb-1 mb-2">
        {title}
      </div>
      {children}
    </section>
  );
}

function OrderRow({ label, items }: { label: string; items: string[] }) {
  return (
    <tr>
      <td className="font-semibold text-text-muted w-32 align-top py-1">{label}</td>
      <td className="py-1">{items.join(" · ")}</td>
    </tr>
  );
}

function InsRow({ label, value, mono }: { label: string; value: string | null | undefined; mono?: boolean }) {
  if (!value) return null;
  return (
    <tr>
      <td className="font-semibold text-text-muted w-32 align-top py-0.5">{label}</td>
      <td className={`py-0.5 ${mono ? "font-mono" : ""}`}>{value}</td>
    </tr>
  );
}

function ReportedHistory({ info }: { info: NonNullable<PatientDetail["medical_info"]> }) {
  const filt = (list: string[] | undefined) =>
    (list || []).filter((x) => x && x.toLowerCase() !== "none");
  const parts: { label: string; value: string }[] = [];
  if (info.age != null) parts.push({ label: "Age", value: `${info.age} years` });
  if (info.sex) parts.push({ label: "Sex", value: info.sex });
  if (info.pregnant) {
    parts.push({
      label: "Pregnancy",
      value: info.gestational_weeks ? `${info.gestational_weeks} weeks` : "yes",
    });
  }
  if (info.smoker != null) parts.push({ label: "Smoker", value: info.smoker ? "yes" : "no" });

  const allergies = filt(info.allergies);
  if (allergies.length) {
    const labeled = allergies.map((a) => {
      const sev = info.allergy_severity?.[a];
      return sev ? `${a} (${sev})` : a;
    });
    parts.push({ label: "Allergies", value: labeled.join(", ") });
  }
  const meds = filt(info.medications);
  if (meds.length) {
    const labeled = meds.map((m) =>
      m === "Blood thinners" && info.blood_thinner_name ? `${m} (${info.blood_thinner_name})` : m
    );
    parts.push({ label: "Medications", value: labeled.join(", ") });
  }
  const conds = filt(info.conditions);
  if (conds.length) parts.push({ label: "Conditions", value: conds.join(", ") });

  return (
    <table className="w-full text-[13px]">
      <tbody>
        {parts.map((p) => (
          <tr key={p.label}>
            <td className="font-semibold text-text-muted w-32 align-top py-0.5">{p.label}</td>
            <td className="py-0.5">{p.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
