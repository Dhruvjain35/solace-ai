import { api } from "./api";

// ============================================================================
// Letters and patient-education API surface
// New backend endpoints, relative to /api/{hospitalId}. Kept in its own module
// so lib/api.ts stays untouched (ARCH-007: still the typed-wrapper convention).
// ============================================================================

export type LetterCategory = {
  key: string;
  label: string;
};

export type LetterResult = {
  template_key: string;
  template_name: string;
  category: string;
  audience: string;
  slots: Record<string, string>;
  rendered: string;
  complete: boolean;
  missing_required: string[];
  missing_optional: string[];
  error?: string | null;
};

export type LetterGenerateRequest = {
  template_key: string;
  chart_context?: Record<string, unknown>;
  slot_overrides?: Record<string, string>;
};

export type EducationHandout = {
  condition: string;
  title: string;
  overview: string;
  why_it_happens: string;
  what_to_expect: string;
  self_care: string[];
  medication_notes: string;
  red_flags: string[];
  when_to_seek_care: string;
  follow_up: string;
  closing: string;
};

export type HandoutRequest = {
  condition: string;
  patient_context?: Record<string, unknown>;
  reading_level?: string;
  patient_language?: string;
};

// --- Letter templates / categories --------------------------------------------------

export async function getLetterCategories(hospitalId: string): Promise<LetterCategory[]> {
  const { data } = await api.get<{ categories: LetterCategory[] }>(
    `/api/${hospitalId}/letters/categories`,
  );
  return data.categories || [];
}

// --- One-click letter generation -----------------------------------------------------

export async function generateLetter(
  hospitalId: string,
  body: LetterGenerateRequest,
): Promise<LetterResult> {
  const { data } = await api.post<LetterResult>(
    `/api/${hospitalId}/letters/generate`,
    body,
  );
  return data;
}

export async function generateLetterBatch(
  hospitalId: string,
  requests: LetterGenerateRequest[],
  chartContext?: Record<string, unknown>,
): Promise<LetterResult[]> {
  const { data } = await api.post<{ letters: LetterResult[] }>(
    `/api/${hospitalId}/letters/batch`,
    { requests, ...(chartContext ? { chart_context: chartContext } : {}) },
  );
  return data.letters || [];
}

// --- Patient education handouts ------------------------------------------------------

export async function generateHandout(
  hospitalId: string,
  body: HandoutRequest,
): Promise<EducationHandout> {
  const { data } = await api.post<EducationHandout>(
    `/api/${hospitalId}/education/handout`,
    body,
  );
  return data;
}

export async function generateHandoutBatch(
  hospitalId: string,
  conditions: string[],
  readingLevel?: string,
  patientLanguage?: string,
): Promise<EducationHandout[]> {
  const { data } = await api.post<{ handouts: EducationHandout[] }>(
    `/api/${hospitalId}/education/handout-batch`,
    {
      conditions,
      ...(readingLevel ? { reading_level: readingLevel } : {}),
      ...(patientLanguage ? { patient_language: patientLanguage } : {}),
    },
  );
  return data.handouts || [];
}
