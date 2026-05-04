"""No-code workflow builder.

Keragon / Notable-style: hospital admins describe a trigger + a chain of
actions in a form, and the engine fires the chain whenever the event happens.

Module layout:
  triggers.py — registry of event names + their payload shapes
  actions.py  — registry of action types + their handlers (sms, slack, note, etc)
  engine.py   — fire(event_name, hospital_id, context) — looks up matching
                workflows and runs them
  templates.py — pre-built workflows hospitals can clone in one click
  storage.py  — DDB persistence for solace-workflows
"""
