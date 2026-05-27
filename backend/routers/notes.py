"""Clinician notes + patient-education publish."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from db import storage
from lib.auth import audit, require_clinician
from services import patient_education

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., max_length=20_000)
    author: str = Field("Clinician", max_length=200)


@router.post("/patients/{patient_id}/notes")
def create_note(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: NoteBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "notes.create", patient_id=patient_id)
    if body is None or not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    # Prefer the authenticated clinician's name when available; fall back to body
    author = caller.get("name") if caller.get("auth_method") == "jwt" else (body.author.strip() or "Clinician")
    note = {
        "note_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "text": body.text.strip(),
        "author": author,
        "clinician_id": caller.get("clinician_id"),
        "created_at": _now_iso(),
    }
    storage.add_note(note)
    return {"success": True, "note": note}


@router.get("/patients/{patient_id}/notes")
def list_notes(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "notes.list", patient_id=patient_id)
    return {"notes": storage.list_notes(patient_id)}


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Either pass a specific note_id or let the server combine the latest note(s).
    note_id: str | None = Field(None, max_length=64)


@router.post("/patients/{patient_id}/publish-summary")
def publish_summary(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: PublishBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "notes.publish_summary", patient_id=patient_id)
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="patient not found")

    notes = storage.list_notes(patient_id)
    selected_text = ""
    if body and body.note_id:
        for n in notes:
            if n["note_id"] == body.note_id:
                selected_text = n["text"]
                break
    if not selected_text and notes:
        # Default: combine ALL notes (most recent last)
        selected_text = "\n\n".join(n["text"] for n in notes)
    # Empty clinician notes are OK — we can still generate from scribe + transcript.

    language = str(patient.get("language") or "en")
    result = patient_education.generate_summary(
        clinician_note=selected_text,
        scribe_note=patient.get("clinical_scribe_note", ""),
        transcript=patient.get("transcript", ""),
        patient_language=language,
    )
    if result.get("error"):
        # The provider error string can echo transcript / note fragments —
        # log it server-side, surface a static message to the clinician UI.
        import logging as _logging  # noqa: PLC0415

        _logging.getLogger(__name__).warning(
            "publish-summary generation failed for patient %s: %s",
            patient_id, result["error"],
        )
        raise HTTPException(status_code=502, detail="Patient summary generation is temporarily unavailable. Please try again.")

    import json as _json

    storage.update_patient(
        patient_id,
        {
            "patient_education": _json.dumps(result),
            "patient_education_published_at": _now_iso(),
        },
    )
    return {"success": True, "summary": result}
