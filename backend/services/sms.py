"""Outbound SMS — AWS SNS by default, Twilio when its creds are configured.

Used by:
  - Clinician dashboard: "Text discharge plan to patient" button
  - Voice agent: appointment confirmations
  - Patient result page: "text me my care instructions" self-serve

Always returns a structured dict so callers can render a friendly state when
Twilio creds aren't configured (e.g. demo deployment without a Twilio account).
Never raises — the SMS is a nice-to-have, not a blocker.

Config note: Twilio credentials are read from the process environment
(``TWILIO_ACCOUNT_SID`` / ``TWILIO_AUTH_TOKEN`` / ``TWILIO_SMS_FROM_NUMBER``),
matching ``routers/voice.py``'s pattern. ``lib.config.Settings`` does not
declare ``twilio_*`` fields, so reading ``settings.twilio_*`` raised
``AttributeError`` — that latent bug is fixed here.

PHI note: a phone number is a HIPAA Safe Harbor identifier (§164.514). It is
never written to logs in plaintext — every log line hashes it via the shared
HMAC salt (the same ``lib.intake_nonce._hmac_key`` pattern ``lib.quota``
uses), and only the last-4 digits are kept as a human-debuggable suffix.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re

import httpx

log = logging.getLogger(__name__)

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

# Inbound keywords that constitute a TCPA opt-out / opt-in (Twilio Advanced
# Opt-Out mirrors this list; we honor it locally too for non-Twilio paths).
_OPT_OUT_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
_OPT_IN_KEYWORDS = {"start", "yes", "unstop"}
_HELP_KEYWORDS = {"help", "info"}

# Twilio message statuses that mean the carrier could not deliver the SMS.
_FAILED_STATUSES = {"failed", "undelivered"}
_DELIVERED_STATUSES = {"delivered"}
_PENDING_STATUSES = {"queued", "accepted", "sending", "sent", "scheduled"}


# --- config -----------------------------------------------------------------


def _twilio_account_sid() -> str:
    return os.environ.get("TWILIO_ACCOUNT_SID", "")


def _twilio_auth_token() -> str:
    return os.environ.get("TWILIO_AUTH_TOKEN", "")


def _twilio_from_number() -> str:
    # Accept either an explicit name or the generic voice "from" number so a
    # deployment that already set TWILIO_FROM_NUMBER for voice works for SMS.
    return os.environ.get("TWILIO_SMS_FROM_NUMBER") or os.environ.get("TWILIO_FROM_NUMBER", "")


def _twilio_configured() -> bool:
    return bool(_twilio_account_sid() and _twilio_auth_token() and _twilio_from_number())


def _sns_enabled() -> bool:
    """AWS SNS is the no-external-account SMS path (used when Twilio creds are
    absent). Enabled by default whenever we're running inside AWS, or forced via
    ``SMS_PROVIDER=sns``. Set ``SMS_PROVIDER=twilio`` to disable the SNS path.

    SNS needs no "from number": messages send from AWS's shared pool (or the
    ``SNS_SMS_SENDER_ID`` if set). Note: while the account is in the SNS SMS
    sandbox, delivery only succeeds to verified destination numbers.
    """
    provider = os.environ.get("SMS_PROVIDER", "").strip().lower()
    if provider == "sns":
        return True
    if provider == "twilio":
        return False
    # Auto: on inside AWS Lambda / when a region is configured.
    return bool(os.environ.get("AWS_REGION") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _provider() -> str:
    """Resolve the active SMS backend: 'twilio' | 'sns' | 'none'."""
    if _twilio_configured():
        return "twilio"
    if _sns_enabled():
        return "sns"
    return "none"


def is_configured() -> bool:
    return _provider() != "none"


# --- PHI-safe logging --------------------------------------------------------


def hash_phone(raw: str | None) -> str:
    """HMAC-SHA256 a phone number for log/audit use — never log it plaintext.

    Reuses ``lib.intake_nonce._hmac_key`` (the clinician-auth JWT signing key,
    already CMK-encrypted in Secrets Manager) as the salt, exactly like
    ``lib.quota.identity_of``. Format: ``last4:hash`` so a human can still
    eyeball-match a number while the rest stays opaque. Falls back to an
    unsalted SHA-256 only if the auth secret is unavailable (local dev).
    """
    phone = (raw or "").strip()
    if not phone:
        return "none"
    last4 = re.sub(r"\D", "", phone)[-4:] or "????"
    try:
        from lib.intake_nonce import _hmac_key  # noqa: PLC0415 — shared salt, avoid import cycle

        digest = hmac.new(_hmac_key(), phone.encode(), hashlib.sha256).hexdigest()
    except Exception:  # noqa: BLE001 — degrade gracefully, still no plaintext
        digest = hashlib.sha256(phone.encode()).hexdigest()
    return f"{last4}:{digest[:16]}"


def normalize_phone(raw: str | None) -> str:
    """Strip everything except digits and a leading +. Accepts US-formatted
    numbers and converts (512) 555-0177 -> +15125550177."""
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


# --- TCPA opt-out ------------------------------------------------------------


def classify_inbound(body: str | None) -> str:
    """Classify an inbound SMS body as ``opt_out`` | ``opt_in`` | ``help`` |
    ``message``. Used by the Twilio inbound webhook to honor TCPA keywords."""
    word = (body or "").strip().lower()
    # Keep only the first token — carriers send "STOP" but users send "stop please".
    word = word.split()[0] if word else ""
    if word in _OPT_OUT_KEYWORDS:
        return "opt_out"
    if word in _OPT_IN_KEYWORDS:
        return "opt_in"
    if word in _HELP_KEYWORDS:
        return "help"
    return "message"


def is_opted_out(phone: str | None) -> bool:
    """Whether a number has texted STOP.

    Twilio's Advanced Opt-Out enforces this at the carrier edge automatically
    (a send to an opted-out number returns error 21610). This local check lets
    callers short-circuit before the API call. The persistent opt-out store
    lives in ``db.storage``; the router layer owns that lookup, so this base
    implementation is intentionally conservative and returns False — callers
    that have a store should pass results through ``send(..., opted_out=...)``.
    """
    return False


# --- multi-language reminder templates --------------------------------------

# Footer carries the HIPAA notice + the TCPA-required STOP/HELP affordance.
_FOOTERS: dict[str, str] = {
    "en": (
        "\n\nReply STOP to opt out, HELP for help. Contains protected health "
        "information from Solace on behalf of your care team. Do not share."
    ),
    "es": (
        "\n\nResponda STOP para cancelar, HELP para ayuda. Contiene informacion "
        "medica protegida de Solace en nombre de su equipo de atencion. No la comparta."
    ),
    "zh": (
        "\n\n回复 STOP 取消订阅，回复 HELP "
        "获得帮助。此信息包含来自 Solace "
        "代表您的护理团队的受保护健康"
        "信息。请勿分享。"
    ),
    "vi": (
        "\n\nTra loi STOP de huy, HELP de duoc tro giup. Chua thong tin suc khoe "
        "duoc bao ve tu Solace thay mat nhom cham soc cua ban. Khong chia se."
    ),
}

_DISCHARGE_INTRO: dict[str, str] = {
    "en": "{name}, here's the discharge plan from {hospital}:",
    "es": "{name}, este es el plan de alta de {hospital}:",
    "zh": "{name}，以下是 {hospital} 的出院计划：",
    "vi": "{name}, day la ke hoach xuat vien tu {hospital}:",
}

_DISCHARGE_RETURN: dict[str, str] = {
    "en": "\nCome back if: {when}",
    "es": "\nRegrese si: {when}",
    "zh": "\n出现以下情况请返回：{when}",
    "vi": "\nQuay lai neu: {when}",
}

_REMINDER_BODY: dict[str, str] = {
    "en": (
        "{name}, reminder: your visit at {hospital} is {when}. "
        "Confirmation: {code}. Reply CANCEL to reschedule."
    ),
    "es": (
        "{name}, recordatorio: su cita en {hospital} es {when}. "
        "Confirmacion: {code}. Responda CANCEL para reprogramar."
    ),
    "zh": (
        "{name}，提醒：您在 {hospital} 的预约"
        "时间为 {when}。确认码：{code}。"
        "回复 CANCEL 可重新安排。"
    ),
    "vi": (
        "{name}, nhac nho: cuoc hen cua ban tai {hospital} la {when}. "
        "Ma xac nhan: {code}. Tra loi CANCEL de doi lich."
    ),
}

_DEFAULT_GREETING: dict[str, str] = {"en": "Hi", "es": "Hola", "zh": "您好", "vi": "Xin chao"}


def _lang(language: str | None) -> str:
    """Resolve a language tag to a supported template key; default English."""
    code = (language or "en").strip().lower().split("-")[0]
    return code if code in _FOOTERS else "en"


def hipaa_footer(language: str | None = "en") -> str:
    """The HIPAA + TCPA footer in the patient's language."""
    return _FOOTERS[_lang(language)]


# --- send --------------------------------------------------------------------


def send(
    to: str,
    body: str,
    *,
    append_hipaa_footer: bool = True,
    language: str | None = "en",
    opted_out: bool = False,
) -> dict:
    """Send one SMS via the active provider (Twilio if creds are set, else AWS
    SNS). Returns:
      {success: bool, sid?: str, status?: str, reason?: str, message?: str}
    Reasons: "not_configured" | "invalid_number" | "twilio_error"
             | "sns_error" | "empty_body" | "opted_out"

    ``language`` selects the footer language. ``opted_out`` lets a caller that
    consulted the opt-out store short-circuit before hitting Twilio (TCPA).
    The ``to`` number is never logged in plaintext — only its HMAC hash.
    """
    if not is_configured():
        return {"success": False, "reason": "not_configured",
                "message": "Twilio SMS not configured for this hospital."}
    if not body or not body.strip():
        return {"success": False, "reason": "empty_body"}

    e164 = normalize_phone(to)
    if not e164 or not _E164_RE.match(e164):
        # Do not echo the raw number — log the hash, return a generic message.
        log.info("sms send rejected: invalid number %s", hash_phone(to))
        return {"success": False, "reason": "invalid_number",
                "message": "The phone number provided is not valid."}

    if opted_out or is_opted_out(e164):
        log.info("sms send skipped: %s has opted out (TCPA)", hash_phone(e164))
        return {"success": False, "reason": "opted_out",
                "message": "This number has opted out of text messages."}

    final_body = body.strip()
    if append_hipaa_footer:
        final_body = final_body + hipaa_footer(language)

    if _provider() == "sns":
        return _send_via_sns(e164, final_body)
    return _send_via_twilio(e164, final_body)


def _send_via_sns(e164: str, final_body: str) -> dict:
    """Send via AWS SNS — no external account or "from" number required.

    Sends as a Transactional message (carrier-prioritized, no promotional
    throttling) which suits clinical/appointment messaging. The destination
    number is never logged in plaintext — only its HMAC hash.
    """
    try:
        import boto3  # noqa: PLC0415 — optional dep, only needed on the SNS path

        region = os.environ.get("AWS_REGION", "us-east-1")
        sns = boto3.client("sns", region_name=region)
        attrs = {
            "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
        }
        sender_id = os.environ.get("SNS_SMS_SENDER_ID")
        if sender_id:
            attrs["AWS.SNS.SMS.SenderID"] = {"DataType": "String", "StringValue": sender_id}
        resp = sns.publish(PhoneNumber=e164, Message=final_body, MessageAttributes=attrs)
        message_id = resp.get("MessageId", "")
        log.info("sns sms accepted for %s id=%s", hash_phone(e164), message_id or "unknown")
        return {
            "success": True,
            "sid": message_id,
            "status": "queued",
            "to_hash": hash_phone(e164),
        }
    except Exception as e:  # noqa: BLE001 — never raise; SMS is a nice-to-have
        # Exception text can include the number — log only the type.
        log.warning("sns sms exception for %s: %s", hash_phone(e164), type(e).__name__)
        return {"success": False, "reason": "sns_error",
                "message": "The text message could not be sent."}


def _send_via_twilio(e164: str, final_body: str) -> dict:
    account_sid = _twilio_account_sid()
    auth_token = _twilio_auth_token()
    from_number = _twilio_from_number()

    # Twilio outbound SMS REST API — basic-auth with account SID + auth token.
    auth_b64 = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                url,
                data={"To": e164, "From": from_number, "Body": final_body},
                headers={"Authorization": f"Basic {auth_b64}"},
            )
            if resp.status_code >= 400:
                # resp.text may contain the To number — never log it raw.
                log.warning("twilio sms %d for %s", resp.status_code, hash_phone(e164))
                return {"success": False, "reason": "twilio_error",
                        "message": "The text message could not be sent."}
            payload = resp.json()
            status = str(payload.get("status", "")).lower()
            log.info("twilio sms accepted for %s status=%s", hash_phone(e164), status or "unknown")
            return {
                "success": True,
                "sid": payload.get("sid", ""),
                "status": status or "queued",
                "to_hash": hash_phone(e164),
            }
    except Exception as e:  # noqa: BLE001
        # Exception text can include the URL/number — log only the type.
        log.warning("twilio sms exception for %s: %s", hash_phone(e164), type(e).__name__)
        return {"success": False, "reason": "twilio_error",
                "message": "The text message could not be sent."}


# --- delivery-status webhook handling ---------------------------------------


def interpret_delivery_status(status: str | None) -> dict:
    """Map a Twilio status-callback ``MessageStatus`` to a structured outcome.

    Twilio POSTs a status callback as the message progresses
    (queued -> sent -> delivered, or -> failed/undelivered). The router that
    receives the webhook calls this to decide what to record. Returns:
      {state: "delivered"|"pending"|"failed", terminal: bool, status: str}
    """
    s = (status or "").strip().lower()
    if s in _DELIVERED_STATUSES:
        return {"state": "delivered", "terminal": True, "status": s}
    if s in _FAILED_STATUSES:
        return {"state": "failed", "terminal": True, "status": s}
    if s in _PENDING_STATUSES:
        return {"state": "pending", "terminal": False, "status": s}
    return {"state": "pending", "terminal": False, "status": s or "unknown"}


def handle_status_callback(form: dict[str, str]) -> dict:
    """Process a Twilio delivery status webhook payload (form-encoded).

    Expects Twilio's standard fields: ``MessageSid``, ``MessageStatus``,
    ``To``, and (on failure) ``ErrorCode``. Returns a PHI-safe summary the
    router can audit/persist — the ``To`` number is hashed, never stored raw.
    """
    sid = form.get("MessageSid") or form.get("SmsSid") or ""
    outcome = interpret_delivery_status(form.get("MessageStatus"))
    summary = {
        "sid": sid,
        "to_hash": hash_phone(form.get("To")),
        **outcome,
    }
    error_code = form.get("ErrorCode")
    if error_code:
        summary["error_code"] = error_code
        # Twilio 21610 == message to an opted-out number.
        if str(error_code) == "21610":
            summary["state"] = "opted_out"
    if outcome["state"] == "failed":
        log.warning("twilio delivery failed sid=%s to=%s code=%s",
                    sid, summary["to_hash"], error_code or "")
    else:
        log.info("twilio delivery sid=%s to=%s state=%s",
                 sid, summary["to_hash"], outcome["state"])
    return summary


def handle_inbound_message(form: dict[str, str]) -> dict:
    """Process a Twilio inbound SMS webhook (a patient texting the number).

    Classifies TCPA keywords (STOP/START/HELP) so the router can update the
    opt-out store. Returns a PHI-safe summary with the sender hashed.
    """
    from_number = form.get("From") or ""
    kind = classify_inbound(form.get("Body"))
    summary = {"from_hash": hash_phone(from_number), "kind": kind, "sid": form.get("MessageSid", "")}
    if kind == "opt_out":
        log.info("sms inbound opt-out (STOP) from %s", summary["from_hash"])
    elif kind == "opt_in":
        log.info("sms inbound opt-in (START) from %s", summary["from_hash"])
    return summary


# --- templates ---------------------------------------------------------------


def render_discharge_template(
    *, patient_name: str, hospital_name: str,
    care_instructions: list[str], when_to_return: str,
    language: str | None = "en",
) -> str:
    lang = _lang(language)
    first = patient_name.split(" ")[0] if patient_name else _DEFAULT_GREETING[lang]
    lines = [_DISCHARGE_INTRO[lang].format(name=first, hospital=hospital_name)]
    for i, step in enumerate(care_instructions[:4], 1):
        lines.append(f"{i}. {step}")
    if when_to_return:
        lines.append(_DISCHARGE_RETURN[lang].format(when=when_to_return))
    return "\n".join(lines)


def render_appointment_reminder(
    *, patient_name: str, hospital_name: str,
    when_human: str, confirmation_code: str,
    language: str | None = "en",
) -> str:
    lang = _lang(language)
    first = patient_name.split(" ")[0] if patient_name else _DEFAULT_GREETING[lang]
    return _REMINDER_BODY[lang].format(
        name=first, hospital=hospital_name, when=when_human, code=confirmation_code,
    )
