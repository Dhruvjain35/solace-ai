"""Public contact / sales inbound — POST /api/contact.

Marketing-surface form (book a demo, sales, security questionnaires, support).
Unauthenticated but rate-limited per identity via lib.quota, mirroring the
public request-to-join endpoint in routers/onboarding.py.

Spam posture:
  - Honeypot: the form ships a hidden "website" field. Humans never fill it;
    bots do. A non-empty honeypot returns the normal {"ok": true} envelope
    WITHOUT storing or notifying, so the bot learns nothing.
  - Quota: "contact.submit" (10/hour per IP+UA identity) + blocklist.

Storage follows the db/storage.py local/aws split (in-memory dict locally,
DDB `solace-contact-requests` in aws mode). When settings.contact_notify_email
is configured, each stored submission is forwarded via services/email.py
(console provider in local mode — never needs a mailbox on a laptop).
"""
from __future__ import annotations

import html
import logging
import re
import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator
from typing import Literal

from db import storage
from lib import audit as _audit, blocklist, quota
from lib.config import settings
from services import email as email_service

log = logging.getLogger(__name__)

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ContactBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str
    organization: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    topic: Literal["demo", "sales", "security", "support", "other"] = "demo"
    message: str = Field(min_length=1, max_length=4000)
    # Honeypot — hidden in the UI. Humans leave it empty.
    website: str | None = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("enter a valid email address")
        return v


@router.post("/api/contact")
def submit_contact(body: ContactBody, request: Request = None) -> dict:
    """Accept a contact/sales inquiry. Public + rate-limited. Returns {ok, id}."""
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "contact.submit", source_ip=source_ip)

    contact_id = f"ct-{uuid.uuid4().hex[:16]}"

    # Honeypot tripped: answer exactly like a success, but store nothing and
    # notify no one. The response shape is indistinguishable from the real one.
    if (body.website or "").strip():
        _audit.record(
            clinician_id=None, clinician_name=None, action="contact.honeypot_dropped",
            source_ip=source_ip, status_code=200, extra={"identity": identity},
        )
        return {"ok": True, "id": contact_id}

    record = {
        "contact_id": contact_id,
        "name": body.name.strip(),
        "email": body.email,
        "organization": (body.organization or "").strip(),
        "role": (body.role or "").strip(),
        "topic": body.topic,
        "message": body.message.strip(),
        "status": "new",
        "created_at": storage._now_iso(),
    }
    storage.put_contact_request(record)

    if settings.contact_notify_email:
        safe = {k: html.escape(str(record.get(k, ""))) for k in
                ("name", "email", "organization", "role", "topic", "message")}
        email_service.send_email(
            to=settings.contact_notify_email,
            subject=f"[Solace contact] {record['topic']} — {record['name']}",
            html=(
                f"<p><strong>{safe['name']}</strong> ({safe['email']})"
                f"{' · ' + safe['organization'] if safe['organization'] else ''}"
                f"{' · ' + safe['role'] if safe['role'] else ''}</p>"
                f"<p>Topic: {safe['topic']}</p>"
                f"<p style=\"white-space:pre-wrap\">{safe['message']}</p>"
                f"<p style=\"color:#94a3b8;font-size:12px\">id {contact_id}</p>"
            ),
            text=(
                f"{record['name']} ({record['email']})\n"
                f"Organization: {record['organization'] or '-'}\n"
                f"Role: {record['role'] or '-'}\nTopic: {record['topic']}\n\n"
                f"{record['message']}\n\nid {contact_id}"
            ),
        )

    _audit.record(
        clinician_id=None, clinician_name=None, action="contact.submitted",
        source_ip=source_ip, status_code=200,
        extra={"contact_id": contact_id, "topic": record["topic"]},
    )
    return {"ok": True, "id": contact_id}
