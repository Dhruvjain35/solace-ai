"""Claude tool definitions + dispatch for the voice agent.

Each turn we send the conversation history to Claude with these tools available.
Claude either replies with text (we speak it) or invokes a tool (we run it,
feed the result back, and ask Claude for the spoken response).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from db import storage
from lib import claude
from services import triage as _triage_service
from services.voice_agent.prompts import (
    EMERGENCY_KEYWORDS,
    EMERGENCY_RESPONSE,
    SYSTEM_PROMPT,
    TRANSFER_PROMPT,
)

log = logging.getLogger(__name__)


# Tool schemas — Claude decides when to invoke. Keep names + descriptions terse;
# Claude reads them every turn and verbose schemas inflate token cost.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "triage_symptoms",
        "description": "Run an ESI triage on the caller's described symptoms. Use when caller asks 'should I come in', 'is this serious', or describes any acute symptom.",
        "input_schema": {
            "type": "object",
            "properties": {
                "complaint": {"type": "string", "description": "Caller's chief complaint, paraphrased in clinical-light language."},
                "age": {"type": "integer", "description": "Caller's age if shared, else 0."},
                "duration": {"type": "string", "description": "How long, if shared. Empty if unknown."},
            },
            "required": ["complaint"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book a new appointment for the caller. Only invoke after caller confirms the slot. Use answer_faq first if they ask about availability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "callback_phone": {"type": "string", "description": "Phone to confirm via SMS."},
                "reason": {"type": "string", "description": "Short reason for the visit."},
                "preferred_window": {"type": "string", "description": "e.g. 'this week morning', 'next Tuesday afternoon'."},
            },
            "required": ["patient_name", "reason"],
        },
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel an existing appointment by confirmation code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confirmation_code": {"type": "string"},
            },
            "required": ["confirmation_code"],
        },
    },
    {
        "name": "answer_faq",
        "description": "Look up a hospital FAQ (hours, address, parking, billing, what to bring). Returns a paragraph the agent paraphrases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "transfer_to_human",
        "description": "Escalate to a real person at the hospital. Use when the caller asks for it, when the agent is stuck after 2 turns, or when the request is outside scope.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "escalate_911",
        "description": "True medical emergency — chest pain, stroke, can't breathe, heavy bleeding, unconscious, suicidal. Tells the caller to dial 911 and immediately tries to transfer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symptom": {"type": "string"},
            },
            "required": ["symptom"],
        },
    },
]


# --- Dispatch ------------------------------------------------------------------------


def dispatch(tool_name: str, tool_input: dict[str, Any], call_ctx: dict[str, Any]) -> dict[str, Any]:
    """Run the tool. Returns a dict with `say` (what the agent should speak) +
    optional `escalate` flag + side-effect metadata for persistence."""
    if tool_name == "triage_symptoms":
        return _do_triage(tool_input, call_ctx)
    if tool_name == "book_appointment":
        return _do_book(tool_input, call_ctx)
    if tool_name == "cancel_appointment":
        return _do_cancel(tool_input, call_ctx)
    if tool_name == "answer_faq":
        return _do_faq(tool_input, call_ctx)
    if tool_name == "transfer_to_human":
        return {"say": TRANSFER_PROMPT, "escalate": "human", "reason": tool_input.get("reason", "")}
    if tool_name == "escalate_911":
        return {"say": EMERGENCY_RESPONSE, "escalate": "911", "symptom": tool_input.get("symptom", "")}
    return {"say": "Sorry, I'm not sure I can help with that.", "tool_unknown": tool_name}


def _do_triage(tool_input: dict[str, Any], call_ctx: dict[str, Any]) -> dict[str, Any]:
    complaint = (tool_input.get("complaint") or "").strip()
    age = int(tool_input.get("age") or 0) or None
    duration = (tool_input.get("duration") or "").strip()
    if not complaint:
        return {"say": "Could you describe what's happening?"}
    transcript = f"{complaint}. {duration}".strip().rstrip(".")
    info = {"age": age} if age else None
    try:
        result = _triage_service.predict(transcript, photo_analysis={}, medical_info=info)
        esi = result.esi_level
    except Exception:
        log.exception("voice triage failed")
        return {"say": "I want to be careful here — let me transfer you to a nurse who can help.", "escalate": "human"}

    if esi <= 2:
        say = (
            f"Based on what you're describing, this needs attention right away. "
            f"Please come into the ER or call nine one one. "
            f"Are you safe to come in now?"
        )
    elif esi == 3:
        say = (
            f"That sounds like something we should see today. "
            f"Would you like me to book the next available slot, or do you want to come straight in?"
        )
    else:
        say = (
            f"That's likely manageable from home for now, but I can book you a visit "
            f"or send self-care guidance. Which would you prefer?"
        )
    return {"say": say, "esi_level": esi, "complaint": complaint}


def _do_book(tool_input: dict[str, Any], call_ctx: dict[str, Any]) -> dict[str, Any]:
    name = (tool_input.get("patient_name") or "").strip()
    phone = (tool_input.get("callback_phone") or call_ctx.get("caller_phone") or "").strip()
    reason = (tool_input.get("reason") or "").strip()
    window = (tool_input.get("preferred_window") or "soon").strip()
    if not name or not reason:
        return {"say": "Could you give me your full name and the reason for the visit?"}

    confirmation = _generate_confirmation_code()
    appt = {
        "appointment_id": str(uuid.uuid4()),
        "hospital_id": call_ctx.get("hospital_id", "demo"),
        "patient_name": name,
        "patient_phone": phone,
        "reason_short": reason,
        "preferred_window": window,
        "status": "booked",
        "confirmation_code": confirmation,
        "created_via": "voice",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    try:
        storage.add_appointment(appt)
    except Exception:
        log.exception("appointment write failed")
    spelled = " ".join(list(confirmation))
    return {
        "say": f"Booked. Your confirmation code is {spelled}. We'll text the time when it's confirmed. Anything else?",
        "appointment": appt,
    }


def _do_cancel(tool_input: dict[str, Any], call_ctx: dict[str, Any]) -> dict[str, Any]:
    code = (tool_input.get("confirmation_code") or "").strip().upper()
    if not code:
        return {"say": "What's the confirmation code?"}
    try:
        ok = storage.cancel_appointment(code, hospital_id=call_ctx.get("hospital_id", "demo"))
    except Exception:
        log.exception("appointment cancel failed")
        ok = False
    if ok:
        return {"say": "Cancelled. Anything else?"}
    return {"say": "I couldn't find that code. Want me to transfer you to a person?"}


def _do_faq(tool_input: dict[str, Any], call_ctx: dict[str, Any]) -> dict[str, Any]:
    question = (tool_input.get("question") or "").strip().lower()
    if not question:
        return {"say": "What would you like to know?"}

    # Cheap built-in FAQ. Production swaps this for RAG over a per-hospital
    # knowledge base — ~50 lines, plug in via faq_rag.py later.
    facts = {
        "hours": "We're open twenty-four seven for emergencies. Clinic hours are seven AM to seven PM weekdays, nine to three Saturdays.",
        "address": "Twelve forty-eight Front Street. There's signage from the freeway exit.",
        "parking": "Free parking in the south garage. Bring your ticket inside for validation.",
        "billing": "For billing, please call our office at five-five-five, eight one zero zero, weekdays nine to five.",
        "bring": "Bring a photo ID, your insurance card, a list of current medications, and any recent test results if you have them.",
        "wait": "Current ER wait is around forty minutes for non-urgent cases. Severe cases are seen first.",
    }
    response = None
    for key, val in facts.items():
        if key in question:
            response = val
            break
    if response is None:
        # Fall back to a transfer rather than guessing.
        return {
            "say": "Let me get someone who can answer that. Hold on.",
            "escalate": "human",
            "reason": f"FAQ miss: {question[:60]}",
        }
    return {"say": response, "faq_key": [k for k in facts if k in question][:1]}


def _generate_confirmation_code() -> str:
    # 6-letter alphanumeric, no I/O/0/1 (phone-spelling friendly).
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


# --- Claude turn loop ----------------------------------------------------------------


def run_turn(
    *,
    history: list[dict[str, Any]],
    user_text: str,
    call_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Run one agent turn. Returns:
    - say: text the agent should speak
    - tool: name of tool invoked, if any
    - tool_result: result dict from dispatch, if any
    - escalate: "human" | "911" | None
    - history: updated message history for next turn
    """
    # Hard-coded emergency trip — bypass Claude on red-flag phrases for speed + reliability.
    lowered = user_text.lower()
    if any(kw in lowered for kw in EMERGENCY_KEYWORDS):
        result = dispatch("escalate_911", {"symptom": user_text}, call_ctx)
        return {
            "say": result["say"],
            "tool": "escalate_911",
            "tool_result": result,
            "escalate": "911",
            "history": history + [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": result["say"]},
            ],
        }

    hospital = storage.get_hospital(call_ctx.get("hospital_id", "demo")) or {}
    system = SYSTEM_PROMPT.format(hospital_name=hospital.get("name", "the hospital"))

    new_history = history + [{"role": "user", "content": user_text}]
    try:
        resp = claude.messages_create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            system=system,
            messages=new_history,
            purpose="voice_agent",
            tools=TOOLS,
        )
    except Exception:
        log.exception("voice claude failed")
        return {
            "say": "I'm having trouble connecting. Let me get you a person.",
            "escalate": "human",
            "tool": None,
            "tool_result": None,
            "history": new_history,
        }

    say_parts: list[str] = []
    tool_calls: list[tuple[str, dict[str, Any], str]] = []  # (name, input, tool_use_id)
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text" and getattr(block, "text", "").strip():
            say_parts.append(block.text)
        elif btype == "tool_use":
            tool_calls.append((block.name, block.input or {}, block.id))

    if not tool_calls:
        text = " ".join(say_parts).strip() or "Could you say that again?"
        return {
            "say": text,
            "tool": None,
            "tool_result": None,
            "escalate": None,
            "history": new_history + [{"role": "assistant", "content": text}],
        }

    # Single tool call (the most common case). If Claude emitted multiple, take
    # only the first — phone calls don't benefit from parallel tool fanout.
    tool_name, tool_input, tool_use_id = tool_calls[0]
    tool_result = dispatch(tool_name, tool_input, call_ctx)
    say = tool_result.get("say", "")

    # Persist Claude's tool-use turn AND our tool-result turn so the next round
    # sees the full conversation. This lets Claude follow up coherently.
    assistant_blocks: list[dict[str, Any]] = []
    if say_parts:
        assistant_blocks.append({"type": "text", "text": " ".join(say_parts).strip()})
    assistant_blocks.append({
        "type": "tool_use", "id": tool_use_id, "name": tool_name, "input": tool_input,
    })
    user_tool_result_blocks = [{
        "type": "tool_result", "tool_use_id": tool_use_id, "content": say or "(no result)",
    }]
    return {
        "say": say,
        "tool": tool_name,
        "tool_result": tool_result,
        "escalate": tool_result.get("escalate"),
        "history": new_history + [
            {"role": "assistant", "content": assistant_blocks},
            {"role": "user", "content": user_tool_result_blocks},
        ],
    }


