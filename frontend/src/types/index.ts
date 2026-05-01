export type ComfortAction = {
  title: string;
  instruction: string;
  icon: string;
};

export type Sex = "male" | "female" | "other";

export type MedicalInfo = {
  age: number | null;
  sex: Sex | null;
  pregnant: boolean | null;
  gestational_weeks: number | null;
  allergies: string[];
  allergy_severity: Record<string, "mild" | "moderate" | "anaphylaxis">;
  medications: string[];
  blood_thinner_name: string | null;
  conditions: string[];
  diabetes_type: "type1" | "type2" | "gestational" | null;
  heart_failure_class: "I" | "II" | "III" | "IV" | null;
  smoker: boolean | null;
};

export type FollowupQuestion =
  | { id: string; question: string; type: "boolean" }
  | { id: string; question: string; type: "choice"; options: string[] }
  | { id: string; question: string; type: "text" };

export type FollowupAnswer = {
  id: string;
  question: string;
  answer: string;
};

export type TranscribeResponse = {
  transcript: string;
  language: string;
  followups: FollowupQuestion[];
};

export type IntakeResponse = {
  patient_id: string;
  esi_level: 1 | 2 | 3 | 4 | 5;
  esi_label: string;
  patient_explanation: string;
  comfort_protocol: ComfortAction[];
  audio_url: string | null;
  confidence_band: string | null;
  language: string;
};

export type PatientSummary = {
  patient_id: string;
  name: string;
  esi_level: 1 | 2 | 3 | 4 | 5;
  esi_label: string;
  esi_confidence: number | null;
  confidence_band: string | null;
  clinician_prebrief: string;
  language: string;
  pain_flagged: boolean;
  pain_flagged_at: string | null;
  status: "waiting" | "seen";
  seen_by: string | null;
  seen_at: string | null;
  created_at: string;
  waited_minutes: number;
  refined_esi_level?: number | null;
  refined_confidence?: number | null;
  refined_at?: string | null;
};

export type InsuranceFields = {
  provider: string | null;
  plan_name: string | null;
  member_id: string | null;
  group_number: string | null;
  name_on_card: string | null;
  bin: string | null;
  pcn: string | null;
  rx_group: string | null;
  effective_date: string | null;
  phone: string | null;
};

export type Prescription = {
  prescription_id: string;
  patient_id: string;
  hospital_id: string;
  drug: string;
  dose: string;
  route: string;
  frequency: string;
  duration: string;
  indication: string;
  cautions: string;
  prescribed_by: string;
  prescribed_at: string;
  source: "manual" | "ai_suggested_accepted" | "ai_suggested";
};

export type PrescriptionSuggestion = Omit<
  Prescription,
  "prescription_id" | "patient_id" | "hospital_id" | "prescribed_at" | "prescribed_by" | "source"
>;

export type ClinicianNote = {
  note_id: string;
  patient_id: string;
  hospital_id: string;
  text: string;
  author: string;
  created_at: string;
};

export type PatientEducation = {
  headline: string;
  what_we_are_doing: string;
  things_to_do_at_home: string[];
  when_to_come_back: string;
  closing: string;
};

export type Vitals = {
  systolic_bp?: number | null;
  diastolic_bp?: number | null;
  heart_rate?: number | null;
  respiratory_rate?: number | null;
  temperature_c?: number | null;
  spo2?: number | null;
  gcs_total?: number | null;
  pain_score?: number | null;
  mental_status?: string | null;
  weight_kg?: number | null;
  height_cm?: number | null;
  news2_score?: number | null;
};

export type RefinedTriage = {
  esi_level: number;
  confidence: number;
  probabilities: Record<string, number>;
  conformal_set: number[];
  conformal_q_hat: number;
  top_features: {
    feature: string;
    value: number;
    shap?: number;
    direction?: "increases" | "decreases";
    weight?: number;
  }[];
  source: string;
  model_metrics?: { oof_qwk?: number; oof_accuracy?: number };
  dataset?: string;
  training_data_note?: string;
};

export type DifferentialEntry = {
  diagnosis: string;
  icd10: string;
  likelihood: "high" | "moderate" | "low";
  rule_in: string[];
  rule_out: string[];
  must_not_miss: boolean;
};

export type WorkupOrders = {
  labs: string[];
  imaging: string[];
  monitoring: string[];
  consults: string[];
  rationale: string;
};

export type Disposition = {
  disposition: "admit" | "observe" | "discharge" | "transfer" | "";
  level_of_care: string;
  expected_los_hours: number;
  rationale: string;
  discharge_criteria: string[];
  return_precautions: string[];
};

export type PatientDetail = PatientSummary & {
  transcript: string;
  photo_url: string | null;
  photo_analysis: { description?: string; severity_indicators?: string[]; triage_observations?: string[] } | null;
  shap_values: Record<string, number> | null;
  comfort_protocol: ComfortAction[];
  patient_explanation: string;
  audio_url: string | null;
  triage_source: string | null;
  clinical_flags: string[];
  composites: { qsofa?: number; sirs?: number; shock_index?: number; cv_risk?: number };
  triage_recommendation: string;
  probabilities: number[];
  medical_info: MedicalInfo | null;
  followup_qa: FollowupAnswer[];
  insurance_info: InsuranceFields | null;
  prescriptions: Prescription[];
  clinical_scribe_note: string;
  differential: DifferentialEntry[];
  workup_orders: WorkupOrders;
  disposition: Disposition;
  notes: ClinicianNote[];
  patient_education: PatientEducation | null;
  patient_education_published_at: string | null;
  refined_esi_level?: number | null;
  refined_confidence?: number | null;
  refined_probabilities?: string | null;
  refined_conformal_set?: string | null;
  refined_top_features?: string | null;
  refined_source?: string | null;
  refined_at?: string | null;
  measured_vitals?: string | null;
};

export type PublicPatient = {
  patient_id: string;
  patient_explanation: string;
  comfort_protocol: ComfortAction[];
  audio_url: string | null;
  patient_education: PatientEducation | null;
  patient_education_published_at: string | null;
  status: "waiting" | "seen";
  wait_estimate_minutes?: number;
  wait_estimate_range?: string;
};
