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

    # AI providers
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel (warm, clear)

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

    mapping = {
        "OPENAI_API_KEY": "openai_api_key",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "ELEVENLABS_API_KEY": "elevenlabs_api_key",
        "ELEVENLABS_VOICE_ID": "elevenlabs_voice_id",
        "DEMO_CLINICIAN_PIN": "demo_clinician_pin",
    }
    missing = []
    for secret_key, attr in mapping.items():
        value = payload.get(secret_key)
        if not value:
            missing.append(secret_key)
            continue
        object.__setattr__(settings, attr, value)
    if missing:
        raise RuntimeError(
            f"Secrets Manager payload missing required keys: {missing}. "
            f"Re-run scripts/setup_security.py after fixing .env, or rotate the secret."
        )
    log.info("Secrets Manager: hydrated %d field(s)", len(mapping))
