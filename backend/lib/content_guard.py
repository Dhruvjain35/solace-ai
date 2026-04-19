"""Pre-Claude content guardrails.

Magic bytes prove a file looks like audio/image; this module classifies the
TEXT we extracted from it. Catches:

  - Prompt-injection attempts in transcripts ("ignore previous instructions")
  - LLM control-token smuggling (`[INST]`, `<|im_start|>`, `<|system|>`, …)
  - Obvious PHI-scraping intents ("list all patients", "dump the database")
  - System-prompt overrides ("you are now", "you're actually", "as DAN")

Decision policy:
  - HIGH confidence → reject the request, 422, audit event
  - LOW confidence → accept but sanitize (strip the offending tokens) and log

Guardrails here are deliberately cheap regex; a real deployment would layer a
classifier. For HIPAA §164.514 (data minimization) we also redact obvious PII
signatures before shipping transcripts to third-party LLMs.
"""
from __future__ import annotations

import logging
import re

from lib import audit as _audit

log = logging.getLogger(__name__)


# HIGH-confidence prompt-injection patterns — reject outright
_REJECT_PATTERNS = [
    (r"ignore\s+(?:all\s+|the\s+|any\s+)?(?:previous|prior|above)\s+"
     r"(?:instruction|prompt|message|rule|system)", "ignore-previous"),
    (r"(?:you\s+are\s+now|you're\s+now|from\s+now\s+on\s+you)\s+"
     r"(?:a\s+|an\s+|the\s+)?(?:different|new|jailbroken|unrestricted|DAN)", "persona-override"),
    (r"\[/?(?:INST|SYS|SYSTEM|HUMAN|ASSISTANT)\]", "inst-token"),
    (r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>", "chat-control-token"),
    (r"(?:forget|disregard|override)\s+(?:your\s+|the\s+|all\s+)?"
     r"(?:instructions?|prompt|system\s+message|rules?|training)", "forget-instructions"),
    (r"(?:dump|list|show\s+me|give\s+me)\s+(?:all\s+)?"
     r"(?:patient|user|record|credential|token|secret|api[_\s]?key|password)s?",
     "data-exfiltration-intent"),
    (r"you\s+must\s+(?:ignore|override|bypass)\s+", "direct-override"),
    (r"(?:reveal|print|leak|expose)\s+(?:your\s+)?(?:system\s+prompt|hidden\s+prompt|"
     r"instructions|api\s+key)", "prompt-leak"),
]

# LOW-confidence — strip but don't reject
_SANITIZE_PATTERNS = [
    (r"```[\s\S]*?```", "code-block"),
    (r"<\|[^|]*\|>", "generic-control-token"),
    (r"\{\{[\s\S]*?\}\}", "template-interpolation"),
]

# PHI signatures — always redact before third-party LLM calls (§164.514)
_PII_REDACTIONS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED:SSN]"),
    (r"\b\d{3}\.\d{2}\.\d{4}\b", "[REDACTED:SSN]"),
    (r"\b\d{16}\b", "[REDACTED:CARD]"),
    (r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b", "[REDACTED:CARD]"),
    (r"\b\d{3}-\d{3}-\d{4}\b", "[REDACTED:PHONE]"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED:EMAIL]"),
]


def _compile():
    return (
        [(re.compile(p, re.IGNORECASE), tag) for p, tag in _REJECT_PATTERNS],
        [(re.compile(p, re.IGNORECASE), tag) for p, tag in _SANITIZE_PATTERNS],
        [(re.compile(p), tag) for p, tag in _PII_REDACTIONS],
    )


_REJECT, _SANITIZE, _REDACT = _compile()


def scan(
    text: str,
    *,
    label: str,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[bool, str, list[str]]:
    """Inspect `text`. Returns (safe, cleaned_text, findings).

    - `safe=False` → caller should reject (HIGH patterns matched).
    - `safe=True` → cleaned_text has sanitize patterns removed + PII redacted.
    - `findings` names every rule hit (for audit).
    """
    findings: list[str] = []
    if not text:
        return True, text, findings

    # Pre-compute the caller's quota identity so abuse audit records attribute
    # the event to the SAME identity that the blocklist enforce() check uses.
    from lib.quota import identity_of  # noqa: PLC0415

    identity = identity_of(source_ip, user_agent) if (source_ip or user_agent) else None

    # 1. Rejection patterns — high confidence
    for rx, tag in _REJECT:
        if rx.search(text):
            findings.append(f"reject:{tag}")
    if findings:
        extra = {"label": label, "findings": findings, "snippet": text[:200]}
        if identity:
            extra["identity"] = identity
        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.content_prompt_injection",
            source_ip=source_ip, status_code=422,
            extra=extra,
        )
        return False, text, findings

    # 2. Sanitize patterns — strip LLM control tokens / code blocks
    cleaned = text
    for rx, tag in _SANITIZE:
        if rx.search(cleaned):
            findings.append(f"sanitize:{tag}")
            cleaned = rx.sub("", cleaned)

    # 3. PII redaction — §164.514 minimization before third-party LLM calls
    for rx, replacement in _REDACT:
        if rx.search(cleaned):
            findings.append(f"redact:{replacement.strip('[]:REDACTED').strip(':')}")
            cleaned = rx.sub(replacement, cleaned)

    if findings:
        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.content_sanitized",
            source_ip=source_ip, status_code=200,
            extra={"label": label, "findings": findings},
        )

    return True, cleaned, findings
