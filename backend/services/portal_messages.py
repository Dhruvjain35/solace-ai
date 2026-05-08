"""Patient portal async messaging — full thread management with auto-draft + tag routing.

Mock provider that mirrors the surface a real MyChart / Healow / NexHealth /
Athena portal exposes. Messages thread per patient. Each inbound message:
  - Gets a tag (refill, result, billing, scheduling, clinical_question, urgent)
  - Triggers an AI draft reply (via inbox_drafts.draft_reply)
  - Appears in the clinician inbox until acknowledged
  - Records read receipts when the patient sees the reply

Tag routing dispatches refill messages to the refill-triage agent, result
messages to result-triage, billing to RCM, scheduling to the appointments
router. Anything tagged 'urgent' bypasses the queue and pages the on-call.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


_THREADS: dict[str, list[dict[str, Any]]] = defaultdict(list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tag(text: str) -> list[str]:
    t = (text or "").lower()
    tags = []
    if any(re.search(p, t) for p in [r"\brefill\b", r"\brefill request\b", r"\bcan i get more of my\b", r"\bout of my\b"]):
        tags.append("refill")
    if any(re.search(p, t) for p in [r"\bresult\b", r"\bmy lab\b", r"\bmy a1c\b", r"\bx[- ]?ray\b", r"\bMRI\b"]):
        tags.append("result")
    if any(re.search(p, t) for p in [r"\bbill\b", r"\binsurance\b", r"\bcopay\b", r"\bcharge\b"]):
        tags.append("billing")
    if any(re.search(p, t) for p in [r"\bappointment\b", r"\breschedule\b", r"\bcancel\b", r"\bschedul"]):
        tags.append("scheduling")
    if any(re.search(p, t) for p in [r"\bchest pain\b", r"\bshort of breath\b", r"\bsuicid", r"\bbleeding\b", r"\b911\b", r"\bpassed out\b"]):
        tags.append("urgent")
    if not tags:
        tags.append("clinical_question")
    return tags


def post_inbound(*, hospital_id: str, patient_id: str, body: str, sender_name: str = "Patient") -> dict[str, Any]:
    msg_id = str(uuid.uuid4())
    msg = {
        "id": msg_id,
        "thread_key": f"{hospital_id}:{patient_id}",
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "direction": "inbound",
        "sender_name": sender_name,
        "body": body,
        "tags": _tag(body),
        "created_at": _now(),
        "read_by_clinician_at": None,
        "read_by_patient_at": None,
        "ai_draft": None,
        "ai_draft_status": None,  # pending | accepted | edited | rejected
        "outbound_reply": None,
        "outbound_at": None,
        "routing": _route_for_tags(_tag(body)),
    }
    _THREADS[msg["thread_key"]].append(msg)
    return msg


def _route_for_tags(tags: list[str]) -> str:
    if "urgent" in tags:
        return "page_on_call"
    if "refill" in tags:
        return "refill_triage"
    if "result" in tags:
        return "result_triage"
    if "billing" in tags:
        return "rcm"
    if "scheduling" in tags:
        return "appointments"
    return "clinical_inbox"


def attach_ai_draft(message_id: str, draft: str) -> dict[str, Any] | None:
    for msgs in _THREADS.values():
        for m in msgs:
            if m["id"] == message_id:
                m["ai_draft"] = draft
                m["ai_draft_status"] = "pending"
                return m
    return None


def respond(message_id: str, *, clinician_id: str, body: str, ai_draft_status: str = "edited") -> dict[str, Any] | None:
    for msgs in _THREADS.values():
        for m in msgs:
            if m["id"] == message_id:
                m["outbound_reply"] = body
                m["outbound_at"] = _now()
                m["ai_draft_status"] = ai_draft_status
                m["read_by_clinician_at"] = m["read_by_clinician_at"] or _now()
                # Append outbound as its own message for thread display
                reply_msg = {
                    "id": str(uuid.uuid4()),
                    "thread_key": m["thread_key"],
                    "hospital_id": m["hospital_id"],
                    "patient_id": m["patient_id"],
                    "direction": "outbound",
                    "sender_name": clinician_id,
                    "body": body,
                    "tags": [],
                    "created_at": m["outbound_at"],
                    "read_by_patient_at": None,
                    "in_reply_to": message_id,
                }
                _THREADS[m["thread_key"]].append(reply_msg)
                return reply_msg
    return None


def list_threads(hospital_id: str | None = None, *, only_unread: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, msgs in _THREADS.items():
        h, pid = key.split(":", 1)
        if hospital_id and h != hospital_id:
            continue
        unread = sum(1 for m in msgs if m["direction"] == "inbound" and not m.get("read_by_clinician_at"))
        if only_unread and unread == 0:
            continue
        out.append({
            "thread_key": key,
            "hospital_id": h,
            "patient_id": pid,
            "message_count": len(msgs),
            "unread_count": unread,
            "last_message_at": msgs[-1]["created_at"] if msgs else None,
        })
    out.sort(key=lambda x: x["last_message_at"] or "", reverse=True)
    return out


def get_thread(thread_key: str) -> list[dict[str, Any]]:
    return list(_THREADS.get(thread_key, []))


def mark_read(thread_key: str) -> int:
    n = 0
    for m in _THREADS.get(thread_key, []):
        if m["direction"] == "inbound" and not m.get("read_by_clinician_at"):
            m["read_by_clinician_at"] = _now()
            n += 1
    return n
