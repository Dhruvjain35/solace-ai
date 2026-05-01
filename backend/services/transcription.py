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


def transcribe(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    language_hint: str | None = None,
) -> Transcription:
    """Send audio bytes to Whisper. Returns transcript + detected language code.

    `language_hint`: ISO-639-1 code (e.g. "ur", "it"). When provided, we pass it
    to Whisper as `language=` to force decoding in that language — auto-detect on
    short clips can misclassify (e.g. Urdu mistaken for Hindi or Arabic), and
    pinning the language gives correct transcription every time the patient
    selected one explicitly on the language gate.
    """
    from lib import ai_log  # noqa: PLC0415

    try:
        client = _get_client()
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        kwargs: dict = {
            "model": "whisper-1",
            "file": buf,
            "response_format": "verbose_json",
        }
        normalized_hint = (language_hint or "").strip().lower()[:2] or None
        if normalized_hint and normalized_hint in _SUPPORTED_LANG_CODES:
            kwargs["language"] = normalized_hint
        resp = client.audio.transcriptions.create(**kwargs)
        text = getattr(resp, "text", "").strip()
        language = getattr(resp, "language", None) or normalized_hint or "en"
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


# Whisper "whisper-1" supports these ISO-639-1 codes (per OpenAI's docs).
# Anything outside this set we leave to auto-detect rather than risk a 400.
_SUPPORTED_LANG_CODES: set[str] = {
    "af", "ar", "az", "be", "bg", "bn", "bs", "ca", "cs", "cy", "da", "de", "el",
    "en", "es", "et", "fa", "fi", "fr", "gl", "he", "hi", "hr", "hu", "hy", "id",
    "is", "it", "ja", "kk", "kn", "ko", "lt", "lv", "mi", "mk", "mr", "ms", "ne",
    "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sr", "sv", "sw", "ta", "th",
    "tl", "tr", "uk", "ur", "vi", "zh",
}


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
