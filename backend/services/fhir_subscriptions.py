"""FHIR Subscriptions — create a Subscription resource + ingest notifications.

Two halves of the FHIR Subscription framework:

  * **create** — build a ``Subscription`` resource (R4 ``rest-hook`` channel) that
    asks a hospital's FHIR server to POST a notification to a Solace webhook URL
    whenever resources matching a criteria string change, then write it through
    ``services.ehr_gateway.write_resource`` (so vendor routing, retry, dry-run,
    and the audit hook are all reused — never duplicated here).

  * **ingest** — parse an inbound notification. R4 servers POST either the
    *changed resource itself* or an empty ``id-only`` ping; the R4B / R5
    ``Subscriptions Backport`` IG POSTs a ``Bundle`` of type
    ``subscription-notification`` whose first entry is a ``SubscriptionStatus``.
    :func:`parse_notification` normalizes both into a list of resource
    references plus any inline resources.

Constitution:
  * ARCH-002 — service layer: imports ``lib.*`` and ``services.ehr_gateway`` only,
    never ``boto3``. Subscription registration state is persisted by the router
    through the db layer.
  * SEC-005 / COMP-001 — any inline free-text in an inbound notification that is
    destined for an AI provider is scanned via ``content_guard.scan()`` (delegated
    to ``services.fhir_bulk_export.scan_resource_freetext`` so the logic lives in
    one place). Unsafe content is dropped from the AI path.
  * No PHI in logs — only resource types, counts, and subscription ids.

The webhook receiver endpoint and the persistence of subscription registrations
live in ``routers/fhir_subscriptions.py`` (router → service → db layering).
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from services import ehr_gateway, fhir_bulk_export

log = logging.getLogger(__name__)

# R4 Subscription channel type for an HTTP webhook.
_REST_HOOK = "rest-hook"
_PAYLOAD_FULL = "application/fhir+json"

# Backport / R5 notification Bundle type.
_NOTIFICATION_BUNDLE_TYPES = {"subscription-notification", "history"}


def build_subscription(
    *,
    criteria: str,
    endpoint: str,
    payload_mime: str = _PAYLOAD_FULL,
    reason: str = "Solace clinical triage change notification",
    secret_header: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Build an R4 ``Subscription`` resource using the ``rest-hook`` channel.

    ``criteria`` is the FHIR search string the server watches, e.g.
    ``"Encounter?status=in-progress"`` or ``"Observation?category=vital-signs"``.
    ``endpoint`` is Solace's webhook URL. ``secret_header`` (when supplied) is
    sent back to us as an ``Authorization``-style header so the receiver can
    verify the notification originated from a subscription we created — it is a
    bearer-style shared secret, never a patient identifier.

    The resource is created ``requested``; the server activates it (``active``)
    once it accepts the channel.
    """
    if not criteria or not endpoint:
        raise ValueError("criteria and endpoint are required to build a Subscription")
    channel: dict[str, Any] = {
        "type": _REST_HOOK,
        "endpoint": endpoint,
        "payload": payload_mime,
    }
    if secret_header:
        # R4 channel.header carries extra HTTP headers the server echoes back.
        channel["header"] = [f"X-Solace-Subscription-Secret: {secret_header}"]
    resource: dict[str, Any] = {
        "resourceType": "Subscription",
        "status": "requested",
        "reason": reason,
        "criteria": criteria,
        "channel": channel,
    }
    if end:
        resource["end"] = end
    return resource


def generate_subscription_secret() -> str:
    """A high-entropy shared secret for verifying inbound notifications."""
    return secrets.token_urlsafe(32)


def create_subscription(
    *,
    criteria: str,
    endpoint: str,
    ehr_config: dict[str, Any] | None = None,
    secret_header: str | None = None,
    end: str | None = None,
    dry_run: bool = False,
    audit_hook=None,
) -> dict[str, Any]:
    """Build and register a Subscription through the EHR gateway.

    Routes the write via ``ehr_gateway.write_resource`` so vendor selection,
    bounded retry, dry-run, and the audit hook are all inherited. Returns the
    gateway write result augmented with the ``criteria`` and ``endpoint`` so the
    router can persist the registration.

    Raises ``ehr_gateway.EhrGatewayError`` on a hard write failure.
    """
    resource = build_subscription(
        criteria=criteria,
        endpoint=endpoint,
        secret_header=secret_header,
        end=end,
    )
    result = ehr_gateway.write_resource(
        resource,
        ehr_config=ehr_config,
        dry_run=dry_run,
        audit_hook=audit_hook,
    )
    log.info(
        "subscription create: criteria_type=%s dry_run=%s stored=%s",
        criteria.split("?", 1)[0], dry_run, result.get("stored"),
    )
    return {
        **result,
        "criteria": criteria,
        "endpoint": endpoint,
    }


# --------------------------------------------------------------------------
# Inbound notification parsing
# --------------------------------------------------------------------------


def verify_notification_secret(headers: dict[str, str], expected_secret: str | None) -> bool:
    """Constant-time-ish check that an inbound notification carries our secret.

    When no secret was configured for a subscription, verification is skipped
    (returns ``True``) — the caller decides whether an unauthenticated channel
    is acceptable. Header lookup is case-insensitive.
    """
    if not expected_secret:
        return True
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    got = lowered.get("x-solace-subscription-secret", "")
    return secrets.compare_digest(str(got), str(expected_secret))


def parse_notification(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize an inbound FHIR Subscription notification.

    Handles both wire shapes:
      * A bare changed resource (R4 ``full-resource`` payload).
      * A backport/R5 notification ``Bundle`` whose entries carry a
        ``SubscriptionStatus`` plus the changed resources.

    Returns ``{"event": str, "references": [str], "resources": [dict], "status": dict|None}``
    where ``references`` are ``ResourceType/id`` strings and ``resources`` are any
    inline resources delivered with the notification (excluding the
    ``SubscriptionStatus`` itself).
    """
    body = body or {}
    rtype = body.get("resourceType")

    if rtype == "Bundle" and body.get("type") in _NOTIFICATION_BUNDLE_TYPES:
        return _parse_notification_bundle(body)

    # A bare resource notification.
    if rtype and rtype not in ("OperationOutcome",):
        ref = _resource_ref(body)
        return {
            "event": "resource-change",
            "references": [ref] if ref else [],
            "resources": [body],
            "status": None,
        }

    # An id-only / empty ping carries no resource — still a valid notification.
    return {"event": "ping", "references": [], "resources": [], "status": None}


def _parse_notification_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    references: list[str] = []
    resources: list[dict[str, Any]] = []
    status: dict[str, Any] | None = None

    for entry in bundle.get("entry", []) or []:
        res = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(res, dict):
            # An entry may carry only request.url (a reference) with no inline resource.
            req = entry.get("request") if isinstance(entry, dict) else None
            url = (req or {}).get("url") if isinstance(req, dict) else None
            if url:
                references.append(str(url).lstrip("/"))
            continue
        if res.get("resourceType") == "SubscriptionStatus":
            status = res
            # SubscriptionStatus.notificationEvent[].focus carries refs to the
            # resources that triggered this notification.
            for ev in res.get("notificationEvent", []) or []:
                focus = (ev.get("focus") or {}).get("reference") if isinstance(ev, dict) else None
                if focus:
                    references.append(str(focus))
            continue
        resources.append(res)
        ref = _resource_ref(res)
        if ref:
            references.append(ref)

    event = "subscription-notification"
    if status and status.get("type"):
        event = str(status["type"])
    # De-dupe references while preserving order.
    seen: set[str] = set()
    uniq_refs = [r for r in references if not (r in seen or seen.add(r))]
    return {
        "event": event,
        "references": uniq_refs,
        "resources": resources,
        "status": status,
    }


def _resource_ref(resource: dict[str, Any]) -> str:
    rtype = resource.get("resourceType")
    rid = resource.get("id")
    return f"{rtype}/{rid}" if rtype and rid else ""


def scan_notification_for_ai(
    parsed: dict[str, Any],
    *,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """SEC-005: scan any inline free-text in a parsed notification before AI use.

    Delegates per-resource scanning to ``fhir_bulk_export.scan_resource_freetext``
    so the content-guard logic lives in exactly one place. Returns
    ``{"safe_resources": int, "rejected_resources": int, "findings": [str]}``.
    Callers forwarding notification content to an AI provider must consult this
    and drop the rejected resources.
    """
    safe_count = 0
    rejected = 0
    findings: list[str] = []
    for res in parsed.get("resources", []) or []:
        rtype = res.get("resourceType", "Resource")
        safe, _cleaned, hits = fhir_bulk_export.scan_resource_freetext(
            res, label=f"ehr_subscription:{rtype}",
            source_ip=source_ip, user_agent=user_agent,
        )
        findings.extend(hits)
        if safe:
            safe_count += 1
        else:
            rejected += 1
    return {
        "safe_resources": safe_count,
        "rejected_resources": rejected,
        "findings": sorted(set(findings)),
    }
