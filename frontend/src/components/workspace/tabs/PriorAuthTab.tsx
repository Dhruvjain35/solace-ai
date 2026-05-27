import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Braces,
  CheckCircle2,
  FileCheck2,
  FileText,
  Gavel,
  Loader2,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import { paPacket } from "../../../lib/api";
import {
  paCompleteness,
  paHumanPacket,
  paDaVinciBundle,
  paAppeal,
  type Completeness,
  type HumanPacket,
  type FhirBundle,
  type Appeal,
  type PaPacket,
} from "../../../lib/api-inbox";

const inputClass =
  "w-full px-3 py-2 rounded-md border border-line bg-surface-lowest text-sm text-ink " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:border-primary";

const labelClass = "text-xs font-medium text-text-muted";

const primaryBtn =
  "flex items-center gap-1.5 h-11 px-4 rounded-md bg-primary text-surface-lowest text-sm font-medium " +
  "hover:bg-primary-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-primary/40 focus-visible:ring-offset-2 transition-colors";

const ghostBtn =
  "flex items-center gap-1.5 h-11 px-4 rounded-md border border-line bg-surface-lowest text-sm " +
  "text-ink hover:bg-surface-low disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-primary/40 focus-visible:ring-offset-2 transition-colors";

const sectionLabel = "text-xs font-semibold uppercase tracking-editorial text-text-muted";

const DENIAL_CATEGORIES = [
  "medical_necessity",
  "missing_documentation",
  "coding_error",
  "non_covered_benefit",
  "experimental",
  "other",
];

/** PriorAuthTab — prior-authorization workflow for the workspace patient.
 * The clinician confirms the order; patient identity + chart come from context. */
export default function PriorAuthTab() {
  const { hospitalId, patientId, patient, loading, error } = usePatientWorkspace();

  // --- Order fields (prefilled from chart, clinician-editable) ----------------
  const [note, setNote] = useState("");
  const [diagnosis, setDiagnosis] = useState("");
  const [icd10, setIcd10] = useState("");
  const [requested, setRequested] = useState("");
  const [code, setCode] = useState("");
  const [prefilled, setPrefilled] = useState(false);

  const [packet, setPacket] = useState<PaPacket | null>(null);
  const [packetRaw, setPacketRaw] = useState<Record<string, unknown> | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildErr, setBuildErr] = useState("");

  // Prefill order fields from the loaded chart once the patient resolves.
  const chartSeed = useMemo(() => {
    if (!patient) return null;
    return {
      note: patient.clinical_scribe_note || patient.transcript || "",
      diagnosis: patient.triage_recommendation || "",
      requested: patient.workup_orders?.imaging?.[0] || "",
    };
  }, [patient]);

  if (patient && chartSeed && !prefilled) {
    setNote(chartSeed.note);
    setDiagnosis(chartSeed.diagnosis);
    setRequested(chartSeed.requested);
    setPrefilled(true);
  }

  // --- Guard rendering --------------------------------------------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 animate-spin text-text-muted" aria-hidden="true" />
        <span className="sr-only">Loading patient</span>
      </div>
    );
  }

  if (error || !patient) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <AlertTriangle size={28} className="mx-auto mb-3 text-error" aria-hidden="true" />
          <h2 className="text-lg font-bold tracking-tight text-ink">Prior Authorization</h2>
          <p className="text-text-muted text-sm mt-1">
            {error || "This patient record could not be loaded."}
          </p>
        </div>
      </div>
    );
  }

  const ins = patient.insurance_info;
  const med = patient.medical_info;

  const buildPacket = async () => {
    setBuilding(true);
    setBuildErr("");
    try {
      const res = (await paPacket(hospitalId, {
        note_text: note,
        diagnosis,
        icd10,
        requested_service: requested,
        cpt_or_hcpcs_or_ndc: code,
        patient: {
          name: patient.name,
          patient_id: patientId,
          age: med?.age ?? undefined,
          sex: med?.sex ?? undefined,
          member_id: ins?.member_id ?? undefined,
        },
        payer: { name: ins?.provider ?? undefined, plan_name: ins?.plan_name ?? undefined },
      })) as { packet?: PaPacket; fhir_claim?: unknown } & Record<string, unknown>;
      setPacketRaw(res);
      setPacket(res.packet ?? null);
      if (!res.packet) {
        setBuildErr("The PA packet came back empty. Check the order fields and try again.");
      }
    } catch {
      setBuildErr("Could not assemble the PA packet. Try again in a moment.");
    } finally {
      setBuilding(false);
    }
  };

  return (
    <div className="space-y-4 pb-8">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-primary-dim p-2">
          <ShieldCheck size={20} className="text-primary" aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-editorial text-ink">Prior Authorization</h2>
          <p className="text-text-muted text-sm">
            Assemble and submit a payer authorization packet for{" "}
            <span className="font-medium text-ink">{patient.name}</span>.
          </p>
        </div>
      </div>

      {/* Patient identity (from chart, read-only) */}
      <div className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4">
        <div className={sectionLabel}>Patient and coverage</div>
        <dl className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-2 text-sm">
          <div>
            <dt className="text-xs text-text-muted">Patient</dt>
            <dd className="text-ink font-medium">{patient.name}</dd>
          </div>
          <div>
            <dt className="text-xs text-text-muted">Age / Sex</dt>
            <dd className="text-ink">
              {med?.age ?? "—"} / {med?.sex ?? "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-text-muted">Payer</dt>
            <dd className="text-ink">{ins?.provider || "Not on file"}</dd>
          </div>
          <div>
            <dt className="text-xs text-text-muted">Member ID</dt>
            <dd className="text-ink font-mono text-xs">{ins?.member_id || "Not on file"}</dd>
          </div>
        </dl>
        {!ins?.member_id && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-warning">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
            No insurance on file — the readiness check will likely flag this as a blocker.
          </p>
        )}
      </div>

      {/* Order entry / confirmation */}
      <div className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4 space-y-3">
        <div className={sectionLabel}>Confirm the order</div>
        <div>
          <label htmlFor="pa-note" className={labelClass}>
            Encounter note
          </label>
          <textarea
            id="pa-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="Clinical rationale supporting the requested service"
            className={`mt-1 ${inputClass}`}
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label htmlFor="pa-diagnosis" className={labelClass}>
              Diagnosis
            </label>
            <input
              id="pa-diagnosis"
              value={diagnosis}
              onChange={(e) => setDiagnosis(e.target.value)}
              placeholder="e.g. Lumbar radiculopathy"
              className={`mt-1 ${inputClass}`}
            />
          </div>
          <div>
            <label htmlFor="pa-icd10" className={labelClass}>
              ICD-10 code
            </label>
            <input
              id="pa-icd10"
              value={icd10}
              onChange={(e) => setIcd10(e.target.value)}
              placeholder="e.g. M54.16"
              className={`mt-1 ${inputClass}`}
            />
          </div>
          <div>
            <label htmlFor="pa-requested" className={labelClass}>
              Requested service
            </label>
            <input
              id="pa-requested"
              value={requested}
              onChange={(e) => setRequested(e.target.value)}
              placeholder="e.g. MRI lumbar spine without contrast"
              className={`mt-1 ${inputClass}`}
            />
          </div>
          <div>
            <label htmlFor="pa-code" className={labelClass}>
              CPT / HCPCS / NDC
            </label>
            <input
              id="pa-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. 72148"
              className={`mt-1 ${inputClass}`}
            />
          </div>
        </div>
        <button
          type="button"
          onClick={buildPacket}
          disabled={building || !requested.trim()}
          className={primaryBtn}
        >
          {building ? (
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
          ) : (
            <FileText className="w-4 h-4" aria-hidden="true" />
          )}
          {building ? "Assembling…" : "Assemble PA packet"}
        </button>
        {buildErr && (
          <div className="text-xs text-error" role="alert">
            {buildErr}
          </div>
        )}
      </div>

      {/* Assembled packet preview */}
      {packetRaw && (
        <div
          className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4"
          role="status"
          aria-live="polite"
        >
          <div className={sectionLabel}>Assembled packet</div>
          {getNarrative(packetRaw) && (
            <>
              <div className="mt-2 text-xs text-text-muted">Clinical rationale</div>
              <pre className="mt-1 text-xs text-ink bg-surface-low rounded-md p-2 whitespace-pre-wrap">
                {getNarrative(packetRaw)}
              </pre>
            </>
          )}
          {getChannels(packetRaw).length > 0 && (
            <>
              <div className="mt-3 text-xs text-text-muted">Submission channels</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {getChannels(packetRaw).map((c, i) => (
                  <span
                    key={i}
                    className="text-xs px-2 py-0.5 rounded bg-surface-low text-ink"
                  >
                    {c.channel}: {c.status}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Packet follow-up actions */}
      {packet && <PAFollowUp hospitalId={hospitalId} packet={packet} />}
    </div>
  );
}

// --- Packet field readers (server-owned shape, read defensively) -------------
function getNarrative(raw: Record<string, unknown>): string {
  const packet = raw.packet as Record<string, unknown> | undefined;
  const narrative = packet?.narrative as Record<string, unknown> | undefined;
  const r = narrative?.clinical_rationale;
  return typeof r === "string" ? r : "";
}

function getChannels(raw: Record<string, unknown>): { channel: string; status: string }[] {
  const packet = raw.packet as Record<string, unknown> | undefined;
  const channels = packet?.submission_channels;
  if (!Array.isArray(channels)) return [];
  return channels
    .filter((c): c is Record<string, unknown> => typeof c === "object" && c !== null)
    .map((c) => ({
      channel: String(c.channel ?? "channel"),
      status: String(c.status ?? "unknown"),
    }));
}

// --- Follow-up: completeness, human packet, FHIR bundle, appeal --------------
function PAFollowUp({ hospitalId, packet }: { hospitalId: string; packet: PaPacket }) {
  const [completeness, setCompleteness] = useState<Completeness | null>(null);
  const [human, setHuman] = useState<HumanPacket | null>(null);
  const [bundle, setBundle] = useState<FhirBundle | null>(null);
  const [busy, setBusy] = useState<"" | "completeness" | "human" | "bundle">("");
  const [err, setErr] = useState("");

  const runCompleteness = async () => {
    setBusy("completeness");
    setErr("");
    try {
      setCompleteness(await paCompleteness(hospitalId, packet));
    } catch {
      setErr("Could not run the readiness check. Try again in a moment.");
    } finally {
      setBusy("");
    }
  };
  const runHuman = async () => {
    setBusy("human");
    setErr("");
    try {
      setHuman(await paHumanPacket(hospitalId, packet));
    } catch {
      setErr("Could not assemble the formatted packet. Try again in a moment.");
    } finally {
      setBusy("");
    }
  };
  const runBundle = async () => {
    setBusy("bundle");
    setErr("");
    try {
      setBundle(await paDaVinciBundle(hospitalId, packet));
    } catch {
      setErr("Could not build the FHIR bundle. Try again in a moment.");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4">
        <div className={sectionLabel}>Packet actions</div>
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={runCompleteness}
            disabled={busy !== ""}
            className={ghostBtn}
          >
            {busy === "completeness" ? (
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            ) : (
              <FileCheck2 className="w-4 h-4" aria-hidden="true" />
            )}
            Check readiness
          </button>
          <button type="button" onClick={runHuman} disabled={busy !== ""} className={ghostBtn}>
            {busy === "human" ? (
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            ) : (
              <FileText className="w-4 h-4" aria-hidden="true" />
            )}
            Formatted packet
          </button>
          <button type="button" onClick={runBundle} disabled={busy !== ""} className={ghostBtn}>
            {busy === "bundle" ? (
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            ) : (
              <Braces className="w-4 h-4" aria-hidden="true" />
            )}
            FHIR bundle
          </button>
        </div>
        {err && (
          <div className="mt-2 text-xs text-error" role="alert">
            {err}
          </div>
        )}
      </div>

      {/* Completeness / readiness */}
      {completeness && (
        <div
          className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center justify-between mb-3">
            <div className={sectionLabel}>Submission readiness</div>
            <div
              className={`text-xs px-2 py-0.5 rounded font-medium ${
                completeness.ready_to_submit
                  ? "bg-success-container text-success"
                  : "bg-warning-container text-warning"
              }`}
            >
              {completeness.ready_to_submit ? "Ready to submit" : "Not ready"}
            </div>
          </div>
          <div className="flex items-center gap-3 mb-3">
            <div className="flex-1 h-2 rounded-full bg-surface-high overflow-hidden">
              <div
                className={`h-full rounded-full ${
                  completeness.score >= 80
                    ? "bg-success"
                    : completeness.score >= 50
                      ? "bg-warning"
                      : "bg-error"
                }`}
                style={{ width: `${Math.max(0, Math.min(100, completeness.score))}%` }}
              />
            </div>
            <div className="text-sm font-semibold tabular-nums text-ink">
              {completeness.score}/100
            </div>
          </div>
          {completeness.blockers?.length > 0 && (
            <div className="space-y-1.5 mb-2">
              <div className="text-xs font-semibold uppercase tracking-editorial text-error">
                Blockers
              </div>
              {completeness.blockers.map((b, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 text-xs bg-error-container rounded-md p-2"
                >
                  <XCircle
                    className="w-3.5 h-3.5 text-error mt-0.5 shrink-0"
                    aria-hidden="true"
                  />
                  <div className="text-ink">
                    <b>{b.field}</b> — {b.message}
                    <div className="text-error mt-0.5">Fix: {b.fix}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {completeness.warnings?.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs font-semibold uppercase tracking-editorial text-warning">
                Warnings
              </div>
              {completeness.warnings.map((w, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 text-xs bg-warning-container rounded-md p-2"
                >
                  <AlertTriangle
                    className="w-3.5 h-3.5 text-warning mt-0.5 shrink-0"
                    aria-hidden="true"
                  />
                  <div className="text-ink">
                    {w.field ? <b>{w.field} — </b> : null}
                    {w.message}
                  </div>
                </div>
              ))}
            </div>
          )}
          {completeness.blockers?.length === 0 && completeness.warnings?.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-success">
              <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />
              No blockers or warnings — packet is clean.
            </div>
          )}
        </div>
      )}

      {/* Formatted human packet */}
      {human && (
        <div
          className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center justify-between mb-1">
            <div className="text-base font-semibold text-ink">{human.title}</div>
            <div className="text-xs px-2 py-0.5 rounded bg-surface-low text-ink">
              {human.completeness}% complete
            </div>
          </div>
          <div className="text-xs text-text-muted mb-3">Generated {human.generated_at}</div>
          <div className="space-y-3">
            {human.sections?.map((s, i) => (
              <div key={i}>
                <div className={sectionLabel}>{s.heading}</div>
                <div className="mt-1 whitespace-pre-wrap text-sm text-ink">{s.body}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-line whitespace-pre-wrap text-sm text-text-muted">
            {human.signature_block}
          </div>
        </div>
      )}

      {/* FHIR bundle */}
      {bundle && (
        <div
          className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4"
          role="status"
          aria-live="polite"
        >
          <div className={sectionLabel}>
            Da Vinci FHIR Bundle ({bundle.type || "collection"})
          </div>
          {bundle.entry && bundle.entry.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {bundle.entry.map((e, i) => (
                <span key={i} className="text-xs px-2 py-0.5 rounded bg-surface-low text-ink">
                  {e.resource?.resourceType || "Resource"}
                </span>
              ))}
            </div>
          )}
          <pre className="mt-2 text-xs text-ink bg-surface-low rounded-md p-2 max-h-80 overflow-auto">
            {JSON.stringify(bundle, null, 2)}
          </pre>
        </div>
      )}

      <DenialAppeal hospitalId={hospitalId} packet={packet} />
    </div>
  );
}

// --- Denial appeal form ------------------------------------------------------
function DenialAppeal({ hospitalId, packet }: { hospitalId: string; packet: PaPacket }) {
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState("medical_necessity");
  const [date, setDate] = useState("");
  const [context, setContext] = useState("");
  const [appeal, setAppeal] = useState<Appeal | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    setBusy(true);
    setErr("");
    try {
      setAppeal(
        await paAppeal(hospitalId, {
          packet,
          denial_reason: reason,
          denial_category: category || undefined,
          denial_date: date ? new Date(date).toISOString() : undefined,
          appeal_level: "first",
          additional_context: context || undefined,
        }),
      );
    } catch {
      setErr("Could not generate the appeal letter. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-surface-lowest rounded-xl shadow-soft border border-line p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Gavel className="w-4 h-4 text-text-muted" aria-hidden="true" />
        <span className={sectionLabel}>Denial appeal</span>
      </div>
      <p className="text-xs text-text-muted">
        If the payer denies this request, draft a first-level appeal letter grounded in the
        assembled packet.
      </p>
      <div>
        <label htmlFor="appeal-reason" className={labelClass}>
          Denial reason (as stated by payer)
        </label>
        <textarea
          id="appeal-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          placeholder="e.g. Service deemed not medically necessary"
          className={`mt-1 ${inputClass}`}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label htmlFor="appeal-category" className={labelClass}>
            Denial category
          </label>
          <select
            id="appeal-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className={`mt-1 ${inputClass}`}
          >
            {DENIAL_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="appeal-date" className={labelClass}>
            Denial date
          </label>
          <input
            id="appeal-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className={`mt-1 ${inputClass}`}
          />
        </div>
      </div>
      <div>
        <label htmlFor="appeal-context" className={labelClass}>
          Additional context (optional)
        </label>
        <textarea
          id="appeal-context"
          value={context}
          onChange={(e) => setContext(e.target.value)}
          rows={2}
          placeholder="New labs, imaging, or clinical updates since the original request"
          className={`mt-1 ${inputClass}`}
        />
      </div>
      <button
        type="button"
        onClick={run}
        disabled={busy || !reason.trim()}
        className={primaryBtn}
      >
        {busy ? (
          <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
        ) : (
          <Gavel className="w-4 h-4" aria-hidden="true" />
        )}
        Draft appeal letter
      </button>
      {err && (
        <div className="text-xs text-error" role="alert">
          {err}
        </div>
      )}
      {appeal && (
        <div className="mt-1 space-y-3" role="status" aria-live="polite">
          <div className="text-xs text-text-muted">
            Appeal ID: <span className="font-mono">{appeal.appeal_id}</span>
          </div>
          <div className="bg-surface-low rounded-md p-3">
            <div className="whitespace-pre-wrap text-sm text-ink">{appeal.letter.header}</div>
            <div className="whitespace-pre-wrap text-sm text-ink mt-2">{appeal.letter.body}</div>
            <div className="whitespace-pre-wrap text-sm text-text-muted mt-2 pt-2 border-t border-line">
              {appeal.letter.signature}
            </div>
          </div>
          {appeal.rebuttal_points?.length > 0 && (
            <div>
              <div className={sectionLabel}>Rebuttal points</div>
              <ul className="mt-1 list-disc pl-5 text-sm text-ink space-y-0.5">
                {appeal.rebuttal_points.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {appeal.additional_evidence_requested?.length > 0 && (
            <div>
              <div className={sectionLabel}>Additional evidence to attach</div>
              <ul className="mt-1 list-disc pl-5 text-sm text-ink space-y-0.5">
                {appeal.additional_evidence_requested.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
