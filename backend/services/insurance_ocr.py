"""Claude Vision OCR for US health insurance cards."""
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


_PROMPT = """You are reading a US health insurance card photo. Extract the visible fields.

Return JSON ONLY, no preamble, no markdown fence:
{
  "provider": "insurance company name or null",
  "plan_name": "plan name or null",
  "member_id": "member / subscriber ID or null",
  "group_number": "group number or null",
  "name_on_card": "member name as printed or null",
  "bin": "pharmacy BIN or null",
  "pcn": "pharmacy PCN or null",
  "rx_group": "Rx group or null",
  "effective_date": "effective date or null",
  "phone": "member services phone or null"
}

Return null for any field not clearly visible. Do NOT guess.
If this doesn't look like an insurance card, return exactly:
{"error": "not_an_insurance_card"}
"""


def extract(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    if not image_bytes:
        return {"error": "empty_image"}
    if not settings.anthropic_api_key:
        return {"error": "anthropic_key_missing"}
    try:
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=500,
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
            purpose="insurance_ocr",
        )
        raw = "".join(block.text for block in resp.content)
        return _parse_json(raw)
    except Exception as e:
        log.exception("Insurance OCR failure: %s", e)
        return {"error": "ocr_failed"}


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {"error": "parse_failed"}
    try:
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            return {"error": "parse_failed"}
        return parsed
    except json.JSONDecodeError:
        log.warning("Insurance OCR JSON parse failed (len=%d, content redacted)", len(raw))
        return {"error": "parse_failed"}
