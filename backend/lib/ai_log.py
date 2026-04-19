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
