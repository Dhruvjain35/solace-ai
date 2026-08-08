"""CONSTITUTION SEC-008 — the tenant boundary, driven rather than read.

The rule says a clinician's JWT must match the hospital_id in the path. That part
works: a token minted for alpha-health calling ``/api/beta-health/...`` gets a
403 "hospital mismatch".

It is also not the attack. The attacker uses their OWN hospital in the path and
someone else's patient_id, and the path check passes cleanly while the patient
resolves globally. Eleven routes caught that with a copy-pasted three-liner. One
did not::

    GET /api/alpha-health/patients/pt-beta-001/notes
      -> 200 {"notes":[{"hospital_id":"beta-health",
                        "text":"HIV+ on ART, disclosed in confidence", ...}]}

The response carries the other hospital's id. The data knew; nothing looked.

These tests drive the boundary rather than reading it, and the structural one
derives its own scope so the twelfth route cannot happen again.
"""
from __future__ import annotations

import ast
import os
import pathlib
import uuid

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402

settings.solace_mode = "local"

from db import storage  # noqa: E402
from lib import jwt_auth  # noqa: E402
from main import app  # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTERS = BACKEND / "routers"

ALPHA = "alpha-health"
BETA = "beta-health"


@pytest.fixture
def beta_patient():
    """A patient at beta-health, with a note carrying content that makes the
    stakes obvious if it is ever returned to the wrong hospital."""
    pid = f"pt-beta-{uuid.uuid4().hex[:8]}"
    storage.put_patient({
        "patient_id": pid, "hospital_id": BETA, "name": "Beta Patient",
        "chief_complaint": "chest pain", "esi_level": 2,
    })
    storage.add_note({
        "patient_id": pid, "note_id": f"n-{uuid.uuid4().hex[:8]}", "hospital_id": BETA,
        "clinician_name": "Dr Beta", "text": "HIV+ on ART, disclosed in confidence",
        "created_at": "2026-08-01T00:00:00Z",
    })
    return pid


@pytest.fixture
def alpha_client():
    token, _ = jwt_auth.issue_token({
        "clinician_id": "c-alpha", "hospital_id": ALPHA,
        "name": "Dr Alpha", "role": "clinician",
    })
    return TestClient(app, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": f"pytest-{uuid.uuid4().hex}",
    })


# ── The check that already worked, which must keep working ───────────────────

def test_a_token_for_one_hospital_cannot_use_anothers_path(alpha_client, beta_patient):
    r = alpha_client.get(f"/api/{BETA}/patients/{beta_patient}/notes")
    assert r.status_code == 403


# ── The check that did not ───────────────────────────────────────────────────

def test_a_clinician_cannot_read_another_hospitals_notes(alpha_client, beta_patient):
    """Own hospital in the path, someone else's patient in it. The path check
    passes and there is nothing behind it."""
    r = alpha_client.get(f"/api/{ALPHA}/patients/{beta_patient}/notes")
    assert r.status_code == 404, (
        f"cross-tenant read returned {r.status_code}: {r.text[:200]}"
    )
    assert "HIV+" not in r.text
    assert BETA not in r.text


def test_the_refusal_does_not_confirm_the_patient_exists(alpha_client, beta_patient):
    """404 for a real patient at another hospital and 404 for one that does not
    exist anywhere must be indistinguishable, or the endpoint becomes an oracle
    for which ids are real patients somewhere on the platform."""
    real = alpha_client.get(f"/api/{ALPHA}/patients/{beta_patient}/notes")
    fake = alpha_client.get(f"/api/{ALPHA}/patients/pt-does-not-exist/notes")
    assert real.status_code == fake.status_code == 404
    assert real.json() == fake.json()


def test_a_clinician_can_still_read_their_own_hospitals_notes(alpha_client):
    """The boundary has to let the legitimate read through, or the product does
    not work and someone removes the check."""
    pid = f"pt-alpha-{uuid.uuid4().hex[:8]}"
    storage.put_patient({"patient_id": pid, "hospital_id": ALPHA, "name": "Alpha Patient"})
    storage.add_note({
        "patient_id": pid, "note_id": "n-a1", "hospital_id": ALPHA,
        "clinician_name": "Dr Alpha", "text": "Seen and discharged",
        "created_at": "2026-08-01T00:00:00Z",
    })
    r = alpha_client.get(f"/api/{ALPHA}/patients/{pid}/notes")
    assert r.status_code == 200
    assert "Seen and discharged" in r.text


def test_a_cross_tenant_attempt_is_audited(alpha_client, beta_patient, monkeypatch):
    recorded = []
    from lib import audit
    monkeypatch.setattr(audit, "record", lambda **kw: recorded.append(kw))

    alpha_client.get(f"/api/{ALPHA}/patients/{beta_patient}/notes")
    assert any(r.get("action") == "abuse.cross_tenant_patient_access" for r in recorded), (
        "a clinician reached for another hospital's chart and left no trace"
    )


# ── The structural rule, so the twelfth route cannot happen again ────────────

_AUTH_HINTS = ("require_clinician", "current_clinician", "require_auth", "require_admin")

# Resolving patient-scoped data without going through the shared helper.
_RESOLVERS = (
    "storage.get_patient(", "storage.list_notes(", "storage.list_prescriptions(",
)


def _clinician_patient_routes():
    """(module, route, uses_helper, resolves_directly) for clinician routes that
    take a patient_id."""
    out = []
    for path in sorted(ROUTERS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            verbs = [
                d for d in node.decorator_list
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr in {"get", "post", "put", "patch", "delete"}
            ]
            if not verbs:
                continue
            signature = ast.unparse(node.args)
            if not any(h in signature for h in _AUTH_HINTS):
                continue
            if "patient_id" not in signature:
                continue
            body = ast.unparse(node)
            route = (verbs[0].args[0].value
                     if verbs[0].args and isinstance(verbs[0].args[0], ast.Constant) else "?")
            out.append((
                path.stem, route,
                "tenancy.require_patient(" in body or "require_patient(" in body,
                any(r in body for r in _RESOLVERS),
            ))
    return out


CLINICIAN_PATIENT_ROUTES = _clinician_patient_routes()
UNSCOPED = [(m, r) for m, r, helper, resolves in CLINICIAN_PATIENT_ROUTES
            if resolves and not helper]


def test_the_route_scan_works():
    assert len(CLINICIAN_PATIENT_ROUTES) >= 10, "clinician-route detection looks broken"


@pytest.mark.parametrize("module,route", UNSCOPED,
                         ids=[f"{m}:{r}" for m, r in UNSCOPED] or ["none"])
def test_every_clinician_patient_route_scopes_to_the_hospital(module, route):
    """Any route that resolves patient-scoped data under a clinician JWT has to
    go through lib.tenancy, not its own copy of the check. Eleven copies is how
    the twelfth got written without one."""
    raise AssertionError(
        f"{route} in routers/{module}.py resolves patient data directly instead "
        f"of through tenancy.require_patient(). A clinician at another hospital "
        f"can pass any patient_id here and the JWT check will not catch it, "
        f"because they are using their own hospital in the path."
    )
