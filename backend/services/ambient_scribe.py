"""Ambient scribe pipeline (Abridge-grade).

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

Depth features layered on top:

* **Linked Evidence resolution** — every note line's ``evidence_segments`` (a list
  of integer segment ids) is resolved into concrete, renderable evidence objects:
  ``{segment_id, begin_ms, end_ms, speaker, snippet}`` plus a rolled-up
  ``evidence_span`` ``{begin_ms, end_ms, segment_ids}`` covering the whole line.
  The frontend can jump audio playback straight to a cited utterance.
* **Specialty-aware SOAP** — the synthesis prompt and the section ordering adapt
  to a clinical specialty (``emergency``, ``cardiology``, ``primary_care``, etc.),
  so an ED note leads with disposition while a cardiology note carries a richer
  exam/ROS scaffold.
* **Pause / resume / regenerate-one-section** — a long encounter can be recorded
  in chunks; ``append_transcript_chunk`` accumulates a session without
  re-running the model, ``finalize_session`` runs synthesis once, and
  ``regenerate_section`` re-derives a single SOAP section from the transcript
  without touching the rest of the note or re-recording audio.
* **Latency** — independent Claude calls (synthesis + per-section regen, refine)
  are dispatched concurrently via ``asyncio.to_thread`` + ``asyncio.gather`` in
  the async helpers, since ``lib.claude.messages_create`` is synchronous.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

from lib import claude, content_guard
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

# Canonical SOAP section names the pipeline knows how to render.
_KNOWN_SECTIONS = (
    "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
    "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    "DISPOSITION",
)

# Specialty-aware section ordering. Each entry lists the sections in the order
# a clinician of that specialty expects to read them. The default ED order
# leads with disposition urgency; primary care leads with a fuller history.
_SPECIALTY_SECTION_ORDER: dict[str, tuple[str, ...]] = {
    "emergency": (
        "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
        "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
        "DISPOSITION",
    ),
    "primary_care": (
        "CHIEF_COMPLAINT", "HPI", "PAST_MEDICAL_HISTORY", "MEDICATIONS",
        "ALLERGIES", "REVIEW_OF_SYSTEMS", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    ),
    "cardiology": (
        "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
        "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    ),
    "pediatrics": (
        "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
        "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    ),
}
_DEFAULT_SPECIALTY = "emergency"

# Per-specialty guidance injected into the synthesis system prompt so the model
# emphasizes the fields that specialty cares about most.
_SPECIALTY_GUIDANCE: dict[str, str] = {
    "emergency": (
        "Specialty: Emergency Medicine. Lead the assessment with acuity and the "
        "must-not-miss differential. Always populate DISPOSITION (admit / observe / "
        "discharge / transfer) and red-flag return precautions in PLAN."
    ),
    "primary_care": (
        "Specialty: Primary Care. Emphasize chronic disease context, preventive "
        "care gaps, and medication reconciliation. DISPOSITION is usually routine "
        "follow-up; omit it unless escalation is discussed."
    ),
    "cardiology": (
        "Specialty: Cardiology. Capture cardiac risk factors, exertional symptoms, "
        "NYHA / CCS class where stated, and prior cardiac workup. PHYSICAL_EXAM "
        "should foreground cardiopulmonary findings."
    ),
    "pediatrics": (
        "Specialty: Pediatrics. Note weight-based dosing context, immunization "
        "status, developmental milestones, and caregiver-reported history; the "
        "historian is often a parent, not the patient."
    ),
}


def _resolve_specialty(specialty: str | None) -> str:
    """Map a free-form specialty hint to a known key, defaulting to emergency."""
    if not specialty:
        return _DEFAULT_SPECIALTY
    key = specialty.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ed": "emergency", "er": "emergency", "emergency_medicine": "emergency",
        "family_medicine": "primary_care", "internal_medicine": "primary_care",
        "gp": "primary_care", "peds": "pediatrics", "cards": "cardiology",
    }
    key = aliases.get(key, key)
    return key if key in _SPECIALTY_SECTION_ORDER else _DEFAULT_SPECIALTY


def _section_order(specialty: str | None) -> tuple[str, ...]:
    return _SPECIALTY_SECTION_ORDER[_resolve_specialty(specialty)]


_SYNTH_SYSTEM = """You convert a doctor-patient conversation transcript into a HealthScribe-shaped \
clinical document with Linked Evidence — every line of the note must cite the transcript spans \
that support it.

Return JSON ONLY (no markdown, no preamble):
{
  "sections": [
    {
      "name": "CHIEF_COMPLAINT" | "HPI" | "REVIEW_OF_SYSTEMS" | "PAST_MEDICAL_HISTORY" | "MEDICATIONS" | "ALLERGIES" | "PHYSICAL_EXAM" | "ASSESSMENT" | "PLAN" | "DISPOSITION",
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
- EVERY summary line MUST cite at least one evidence segment. Never leave evidence_segments empty.
- Use clinical shorthand: c/o, hx, sx, SOB, N/V, abd, NKDA, etc.
- NEVER invent facts not present in the transcript. If a section has no support, omit it or write 'not discussed'.
- ASSESSMENT prefix: 'AI draft - <impression>'. PLAN: short bullet-style prose, one sentence each.
"""

_REGEN_SECTION_SYSTEM = """You are a medical scribe regenerating ONE section of an existing \
clinical note from the conversation transcript. The transcript segments are given with their \
integer ids. Re-derive ONLY the requested section.

Return JSON ONLY:
{"name": "<SECTION_NAME>", "summary": [{"text": "...", "evidence_segments": [int, ...]}]}

Rules:
- evidence_segments must reference REAL segment ids from the supplied transcript.
- EVERY summary line MUST cite at least one evidence segment.
- Clinical shorthand. Never invent facts absent from the transcript.
- ASSESSMENT prefix 'AI draft - '. PLAN as short bullet-like sentences.
"""


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    return text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _claude_json(*, system: str, user: str, max_tokens: int, purpose: str) -> dict[str, Any]:
    """Single synchronous Claude call returning parsed JSON. Raises on failure."""
    resp = claude.messages_create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        purpose=purpose,
    )
    text = "".join(getattr(b, "text", "") for b in resp.content)
    return json.loads(_strip_json_fence(text))


# ---- Linked Evidence resolution --------------------------------------------------
def _segment_index(structured: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map segment id -> segment dict for O(1) evidence lookups."""
    index: dict[int, dict[str, Any]] = {}
    for seg in structured.get("transcript_segments", []) or []:
        try:
            index[int(seg.get("id"))] = seg
        except (TypeError, ValueError):
            continue
    return index


def _snippet(content: str, limit: int = 180) -> str:
    content = (content or "").strip()
    return content if len(content) <= limit else content[: limit - 1].rstrip() + "…"


def resolve_linked_evidence(structured: dict[str, Any]) -> dict[str, Any]:
    """Resolve each note line's ``evidence_segments`` ids into concrete evidence.

    For every ``summary`` entry this adds two keys (the original
    ``evidence_segments`` int list is preserved untouched for backward compat):

    * ``linked_evidence`` — list of
      ``{segment_id, begin_ms, end_ms, speaker, snippet}`` in transcript order,
      one per resolvable cited segment.
    * ``evidence_span`` — rolled-up
      ``{begin_ms, end_ms, segment_ids}`` covering the line's full citation
      range, or ``None`` when nothing resolved. Lets the UI scrub audio to the
      entire supporting passage in one gesture.

    Also annotates each section with ``evidence_coverage`` — the fraction of its
    summary lines that carry at least one resolvable citation (0.0-1.0) — so the
    UI can flag uncited claims for clinician review. Mutates and returns
    ``structured``.
    """
    index = _segment_index(structured)
    for section in structured.get("sections", []) or []:
        summary = section.get("summary", []) or []
        cited_lines = 0
        for entry in summary:
            raw_ids = entry.get("evidence_segments", []) or []
            linked: list[dict[str, Any]] = []
            seen: set[int] = set()
            for rid in raw_ids:
                try:
                    sid = int(rid)
                except (TypeError, ValueError):
                    continue
                seg = index.get(sid)
                if seg is None or sid in seen:
                    continue
                seen.add(sid)
                linked.append({
                    "segment_id": sid,
                    "begin_ms": int(seg.get("begin_ms", 0) or 0),
                    "end_ms": int(seg.get("end_ms", 0) or 0),
                    "speaker": seg.get("speaker", "") or "",
                    "snippet": _snippet(seg.get("content", "")),
                })
            linked.sort(key=lambda e: (e["begin_ms"], e["segment_id"]))
            entry["linked_evidence"] = linked
            if linked:
                cited_lines += 1
                entry["evidence_span"] = {
                    "begin_ms": min(e["begin_ms"] for e in linked),
                    "end_ms": max(e["end_ms"] for e in linked),
                    "segment_ids": [e["segment_id"] for e in linked],
                }
            else:
                entry["evidence_span"] = None
        section["evidence_coverage"] = round(cited_lines / len(summary), 3) if summary else 0.0
    return structured


# ---- Synthetic (no-BAA) path -----------------------------------------------------
def synthesize_from_transcript(
    transcript: str,
    *,
    specialty: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """No-BAA path. Single Claude call returns segments + sections + evidence links.

    The transcript is scanned through ``content_guard`` (SEC-005 / COMP-001)
    before reaching Claude. Output sections are ordered for ``specialty`` and
    every line carries resolved Linked Evidence.

    ``specialty`` / ``source_ip`` / ``user_agent`` are keyword-only and optional,
    so existing single-arg callers keep working unchanged.
    """
    if not settings.anthropic_api_key:
        return {"sections": [], "transcript_segments": [], "error": "anthropic_api_key not configured"}

    safe, cleaned, findings = content_guard.scan(
        transcript, label="ambient_scribe", source_ip=source_ip, user_agent=user_agent
    )
    if not safe:
        log.warning("scribe synth blocked by content_guard: %s", findings)
        return {"sections": [], "transcript_segments": [], "error": "content_guard_blocked", "findings": findings}

    spec = _resolve_specialty(specialty)
    system = _SYNTH_SYSTEM + "\n\n" + _SPECIALTY_GUIDANCE.get(spec, "")
    user = (
        f'Transcript:\n"""\n{cleaned[:14000]}\n"""\n\n'
        "Return the JSON now."
    )
    try:
        data = _claude_json(
            system=system, user=user, max_tokens=3000, purpose="ambient_scribe_synth"
        )
        return _finalize_structured(data, specialty=spec)
    except Exception as e:
        log.warning("scribe synth failed: %s", e)
        return {"sections": [], "transcript_segments": [], "error": str(e)}


def _finalize_structured(data: dict[str, Any], *, specialty: str) -> dict[str, Any]:
    """Normalize ids, drop dangling evidence refs, order sections, resolve evidence."""
    data.setdefault("sections", [])
    data.setdefault("transcript_segments", [])

    ids = {int(s.get("id", -1)) for s in data["transcript_segments"] if str(s.get("id", "")).lstrip("-").isdigit()}
    for sec in data["sections"]:
        sec["name"] = str(sec.get("name", "")).upper().replace(" ", "_")
        for entry in sec.get("summary", []) or []:
            entry["evidence_segments"] = [
                int(i) for i in entry.get("evidence_segments", []) or []
                if str(i).lstrip("-").isdigit() and int(i) in ids
            ]

    order = _section_order(specialty)
    rank = {name: i for i, name in enumerate(order)}
    data["sections"].sort(key=lambda s: rank.get(s.get("name", ""), len(order)))
    data["specialty"] = specialty
    return resolve_linked_evidence(data)


# ---- Async fan-out helpers (latency) ---------------------------------------------
async def synthesize_from_transcript_async(
    transcript: str,
    *,
    specialty: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    refine_note: bool = True,
) -> dict[str, Any]:
    """Async wrapper: runs synthesis and the style-refine pass without blocking the
    event loop. ``lib.claude.messages_create`` is synchronous, so each call is
    offloaded with ``asyncio.to_thread``. Synthesis and refine are sequential
    (refine depends on synthesis), but this frees the loop for other requests.
    """
    structured = await asyncio.to_thread(
        synthesize_from_transcript,
        transcript, specialty=specialty, source_ip=source_ip, user_agent=user_agent,
    )
    if refine_note and structured.get("sections"):
        structured = await asyncio.to_thread(refine, structured)
    return structured


async def regenerate_sections_async(
    structured: dict[str, Any], section_names: list[str], *, specialty: str | None = None
) -> dict[str, Any]:
    """Regenerate several sections concurrently. Each section is an independent
    Claude call, so they fan out with ``asyncio.gather`` over ``asyncio.to_thread``
    — N sections cost roughly one call's latency instead of N.
    """
    targets = [str(n).upper().replace(" ", "_") for n in section_names]
    results = await asyncio.gather(
        *(asyncio.to_thread(_regenerate_section_payload, structured, name, specialty)
          for name in targets),
        return_exceptions=True,
    )
    by_name = {s["name"]: s for s in structured.get("sections", [])}
    for name, res in zip(targets, results):
        if isinstance(res, Exception) or res is None:
            log.warning("regenerate section %s failed: %s", name, res)
            continue
        by_name[name] = res
    structured["sections"] = list(by_name.values())
    spec = _resolve_specialty(specialty or structured.get("specialty"))
    order = _section_order(spec)
    rank = {n: i for i, n in enumerate(order)}
    structured["sections"].sort(key=lambda s: rank.get(s.get("name", ""), len(order)))
    return resolve_linked_evidence(structured)


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


def normalize_healthscribe_output(
    doc: dict[str, Any], transcript: dict[str, Any], *, specialty: str | None = None
) -> dict[str, Any]:
    """Reshape HealthScribe's native JSON to our internal {sections, transcript_segments}
    shape, then resolve Linked Evidence and order sections for ``specialty``.

    ``specialty`` is keyword-only and optional — existing two-arg callers are
    unaffected.
    """
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

    return _finalize_structured(
        {"sections": sections, "transcript_segments": segments},
        specialty=_resolve_specialty(specialty),
    )


# ---- Refinement layer (style transfer) -------------------------------------------
_REFINE_SYSTEM = """Refine an AI-generated clinical note in Solace house style WITHOUT introducing \
any new facts. Preserve the section structure and the evidence_segments arrays exactly.

Style:
- Clinical shorthand (c/o, hx, sx, SOB, N/V, abd, NKDA, etc.)
- HPI <= 60 words
- ASSESSMENT prefixed 'AI draft -'
- PLAN as short bullet-like sentences
- No invented vitals, exam findings, labs, or doses

Return JSON in the exact same shape received. Keep every summary entry's \
evidence_segments array EXACTLY as received. Do not modify transcript_segments.
"""


def refine(structured: dict[str, Any]) -> dict[str, Any]:
    """Style-transfer pass. Preserves transcript_segments and re-resolves Linked
    Evidence afterward (refine may not echo the resolved fields)."""
    if not settings.anthropic_api_key or not structured.get("sections"):
        return structured
    try:
        # Send only the lightweight shape (drop resolved evidence to save tokens).
        slim = {
            "sections": [
                {
                    "name": s.get("name"),
                    "summary": [
                        {"text": e.get("text", ""), "evidence_segments": e.get("evidence_segments", [])}
                        for e in s.get("summary", []) or []
                    ],
                }
                for s in structured.get("sections", [])
            ],
            "transcript_segments": structured.get("transcript_segments", []),
        }
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=2200,
            system=_REFINE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(slim)}],
            purpose="ambient_scribe_refine",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        out = json.loads(_strip_json_fence(text))
        # Force preserve transcript_segments + specialty, then re-resolve evidence.
        out["transcript_segments"] = structured["transcript_segments"]
        out["specialty"] = structured.get("specialty", _DEFAULT_SPECIALTY)
        return resolve_linked_evidence(out)
    except Exception as e:
        log.warning("scribe refine failed: %s", e)
        return structured


# ---- Regenerate a single section (no re-recording) -------------------------------
def _regenerate_section_payload(
    structured: dict[str, Any], section_name: str, specialty: str | None
) -> dict[str, Any] | None:
    """Run one Claude call to re-derive ``section_name`` from the transcript.
    Returns a section dict or None on failure."""
    segments = structured.get("transcript_segments", []) or []
    if not segments:
        return None
    spec = _resolve_specialty(specialty or structured.get("specialty"))
    transcript_lines = "\n".join(
        f'[{s.get("id")}] {s.get("speaker", "?")}: {s.get("content", "")}'
        for s in segments
    )
    user = (
        f"{_SPECIALTY_GUIDANCE.get(spec, '')}\n\n"
        f"Section to regenerate: {section_name}\n\n"
        f"Transcript segments:\n{transcript_lines[:14000]}\n\n"
        "Return the JSON for that one section now."
    )
    data = _claude_json(
        system=_REGEN_SECTION_SYSTEM, user=user, max_tokens=900,
        purpose="ambient_scribe_regen_section",
    )
    ids = {int(s.get("id", -1)) for s in segments if str(s.get("id", "")).lstrip("-").isdigit()}
    for entry in data.get("summary", []) or []:
        entry["evidence_segments"] = [
            int(i) for i in entry.get("evidence_segments", []) or []
            if str(i).lstrip("-").isdigit() and int(i) in ids
        ]
    return {"name": str(data.get("name", section_name)).upper().replace(" ", "_"),
            "summary": data.get("summary", []) or []}


def regenerate_section(
    structured: dict[str, Any], section_name: str, *, specialty: str | None = None
) -> dict[str, Any]:
    """Re-derive ONE SOAP section from the existing transcript without touching the
    rest of the note and without re-recording audio.

    Returns the updated ``structured`` dict (other sections untouched, Linked
    Evidence re-resolved). On failure the original note is returned unchanged.
    """
    if not settings.anthropic_api_key:
        return structured
    name = str(section_name).upper().replace(" ", "_")
    try:
        regenerated = _regenerate_section_payload(structured, name, specialty)
    except Exception as e:
        log.warning("regenerate_section %s failed: %s", name, e)
        return structured
    if regenerated is None:
        return structured
    by_name = {s["name"]: s for s in structured.get("sections", [])}
    by_name[name] = regenerated
    spec = _resolve_specialty(specialty or structured.get("specialty"))
    order = _section_order(spec)
    rank = {n: i for i, n in enumerate(order)}
    structured["sections"] = sorted(
        by_name.values(), key=lambda s: rank.get(s.get("name", ""), len(order))
    )
    structured["specialty"] = spec
    return resolve_linked_evidence(structured)


# ---- Pause / resume: chunked recording sessions ----------------------------------
# A long encounter is recorded in pieces. The clinician can pause (stop sending
# chunks) and resume (send more) without losing prior audio. State is held in a
# process-local dict in dev mode; in AWS mode the router persists via db.storage
# and passes the accumulated transcript back in — see wiring notes.
_SESSIONS: dict[str, dict[str, Any]] = {}


def start_session(*, specialty: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    """Open a chunked-recording session. Returns ``{session_id, specialty, status}``."""
    sid = session_id or f"scribe-sess-{uuid.uuid4().hex[:12]}"
    _SESSIONS[sid] = {
        "session_id": sid,
        "specialty": _resolve_specialty(specialty),
        "chunks": [],
        "status": "recording",
        "created_ms": int(time.time() * 1000),
        "updated_ms": int(time.time() * 1000),
    }
    return {"session_id": sid, "specialty": _SESSIONS[sid]["specialty"], "status": "recording"}


def append_transcript_chunk(session_id: str, chunk: str) -> dict[str, Any]:
    """Append a transcript chunk to an in-progress session. No model call here —
    chunks just accumulate so the clinician can pause/resume freely."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"status": "unknown_session", "session_id": session_id}
    if chunk and chunk.strip():
        sess["chunks"].append(chunk.strip())
    sess["updated_ms"] = int(time.time() * 1000)
    sess["status"] = "recording"
    return {"session_id": session_id, "status": "recording", "chunk_count": len(sess["chunks"])}


def pause_session(session_id: str) -> dict[str, Any]:
    """Mark a session paused. Audio/transcript captured so far is retained."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"status": "unknown_session", "session_id": session_id}
    sess["status"] = "paused"
    sess["updated_ms"] = int(time.time() * 1000)
    return {"session_id": session_id, "status": "paused", "chunk_count": len(sess["chunks"])}


def resume_session(session_id: str) -> dict[str, Any]:
    """Resume a paused session so further chunks can be appended."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"status": "unknown_session", "session_id": session_id}
    sess["status"] = "recording"
    sess["updated_ms"] = int(time.time() * 1000)
    return {"session_id": session_id, "status": "recording", "chunk_count": len(sess["chunks"])}


def session_transcript(session_id: str) -> str:
    """Return the concatenated transcript accumulated for a session."""
    sess = _SESSIONS.get(session_id)
    return "\n".join(sess["chunks"]) if sess else ""


def finalize_session(
    session_id: str, *, source_ip: str | None = None, user_agent: str | None = None,
    refine_note: bool = True,
) -> dict[str, Any]:
    """Close a chunked session: synthesize the full note from all chunks in one
    pass. Marks the session ``finalized`` and returns the structured note."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"sections": [], "transcript_segments": [], "error": "unknown_session"}
    transcript = "\n".join(sess["chunks"])
    if not transcript.strip():
        return {"sections": [], "transcript_segments": [], "error": "empty_session"}
    structured = synthesize_from_transcript(
        transcript, specialty=sess["specialty"], source_ip=source_ip, user_agent=user_agent
    )
    if refine_note and structured.get("sections"):
        structured = refine(structured)
    sess["status"] = "finalized"
    sess["updated_ms"] = int(time.time() * 1000)
    structured["session_id"] = session_id
    return structured


# ---- Convenience: render to plain SOAP text --------------------------------------
def to_soap_text(structured: dict[str, Any]) -> str:
    """Render the structured note to plain SOAP text, ordered for its specialty."""
    order = _section_order(structured.get("specialty"))
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
    # Append any non-standard sections the model emitted that aren't in the order.
    for name, sec in by_name.items():
        if name in order:
            continue
        lines.append(f"{name.replace('_', ' ').title()}:")
        for entry in sec.get("summary", []):
            lines.append(f"  - {entry.get('text', '')}")
        lines.append("")
    return "\n".join(lines).strip()
