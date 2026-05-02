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
// then sessionStorage (legacy fallback for sessions issued before the storage move).
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
  pin: string,
): Promise<void> {
  await api.post(
    `/api/${hospitalId}/pain-flag/acknowledge`,
    { patient_id: patientId },
    { headers: { "X-Clinician-PIN": pin } },
  );
}

export async function getPatients(
  hospitalId: string,
  pin: string,
  status: "waiting" | "all" = "waiting"
): Promise<{ patients: PatientSummary[] }> {
  const { data } = await api.get(`/api/${hospitalId}/patients`, {
    params: { status },
    headers: { "X-Clinician-PIN": pin },
  });
  return data;
}

export async function getPatientDetail(
  hospitalId: string,
  patientId: string,
  pin: string
): Promise<PatientDetail> {
  const { data } = await api.get<PatientDetail>(`/api/${hospitalId}/patients/${patientId}`, {
    headers: { "X-Clinician-PIN": pin },
  });
  return data;
}

export async function markSeen(
  hospitalId: string,
  patientId: string,
  pin: string,
  clinicianName: string
): Promise<void> {
  await api.patch(
    `/api/${hospitalId}/patients/${patientId}/resolve`,
    { clinician_name: clinicianName },
    { headers: { "X-Clinician-PIN": pin } }
  );
}

export async function scanInsurance(
  hospitalId: string,
  imageFile: File
): Promise<{ success: boolean; fields?: InsuranceFields; error?: string }> {
  const form = new FormData();
  form.append("image_file", imageFile);
  const { data } = await api.post(`/api/${hospitalId}/scan-insurance`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listPrescriptions(
  hospitalId: string,
  patientId: string,
  pin: string
): Promise<Prescription[]> {
  const { data } = await api.get(`/api/${hospitalId}/patients/${patientId}/prescriptions`, {
    headers: { "X-Clinician-PIN": pin },
  });
  return data.prescriptions || [];
}

export async function suggestPrescriptions(
  hospitalId: string,
  patientId: string,
  pin: string
): Promise<PrescriptionSuggestion[]> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/prescriptions/suggest`,
    {},
    { headers: { "X-Clinician-PIN": pin } }
  );
  return data.suggestions || [];
}

export async function createPrescription(
  hospitalId: string,
  patientId: string,
  pin: string,
  body: Partial<Prescription> & { drug: string }
): Promise<Prescription> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/prescriptions`,
    body,
    { headers: { "X-Clinician-PIN": pin } }
  );
  return data.prescription;
}

export async function createNote(
  hospitalId: string,
  patientId: string,
  pin: string,
  text: string,
  author = "Clinician"
): Promise<ClinicianNote> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/notes`,
    { text, author },
    { headers: { "X-Clinician-PIN": pin } }
  );
  return data.note;
}

export async function publishPatientSummary(
  hospitalId: string,
  patientId: string,
  pin: string,
  noteId?: string
): Promise<PatientEducation> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/publish-summary`,
    noteId ? { note_id: noteId } : {},
    { headers: { "X-Clinician-PIN": pin } }
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
  pin: string
): Promise<{ deleted_test_patients: string[]; cleared_canonical_patients: string[] }> {
  const { data } = await api.post(
    `/api/${hospitalId}/admin/reset-demo`,
    {},
    { headers: { "X-Clinician-PIN": pin } }
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

export async function listVoiceCalls(hospitalId: string, pin: string): Promise<VoiceCallSummary[]> {
  const { data } = await api.get(`/api/voice/calls`, {
    params: { hospital_id: hospitalId },
    headers: { "X-Clinician-PIN": pin },
  });
  return data.calls || [];
}

export async function getVoiceStats(
  hospitalId: string,
  pin: string
): Promise<{ total: number; intents: Record<string, number>; escalations: number; avg_duration_seconds: number }> {
  const { data } = await api.get(`/api/voice/stats`, {
    params: { hospital_id: hospitalId },
    headers: { "X-Clinician-PIN": pin },
  });
  return data;
}

export type VoiceAppointment = {
  appointment_id: string;
  hospital_id: string;
  patient_name: string;
  patient_phone?: string;
  reason_short: string;
  preferred_window?: string;
  status: string;
  confirmation_code: string;
  created_at: string;
};

export async function listVoiceAppointments(hospitalId: string, pin: string): Promise<VoiceAppointment[]> {
  const { data } = await api.get(`/api/voice/appointments`, {
    params: { hospital_id: hospitalId },
    headers: { "X-Clinician-PIN": pin },
  });
  return data.appointments || [];
}

export async function refineTriage(
  hospitalId: string,
  patientId: string,
  vitals: Vitals,
  pin: string
): Promise<RefinedTriage> {
  const { data } = await api.post<{ success: boolean; refinement: RefinedTriage; applied_at: string }>(
    `/api/${hospitalId}/patients/${patientId}/refine-triage`,
    vitals,
    { headers: { "X-Clinician-PIN": pin } }
  );
  return data.refinement;
}
