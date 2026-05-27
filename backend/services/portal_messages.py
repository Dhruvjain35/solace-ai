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


# Urgency from a draft -> SLA in business hours the clinician should reply within.
_URGENCY_SLA_HOURS = {
    "crisis": 0,        # page on-call immediately
    "emergent": 1,
    "same_day": 8,
    "routine": 48,
}


def attach_ai_draft(
    message_id: str,
    draft: str,
    *,
    envelope: dict[str, Any] | None = None,
    urgency: str | None = None,
    red_flags: list[str] | None = None,
    ungrounded_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Attach the inbox_drafts output to an inbound message.

    `draft` keeps the legacy string signature. The optional keyword args carry
    the richer envelope from inbox_drafts.draft_reply so the clinician inbox can
    show urgency, red flags, the one-click-send envelope, and any ungrounded
    claims that must be verified before sending. auto_send is never honored:
    the message always waits for a clinician.
    """
    for msgs in _THREADS.values():
        for m in msgs:
            if m["id"] == message_id:
                m["ai_draft"] = draft
                m["ai_draft_status"] = "pending"
                m["ai_draft_envelope"] = envelope
                m["ai_draft_urgency"] = urgency
                m["ai_draft_red_flags"] = red_flags or []
                m["ai_draft_ungrounded_claims"] = ungrounded_claims or []
                m["reply_sla_hours"] = _URGENCY_SLA_HOURS.get(urgency or "routine", 48)
                # A crisis-urgency inbound is force-routed to the on-call page,
                # even if keyword tagging missed it.
                if urgency == "crisis" and m.get("routing") != "page_on_call":
                    m["routing"] = "page_on_call"
                    if "urgent" not in m.get("tags", []):
                        m.setdefault("tags", []).append("urgent")
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


def inbox_triage_summary(hospital_id: str | None = None) -> dict[str, Any]:
    """Non-PHI worklist summary for the clinician inbox dashboard.

    Counts only — no message bodies, no patient identifiers — so it is safe to
    log or surface in audit trails. Use this to drive the inbox badge and the
    "needs attention" sort order.
    """
    buckets = {"crisis": 0, "emergent": 0, "same_day": 0, "routine": 0, "unassessed": 0}
    routing_counts: dict[str, int] = defaultdict(int)
    needs_review = 0
    ungrounded_pending = 0
    total_unread = 0
    for key, msgs in _THREADS.items():
        h, _pid = key.split(":", 1)
        if hospital_id and h != hospital_id:
            continue
        for m in msgs:
            if m["direction"] != "inbound":
                continue
            if not m.get("read_by_clinician_at"):
                total_unread += 1
            if m.get("ai_draft_status") == "pending":
                needs_review += 1
                u = m.get("ai_draft_urgency")
                buckets[u if u in buckets else "unassessed"] += 1
                routing_counts[m.get("routing", "clinical_inbox")] += 1
                if m.get("ai_draft_ungrounded_claims"):
                    ungrounded_pending += 1
    return {
        "hospital_id": hospital_id,
        "unread_inbound": total_unread,
        "drafts_pending_review": needs_review,
        "drafts_with_ungrounded_claims": ungrounded_pending,
        "urgency_breakdown": buckets,
        "routing_breakdown": dict(routing_counts),
        "generated_at": _now(),
    }
