"""PHI guardrails for the no-code workflow engine.

Workflows are author-editable by hospital admins and they fire automatically
on patient events. Two places PHI can leak:

  1. The *context* the engine dispatches to action handlers (and from there to
     SMS bodies, Slack webhooks, Claude prompts, outbound HTTP). A context dict
     assembled from a live patient row carries names, phones, emails, DOB, the
     raw transcript and addresses — none of which a workflow needs.
  2. The *workflow definition itself* — a step config can hard-code a template
     like "SSN on file: 123-45-6789" or "{{patient.transcript}}" that would
     ship PHI to a third party every time the workflow runs.

`sanitize_context()` strips PHI-bearing fields out of any context before the
engine runs an action chain, keeping only opaque identifiers (ids, hashes,
ESI level, language, counts) that workflows legitimately need.

`validate_no_phi()` scans a workflow definition's step configs for PHI-leaking
templates — both literal PHI signatures (reusing lib.content_guard PII regexes)
and references to PHI-bearing context paths like {{patient.transcript}}.

HIPAA §164.514(b) Safe Harbor — data minimization. The regex catalog is the
single source of truth in lib.content_guard._PII_REDACTIONS; we reuse it here
rather than maintaining a second copy.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from lib.content_guard import _REDACT

log = logging.getLogger(__name__)


# Field names that carry PHI and must NEVER reach an action handler. Matched
# case-insensitively against dict keys at every depth of the context.
_PHI_KEYS: frozenset[str] = frozenset({
    "name", "full_name", "first_name", "last_name", "patient_name",
    "preferred_name", "caller_name", "guardian_name", "emergency_contact",
    "phone", "phone_number", "caller_phone", "mobile", "telephone",
    "email", "email_address",
    "dob", "date_of_birth", "birthdate", "birth_date",
    "transcript", "raw_transcript", "chief_complaint_text", "hpi",
    "free_text", "narrative", "notes_text", "voice_transcript",
    "address", "street", "street_address", "home_address", "mailing_address",
    "zip", "zipcode", "postal_code",
    "ssn", "mrn", "medical_record_number", "member_id", "subscriber_id",
    "account_number", "license_number", "insurance_id", "policy_number",
    "ip", "ip_address", "source_ip", "geolocation", "lat", "lng",
})

# Identifier-shaped keys that are SAFE to keep — opaque ids and hashes carry no
# Safe Harbor identifier. We allowlist them so a key like "patient_id" is not
# mistaken for a PHI key by a future fuzzy match.
_SAFE_ID_KEYS: frozenset[str] = frozenset({
    "id", "patient_id", "hospital_id", "workflow_id", "appointment_id",
    "note_id", "encounter_id", "result_id", "task_id", "thread_id",
    "phone_hash", "patient_phone_hash", "caller_phone_hash", "hash",
})

# Context paths a step template must never interpolate — these resolve to PHI
# even though their leaf key might look innocuous in a dotted path.
_PHI_PATHS: frozenset[str] = frozenset({
    "patient.name", "patient.full_name", "patient.first_name",
    "patient.last_name", "patient.phone", "patient.phone_number",
    "patient.email", "patient.dob", "patient.date_of_birth",
    "patient.transcript", "patient.raw_transcript", "patient.address",
    "patient.ssn", "patient.mrn", "patient.member_id",
    "caller.name", "caller.phone", "appointment.patient_name",
    "appointment.patient_phone", "encounter.transcript", "result.patient_name",
})

# {{ path }} extractor — mirrors actions._VAR_RE so validation sees exactly the
# templates the interpolator would expand.
_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _is_phi_key(key: str) -> bool:
    k = str(key).strip().lower()
    if k in _SAFE_ID_KEYS:
        return False
    return k in _PHI_KEYS


def sanitize_context(context: Any) -> Any:
    """Return a deep copy of `context` with every PHI-bearing field removed.

    - Drops keys in `_PHI_KEYS` at any nesting depth (lists included).
    - Keeps opaque ids/hashes (`_SAFE_ID_KEYS`), ESI level, language, counts.
    - Redacts any literal PHI signature that survives inside a kept string
      value (e.g. a transcript snippet copied into a `reason` field) using the
      content_guard PII regexes.

    The engine calls this before dispatching any action so that no handler —
    SMS, Slack, webhook, Claude prompt — ever receives raw PHI.
    """
    if isinstance(context, dict):
        clean: dict[str, Any] = {}
        for key, value in context.items():
            if _is_phi_key(key):
                continue
            clean[key] = sanitize_context(value)
        return clean
    if isinstance(context, (list, tuple)):
        return [sanitize_context(v) for v in context]
    if isinstance(context, str):
        return _redact_literals(context)
    return context


def _redact_literals(text: str) -> str:
    """Apply the content_guard PII redaction regexes to a free-text value."""
    if not text:
        return text
    cleaned = text
    for rx, replacement in _REDACT:
        if rx.search(cleaned):
            cleaned = rx.sub(replacement, cleaned)
    return cleaned


def _scan_template_string(value: str) -> list[str]:
    """Return PHI findings for one step-config string value."""
    findings: list[str] = []
    if not value:
        return findings

    # 1. {{ path }} references to PHI-bearing context paths.
    for m in _VAR_RE.finditer(value):
        path = m.group(1).strip().lower()
        leaf = path.split(".")[-1]
        if path in _PHI_PATHS or (_is_phi_key(leaf) and "." in path):
            findings.append(f"phi-path:{path}")

    # 2. Literal PHI signatures hard-coded into the template.
    for rx, replacement in _REDACT:
        if rx.search(value):
            tag = replacement.strip("[]").replace("REDACTED:", "").lower()
            findings.append(f"phi-literal:{tag}")

    return findings


def validate_no_phi(workflow: dict) -> tuple[bool, list[str]]:
    """Scan a workflow definition for PHI-leaking step templates.

    Returns (safe, findings). `safe=False` means at least one step config
    references a PHI context path (e.g. {{patient.transcript}}) or hard-codes a
    literal PHI signature. The router calls this before persisting a workflow
    so a PHI-leaking automation can never be saved or enabled.
    """
    findings: list[str] = []
    if not isinstance(workflow, dict):
        return True, findings

    for i, step in enumerate(workflow.get("steps") or []):
        if not isinstance(step, dict):
            continue
        config = step.get("config")
        if not isinstance(config, dict):
            continue
        for field, value in config.items():
            for hit in _scan_string_recursive(value):
                findings.append(f"step[{i}].{field}:{hit}")

    # Filters are author-supplied too — a filter value could embed a literal.
    for field, value in (workflow.get("filters") or {}).items():
        for hit in _scan_string_recursive(value):
            findings.append(f"filter.{field}:{hit}")

    safe = not findings
    if not safe:
        log.warning(
            "workflow PHI validation rejected '%s': %s",
            workflow.get("name") or workflow.get("workflow_id") or "?",
            findings,
        )
    return safe, findings


def _scan_string_recursive(value: Any) -> list[str]:
    """Walk a config value (string / list / nested dict) for PHI findings."""
    out: list[str] = []
    if isinstance(value, str):
        out.extend(_scan_template_string(value))
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_scan_string_recursive(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_scan_string_recursive(v))
    return out
