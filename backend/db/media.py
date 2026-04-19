"""Media storage. Local mode writes to disk and serves via /media/*.

AWS mode uploads to S3 and returns pre-signed URLs (Phase 1).
"""
from __future__ import annotations

from pathlib import Path

from lib.config import settings


def save(kind: str, filename: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Save a media blob; return a URL the patient/clinician can fetch.

    kind: "audio" | "photos"
    """
    if settings.solace_mode == "aws":
        return _s3_put(kind, filename, data, content_type)
    return _local_put(kind, filename, data)


def presigned_get(kind: str, filename: str) -> str:
    """Regenerate a fetch URL for existing media. Local mode: deterministic URL."""
    if settings.solace_mode == "aws":
        return _s3_presign(kind, filename)
    return f"{settings.local_media_base_url}/{kind}/{filename}"


# ---- Local implementation -----------------------------------------------------------
def _local_put(kind: str, filename: str, data: bytes) -> str:
    base = Path(settings.local_media_dir).resolve() / kind
    base.mkdir(parents=True, exist_ok=True)
    path = base / filename
    path.write_bytes(data)
    return f"{settings.local_media_base_url}/{kind}/{filename}"


# ---- S3 implementation --------------------------------------------------------------
# The media bucket uses CMK (SSE-KMS) encryption, and S3 REQUIRES SigV4 for any
# request against KMS-encrypted objects. boto3's default signer on `s3` clients
# can fall back to SigV2 in some regions/configurations — without this explicit
# Config, presigned GETs come back as 400 "requires SigV4". Passing the config
# to both put_object and generate_presigned_url keeps the two paths consistent.
def _s3_client():  # pragma: no cover
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
    )


def _s3_put(kind: str, filename: str, data: bytes, content_type: str) -> str:  # pragma: no cover
    s3 = _s3_client()
    key = f"{kind}/{filename}"
    s3.put_object(Bucket=settings.s3_bucket_media, Key=key, Body=data, ContentType=content_type)
    return _s3_presign(kind, filename)


def _s3_presign(kind: str, filename: str, expiry_seconds: int = 900) -> str:  # pragma: no cover
    s3 = _s3_client()
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_media, "Key": f"{kind}/{filename}"},
        ExpiresIn=expiry_seconds,
    )
