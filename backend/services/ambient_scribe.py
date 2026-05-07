"""Ambient scribe pipeline.

Two paths:

1. **Real path** (production): Audio uploaded to S3 -> AWS HealthScribe job -> poll
   until COMPLETE -> read summary + transcript JSON from S3 -> Claude refinement
   layer rewrites SOAP sections in our house style preserving evidence links ->
   return Linked Evidence note.

2. **Synthetic path** (no-BAA dev mode): Caller passes a pre-existing transcript
   string (e.g. from the existing voice agent / OpenAI Whisper). We synthesize
   a HealthScribe-shaped output from the transcript using a single Claude call
   that emits sections + evidence-span anchors directly. Same downstream API.

The downstream API is the same in both modes, so the frontend never branches.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_SYNTH_SYSTEM = """You convert a doctor-patient conversation transcript into a HealthScribe-shaped \
clinical document with Linked Evidence — every line of the note must cite the transcript spans \
that support it.

Return JSON ONLY (no markdown, no preamble):
{
  "sections": [
    {
      "name": "CHIEF_COMPLAINT" | "HPI" | "REVIEW_OF_SYSTEMS" | "PAST_MEDICAL_HISTORY" | "MEDICATIONS" | "ALLERGIES" | "PHYSICAL_EXAM" | "ASSESSMENT" | "PLAN",
      "summary": [
        {"text": "one sentence of the section in clinical shorthand", "evidence_segments": [3, 5]}
      ]
    }
  ],
  "transcript_segments": [
    {"id": 0, "speaker": "CLINICIAN" | "PATIENT", "begin_ms": 0, "end_ms": 4000, "content": "the utterance"}
  ]
}

Rules:
- Split the transcript into utterance-level segments. Reasonable default ~3-8 seconds per segment.
- The speaker tag is your best inference (clinician asks/orders, patient describes/answers).
- evidence_segments must reference REAL segment ids in transcript_segments.
- Use clinical shorthand: c/o, hx, sx, SOB, N/V, abd, NKDA, etc.
- NEVER invent facts not present in the transcript. If a section has no support, omit it or write 'not discussed'.
- ASSESSMENT prefix: 'AI draft - <impression>'. PLAN: short bullet-style prose, one sentence each.
"""


def synthesize_from_transcript(transcript: str) -> dict[str, Any]:
    """No-BAA path. Single Claude call returns segments + sections + evidence links."""
    if not settings.anthropic_api_key:
        return {"sections": [], "transcript_segments": [], "error": "anthropic_api_key not configured"}
    user = (
        f'Transcript:\n"""\n{transcript[:14000]}\n"""\n\n'
        "Return the JSON now."
    )
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=3000,
            system=_SYNTH_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="ambient_scribe_synth",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
        # Normalize + post-validate evidence ids
        ids = {int(s.get("id", -1)) for s in data.get("transcript_segments", [])}
        for sec in data.get("sections", []):
            for entry in sec.get("summary", []):
                entry["evidence_segments"] = [i for i in entry.get("evidence_segments", []) if int(i) in ids]
        return data
    except Exception as e:
        log.warning("scribe synth failed: %s", e)
        return {"sections": [], "transcript_segments": [], "error": str(e)}


# ---- Real HealthScribe path -------------------------------------------------------
def start_healthscribe_job(audio_s3_uri: str, output_s3_uri: str, *, job_name: str | None = None) -> dict[str, Any]:  # pragma: no cover (requires AWS BAA)
    """Kick off a HealthScribe job. Returns job_name + status URL.

    Requires the AWS BAA + IAM role with `transcribe:StartMedicalScribeJob`. In
    dev / synthetic mode this returns a stub indicating not-configured.
    """
    if settings.solace_mode != "aws":
        return {"status": "skipped_local_mode", "job_name": None}
    try:
        import boto3
        client = boto3.client("transcribe", region_name=settings.aws_region)
        name = job_name or f"solace-scribe-{uuid.uuid4().hex[:10]}"
        client.start_medical_scribe_job(
            MedicalScribeJobName=name,
            Media={"MediaFileUri": audio_s3_uri},
            OutputBucketName=output_s3_uri.split("/")[2],
            DataAccessRoleArn=os.environ["HEALTHSCRIBE_ROLE_ARN"],
            Settings={
                "ShowSpeakerLabels": True,
                "ChannelIdentification": False,
                "MaxSpeakerLabels": 4,
            },
        )
        return {"status": "in_progress", "job_name": name}
    except Exception as e:
        log.warning("start_healthscribe_job failed: %s", e)
        return {"status": "failed", "error": str(e), "job_name": None}


def poll_healthscribe_job(job_name: str) -> dict[str, Any]:  # pragma: no cover
    """Poll HealthScribe; when complete, read output JSON from S3 and return."""
    if settings.solace_mode != "aws":
        return {"status": "skipped_local_mode"}
    try:
        import boto3
        client = boto3.client("transcribe", region_name=settings.aws_region)
        resp = client.get_medical_scribe_job(MedicalScribeJobName=job_name)
        job = resp["MedicalScribeJob"]
        status = job["MedicalScribeJobStatus"]
        if status == "COMPLETED":
            transcript_uri = job["MedicalScribeOutput"]["TranscriptFileUri"]
            doc_uri = job["MedicalScribeOutput"]["ClinicalDocumentUri"]
            return {
                "status": "COMPLETED",
                "transcript_uri": transcript_uri,
                "clinical_document_uri": doc_uri,
            }
        return {"status": status}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def normalize_healthscribe_output(doc: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    """Reshape HealthScribe's native JSON to our internal {sections, transcript_segments} shape."""
    segments = []
    for i, item in enumerate(transcript.get("Conversation", {}).get("TranscriptItems", [])):
        segments.append({
            "id": i,
            "speaker": item.get("ParticipantDetails", {}).get("ParticipantRole", ""),
            "begin_ms": int(item.get("BeginAudioTime", 0) * 1000),
            "end_ms": int(item.get("EndAudioTime", 0) * 1000),
            "content": item.get("Alternatives", [{}])[0].get("Content", ""),
        })

    sections = []
    for section_name, section in (doc.get("ClinicalDocumentation", {}) or {}).items():
        summary = []
        for s in section.get("Summary", []) or []:
            summary.append({
                "text": s.get("SummarizedSegment", ""),
                "evidence_segments": [int(e.get("SegmentId", 0)) for e in s.get("EvidenceLinks", []) or []],
            })
        sections.append({"name": section_name.upper().replace(" ", "_"), "summary": summary})

    return {"sections": sections, "transcript_segments": segments}


# ---- Refinement layer (style transfer) -------------------------------------------
_REFINE_SYSTEM = """Refine an AI-generated clinical note in Solace house style WITHOUT introducing \
any new facts. Preserve the section structure and the evidence_segments arrays exactly.

Style:
- Clinical shorthand (c/o, hx, sx, SOB, N/V, abd, NKDA, etc.)
- HPI <= 60 words
- ASSESSMENT prefixed 'AI draft -'
- PLAN as short bullet-like sentences
- No invented vitals, exam findings, labs, or doses

Return JSON in the exact same shape received. Do not modify transcript_segments.
"""


def refine(structured: dict[str, Any]) -> dict[str, Any]:
    if not settings.anthropic_api_key or not structured.get("sections"):
        return structured
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=2200,
            system=_REFINE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(structured)}],
            purpose="ambient_scribe_refine",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(text)
        # Force preserve transcript_segments
        out["transcript_segments"] = structured["transcript_segments"]
        return out
    except Exception as e:
        log.warning("scribe refine failed: %s", e)
        return structured


# ---- Convenience: render to plain SOAP text --------------------------------------
def to_soap_text(structured: dict[str, Any]) -> str:
    order = [
        "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
        "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    ]
    by_name = {s["name"]: s for s in structured.get("sections", [])}
    lines: list[str] = []
    for name in order:
        sec = by_name.get(name)
        if not sec:
            continue
        label = name.replace("_", " ").title()
        lines.append(f"{label}:")
        for entry in sec.get("summary", []):
            lines.append(f"  - {entry.get('text', '')}")
        lines.append("")
    return "\n".join(lines).strip()
