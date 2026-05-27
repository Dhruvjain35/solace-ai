import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  FileText,
  Activity,
  Link2,
  Link2Off,
  Loader2,
  Search,
  ServerCog,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import {
  ehrPatientMatch,
  ehrVendorStatus,
  ehrWriteBack,
} from "../../../lib/api-tools";
import type {
  EhrVendorStatus,
  EhrWriteBackResult,
  FhirResource,
  PatientMatchQuery,
  PatientMatchResult,
} from "../../../lib/api-tools";
import type { PatientDetail } from "../../../types";

/**
 * EhrTab — the EHR-integration payoff of the Patient Workspace.
 *
 * "Resolve once, write everywhere": the patient's chart is matched to the EHR a
 * single time (patient-match flow). After that, every write-back targets the
 * resolved FHIR chart automatically — no manual id entry anywhere in the app.
 */

type WriteKind = "note" | "condition" | "observation";

function readError(e: unknown): string {
  const err = e as { response?: { data?: { detail?: string } }; message?: string };
  return err?.response?.data?.detail || err?.message || "Request failed";
}

/** Build a FHIR Patient-match query from the workspace patient demographics. */
function buildMatchQuery(patient: PatientDetail): PatientMatchQuery {
  const mi = patient.medical_info;
  const [given, ...rest] = (patient.name || "").trim().split(/\s+/);
  const family = rest.join(" ");
  const query: PatientMatchQuery = {};
  if (given) query.given = given;
  if (family) query.family = family;
  if (mi?.sex) query.gender = mi.sex;
  return query;
}

/** A minimal FHIR resource for each one-click write-back, scoped to this chart. */
function buildResource(kind: WriteKind, patient: PatientDetail, fhirId: string): FhirResource {
  const subject = { reference: `Patient/${fhirId}` };
  if (kind === "note") {
    return {
      resourceType: "DocumentReference",
      status: "current",
      type: { text: "Triage note" },
      subject,
      description: `Solace triage note — ESI ${patient.esi_level} (${patient.esi_label})`,
      content: [
        {
          attachment: {
            contentType: "text/plain",
            title: "Solace triage prebrief",
            data: patient.clinician_prebrief || patient.triage_recommendation || "Triage note",
          },
        },
      ],
    };
  }
  if (kind === "condition") {
    const primary = patient.differential?.[0];
    return {
      resourceType: "Condition",
      clinicalStatus: { coding: [{ code: "active" }] },
      verificationStatus: { coding: [{ code: "provisional" }] },
      code: primary
        ? { coding: [{ system: "http://hl7.org/fhir/sid/icd-10", code: primary.icd10 }], text: primary.diagnosis }
        : { text: patient.esi_label },
      subject,
    };
  }
  // observation
  return {
    resourceType: "Observation",
    status: "preliminary",
    code: { text: "ESI acuity level" },
    valueInteger: patient.esi_level,
    subject,
  };
}

const WRITE_ACTIONS: { kind: WriteKind; label: string; desc: string; Icon: typeof FileText }[] = [
  { kind: "note", label: "Triage note", desc: "DocumentReference — triage prebrief", Icon: FileText },
  { kind: "condition", label: "Condition", desc: "Working diagnosis from differential", Icon: ClipboardList },
  { kind: "observation", label: "ESI observation", desc: "Acuity level as an Observation", Icon: Activity },
];

export default function EhrTab() {
  const { hospitalId, patient, loading, error, ehrFhirId, ehrLinked } = usePatientWorkspace();

  // Vendor status
  const [vendor, setVendor] = useState<EhrVendorStatus | null>(null);
  const [vendorBusy, setVendorBusy] = useState(false);
  const [vendorErr, setVendorErr] = useState<string | null>(null);

  // Patient-match flow
  const [matchBusy, setMatchBusy] = useState(false);
  const [matchErr, setMatchErr] = useState<string | null>(null);
  const [matchResult, setMatchResult] = useState<PatientMatchResult | null>(null);

  // Write-back
  const [dryRun, setDryRun] = useState(true);
  const [writeBusy, setWriteBusy] = useState<WriteKind | null>(null);
  const [writeErr, setWriteErr] = useState<string | null>(null);
  const [writeResult, setWriteResult] = useState<{ kind: WriteKind; result: EhrWriteBackResult } | null>(null);

  // A match result that resolved a chart counts as linked for this session.
  const resolvedFromMatch =
    matchResult?.status === "matched"
      ? ((matchResult.patient?.id as string | undefined) ?? null)
      : null;
  const effectiveFhirId = ehrFhirId ?? resolvedFromMatch;
  const isLinked = ehrLinked || resolvedFromMatch != null;

  const loadVendor = useCallback(async () => {
    setVendorBusy(true);
    setVendorErr(null);
    try {
      setVendor(await ehrVendorStatus(hospitalId));
    } catch (e: unknown) {
      setVendorErr(readError(e));
    } finally {
      setVendorBusy(false);
    }
  }, [hospitalId]);

  const runMatch = useCallback(async () => {
    if (!patient) return;
    setMatchBusy(true);
    setMatchErr(null);
    setMatchResult(null);
    try {
      // No local FHIR candidate cache yet — the endpoint resolves against the
      // EHR's own roster. We pass an empty candidate list and the patient's
      // demographics so the matcher can score against the live directory.
      const result = await ehrPatientMatch(hospitalId, buildMatchQuery(patient), []);
      setMatchResult(result);
    } catch (e: unknown) {
      setMatchErr(readError(e));
    } finally {
      setMatchBusy(false);
    }
  }, [hospitalId, patient]);

  const runWriteBack = useCallback(
    async (kind: WriteKind) => {
      if (!patient || !effectiveFhirId) return;
      setWriteBusy(kind);
      setWriteErr(null);
      setWriteResult(null);
      try {
        const resource = buildResource(kind, patient, effectiveFhirId);
        const result = await ehrWriteBack(hospitalId, resource, dryRun);
        setWriteResult({ kind, result });
      } catch (e: unknown) {
        setWriteErr(readError(e));
      } finally {
        setWriteBusy(null);
      }
    },
    [hospitalId, patient, effectiveFhirId, dryRun],
  );

  const matchQueryPreview = useMemo(
    () => (patient ? buildMatchQuery(patient) : null),
    [patient],
  );

  // --- Guards ---------------------------------------------------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted text-sm">
        <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
        Loading patient record…
      </div>
    );
  }
  if (error) {
    return <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>;
  }
  if (!patient) {
    return <div className="text-text-muted text-sm py-8">No patient record available.</div>;
  }

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      {/* EHR-link status ------------------------------------------------- */}
      <section className="bg-surface-lowest rounded-xl shadow-card p-5">
        <div className="flex items-start gap-3">
          {isLinked ? (
            <Link2 size={20} className="text-primary shrink-0 mt-0.5" aria-hidden="true" />
          ) : (
            <Link2Off size={20} className="text-text-muted shrink-0 mt-0.5" aria-hidden="true" />
          )}
          <div className="min-w-0">
            <h2 className="text-lg font-bold tracking-tight">EHR chart link</h2>
            {isLinked ? (
              <>
                <p className="text-sm text-text-muted mt-0.5">
                  {patient.name} is resolved to a live EHR chart. Every write-back below targets
                  this chart automatically — no id entry.
                </p>
                <p className="text-xs font-mono text-text-muted mt-2">
                  FHIR Patient/{effectiveFhirId}
                </p>
              </>
            ) : (
              <p className="text-sm text-text-muted mt-0.5">
                No EHR identity on record for {patient.name}. Resolve this patient against the EHR
                once below — after that, all write-backs target the matched chart.
              </p>
            )}
          </div>
        </div>
      </section>

      {/* Patient-match flow (unlinked only) ------------------------------ */}
      {!isLinked && (
        <section className="bg-surface-lowest rounded-xl shadow-card p-5">
          <h3 className="text-sm font-bold tracking-tight flex items-center gap-2">
            <Search size={16} className="text-text-muted" aria-hidden="true" />
            Resolve patient in the EHR
          </h3>
          <p className="text-xs text-text-muted mt-1">
            Matches on the demographics already on this chart. Resolve once — write everywhere.
          </p>

          {matchQueryPreview && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 mt-3 text-xs">
              <div className="flex justify-between border-b border-line py-1">
                <dt className="text-text-muted">Given</dt>
                <dd className="text-ink font-medium">{matchQueryPreview.given || "—"}</dd>
              </div>
              <div className="flex justify-between border-b border-line py-1">
                <dt className="text-text-muted">Family</dt>
                <dd className="text-ink font-medium">{matchQueryPreview.family || "—"}</dd>
              </div>
              <div className="flex justify-between border-b border-line py-1">
                <dt className="text-text-muted">Gender</dt>
                <dd className="text-ink font-medium">{matchQueryPreview.gender || "—"}</dd>
              </div>
              <div className="flex justify-between border-b border-line py-1">
                <dt className="text-text-muted">Age</dt>
                <dd className="text-ink font-medium">{patient.medical_info?.age ?? "—"}</dd>
              </div>
            </dl>
          )}

          <button
            type="button"
            onClick={runMatch}
            disabled={matchBusy}
            className="mt-4 h-11 px-4 inline-flex items-center justify-center gap-2 rounded-lg bg-primary text-white text-sm font-medium disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
          >
            {matchBusy ? (
              <Loader2 size={16} className="animate-spin" aria-hidden="true" />
            ) : (
              <Search size={16} aria-hidden="true" />
            )}
            {matchBusy ? "Matching…" : "Match patient to EHR"}
          </button>

          {matchErr && (
            <div className="mt-3 p-2.5 rounded-md bg-error-container text-error text-xs">
              {matchErr}
            </div>
          )}

          {matchResult && (
            <div
              className={`mt-3 p-3 rounded-md text-xs ${
                matchResult.status === "matched"
                  ? "bg-surface-low text-ink"
                  : "bg-surface-low text-text-muted"
              }`}
            >
              <p className="flex items-center gap-2 font-medium">
                {matchResult.status === "matched" ? (
                  <CheckCircle2 size={14} className="text-primary" aria-hidden="true" />
                ) : (
                  <AlertTriangle size={14} className="text-text-muted" aria-hidden="true" />
                )}
                {matchResult.status === "matched"
                  ? "Matched"
                  : matchResult.status === "needs_review"
                    ? "Needs review"
                    : "No match"}
                <span className="text-text-muted font-normal">
                  · confidence {Math.round((matchResult.confidence ?? 0) * 100)}%
                </span>
              </p>
              {matchResult.reason && (
                <p className="text-text-muted mt-1">{matchResult.reason}</p>
              )}
              {matchResult.status !== "matched" && (
                <p className="text-text-muted mt-1">
                  Confirm demographics with the patient or search the EHR manually, then retry.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      {/* Vendor status + write-back (linked only) ------------------------ */}
      {isLinked && (
        <>
          <section className="bg-surface-lowest rounded-xl shadow-card p-5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-bold tracking-tight flex items-center gap-2">
                <ServerCog size={16} className="text-text-muted" aria-hidden="true" />
                EHR vendor status
              </h3>
              <button
                type="button"
                onClick={loadVendor}
                disabled={vendorBusy}
                className="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg bg-surface-low text-ink text-xs font-medium disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
              >
                {vendorBusy ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                ) : null}
                {vendor ? "Refresh" : "Check status"}
              </button>
            </div>

            {vendorErr && (
              <div className="mt-3 p-2.5 rounded-md bg-error-container text-error text-xs">
                {vendorErr}
              </div>
            )}

            {vendor && (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 mt-3 text-xs">
                <div className="flex justify-between border-b border-line py-1">
                  <dt className="text-text-muted">Vendor</dt>
                  <dd className="text-ink font-medium">{vendor.vendor}</dd>
                </div>
                <div className="flex justify-between border-b border-line py-1">
                  <dt className="text-text-muted">Backend</dt>
                  <dd className="text-ink font-medium">{vendor.backend}</dd>
                </div>
                <div className="flex justify-between border-b border-line py-1">
                  <dt className="text-text-muted">Online</dt>
                  <dd className={vendor.online ? "text-primary font-medium" : "text-error font-medium"}>
                    {vendor.online ? "Yes" : "No"}
                  </dd>
                </div>
                <div className="flex justify-between border-b border-line py-1">
                  <dt className="text-text-muted">Configured</dt>
                  <dd className={vendor.configured ? "text-primary font-medium" : "text-error font-medium"}>
                    {vendor.configured ? "Yes" : "No"}
                  </dd>
                </div>
              </dl>
            )}
            {!vendor && !vendorErr && !vendorBusy && (
              <p className="text-xs text-text-muted mt-2">
                Check connectivity before writing back to the chart.
              </p>
            )}
          </section>

          <section className="bg-surface-lowest rounded-xl shadow-card p-5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-bold tracking-tight">Write back to this chart</h3>
              <label className="inline-flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={(e) => {
                    setDryRun(e.target.checked);
                    setWriteResult(null);
                    setWriteErr(null);
                  }}
                  className="h-4 w-4 rounded border-line focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                />
                Dry-run preview
              </label>
            </div>
            <p className="text-xs text-text-muted mt-1">
              {dryRun
                ? "Preview the FHIR resource and routing without committing to the EHR."
                : "Live write — the resource will be committed to the matched EHR chart."}
            </p>

            <div className="flex flex-col gap-2 mt-3">
              {WRITE_ACTIONS.map(({ kind, label, desc, Icon }) => (
                <button
                  key={kind}
                  type="button"
                  onClick={() => runWriteBack(kind)}
                  disabled={writeBusy != null}
                  className="h-11 px-3 flex items-center gap-3 rounded-lg bg-surface-low text-left text-ink disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                >
                  {writeBusy === kind ? (
                    <Loader2 size={16} className="animate-spin shrink-0" aria-hidden="true" />
                  ) : (
                    <Icon size={16} className="text-text-muted shrink-0" aria-hidden="true" />
                  )}
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{label}</span>
                    <span className="block text-xs text-text-muted truncate">{desc}</span>
                  </span>
                </button>
              ))}
            </div>

            {writeErr && (
              <div className="mt-3 p-2.5 rounded-md bg-error-container text-error text-xs">
                {writeErr}
              </div>
            )}

            {writeResult && (
              <div className="mt-3 p-3 rounded-md bg-surface-low text-xs">
                <p className="flex items-center gap-2 font-medium text-ink">
                  <CheckCircle2 size={14} className="text-primary" aria-hidden="true" />
                  {writeResult.result.dry_run ? "Dry-run preview" : "Written to EHR"}
                  <span className="text-text-muted font-normal">
                    · {WRITE_ACTIONS.find((a) => a.kind === writeResult.kind)?.label}
                  </span>
                </p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2">
                  <div className="flex justify-between border-b border-line py-1">
                    <dt className="text-text-muted">Resource</dt>
                    <dd className="text-ink font-medium">
                      {writeResult.result.resource_type ||
                        buildResource(writeResult.kind, patient, effectiveFhirId ?? "").resourceType}
                    </dd>
                  </div>
                  <div className="flex justify-between border-b border-line py-1">
                    <dt className="text-text-muted">Routed to</dt>
                    <dd className="text-ink font-medium font-mono truncate">
                      {writeResult.result.routed_to || `Patient/${effectiveFhirId}`}
                    </dd>
                  </div>
                  {writeResult.result.vendor && (
                    <div className="flex justify-between border-b border-line py-1">
                      <dt className="text-text-muted">Vendor</dt>
                      <dd className="text-ink font-medium">{writeResult.result.vendor}</dd>
                    </div>
                  )}
                  {writeResult.result.id && (
                    <div className="flex justify-between border-b border-line py-1">
                      <dt className="text-text-muted">Resource id</dt>
                      <dd className="text-ink font-medium font-mono truncate">
                        {writeResult.result.id}
                      </dd>
                    </div>
                  )}
                </dl>
                {writeResult.result.url && (
                  <p className="text-text-muted font-mono mt-2 truncate">{writeResult.result.url}</p>
                )}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

EhrTab.displayName = "EhrTab";
