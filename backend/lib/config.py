"""Environment-driven config. In AWS mode we re-hydrate from Secrets Manager on cold start."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    solace_mode: Literal["local", "aws"] = "local"

    # AI providers — defaults use AWS services (Bedrock, Transcribe, Polly)
    # which are covered by the AWS BAA. Third-party keys are only needed
    # when overriding to direct providers (local dev only).
    #   CLAUDE_PROVIDER=bedrock (default) | direct
    #   TRANSCRIPTION_PROVIDER=aws (default) | openai
    #   TTS_PROVIDER=aws (default) | elevenlabs
    openai_api_key: str = ""          # only needed if TRANSCRIPTION_PROVIDER=openai
    anthropic_api_key: str = ""       # only needed if CLAUDE_PROVIDER=direct
    elevenlabs_api_key: str = ""      # only needed if TTS_PROVIDER=elevenlabs
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs Rachel (local dev)

    # AWS secret source — when set, overrides .env values on startup
    aws_secret_name: str = "solace/api-keys"

    # AWS
    aws_region: str = "us-east-1"
    dynamodb_table_patients: str = "solace-patients"
    dynamodb_table_hospitals: str = "solace-hospitals"
    dynamodb_table_prescriptions: str = "solace-prescriptions"
    dynamodb_table_notes: str = "solace-notes"
    s3_bucket_media: str = ""

    # Local dev
    local_media_dir: str = str(ROOT / "backend" / "tmp" / "media")
    local_media_base_url: str = "http://localhost:8000/media"

    # Demo hospital seed
    demo_hospital_id: str = "demo"
    demo_hospital_name: str = "Demo Medical Center"
    demo_clinician_pin: str = "123456"


@lru_cache(maxsize=1)
def _load() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = _load()


def hydrate_from_secrets_manager() -> None:
    """In aws mode: pull API keys from Secrets Manager. Fail loudly if it can't.

    No-op in local mode. In aws mode, Secrets Manager is the ONLY source — .env keys
    are intentionally blank, so a fetch failure means the app cannot serve and must crash.
    """
    global settings
    if settings.solace_mode != "aws":
        return

    import json
    import logging

    import boto3

    log = logging.getLogger(__name__)
    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    resp = client.get_secret_value(SecretId=settings.aws_secret_name)
    payload = json.loads(resp["SecretString"])

    # Required keys — always needed regardless of provider
    required_mapping = {
        "DEMO_CLINICIAN_PIN": "demo_clinician_pin",
    }
    # Optional keys — only needed when overriding to third-party providers.
    # In default AWS mode (Bedrock + Transcribe + Polly), none of these are required.
    optional_mapping = {
        "OPENAI_API_KEY": "openai_api_key",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "ELEVENLABS_API_KEY": "elevenlabs_api_key",
        "ELEVENLABS_VOICE_ID": "elevenlabs_voice_id",
    }
    missing = []
    for secret_key, attr in required_mapping.items():
        value = payload.get(secret_key)
        if not value:
            missing.append(secret_key)
            continue
        object.__setattr__(settings, attr, value)
    for secret_key, attr in optional_mapping.items():
        value = payload.get(secret_key)
        if value:
            object.__setattr__(settings, attr, value)
    if missing:
        raise RuntimeError(
            f"Secrets Manager payload missing required keys: {missing}. "
            f"Re-run scripts/setup_security.py after fixing .env, or rotate the secret."
        )
    hydrated = sum(1 for k in {**required_mapping, **optional_mapping} if payload.get(k))
    log.info("Secrets Manager: hydrated %d field(s)", hydrated)
