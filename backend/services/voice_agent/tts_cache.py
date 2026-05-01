"""ElevenLabs TTS, hash-cached in S3.

Voice agent calls reuse the same phrases over and over (greetings, "I didn't
catch that", "anything else?", canned FAQ responses). Hashing on
(text + language + voice) and storing the MP3 in S3 means after the first
generation, repeats cost $0 in ElevenLabs.

Returned URLs are 1h pre-signed (long enough for any single call).
"""
from __future__ import annotations

import hashlib
import logging

from db import media
from lib.config import settings
from services import tts as _tts

log = logging.getLogger(__name__)

KIND = "voice"  # S3 prefix — separate from patient-flow audio


def _key_for(text: str, language: str, voice_id: str) -> str:
    digest = hashlib.sha256(f"{voice_id}|{language}|{text}".encode()).hexdigest()[:32]
    return f"{digest}.mp3"


def get_or_generate(text: str, language: str = "en") -> str | None:
    """Return a public-readable URL for the spoken `text` in `language`.

    Cache layer: same (text, lang, voice) → same S3 key → reused MP3.
    Falls back to None if ElevenLabs is unavailable (caller should use Twilio's
    free <Say> verb in that path).
    """
    if not text.strip():
        return None
    voice_id = settings.elevenlabs_voice_id or "default"
    filename = _key_for(text.strip(), language[:2], voice_id)

    # AWS mode: check S3 first via a HEAD-equivalent (presign + try).
    if settings.solace_mode == "aws":
        if _s3_exists(filename):
            return media.presigned_get(KIND, filename)
    # Local mode: filesystem check.
    else:
        from pathlib import Path
        local_path = Path(settings.local_media_dir) / KIND / filename
        if local_path.exists():
            return media.presigned_get(KIND, filename)

    # Cache miss — generate via ElevenLabs.
    if not settings.elevenlabs_api_key:
        return None
    try:
        import httpx
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        if language and len(language) == 2:
            payload["language_code"] = language[:2]
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            mp3_bytes = resp.content
        return media.save(KIND, filename, mp3_bytes, content_type="audio/mpeg")
    except Exception as e:  # noqa: BLE001
        log.warning("voice_agent.tts_cache: generation failed: %s", e)
        return None


def _s3_exists(filename: str) -> bool:
    try:
        import boto3
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.head_object(Bucket=settings.s3_bucket_media, Key=f"{KIND}/{filename}")
        return True
    except Exception:
        return False


# Re-export so the patient TTS pipeline keeps working untouched.
compose_script = _tts.compose_script
