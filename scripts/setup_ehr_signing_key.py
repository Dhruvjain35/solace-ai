#!/usr/bin/env python3
"""Generate an RSA-2048 signing keypair for EHR confidential-client auth (private_key_jwt).

Epic and Oracle Health accept asymmetric (private_key_jwt) client authentication
where Solace signs an RS384 client assertion with a private key and the vendor
verifies it against Solace's PUBLIC key — fetched from a JWKS URL (preferred) or a
pasted public key. This script produces:

  - an RSA-2048 private key PEM (PKCS#8) — the secret, written to a gitignored path
  - the matching PUBLIC JWK (kty=RSA, alg=RS384, use=sig, kid=RFC-7638 thumbprint)
  - the exact env-var + AWS Secrets Manager wiring the backend expects
    (SOLACE_<VENDOR>_PRIVATE_KEY, SOLACE_<VENDOR>_KID), and the SOLACE_EHR_JWKS
    value served by GET /.well-known/jwks.json

The backend signer is pure-Python (no `cryptography`), so we shell out to `openssl`
(present on macOS/Linux dev machines) for key generation only. Nothing here runs in
Lambda — keys are generated once locally and stored in Secrets Manager.

Usage:
    python scripts/setup_ehr_signing_key.py --vendor epic
    python scripts/setup_ehr_signing_key.py --vendor epic --from-pem path/to/key.pem

The private key is NEVER printed to stdout — only its on-disk path. Use a SANDBOX
key first; rotate to a production key (and re-publish the JWKS) before go-live.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys

_SECRETS_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", ".secrets")


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _gen_private_pem(path: str) -> None:
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA",
         "-pkeyopt", "rsa_keygen_bits:2048", "-out", path],
        check=True, capture_output=True,
    )
    os.chmod(path, 0o600)


def _modulus_and_exponent(pem_path: str) -> tuple[int, int]:
    """Extract (n, e) from an RSA private key via openssl. e is the standard 65537."""
    out = subprocess.run(
        ["openssl", "rsa", "-in", pem_path, "-noout", "-modulus"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    # "Modulus=<HEX>"
    hex_mod = out.split("=", 1)[1].strip()
    n = int(hex_mod, 16)
    # openssl genpkey uses F4 (65537) as the public exponent.
    return n, 65537


def _jwk_thumbprint(n_b64: str, e_b64: str) -> str:
    """RFC 7638 JWK thumbprint (used as the kid — matches Epic's convention)."""
    canonical = json.dumps({"e": e_b64, "kty": "RSA", "n": n_b64},
                           separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(hashlib.sha256(canonical).digest()).rstrip(b"=").decode()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vendor", required=True,
                    help="vendor id (epic / cerner / athena) — sets the env-var prefix")
    ap.add_argument("--from-pem", default="",
                    help="use an existing RSA private key PEM instead of generating one")
    args = ap.parse_args()
    vendor = args.vendor.lower()

    os.makedirs(_SECRETS_DIR, exist_ok=True)
    pem_path = os.path.abspath(args.from_pem) if args.from_pem else \
        os.path.abspath(os.path.join(_SECRETS_DIR, f"ehr_signing_{vendor}.pem"))

    if not args.from_pem:
        if os.path.exists(pem_path):
            print(f"refusing to overwrite existing key at {pem_path}", file=sys.stderr)
            return 1
        try:
            _gen_private_pem(pem_path)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"openssl key generation failed: {e}", file=sys.stderr)
            return 1

    n, e = _modulus_and_exponent(pem_path)
    n_b64, e_b64 = _b64url_uint(n), _b64url_uint(e)
    kid = _jwk_thumbprint(n_b64, e_b64)
    jwk = {"kty": "RSA", "use": "sig", "alg": "RS384", "kid": kid, "n": n_b64, "e": e_b64}

    # Public JWKS the GET /.well-known/jwks.json endpoint serves.
    jwks = {"keys": [jwk]}
    jwks_path = os.path.join(_SECRETS_DIR, f"jwks_{vendor}.json")
    with open(jwks_path, "w") as fh:
        json.dump(jwks, fh, indent=2)

    up = vendor.upper()
    print("=" * 72)
    print(f"EHR signing key for vendor '{vendor}' — RSA-2048, RS384")
    print("=" * 72)
    print(f"  private key (SECRET, gitignored): {pem_path}")
    print(f"  public JWKS written to:           {jwks_path}")
    print(f"  kid (RFC-7638 thumbprint):        {kid}")
    print()
    print("Public JWK to register with the vendor (or expose via JWKS URL):")
    print(json.dumps(jwk, indent=2))
    print()
    print("Backend env wiring (local/dev): set the PEM as one line with \\n escapes —")
    print(f"  export SOLACE_{up}_KID='{kid}'")
    print(f"  export SOLACE_{up}_PRIVATE_KEY=\"$(awk 'BEGIN{{ORS=\"\\\\n\"}}1' {pem_path})\"")
    print()
    print("Production (AWS Secrets Manager) — store the PEM, reference by name:")
    print(f"  aws secretsmanager put-secret-value --secret-id solace/ehr/{vendor}-private-key \\")
    print(f"      --secret-string file://{pem_path}")
    print()
    print("JWKS endpoint env (serves all active public keys at /.well-known/jwks.json):")
    print(f"  export SOLACE_EHR_JWKS='{json.dumps(jwks)}'")
    print()
    print("Vendor JWKS URL to register:")
    print("  https://djfjrel7b1ebi.cloudfront.net/.well-known/jwks.json")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
