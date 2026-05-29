"""Shared Claude Vision layer for Solace.

Three building blocks used by injury-photo analysis, insurance-card OCR, and
ID OCR:

  * `vision_extract()`      — single deterministic (temperature=0) vision call
                              that NEVER raises; returns a dict.
  * `vision_extract_many()` — run several `vision_extract` calls in parallel.
  * `image_quality_gate()`  — a cheap, no-AI blur/glare/size heuristic so the
                              UI can ask for a re-scan before spending an AI
                              call on an unreadable photo.

Plus `parse_json_object()`, a brace-aware JSON extractor tolerant of markdown
fences and trailing prose.

All functions degrade gracefully when Pillow is absent (the quality gate just
returns "ok" so nothing is blocked) and never log PHI — only sizes, lengths,
and boolean verdicts reach the logger.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = settings.model_utility

# Pillow is optional — the quality gate is the only consumer and degrades to a
# pass-through verdict when it is missing.
try:  # pragma: no cover - import guard
    from PIL import Image, ImageFilter, ImageStat  # type: ignore

    _PIL_OK = True
except Exception:  # noqa: BLE001
    _PIL_OK = False


# --- JSON parsing --------------------------------------------------------------


def parse_json_object(raw: str) -> dict[str, Any] | None:
    """Extract the first complete JSON object from a model response.

    Brace-aware: walks the string counting `{`/`}` (respecting string literals
    and escapes) so trailing prose or a second object after the first does not
    break parsing. Tolerates markdown ```json fences. Returns None when no
    valid object is found — callers decide what error shape to surface.
    """
    if not raw:
        return None
    text = raw.strip()
    # Drop a leading ```json / ``` fence if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


# --- single + parallel vision calls -------------------------------------------


def vision_extract(
    image_bytes: bytes,
    *,
    prompt: str,
    system: str = "",
    mime_type: str = "image/jpeg",
    purpose: str = "vision",
    max_tokens: int = 600,
) -> dict[str, Any]:
    """Run one Claude Vision call and return a parsed JSON dict.

    Deterministic (temperature=0) so the same card photographed twice yields the
    same fields. NEVER raises — every failure path returns a dict with an
    `_error` key so callers can branch without a try/except:

      {"_error": "empty_image"}        — no bytes supplied
      {"_error": "vision_unavailable"} — no Anthropic key configured
      {"_error": "vision_failed"}      — the provider call raised
      {"_error": "parse_failed"}       — response was not valid JSON

    On success the returned dict is whatever the model produced (no `_error`).
    """
    if not image_bytes:
        return {"_error": "empty_image"}
    if not claude.available():
        log.warning("vision_extract: no Anthropic key; purpose=%s skipped", purpose)
        return {"_error": "vision_unavailable"}
    try:
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=max_tokens,
            system=system,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            purpose=purpose,
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
    except Exception as e:  # noqa: BLE001
        log.exception("vision_extract failed (purpose=%s): %s", purpose, e)
        return {"_error": "vision_failed"}

    parsed = parse_json_object(raw)
    if parsed is None:
        log.warning(
            "vision_extract parse failed (purpose=%s, raw_len=%d, content redacted)",
            purpose,
            len(raw),
        )
        return {"_error": "parse_failed"}
    return parsed


def vision_extract_many(
    jobs: list[dict[str, Any]],
    *,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    """Run several `vision_extract` calls concurrently.

    Each job is a kwargs dict for `vision_extract` (must include `image_bytes`
    and `prompt`). Results come back in the same order as `jobs`. Because
    `vision_extract` never raises, a failure in one job never poisons the batch.
    """
    if not jobs:
        return []
    results: list[dict[str, Any]] = [{} for _ in jobs]
    workers = max(1, min(max_workers, len(jobs)))

    def _run(idx: int, job: dict[str, Any]) -> None:
        kwargs = dict(job)
        image = kwargs.pop("image_bytes", b"")
        results[idx] = vision_extract(image, **kwargs)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run, i, job) for i, job in enumerate(jobs)]
        for f in futures:
            f.result()  # _run swallows errors; this just joins
    return results


# --- no-AI image quality gate --------------------------------------------------

# Heuristic thresholds tuned for phone-camera document photos. They are
# intentionally lenient — the gate exists to catch obviously unusable photos
# (a thumb over the lens, a 3 KB pixel, a washed-out flash glare), not to be a
# strict quality scorer. Borderline photos pass and let the AI try.
_MIN_BYTES = 6_000          # smaller than this is almost certainly not a card
_MIN_DIMENSION = 320        # px on the short edge — below this OCR is hopeless
_BLUR_VARIANCE_FLOOR = 90.0  # Laplacian-style edge variance; lower => blurry
_GLARE_BRIGHT_FRACTION = 0.32  # >32% near-white pixels => likely flash glare
_DARK_MEAN_FLOOR = 38.0     # mean luma below this => underexposed / too dark


def image_quality_gate(image_bytes: bytes) -> dict[str, Any]:
    """Cheap, no-AI verdict on whether a photo is worth an OCR call.

    Returns:
      {
        "ok": bool,                  # True => safe to send to vision_extract
        "reason": str,               # machine code, "" when ok
        "message": str,              # patient-facing guidance, "" when ok
        "checks": {blur,glare,dark,size,decoded}  # per-check booleans (True=passed)
        "metrics": {...}             # raw numbers, for debugging only — no PHI
      }

    When Pillow is unavailable the gate degrades to a size-only check so a
    missing dependency never blocks a scan.
    """
    checks = {"size": True, "decoded": True, "blur": True, "glare": True, "dark": True}
    metrics: dict[str, Any] = {}

    if not image_bytes:
        return _gate_fail("empty_image", "No image received. Please take a photo.", checks, metrics, "size")

    metrics["bytes"] = len(image_bytes)
    if len(image_bytes) < _MIN_BYTES:
        checks["size"] = False
        return _gate_fail(
            "image_too_small",
            "That photo looks too small or didn't upload fully. Please retake it.",
            checks,
            metrics,
            "size",
        )

    if not _PIL_OK:
        # No Pillow — we cannot inspect pixels. Pass on size alone.
        log.debug("image_quality_gate: Pillow unavailable, size-only verdict")
        return {"ok": True, "reason": "", "message": "", "checks": checks, "metrics": metrics}

    try:
        import io  # noqa: PLC0415

        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception as e:  # noqa: BLE001
        log.warning("image_quality_gate: decode failed (%s)", type(e).__name__)
        checks["decoded"] = False
        return _gate_fail(
            "image_unreadable",
            "We couldn't open that image. Please retake the photo.",
            checks,
            metrics,
            "decoded",
        )

    width, height = img.size
    metrics["width"], metrics["height"] = width, height
    if min(width, height) < _MIN_DIMENSION:
        checks["size"] = False
        return _gate_fail(
            "image_low_resolution",
            "That photo is too low-resolution to read. Move closer and retake it.",
            checks,
            metrics,
            "size",
        )

    gray = img.convert("L")

    # Brightness / darkness.
    stat = ImageStat.Stat(gray)
    mean_luma = stat.mean[0]
    metrics["mean_luma"] = round(mean_luma, 1)
    if mean_luma < _DARK_MEAN_FLOOR:
        checks["dark"] = False
        return _gate_fail(
            "image_too_dark",
            "That photo is too dark to read. Find better lighting and retake it.",
            checks,
            metrics,
            "dark",
        )

    # Glare: fraction of near-white pixels. A flash hotspot washes out text.
    histogram = gray.histogram()
    total_px = max(1, sum(histogram))
    bright_px = sum(histogram[235:])
    bright_fraction = bright_px / total_px
    metrics["bright_fraction"] = round(bright_fraction, 3)
    if bright_fraction > _GLARE_BRIGHT_FRACTION:
        checks["glare"] = False
        return _gate_fail(
            "image_glare",
            "There's too much glare on the card. Tilt it away from the light and retake.",
            checks,
            metrics,
            "glare",
        )

    # Blur: variance of an edge-detected (high-pass) image. Sharp photos have
    # strong edges => high variance; blurry photos => low variance.
    try:
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_var = ImageStat.Stat(edges).var[0]
        metrics["edge_variance"] = round(edge_var, 1)
        if edge_var < _BLUR_VARIANCE_FLOOR:
            checks["blur"] = False
            return _gate_fail(
                "image_blurry",
                "That photo looks blurry. Hold steady and retake it.",
                checks,
                metrics,
                "blur",
            )
    except Exception as e:  # noqa: BLE001
        # Blur detection is best-effort — never block a scan on a filter error.
        log.debug("image_quality_gate: blur check skipped (%s)", type(e).__name__)

    return {"ok": True, "reason": "", "message": "", "checks": checks, "metrics": metrics}


def _gate_fail(
    reason: str,
    message: str,
    checks: dict[str, bool],
    metrics: dict[str, Any],
    failed: str,
) -> dict[str, Any]:
    checks[failed] = False
    return {"ok": False, "reason": reason, "message": message, "checks": checks, "metrics": metrics}


# --- injury photo analysis (existing public API) ------------------------------


_PROMPT = """Analyze this ER patient injury photo.

Return JSON ONLY, no preamble or markdown fence, in this exact shape:
{
  "description": "one sentence on what's visible",
  "severity_indicators": ["short phrase", "short phrase"],
  "triage_observations": ["short clinical observation", "short clinical observation"]
}

If the photo does not show an injury or condition (e.g. a blurry shot, a face, a room), return:
{"description": "no visible injury or medically relevant finding", "severity_indicators": [], "triage_observations": []}
"""


def analyze_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Send bytes to Claude Vision. Returns empty dict on failure or if no image.

    Contract preserved for routers/intake.py: on any failure (no image, no key,
    provider error, parse error) this returns `{}` — callers treat an empty
    dict as "no photo analysis available".
    """
    if not image_bytes:
        return {}
    result = vision_extract(
        image_bytes,
        prompt=_PROMPT,
        mime_type=mime_type,
        purpose="vision",
        max_tokens=400,
    )
    if result.get("_error"):
        return {}
    return result


def _parse_json(raw: str) -> dict[str, Any]:
    """Back-compat shim — retained in case anything imported it directly."""
    return parse_json_object(raw) or {}
