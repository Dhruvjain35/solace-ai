// Typed API wrappers for the Wave-5 prior-auth + evidence-grounding endpoints.
// All calls go through the shared axios instance in lib/api.ts (ARCH-007).
import { api } from "./api";

// A PA packet is whatever paPacket() returned — its exact shape is server-owned,
// so we treat it as an opaque record when forwarding it to downstream endpoints.
export type PaPacket = Record<string, unknown>;

// --- /pa/da-vinci-bundle -------------------------------------------------------------
// FHIR collection Bundle. Shape is FHIR-defined; kept loose on purpose.
export type FhirBundle = {
  resourceType: "Bundle";
  type?: string;
  entry?: { resource?: { resourceType?: string; id?: string } }[];
  [k: string]: unknown;
};

export async function paDaVinciBundle(
  hospitalId: string,
  packet: PaPacket,
): Promise<FhirBundle> {
  const { data } = await api.post<FhirBundle>(
    `/api/${hospitalId}/pa/da-vinci-bundle`,
    { packet },
  );
  return data;
}

// --- /pa/human-packet ----------------------------------------------------------------
export type HumanPacketSection = { heading: string; body: string };
export type HumanPacket = {
  title: string;
  generated_at: string;
  sections: HumanPacketSection[];
  signature_block: string;
  completeness: number;
};

export async function paHumanPacket(
  hospitalId: string,
  packet: PaPacket,
): Promise<HumanPacket> {
  const { data } = await api.post<HumanPacket>(
    `/api/${hospitalId}/pa/human-packet`,
    { packet },
  );
  return data;
}

// --- /pa/completeness ----------------------------------------------------------------
export type CompletenessBlocker = { field: string; message: string; fix: string };
export type CompletenessWarning = { field?: string; message: string };
export type Completeness = {
  ready_to_submit: boolean;
  blockers: CompletenessBlocker[];
  warnings: CompletenessWarning[];
  score: number; // 0-100
};

export async function paCompleteness(
  hospitalId: string,
  packet: PaPacket,
): Promise<Completeness> {
  const { data } = await api.post<Completeness>(
    `/api/${hospitalId}/pa/completeness`,
    { packet },
  );
  return data;
}

// --- /pa/appeal ----------------------------------------------------------------------
export type AppealLevel = "first" | "second" | "external";
export type AppealRequest = {
  packet: PaPacket;
  denial_reason: string;
  denial_category?: string;
  denial_date?: string;
  appeal_level?: AppealLevel;
  additional_context?: string;
};
export type AppealLetter = {
  header: string;
  body: string;
  signature: string;
  full_text: string;
};
export type Appeal = {
  appeal_id: string;
  letter: AppealLetter;
  rebuttal_points: string[];
  additional_evidence_requested: string[];
};

export async function paAppeal(
  hospitalId: string,
  body: AppealRequest,
): Promise<Appeal> {
  const { data } = await api.post<Appeal>(`/api/${hospitalId}/pa/appeal`, body);
  return data;
}

// --- /evidence/ground ----------------------------------------------------------------
export type GroundingVerdict = "supported" | "partial" | "unsupported";
export type GroundingCitation = {
  index?: number;
  title: string;
  source?: string;
  year?: number;
  url?: string;
  score?: number;
};
export type EvidenceGrounding = {
  grounded: boolean;
  verdict: GroundingVerdict;
  confidence: number;
  citations: GroundingCitation[];
  supporting_evidence: string[];
  rationale: string;
};

export async function evidenceGround(
  hospitalId: string,
  recommendation: string,
  context = "",
  k = 6,
): Promise<EvidenceGrounding> {
  const { data } = await api.post<EvidenceGrounding>(
    `/api/${hospitalId}/evidence/ground`,
    { recommendation, context, k },
  );
  return data;
}
