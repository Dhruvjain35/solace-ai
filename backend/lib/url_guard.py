"""SSRF guard for outbound EHR/OAuth URLs (C3 fix).

EHR endpoint URLs (FHIR base, authorize, token, JWKS, bulk-export file URLs) are
attacker-influenceable: a workspace EHR config is clinician-writable, and bulk
export / discovery follow server-returned URLs. Without validation, a crafted
``token_url`` / ``fhir_base_url`` can point Solace's server at the cloud metadata
endpoint (169.254.169.254) or an internal VPC service — classic SSRF, which on a
Lambda/EC2 instance profile can yield IAM credentials, and which delivers signed
client-assertions / OAuth codes to an attacker.

This module rejects any URL whose host resolves to a private, loopback,
link-local, reserved, or multicast address. In ``SOLACE_MODE=local`` (test/mock
harness) loopback + localhost are permitted so the in-repo mock FHIR server works;
in every other mode the full block list applies.

Apply ``assert_public_https()`` both when persisting config AND immediately before
each outbound request (resolve-then-check narrows the DNS-rebind window; callers
should also disable HTTP redirect-following so a 30x can't bounce into the block
list after the check).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    """Raised when a URL is not a safe, public HTTPS endpoint."""


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _local_mode() -> bool:
    return os.environ.get("SOLACE_MODE", "").lower() == "local"


def _ip_is_blocked(ip: str) -> bool:
    """True if an IP literal falls in a range we must never reach from the server."""
    try:
        addr = ipaddress.ip_address(ip.strip("[]"))
    except ValueError:
        return False  # not an IP literal; hostname path handles it
    if _local_mode() and addr.is_loopback:
        return False  # mock harness on 127.0.0.1 / ::1
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local      # 169.254.0.0/16 — the cloud metadata endpoint
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_public_https(url: str, field: str = "url") -> str:
    """Validate ``url`` is an absolute HTTPS URL whose host is publicly routable.

    Raises ``UnsafeURL`` on a non-HTTPS scheme, a missing host, or a host that
    resolves (or is literally) a private/loopback/link-local/reserved/multicast
    address. Returns the stripped URL on success.
    """
    url = (url or "").strip()
    if not url:
        raise UnsafeURL(f"{field} is required")

    parsed = urlparse(url)
    host = parsed.hostname

    # Local mock harness: allow http(s)://localhost / 127.0.0.1 for offline tests only.
    if _local_mode() and host and host.lower() in _LOOPBACK_HOSTS:
        return url

    if parsed.scheme != "https" or not host:
        raise UnsafeURL(f"{field} must be an absolute https:// URL")

    # Reject IP-literal hosts that are non-public outright (applies in every mode).
    if _ip_is_blocked(host):
        raise UnsafeURL(f"{field} host {host} is not a routable public address")

    # In local/test mode, stop here: fixtures use placeholder hosts (e.g.
    # tenant.example.org) that don't resolve, and there's no metadata endpoint to
    # protect. The SSRF resolution check is a production control.
    if _local_mode():
        return url

    # Resolve the hostname and reject if ANY resolved address is blocked. Defeats
    # both DNS names pointed at private space and split A/AAAA tricks.
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURL(f"{field} host {host} could not be resolved") from e

    for info in infos:
        sockaddr = info[4]
        ip = sockaddr[0]
        if _ip_is_blocked(ip):
            raise UnsafeURL(
                f"{field} host {host} resolves to non-public address {ip}"
            )

    return url
