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
