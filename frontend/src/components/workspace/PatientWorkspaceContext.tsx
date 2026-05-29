/**
 * PatientWorkspaceContext — shared per-patient state for the Patient Workspace.
 *
 * ─────────────────────────────────────────────────────────────────────────
 * TAB CONTRACT (read this before filling a tab in the next phase)
 * ─────────────────────────────────────────────────────────────────────────
 *
 * Every tab component lives in `frontend/src/components/workspace/tabs/` and is
 * rendered INSIDE `<PatientWorkspaceProvider>`. A tab never receives props — it
 * pulls everything it needs from the workspace context:
 *
 *     import { usePatientWorkspace } from "../PatientWorkspaceContext";
 *
 *     export default function XTab() {
 *       const { hospitalId, patientId, patient, loading, error,
 *               reloadPatient, ehrFhirId, ehrLinked } = usePatientWorkspace();
 *       ...
 *     }
 *
 * Context fields:
 *   - hospitalId   : string         — route hospital id (e.g. "demo"). Pass to
 *                                     every lib/api.ts call.
 *   - patientId    : string         — route patient id. Pass to every
 *                                     per-patient lib/api.ts call.
 *   - patient      : PatientDetail | null
 *                                   — full loaded patient record, or null while
 *                                     loading / on error. Always null-check.
 *   - loading      : boolean        — true while the initial fetch is in flight.
 *   - error        : string | null  — human-readable load error, or null.
 *   - reloadPatient: () => void     — re-fetch the patient record. Call this
 *                                     after a tab mutates patient data (vitals,
 *                                     notes, disposition, mark-seen, etc.) so
 *                                     the sticky header and other tabs refresh.
 *   - ehrFhirId    : string | null  — the patient's FHIR resource id if the
 *                                     record carries one; null otherwise.
 *   - ehrLinked    : boolean        — true when an EHR FHIR identity is present.
 *                                     EHR-dependent tabs should gate on this.
 *
 * Rules for the 8 parallel agents filling tabs:
 *   1. Do NOT add props to a tab. Read context only.
 *   2. Do NOT fetch the patient record yourself — use `patient`. Fetch only
 *      tool-specific sub-resources via lib/api.ts.
 *   3. After any write that changes the patient record, call `reloadPatient()`.
 *   4. Guard rendering on `loading` / `error` / `patient == null` first.
 *   5. Keep relative imports (no `@/` alias) and match repo design tokens.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getPatientDetail } from "../../lib/api";
import type { PatientDetail } from "../../types";

/** Optional EHR identity fields that may ride on the patient record but are not
 * yet part of the PatientDetail type. Read defensively. */
type EhrIdentityCarrier = {
  ehr_fhir_id?: string | null;
  fhir_id?: string | null;
  ehr_patient_id?: string | null;
};

export type PatientWorkspaceValue = {
  hospitalId: string;
  patientId: string;
  patient: PatientDetail | null;
  loading: boolean;
  error: string | null;
  reloadPatient: () => void;
  ehrFhirId: string | null;
  ehrLinked: boolean;
};

const PatientWorkspaceContext = createContext<PatientWorkspaceValue | null>(null);

/** Derive a FHIR identity from whatever EHR-id-shaped field the record carries. */
function deriveEhrFhirId(patient: PatientDetail | null): string | null {
  if (!patient) return null;
  const carrier = patient as PatientDetail & EhrIdentityCarrier;
  return carrier.ehr_fhir_id || carrier.fhir_id || carrier.ehr_patient_id || null;
}

type ProviderProps = {
  hospitalId: string;
  patientId: string;
  authenticated: boolean;
  children: React.ReactNode;
};

export function PatientWorkspaceProvider({
  hospitalId,
  patientId,
  authenticated,
  children,
}: ProviderProps) {
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState<number>(0);

  const reloadPatient = useCallback(() => {
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!authenticated || !patientId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPatientDetail(hospitalId, patientId)
      .then((d) => {
        if (!cancelled) setPatient(d);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const err = e as { response?: { data?: { detail?: string } }; message?: string };
        setError(err?.response?.data?.detail || err?.message || "Could not load patient");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hospitalId, patientId, authenticated, reloadKey]);

  const ehrFhirId = deriveEhrFhirId(patient);

  const value: PatientWorkspaceValue = {
    hospitalId,
    patientId,
    patient,
    loading,
    error,
    reloadPatient,
    ehrFhirId,
    ehrLinked: ehrFhirId != null,
  };

  return (
    <PatientWorkspaceContext.Provider value={value}>
      {children}
    </PatientWorkspaceContext.Provider>
  );
}

/** Hook for tabs and workspace chrome to read the current patient context. */
export function usePatientWorkspace(): PatientWorkspaceValue {
  const ctx = useContext(PatientWorkspaceContext);
  if (!ctx) {
    throw new Error("usePatientWorkspace must be used within a PatientWorkspaceProvider");
  }
  return ctx;
}
