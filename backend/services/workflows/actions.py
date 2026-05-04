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
