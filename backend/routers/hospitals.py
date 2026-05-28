"""Hospital workspace provisioning.

Public, unauthenticated onboarding endpoint. Each hospital that adopts Solace
gets its own unique URL-safe slug. The slug is also the hospital_id, so all
existing per-hospital routes (`/api/{hospital_id}/...`) and frontend paths
(`/h/{slug}/clinician`) work without any other change.

The legacy `demo` hospital keeps working untouched — it is seeded separately
by storage.seed_demo_hospital() and is not reachable through this router.

  - POST /hospitals/provision  — create a workspace, return its slug + URLs

This router is mounted WITHOUT the `/api/{hospital_id}` prefix because it
creates the hospital_id rather than operating inside one.
"""
from __future__ import annotations

import logging
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db import storage
from lib import accounts, audit as _audit, blocklist, quota
from lib.config import settings
from services import email as email_service

log = logging.getLogger(__name__)

router = APIRouter()


def _frontend_base(request: Request | None) -> str:
    """Origin the emailed link points at: configured app_base_url, else the
    request's own Origin/Referer (the landing page that called provision)."""
    if settings.app_base_url:
        return settings.app_base_url.rstrip("/")
    if request is not None:
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            return origin.split("/clinicians")[0].rstrip("/")
    return ""

# Reserved slugs — these collide with fixed frontend/API paths or the demo
# workspace, so a provisioned hospital may never claim them.
_RESERVED_SLUGS = {
    "demo", "api", "health", "voice", "ehr", "h", "media",
    "hospitals", "admin", "clinician", "static", "assets",
}

_SLUG_MAX_LEN = 40
_SLUG_MIN_LEN = 3


class ProvisionHospitalBody(BaseModel):
    name: str
    requested_slug: str | None = None
    # The person provisioning becomes the workspace's first admin. Optional so
    # the legacy "just give me a workspace" flow still works.
    admin_email: str | None = None
    admin_name: str | None = None


def _slugify(text: str) -> str:
    """Lower-case, ASCII, hyphen-separated. Strips anything that is not a
    letter/digit and collapses runs of separators into a single hyphen."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:_SLUG_MAX_LEN].strip("-")


def _unique_slug(base: str) -> str:
    """Return a slug derived from `base` that no hospital currently occupies.
    Falls back to a random suffix when the base (and short variants) collide."""
    candidate = base
    if candidate in _RESERVED_SLUGS or storage.slug_exists(candidate):
        # Try a few random 4-char suffixes before giving up.
        for _ in range(6):
            suffix = secrets.token_hex(2)  # 4 hex chars
            trimmed = base[: _SLUG_MAX_LEN - 5].rstrip("-")
            candidate = f"{trimmed}-{suffix}"
            if candidate not in _RESERVED_SLUGS and not storage.slug_exists(candidate):
                return candidate
        raise HTTPException(status_code=409, detail="Could not allocate a unique workspace URL — try a different name.")
    return candidate


def _base_url(request: Request) -> str:
    """Best-effort public origin for building shareable URLs. Honours the
    standard proxy headers set by API Gateway / CloudFront."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        return ""
    return f"{proto}://{host}"


@router.post("/hospitals/provision")
def provision_hospital(body: ProvisionHospitalBody | None = None, request: Request = None) -> dict:
    """Create a new hospital workspace and return its unique URLs.

    Unauthenticated but rate-limited per identity. The generated slug is
    URL-safe and globally unique; it is used as the hospital_id for every
    downstream per-hospital route."""
    if body is None or not body.name.strip():
        raise HTTPException(status_code=400, detail="hospital name is required")

    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")

    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "hospitals.provision", source_ip=source_ip)

    raw = body.requested_slug.strip() if body.requested_slug else body.name
    base = _slugify(raw)
    if len(base) < _SLUG_MIN_LEN:
        raise HTTPException(
            status_code=400,
            detail="Workspace name must contain at least 3 letters or digits.",
        )

    slug = _unique_slug(base)

    storage.put_hospital(
        {
            "hospital_id": slug,
            "slug": slug,
            "name": body.name.strip(),
            "created_at": storage._now_iso(),
            "provisioned": True,
            "onboarded": False,  # gates the first-run setup wizard
        }
    )
    log.info("Provisioned hospital workspace slug=%s", slug)

    # The creator becomes the first admin. We mint their account and email a
    # single-use sign-in link so they land in the onboarding wizard.
    admin_invited = False
    admin_email = (body.admin_email or "").strip()
    if admin_email:
        accounts.create_clinician(
            hospital_id=slug,
            email=admin_email,
            name=(body.admin_name or admin_email.split("@")[0]).strip(),
            role="admin",
        )
        raw = accounts.issue_magic_token(hospital_id=slug, email=admin_email, purpose="login")
        link = f"{_frontend_base(request)}/h/{slug}/auth/verify?token={raw}"
        send_result = email_service.send_magic_link(
            to=admin_email, link=link, hospital_name=body.name.strip(), purpose="login"
        )
        admin_invited = True
        _audit.record(
            clinician_id=None, clinician_name=body.admin_name, action="hospital.admin_provisioned",
            source_ip=source_ip, status_code=200,
            extra={"hospital_id": slug, "delivered": send_result.get("delivered")},
        )

    # Shareable workspace URLs point at the frontend app (app_base_url / Origin),
    # never the API host the request happens to arrive on.
    base_url = _frontend_base(request)
    resp = {
        "hospital_id": slug,
        "slug": slug,
        "name": body.name.strip(),
        "onboarded": False,
        "admin_invited": admin_invited,
        "clinician_path": f"/h/{slug}/clinician",
        "patient_path": f"/h/{slug}",
        "clinician_url": f"{base_url}/h/{slug}/clinician" if base_url else f"/h/{slug}/clinician",
        "patient_url": f"{base_url}/h/{slug}" if base_url else f"/h/{slug}",
    }
    # Dev/sandbox only: surface the admin's sign-in link so the flow is followable.
    if admin_invited and settings.email_dev_echo:
        resp["admin_dev_link"] = f"{_frontend_base(request)}/h/{slug}/auth/verify?token={raw}"
    return resp
