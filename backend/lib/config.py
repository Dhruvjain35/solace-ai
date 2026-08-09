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
        # model_clinical / model_utility intentionally start with "model_";
        # opt out of pydantic's protected-namespace warning for them.
        protected_namespaces=(),
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

    # Model tiers — one place to choose which Claude model each kind of task uses.
    #   model_clinical — clinical reasoning (differential, disposition, workup,
    #     scribe, coding). Should be the strongest model once it is available.
    #   model_utility — structured/boilerplate tasks (follow-up questions, OCR,
    #     redaction labels, letters, discharge text). Cheaper model is fine.
    # Both default to Haiku today because Bedrock Sonnet access is pending the
    # account use-case form. When Sonnet is unlocked, flip clinical with one env
    # var: MODEL_CLINICAL=claude-sonnet-4-5 (no code change, no redeploy of logic).
    model_clinical: str = "claude-haiku-4-5"
    model_utility: str = "claude-haiku-4-5"

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

    # Voice consent basis (CONSTITUTION SEC-004, phone path).
    #   "disclosure" — the caller hears that this is an automated assistant and
    #     that the call is recorded and transcribed, before the first <Record>.
    #     Continuing to speak is the consent. This is how healthcare IVR
    #     normally works and is the default.
    #   "explicit" — the caller must additionally answer yes before anything
    #     they say reaches a transcription or language model.
    # Which one is sufficient is a question for the deploying hospital's counsel
    # and its state's law, not something the code should decide on their behalf.
    voice_consent_mode: Literal["disclosure", "explicit"] = "disclosure"

    # Demo hospital seed
    demo_hospital_id: str = "demo"
    demo_hospital_name: str = "Demo Medical Center"
    demo_clinician_pin: str = "123456"

    # Magic-link auth + transactional email
    #   app_base_url — where the emailed link points (the frontend origin).
    #     Empty falls back to the request's own origin at send time.
    #   email_provider — "ses" (default, production) | "console" (log + echo).
    #     Forced to "console" whenever solace_mode == "local".
    #   email_from — verified SES sender identity. Required for ses provider.
    #   email_dev_echo — when true, the magic link is returned in the API
    #     response body so sandbox/local flows are testable WITHOUT a mailbox.
    #     MUST stay false in production (it would leak login links).
    app_base_url: str = ""
    email_provider: Literal["ses", "console"] = "ses"
    email_from: str = "Solace <no-reply@solace.health>"
    email_dev_echo: bool = False
    magic_link_ttl_seconds: int = 900  # 15-minute single-use login links


@lru_cache(maxsize=1)
def _load() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = _load()


# Environment variables the Lambda runtime sets and a laptop never does. They are
# the only trustworthy answer to "am I actually deployed", which matters because
# SOLACE_MODE defaults to "local" and an unset variable is indistinguishable from
# a developer's machine.
_LAMBDA_MARKERS = ("AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "AWS_LAMBDA_RUNTIME_API")


def is_deployed() -> bool:
    import os  # noqa: PLC0415

    return any(os.environ.get(m) for m in _LAMBDA_MARKERS)


def assert_deployment_is_configured(mode: str) -> None:
    """Refuse to run a deployed process in local mode (CONSTITUTION SEC-001).

    SEC-001 promises that missing secrets crash the app. That promise is made by
    code inside ``if settings.solace_mode == "aws"``, and the mode defaults to
    "local", so a deployment that never sets SOLACE_MODE does not crash. It skips
    hydration, and ``jwt_auth._auth_secret()`` hands it a signing key that is
    committed to this repository. Every clinician JWT it issues is then forgeable
    by anyone who has read the source.

    Pydantic already rejects a misspelled value. The hole is the variable being
    absent, and no amount of documentation closes that. The Lambda runtime tells
    us what the environment variable did not.
    """
    if mode != "aws" and is_deployed():
        raise RuntimeError(
            "Refusing to start: this process is running in AWS Lambda but "
            f"SOLACE_MODE is {mode!r}. In that mode secrets are never hydrated "
            "and clinician JWTs are signed with the dev key committed to this "
            "repo, so every token would be forgeable. Set SOLACE_MODE=aws."
        )


def harden_for_deployment() -> None:
    """Turn off settings that are safe on a laptop and dangerous in production.

    EMAIL_DEV_ECHO returns the magic-link login URL in the API response body so
    local and sandbox flows work without a mailbox. The comment on the setting
    says it MUST stay false in production. It was "true" on the production Lambda
    anyway, and POST /auth/magic/request is unauthenticated, so knowing a
    clinician's email address was enough to be handed their working single-use
    login link and sign in as them.

    A comment saying MUST is not a control. This makes the setting inert wherever
    it would do harm.

    Forced off rather than refusing to boot: the leak closes either way, and
    taking the whole API down over an email flag trades one outage for another.
    Logged at error level so the misconfiguration stays visible instead of being
    silently papered over.
    """
    import logging  # noqa: PLC0415

    log = logging.getLogger(__name__)
    if is_deployed() and settings.email_dev_echo:
        object.__setattr__(settings, "email_dev_echo", False)
        log.error(
            "EMAIL_DEV_ECHO was enabled in a deployed environment and has been "
            "forced off. While it was on, POST /auth/magic/request returned the "
            "clinician's login link in the response body to any unauthenticated "
            "caller. Remove the variable from the function configuration."
        )


def assert_signing_key_present() -> None:
    """Fail at boot if the clinician signing key is missing (SEC-001).

    ``hydrate_from_secrets_manager`` requires exactly one key, DEMO_CLINICIAN_PIN.
    The JWT signing key lives in a separate secret, ``solace/clinician-auth``,
    fetched lazily the first time somebody logs in. A missing or malformed one
    therefore showed up as a 500 for the first clinician of the day rather than as
    a failure to deploy, which is the opposite of what SEC-001 asks for.
    """
    if settings.solace_mode != "aws":
        return
    from lib import jwt_auth  # noqa: PLC0415

    try:
        secret = jwt_auth._auth_secret()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Refusing to start: clinician auth secret could not be read ({e})."
        ) from e
    if not secret.get("JWT_SIGNING_KEY"):
        raise RuntimeError(
            "Refusing to start: solace/clinician-auth has no JWT_SIGNING_KEY. "
            "Clinician tokens cannot be signed."
        )


def hydrate_from_secrets_manager() -> None:
    """In aws mode: pull API keys from Secrets Manager. Fail loudly if it can't.

    No-op in local mode. In aws mode, Secrets Manager is the ONLY source — .env keys
    are intentionally blank, so a fetch failure means the app cannot serve and must crash.
    """
    global settings
    assert_deployment_is_configured(settings.solace_mode)
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
