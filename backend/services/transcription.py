"""Speech-to-text transcription — AWS Transcribe (default) or OpenAI Whisper.

Switch at runtime via env var `TRANSCRIPTION_PROVIDER=aws|openai`. Default **aws**.

HIPAA: AWS Transcribe is covered by the AWS BAA. Patient audio stays inside
AWS's signed-BAA perimeter by default. The OpenAI Whisper path is retained for
local development only — it requires a separate BAA with OpenAI and MUST NOT
be used in production without one.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass

from lib.config import settings

log = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Transcription:
    text: str
    language: str  # ISO 639-1


def _provider() -> str:
    return os.environ.get("TRANSCRIPTION_PROVIDER", "aws").lower()


# ---------------------------------------------------------------------------
# Public API — unchanged interface for all callers
# ---------------------------------------------------------------------------

def transcribe(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    language_hint: str | None = None,
) -> Transcription:
    """Send audio bytes for transcription. Returns transcript + detected language code.

    `language_hint`: ISO-639-1 code (e.g. "ur", "it"). When provided, forces
    decoding in that language — auto-detect on short clips can misclassify.
    """
    from lib import ai_log  # noqa: PLC0415

    prov = _provider()
    try:
        if prov == "aws":
            result = _aws_transcribe(audio_bytes, filename, language_hint)
        else:
            result = _openai_transcribe(audio_bytes, filename, language_hint)
    except TranscriptionError:
        raise
    except Exception as e:
        ai_log.record(
            provider=prov, model="aws-transcribe" if prov == "aws" else "whisper-1",
            purpose="transcription",
            input_bytes=len(audio_bytes), output_bytes=0,
            success=False, error=str(e)[:200],
        )
        log.exception("Transcription failure (%s)", prov)
        raise TranscriptionError(str(e)) from e

    if not result.text:
        ai_log.record(
            provider=prov, model="aws-transcribe" if prov == "aws" else "whisper-1",
            purpose="transcription",
            input_bytes=len(audio_bytes), output_bytes=0,
            success=False, error="empty_transcript",
        )
        raise TranscriptionError("Transcription returned empty transcript")

    ai_log.record(
        provider=prov, model="aws-transcribe" if prov == "aws" else "whisper-1",
        purpose="transcription",
        input_bytes=len(audio_bytes), output_bytes=len(result.text.encode()),
        success=True,
    )
    return result


# ---------------------------------------------------------------------------
# AWS Transcribe — covered by AWS BAA
# ---------------------------------------------------------------------------

_AWS_TRANSCRIBE_LANG_MAP: dict[str, str] = {
    "en": "en-US", "es": "es-US", "fr": "fr-FR", "de": "de-DE",
    "pt": "pt-BR", "it": "it-IT", "vi": "vi-VN", "zh": "zh-CN",
    "ja": "ja-JP", "ko": "ko-KR", "ar": "ar-SA", "hi": "hi-IN",
    "ru": "ru-RU", "nl": "nl-NL", "pl": "pl-PL", "sv": "sv-SE",
    "da": "da-DK", "fi": "fi-FI", "he": "he-IL", "id": "id-ID",
    "ms": "ms-MY", "th": "th-TH", "tr": "tr-TR", "uk": "uk-UA",
    "ur": "ur-PK", "bn": "bn-IN", "ta": "ta-IN", "te": "te-IN",
    "mr": "mr-IN", "kn": "kn-IN", "ml": "ml-IN", "gu": "gu-IN",
    "af": "af-ZA", "cy": "cy-GB", "hr": "hr-HR", "bg": "bg-BG",
    "cs": "cs-CZ", "el": "el-GR", "hu": "hu-HU", "ro": "ro-RO",
    "sk": "sk-SK", "sl": "sl-SI", "sr": "sr-RS", "sw": "sw-KE",
    "tl": "tl-PH", "ca": "ca-ES", "gl": "gl-ES", "eu": "eu-ES",
    "fa": "fa-IR", "no": "no-NO", "et": "et-EE", "lv": "lv-LV",
    "lt": "lt-LT",
}

# Map file extensions to MediaFormat values accepted by AWS Transcribe
_MEDIA_FORMAT_MAP: dict[str, str] = {
    "webm": "webm", "mp3": "mp3", "mp4": "mp4", "m4a": "mp4",
    "wav": "wav", "flac": "flac", "ogg": "ogg", "amr": "amr",
}


def _aws_transcribe(
    audio_bytes: bytes,
    filename: str,
    language_hint: str | None,
) -> Transcription:
    """Transcribe via AWS Transcribe streaming or batch (S3 round-trip).

    Uses batch mode (upload to S3 -> start job -> poll) because streaming
    requires websocket and adds complexity. Batch jobs complete in 5-15s for
    typical ER intake clips (<5 min audio).
    """
    import boto3  # noqa: PLC0415

    region = settings.aws_region
    bucket = settings.s3_bucket_media
    if not bucket:
        raise TranscriptionError(
            "S3_BUCKET_MEDIA not set — required for AWS Transcribe. "
            "Set TRANSCRIPTION_PROVIDER=openai for local dev without S3."
        )

    s3 = boto3.client("s3", region_name=region)
    transcribe_client = boto3.client("transcribe", region_name=region)

    # Determine media format from filename extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    media_format = _MEDIA_FORMAT_MAP.get(ext, "webm")

    # Upload audio to S3 (temporary prefix, auto-cleaned by lifecycle rule)
    job_name = f"solace-{uuid.uuid4().hex[:16]}"
    s3_key = f"transcribe-tmp/{job_name}.{ext}"
    s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=audio_bytes,
        ContentType=f"audio/{media_format}",
        ServerSideEncryption="aws:kms",
    )

    try:
        # Build transcription job config
        job_config: dict = {
            "TranscriptionJobName": job_name,
            "Media": {"MediaFileUri": f"s3://{bucket}/{s3_key}"},
            "MediaFormat": media_format,
            "OutputBucketName": bucket,
            "OutputKey": f"transcribe-tmp/{job_name}-output.json",
            "Settings": {"ShowSpeakerLabels": False},
        }

        # Language: use hint if provided, otherwise auto-detect
        normalized_hint = (language_hint or "").strip().lower()[:2] or None
        if normalized_hint and normalized_hint in _AWS_TRANSCRIBE_LANG_MAP:
            job_config["LanguageCode"] = _AWS_TRANSCRIBE_LANG_MAP[normalized_hint]
        else:
            # Auto-detect from common ER languages
            job_config["IdentifyLanguage"] = True
            job_config["LanguageOptions"] = ",".join([
                "en-US", "es-US", "fr-FR", "zh-CN", "vi-VN", "ar-SA",
                "hi-IN", "ko-KR", "pt-BR", "ur-PK", "tl-PH", "de-DE",
            ])

        transcribe_client.start_transcription_job(**job_config)

        # Poll for completion (typical: 5-15s for <5 min audio)
        for _ in range(60):  # max 60s
            time.sleep(1)
            status = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )
            job_status = status["TranscriptionJob"]["TranscriptionJobStatus"]
            if job_status == "COMPLETED":
                break
            if job_status == "FAILED":
                reason = status["TranscriptionJob"].get("FailureReason", "unknown")
                raise TranscriptionError(f"AWS Transcribe job failed: {reason}")
        else:
            raise TranscriptionError("AWS Transcribe job timed out after 60s")

        # Read result from S3
        output_key = f"transcribe-tmp/{job_name}-output.json"
        result_obj = s3.get_object(Bucket=bucket, Key=output_key)
        result_data = json.loads(result_obj["Body"].read())

        transcript_text = (
            result_data.get("results", {})
            .get("transcripts", [{}])[0]
            .get("transcript", "")
            .strip()
        )

        # Detected language
        detected_lang = "en"
        if normalized_hint:
            detected_lang = normalized_hint
        elif "LanguageCode" in status.get("TranscriptionJob", {}):
            lc = status["TranscriptionJob"]["LanguageCode"]  # e.g. "en-US"
            detected_lang = lc.split("-")[0]
        detected_lang = _normalize_language(detected_lang)

        return Transcription(text=transcript_text, language=detected_lang)

    finally:
        # Clean up temporary S3 objects
        for key in [s3_key, f"transcribe-tmp/{job_name}-output.json"]:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass  # best-effort cleanup


# ---------------------------------------------------------------------------
# OpenAI Whisper — local dev / fallback (requires separate BAA for production)
# ---------------------------------------------------------------------------

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI  # noqa: PLC0415
        if not settings.openai_api_key:
            raise TranscriptionError("OPENAI_API_KEY is not set")
        _openai_client = OpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _openai_transcribe(
    audio_bytes: bytes,
    filename: str,
    language_hint: str | None,
) -> Transcription:
    """Fallback: OpenAI Whisper. For local dev only — requires BAA for production."""
    client = _get_openai_client()
    buf = io.BytesIO(audio_bytes)
    buf.name = filename
    kwargs: dict = {
        "model": "whisper-1",
        "file": buf,
        "response_format": "verbose_json",
    }
    normalized_hint = (language_hint or "").strip().lower()[:2] or None
    if normalized_hint and normalized_hint in _WHISPER_LANG_CODES:
        kwargs["language"] = normalized_hint
    resp = client.audio.transcriptions.create(**kwargs)
    text = getattr(resp, "text", "").strip()
    language = getattr(resp, "language", None) or normalized_hint or "en"
    language = _normalize_language(language)
    return Transcription(text=text, language=language)


# Whisper ISO-639-1 codes
_WHISPER_LANG_CODES: set[str] = {
    "af", "ar", "az", "be", "bg", "bn", "bs", "ca", "cs", "cy", "da", "de", "el",
    "en", "es", "et", "fa", "fi", "fr", "gl", "he", "hi", "hr", "hu", "hy", "id",
    "is", "it", "ja", "kk", "kn", "ko", "lt", "lv", "mi", "mk", "mr", "ms", "ne",
    "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sr", "sv", "sw", "ta", "th",
    "tl", "tr", "uk", "ur", "vi", "zh",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_LANG_MAP = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "portuguese": "pt", "italian": "it", "vietnamese": "vi",
    "haitian creole": "ht", "chinese": "zh", "japanese": "ja",
    "korean": "ko", "arabic": "ar", "hindi": "hi", "russian": "ru",
}


def _normalize_language(lang: str) -> str:
    key = lang.lower().strip()
    if key in _LANG_MAP:
        return _LANG_MAP[key]
    if len(key) == 2:
        return key
    return "en"
