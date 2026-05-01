"""Voice agent webhook + simulator router.

Two surfaces, one brain:

  * Twilio Voice (real phone calls)
      POST /api/voice/incoming           — first ring; returns greeting + first <Record>
      POST /api/voice/turn/{call_id}     — Twilio posts the recording URL; we transcribe + respond
      POST /api/voice/status             — Twilio status callback (call ended, etc.)

  * Browser simulator (frontend demo, no Twilio account needed)
      POST /api/voice/simulator/start    — open a session, get first agent line + audio
      POST /api/voice/simulator/turn     — send a user line, get agent reply + audio
      POST /api/voice/simulator/end      — finalize the session

  * Admin (clinician PIN)
      GET  /api/voice/calls              — recent call list
      GET  /api/voice/calls/{call_id}    — single transcript
      GET  /api/voice/stats              — intent breakdown / volume / avg duration
      GET  /api/voice/appointments       — voice-booked appointments
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from db import storage
from lib.auth import audit, require_clinician
from services import transcription
from services.voice_agent import intents, prompts, session, tts_cache

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


# --- Twilio TwiML helpers ------------------------------------------------------------


def _twiml(body: str) -> Response:
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'
    return Response(content=xml, media_type="application/xml")


def _say_or_play(text: str, language: str, base_url: str) -> str:
    """Prefer ElevenLabs (cached). Fall back to Twilio's free <Say> if unavailable."""
    audio_url = tts_cache.get_or_generate(text, language=language)
    if audio_url:
        return f'<Play>{_xml_escape(audio_url)}</Play>'
    # <Say> uses Twilio's built-in voices — much cheaper than Polly Neural.
    voice = "Polly.Joanna" if language == "en" else "Polly.Bianca-Neural"
    lang_attr = {"en": "en-US", "es": "es-ES"}.get(language, "en-US")
    return f'<Say voice="{voice}" language="{lang_attr}">{_xml_escape(text)}</Say>'


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )


def _record_block(call_id: str, base_url: str) -> str:
    """Twilio records up to 30s, with 2s of silence ending the turn."""
    return (
        f'<Record action="{base_url}/api/voice/turn/{call_id}" '
        f'method="POST" maxLength="30" timeout="2" trim="trim-silence" '
        f'playBeep="false" />'
    )


# --- Twilio: incoming call -----------------------------------------------------------


@router.post("/incoming")
async def twilio_incoming(request: Request) -> Response:
    """Twilio hits this on first ring. We greet the caller and start the first turn."""
    form = dict(await request.form())
    call_sid = form.get("CallSid", "")
    caller = form.get("From", "")
    to = form.get("To", "")
    base_url = _base_url(request)

    # Map the dialed number to a hospital. Default to demo for now; production
    # looks up `to` against `solace-hospitals.voice_phone_number`.
    hospital_id = _hospital_for_dialed_number(to)

    # Default to English greeting; Claude switches if the caller does.
    rec = session.start(
        hospital_id=hospital_id,
        caller_phone=caller,
        language="en",
        channel="twilio",
        twilio_call_sid=call_sid,
    )

    hospital = storage.get_hospital(hospital_id) or {}
    greeting = prompts.GREETINGS["en"].format(hospital_name=hospital.get("name", "the clinic"))
    session.append_turn(rec["call_id"], role="assistant", text=greeting)

    body = _say_or_play(greeting, "en", base_url) + _record_block(rec["call_id"], base_url)
    return _twiml(body)


# --- Twilio: per-turn handler --------------------------------------------------------


@router.post("/turn/{call_id}")
async def twilio_turn(call_id: str = Path(...), request: Request = None) -> Response:
    """Twilio posts the recording URL after each <Record>. We transcribe with Whisper,
    pass to Claude, and reply with the next TwiML."""
    form = dict(await request.form()) if request else {}
    recording_url = form.get("RecordingUrl", "")
    base_url = _base_url(request)
    rec = session.get(call_id)
    if not rec:
        # Stale callback — bail gracefully.
        return _twiml('<Hangup/>')

    user_text = ""
    if recording_url:
        try:
            user_text = _whisper_from_twilio_url(recording_url)
        except Exception as e:  # noqa: BLE001
            log.warning("voice whisper fail: %s", e)
            user_text = ""

    if not user_text.strip():
        # Caller said nothing audible — re-prompt once.
        body = _say_or_play(prompts.NO_INPUT_PROMPT, rec.get("language", "en"), base_url) \
               + _record_block(call_id, base_url)
        return _twiml(body)

    session.append_turn(call_id, role="user", text=user_text)
    turn = intents.run_turn(history=rec.get("history", []), user_text=user_text, call_ctx=rec)
    session.update(call_id, {"history": turn["history"]})
    if turn.get("tool"):
        session.append_tool(
            call_id,
            name=turn["tool"],
            tool_input=turn.get("tool_result", {}).get("input", {}) if isinstance(turn.get("tool_result"), dict) else {},
            result_summary=turn.get("say", "")[:200],
        )
        session.update(call_id, {"intent": turn["tool"]})
    if turn.get("escalate"):
        session.update(call_id, {"escalation": turn["escalate"]})
    say = turn.get("say") or prompts.NO_INPUT_PROMPT
    session.append_turn(call_id, role="assistant", text=say)

    # Escalate to a human → <Dial> the configured number, then end.
    if turn.get("escalate") == "human":
        hospital = storage.get_hospital(rec["hospital_id"]) or {}
        dial_to = hospital.get("voice_escalation_phone")
        if dial_to:
            body = _say_or_play(say, rec.get("language", "en"), base_url) \
                   + f'<Dial>{_xml_escape(dial_to)}</Dial>'
            session.end(call_id, disposition="transferred")
            return _twiml(body)
        session.end(call_id, disposition="transfer_unconfigured")
        return _twiml(_say_or_play("I'll have someone call you back shortly. Goodbye.",
                                    rec.get("language", "en"), base_url) + "<Hangup/>")
    if turn.get("escalate") == "911":
        session.end(call_id, disposition="emergency_911")
        return _twiml(_say_or_play(say, rec.get("language", "en"), base_url) + "<Hangup/>")

    body = _say_or_play(say, rec.get("language", "en"), base_url) + _record_block(call_id, base_url)
    return _twiml(body)


@router.post("/status")
async def twilio_status(request: Request) -> Response:
    """Twilio status callback. We finalize sessions when the call really ends."""
    form = dict(await request.form())
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    if call_sid and status in {"completed", "failed", "busy", "no-answer", "canceled"}:
        rec = session.get(call_sid)
        if rec and rec.get("status") == "active":
            session.end(call_sid, disposition=f"twilio_{status}")
    return Response(status_code=200, content="")


# --- Browser simulator ---------------------------------------------------------------


class SimulatorStartBody(BaseModel):
    hospital_id: str = "demo"
    language: str = "en"


class SimulatorTurnBody(BaseModel):
    call_id: str
    text: str


@router.post("/simulator/start")
def simulator_start(body: SimulatorStartBody) -> dict:
    rec = session.start(
        hospital_id=body.hospital_id,
        caller_phone=None,
        language=body.language,
        channel="simulator",
    )
    hospital = storage.get_hospital(body.hospital_id) or {}
    lang = (body.language or "en")[:2]
    template = prompts.GREETINGS.get(lang, prompts.GREETINGS["en"])
    greeting = template.format(hospital_name=hospital.get("name", "the clinic"))
    session.append_turn(rec["call_id"], role="assistant", text=greeting)
    audio_url = tts_cache.get_or_generate(greeting, language=lang)
    return {
        "call_id": rec["call_id"],
        "say": greeting,
        "audio_url": audio_url,
        "language": lang,
    }


@router.post("/simulator/turn")
def simulator_turn(body: SimulatorTurnBody) -> dict:
    rec = session.get(body.call_id)
    if not rec:
        raise HTTPException(status_code=404, detail="unknown call_id")
    user_text = (body.text or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text required")
    session.append_turn(body.call_id, role="user", text=user_text)
    turn = intents.run_turn(history=rec.get("history", []), user_text=user_text, call_ctx=rec)
    session.update(body.call_id, {"history": turn["history"]})
    if turn.get("tool"):
        session.append_tool(
            body.call_id,
            name=turn["tool"],
            tool_input=turn.get("tool_result", {}) if isinstance(turn.get("tool_result"), dict) else {},
            result_summary=turn.get("say", "")[:200],
        )
        session.update(body.call_id, {"intent": turn["tool"]})
    if turn.get("escalate"):
        session.update(body.call_id, {"escalation": turn["escalate"]})
    say = turn.get("say") or prompts.NO_INPUT_PROMPT
    session.append_turn(body.call_id, role="assistant", text=say)
    audio_url = tts_cache.get_or_generate(say, language=rec.get("language", "en"))
    return {
        "call_id": body.call_id,
        "say": say,
        "audio_url": audio_url,
        "tool": turn.get("tool"),
        "escalate": turn.get("escalate"),
    }


class SimulatorEndBody(BaseModel):
    call_id: str
    disposition: str = "ended_by_user"


@router.post("/simulator/end")
def simulator_end(body: SimulatorEndBody) -> dict:
    rec = session.get(body.call_id)
    if not rec:
        return {"ok": True}
    session.end(body.call_id, disposition=body.disposition)
    return {"ok": True}


# --- Admin / dashboard ---------------------------------------------------------------


@router.get("/calls")
def list_calls(
    hospital_id: str = Query("demo"),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "voice.calls.list")
    rows = session.list_recent(hospital_id=hospital_id, limit=50)
    # Strip the live `history` field from API response — it carries internal Claude
    # message blocks (tool_use objects) that aren't useful for the UI.
    cleaned = [{k: v for k, v in r.items() if k != "history"} for r in rows]
    return {"calls": cleaned}


@router.get("/calls/{call_id}")
def get_call(
    call_id: str = Path(...),
    hospital_id: str = Query("demo"),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "voice.calls.detail", patient_id=call_id)
    rec = session.get(call_id)
    if not rec or rec.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="call not found")
    return {k: v for k, v in rec.items() if k != "history"}


@router.get("/stats")
def voice_stats(
    hospital_id: str = Query("demo"),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "voice.stats")
    return session.stats(hospital_id=hospital_id)


@router.get("/appointments")
def list_voice_appointments(
    hospital_id: str = Query("demo"),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "voice.appointments.list")
    return {"appointments": storage.list_appointments(hospital_id=hospital_id)}


# --- Helpers -----------------------------------------------------------------------


def _base_url(request: Request | None) -> str:
    """Build the public URL Twilio should call back to. We prefer the
    forwarded host (CloudFront → API GW), falling back to the request URL host."""
    if request is None:
        return ""
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    return f"{fwd_proto}://{fwd_host}".rstrip("/")


def _hospital_for_dialed_number(to: str) -> str:
    """Look up which hospital a dialed Twilio number belongs to.

    Fast path for v1: every number routes to "demo". Real version queries
    `solace-hospitals` GSI on `voice_phone_number`.
    """
    return "demo"


def _whisper_from_twilio_url(recording_url: str) -> str:
    """Twilio appends recording metadata; download the .mp3 binary, pass to Whisper.
    Twilio Recording URLs need basic-auth (account SID + auth token) for private
    recordings — public recordings work without. v1 assumes public; production
    flips this to authenticated GETs.
    """
    import httpx
    url = recording_url + ".mp3" if not recording_url.endswith(".mp3") else recording_url
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        audio_bytes = resp.content
    t = transcription.transcribe(audio_bytes, filename="twilio_recording.mp3")
    return (t.text or "").strip()
