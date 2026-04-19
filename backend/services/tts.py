"""ElevenLabs TTS. Generates MP3 and uploads to media storage (local disk or S3).

Script is intentionally short to keep ElevenLabs character usage low. The screen
carries the full comfort protocol — the voice just reassures and orients.
"""
from __future__ import annotations

import logging

import httpx

from db import media
from lib.config import settings

log = logging.getLogger(__name__)

_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
_MAX_SCRIPT_CHARS = 350


def compose_script(patient_explanation: str, comfort_protocol: list[dict], patient_name: str = "") -> str:
    """Short voice script. Full guidance stays on screen."""
    first = (comfort_protocol[0]["title"].rstrip(".") if comfort_protocol else "").strip()
    name_greeting = f"{patient_name.strip()}, " if patient_name else ""

    # Goal: ≤ 300 chars. Enough to feel human, short enough to stay on free tier.
    parts = [
        f"{name_greeting}{patient_explanation.strip()}",
        f"Read the screen for three ways to feel better right now." if not first else
        f"Read the screen for three ways to feel better — starting with: {first}.",
        "We will alert a clinician if anything changes.",
    ]
    script = " ".join(p for p in parts if p).strip()
    if len(script) > _MAX_SCRIPT_CHARS:
        script = script[:_MAX_SCRIPT_CHARS].rsplit(". ", 1)[0] + "."
    return script


def generate_and_upload(script: str, language: str, patient_id: str) -> str | None:
    from lib import ai_log  # noqa: PLC0415

    if not settings.elevenlabs_api_key:
        log.warning("ELEVENLABS_API_KEY missing; skipping TTS")
        return None
    try:
        url = f"{_ELEVENLABS_BASE}/text-to-speech/{settings.elevenlabs_voice_id}"
        headers = {
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": script,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        if language and len(language) == 2:
            payload["language_code"] = language

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            mp3_bytes = resp.content

        ai_log.record(provider="elevenlabs", model="eleven_multilingual_v2", purpose="tts",
                      input_bytes=len(script.encode()), output_bytes=len(mp3_bytes), success=True)
        filename = f"{patient_id}.mp3"
        return media.save("audio", filename, mp3_bytes, content_type="audio/mpeg")
    except httpx.HTTPStatusError as e:
        ai_log.record(provider="elevenlabs", model="eleven_multilingual_v2", purpose="tts",
                      input_bytes=len(script.encode()), output_bytes=0,
                      success=False, error=f"{e.response.status_code}")
        log.error("ElevenLabs HTTP error %s: %s", e.response.status_code, e.response.text[:300])
        return None
    except Exception as e:
        ai_log.record(provider="elevenlabs", model="eleven_multilingual_v2", purpose="tts",
                      input_bytes=len(script.encode()), output_bytes=0,
                      success=False, error=str(e)[:200])
        log.exception("TTS failure: %s", e)
        return None
