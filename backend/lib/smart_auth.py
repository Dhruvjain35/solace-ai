"""SMART App Launch v2 hardening primitives.

Pure-stdlib helpers for the SMART-on-FHIR v2 OAuth flow, used by
``routers/ehr_auth.py``. No new third-party dependency is introduced — the
private_key_jwt signer is a pure-Python RSA PKCS#1 v1.5 / SHA-384 (RS384)
implementation built on ``hashlib`` and ``pow()``, because the backend venv
ships ``pyjwt`` but not ``cryptography``.

What lives here:
  - PKCE: verifier + S256 challenge generation.
  - state / nonce: CSRF + OIDC replay protection token generators + validators.
  - .well-known/smart-configuration discovery fetch + parse.
  - SMART v2 scope helpers: parse / build / wildcard match for the
    ``resource.cruds`` granular permission grammar (c, r, u, d, s).
  - private_key_jwt: RS384 client-assertion builder for confidential clients.

Everything is deliberately framework-free so it stays import-light for Lambda
cold starts and is unit-testable without FastAPI.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from lib import url_guard

log = logging.getLogger(__name__)

# SMART spec bounds: a PKCE verifier is 43-128 chars; a nonce / state need only
# be unguessable. 32 random bytes base64url-encoded is 43 chars — comfortably
# above any guessing budget.
_DISCOVERY_TIMEOUT = 8.0
_NONCE_BYTES = 32


# ----------------------------------------------------------------------------------
# base64url helpers (no padding — JWT / OAuth wire format)
# ----------------------------------------------------------------------------------


def b64url_encode(raw: bytes) -> str:
    """base64url-encode without padding (JWT / PKCE wire format)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(data: str) -> bytes:
    """base64url-decode, tolerating missing padding."""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


# ----------------------------------------------------------------------------------
# PKCE — RFC 7636, S256. SMART v2 makes PKCE mandatory for ALL clients.
# ----------------------------------------------------------------------------------


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)``.

    Verifier: 64 random bytes base64url-encoded → 86 url-safe chars, within the
    RFC 7636 43-128 range. Challenge: ``base64url(sha256(verifier))``.
    """
    verifier = b64url_encode(secrets.token_bytes(64))
    challenge = b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Constant-time check that ``code_verifier`` hashes to ``code_challenge``."""
    if not code_verifier or not code_challenge:
        return False
    expected = b64url_encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
    return secrets.compare_digest(expected, code_challenge)


# ----------------------------------------------------------------------------------
# state + nonce — CSRF (state) and OIDC id_token replay protection (nonce)
# ----------------------------------------------------------------------------------


def generate_state() -> str:
    """Opaque, unguessable OAuth ``state`` value (CSRF binding)."""
    return secrets.token_urlsafe(_NONCE_BYTES)


def generate_nonce() -> str:
    """Opaque OIDC ``nonce`` — echoed into the id_token, validated on return."""
    return secrets.token_urlsafe(_NONCE_BYTES)


def validate_state(received: str, expected: str) -> bool:
    """Constant-time compare of the returned ``state`` against the stored one."""
    if not received or not expected:
        return False
    return secrets.compare_digest(str(received), str(expected))


def validate_nonce(id_token_nonce: str, expected: str) -> bool:
    """Constant-time compare of the id_token ``nonce`` claim against stored value.

    Per OIDC core §3.1.3.7, the nonce in the id_token MUST equal the nonce sent
    in the authorize request. A missing or mismatched nonce means a replayed or
    cross-session id_token and MUST be rejected.
    """
    if not id_token_nonce or not expected:
        return False
    return secrets.compare_digest(str(id_token_nonce), str(expected))


# ----------------------------------------------------------------------------------
# .well-known/smart-configuration discovery
# ----------------------------------------------------------------------------------


@dataclass
class SmartConfiguration:
    """Parsed subset of a SMART v2 ``.well-known/smart-configuration`` document.

    https://hl7.org/fhir/smart-app-launch/conformance.html
    """

    authorization_endpoint: str = ""
    token_endpoint: str = ""
    introspection_endpoint: str = ""
    revocation_endpoint: str = ""
    capabilities: list[str] = field(default_factory=list)
    scopes_supported: list[str] = field(default_factory=list)
    code_challenge_methods_supported: list[str] = field(default_factory=list)
    token_endpoint_auth_methods_supported: list[str] = field(default_factory=list)
    issuer: str = ""
    jwks_uri: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def supports_pkce_s256(self) -> bool:
        return "S256" in (self.code_challenge_methods_supported or [])

    @property
    def supports_private_key_jwt(self) -> bool:
        return "private_key_jwt" in (self.token_endpoint_auth_methods_supported or [])

    @property
    def supports_ehr_launch(self) -> bool:
        return "launch-ehr" in (self.capabilities or [])

    @property
    def supports_standalone_launch(self) -> bool:
        return "launch-standalone" in (self.capabilities or [])


def parse_smart_configuration(doc: dict[str, Any]) -> SmartConfiguration:
    """Map a raw discovery JSON document into a :class:`SmartConfiguration`."""
    doc = doc or {}

    def _list(key: str) -> list[str]:
        v = doc.get(key)
        return [str(x) for x in v] if isinstance(v, list) else []

    return SmartConfiguration(
        authorization_endpoint=str(doc.get("authorization_endpoint", "")),
        token_endpoint=str(doc.get("token_endpoint", "")),
        introspection_endpoint=str(doc.get("introspection_endpoint", "")),
        revocation_endpoint=str(doc.get("revocation_endpoint", "")),
        capabilities=_list("capabilities"),
        scopes_supported=_list("scopes_supported"),
        code_challenge_methods_supported=_list("code_challenge_methods_supported"),
        token_endpoint_auth_methods_supported=_list(
            "token_endpoint_auth_methods_supported"
        ),
        issuer=str(doc.get("issuer", "")),
        jwks_uri=str(doc.get("jwks_uri", "")),
        raw=doc,
    )


def discovery_url(fhir_base_url: str) -> str:
    """Build the ``.well-known/smart-configuration`` URL for a FHIR base URL."""
    return fhir_base_url.rstrip("/") + "/.well-known/smart-configuration"


def fetch_smart_configuration(fhir_base_url: str) -> SmartConfiguration | None:
    """Fetch + parse the SMART discovery document for ``fhir_base_url``.

    Returns ``None`` on any network / parse failure so callers can fall back to
    statically-configured vendor endpoints. SMART v1 servers that lack the
    well-known doc still work via the static fallback.
    """
    if not fhir_base_url:
        return None
    url = discovery_url(fhir_base_url)
    try:
        # C3 (SSRF): reject a discovery URL pointed at metadata/internal hosts, and
        # do NOT follow redirects (a 30x could bounce past the check into the VPC).
        url_guard.assert_public_https(url, "fhir_base_url")
        with httpx.Client(timeout=_DISCOVERY_TIMEOUT, follow_redirects=False) as client:
            resp = client.get(url, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            log.info("SMART discovery %s -> %d", url, resp.status_code)
            return None
        return parse_smart_configuration(resp.json())
    except Exception as e:  # noqa: BLE001
        log.info("SMART discovery fetch failed for %s: %s", url, e)
        return None


# ----------------------------------------------------------------------------------
# SMART v2 scopes — granular ``resource.cruds`` permission grammar
# ----------------------------------------------------------------------------------

# SMART v2 resource scope, e.g. "patient/Observation.rs" or "user/*.cruds".
# group ∈ {patient, user, system}; resource is a FHIR type or "*";
# perms is a subset of "cruds" (create, read, update, delete, search).
_V2_SCOPE_RE = re.compile(r"^(patient|user|system)/([A-Za-z*]+)\.([cruds]+)$")
# SMART v1 resource scope, e.g. "user/Observation.read" — still emitted by Epic.
_V1_SCOPE_RE = re.compile(r"^(patient|user|system)/([A-Za-z*]+)\.(read|write|\*)$")
_V1_TO_V2 = {"read": "rs", "write": "cud", "*": "cruds"}


@dataclass(frozen=True)
class ResourceScope:
    """A single SMART resource scope, normalized to v2 ``cruds`` permissions."""

    group: str        # patient | user | system
    resource: str     # FHIR resource type, or "*"
    perms: frozenset  # subset of {c, r, u, d, s}

    def to_v2(self) -> str:
        ordered = "".join(p for p in "cruds" if p in self.perms)
        return f"{self.group}/{self.resource}.{ordered}"

    def covers(self, group: str, resource: str, perm: str) -> bool:
        """True if this scope grants ``perm`` on ``group/resource``.

        Wildcard ``*`` on the resource matches any FHIR type. ``perm`` is a
        single CRUDS letter.
        """
        if self.group != group:
            return False
        if self.resource != "*" and self.resource != resource:
            return False
        return perm in self.perms


def parse_scope(scope_token: str) -> ResourceScope | None:
    """Parse one scope token into a :class:`ResourceScope`.

    Accepts both v2 (``.cruds``) and v1 (``.read`` / ``.write`` / ``.*``)
    resource grammar; v1 forms are upgraded to their v2 equivalent. Non-resource
    scopes (``openid``, ``fhirUser``, ``launch``, ...) return ``None``.
    """
    if not scope_token:
        return None
    m = _V2_SCOPE_RE.match(scope_token)
    if m:
        return ResourceScope(m.group(1), m.group(2), frozenset(m.group(3)))
    m = _V1_SCOPE_RE.match(scope_token)
    if m:
        perms = _V1_TO_V2.get(m.group(3), "")
        return ResourceScope(m.group(1), m.group(2), frozenset(perms))
    return None


def parse_scopes(scope_string: str) -> list[ResourceScope]:
    """Parse a space-delimited scope string, dropping non-resource scopes."""
    out: list[ResourceScope] = []
    for tok in (scope_string or "").split():
        rs = parse_scope(tok)
        if rs is not None:
            out.append(rs)
    return out


def scope_granted(
    granted_scope_string: str, group: str, resource: str, perm: str
) -> bool:
    """True if the granted scope set permits ``perm`` on ``group/resource``.

    Honors v2 wildcard resources. ``perm`` is a single CRUDS letter, e.g. "r".
    """
    return any(
        rs.covers(group, resource, perm)
        for rs in parse_scopes(granted_scope_string)
    )


def build_v2_scopes(
    resource_perms: dict[str, str],
    group: str = "user",
    extra: tuple[str, ...] = ("openid", "fhirUser", "profile"),
) -> str:
    """Build a space-delimited SMART v2 scope string.

    ``resource_perms`` maps a FHIR resource type (or ``*``) to a CRUDS permission
    string, e.g. ``{"Patient": "rs", "Observation": "rs", "*": "r"}``. ``extra``
    is prepended verbatim for identity / launch scopes.
    """
    parts: list[str] = list(extra)
    for resource, perms in resource_perms.items():
        ordered = "".join(p for p in "cruds" if p in perms)
        if ordered:
            parts.append(f"{group}/{resource}.{ordered}")
    return " ".join(parts)


def normalize_scope_string(scope_string: str) -> str:
    """Normalize a scope string: upgrade v1 resource scopes to v2, keep others.

    Used to compare a requested scope set against what a server granted without
    being tripped up by v1/v2 spelling differences.
    """
    out: list[str] = []
    for tok in (scope_string or "").split():
        rs = parse_scope(tok)
        out.append(rs.to_v2() if rs is not None else tok)
    return " ".join(out)


# ----------------------------------------------------------------------------------
# private_key_jwt — RS384 client assertion for confidential clients
#
# SMART Backend Services + confidential symmetric/asymmetric clients authenticate
# to the token endpoint with a signed JWT instead of a client_secret. SMART
# mandates RS384 or ES384. The backend venv has no `cryptography`, so we
# implement RSA PKCS#1 v1.5 signing in pure Python: SHA-384 digest, DigestInfo
# wrapper, EMSA-PKCS1-v1_5 padding, then m = pow(em_int, d, n).
# ----------------------------------------------------------------------------------

# DER prefix for an RFC 8017 DigestInfo wrapping a SHA-384 digest.
_SHA384_DIGESTINFO_PREFIX = bytes([
    0x30, 0x41, 0x30, 0x0D, 0x06, 0x09, 0x60, 0x86,
    0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x02, 0x05,
    0x00, 0x04, 0x30,
])


class PrivateKeyJwtError(Exception):
    """Raised when a private_key_jwt client assertion cannot be produced."""


def _read_der_length(data: bytes, idx: int) -> tuple[int, int]:
    """Read a DER length field. Returns ``(length, next_index)``."""
    first = data[idx]
    idx += 1
    if first < 0x80:
        return first, idx
    num_bytes = first & 0x7F
    length = int.from_bytes(data[idx:idx + num_bytes], "big")
    return length, idx + num_bytes


def _der_read_tlv(data: bytes, idx: int) -> tuple[int, bytes, int]:
    """Read one DER TLV. Returns ``(tag, value_bytes, next_index)``."""
    tag = data[idx]
    length, idx = _read_der_length(data, idx + 1)
    return tag, data[idx:idx + length], idx + length


def _der_int(data: bytes, idx: int) -> tuple[int, int]:
    """Read a DER INTEGER. Returns ``(value, next_index)``."""
    tag, val, nxt = _der_read_tlv(data, idx)
    if tag != 0x02:
        raise PrivateKeyJwtError("expected DER INTEGER in RSA private key")
    return int.from_bytes(val, "big"), nxt


def _pem_to_der(pem: str) -> tuple[bytes, str]:
    """Strip PEM armor. Returns ``(der_bytes, header_label)``.

    ``header_label`` is the text inside ``-----BEGIN <label>-----``; callers use
    it to tell PKCS#1 (``RSA PRIVATE KEY``) from PKCS#8 (``PRIVATE KEY``) and to
    reject EC keys early.
    """
    lines = [ln.strip() for ln in pem.strip().splitlines()]
    label = ""
    body: list[str] = []
    in_body = False
    for ln in lines:
        if ln.startswith("-----BEGIN "):
            label = ln[len("-----BEGIN "):].rstrip("-").strip()
            in_body = True
            continue
        if ln.startswith("-----END "):
            break
        if in_body:
            body.append(ln)
    if not body:
        raise PrivateKeyJwtError("no PEM body found in private key")
    return base64.b64decode("".join(body)), label


def _parse_rsa_private_key(pem: str) -> tuple[int, int]:
    """Parse an RSA private key PEM. Returns ``(n, d)``.

    Supports PKCS#1 (``RSA PRIVATE KEY``) and PKCS#8 (``PRIVATE KEY``). EC keys
    (``EC PRIVATE KEY`` / PKCS#8 wrapping an EC key) are rejected with a clear
    message — SMART also permits ES384, but ES384 needs elliptic-curve math we
    do not implement without ``cryptography``.
    """
    der, label = _pem_to_der(pem)
    upper = label.upper()
    if "EC" in upper.split() or upper == "EC PRIVATE KEY":
        raise PrivateKeyJwtError(
            "EC private keys are not supported by the pure-Python signer. "
            "SMART permits ES384, but Solace's signer implements RS384 only. "
            "Register an RSA (2048-bit) key pair with the EHR instead."
        )

    # Unwrap PKCS#8 to reach the inner PKCS#1 RSAPrivateKey structure.
    if upper == "PRIVATE KEY":
        tag, outer, _ = _der_read_tlv(der, 0)
        if tag != 0x30:
            raise PrivateKeyJwtError("malformed PKCS#8 private key")
        idx = 0
        # version INTEGER
        _, idx = _der_int(outer, idx)
        # privateKeyAlgorithm SEQUENCE — inspect the OID to reject EC keys.
        tag, algo, idx = _der_read_tlv(outer, idx)
        if tag != 0x30:
            raise PrivateKeyJwtError("malformed PKCS#8 algorithm identifier")
        # OID 1.2.840.10045.2.1 is ecPublicKey — EC, unsupported.
        ec_oid = bytes([0x06, 0x07, 0x2A, 0x86, 0x48, 0xCE, 0x3D, 0x02, 0x01])
        if ec_oid in algo:
            raise PrivateKeyJwtError(
                "PKCS#8 key wraps an EC key — unsupported. Use an RSA key (RS384)."
            )
        # privateKey OCTET STRING wraps the PKCS#1 RSAPrivateKey.
        tag, inner, _ = _der_read_tlv(outer, idx)
        if tag != 0x04:
            raise PrivateKeyJwtError("malformed PKCS#8 privateKey octet string")
        der = inner
        label = "RSA PRIVATE KEY"

    # PKCS#1 RSAPrivateKey ::= SEQUENCE { version, n, e, d, p, q, ... }
    tag, seq, _ = _der_read_tlv(der, 0)
    if tag != 0x30:
        raise PrivateKeyJwtError("malformed RSA private key (expected SEQUENCE)")
    idx = 0
    _, idx = _der_int(seq, idx)        # version
    n, idx = _der_int(seq, idx)        # modulus
    _, idx = _der_int(seq, idx)        # publicExponent
    d, idx = _der_int(seq, idx)        # privateExponent
    if n <= 0 or d <= 0:
        raise PrivateKeyJwtError("RSA private key missing modulus/exponent")
    return n, d


def _rsa_sign_rs384(message: bytes, n: int, d: int) -> bytes:
    """RSA PKCS#1 v1.5 sign ``message`` with SHA-384. Returns the signature.

    Implements EMSA-PKCS1-v1_5 (RFC 8017 §9.2) and RSASP1 (§5.2.1) using only
    ``hashlib`` and ``pow()``.
    """
    k = (n.bit_length() + 7) // 8
    digest = hashlib.sha384(message).digest()
    t = _SHA384_DIGESTINFO_PREFIX + digest
    if k < len(t) + 11:
        raise PrivateKeyJwtError("RSA modulus too small for an RS384 signature")
    # EM = 0x00 || 0x01 || PS (0xFF padding) || 0x00 || T
    ps = b"\xff" * (k - len(t) - 3)
    em = b"\x00\x01" + ps + b"\x00" + t
    m_int = int.from_bytes(em, "big")
    sig_int = pow(m_int, d, n)
    return sig_int.to_bytes(k, "big")


def build_client_assertion(
    *,
    client_id: str,
    token_endpoint: str,
    private_key_pem: str,
    kid: str | None = None,
    lifetime_seconds: int = 300,
) -> str:
    """Build an RS384-signed ``private_key_jwt`` client assertion.

    The assertion is sent as ``client_assertion`` on the token request, with
    ``client_assertion_type`` set to
    ``urn:ietf:params:oauth:client-assertion-type:jwt-bearer``.

    Per SMART (https://hl7.org/fhir/smart-app-launch/client-confidential-asymmetric.html):
      - ``iss`` and ``sub`` are both the client_id.
      - ``aud`` is the token endpoint URL.
      - ``jti`` is a unique nonce (replay protection at the server).
      - ``exp`` is short-lived (<= 5 min recommended).
      - signing algorithm is RS384.

    Raises :class:`PrivateKeyJwtError` for EC keys or malformed PEM input.
    """
    if not client_id or not token_endpoint or not private_key_pem:
        raise PrivateKeyJwtError(
            "client_id, token_endpoint and private_key_pem are all required"
        )
    n, d = _parse_rsa_private_key(private_key_pem)

    now = int(time.time())
    header: dict[str, Any] = {"alg": "RS384", "typ": "JWT"}
    if kid:
        header["kid"] = kid
    claims = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_endpoint,
        "jti": secrets.token_urlsafe(_NONCE_BYTES),
        "iat": now,
        "exp": now + max(1, int(lifetime_seconds)),
    }
    signing_input = (
        b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + b64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    )
    signature = _rsa_sign_rs384(signing_input.encode("ascii"), n, d)
    return signing_input + "." + b64url_encode(signature)


# Standard OAuth client-assertion type for JWT-bearer client authentication.
CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


# ----------------------------------------------------------------------------------
# id_token claim extraction (unverified — signature trust is delegated to the
# fact that the id_token arrives over TLS directly from the token endpoint, the
# same trust model the existing _practitioner_from_id_token helper relies on).
# ----------------------------------------------------------------------------------


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode (without signature verification) the claims of a compact JWT.

    Returns ``{}`` on any structural error. Used to read the ``nonce`` /
    ``fhirUser`` claims out of an id_token received over TLS from the token
    endpoint; the TLS channel is the integrity guarantee here.

    For full cryptographic verification against the issuer JWKS, use
    :func:`verify_id_token` instead — that path adds defense-in-depth on top of
    the TLS-channel trust this function assumes.
    """
    if not token or token.count(".") != 2:
        return {}
    try:
        return json.loads(b64url_decode(token.split(".")[1]).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _decode_jwt_header(token: str) -> dict[str, Any]:
    """Decode the protected header of a compact JWT (``{}`` on error)."""
    if not token or token.count(".") != 2:
        return {}
    try:
        return json.loads(b64url_decode(token.split(".")[0]).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ----------------------------------------------------------------------------------
# id_token signature verification against the issuer JWKS (RS256/RS384/RS512).
#
# SMART/OIDC id_tokens are signed by the authorization server. We verify them
# against the public keys published at the issuer's ``jwks_uri`` so a token whose
# signature does not match a published key is rejected — defense-in-depth beyond
# the "it arrived over TLS" assumption ``decode_jwt_claims`` relies on. Pure
# stdlib: RSA public verify is ``pow(sig, e, n)`` + EMSA-PKCS1-v1_5 compare. EC
# (ES*) keys are not verifiable without ``cryptography``; we treat them as a
# soft-fail so the existing TLS-trust path still works (honest fallback).
# ----------------------------------------------------------------------------------

# DigestInfo DER prefixes for the SHA-2 family used by RS256/RS384/RS512.
_DIGESTINFO_PREFIX: dict[str, bytes] = {
    "RS256": bytes([
        0x30, 0x31, 0x30, 0x0D, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65,
        0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20,
    ]),
    "RS384": _SHA384_DIGESTINFO_PREFIX,
    "RS512": bytes([
        0x30, 0x51, 0x30, 0x0D, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65,
        0x03, 0x04, 0x02, 0x03, 0x05, 0x00, 0x04, 0x40,
    ]),
}
_ALG_HASH: dict[str, Any] = {
    "RS256": hashlib.sha256,
    "RS384": hashlib.sha384,
    "RS512": hashlib.sha512,
}

_JWKS_TIMEOUT = 8.0


class IdTokenVerificationError(Exception):
    """Raised when an id_token fails cryptographic / claim verification."""


@dataclass
class IdTokenResult:
    """Outcome of :func:`verify_id_token`.

    ``verified`` is True only when an RSA signature matched a published JWKS key.
    ``fallback`` is True when verification could not be performed (no JWKS, EC
    key, network failure) and the caller should fall back to TLS-channel trust.
    ``claims`` are the decoded payload claims either way (so existing nonce /
    fhirUser extraction keeps working in the fallback path).
    """

    verified: bool
    claims: dict[str, Any] = field(default_factory=dict)
    fallback: bool = False
    reason: str = ""


def _b64url_uint(data: str) -> int:
    """Decode a base64url JWK integer parameter (n / e) to a Python int."""
    return int.from_bytes(b64url_decode(data), "big")


def _jwk_to_rsa(jwk: dict[str, Any]) -> tuple[int, int] | None:
    """Extract ``(n, e)`` from an RSA JWK, or None if it is not an RSA key."""
    if (jwk or {}).get("kty") != "RSA" or not jwk.get("n") or not jwk.get("e"):
        return None
    try:
        return _b64url_uint(jwk["n"]), _b64url_uint(jwk["e"])
    except Exception:  # noqa: BLE001
        return None


def _rsa_verify(signing_input: bytes, signature: bytes, alg: str,
                n: int, e: int) -> bool:
    """RSASSA-PKCS1-v1_5 verify (RFC 8017 §8.2.2) using only ``pow``."""
    prefix = _DIGESTINFO_PREFIX.get(alg)
    hasher = _ALG_HASH.get(alg)
    if prefix is None or hasher is None:
        return False
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    sig_int = int.from_bytes(signature, "big")
    if sig_int >= n:
        return False
    em_int = pow(sig_int, e, n)
    em = em_int.to_bytes(k, "big")
    digest = hasher(signing_input).digest()
    t = prefix + digest
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return secrets.compare_digest(em, expected)


def fetch_jwks(jwks_uri: str) -> list[dict[str, Any]]:
    """Fetch the JWK set from ``jwks_uri``; ``[]`` on any failure."""
    if not jwks_uri:
        return []
    try:
        # C3 (SSRF): same guard as discovery — public host only, no redirect bounce.
        url_guard.assert_public_https(jwks_uri, "jwks_uri")
        with httpx.Client(timeout=_JWKS_TIMEOUT, follow_redirects=False) as client:
            resp = client.get(jwks_uri, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            log.info("JWKS fetch %s -> %d", jwks_uri, resp.status_code)
            return []
        keys = resp.json().get("keys")
        return [k for k in keys if isinstance(k, dict)] if isinstance(keys, list) else []
    except Exception as e:  # noqa: BLE001
        log.info("JWKS fetch failed for %s: %s", jwks_uri, e)
        return []


def verify_id_token(
    token: str,
    *,
    jwks: list[dict[str, Any]] | None = None,
    jwks_uri: str = "",
    expected_issuer: str = "",
    expected_audience: str = "",
    expected_nonce: str = "",
    leeway_seconds: int = 120,
    now: int | None = None,
) -> IdTokenResult:
    """Verify an OIDC id_token signature against the issuer JWKS, then claims.

    Pass either a pre-fetched ``jwks`` (the keys array) or a ``jwks_uri`` to
    fetch from. RSA-signed tokens (RS256/384/512) are cryptographically verified;
    a signature mismatch raises :class:`IdTokenVerificationError`. When the key
    is EC, or no JWKS is available, the result is a *fallback* (``verified=False,
    fallback=True``) so the caller keeps the pre-existing TLS-channel trust
    behavior rather than hard-failing a previously-accepted flow.

    Time-based (``exp`` / ``iat``) and ``iss`` / ``aud`` / ``nonce`` claim checks
    run whenever the corresponding ``expected_*`` argument is provided, and a
    failure there is always a hard :class:`IdTokenVerificationError` regardless
    of signature path (a wrong audience is a security finding even over TLS).
    """
    if not token or token.count(".") != 2:
        raise IdTokenVerificationError("id_token is not a compact JWS")

    header = _decode_jwt_header(token)
    claims = decode_jwt_claims(token)
    alg = str(header.get("alg", ""))
    kid = header.get("kid")

    # --- Claim checks always run (independent of signature path). ----------------
    _check_id_token_claims(
        claims,
        expected_issuer=expected_issuer,
        expected_audience=expected_audience,
        expected_nonce=expected_nonce,
        leeway_seconds=leeway_seconds,
        now=now,
    )

    if alg == "none" or not alg:
        raise IdTokenVerificationError("id_token alg=none is not permitted")

    if jwks is None:
        jwks = fetch_jwks(jwks_uri) if jwks_uri else []

    if not jwks:
        return IdTokenResult(False, claims, fallback=True,
                             reason="no JWKS available; relying on TLS trust")

    if alg not in _DIGESTINFO_PREFIX:
        # ES256/384/etc. — no EC math without `cryptography`. Honest fallback.
        return IdTokenResult(False, claims, fallback=True,
                             reason=f"alg {alg} not RSA; cannot verify offline")

    # Pick the JWK: by kid if present, else the first RSA signing key.
    candidates = jwks
    if kid:
        matched = [k for k in jwks if k.get("kid") == kid]
        if matched:
            candidates = matched

    signing_input, sig_b64 = token.rsplit(".", 1)
    try:
        signature = b64url_decode(sig_b64)
    except Exception as exc:  # noqa: BLE001
        raise IdTokenVerificationError("malformed id_token signature") from exc

    for jwk in candidates:
        if jwk.get("use") not in (None, "sig"):
            continue
        rsa = _jwk_to_rsa(jwk)
        if rsa is None:
            continue
        n, e = rsa
        if _rsa_verify(signing_input.encode("ascii"), signature, alg, n, e):
            return IdTokenResult(True, claims, fallback=False, reason="signature verified")

    raise IdTokenVerificationError(
        "id_token signature did not match any published JWKS key"
    )


def _check_id_token_claims(
    claims: dict[str, Any],
    *,
    expected_issuer: str,
    expected_audience: str,
    expected_nonce: str,
    leeway_seconds: int,
    now: int | None,
) -> None:
    """Validate iss/aud/nonce/exp/iat; raise on any provided-and-failing check."""
    now = int(time.time()) if now is None else int(now)

    if expected_issuer and str(claims.get("iss", "")) != expected_issuer:
        raise IdTokenVerificationError("id_token issuer mismatch")

    if expected_audience:
        aud = claims.get("aud")
        aud_set = set(aud) if isinstance(aud, list) else {aud}
        if expected_audience not in {str(a) for a in aud_set}:
            raise IdTokenVerificationError("id_token audience mismatch")

    if expected_nonce:
        if not validate_nonce(str(claims.get("nonce", "")), expected_nonce):
            raise IdTokenVerificationError("id_token nonce mismatch")

    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and now > exp + leeway_seconds:
        raise IdTokenVerificationError("id_token is expired")
    iat = claims.get("iat")
    if isinstance(iat, (int, float)) and iat - leeway_seconds > now:
        raise IdTokenVerificationError("id_token iat is in the future")


def extract_launch_context(token_payload: dict[str, Any]) -> dict[str, str]:
    """Pull SMART launch context (patient / encounter / ...) from a token response.

    The token endpoint returns launch context as top-level fields alongside
    ``access_token`` — e.g. ``patient``, ``encounter``, ``fhirContext``. This
    normalizes the ones Solace cares about into plain strings.
    """
    ctx: dict[str, str] = {}
    for key in ("patient", "encounter", "fhirUser", "intent", "smart_style_url",
                "tenant", "need_patient_banner"):
        val = token_payload.get(key)
        if val not in (None, "", []):
            ctx[key] = str(val)
    fhir_context = token_payload.get("fhirContext")
    if fhir_context:
        try:
            ctx["fhirContext"] = json.dumps(fhir_context, separators=(",", ":"))
        except (TypeError, ValueError):
            pass
    return ctx
