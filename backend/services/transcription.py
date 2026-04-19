"""Whisper transcription. Works locally the moment an OPENAI_API_KEY is present."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from openai import OpenAI

from lib.config import settings

log = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Transcription:
    text: str
    language: str  # ISO 639-1


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise TranscriptionError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> Transcription:
    """Send audio bytes to Whisper. Returns transcript + detected language code."""
    from lib import ai_log  # noqa: PLC0415

    try:
        client = _get_client()
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            response_format="verbose_json",
        )
        text = getattr(resp, "text", "").strip()
        language = getattr(resp, "language", None) or "en"
        language = _normalize_language(language)
        if not text:
            ai_log.record(provider="openai", model="whisper-1", purpose="transcription",
                          input_bytes=len(audio_bytes), output_bytes=0,
                          success=False, error="empty_transcript")
            raise TranscriptionError("Whisper returned empty transcript")
        ai_log.record(provider="openai", model="whisper-1", purpose="transcription",
                      input_bytes=len(audio_bytes), output_bytes=len(text.encode()), success=True)
        return Transcription(text=text, language=language)
    except TranscriptionError:
        raise
    except Exception as e:
        ai_log.record(provider="openai", model="whisper-1", purpose="transcription",
                      input_bytes=len(audio_bytes), output_bytes=0,
                      success=False, error=str(e)[:200])
        log.exception("Whisper failure")
        raise TranscriptionError(str(e)) from e


_LANG_MAP = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "portuguese": "pt",
    "italian": "it",
    "vietnamese": "vi",
    "haitian creole": "ht",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "arabic": "ar",
    "hindi": "hi",
    "russian": "ru",
}


def _normalize_language(lang: str) -> str:
    key = lang.lower().strip()
    if key in _LANG_MAP:
        return _LANG_MAP[key]
    # Already an ISO code (e.g. "en")
    if len(key) == 2:
        return key
    return "en"
