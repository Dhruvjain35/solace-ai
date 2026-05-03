"""Per-patient AI-call attribution log.

Every third-party model call (Claude / OpenAI Whisper / ElevenLabs) appends an
entry so the clinician dashboard + auditors can see exactly which provider saw
which bytes, when, and for what purpose.

Shape of each entry:
  {provider, model, purpose, ts, input_bytes, output_bytes, success}

Not stored in DDB directly — collected in memory during the intake/refine pipeline
via `new_log()` / `record()` and then serialized onto the patient record at the
end of the request. This keeps DDB writes minimal while preserving the audit trail.
"""
from __future__ import annotations

import contextvars
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AIEvent:
    provider: str              # "anthropic" | "bedrock" | "openai" | "elevenlabs"
    model: str                 # e.g. "claude-sonnet-4-5" / "whisper-1" / "eleven_multilingual_v2"
    purpose: str               # "prebrief" | "scribe" | "comfort" | "vision" | "transcription" | "tts" ...
    ts: str                    # ISO8601 UTC
    input_bytes: int = 0
    output_bytes: int = 0
    success: bool = True
    error: str | None = None


# Per-1K-input-tokens / per-1K-output-tokens pricing in USD. Bytes → tokens via
# the rough 1 token ≈ 4 bytes heuristic. Numbers updated against current vendor
# pricing pages; refresh when contracts change. Acceptable accuracy for spend
# trend lines + hospital-facing per-encounter cost reporting; not for invoicing.
_PRICING_USD: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "claude-sonnet-4-5"): (0.003, 0.015),
    ("anthropic", "claude-sonnet-4-5-20251001"): (0.003, 0.015),
    ("bedrock",   "claude-sonnet-4-5"): (0.003, 0.015),
    ("openai",    "whisper-1"):         (0.006 / 60, 0.0),  # whisper bills per minute, treat input_bytes as ms-ish
    ("elevenlabs","eleven_multilingual_v2"): (0.000033, 0.0),  # $0.33 per 10k chars input ≈ $0.000033/char
}


def _estimate_cost_usd(provider: str, model: str, input_bytes: int, output_bytes: int) -> float:
    rates = _PRICING_USD.get((provider, model))
    if not rates:
        return 0.0
    in_rate, out_rate = rates
    # Whisper / ElevenLabs aren't token-based — treat input as bytes-of-input directly.
    if provider == "openai" and model == "whisper-1":
        # Rough: whisper bills $0.006/min; 16kHz mono PCM ≈ 32 KB/sec, MP3 ≈ 3 KB/sec.
        # Use 8 KB/sec as a cross-format midpoint → seconds = bytes / 8000.
        seconds = input_bytes / 8000.0
        return (seconds / 60.0) * 0.006
    if provider == "elevenlabs":
        chars = input_bytes  # input_bytes is the script byte count which ≈ chars in english
        return chars * 0.000033
    in_tokens = input_bytes / 4.0
    out_tokens = output_bytes / 4.0
    return (in_tokens / 1000.0) * in_rate + (out_tokens / 1000.0) * out_rate


@dataclass
class AILog:
    events: list[AIEvent] = field(default_factory=list)

    def record(self, provider: str, model: str, purpose: str, *,
               input_bytes: int = 0, output_bytes: int = 0,
               success: bool = True, error: str | None = None) -> None:
        self.events.append(AIEvent(
            provider=provider, model=model, purpose=purpose,
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            input_bytes=input_bytes, output_bytes=output_bytes,
            success=success, error=error,
        ))

    def serialize(self) -> list[dict[str, Any]]:
        return [asdict(e) for e in self.events]

    def total_cost_usd(self) -> float:
        """Estimated $ spend for this encounter — sum of per-event estimates."""
        return sum(
            _estimate_cost_usd(e.provider, e.model, e.input_bytes, e.output_bytes)
            for e in self.events
            if e.success
        )

    def cost_breakdown(self) -> dict[str, float]:
        """Per-purpose cost split (e.g. {prebrief: 0.012, scribe: 0.018, ...})."""
        out: dict[str, float] = {}
        for e in self.events:
            if not e.success:
                continue
            c = _estimate_cost_usd(e.provider, e.model, e.input_bytes, e.output_bytes)
            out[e.purpose] = round(out.get(e.purpose, 0.0) + c, 5)
        return out


# Context variable so nested service calls share the same log without threading it
# through every function signature. Routers call `new_log()` at the top of their
# handler; services call `current()` to append.
_current: contextvars.ContextVar[AILog | None] = contextvars.ContextVar("ai_log", default=None)


def new_log() -> AILog:
    log = AILog()
    _current.set(log)
    return log


def current() -> AILog | None:
    return _current.get()


def record(**kwargs: Any) -> None:
    """Shortcut — no-op if no log is active (e.g. warmup dry-prediction path)."""
    log = _current.get()
    if log is not None:
        log.record(**kwargs)
