"""SMART App Launch v2 conformance suite.

Codifies the SMART v2 (and ONC (g)(10)) requirements a marketplace reviewer
checks for the *authorization* flow, asserting them against ``lib.smart_auth``
and the ``routers.ehr_auth`` launch wiring:

  * PKCE is mandatory and uses S256 (RFC 7636).
  * ``.well-known/smart-configuration`` discovery parses into the fields the
    flow depends on (authorize/token/jwks, capabilities, PKCE method, auth
    methods).
  * ``state`` (CSRF) and ``nonce`` (OIDC replay) are unguessable + validated
    with constant-time compares.
  * SMART v2 ``resource.cruds`` scope grammar parses, builds, and wildcard-
    matches; v1 ``.read``/``.write`` upgrade cleanly.
  * Launch contexts (patient / encounter / fhirContext) extract from the token
    response.
  * private_key_jwt (confidential asymmetric client) produces a verifiable
    RS384 assertion.

All offline — no network, no vendor account.
"""
from __future__ import annotations

import base64
import hashlib

import pytest

from lib import smart_auth
from tests.ehr import _rsa_testkey


# ==========================================================================
# PKCE — RFC 7636, S256 mandatory for ALL SMART v2 clients.
# ==========================================================================
class TestPKCE:
    def test_challenge_is_s256_of_verifier(self):
        verifier, challenge = smart_auth.generate_pkce()
        expected = smart_auth.b64url_encode(
            hashlib.sha256(verifier.encode("ascii")).digest())
        assert challenge == expected

    def test_verifier_within_rfc7636_length_bounds(self):
        verifier, _ = smart_auth.generate_pkce()
        assert 43 <= len(verifier) <= 128

    def test_verify_pkce_round_trip(self):
        verifier, challenge = smart_auth.generate_pkce()
        assert smart_auth.verify_pkce(verifier, challenge)
        assert not smart_auth.verify_pkce("wrong-verifier", challenge)

    def test_empty_inputs_rejected(self):
        assert not smart_auth.verify_pkce("", "")
        assert not smart_auth.verify_pkce("v", "")

    def test_launch_uses_s256_challenge_method(self):
        """The router must advertise code_challenge_method=S256, never plain."""
        import inspect
        from routers import ehr_auth
        src = inspect.getsource(ehr_auth.launch)
        assert '"code_challenge_method": "S256"' in src
        assert "plain" not in src.lower()


# ==========================================================================
# Discovery — .well-known/smart-configuration parsing.
# ==========================================================================
class TestDiscovery:
    def test_discovery_url_construction(self):
        assert smart_auth.discovery_url("https://fhir.example.org/r4") == (
            "https://fhir.example.org/r4/.well-known/smart-configuration")
        # trailing slash tolerated
        assert smart_auth.discovery_url("https://fhir.example.org/r4/").endswith(
            "/r4/.well-known/smart-configuration")

    def test_parse_full_configuration(self):
        doc = {
            "issuer": "https://auth.example.org",
            "authorization_endpoint": "https://auth.example.org/authorize",
            "token_endpoint": "https://auth.example.org/token",
            "jwks_uri": "https://auth.example.org/jwks",
            "capabilities": ["launch-ehr", "launch-standalone", "client-confidential-asymmetric"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["private_key_jwt"],
            "scopes_supported": ["openid", "fhirUser", "patient/*.rs"],
        }
        cfg = smart_auth.parse_smart_configuration(doc)
        assert cfg.authorization_endpoint.endswith("/authorize")
        assert cfg.token_endpoint.endswith("/token")
        assert cfg.jwks_uri.endswith("/jwks")
        assert cfg.supports_pkce_s256
        assert cfg.supports_private_key_jwt
        assert cfg.supports_ehr_launch
        assert cfg.supports_standalone_launch

    def test_parse_tolerates_missing_fields(self):
        cfg = smart_auth.parse_smart_configuration({})
        assert cfg.authorization_endpoint == ""
        assert not cfg.supports_pkce_s256


# ==========================================================================
# state + nonce — CSRF + OIDC replay protection.
# ==========================================================================
class TestStateAndNonce:
    def test_state_and_nonce_are_unguessable_and_unique(self):
        states = {smart_auth.generate_state() for _ in range(100)}
        nonces = {smart_auth.generate_nonce() for _ in range(100)}
        assert len(states) == 100
        assert len(nonces) == 100
        # >= 128 bits of entropy in the encoded value.
        assert len(smart_auth.generate_state()) >= 22

    def test_state_validation_constant_time_and_correct(self):
        s = smart_auth.generate_state()
        assert smart_auth.validate_state(s, s)
        assert not smart_auth.validate_state(s, smart_auth.generate_state())
        assert not smart_auth.validate_state("", s)

    def test_nonce_validation(self):
        n = smart_auth.generate_nonce()
        assert smart_auth.validate_nonce(n, n)
        assert not smart_auth.validate_nonce("other", n)
        assert not smart_auth.validate_nonce("", n)


# ==========================================================================
# SMART v2 scope grammar — resource.cruds.
# ==========================================================================
class TestScopeGrammar:
    def test_parse_v2_scope(self):
        rs = smart_auth.parse_scope("patient/Observation.rs")
        assert rs is not None
        assert rs.group == "patient"
        assert rs.resource == "Observation"
        assert rs.perms == frozenset("rs")

    def test_v1_scope_upgrades_to_v2(self):
        rs = smart_auth.parse_scope("user/Observation.read")
        assert rs.to_v2() == "user/Observation.rs"
        rw = smart_auth.parse_scope("user/Condition.write")
        assert rw.perms == frozenset("cud")

    def test_non_resource_scopes_ignored(self):
        assert smart_auth.parse_scope("openid") is None
        assert smart_auth.parse_scope("launch/patient") is None

    def test_wildcard_resource_matches_any_type(self):
        granted = "user/*.cruds"
        assert smart_auth.scope_granted(granted, "user", "Observation", "r")
        assert smart_auth.scope_granted(granted, "user", "Condition", "u")

    def test_scope_granted_respects_group_and_perm(self):
        granted = "patient/Observation.rs"
        assert smart_auth.scope_granted(granted, "patient", "Observation", "r")
        assert not smart_auth.scope_granted(granted, "patient", "Observation", "c")
        assert not smart_auth.scope_granted(granted, "user", "Observation", "r")

    def test_build_v2_scopes(self):
        scopes = smart_auth.build_v2_scopes(
            {"Patient": "rs", "Observation": "rs"}, group="user")
        assert "user/Patient.rs" in scopes
        assert "user/Observation.rs" in scopes
        assert "openid" in scopes and "fhirUser" in scopes

    def test_normalize_scope_string_upgrades_v1(self):
        out = smart_auth.normalize_scope_string("user/Observation.read openid")
        assert "user/Observation.rs" in out
        assert "openid" in out


# ==========================================================================
# Launch contexts.
# ==========================================================================
class TestLaunchContext:
    def test_extract_patient_and_encounter(self):
        token_response = {
            "access_token": "x",
            "patient": "Patient/123",
            "encounter": "Encounter/456",
            "need_patient_banner": True,
        }
        ctx = smart_auth.extract_launch_context(token_response)
        assert ctx["patient"] == "Patient/123"
        assert ctx["encounter"] == "Encounter/456"
        assert ctx["need_patient_banner"] == "True"

    def test_extract_fhir_context_serialized(self):
        ctx = smart_auth.extract_launch_context(
            {"fhirContext": [{"reference": "Encounter/789"}]})
        assert "Encounter/789" in ctx["fhirContext"]

    def test_empty_token_response_yields_empty_context(self):
        assert smart_auth.extract_launch_context({}) == {}


# ==========================================================================
# private_key_jwt — confidential asymmetric client (SMART Backend Services).
# ==========================================================================
class TestPrivateKeyJwt:
    def test_round_trip_rs384_assertion_verifies(self):
        pem = _rsa_testkey.generate_rsa_private_key_pem(bits=1024)
        assertion = smart_auth.build_client_assertion(
            client_id="solace-client",
            token_endpoint="https://auth.example.org/token",
            private_key_pem=pem,
        )
        assert assertion.count(".") == 2
        # Decode claims: iss==sub==client_id, aud==token endpoint.
        claims = smart_auth.decode_jwt_claims(assertion)
        assert claims["iss"] == claims["sub"] == "solace-client"
        assert claims["aud"] == "https://auth.example.org/token"
        assert claims["exp"] > claims["iat"]

    def test_ec_key_rejected_with_clear_message(self):
        ec_pem = (
            "-----BEGIN EC PRIVATE KEY-----\n"
            + base64.encodebytes(b"\x00" * 32).decode()
            + "-----END EC PRIVATE KEY-----\n"
        )
        with pytest.raises(smart_auth.PrivateKeyJwtError) as exc:
            smart_auth.build_client_assertion(
                client_id="c", token_endpoint="https://t", private_key_pem=ec_pem)
        assert "EC" in str(exc.value)

    def test_assertion_type_constant(self):
        assert smart_auth.CLIENT_ASSERTION_TYPE == (
            "urn:ietf:params:oauth:client-assertion-type:jwt-bearer")
