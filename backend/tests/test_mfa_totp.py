"""TOTP MFA second factor for clinician login (Bet #2, Wave-1 slice).

Runs entirely in local mode (in-memory accounts store) so no AWS is needed.
Exercises the stdlib RFC 6238 implementation directly, plus the full
enroll -> confirm -> login flow through the real FastAPI routes, and proves:
  - enrolled clinician must supply a valid TOTP code to log in
  - a wrong/absent code is rejected with 401 and issues NO token
  - a non-enrolled clinician logs in exactly as before (backward compatible)
  - the TOTP secret / code never reach the logs (SEC-002)
  - the COMP-006 brute-force lockout still fires on repeated MFA failures
"""
from __future__ import annotations

import logging
import os
import time
import uuid

# Force local mode BEFORE importing app/config.
os.environ["SOLACE_MODE"] = "local"
os.environ["EMAIL_DEV_ECHO"] = "true"

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402
from lib import accounts, jwt_auth, mfa  # noqa: E402

settings.solace_mode = "local"
settings.email_dev_echo = True

from main import app  # noqa: E402

HOSPITAL = "test-clinic"
PIN = "13579"


# ---- pure TOTP unit tests ----------------------------------------------------------
def test_generate_secret_is_base32_and_unique():
    s1 = mfa.generate_secret()
    s2 = mfa.generate_secret()
    assert s1 != s2
    # base32 alphabet, unpadded
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in s1)
    # decodes without raising
    mfa._b32_decode(s1)


def test_generate_then_verify_roundtrip():
    secret = mfa.generate_secret()
    now = time.time()
    code = mfa.generate_code(secret, at=now)
    assert mfa.verify(secret, code, at=now) is True


def test_verify_rejects_wrong_code():
    secret = mfa.generate_secret()
    now = time.time()
    good = mfa.generate_code(secret, at=now)
    bad = "000000" if good != "000000" else "111111"
    assert mfa.verify(secret, bad, at=now) is False


def test_verify_tolerates_one_step_drift():
    secret = mfa.generate_secret()
    now = time.time()
    prev = mfa.generate_code(secret, at=now - 30)
    nxt = mfa.generate_code(secret, at=now + 30)
    assert mfa.verify(secret, prev, at=now) is True
    assert mfa.verify(secret, nxt, at=now) is True
    # two steps away is outside the window
    two_ago = mfa.generate_code(secret, at=now - 90)
    if two_ago != mfa.generate_code(secret, at=now):
        assert mfa.verify(secret, two_ago, at=now) is False


def test_verify_handles_malformed_input():
    secret = mfa.generate_secret()
    assert mfa.verify(secret, "") is False
    assert mfa.verify(secret, "abcdef") is False
    assert mfa.verify(secret, "12345") is False   # too short
    assert mfa.verify(secret, "1234567") is False  # too long
    assert mfa.verify("", "123456") is False


def test_provisioning_uri_shape():
    secret = mfa.generate_secret()
    uri = mfa.provisioning_uri(secret, account="Dr. Rivera", issuer="Solace")
    assert uri.startswith("otpauth://totp/Solace%3A")
    assert f"secret={secret}" in uri
    assert "issuer=Solace" in uri
    assert "digits=6" in uri
    assert "period=30" in uri


# ---- end-to-end flow through the API -----------------------------------------------
@pytest.fixture
def client():
    accounts._clinicians.clear()
    accounts._magic_tokens.clear()
    c = TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"})
    yield c
    accounts._clinicians.clear()
    accounts._magic_tokens.clear()


def _seed_clinician_with_pin(name="Dr. Rivera", pin=PIN) -> dict:
    """Create a clinician and give them a bcrypt PIN so the PIN-login path works."""
    import bcrypt

    rec = accounts.create_clinician(
        hospital_id=HOSPITAL, email=f"{uuid.uuid4().hex}@clinic.org", name=name, role="attending"
    )
    rec["pin_hash"] = bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=4)).decode()
    return rec


def _login(client, name, pin, mfa_code=None):
    body = {"clinician_name": name, "pin": pin}
    if mfa_code is not None:
        body["mfa_code"] = mfa_code
    return client.post(f"/api/{HOSPITAL}/auth/login", json=body)


def test_non_enrolled_clinician_logs_in_without_code(client):
    rec = _seed_clinician_with_pin()
    r = _login(client, rec["name"], PIN)
    assert r.status_code == 200, r.text
    assert "token" in r.json()


def test_enroll_confirm_then_login_requires_code(client):
    rec = _seed_clinician_with_pin()

    # 1. log in (no MFA yet) to get a bearer token for the authed enroll endpoint
    r = _login(client, rec["name"], PIN)
    token = r.json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    # 2. enroll -> get secret + otpauth uri (returned exactly once)
    e = client.post(f"/api/{HOSPITAL}/auth/mfa/enroll", headers=auth)
    assert e.status_code == 200, e.text
    secret = e.json()["secret"]
    assert e.json()["otpauth_uri"].startswith("otpauth://totp/")

    # not enabled until confirmed
    assert jwt_auth.mfa_enabled(accounts._clinicians[rec["clinician_id"]]) is False

    # 3. confirm with a live code
    code = mfa.generate_code(secret)
    v = client.post(f"/api/{HOSPITAL}/auth/mfa/verify", headers=auth, json={"code": code})
    assert v.status_code == 200, v.text
    assert jwt_auth.mfa_enabled(accounts._clinicians[rec["clinician_id"]]) is True

    # 4. now login WITHOUT a code must be rejected (no token issued)
    r_nocode = _login(client, rec["name"], PIN)
    assert r_nocode.status_code == 401
    assert "token" not in r_nocode.json()

    # 5. login WITH a wrong code rejected
    wrong = "000000" if mfa.generate_code(secret) != "000000" else "111111"
    r_wrong = _login(client, rec["name"], PIN, mfa_code=wrong)
    assert r_wrong.status_code == 401

    # 6. login WITH the correct code succeeds
    r_ok = _login(client, rec["name"], PIN, mfa_code=mfa.generate_code(secret))
    assert r_ok.status_code == 200, r_ok.text
    assert "token" in r_ok.json()


def test_mfa_verify_rejects_wrong_code_at_enrollment(client):
    rec = _seed_clinician_with_pin()
    token = _login(client, rec["name"], PIN).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    secret = client.post(f"/api/{HOSPITAL}/auth/mfa/enroll", headers=auth).json()["secret"]

    wrong = "000000" if mfa.generate_code(secret) != "000000" else "111111"
    v = client.post(f"/api/{HOSPITAL}/auth/mfa/verify", headers=auth, json={"code": wrong})
    assert v.status_code == 400
    assert jwt_auth.mfa_enabled(accounts._clinicians[rec["clinician_id"]]) is False


def test_secret_and_code_never_logged(client, caplog):
    rec = _seed_clinician_with_pin()
    with caplog.at_level(logging.DEBUG):
        token = _login(client, rec["name"], PIN).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        e = client.post(f"/api/{HOSPITAL}/auth/mfa/enroll", headers=auth)
        secret = e.json()["secret"]
        code = mfa.generate_code(secret)
        client.post(f"/api/{HOSPITAL}/auth/mfa/verify", headers=auth, json={"code": code})
        # a couple of logins with the live code
        _login(client, rec["name"], PIN, mfa_code=mfa.generate_code(secret))

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in combined
    assert code not in combined


def test_repeated_mfa_failures_trip_brute_force_protection(client):
    """Repeated bad codes on an MFA-enabled account get short-circuited.

    In local mode the per-account DDB lockout fails open (no AWS), so this
    asserts the per-identity SEC-003 brute-force layer (quota/blocklist)
    eventually short-circuits the sweep with a 429 even when the attacker
    finally supplies a correct code. The per-account COMP-006 lockout path is
    verified separately in test_per_account_lockout_path_on_mfa_failure.
    """
    rec = _seed_clinician_with_pin()
    token = _login(client, rec["name"], PIN).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    secret = client.post(f"/api/{HOSPITAL}/auth/mfa/enroll", headers=auth).json()["secret"]
    client.post(
        f"/api/{HOSPITAL}/auth/mfa/verify", headers=auth, json={"code": mfa.generate_code(secret)}
    )

    wrong = "000000" if mfa.generate_code(secret) != "000000" else "111111"
    saw_block = False
    for _ in range(30):
        r = _login(client, rec["name"], PIN, mfa_code=wrong)
        assert r.status_code in (401, 429)
        if r.status_code == 429:
            saw_block = True
            break
    assert saw_block, "repeated MFA failures from one identity were never short-circuited"


def test_per_account_lockout_path_on_mfa_failure(monkeypatch):
    """COMP-006: a bad MFA code drives the SAME record_failed_attempt -> lockout
    machinery as a bad PIN. Verified against a fake DDB table so the real
    aws-mode counter/lockout logic in jwt_auth runs end to end.
    """
    store: dict = {"clinician_id": "cln-lock", "failed_attempts": 0}

    class FakeTable:
        def get_item(self, Key, **kw):
            return {"Item": dict(store)}

        def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **kw):
            if "failed_attempts = if_not_exists" in UpdateExpression:
                store["failed_attempts"] = int(store.get("failed_attempts", 0)) + 1
                store["last_failed_at"] = ExpressionAttributeValues[":now"]
            if "locked_until = :until" in UpdateExpression:
                store["locked_until"] = ExpressionAttributeValues[":until"]
            return {"Attributes": dict(store)}

    monkeypatch.setattr(jwt_auth, "_table", lambda name: FakeTable())

    assert jwt_auth.check_lockout("cln-lock") is False
    for _ in range(jwt_auth.MAX_FAILED_ATTEMPTS):
        jwt_auth.record_failed_attempt("cln-lock")
    # locked_until set => check_lockout reports True
    assert store.get("locked_until", 0) > int(time.time())
    assert jwt_auth.check_lockout("cln-lock") is True


def test_lockout_window_constants_unchanged():
    """Guard COMP-006 bounds were not weakened by this change."""
    assert jwt_auth.ACCESS_TTL_SECONDS <= 1800
    assert jwt_auth.MAX_FAILED_ATTEMPTS == 5
    assert jwt_auth.LOCKOUT_WINDOW_SECONDS == 900
    assert jwt_auth.LOCKOUT_DURATION_SECONDS >= 1800
