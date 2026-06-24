"""id_token JWKS signature-verification suite.

Closes the gap the marketplace gap-checklist flagged (lib/smart_auth.py id_token
decoded-but-not-verified). Proves ``smart_auth.verify_id_token``:

  * accepts an RS256 id_token whose signature matches a published JWKS key;
  * rejects a tampered token, a wrong-key signature, alg=none, and bad
    iss/aud/nonce/exp claims;
  * degrades to a TLS-trust *fallback* (not a hard failure) when no JWKS is
    available or the key is EC — preserving the pre-existing behavior.

Uses the pure-Python RSA test keygen (no ``cryptography`` dependency).
"""
from __future__ import annotations

import time

import pytest

from lib import smart_auth
from tests.ehr import _rsa_testkey

ISSUER = "https://auth.example.org"
AUD = "solace-client"


@pytest.fixture(scope="module")
def keypair():
    return _rsa_testkey.generate_rsa_keypair(bits=1024)


@pytest.fixture
def jwks(keypair):
    n, e, _d = keypair
    return [_rsa_testkey.rsa_public_jwk(n, e, kid="test-key-1")]


def _claims(**over):
    now = int(time.time())
    base = {
        "iss": ISSUER, "aud": AUD, "nonce": "the-nonce",
        "iat": now, "exp": now + 300, "fhirUser": "Practitioner/abc",
    }
    base.update(over)
    return base


def _sign(claims, keypair, **over):
    n, e, d = keypair
    return _rsa_testkey.sign_id_token(claims, n, e, d, **over)


# ==========================================================================
# Happy path — valid signature + claims.
# ==========================================================================
class TestValidToken:
    def test_signature_verifies_against_jwks(self, keypair, jwks):
        token = _sign(_claims(), keypair)
        result = smart_auth.verify_id_token(
            token, jwks=jwks, expected_issuer=ISSUER,
            expected_audience=AUD, expected_nonce="the-nonce")
        assert result.verified is True
        assert result.fallback is False
        assert result.claims["fhirUser"] == "Practitioner/abc"

    def test_aud_as_array_accepted(self, keypair, jwks):
        token = _sign(_claims(aud=[AUD, "other-client"]), keypair)
        result = smart_auth.verify_id_token(
            token, jwks=jwks, expected_audience=AUD)
        assert result.verified


# ==========================================================================
# Tampering + wrong key — must hard-fail.
# ==========================================================================
class TestTampering:
    def test_tampered_payload_rejected(self, keypair, jwks):
        token = _sign(_claims(), keypair)
        head, _payload, sig = token.split(".")
        forged_payload = smart_auth.b64url_encode(
            b'{"iss":"https://auth.example.org","aud":"solace-client","nonce":"the-nonce","sub":"attacker"}')
        forged = f"{head}.{forged_payload}.{sig}"
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(forged, jwks=jwks)

    def test_signature_from_other_key_rejected(self, keypair, jwks):
        other = _rsa_testkey.generate_rsa_keypair(bits=1024)
        token = _sign(_claims(), other)  # signed by a key NOT in the JWKS
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(token, jwks=jwks)

    def test_alg_none_rejected(self, jwks):
        import base64
        import json

        def _b64(raw):
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        payload = _b64(json.dumps(_claims()).encode())
        token = f"{header}.{payload}."
        # alg=none has 2 dots only if we append empty sig; ensure compact form:
        token = f"{header}.{payload}.{_b64(b'')}"
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(token, jwks=jwks)


# ==========================================================================
# Claim validation — independent of signature path.
# ==========================================================================
class TestClaimChecks:
    def test_wrong_issuer_rejected(self, keypair, jwks):
        token = _sign(_claims(iss="https://evil.example.org"), keypair)
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(token, jwks=jwks, expected_issuer=ISSUER)

    def test_wrong_audience_rejected(self, keypair, jwks):
        token = _sign(_claims(aud="some-other-app"), keypair)
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(token, jwks=jwks, expected_audience=AUD)

    def test_nonce_mismatch_rejected(self, keypair, jwks):
        token = _sign(_claims(nonce="attacker-nonce"), keypair)
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(token, jwks=jwks, expected_nonce="the-nonce")

    def test_expired_token_rejected(self, keypair, jwks):
        old = int(time.time()) - 10_000
        token = _sign(_claims(iat=old, exp=old + 60), keypair)
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(token, jwks=jwks)


# ==========================================================================
# Honest fallback — preserve TLS-trust when offline verification impossible.
# ==========================================================================
class TestFallback:
    def test_no_jwks_falls_back_not_fails(self, keypair):
        token = _sign(_claims(), keypair)
        result = smart_auth.verify_id_token(
            token, jwks=None, jwks_uri="", expected_nonce="the-nonce")
        assert result.verified is False
        assert result.fallback is True
        # Nonce was still enforced even in the fallback.
        assert result.claims["nonce"] == "the-nonce"

    def test_fallback_still_enforces_nonce(self, keypair):
        token = _sign(_claims(nonce="wrong"), keypair)
        with pytest.raises(smart_auth.IdTokenVerificationError):
            smart_auth.verify_id_token(
                token, jwks=None, expected_nonce="the-nonce")

    def test_ec_alg_falls_back(self, keypair):
        # Forge a header advertising ES256 (no offline EC math) over an RSA body.
        token = _sign(_claims(), keypair, alg="ES256")
        result = smart_auth.verify_id_token(token, jwks=[{"kty": "EC", "use": "sig"}])
        assert result.fallback is True
        assert result.verified is False


# ==========================================================================
# JWK -> RSA extraction edge cases.
# ==========================================================================
class TestJwkParsing:
    def test_non_rsa_jwk_ignored(self):
        assert smart_auth._jwk_to_rsa({"kty": "EC", "x": "a", "y": "b"}) is None

    def test_kid_selects_correct_key(self, keypair):
        n, e, d = keypair
        other = _rsa_testkey.generate_rsa_keypair(bits=1024)
        jwks = [
            _rsa_testkey.rsa_public_jwk(other[0], other[1], kid="other"),
            _rsa_testkey.rsa_public_jwk(n, e, kid="test-key-1"),
        ]
        token = _rsa_testkey.sign_id_token(_claims(), n, e, d, kid="test-key-1")
        result = smart_auth.verify_id_token(token, jwks=jwks)
        assert result.verified
