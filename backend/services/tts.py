"""Text-to-speech — AWS Polly (default) or ElevenLabs.

Switch at runtime via env var `TTS_PROVIDER=aws|elevenlabs`. Default **aws**.

HIPAA: AWS Polly is covered by the AWS BAA. Patient comfort scripts stay
inside AWS's signed-BAA perimeter by default. The ElevenLabs path is retained
for local development only — it requires a separate BAA and MUST NOT be used
in production without one.

Script is intentionally short. The screen carries the full comfort protocol —
the voice just reassures and orients.
"""
from __future__ import annotations

import logging
import os

from db import media
from lib.config import settings

log = logging.getLogger(__name__)

_MAX_SCRIPT_CHARS = 350


def compose_script(patient_explanation: str, comfort_protocol: list[dict], patient_name: str = "") -> str:
    """Short voice script. Full guidance stays on screen."""
    first = (comfort_protocol[0]["title"].rstrip(".") if comfort_protocol else "").strip()
    name_greeting = f"{patient_name.strip()}, " if patient_name else ""

    parts = [
        f"{name_greeting}{patient_explanation.strip()}",
        f"Read the screen for three ways to feel better right now." if not first else
        f"Read the screen for three ways to feel better, starting with: {first}.",
        "We will alert a clinician if anything changes.",
    ]
    script = " ".join(p for p in parts if p).strip()
    if len(script) > _MAX_SCRIPT_CHARS:
        script = script[:_MAX_SCRIPT_CHARS].rsplit(". ", 1)[0] + "."
    return script


def _provider() -> str:
    return os.environ.get("TTS_PROVIDER", "aws").lower()


def generate_and_upload(script: str, language: str, patient_id: str) -> str | None:
    """Generate TTS audio and upload to media storage. Returns URL or None."""
    from lib import ai_log  # noqa: PLC0415

    prov = _provider()
    try:
        if prov == "aws":
            mp3_bytes = _aws_polly_synthesize(script, language)
        else:
            mp3_bytes = _elevenlabs_synthesize(script, language)

        if mp3_bytes is None:
            return None

        model_name = "aws-polly" if prov == "aws" else "eleven_multilingual_v2"
        ai_log.record(
            provider=prov if prov == "aws" else "elevenlabs",
            model=model_name, purpose="tts",
            input_bytes=len(script.encode()),
            output_bytes=len(mp3_bytes), success=True,
        )
        filename = f"{patient_id}.mp3"
        return media.save("audio", filename, mp3_bytes, content_type="audio/mpeg")

    except Exception as e:
        model_name = "aws-polly" if prov == "aws" else "eleven_multilingual_v2"
        ai_log.record(
            provider=prov if prov == "aws" else "elevenlabs",
            model=model_name, purpose="tts",
            input_bytes=len(script.encode()), output_bytes=0,
            success=False, error=str(e)[:200],
        )
        log.exception("TTS failure (%s): %s", prov, e)
        return None


# ---------------------------------------------------------------------------
# AWS Polly — covered by AWS BAA
# ---------------------------------------------------------------------------

# Neural voices by language — Polly's best quality voices for ER patient comfort
_POLLY_VOICE_MAP: dict[str, tuple[str, str]] = {
    # (VoiceId, Engine) — prefer neural/generative where available
    "en": ("Joanna", "neural"),
    "es": ("Lupe", "neural"),
    "fr": ("Lea", "neural"),
    "de": ("Vicki", "neural"),
    "pt": ("Camila", "neural"),
    "it": ("Bianca", "neural"),
    "ja": ("Kazuha", "neural"),
    "ko": ("Seoyeon", "neural"),
    "zh": ("Zhiyu", "neural"),
    "hi": ("Kajal", "neural"),
    "ar": ("Hala", "neural"),
    "nl": ("Laura", "neural"),
    "pl": ("Ola", "neural"),
    "sv": ("Elin", "neural"),
    "da": ("Sofie", "neural"),
    "no": ("Ida", "neural"),
    "fi": ("Suvi", "neural"),
    "tr": ("Burcu", "neural"),
    "ru": ("Tatyana", "standard"),
    "ro": ("Carmen", "standard"),
    "cy": ("Gwyneth", "standard"),
    "vi": ("Joanna", "neural"),      # fallback to English voice
    "ur": ("Joanna", "neural"),      # fallback to English voice
    "tl": ("Joanna", "neural"),      # fallback to English voice
}


def _aws_polly_synthesize(script: str, language: str) -> bytes | None:
    """Synthesize speech via AWS Polly. Returns MP3 bytes."""
    import boto3  # noqa: PLC0415

    polly = boto3.client("polly", region_name=settings.aws_region)

    lang_key = (language or "en").strip().lower()[:2]
    voice_id, engine = _POLLY_VOICE_MAP.get(lang_key, ("Joanna", "neural"))

    try:
        resp = polly.synthesize_speech(
            Text=script,
            OutputFormat="mp3",
            VoiceId=voice_id,
            Engine=engine,
            TextType="text",
        )
        return resp["AudioStream"].read()

    except Exception as e:
        # If neural voice fails, fall back to standard engine
        if engine == "neural":
            log.warning("Polly neural voice %s failed, falling back to standard: %s", voice_id, e)
            try:
                resp = polly.synthesize_speech(
                    Text=script,
                    OutputFormat="mp3",
                    VoiceId=voice_id,
                    Engine="standard",
                    TextType="text",
                )
                return resp["AudioStream"].read()
            except Exception:
                pass
        raise


# ---------------------------------------------------------------------------
# ElevenLabs — local dev / fallback (requires separate BAA for production)
# ---------------------------------------------------------------------------

_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


def _elevenlabs_synthesize(script: str, language: str) -> bytes | None:
    """Fallback: ElevenLabs TTS. For local dev only — requires BAA for production."""
    import httpx  # noqa: PLC0415

    if not settings.elevenlabs_api_key:
        log.warning("ELEVENLABS_API_KEY missing; skipping TTS")
        return None

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
        return resp.content
