// api-ops.ts — typed wrappers for the new clinician-ops backend endpoints.
// All endpoints are relative to /api/{hospitalId}. Shares the single axios
// instance (with Bearer interceptor) exported by lib/api.ts — no new instance,
// per ARCH-007.
import { api } from "./api";

// --- SDoH (PRAPARE social-determinants screener) ------------------------------

export type SdohNeed = {
  domain: string;
  detail?: string;
  [k: string]: unknown;
};

export type SdohScreenResult = {
  instrument: string;
  positive_domains: string[];
  risk_count: number;
  risk_level: "low" | "moderate" | "high" | string;
  urgent: boolean;
  icd10_z_codes: string[];
  recommended_referrals: string[];
  needs: SdohNeed[];
};

export async function sdohScreen(
  hospitalId: string,
  answers: Record<string, unknown>,
  instrument: string = "prapare",
): Promise<SdohScreenResult> {
  const { data } = await api.post<SdohScreenResult>(
    `/api/${hospitalId}/sdoh/screen`,
    { answers, instrument },
  );
  return data;
}

export type SdohReferral = {
  referral_id: string;
  status: string;
  domain?: string;
  patient_ref?: string;
  organization?: string;
  network?: string;
  note?: string;
  [k: string]: unknown;
};

export async function sdohReferral(
  hospitalId: string,
  body: {
    domain: string;
    patient_ref: string;
    consent?: boolean;
    organization?: string;
    note?: string;
    network?: string;
  },
): Promise<SdohReferral> {
  const { data } = await api.post<SdohReferral>(
    `/api/${hospitalId}/sdoh/referral`,
    { network: "findhelp", consent: false, ...body },
  );
  return data;
}

export async function sdohReferralsBatch(
  hospitalId: string,
  body: {
    screen_result: SdohScreenResult;
    patient_ref: string;
    consent?: boolean;
    network?: string;
  },
): Promise<{ count: number; referrals: SdohReferral[] }> {
  const { data } = await api.post<{ count: number; referrals: SdohReferral[] }>(
    `/api/${hospitalId}/sdoh/referrals`,
    { consent: false, ...body },
  );
  return data;
}

// --- Care gaps (per-patient HEDIS sidebar) ------------------------------------

export type CareGap = {
  measure?: string;
  title?: string;
  description?: string;
  priority?: string;
  [k: string]: unknown;
};

export type CareGapSidebar = {
  patient_age: number | null;
  total_open_gaps: number;
  shown: number;
  gaps: CareGap[];
  more_gaps: number;
  headline: string;
};

export async function careGapsSidebar(
  hospitalId: string,
  patientId: string,
  limit: number = 2,
): Promise<CareGapSidebar> {
  const { data } = await api.get<CareGapSidebar>(
    `/api/${hospitalId}/care-gaps/${encodeURIComponent(patientId)}/sidebar`,
    { params: { limit } },
  );
  return data;
}

// --- No-show (equity audit + reminder plan) -----------------------------------

export type NoShowEquityAudit = {
  by_group: Record<string, unknown>;
  max_risk_gap: number;
  flag: boolean;
  note: string;
};

export async function noShowEquityAudit(
  hospitalId: string,
  records: Record<string, unknown>[],
  groupKey?: string,
): Promise<NoShowEquityAudit> {
  const { data } = await api.post<NoShowEquityAudit>(
    `/api/${hospitalId}/no-show/equity-audit`,
    { records, ...(groupKey ? { group_key: groupKey } : {}) },
  );
  return data;
}

export type ReminderItem = {
  offset_hours: number;
  channel: string;
  send_iso: string;
  due: boolean;
};

export type ReminderPlan = {
  tier: string;
  reminders: ReminderItem[];
  channels: string[];
  summary: string;
};

export async function noShowReminderPlan(
  hospitalId: string,
  body: { tier: string; appointment_iso?: string; no_show_probability?: number },
): Promise<ReminderPlan> {
  const { data } = await api.post<ReminderPlan>(
    `/api/${hospitalId}/no-show/reminder-plan`,
    body,
  );
  return data;
}

// --- Result loop-closure ------------------------------------------------------

export type AbnormalResult = {
  result_name?: string;
  name?: string;
  value?: number | string;
  unit?: string;
  severity?: string;
  reason?: string;
  [k: string]: unknown;
};

export async function resultsDetectAbnormal(
  hospitalId: string,
  results: Record<string, unknown>[],
): Promise<{ count: number; abnormal_results: AbnormalResult[] }> {
  const { data } = await api.post<{ count: number; abnormal_results: AbnormalResult[] }>(
    `/api/${hospitalId}/results/detect-abnormal`,
    { results },
  );
  return data;
}

export type ResultReviewDraft = {
  result_name: string;
  severity: string;
  message: string;
  tone: string;
};

export async function resultsReview(
  hospitalId: string,
  body: {
    abnormal_results: AbnormalResult[];
    reading_level?: string;
    language?: string;
  },
): Promise<{ count: number; drafts: ResultReviewDraft[] }> {
  const { data } = await api.post<{ count: number; drafts: ResultReviewDraft[] }>(
    `/api/${hospitalId}/results/review`,
    body,
  );
  return data;
}

export type ClosureHistoryEntry = {
  state: string;
  actor?: string;
  note?: string;
  at?: string;
  [k: string]: unknown;
};

export type ResultClosure = {
  closure_id: string;
  state: string;
  patient_id?: string;
  result?: Record<string, unknown>;
  history: ClosureHistoryEntry[];
  detected_by?: string;
  [k: string]: unknown;
};

export async function resultClosureOpen(
  hospitalId: string,
  body: {
    patient_id: string;
    result: Record<string, unknown>;
    detected_by?: string;
  },
): Promise<ResultClosure> {
  const { data } = await api.post<ResultClosure>(
    `/api/${hospitalId}/results/closures`,
    body,
  );
  return data;
}

export async function resultClosureAdvance(
  hospitalId: string,
  body: {
    closure: ResultClosure;
    to_state: string;
    actor?: string;
    note?: string;
    patient_message?: string;
  },
): Promise<ResultClosure> {
  const { data } = await api.post<ResultClosure>(
    `/api/${hospitalId}/results/closures/advance`,
    body,
  );
  return data;
}

export type ClosureSummary = {
  total: number;
  by_state: Record<string, number>;
  open: number;
  closed: number;
  critical_open: number;
  queue: ResultClosure[];
};

export async function resultClosureSummary(
  hospitalId: string,
  closures: ResultClosure[],
): Promise<ClosureSummary> {
  const { data } = await api.post<ClosureSummary>(
    `/api/${hospitalId}/results/closures/summary`,
    { closures },
  );
  return data;
}

// --- EHR Copilot (agentic chart Q&A / summary / scan / autopopulate) ----------

export type CopilotSource = { tool?: string; resource?: string; linked?: boolean };

/**
 * Artifact blocks composed by the model and hydrated server-side. The model
 * only ever chose the block types and which refs to bind; real patient values
 * were filled in by the deterministic renderer (it never saw them).
 */
export type CopilotBlock =
  | { type: "callout"; text: string; tone?: "info" | "warning" | "success" | "critical" }
  | { type: "card"; title?: string; text?: string }
  | { type: "stat"; label?: string; value?: unknown; unit?: string }
  | { type: "risk_gauge"; title?: string; value?: unknown; conformal?: unknown }
  | { type: "table"; title?: string; rows?: Record<string, unknown>[]; columns?: string[] }
  | { type: "timeline"; title?: string; events?: Record<string, unknown>[] }
  | {
      type: "differential";
      title?: string;
      ranked?: {
        diagnosis?: string;
        icd10?: string;
        likelihood?: string;
        must_not_miss?: boolean;
        discriminator?: string;
      }[];
    };

export type CopilotPlanStep = { id: string; primitive: string; params: Record<string, unknown> };
export type CopilotPlan = { reasoning?: string; steps: CopilotPlanStep[] };

export type CopilotAnswer = {
  answer: string;
  blocks?: CopilotBlock[];
  slots?: Record<string, { label: string; value: string }>;
  plan?: CopilotPlan | null;
  sources: CopilotSource[];
  error?: string;
};

export async function copilotAsk(
  hospitalId: string,
  patientId: string,
  question: string,
): Promise<CopilotAnswer> {
  const { data } = await api.post<CopilotAnswer>(
    `/api/${hospitalId}/copilot/ask`,
    { patient_id: patientId, question },
  );
  return data;
}

export async function copilotSummary(
  hospitalId: string,
  patientId: string,
): Promise<CopilotAnswer> {
  const { data } = await api.post<CopilotAnswer>(
    `/api/${hospitalId}/copilot/summary`,
    { patient_id: patientId },
  );
  return data;
}

export type CopilotScanItem = {
  type: string;
  severity: string;
  title: string;
  detail?: string;
  action?: string;
  icd10?: string;
};
export type CopilotScanResult = { count: number; items: CopilotScanItem[]; sources: CopilotSource[] };

export async function copilotScan(
  hospitalId: string,
  patientId: string,
): Promise<CopilotScanResult> {
  const { data } = await api.post<CopilotScanResult>(
    `/api/${hospitalId}/copilot/scan`,
    { patient_id: patientId },
  );
  return data;
}

export type CopilotField = {
  field: string;
  current: string[];
  ehr: string[];
  additions: string[];
  has_changes: boolean;
};
export type CopilotAutopopulate = {
  linked: boolean;
  source?: string;
  note?: string;
  demographics?: Record<string, unknown>;
  prior_visits?: unknown[];
  fields: CopilotField[];
};

export async function copilotAutopopulate(
  hospitalId: string,
  patientId: string,
): Promise<CopilotAutopopulate> {
  const { data } = await api.post<CopilotAutopopulate>(
    `/api/${hospitalId}/copilot/autopopulate`,
    { patient_id: patientId },
  );
  return data;
}
