import axios from "axios";
import type {
  ClinicianNote,
  InsuranceFields,
  IntakeResponse,
  PatientDetail,
  PatientEducation,
  PatientSummary,
  Prescription,
  PrescriptionSuggestion,
  PublicPatient,
  RefinedTriage,
  TranscribeResponse,
  Vitals,
} from "../types";

// If VITE_API_BASE_URL is empty, axios uses relative URLs — served same-origin
// via Vite's proxy. Set explicitly only when you need to bypass the proxy.
const BASE_URL =
  import.meta.env.VITE_API_BASE_URL !== undefined && import.meta.env.VITE_API_BASE_URL !== ""
    ? import.meta.env.VITE_API_BASE_URL
    : "";

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 120_000,
});

// Attach Bearer token on every request. Reads localStorage first (primary store)
// then sessionStorage (legacy fallback). This is the ONLY auth mechanism —
// legacy X-Clinician-PIN has been removed.
api.interceptors.request.use((config) => {
  try {
    const raw =
      localStorage.getItem("solace.session.v1") ??
      sessionStorage.getItem("solace.session.v1");
    if (raw) {
      const sess = JSON.parse(raw);
      if (sess?.token) {
        config.headers = config.headers ?? {};
        (config.headers as any).Authorization = `Bearer ${sess.token}`;
      }
    }
  } catch {
    /* ignore */
  }
  return config;
});

export async function postTranscribe(hospitalId: string, form: FormData): Promise<TranscribeResponse> {
  const { data } = await api.post<TranscribeResponse>(`/api/${hospitalId}/transcribe`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function postIntake(hospitalId: string, form: FormData): Promise<IntakeResponse> {
  const { data } = await api.post<IntakeResponse>(`/api/${hospitalId}/intake`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function postPainFlag(hospitalId: string, patientId: string): Promise<void> {
  await api.post(`/api/${hospitalId}/pain-flag`, { patient_id: patientId });
}

export async function acknowledgePainFlag(
  hospitalId: string,
  patientId: string,
): Promise<void> {
  await api.post(
    `/api/${hospitalId}/pain-flag/acknowledge`,
    { patient_id: patientId },
  );
}

export async function getPatients(
  hospitalId: string,
  status: "waiting" | "all" = "waiting"
): Promise<{ patients: PatientSummary[] }> {
  const { data } = await api.get(`/api/${hospitalId}/patients`, {
    params: { status },
  });
  return data;
}

export async function getPatientDetail(
  hospitalId: string,
  patientId: string,
): Promise<PatientDetail> {
  const { data } = await api.get<PatientDetail>(`/api/${hospitalId}/patients/${patientId}`);
  return data;
}

export async function markSeen(
  hospitalId: string,
  patientId: string,
  clinicianName: string
): Promise<void> {
  await api.patch(
    `/api/${hospitalId}/patients/${patientId}/resolve`,
    { clinician_name: clinicianName },
  );
}

export async function scanInsurance(
  hospitalId: string,
  imageFile: File,
  consentGranted = true,
): Promise<{ success: boolean; fields?: InsuranceFields; error?: string }> {
  const form = new FormData();
  form.append("image_file", imageFile);
  form.append("consent_granted", consentGranted ? "true" : "false");
  const { data } = await api.post(`/api/${hospitalId}/scan-insurance`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listPrescriptions(
  hospitalId: string,
  patientId: string,
): Promise<Prescription[]> {
  const { data } = await api.get(`/api/${hospitalId}/patients/${patientId}/prescriptions`);
  return data.prescriptions || [];
}

export async function suggestPrescriptions(
  hospitalId: string,
  patientId: string,
): Promise<PrescriptionSuggestion[]> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/prescriptions/suggest`,
    {},
  );
  return data.suggestions || [];
}

export async function createPrescription(
  hospitalId: string,
  patientId: string,
  body: Partial<Prescription> & { drug: string }
): Promise<Prescription> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/prescriptions`,
    body,
  );
  return data.prescription;
}

export async function createNote(
  hospitalId: string,
  patientId: string,
  text: string,
  author = "Clinician"
): Promise<ClinicianNote> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/notes`,
    { text, author },
  );
  return data.note;
}

export async function publishPatientSummary(
  hospitalId: string,
  patientId: string,
  noteId?: string
): Promise<PatientEducation> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/publish-summary`,
    noteId ? { note_id: noteId } : {},
  );
  return data.summary;
}

export async function getPublicPatient(
  hospitalId: string,
  patientId: string
): Promise<PublicPatient> {
  const { data } = await api.get<PublicPatient>(
    `/api/${hospitalId}/public-patients/${patientId}`
  );
  return data;
}

export type EHRRecord = {
  mrn: string;
  hospital_id: string;
  name: string;
  dob: string;
  sex: string;
  height_cm: number;
  weight_kg: number;
  bmi: number;
  blood_type: string;
  primary_care_provider: string;
  insurance: string;
  emergency_contact: string;
  allergies: string[];
  medications: string[];
  conditions: string[];
  family_history: string[];
  immunizations: string[];
  social_history: string;
  prior_visits: {
    date: string;
    type: string;
    facility: string;
    chief_complaint: string;
    disposition: string;
    note: string;
  }[];
};

export type EHRLookupResult = {
  record: EHRRecord | null;
  reason?: string;
  match_method?: "insurance_member_id+provider" | "insurance_member_id" | "name_exact";
};

export async function lookupEHR(
  hospitalId: string,
  patientId: string
): Promise<EHRLookupResult> {
  const { data } = await api.get<EHRLookupResult>(
    `/api/${hospitalId}/ehr/lookup-by-patient/${patientId}`
  );
  return data;
}

export async function startIntake(
  hospitalId: string
): Promise<{ token: string; expires_at: number }> {
  const { data } = await api.post(`/api/${hospitalId}/start-intake`);
  return data;
}

export async function loginClinician(
  hospitalId: string,
  clinicianName: string,
  pin: string
): Promise<{
  token: string;
  clinician_id: string;
  name: string;
  role: string;
  hospital_id: string;
  expires_at: number;
}> {
  const { data } = await api.post(`/api/${hospitalId}/auth/login`, {
    clinician_name: clinicianName,
    pin,
  });
  return data;
}

export type EHRVendorOption = {
  id: string;        // "epic" | "cerner" | "athena"
  label: string;
  color: string;
  sandbox: boolean;
};

export async function listEHRVendors(): Promise<EHRVendorOption[]> {
  const { data } = await api.get<{ vendors: EHRVendorOption[] }>("/api/auth/ehr/vendors");
  return data.vendors || [];
}

// Builds the OAuth launch URL — frontend redirects the browser here, which 302s to
// the vendor's authorize endpoint. Mock provider auto-approves; real vendors show
// their hosted login screen.
export function buildEHRLaunchURL(vendorId: string, hospitalId: string, redirectUri: string): string {
  const base =
    import.meta.env.VITE_API_BASE_URL && import.meta.env.VITE_API_BASE_URL !== ""
      ? import.meta.env.VITE_API_BASE_URL
      : "";
  const qs = new URLSearchParams({
    vendor: vendorId,
    hospital_id: hospitalId,
    redirect_uri: redirectUri,
  });
  return `${base}/api/auth/ehr/launch?${qs.toString()}`;
}

export async function whoami(hospitalId: string): Promise<{
  clinician_id: string;
  name: string;
  role: string;
  hospital_id: string;
  auth_method: string;
}> {
  const { data } = await api.get(`/api/${hospitalId}/auth/whoami`);
  return data;
}

export async function resetDemo(
  hospitalId: string,
): Promise<{ deleted_test_patients: string[]; cleared_canonical_patients: string[] }> {
  const { data } = await api.post(
    `/api/${hospitalId}/admin/reset-demo`,
    {},
  );
  return data;
}

// --- Workflows ------------------------------------------------------------------------

export type WorkflowTrigger = {
  name: string;
  label: string;
  description: string;
  sample_context: Record<string, unknown>;
};

export type WorkflowActionField = {
  name: string;
  label: string;
  type: "text" | "textarea";
  required: boolean;
  help?: string;
};

export type WorkflowActionDef = {
  type: string;
  label: string;
  description: string;
  fields: WorkflowActionField[];
};

export type WorkflowTemplate = {
  id: string;
  label: string;
  description: string;
  trigger: string;
};

export type WorkflowStep = {
  type: string;
  config: Record<string, string>;
  stop_on_error?: boolean;
};

export type Workflow = {
  workflow_id: string;
  hospital_id: string;
  name: string;
  trigger: string;
  enabled: boolean;
  filters?: Record<string, unknown>;
  steps: WorkflowStep[];
  fire_count?: number;
  last_fired_at?: string | null;
  created_at?: string;
  updated_at?: string;
  from_template?: string;
};

export async function getWorkflowCatalog(
  hospitalId: string,
): Promise<{
  triggers: WorkflowTrigger[];
  actions: WorkflowActionDef[];
  templates: WorkflowTemplate[];
}> {
  const { data } = await api.get(`/api/${hospitalId}/workflows/catalog`);
  return data;
}

export async function listWorkflows(hospitalId: string): Promise<Workflow[]> {
  const { data } = await api.get<{ workflows: Workflow[] }>(`/api/${hospitalId}/workflows`);
  return data.workflows || [];
}

export async function createWorkflow(
  hospitalId: string,
  body: Omit<Workflow, "workflow_id" | "hospital_id" | "fire_count" | "last_fired_at" | "created_at" | "updated_at" | "from_template">
): Promise<Workflow> {
  const { data } = await api.post(`/api/${hospitalId}/workflows`, body);
  return data.workflow;
}

export async function updateWorkflow(
  hospitalId: string,
  workflowId: string,
  body: Omit<Workflow, "workflow_id" | "hospital_id" | "fire_count" | "last_fired_at" | "created_at" | "updated_at" | "from_template">
): Promise<Workflow> {
  const { data } = await api.put(`/api/${hospitalId}/workflows/${workflowId}`, body);
  return data.workflow;
}

export async function deleteWorkflow(
  hospitalId: string,
  workflowId: string
): Promise<void> {
  await api.delete(`/api/${hospitalId}/workflows/${workflowId}`);
}

export async function testWorkflow(
  hospitalId: string,
  body: { workflow_id?: string; workflow?: Partial<Workflow> }
): Promise<{
  context: Record<string, unknown>;
  results: { step_type: string; result: { success: boolean; reason?: string; message?: string } }[];
}> {
  const { data } = await api.post(`/api/${hospitalId}/workflows/test`, body);
  return data;
}

export async function workflowFromTemplate(
  hospitalId: string,
  templateId: string
): Promise<Workflow> {
  const { data } = await api.post(
    `/api/${hospitalId}/workflows/from-template`,
    { template_id: templateId },
  );
  return data.workflow;
}

// --- Appointments / self-scheduling ---------------------------------------------------

export type AppointmentSlot = {
  iso: string;
  label: string;
  duration_min: number;
};

export type Appointment = {
  appointment_id: string;
  hospital_id: string;
  slot_iso: string;
  patient_name: string;
  patient_phone_hash?: string;  // hashed, not raw — HIPAA §164.514
  reason_short: string;
  status: string;
  confirmation_code: string;
  created_via: string;
};

export async function getAppointmentAvailability(
  hospitalId: string,
  days: number = 7
): Promise<AppointmentSlot[]> {
  const { data } = await api.get<{ slots: AppointmentSlot[] }>(
    `/api/${hospitalId}/appointments/availability`,
    { params: { days } }
  );
  return data.slots || [];
}

export async function bookAppointment(
  hospitalId: string,
  body: { slot_iso: string; patient_name: string; patient_phone: string; reason: string }
): Promise<{ success: boolean; appointment: Appointment }> {
  const { data } = await api.post(`/api/${hospitalId}/appointments/book`, body);
  return data;
}

export async function lookupAppointment(
  hospitalId: string,
  confirmationCode: string
): Promise<Appointment> {
  const { data } = await api.get<Appointment>(
    `/api/${hospitalId}/appointments/${encodeURIComponent(confirmationCode)}`
  );
  return data;
}

export async function cancelAppointment(
  hospitalId: string,
  confirmationCode: string
): Promise<{ success: boolean }> {
  const { data } = await api.post(`/api/${hospitalId}/appointments/cancel`, {
    confirmation_code: confirmationCode,
  });
  return data;
}

// --- SMS ------------------------------------------------------------------------------

export async function sendDischargeSMS(
  hospitalId: string,
  patientId: string,
  phoneOverride?: string
): Promise<{ success: boolean; reason?: string; message?: string }> {
  const { data } = await api.post(
    `/api/${hospitalId}/sms/discharge`,
    { patient_id: patientId, ...(phoneOverride ? { phone: phoneOverride } : {}) },
  );
  return data;
}

export async function sendCareInstructionsSelfServe(
  hospitalId: string,
  patientId: string,
  phone: string
): Promise<{ success: boolean; reason?: string; message?: string }> {
  const { data } = await api.post(`/api/${hospitalId}/sms/care-instructions`, {
    patient_id: patientId,
    phone,
  });
  return data;
}

// --- Care recommendation (already inside intake response) -----------------------------

export type CareRecommendation = {
  destination: "ed_now" | "ed" | "urgent" | "telehealth" | "self_care" | "schedule";
  label: string;
  rationale: string;
  action_cta: string;
  severity: "critical" | "high" | "moderate" | "low";
};

// --- Identity / ID scan ---------------------------------------------------------------

export type IdFields = {
  first_name: string;
  last_name: string;
  dob: string;
  license_number: string;
  issuing_state: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  expiry: string;
  sex: string;
};

export async function scanID(
  hospitalId: string,
  imageFile: File
): Promise<{ success: boolean; fields?: IdFields; error?: string }> {
  const form = new FormData();
  form.append("image_file", imageFile);
  const { data } = await api.post(`/api/${hospitalId}/scan-id`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export type IdentityLookupResult = {
  matched: boolean;
  match_method?: "name+dob" | "name_only";
  reason?: string;
  ehr_record?: {
    name: string;
    mrn: string;
    dob: string;
    sex: string;
    allergies?: string[];
    medications?: string[];
    conditions?: string[];
    insurance?: string;
    primary_care_provider?: string;
    prior_visits?: { date: string; type: string; chief_complaint: string; disposition: string }[];
  };
  prefill?: {
    age: number | null;
    sex: "male" | "female" | "other" | null;
    allergies: string[];
    medications: string[];
    conditions: string[];
    insurance_hint: string;
    emergency_contact: string;
    primary_care_provider: string;
    prior_visits_count: number;
  };
};

export async function identityLookup(
  hospitalId: string,
  body: Pick<IdFields, "first_name" | "last_name" | "dob" | "license_number" | "issuing_state">
): Promise<IdentityLookupResult> {
  const { data } = await api.post<IdentityLookupResult>(
    `/api/${hospitalId}/identity/lookup`,
    body
  );
  return data;
}

// --- Voice agent ----------------------------------------------------------------------

export type VoiceTurnResponse = {
  call_id: string;
  say: string;
  audio_url: string | null;
  tool?: string | null;
  escalate?: "human" | "911" | null;
};

export async function voiceSimulatorStart(
  hospitalId: string,
  language: string
): Promise<VoiceTurnResponse> {
  const { data } = await api.post<VoiceTurnResponse>(`/api/voice/simulator/start`, {
    hospital_id: hospitalId,
    language,
  });
  return data;
}

export async function voiceSimulatorTurn(
  callId: string,
  text: string
): Promise<VoiceTurnResponse> {
  const { data } = await api.post<VoiceTurnResponse>(`/api/voice/simulator/turn`, {
    call_id: callId,
    text,
  });
  return data;
}

export async function voiceSimulatorEnd(callId: string, disposition = "ended_by_user"): Promise<void> {
  await api.post(`/api/voice/simulator/end`, { call_id: callId, disposition });
}

export type VoiceCallSummary = {
  call_id: string;
  hospital_id: string;
  language: string;
  channel: string;
  status: string;
  intent?: string | null;
  escalation?: string | null;
  disposition?: string | null;
  started_at: string;
  ended_at?: string | null;
  duration_seconds?: number | null;
  transcript?: { role: string; text: string; ts: string }[];
  tools_called?: { name: string; result_summary: string; ts: string }[];
};

export async function listVoiceCalls(hospitalId: string): Promise<VoiceCallSummary[]> {
  const { data } = await api.get(`/api/voice/calls`, {
    params: { hospital_id: hospitalId },
  });
  return data.calls || [];
}

export async function getVoiceStats(
  hospitalId: string,
): Promise<{ total: number; intents: Record<string, number>; escalations: number; avg_duration_seconds: number }> {
  const { data } = await api.get(`/api/voice/stats`, {
    params: { hospital_id: hospitalId },
  });
  return data;
}

export type VoiceAppointment = {
  appointment_id: string;
  hospital_id: string;
  patient_name: string;
  patient_phone_hash?: string;  // hashed, not raw — HIPAA §164.514
  reason_short: string;
  preferred_window?: string;
  status: string;
  confirmation_code: string;
  created_at: string;
};

export async function listVoiceAppointments(hospitalId: string): Promise<VoiceAppointment[]> {
  const { data } = await api.get(`/api/voice/appointments`, {
    params: { hospital_id: hospitalId },
  });
  return data.appointments || [];
}

export async function refineTriage(
  hospitalId: string,
  patientId: string,
  vitals: Vitals,
): Promise<RefinedTriage> {
  const { data } = await api.post<{ success: boolean; refinement: RefinedTriage; applied_at: string }>(
    `/api/${hospitalId}/patients/${patientId}/refine-triage`,
    vitals,
  );
  return data.refinement;
}

// ============================================================================
// Wave 1+2 — Clinician AI surface
// ============================================================================

export type ScribeSegment = { id: number; speaker: string; begin_ms: number; end_ms: number; content: string };
export type ScribeSection = { name: string; summary: { text: string; evidence_segments: number[] }[] };
export type ScribeOutput = {
  structured: { sections: ScribeSection[]; transcript_segments: ScribeSegment[] };
  soap_text: string;
};

export async function scribeFromTranscript(hospitalId: string, transcript: string): Promise<ScribeOutput> {
  const { data } = await api.post<ScribeOutput>(`/api/${hospitalId}/scribe/from-transcript`, { transcript, refine: true });
  return data;
}

export type DdxItem = {
  diagnosis: string;
  icd10: string;
  weight: number;
  rule_in: string[];
  rule_out: string[];
  must_not_miss: boolean;
  next_step: string;
  evidence_quote: string;
};
export type DdxResult = {
  differential: DdxItem[];
  counterfactuals: { if_true: string; would_change: string }[];
  red_flags: { diagnosis: string; icd10: string }[];
  conformal: { set_90: string[]; set_95: string[] };
};

export async function ddxV2(
  hospitalId: string,
  body: { transcript: string; chief_complaint?: string; specialty?: string; medical_info?: any; vitals?: any }
): Promise<DdxResult> {
  const { data } = await api.post<DdxResult>(`/api/${hospitalId}/ddx/v2`, body);
  return data;
}

export async function listCalculators(hospitalId: string): Promise<{ key: string; name: string; inputs: string[]; applies_when: string[] }[]> {
  const { data } = await api.get(`/api/${hospitalId}/cds/calculators`);
  return data.calculators;
}

export async function calcAutoExtract(hospitalId: string, transcript: string, chief_complaint = "") {
  const { data } = await api.post(`/api/${hospitalId}/cds/auto-extract`, { transcript, chief_complaint });
  return data as { calculators: { key: string; name: string; result: any; unknown: string[] }[] };
}

export async function calculate(hospitalId: string, key: string, inputs: any) {
  const { data } = await api.post(`/api/${hospitalId}/cds/calculate`, { key, inputs });
  return data;
}

export async function listScreeners(hospitalId: string) {
  const { data } = await api.get(`/api/${hospitalId}/screeners`);
  return data.screeners as { key: string; name: string; items: string[]; scale: string }[];
}

export async function scoreScreener(hospitalId: string, key: string, body: { items?: number[]; answers?: any; sex?: string }) {
  const { data } = await api.post(`/api/${hospitalId}/screeners/score`, { key, ...body });
  return data;
}

export async function codingSuggest(hospitalId: string, note_text: string, established_patient = true) {
  const { data } = await api.post(`/api/${hospitalId}/coding/suggest`, { note_text, established_patient });
  return data;
}

// Letters
export async function listLetterTemplates(hospitalId: string) {
  const { data } = await api.get(`/api/${hospitalId}/letters/templates`);
  return data.templates as { key: string; name: string; audience: string; slots: string[] }[];
}

export async function autofillLetter(hospitalId: string, template_key: string, chart_context: any) {
  const { data } = await api.post(`/api/${hospitalId}/letters/auto-fill`, { template_key, chart_context });
  return data as { slots: Record<string, string>; rendered: string };
}

export async function renderLetter(hospitalId: string, template_key: string, slots: Record<string, string>) {
  const { data } = await api.post(`/api/${hospitalId}/letters/render`, { template_key, slots });
  return data.rendered as string;
}

export async function letterPdfUrl(hospitalId: string, template_key: string, slots: Record<string, string>) {
  const resp = await api.post(`/api/${hospitalId}/letters/pdf`, { template_key, slots }, { responseType: "blob" });
  return URL.createObjectURL(resp.data as Blob);
}

// Inbox draft + result triage
export async function inboxDraft(hospitalId: string, inbound_message: string, patient_chart: any = {}, hospital_name = "our clinic") {
  const { data } = await api.post(`/api/${hospitalId}/inbox/draft`, { inbound_message, patient_chart, hospital_name });
  return data;
}

export async function abnormalResultDraft(hospitalId: string, lab_name: string, value: number, recommended_action = "") {
  const { data } = await api.post(`/api/${hospitalId}/inbox/result-draft`, { lab_name, value, recommended_action });
  return data;
}

// Refills
export async function refillTriage(hospitalId: string, body: { medication_canonical: string; last_visit_iso?: string; relevant_lab_iso?: string; relevant_lab_value?: number; recent_hospitalization?: boolean }) {
  const { data } = await api.post(`/api/${hospitalId}/refills/triage`, body);
  return data;
}

// PA packets
export async function paPacket(hospitalId: string, body: any) {
  const { data } = await api.post(`/api/${hospitalId}/pa/packet`, body);
  return data;
}

// Drug check
export async function drugCheck(hospitalId: string, meds: string[], allergies: string[] = [], egfr?: number, complaint = "") {
  const { data } = await api.post(`/api/${hospitalId}/drug-check`, { meds, allergies, egfr, complaint });
  return data;
}

// Discharge plan
export async function buildDischarge(hospitalId: string, body: any) {
  const { data } = await api.post(`/api/${hospitalId}/discharge/build`, body);
  return data;
}

// Specialty packs
export async function listSpecialtyPacks(hospitalId: string) {
  const { data } = await api.get(`/api/${hospitalId}/specialty/packs`);
  return data.packs as { key: string; name: string }[];
}

// Care ops
export async function eligibilityCheck(hospitalId: string, body: { payer_name: string; member_id: string; patient_first: string; patient_last: string; patient_dob: string }) {
  const { data } = await api.post(`/api/${hospitalId}/eligibility/check`, body);
  return data;
}

export async function noShowPredict(hospitalId: string, body: any) {
  const { data } = await api.post(`/api/${hospitalId}/no-show/predict`, body);
  return data;
}

export async function careGapsAdHoc(hospitalId: string, patient: any) {
  const { data } = await api.post(`/api/${hospitalId}/care-gaps/evaluate`, { patient });
  return data.gaps as any[];
}

export async function sdohPrapare(hospitalId: string, answers: any) {
  const { data } = await api.post(`/api/${hospitalId}/sdoh/prapare`, { answers });
  return data;
}

// FHIR write-back
export async function ehrWrite(hospitalId: string, body: any) {
  const { data } = await api.post(`/api/${hospitalId}/ehr-write`, body);
  return data;
}

export async function ehrLocalResources(hospitalId: string) {
  const { data } = await api.get(`/api/${hospitalId}/ehr-write/local`);
  return data.resources as any[];
}

// AI override audit
export async function recordAiOverride(hospitalId: string, body: { purpose: string; decision: string; patient_id?: string; diff_chars?: number; notes?: string; model_name?: string }) {
  const { data } = await api.post(`/api/${hospitalId}/ai-override`, body);
  return data;
}

// Public — model cards
export async function listModelCards() {
  const { data } = await api.get(`/api/model-cards`);
  return data.cards as { id: string; name: string; version: string }[];
}

export async function getModelCard(card_id: string) {
  const { data } = await api.get(`/api/model-cards/${card_id}`);
  return data;
}
