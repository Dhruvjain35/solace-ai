"""Claude Vision photo analysis. Returns structured injury observations."""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


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
    """Send bytes to Claude Vision. Returns empty dict on failure or if no image."""
    if not image_bytes:
        return {}
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY missing; skipping photo analysis")
        return {}
    try:
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime_type, "data": encoded},
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
            purpose="vision",
        )
        raw = "".join(block.text for block in resp.content)
        return _parse_json(raw)
    except Exception as e:
        log.exception("Claude Vision failure: %s", e)
        return {}


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    # Strip markdown fences if Claude adds them despite the prompt
    fence = re.search(r"\{[\s\S]*\}", raw)
    if not fence:
        return {}
    try:
        return json.loads(fence.group(0))
    except json.JSONDecodeError:
        log.warning("Vision JSON parse failure (len=%d, content redacted)", len(raw))
        return {}
