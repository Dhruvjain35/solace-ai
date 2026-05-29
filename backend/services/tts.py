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

import hashlib
import logging
import os
import time
from collections import OrderedDict
from threading import Lock

from db import media
from lib.config import settings

log = logging.getLogger(__name__)

_MAX_SCRIPT_CHARS = 350

# --- In-process LRU audio cache ------------------------------------------------------
#
# Voice flows replay the same short phrases constantly (greetings, "I didn't
# catch that", canned FAQ answers). tts_cache.py already caches MP3s in S3, but
# every call still pays an S3 round-trip. This in-process LRU sits in front of
# that: on a warm Lambda container, a repeated phrase synthesizes zero times and
# hits zero network. Bounded so a long-lived container can't leak memory.

_LRU_MAX_ENTRIES = 64          # ~64 short MP3s — a few MB at most
_LRU_TTL_SECONDS = 3600        # entries older than 1h are re-synthesized
_lru: "OrderedDict[str, tuple[float, bytes]]" = OrderedDict()
_lru_lock = Lock()

# Retry/backoff for transient Polly failures (throttling, brief 5xx).
_TTS_MAX_ATTEMPTS = 3
_TTS_BACKOFF_BASE = 0.25       # seconds: 0.25, 0.5, 1.0


def _cache_key(text: str, language: str, provider: str) -> str:
    return hashlib.sha256(f"{provider}|{language}|{text}".encode()).hexdigest()


def _lru_get(key: str) -> bytes | None:
    with _lru_lock:
        entry = _lru.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.time() - ts > _LRU_TTL_SECONDS:
            del _lru[key]
            return None
        _lru.move_to_end(key)  # mark most-recently-used
        return data


def _lru_put(key: str, data: bytes) -> None:
    if not data:
        return
    with _lru_lock:
        _lru[key] = (time.time(), data)
        _lru.move_to_end(key)
        while len(_lru) > _LRU_MAX_ENTRIES:
            _lru.popitem(last=False)  # evict least-recently-used


def cache_clear() -> None:
    """Drop the in-process audio cache. Useful for tests and warm-container resets."""
    with _lru_lock:
        _lru.clear()


def cache_stats() -> dict:
    """Lightweight visibility into the in-process cache."""
    with _lru_lock:
        return {"entries": len(_lru), "max_entries": _LRU_MAX_ENTRIES}


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
    """Synthesize speech via AWS Polly with retry/backoff. Returns MP3 bytes.

    Each engine (neural -> standard fallback) is retried up to _TTS_MAX_ATTEMPTS
    with exponential backoff so a transient throttle or 5xx doesn't drop audio
    on a live call.
    """
    import boto3  # noqa: PLC0415

    polly = boto3.client("polly", region_name=settings.aws_region)

    lang_key = (language or "en").strip().lower()[:2]
    voice_id, engine = _POLLY_VOICE_MAP.get(lang_key, ("Joanna", "neural"))

    def _attempt(use_engine: str) -> bytes:
        resp = polly.synthesize_speech(
            Text=script,
            OutputFormat="mp3",
            VoiceId=voice_id,
            Engine=use_engine,
            TextType="text",
        )
        return resp["AudioStream"].read()

    # Engines to try in order: requested engine, then standard as a degrade path.
    engines = [engine] if engine == "standard" else [engine, "standard"]
    last_exc: Exception | None = None
    for use_engine in engines:
        for attempt in range(_TTS_MAX_ATTEMPTS):
            try:
                return _attempt(use_engine)
            except Exception as e:  # noqa: BLE001
                last_exc = e
                if attempt < _TTS_MAX_ATTEMPTS - 1:
                    delay = _TTS_BACKOFF_BASE * (2 ** attempt)
                    log.warning(
                        "Polly %s/%s attempt %d failed, retrying in %.2fs: %s",
                        voice_id, use_engine, attempt + 1, delay, e,
                    )
                    time.sleep(delay)
                else:
                    log.warning(
                        "Polly %s/%s exhausted %d attempts: %s",
                        voice_id, use_engine, _TTS_MAX_ATTEMPTS, e,
                    )
    if last_exc:
        raise last_exc
    return None


def synthesize_cached(script: str, language: str = "en") -> bytes | None:
    """Synthesize `script` to MP3 bytes, served from the in-process LRU cache
    when warm. Returns None if every provider/retry path fails — callers in the
    voice flow should then fall back to Twilio's free <Say> verb (see
    `say_fallback_ssml`).
    """
    text = (script or "").strip()
    if not text:
        return None
    prov = _provider()
    key = _cache_key(text, (language or "en")[:2], prov)

    cached = _lru_get(key)
    if cached is not None:
        return cached

    try:
        if prov == "aws":
            mp3_bytes = _aws_polly_synthesize(text, language)
        else:
            mp3_bytes = _elevenlabs_synthesize(text, language)
    except Exception as e:  # noqa: BLE001
        log.warning("synthesize_cached failed (%s): %s", prov, e)
        return None

    if mp3_bytes:
        _lru_put(key, mp3_bytes)
    return mp3_bytes


# Twilio <Say> voices by language — the zero-cost, always-available fallback
# when Polly/ElevenLabs synthesis fails mid-call.
_SAY_VOICE_MAP: dict[str, tuple[str, str]] = {
    "en": ("Polly.Joanna", "en-US"),
    "es": ("Polly.Lupe", "es-US"),
    "fr": ("Polly.Lea", "fr-FR"),
    "de": ("Polly.Vicki", "de-DE"),
    "pt": ("Polly.Camila", "pt-BR"),
    "it": ("Polly.Bianca", "it-IT"),
    "zh": ("Polly.Zhiyu", "cmn-CN"),
    "ja": ("Polly.Kazuha", "ja-JP"),
    "ko": ("Polly.Seoyeon", "ko-KR"),
    "hi": ("Polly.Kajal", "hi-IN"),
    "ar": ("Polly.Hala", "arb"),
}


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
         .replace('"', "&quot;").replace("'", "&apos;")
    )


def say_fallback_ssml(text: str, language: str = "en") -> str:
    """Build a Twilio <Say> verb for `text` — the graceful fallback when audio
    synthesis is unavailable. The voice router uses this so a Polly outage never
    leaves a caller in silence."""
    voice, lang_attr = _SAY_VOICE_MAP.get((language or "en")[:2], ("Polly.Joanna", "en-US"))
    return f'<Say voice="{voice}" language="{lang_attr}">{_xml_escape(text)}</Say>'


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
