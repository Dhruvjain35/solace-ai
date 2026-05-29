"""Unified Claude client — direct Anthropic API or AWS Bedrock.

Switch at runtime via env var `CLAUDE_PROVIDER=direct|bedrock`. Default **bedrock**.

HIPAA: AWS Bedrock is covered by the AWS BAA. All patient transcripts, insurance
cards, and scribe calls stay inside AWS's signed-BAA perimeter by default. The
direct Anthropic path is retained for local development only — it requires a
separate BAA with Anthropic (enterprise tier) and MUST NOT be used in production
without one.

Both paths auto-log to `lib.ai_log` so the patient record captures which
provider saw which bytes.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from lib import ai_log

log = logging.getLogger(__name__)

# Model-name normalization. Keep our code naming consistent while AWS Bedrock
# uses its own model IDs.
#
# Claude 4+ models on Bedrock require cross-region inference profiles (the
# `us.` prefix). Direct model invocation against the bare ID returns
# `ValidationException: The provided model identifier is invalid`. The Sonnet
# 4.5 weights are dated 2025-09-29, not 2025-10-01 — the previous map had the
# wrong date stamp and broke scribe, ambient scribe, differential, comfort
# protocol, and every other Claude call in production.
_BEDROCK_MODEL_MAP = {
    "claude-sonnet-4-5": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5-20250929": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5-20251001": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # legacy alias
    "claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-5": "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
}


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"
    text: str = ""  # kept so consumers can iterate `.text` uniformly without crashing


@dataclass
class Response:
    content: list  # list[TextBlock | ToolUseBlock]


def provider() -> str:
    return os.environ.get("CLAUDE_PROVIDER", "bedrock").lower()


def available() -> bool:
    """True when a Claude backend is actually callable.

    Bedrock (the default, BAA-covered path) authenticates with the Lambda IAM
    role and needs NO API key — so it is always considered available. Only the
    direct Anthropic path requires ``anthropic_api_key``.

    Services use this instead of checking ``settings.anthropic_api_key`` so AI
    features do not silently disable themselves in production, where we run on
    Bedrock and that key is intentionally unset.
    """
    if provider() == "bedrock":
        return True
    from lib.config import settings  # noqa: PLC0415

    return bool(settings.anthropic_api_key)


@lru_cache(maxsize=1)
def _anthropic_client():
    from anthropic import Anthropic  # noqa: PLC0415
    from lib.config import settings  # noqa: PLC0415

    return Anthropic(api_key=settings.anthropic_api_key)


@lru_cache(maxsize=1)
def _bedrock_client():
    import boto3  # noqa: PLC0415

    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def messages_create(
    *,
    model: str,
    max_tokens: int,
    system: str = "",
    messages: list[dict[str, Any]],
    purpose: str,
    temperature: float | None = None,
    **kwargs: Any,
) -> Response:
    """Unified entrypoint. Shape-compatible with the old `anthropic` SDK response
    (exposes `.content[0].text`), and auto-records to the current AI-log context."""
    prov = provider()
    input_bytes = _estimate_bytes(system) + _estimate_messages(messages)
    try:
        if prov == "bedrock":
            resp = _bedrock_invoke(model, max_tokens, system, messages, temperature, **kwargs)
        else:
            resp = _direct_invoke(model, max_tokens, system, messages, temperature, **kwargs)
    except Exception as e:
        ai_log.record(
            provider=prov if prov == "bedrock" else "anthropic",
            model=model, purpose=purpose,
            input_bytes=input_bytes, output_bytes=0, success=False, error=str(e)[:200],
        )
        raise

    output_bytes = sum(len(getattr(b, "text", "").encode()) for b in resp.content)
    ai_log.record(
        provider=prov if prov == "bedrock" else "anthropic",
        model=model, purpose=purpose,
        input_bytes=input_bytes, output_bytes=output_bytes, success=True,
    )
    return resp


def _system_blocks(system: str) -> list[dict]:
    """Wrap the (static, per-service) system prompt as a cache-controlled block.

    Prompt caching lets repeated calls that share a system prompt re-read it from
    cache instead of re-billing every input token (~90% cheaper on the cached
    span, 5-min TTL). Below the model's minimum cacheable size the marker is
    simply ignored — so it is always safe to attach."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _direct_invoke(model, max_tokens, system, messages, temperature, **kwargs) -> Response:
    kw = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kw["system"] = _system_blocks(system)
    if temperature is not None:
        kw["temperature"] = temperature
    kw.update(kwargs)
    r = _anthropic_client().messages.create(**kw)
    blocks: list = []
    for b in r.content:
        btype = getattr(b, "type", None)
        if btype == "text":
            blocks.append(TextBlock(text=b.text))
        elif btype == "tool_use":
            blocks.append(ToolUseBlock(id=b.id, name=b.name, input=dict(b.input or {})))
    return Response(content=blocks)


def _bedrock_invoke(model, max_tokens, system, messages, temperature, **kwargs) -> Response:
    body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = _system_blocks(system)
    if temperature is not None:
        body["temperature"] = temperature
    # Pass through extras like tools / tool_choice so tool-use works on the
    # Bedrock (BAA) path too, not just the direct API.
    for k, v in kwargs.items():
        body[k] = v
    bedrock_model = _BEDROCK_MODEL_MAP.get(model, model)
    r = _bedrock_client().invoke_model(
        modelId=bedrock_model,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(r["body"].read())
    blocks: list = []
    for b in payload.get("content", []):
        if b.get("type") == "text":
            blocks.append(TextBlock(text=b.get("text", "")))
        elif b.get("type") == "tool_use":
            blocks.append(ToolUseBlock(id=b.get("id", ""), name=b.get("name", ""), input=dict(b.get("input") or {})))
    return Response(content=blocks)


def _estimate_bytes(s: str | None) -> int:
    return len((s or "").encode())


def _estimate_messages(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c.encode())
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict):
                    if "text" in part:
                        total += len(str(part["text"]).encode())
                    if "source" in part and isinstance(part["source"], dict):
                        data = part["source"].get("data", "")
                        total += len(str(data).encode()) * 3 // 4  # base64 → bytes
    return total
