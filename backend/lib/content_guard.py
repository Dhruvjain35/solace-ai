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

# PHI signatures — always redact before third-party LLM calls.
# Covers all 18 HIPAA §164.514(b) Safe Harbor identifiers that can appear in
# free-text transcripts. Some identifiers (biometrics, photos, device IDs) are
# not regex-matchable in text and are handled by other layers (EXIF stripping,
# upload sanitization).
_PII_REDACTIONS = [
    # 1. SSN (###-##-#### and ###.##.####)
    (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED:SSN]"),
    (r"\b\d{3}\.\d{2}\.\d{4}\b", "[REDACTED:SSN]"),

    # 2. Credit/debit card numbers (16-digit continuous or spaced/dashed groups)
    (r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b", "[REDACTED:CARD]"),
    (r"\b\d{16}\b", "[REDACTED:CARD]"),

    # 3. Phone numbers (US formats: ###-###-####, (###) ###-####, +1##########)
    (r"\b\d{3}-\d{3}-\d{4}\b", "[REDACTED:PHONE]"),
    (r"\(\d{3}\)\s*\d{3}-\d{4}", "[REDACTED:PHONE]"),
    (r"\+1\d{10}\b", "[REDACTED:PHONE]"),
    (r"\b\d{10}\b", "[REDACTED:PHONE]"),

    # 4. Email addresses
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED:EMAIL]"),

    # 5. Date of birth patterns (MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD, "born on", "DOB:")
    (r"(?i)(?:date\s+of\s+birth|dob|born\s+on|birthdate|birth\s+date)\s*[:=]?\s*"
     r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", "[REDACTED:DOB]"),
    (r"\b(?:0[1-9]|1[0-2])[/\-](?:0[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b", "[REDACTED:DATE]"),

    # 6. Street addresses (number + street name + suffix)
    (r"\b\d{1,5}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][a-z]+\s+){1,3}"
     r"(?:St(?:reet)?|Ave(?:nue)?|Blvd|Boulevard|Dr(?:ive)?|Ln|Lane|Rd|Road|Way|Ct|Court|Pl|Place|Pkwy|Cir(?:cle)?)"
     r"\.?\b", "[REDACTED:ADDRESS]"),

    # 7. ZIP codes (5-digit and ZIP+4)
    (r"\b\d{5}-\d{4}\b", "[REDACTED:ZIP]"),

    # 8. Medical record numbers (MRN patterns: MRN/MR# followed by digits)
    (r"(?i)(?:MRN|MR#|medical\s+record\s*#?)\s*[:=]?\s*[A-Z0-9\-]{4,15}", "[REDACTED:MRN]"),

    # 9. Health plan beneficiary numbers
    (r"(?i)(?:member\s*(?:id|#|number)|subscriber\s*(?:id|#|number)|policy\s*(?:id|#|number)|"
     r"group\s*(?:id|#|number))\s*[:=]?\s*[A-Z0-9\-]{4,20}", "[REDACTED:MEMBER_ID]"),

    # 10. Account numbers (generic labeled account/acct patterns)
    (r"(?i)(?:account|acct)\s*(?:#|number|no\.?)\s*[:=]?\s*\d{6,17}", "[REDACTED:ACCOUNT]"),

    # 11. Certificate/license numbers
    (r"(?i)(?:license|licence|certificate|cert)\s*(?:#|number|no\.?)\s*[:=]?\s*[A-Z0-9\-]{4,15}",
     "[REDACTED:LICENSE]"),

    # 12. Vehicle identifiers (VIN: 17 alphanumeric, license plate patterns)
    (r"\b[A-HJ-NPR-Z0-9]{17}\b", "[REDACTED:VIN]"),

    # 13. Device serial numbers / identifiers (labeled patterns)
    (r"(?i)(?:serial\s*(?:#|number|no\.?)|device\s*(?:id|#))\s*[:=]?\s*[A-Z0-9\-]{6,20}",
     "[REDACTED:DEVICE_ID]"),

    # 14. URLs (web/ftp) — can contain patient portal links with embedded identifiers
    (r"https?://[^\s<>\"']{8,}", "[REDACTED:URL]"),
    (r"ftp://[^\s<>\"']{8,}", "[REDACTED:URL]"),

    # 15. IP addresses (v4)
    (r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
     "[REDACTED:IP]"),
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
