"""Action registry — what a workflow step can do.

Adding a new action: write a handler function that takes (config, context)
and returns a result dict, then add it to ACTIONS.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from db import storage
from lib import audit as _audit
from services import sms

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionDef:
    type: str                          # canonical id, e.g. "send_sms"
    label: str                         # human display
    description: str
    fields: list[dict]                 # form schema: [{name, label, type, required, help}]
    handler: Callable[[dict, dict], dict]


# --- handlers -----------------------------------------------------------------


def _send_sms(config: dict, context: dict) -> dict:
    to = _interpolate(str(config.get("to", "")), context)
    body = _interpolate(str(config.get("body", "")), context)
    if not to or not body:
        return {"success": False, "reason": "missing_to_or_body"}
    return sms.send(to=to, body=body)


def _send_slack_webhook(config: dict, context: dict) -> dict:
    url = str(config.get("webhook_url", "")).strip()
    text = _interpolate(str(config.get("text", "")), context)
    if not url or not text:
        return {"success": False, "reason": "missing_url_or_text"}
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json={"text": text})
            return {"success": resp.status_code < 400, "status": resp.status_code}
    except Exception as e:  # noqa: BLE001
        log.warning("slack webhook failed: %s", e)
        return {"success": False, "reason": "webhook_error", "message": str(e)[:200]}


def _http_webhook(config: dict, context: dict) -> dict:
    """Generic outbound webhook — POST a JSON body to any URL.

    Lets admins integrate with anything that accepts a webhook (Zapier, Make,
    custom EHRs, in-house Slack alternatives, etc.)."""
    url = str(config.get("url", "")).strip()
    if not url:
        return {"success": False, "reason": "missing_url"}
    body_template = str(config.get("body_template", "{}"))
    try:
        rendered = _interpolate(body_template, context)
        payload = json.loads(rendered)
    except json.JSONDecodeError as e:
        return {"success": False, "reason": "invalid_json_body", "message": str(e)[:200]}
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json=payload)
            return {"success": resp.status_code < 400, "status": resp.status_code}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "reason": "webhook_error", "message": str(e)[:200]}


def _create_clinician_note(config: dict, context: dict) -> dict:
    patient = context.get("patient") or {}
    patient_id = patient.get("id") or patient.get("patient_id")
    if not patient_id:
        return {"success": False, "reason": "no_patient_in_context"}
    text = _interpolate(str(config.get("text", "")), context)
    author = str(config.get("author", "Workflow Bot"))
    if not text:
        return {"success": False, "reason": "missing_text"}
    import uuid  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415
    note = {
        "note_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "hospital_id": (context.get("hospital") or {}).get("id", "demo"),
        "text": text,
        "author": author,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    storage.add_note(note)
    return {"success": True, "note_id": note["note_id"]}


def _set_patient_field(config: dict, context: dict) -> dict:
    """Update a single field on the patient row. Useful for tagging
    ('vip', 'frequent_flyer'), pre-filling notes, etc."""
    patient = context.get("patient") or {}
    patient_id = patient.get("id") or patient.get("patient_id")
    if not patient_id:
        return {"success": False, "reason": "no_patient_in_context"}
    field = str(config.get("field", "")).strip()
    if not field or field in {"patient_id", "hospital_id", "ttl"}:
        return {"success": False, "reason": "invalid_field"}
    value = _interpolate(str(config.get("value", "")), context)
    storage.update_patient(patient_id, {field: value})
    return {"success": True, "field": field}


def _run_claude_prompt(config: dict, context: dict) -> dict:
    """Run an arbitrary Claude prompt with interpolated context. Output is
    saved on the patient row as `workflow_outputs.{output_key}`."""
    from lib import claude  # noqa: PLC0415

    prompt = _interpolate(str(config.get("prompt", "")), context)
    output_key = str(config.get("output_key", "")).strip()
    if not prompt:
        return {"success": False, "reason": "missing_prompt"}
    try:
        resp = claude.messages_create(
            model="claude-sonnet-4-5",
            max_tokens=600,
            system="You are a workflow helper. Reply with the requested content only — no preamble.",
            messages=[{"role": "user", "content": prompt}],
            purpose="workflow_action",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "reason": "claude_error", "message": str(e)[:200]}
    if output_key:
        patient = context.get("patient") or {}
        pid = patient.get("id") or patient.get("patient_id")
        if pid:
            existing = (storage.get_patient(pid) or {}).get("workflow_outputs") or {}
            if isinstance(existing, str):
                try:
                    existing = json.loads(existing)
                except Exception:
                    existing = {}
            existing[output_key] = text[:4000]
            storage.update_patient(pid, {"workflow_outputs": json.dumps(existing)})
    return {"success": True, "output": text[:1000]}


def _audit_log(config: dict, context: dict) -> dict:
    """Pure audit log entry — useful for compliance triggers ('log every time
    a high-acuity patient is checked in')."""
    action = str(config.get("action", "workflow.audit")).strip()
    extra = {
        "patient_id": (context.get("patient") or {}).get("id"),
        "trigger": context.get("trigger"),
    }
    _audit.record(
        clinician_id=None, clinician_name="Workflow Bot",
        action=action, source_ip=None, status_code=200, extra=extra,
        patient_id=extra["patient_id"],
    )
    return {"success": True}


def _slack_message(config: dict, context: dict) -> dict:
    """Post a message to Slack. This is the canonical 'slack_message' action
    referenced by the appointment template — it accepts a `channel` + `message`
    pair (the editor-friendly shape) and also honours a `webhook_url` override.
    Channel is advisory metadata for the Slack app; routing is by webhook."""
    url = str(config.get("webhook_url", "")).strip()
    channel = str(config.get("channel", "")).strip()
    text = _interpolate(str(config.get("message", config.get("text", ""))), context)
    if not text:
        return {"success": False, "reason": "missing_message"}
    if not url:
        # No webhook bound yet — record intent without leaving the boundary so
        # a half-configured template fails safe instead of erroring.
        log.info("slack_message has no webhook_url (channel=%s) — skipped", channel)
        return {"success": False, "reason": "missing_webhook_url", "channel": channel}
    payload: dict = {"text": text}
    if channel:
        payload["channel"] = channel
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json=payload)
            return {"success": resp.status_code < 400, "status": resp.status_code,
                    "channel": channel}
    except Exception as e:  # noqa: BLE001
        log.warning("slack_message failed: %s", e)
        return {"success": False, "reason": "webhook_error", "message": str(e)[:200]}


def _draft_message(config: dict, context: dict) -> dict:
    """Draft a patient-facing message with Claude and stage it for clinician
    review. The draft is NOT auto-sent — it is saved on the patient row under
    workflow_outputs so a human approves before anything reaches the patient."""
    from lib import claude  # noqa: PLC0415

    purpose = _interpolate(str(config.get("purpose", "a follow-up update")), context)
    tone = str(config.get("tone", "warm, plain-language")).strip()
    output_key = str(config.get("output_key", "drafted_message")).strip() or "drafted_message"
    prompt = (
        f"Draft a short {tone} message to a patient about: {purpose}. "
        "Do not invent clinical facts. Keep it under 90 words. "
        "Use only the context provided; do not request or include identifiers."
    )
    try:
        resp = claude.messages_create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            system="You draft patient communications for clinician review. "
                   "Reply with the message body only — no preamble, no PHI.",
            messages=[{"role": "user", "content": prompt}],
            purpose="workflow_draft_message",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "reason": "claude_error", "message": str(e)[:200]}
    _save_output(context, output_key, text)
    return {"success": True, "status": "drafted_for_review", "output": text[:1000]}


def _generate_letter(config: dict, context: dict) -> dict:
    """Generate a clinical/administrative letter (work note, referral, results
    summary) and stage it on the patient row for clinician review and signing.
    Letters are never auto-delivered from a workflow."""
    from lib import claude  # noqa: PLC0415

    letter_type = str(config.get("letter_type", "general")).strip() or "general"
    instructions = _interpolate(str(config.get("instructions", "")), context)
    output_key = str(config.get("output_key", "drafted_letter")).strip() or "drafted_letter"
    prompt = (
        f"Draft a {letter_type} letter for clinician review and signature. "
        f"Instructions: {instructions or 'standard letter for this letter type'}. "
        "Leave a [PATIENT NAME] placeholder; never fill in identifiers. "
        "Keep it professional and concise."
    )
    try:
        resp = claude.messages_create(
            model="claude-sonnet-4-5",
            max_tokens=700,
            system="You draft clinical letters for clinician review. "
                   "Reply with the letter body only. Never include PHI — "
                   "use bracketed placeholders for any identifier.",
            messages=[{"role": "user", "content": prompt}],
            purpose="workflow_generate_letter",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "reason": "claude_error", "message": str(e)[:200]}
    _save_output(context, output_key, text)
    return {"success": True, "status": "drafted_for_review", "letter_type": letter_type,
            "output": text[:1000]}


def _create_task(config: dict, context: dict) -> dict:
    """Open a follow-up task for the care team. Persisted as a clinician note
    tagged [TASK] on the patient chart so it shows on the dashboard with no new
    table required. Title + due window come from the step config."""
    patient = context.get("patient") or {}
    patient_id = patient.get("id") or patient.get("patient_id")
    if not patient_id:
        return {"success": False, "reason": "no_patient_in_context"}
    title = _interpolate(str(config.get("title", "")), context).strip()
    if not title:
        return {"success": False, "reason": "missing_title"}
    priority = str(config.get("priority", "normal")).strip() or "normal"
    assignee = str(config.get("assignee", "Care team")).strip() or "Care team"
    due_in_days = config.get("due_in_days")
    import uuid  # noqa: PLC0415
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    now = datetime.now(timezone.utc)
    due_note = ""
    if due_in_days not in (None, ""):
        try:
            due = now + timedelta(days=int(due_in_days))
            due_note = f" Due {due.date().isoformat()}."
        except (TypeError, ValueError):
            due_note = ""
    note = {
        "note_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "hospital_id": (context.get("hospital") or {}).get("id", "demo"),
        "text": f"[TASK] ({priority}) {title} — assigned to {assignee}.{due_note}",
        "author": "Workflow Bot",
        "kind": "task",
        "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    storage.add_note(note)
    return {"success": True, "task_id": note["note_id"], "priority": priority}


def _ehr_write(config: dict, context: dict) -> dict:
    """Stage a structured write-back to the connected EHR (flag, problem,
    care-team note). Workflows do not push to the EHR directly — the payload is
    queued on the patient row as `ehr_writeback_queue` and the EHR gateway
    drains it under clinician authorization. This keeps the write auditable and
    avoids an unauthenticated automatic EHR mutation."""
    patient = context.get("patient") or {}
    patient_id = patient.get("id") or patient.get("patient_id")
    if not patient_id:
        return {"success": False, "reason": "no_patient_in_context"}
    resource = str(config.get("resource", "")).strip()
    if resource not in {"flag", "problem", "careteam_note", "observation"}:
        return {"success": False, "reason": "invalid_resource",
                "allowed": ["flag", "problem", "careteam_note", "observation"]}
    payload_value = _interpolate(str(config.get("value", "")), context)
    if not payload_value:
        return {"success": False, "reason": "missing_value"}
    from datetime import datetime, timezone  # noqa: PLC0415
    entry = {
        "resource": resource,
        "value": payload_value[:1000],
        "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "workflow",
        "status": "pending_clinician_auth",
    }
    existing = (storage.get_patient(patient_id) or {}).get("ehr_writeback_queue") or []
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except Exception:  # noqa: BLE001
            existing = []
    existing.append(entry)
    storage.update_patient(patient_id, {"ehr_writeback_queue": json.dumps(existing[-50:])})
    return {"success": True, "resource": resource, "status": "queued_for_clinician_auth"}


def _notify(config: dict, context: dict) -> dict:
    """Send an internal staff notification — a pure audit-trail + log signal
    that the dashboard surfaces. Unlike SMS/Slack this never leaves the trust
    boundary, so it is the safe default for paging the care team."""
    message = _interpolate(str(config.get("message", "")), context).strip()
    if not message:
        return {"success": False, "reason": "missing_message"}
    channel = str(config.get("channel", "dashboard")).strip() or "dashboard"
    patient_id = (context.get("patient") or {}).get("id")
    _audit.record(
        clinician_id=None, clinician_name="Workflow Bot",
        action="workflow.notify", source_ip=None, status_code=200,
        extra={"channel": channel, "message": message[:500],
               "trigger": context.get("trigger"), "patient_id": patient_id},
        patient_id=patient_id,
    )
    log.info("workflow notify [%s]: %s", channel, message[:200])
    return {"success": True, "channel": channel}


def _save_output(context: dict, output_key: str, text: str) -> None:
    """Persist an AI-generated draft on patient.workflow_outputs[<key>]."""
    patient = context.get("patient") or {}
    pid = patient.get("id") or patient.get("patient_id")
    if not pid:
        return
    existing = (storage.get_patient(pid) or {}).get("workflow_outputs") or {}
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except Exception:  # noqa: BLE001
            existing = {}
    existing[output_key] = text[:4000]
    storage.update_patient(pid, {"workflow_outputs": json.dumps(existing)})


# --- registry -----------------------------------------------------------------


ACTIONS: list[ActionDef] = [
    ActionDef(
        type="send_sms",
        label="Send SMS",
        description="Send a text message via Twilio. Falls back to a no-op if Twilio isn't configured.",
        fields=[
            {"name": "to", "label": "To", "type": "text", "required": True,
             "help": "Phone number or {{patient.phone}}."},
            {"name": "body", "label": "Message", "type": "textarea", "required": True,
             "help": "Body text. Variables like {{patient.name}} are interpolated."},
        ],
        handler=_send_sms,
    ),
    ActionDef(
        type="send_slack_webhook",
        label="Post to Slack",
        description="POST a message to a Slack incoming webhook.",
        fields=[
            {"name": "webhook_url", "label": "Slack webhook URL", "type": "text", "required": True,
             "help": "Get one from your Slack workspace's Incoming Webhooks app."},
            {"name": "text", "label": "Message", "type": "textarea", "required": True},
        ],
        handler=_send_slack_webhook,
    ),
    ActionDef(
        type="http_webhook",
        label="Outbound HTTP webhook",
        description="POST JSON to any URL — integrate with Zapier, Make, custom EHR, etc.",
        fields=[
            {"name": "url", "label": "URL", "type": "text", "required": True},
            {"name": "body_template", "label": "JSON body template", "type": "textarea",
             "required": True, "help": "JSON with {{vars}} interpolation."},
        ],
        handler=_http_webhook,
    ),
    ActionDef(
        type="create_clinician_note",
        label="Add clinician note",
        description="Append a note to the patient's chart automatically.",
        fields=[
            {"name": "text", "label": "Note text", "type": "textarea", "required": True},
            {"name": "author", "label": "Author", "type": "text", "required": False},
        ],
        handler=_create_clinician_note,
    ),
    ActionDef(
        type="set_patient_field",
        label="Set patient field",
        description="Tag the patient row with a custom field (vip, follow_up, etc.).",
        fields=[
            {"name": "field", "label": "Field name", "type": "text", "required": True,
             "help": "e.g. tag, follow_up_reason, alert_priority"},
            {"name": "value", "label": "Value", "type": "text", "required": True},
        ],
        handler=_set_patient_field,
    ),
    ActionDef(
        type="run_claude_prompt",
        label="Run Claude prompt",
        description="Run a Claude prompt with workflow variables; save output on the patient.",
        fields=[
            {"name": "prompt", "label": "Prompt", "type": "textarea", "required": True,
             "help": "Use {{patient.name}}, {{patient.transcript}}, etc."},
            {"name": "output_key", "label": "Save output as", "type": "text", "required": False,
             "help": "Stored on patient.workflow_outputs[<key>]. Empty = run-and-discard."},
        ],
        handler=_run_claude_prompt,
    ),
    ActionDef(
        type="audit_log",
        label="Audit log entry",
        description="Write a row to the compliance audit log. Use for HIPAA tracking patterns.",
        fields=[
            {"name": "action", "label": "Audit action name", "type": "text", "required": True,
             "help": "e.g. high_acuity_arrived"},
        ],
        handler=_audit_log,
    ),
    ActionDef(
        type="slack_message",
        label="Send Slack message",
        description="Post a message to a Slack channel via an incoming webhook.",
        fields=[
            {"name": "webhook_url", "label": "Slack webhook URL", "type": "text", "required": True,
             "help": "Incoming webhook from your Slack workspace."},
            {"name": "channel", "label": "Channel", "type": "text", "required": False,
             "help": "e.g. #appointments — advisory label for the Slack app."},
            {"name": "message", "label": "Message", "type": "textarea", "required": True,
             "help": "Body text. {{vars}} are interpolated from the trigger context."},
        ],
        handler=_slack_message,
    ),
    ActionDef(
        type="draft_message",
        label="Draft patient message",
        description="Draft a patient-facing message with Claude and stage it for clinician review (never auto-sent).",
        fields=[
            {"name": "purpose", "label": "Message purpose", "type": "textarea", "required": True,
             "help": "What the message is about, e.g. 'follow-up after abnormal result'."},
            {"name": "tone", "label": "Tone", "type": "text", "required": False,
             "help": "Default: warm, plain-language."},
            {"name": "output_key", "label": "Save draft as", "type": "text", "required": False,
             "help": "Stored on patient.workflow_outputs[<key>]. Default: drafted_message."},
        ],
        handler=_draft_message,
    ),
    ActionDef(
        type="generate_letter",
        label="Generate letter",
        description="Draft a clinical/administrative letter for clinician review and signature.",
        fields=[
            {"name": "letter_type", "label": "Letter type", "type": "text", "required": True,
             "help": "e.g. work_note, referral, results_summary."},
            {"name": "instructions", "label": "Instructions", "type": "textarea", "required": False,
             "help": "What the letter should say. {{vars}} interpolated."},
            {"name": "output_key", "label": "Save draft as", "type": "text", "required": False,
             "help": "Default: drafted_letter."},
        ],
        handler=_generate_letter,
    ),
    ActionDef(
        type="create_task",
        label="Create follow-up task",
        description="Open a care-team task on the patient chart (shown on the dashboard).",
        fields=[
            {"name": "title", "label": "Task title", "type": "text", "required": True},
            {"name": "priority", "label": "Priority", "type": "text", "required": False,
             "help": "low / normal / high. Default: normal."},
            {"name": "assignee", "label": "Assignee", "type": "text", "required": False,
             "help": "Role or name. Default: Care team."},
            {"name": "due_in_days", "label": "Due in (days)", "type": "number", "required": False},
        ],
        handler=_create_task,
    ),
    ActionDef(
        type="ehr_write",
        label="Write back to EHR",
        description="Queue a structured EHR write-back (flag/problem/note) for clinician authorization.",
        fields=[
            {"name": "resource", "label": "Resource type", "type": "text", "required": True,
             "help": "flag / problem / careteam_note / observation."},
            {"name": "value", "label": "Value", "type": "textarea", "required": True,
             "help": "Content to write. {{vars}} interpolated."},
        ],
        handler=_ehr_write,
    ),
    ActionDef(
        type="notify",
        label="Notify staff",
        description="Send an internal staff notification — stays inside the trust boundary, no PHI leaves.",
        fields=[
            {"name": "message", "label": "Message", "type": "textarea", "required": True},
            {"name": "channel", "label": "Channel", "type": "text", "required": False,
             "help": "Logical channel, e.g. dashboard, charge_nurse. Default: dashboard."},
        ],
        handler=_notify,
    ),
]


def by_type(type_id: str) -> ActionDef | None:
    return next((a for a in ACTIONS if a.type == type_id), None)


def to_public_list() -> list[dict]:
    return [
        {
            "type": a.type, "label": a.label, "description": a.description,
            "fields": a.fields,
        }
        for a in ACTIONS
    ]


def run(action_type: str, config: dict, context: dict) -> dict:
    a = by_type(action_type)
    if not a:
        return {"success": False, "reason": "unknown_action_type", "type": action_type}
    try:
        return a.handler(config, context)
    except Exception as e:  # noqa: BLE001
        log.exception("workflow action %s failed: %s", action_type, e)
        return {"success": False, "reason": "handler_exception", "message": str(e)[:200]}


# --- variable interpolation ---------------------------------------------------


_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _interpolate(template: str, context: dict) -> str:
    """Replace {{path.to.value}} with context["path"]["to"]["value"]. Missing
    paths render as empty strings — we never error on a missing var because
    workflows shouldn't break a patient flow if a field happens to be empty."""
    if not template:
        return ""
    def _repl(m: re.Match[str]) -> str:
        path = m.group(1).split(".")
        cur: Any = context
        for p in path:
            if isinstance(cur, dict):
                cur = cur.get(p, "")
            else:
                return ""
            if cur is None or cur == "":
                return ""
        return str(cur)
    return _VAR_RE.sub(_repl, template)
