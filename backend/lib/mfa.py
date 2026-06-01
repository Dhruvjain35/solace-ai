"""RFC 6238 TOTP — pure-stdlib second factor for clinician login.

No third-party dependency: TOTP is implemented with hmac/hashlib/base64/struct
so we do not add `pyotp` (or any new wheel) to the Lambda bundle. This honours
the cold-start lesson — nothing heavy in the import path; the whole module is
stdlib and the imports are top-level and cheap.

Parameters (the universally-compatible Google-Authenticator / Authy defaults):
  - HMAC-SHA1
  - 30-second time step
  - 6 digits
  - +/- 1 step skew tolerance on verify (clock drift)

SEC-002: this module never logs. Secrets and codes are passed in and out as
return values only; callers (jwt_auth, routers/auth) are responsible for never
logging them. The provisioning URI / secret is surfaced exactly once at enroll.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

# RFC 6238 / RFC 4226 parameters. Fixed constants — never client-controlled.
_DIGITS = 6
_PERIOD = 30          # seconds per time step
_ALGORITHM = "SHA1"   # authenticator-app default
_SKEW_STEPS = 1       # accept the previous and next step for clock drift
_SECRET_BYTES = 20    # 160-bit secret (RFC 4226 recommends >= 128 bits)


def generate_secret() -> str:
    """Return a fresh base32-encoded TOTP secret (no padding, uppercase).

    Base32 with the padding stripped is the format authenticator apps expect in
    an otpauth:// URI. 20 random bytes -> 32 base32 chars.
    """
    raw = secrets.token_bytes(_SECRET_BYTES)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _b32_decode(secret: str) -> bytes:
    """Decode a (possibly unpadded, lower/upper-case) base32 secret to bytes."""
    s = secret.strip().replace(" ", "").upper()
    # base64.b32decode requires correct '=' padding (length multiple of 8).
    pad = (-len(s)) % 8
    return base64.b32decode(s + ("=" * pad))


def _hotp(secret: str, counter: int) -> str:
    """RFC 4226 HOTP for a given counter -> zero-padded 6-digit string."""
    key = _b32_decode(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** _DIGITS)).zfill(_DIGITS)


def generate_code(secret: str, at: float | None = None) -> str:
    """Current TOTP code for `secret`. `at` (epoch seconds) is test-injectable."""
    now = time.time() if at is None else at
    counter = int(now // _PERIOD)
    return _hotp(secret, counter)


def verify(secret: str, code: str, at: float | None = None) -> bool:
    """Constant-time verify of a 6-digit TOTP code against `secret`.

    Accepts the current step plus +/- `_SKEW_STEPS` for clock drift. Uses
    hmac.compare_digest for every candidate so a partial-match timing oracle
    cannot leak digits. Malformed input returns False (never raises).
    """
    if not secret or not code:
        return False
    candidate = code.strip()
    if len(candidate) != _DIGITS or not candidate.isdigit():
        return False

    now = time.time() if at is None else at
    base = int(now // _PERIOD)
    matched = False
    try:
        for step in range(-_SKEW_STEPS, _SKEW_STEPS + 1):
            expected = _hotp(secret, base + step)
            # Compare every window (don't short-circuit) to keep timing flat.
            if hmac.compare_digest(expected, candidate):
                matched = True
    except Exception:  # noqa: BLE001 — malformed secret etc. => reject, never raise
        return False
    return matched


def provisioning_uri(secret: str, account: str, issuer: str = "Solace") -> str:
    """Build an otpauth:// URI for QR-code enrollment in an authenticator app.

    Format (Key Uri Format spec):
      otpauth://totp/{issuer}:{account}?secret=...&issuer=...&algorithm=SHA1
                &digits=6&period=30
    """
    label = quote(f"{issuer}:{account}")
    params = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": _ALGORITHM,
            "digits": str(_DIGITS),
            "period": str(_PERIOD),
        }
    )
    return f"otpauth://totp/{label}?{params}"
