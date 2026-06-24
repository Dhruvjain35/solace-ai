"""Pure-Python RSA keypair generator for offline tests.

The backend venv ships no ``cryptography`` package (``lib.smart_auth`` implements
RS384 signing by hand), so tests that exercise the SMART Backend Services
``private_key_jwt`` path need an RSA private-key PEM produced without any
third-party dependency. This module generates a small (test-only) RSA key and
serializes it as PKCS#1 ``RSA PRIVATE KEY`` PEM — exactly the shape
``smart_auth._parse_rsa_private_key`` consumes.

NOTE: keys here are deliberately tiny / fast and are for TEST USE ONLY. They are
never written to disk and never used against a real EHR.
"""
from __future__ import annotations

import base64
import secrets


def _is_probable_prime(n: int, rounds: int = 24) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = 2 + secrets.randbelow(n - 3)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def _der_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    body = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _der_int(value: int) -> bytes:
    if value == 0:
        body = b"\x00"
    else:
        body = value.to_bytes((value.bit_length() + 7) // 8 + 1, "big")
        body = body.lstrip(b"\x00") or b"\x00"
        if body[0] & 0x80:
            body = b"\x00" + body
    return b"\x02" + _der_len(len(body)) + body


def generate_rsa_keypair(bits: int = 1024) -> tuple[int, int, int]:
    """Return a fresh RSA keypair as ``(n, e, d)`` integers (test-only).

    Exposes the raw modulus/exponents so tests can build a JWK (public n/e) for
    ``smart_auth.verify_id_token`` and sign an id_token with the private d.
    """
    e = 65537
    while True:
        p = _gen_prime(bits // 2)
        q = _gen_prime(bits // 2)
        if p == q:
            continue
        n = p * q
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        d = pow(e, -1, phi)
        break
    return n, e, d


def _int_to_b64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def rsa_public_jwk(n: int, e: int, kid: str = "test-key-1") -> dict:
    """Build an RSA *public* JWK (the shape a real ``jwks_uri`` publishes)."""
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _int_to_b64url(n),
        "e": _int_to_b64url(e),
    }


def _digestinfo_sha256(message: bytes) -> bytes:
    import hashlib
    prefix = bytes([
        0x30, 0x31, 0x30, 0x0D, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65,
        0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20,
    ])
    return prefix + hashlib.sha256(message).digest()


def sign_id_token(claims: dict, n: int, e: int, d: int,
                  *, kid: str = "test-key-1", alg: str = "RS256") -> str:
    """Produce a compact RS256-signed JWS for ``claims`` (test id_token).

    Pure-Python RSASSA-PKCS1-v1_5 over SHA-256, mirroring the verify path in
    ``smart_auth._rsa_verify`` so a round-trip proves the verifier works.
    """
    import json

    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = {"alg": alg, "typ": "JWT", "kid": kid}
    signing_input = (
        _b64(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64(json.dumps(claims, separators=(",", ":")).encode())
    )
    k = (n.bit_length() + 7) // 8
    t = _digestinfo_sha256(signing_input.encode("ascii"))
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    sig_int = pow(int.from_bytes(em, "big"), d, n)
    signature = sig_int.to_bytes(k, "big")
    return signing_input + "." + _b64(signature)


def generate_rsa_private_key_pem(bits: int = 1024) -> str:
    """Return a fresh PKCS#1 ``RSA PRIVATE KEY`` PEM (test-only, small key).

    1024-bit is below production strength but is fine for a unit test that only
    needs the pure-Python RS384 signer to round-trip. The modulus is still large
    enough to hold a SHA-384 RS384 signature block.
    """
    e = 65537
    while True:
        p = _gen_prime(bits // 2)
        q = _gen_prime(bits // 2)
        if p == q:
            continue
        n = p * q
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        d = pow(e, -1, phi)
        break
    dp = d % (p - 1)
    dq = d % (q - 1)
    qinv = pow(q, -1, p)

    seq = b"".join([
        _der_int(0),      # version
        _der_int(n),
        _der_int(e),
        _der_int(d),
        _der_int(p),
        _der_int(q),
        _der_int(dp),
        _der_int(dq),
        _der_int(qinv),
    ])
    der = b"\x30" + _der_len(len(seq)) + seq
    b64 = base64.encodebytes(der).decode("ascii").replace("\n", "")
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        + "\n".join(lines)
        + "\n-----END RSA PRIVATE KEY-----\n"
    )
