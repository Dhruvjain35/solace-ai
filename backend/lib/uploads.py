"""Server-side file validation — size + magic-byte + full decode + sanitize.

Three-layer defense:
  1. Size cap (fast reject)
  2. Magic-byte sniff (catches obvious lies about content-type)
  3. FULL DECODE — Pillow for images (also strips EXIF to clean bytes),
     ffprobe for audio (catches polyglots, truncated/malformed files
     that pass magic check but crash downstream parsers).

Returns the CLEANED bytes for images (EXIF-stripped JPEG). For audio, returns
the original bytes after confirming it decodes as audio.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from io import BytesIO
from typing import Final

from fastapi import HTTPException, UploadFile

from lib import audit as _audit

log = logging.getLogger(__name__)

MAX_AUDIO_BYTES: Final = 8 * 1024 * 1024
MAX_IMAGE_BYTES: Final = 4 * 1024 * 1024

_AUDIO_SIGS = [
    (b"\x1aE\xdf\xa3", 0, "audio/webm"),
    (b"OggS", 0, "audio/ogg"),
    (b"RIFF", 0, "audio/wav"),
    (b"ID3", 0, "audio/mpeg"),
    (b"\xff\xfb", 0, "audio/mpeg"),
    (b"\xff\xf3", 0, "audio/mpeg"),
    (b"\xff\xf2", 0, "audio/mpeg"),
    (b"ftypM4A", 4, "audio/mp4"),
    (b"ftypmp4", 4, "audio/mp4"),
    (b"ftypisom", 4, "audio/mp4"),
]
_IMAGE_SIGS = [
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"RIFF", 0, "image/webp"),
    # HEIC + AVIF intentionally absent — their decoders have an active CVE surface.
    # Client code resizes/re-encodes iPhone HEIC to JPEG via <canvas> before upload.
]


def _match(head: bytes, sigs) -> str | None:
    for prefix, offset, label in sigs:
        end = offset + len(prefix)
        if len(head) < end:
            continue
        if head[offset:end] == prefix:
            if label == "image/webp" and len(head) >= 12 and head[8:12] != b"WEBP":
                continue
            if label == "audio/wav" and len(head) >= 12 and head[8:12] != b"WAVE":
                continue
            return label
    return None


# Decompression-bomb guard — refuse any image whose pixel count would OOM us
# during decode. 4096² = 16M pixels ≈ 48 MB RGB uncompressed, safe under our
# 2 GB Lambda memory. Pillow's default is 89M which is too generous.
MAX_IMAGE_PIXELS = 4096 * 4096

# HEIC/AVIF decoders have an active CVE surface (libheif, libavif). We strip
# both from the accepted list — modern browsers auto-convert via our client-side
# canvas resize, and iPhone HEIC becomes JPEG when re-encoded through that path.
_REJECTED_IMAGE_FORMATS: set[str] = {"image/heic", "image/avif"}


def _sanitize_image(raw: bytes) -> bytes:
    """Full PIL decode + EXIF strip + re-encode as JPEG.

    Raises ValueError on:
      - any decode/open failure
      - decompression-bomb (pixel count > MAX_IMAGE_PIXELS)
      - HEIC / AVIF input (CVE-prone decoders)
    """
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

    # Make PIL raise instead of silently log past the default cap
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

    try:
        probe = Image.open(BytesIO(raw))
        fmt = (probe.format or "").lower()
        if fmt in {"heif", "avif"}:
            raise ValueError(f"format {fmt} not accepted (CVE-prone decoder surface)")
        # Dimension gate — before verify()/load() allocates the raster
        w, h = probe.size
        if w * h > MAX_IMAGE_PIXELS or w > 8192 or h > 8192:
            raise ValueError(
                f"image {w}x{h} = {w*h:,} px exceeds cap {MAX_IMAGE_PIXELS:,} (decompression bomb?)"
            )
        probe.verify()  # invalidates `probe`, so re-open for the real decode
        img = Image.open(BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise ValueError(f"image decode failed: {type(e).__name__}: {e}") from e
    except Image.DecompressionBombError as e:
        raise ValueError(f"decompression bomb: {e}") from e

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True, exif=b"")
    return out.getvalue()


def _ffprobe_path() -> str:
    """Resolve an ffprobe binary. imageio-ffmpeg ships a static ffmpeg (with ffprobe)."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe  # noqa: PLC0415

        ffmpeg = get_ffmpeg_exe()
        # imageio-ffmpeg's static binary is "ffmpeg"; derive ffprobe sibling, else use
        # ffmpeg itself to probe via -f null output (works for validation purposes).
        return ffmpeg
    except Exception:
        return "ffmpeg"  # rely on PATH (fallback for local dev on Mac with brew)


def _validate_audio(raw: bytes) -> float:
    """Actually decode the audio through ffmpeg; return duration in seconds.

    Uses `ffmpeg -i <file> -f null -` which decodes every frame but writes nothing.
    If the file has no audio stream or is malformed, ffmpeg exits non-zero.
    Returns the parsed duration so callers can enforce cost-based quotas.
    """
    import re as _re

    binary = _ffprobe_path()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=True) as f:
        f.write(raw)
        f.flush()
        try:
            r = subprocess.run(
                [binary, "-hide_banner", "-nostats", "-xerror",
                 "-i", f.name, "-vn", "-f", "null", "-"],
                capture_output=True, timeout=20,
            )
        except FileNotFoundError as e:
            raise RuntimeError("ffmpeg binary not available") from e
        except subprocess.TimeoutExpired as e:
            raise ValueError("audio decode exceeded 20s") from e

    stderr = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0:
        raise ValueError(f"audio decode failed: {stderr[:500]}")

    # ffmpeg writes duration to stderr like: "Duration: 00:00:07.42, ..."
    # or the last time marker in the null-output: "time=00:00:07.42"
    duration = 0.0
    m = _re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if m:
        h, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
        duration = h * 3600 + mm * 60 + ss
    else:
        # Fallback: final "time=HH:MM:SS.xx" line from the null output
        times = _re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        if times:
            h, mm, ss = int(times[-1][0]), int(times[-1][1]), float(times[-1][2])
            duration = h * 3600 + mm * 60 + ss

    if duration <= 0:
        # Decoded OK but couldn't parse duration — accept with 0, callers can decide
        log.warning("audio decoded but duration unparseable; stderr tail: %s", stderr[-200:])

    return duration


async def read_and_validate(
    upload: UploadFile,
    kind: str,
    *,
    source_ip: str | None = None,
) -> bytes:
    """Read, size-check, magic-sniff, AND fully decode the upload.

    Returns CLEANED bytes — for images, an EXIF-stripped JPEG re-encoding; for audio,
    the original bytes after a successful ffmpeg decode pass.

    Raises 413 (oversize), 415 (bad magic), 422 (decode failure). All rejections
    are recorded in the audit log.
    """
    if kind == "audio":
        max_bytes, sigs = MAX_AUDIO_BYTES, _AUDIO_SIGS
    elif kind == "image":
        max_bytes, sigs = MAX_IMAGE_BYTES, _IMAGE_SIGS
    else:
        raise ValueError(f"unknown kind: {kind}")

    raw = await upload.read()
    size = len(raw)

    if size == 0:
        raise HTTPException(status_code=400, detail=f"empty {kind} upload")

    if size > max_bytes:
        _audit.record(
            clinician_id=None, clinician_name=None, action=f"abuse.{kind}_oversize",
            source_ip=source_ip, status_code=413,
            extra={"size_bytes": size, "cap_bytes": max_bytes, "filename": upload.filename},
        )
        raise HTTPException(
            status_code=413,
            detail=f"{kind} upload is {size // 1024}KB, exceeds {max_bytes // 1024}KB cap",
        )

    sniffed = _match(raw[:12], sigs)
    if sniffed is None:
        _audit.record(
            clinician_id=None, clinician_name=None, action=f"abuse.{kind}_bad_magic",
            source_ip=source_ip, status_code=415,
            extra={
                "declared_type": upload.content_type,
                "filename": upload.filename,
                "size_bytes": size,
                "first_bytes_hex": raw[:12].hex(),
            },
        )
        raise HTTPException(
            status_code=415,
            detail=f"file does not match any supported {kind} format",
        )

    # Layer 3: full decode. Catches polyglots, truncated files, metadata injection.
    try:
        if kind == "image":
            cleaned = _sanitize_image(raw)
            log.info("image sanitized: %d→%d bytes (EXIF stripped)", size, len(cleaned))
            return cleaned
        else:
            duration = _validate_audio(raw)
            # Stash the measured duration on the UploadFile so callers can enforce
            # cost-based quotas without re-running ffmpeg.
            upload.duration_seconds = duration  # type: ignore[attr-defined]
            return raw
    except ValueError as e:
        _audit.record(
            clinician_id=None, clinician_name=None, action=f"abuse.{kind}_decode_failed",
            source_ip=source_ip, status_code=422,
            extra={
                "declared_type": upload.content_type,
                "sniffed_type": sniffed,
                "error": str(e)[:300],
                "size_bytes": size,
            },
        )
        raise HTTPException(status_code=422, detail=f"{kind} file could not be decoded")
    except RuntimeError as e:
        log.exception("decoder unavailable for %s: %s", kind, e)
        # Don't fail closed on infrastructure issues — degrade to magic-byte-only
        # but record the event so we notice in metrics.
        _audit.record(
            clinician_id=None, clinician_name=None, action=f"abuse.{kind}_decoder_down",
            source_ip=source_ip, status_code=200,
            extra={"error": str(e)[:200]},
        )
        return raw
