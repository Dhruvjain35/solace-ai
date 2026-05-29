// ============================================================================
// Wave 5 — EHR write-back + vendor status, patient matching, workup safety
// checks, detailed discharge plans, and fairness/bias audits.
//
// Typed wrappers over the new /api/{hospitalId} endpoints. Mirrors the
// convention in lib/api.ts: import the shared axios instance from "./api",
// one async function per endpoint, narrow result types.
// ============================================================================
import { api } from "./api";

// --- EHR vendor status & write-back ------------------------------------------

export type EhrVendorStatus = {
  vendor: string;
  backend: string;
  adapter_available: boolean;
  online: boolean;
  configured: boolean;
};

export async function ehrVendorStatus(hospitalId: string): Promise<EhrVendorStatus> {
  const { data } = await api.get<EhrVendorStatus>(`/api/${hospitalId}/ehr/vendor-status`);
  return data;
}

// A FHIR resource is an open-ended object; resourceType is the only guaranteed key.
export type FhirResource = { resourceType: string; [key: string]: unknown };

export type EhrWriteBackResult = {
  ok: boolean;
  // Live write
  vendor?: string;
  stored?: string;
  id?: string;
  url?: string;
  // Dry-run preview
  dry_run?: boolean;
  resource_type?: string;
  routed_to?: string;
};

export async function ehrWriteBack(
  hospitalId: string,
  resource: FhirResource,
  dryRun = false,
): Promise<EhrWriteBackResult> {
  const { data } = await api.post<EhrWriteBackResult>(`/api/${hospitalId}/ehr/write-back`, {
    resource,
    dry_run: dryRun,
  });
  return data;
}

// --- Patient matching --------------------------------------------------------

export type PatientMatchQuery = {
  given?: string;
  family?: string;
  birth_date?: string;
  gender?: string;
  phone?: string;
  mrn?: string;
};

export type PatientMatchResult = {
  status: "matched" | "needs_review" | "no_match";
  confidence: number;
  reason: string;
  patient: FhirResource | null;
};

export async function ehrPatientMatch(
  hospitalId: string,
  query: PatientMatchQuery,
  candidates: FhirResource[],
): Promise<PatientMatchResult> {
  const { data } = await api.post<PatientMatchResult>(`/api/${hospitalId}/ehr/patient-match`, {
    query,
    candidates,
  });
  return data;
}

// --- Workup safety check -----------------------------------------------------

export type Contraindication = {
  order: string;
  section: string;
  severity: string;
  reason: string;
};

export type WorkupSafetyResult = {
  contraindications: Contraindication[];
  has_critical_contraindication: boolean;
  // The endpoint also returns an order set; keep it open-ended.
  [key: string]: unknown;
};

export type WorkupSafetyBody = {
  transcript: string;
  esi_level: number;
  differential?: unknown[];
  medical_info?: unknown;
  vitals?: unknown;
};

export async function workupSafetyCheck(
  hospitalId: string,
  body: WorkupSafetyBody,
): Promise<WorkupSafetyResult> {
  const { data } = await api.post<WorkupSafetyResult>(`/api/${hospitalId}/workup/safety-check`, body);
  return data;
}

// --- Detailed discharge plan -------------------------------------------------

export type DischargeSection = {
  title?: string;
  name?: string;
  body?: string;
  text?: string;
  [key: string]: unknown;
};

export type TieredPrecaution = {
  tier?: string;
  level?: string;
  label?: string;
  instruction?: string;
  text?: string;
  [key: string]: unknown;
};

export type DetailedDischargeResult = {
  sections: DischargeSection[];
  tiered_precautions: TieredPrecaution[];
  [key: string]: unknown;
};

export type DetailedDischargeBody = {
  condition: string;
  clinician_note: string;
  scribe_note: string;
  transcript: string;
  assessment: string;
  patient_language?: string;
  hospital_name?: string;
  follow_up: string;
};

export async function detailedDischargePlan(
  hospitalId: string,
  body: DetailedDischargeBody,
): Promise<DetailedDischargeResult> {
  const { data } = await api.post<DetailedDischargeResult>(
    `/api/${hospitalId}/discharge/detailed-plan`,
    body,
  );
  return data;
}

// --- Bias / fairness audits --------------------------------------------------

export type BiasFlag = {
  stratum?: string;
  group?: string;
  metric?: string;
  disparity?: number;
  reason?: string;
  [key: string]: unknown;
};

export type BiasAuditResult = {
  count: number;
  errors?: unknown[];
  strata: unknown[];
  flags: BiasFlag[];
  provenance?: unknown;
};

export type EarlyWarningBiasBody = {
  cohort: Record<string, unknown>[];
  strata?: string[];
  score_fn?: string;
  disparity_threshold?: number;
};

export async function earlyWarningBiasAudit(
  hospitalId: string,
  body: EarlyWarningBiasBody,
): Promise<BiasAuditResult> {
  const { data } = await api.post<BiasAuditResult>(
    `/api/${hospitalId}/early-warning/bias-audit`,
    body,
  );
  return data;
}

export type SepsisBundleBiasBody = {
  encounters: Record<string, unknown>[];
  strata?: string[];
  disparity_threshold?: number;
};

export async function sepsisBundleBiasAudit(
  hospitalId: string,
  body: SepsisBundleBiasBody,
): Promise<BiasAuditResult> {
  const { data } = await api.post<BiasAuditResult>(
    `/api/${hospitalId}/sepsis/bundle/bias-audit`,
    body,
  );
  return data;
}
