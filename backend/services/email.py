"""Transactional email — provider-agnostic sender.

Two providers behind one interface:
  - "ses"     — Amazon SES `send_email`. Production path. The sender identity
                (settings.email_from) must be a verified SES identity, and the
                account must be out of the SES sandbox to reach arbitrary
                recipients. Until then SES only delivers to verified addresses.
  - "console" — logs the message (and the magic link) instead of sending.
                Used in local mode and any time SES is not yet provisioned, so
                the onboarding flow is fully exercisable without a mailbox.

`solace_mode == "local"` always forces the console provider regardless of the
configured provider, so laptop dev never needs AWS credentials.

The magic-link sender returns a small result dict. When settings.email_dev_echo
is true (local/sandbox only — NEVER production) the dict carries `dev_link` so
callers can surface the link directly in an API response for testing.
"""
from __future__ import annotations

import logging

from lib.config import settings

log = logging.getLogger(__name__)


def _active_provider() -> str:
    """Console always wins in local mode; otherwise honor the configured provider."""
    if settings.solace_mode == "local":
        return "console"
    return settings.email_provider


def send_email(*, to: str, subject: str, html: str, text: str) -> dict:
    """Send one transactional email. Returns {"provider", "delivered", ...}.

    Never raises on a delivery failure — auth flows degrade to "check your
    inbox" UX rather than 500ing. The caller decides whether the magic link
    was persisted (it was) independently of whether the email left the building.
    """
    provider = _active_provider()

    if provider == "console":
        log.info("[email:console] to=%s subject=%r\n%s", to, subject, text)
        return {"provider": "console", "delivered": True}

    # provider == "ses"
    try:
        import boto3  # noqa: PLC0415

        ses = boto3.client("ses", region_name=settings.aws_region)
        resp = ses.send_email(
            Source=settings.email_from,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html, "Charset": "UTF-8"},
                    "Text": {"Data": text, "Charset": "UTF-8"},
                },
            },
        )
        return {"provider": "ses", "delivered": True, "message_id": resp.get("MessageId")}
    except Exception as e:  # noqa: BLE001
        # Sandbox rejections (unverified recipient), throttling, missing identity
        # — log and report not-delivered. The link still lives in DDB; the user
        # can retry. Surfacing failure honestly beats a silent black hole.
        log.warning("[email:ses] delivery failed to=%s: %s", to, e)
        return {"provider": "ses", "delivered": False, "error": str(e)}


def send_magic_link(
    *,
    to: str,
    link: str,
    hospital_name: str,
    purpose: str = "login",
) -> dict:
    """Compose and send a sign-in / invite magic link. `purpose` ∈ {login, invite}."""
    if purpose == "invite":
        subject = f"You're invited to {hospital_name} on Solace"
        lead = (
            f"You've been invited to join {hospital_name}'s clinical workspace on "
            f"Solace. Use the secure link below to set up your account and sign in."
        )
    else:
        subject = f"Your Solace sign-in link for {hospital_name}"
        lead = (
            f"Use the secure link below to sign in to {hospital_name} on Solace. "
            f"It is single-use and expires shortly."
        )

    text = (
        f"{lead}\n\n{link}\n\n"
        f"If you did not request this, you can safely ignore this email."
    )
    html = (
        f'<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
        f'max-width:480px;margin:0 auto;color:#0f172a">'
        f'<h2 style="font-size:18px;margin:0 0 12px">{hospital_name} · Solace</h2>'
        f'<p style="font-size:14px;line-height:1.6;color:#334155">{lead}</p>'
        f'<p style="margin:24px 0"><a href="{link}" '
        f'style="background:#0f766e;color:#fff;text-decoration:none;padding:12px 20px;'
        f'border-radius:8px;font-size:14px;font-weight:600;display:inline-block">'
        f'{"Set up your account" if purpose == "invite" else "Sign in to Solace"}</a></p>'
        f'<p style="font-size:12px;color:#94a3b8">This link is single-use and expires '
        f'shortly. If you did not request it, you can ignore this email.</p>'
        f'</div>'
    )

    result = send_email(to=to, subject=subject, html=html, text=text)
    if settings.email_dev_echo:
        # Local/sandbox only — lets tests and the dev UI follow the link without
        # a real inbox. Gated off in production by config.
        result["dev_link"] = link
    return result
