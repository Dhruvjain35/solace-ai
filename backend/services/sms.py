"""Twilio Programmable Messaging — outbound SMS.

Used by:
  - Clinician dashboard: "Text discharge plan to patient" button
  - Voice agent: appointment confirmations
  - Patient result page: "text me my care instructions" self-serve

Always returns a structured dict so callers can render a friendly state when
Twilio creds aren't configured (e.g. demo deployment without a Twilio account).
Never raises — the SMS is a nice-to-have, not a blocker.
"""
from __future__ import annotations

import base64
import logging
import re

import httpx

from lib.config import settings

log = logging.getLogger(__name__)

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_HIPAA_FOOTER = (
    "\n\nReply STOP to opt out. This message contains protected health information "
    "from Solace on behalf of your care team. Do not share."
)


def is_configured() -> bool:
    return bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_sms_from_number
    )


def normalize_phone(raw: str | None) -> str:
    """Strip everything except digits and a leading +. Accepts US-formatted
    numbers and converts (512) 555-0177 → +15125550177."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return ""  # unknown shape — caller treats as invalid


def send(to: str, body: str, *, append_hipaa_footer: bool = True) -> dict:
    """Send one SMS. Returns:
      {success: bool, sid?: str, reason?: str, message?: str}
    Reasons: "not_configured" | "invalid_number" | "twilio_error" | "empty_body"
    """
    if not is_configured():
        return {"success": False, "reason": "not_configured",
                "message": "Twilio SMS not configured for this hospital."}
    if not body or not body.strip():
        return {"success": False, "reason": "empty_body"}

    e164 = normalize_phone(to)
    if not e164 or not _E164_RE.match(e164):
        return {"success": False, "reason": "invalid_number",
                "message": f"Invalid phone number: {to}"}

    final_body = body.strip()
    if append_hipaa_footer:
        final_body = final_body + _HIPAA_FOOTER

    # Twilio outbound SMS REST API — basic-auth with account SID + auth token.
    auth_b64 = base64.b64encode(
        f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()
    ).decode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                url,
                data={"To": e164, "From": settings.twilio_sms_from_number, "Body": final_body},
                headers={"Authorization": f"Basic {auth_b64}"},
            )
            if resp.status_code >= 400:
                log.warning("twilio sms %d: %s", resp.status_code, resp.text[:200])
                return {"success": False, "reason": "twilio_error",
                        "message": resp.text[:200]}
            payload = resp.json()
            return {"success": True, "sid": payload.get("sid", ""), "to": e164}
    except Exception as e:  # noqa: BLE001
        log.warning("twilio sms exception: %s", e)
        return {"success": False, "reason": "twilio_error", "message": str(e)[:200]}


def render_discharge_template(
    *, patient_name: str, hospital_name: str,
    care_instructions: list[str], when_to_return: str,
) -> str:
    name = patient_name.split(" ")[0] if patient_name else "Hi"
    lines = [f"{name}, here's the discharge plan from {hospital_name}:"]
    for i, step in enumerate(care_instructions[:4], 1):
        lines.append(f"{i}. {step}")
    if when_to_return:
        lines.append(f"\nCome back if: {when_to_return}")
    return "\n".join(lines)


def render_appointment_reminder(
    *, patient_name: str, hospital_name: str,
    when_human: str, confirmation_code: str,
) -> str:
    name = patient_name.split(" ")[0] if patient_name else "Hi"
    return (
        f"{name}, reminder: your visit at {hospital_name} is {when_human}. "
        f"Confirmation: {confirmation_code}. Reply CANCEL to reschedule."
    )
