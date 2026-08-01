"""CONSTITUTION SEC-003, checked against the routes rather than a written scope.

SEC-003 (L1): patient endpoints must call ``blocklist.enforce(identity)`` before
any request parsing, so abusive identities are short-circuited.

The rule names three files — intake, pain_flag, voice — and cites
``routers/intake.py:69`` as its evidence. Intake does enforce. Voice, also named
in the rule's own scope, does not on any of its three Twilio routes. And the
scope was written when those were the only public endpoints; the surface has
grown since, and the document did not.

So the scope is derived here instead. Every route with no auth dependency is a
public endpoint by definition, and if it reads or writes patient data it needs
the abuse controls. What counts is what the routes do, not what a list from an
earlier version of the codebase says.

The specific defect that prompted this file: ``POST /sms/care-instructions``
carried the docstring "Throttled by the existing identity-based quota; no auth"
and called neither ``blocklist.enforce`` nor ``quota.check_and_consume``. Driving
it showed 25 of 25 rapid requests succeeding, each delivering a named patient's
discharge plan to a caller-supplied phone number. The claim was in the code; the
control was not. That is the same shape as SEC-002, where the cited lines existed
and were correct and the filter still covered almost nothing.
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
from main import app  # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTERS = BACKEND / "routers"

_AUTH_HINTS = (
    "require_clinician", "current_clinician", "require_auth", "clinician",
    "require_admin", "verify_token", "get_current",
)

# A route touches patient data if it reads or writes the patient store, the
# appointment store, or sends a message to a person.
_PATIENT_DATA = (
    "storage.get_patient", "storage.put_patient", "storage.update_patient",
    "storage.list_patients", "storage.add_appointment", "storage.cancel_appointment",
    "storage.list_appointments", "sms.send", "session.start", "session.get",
    "scheduling.lookup", "scheduling.book", "scheduling.availability",
)

# Public routes that touch patient data and do not throttle, with the reason.
# Every entry is a decision someone has to defend in review.
ALLOWED_UNTHROTTLED: dict[str, str] = {
    "voice:/status": (
        "Twilio call-status callback, not a caller-reachable endpoint. Reads no "
        "patient content and takes no argument an attacker gains from: it marks "
        "a session ended. Forging one ends a call early, which is a nuisance "
        "the blocklist would not prevent either, since Twilio's own IPs would "
        "be the identity being counted."
    ),
    "cds_hooks_router:/cds-services": (
        "Static service discovery. Returns our capability list and no patient "
        "data."
    ),
}


def _public_routes():
    """(module, method, route, throttled, touches_patient_data) per public route."""
    out = []
    for path in sorted(ROUTERS.glob("*.py")):
        if path.stem == "__init__":
            continue
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
            deco = verbs[0]
            signature = ast.unparse(node.args) + ast.unparse(node.decorator_list)
            if any(h in signature for h in _AUTH_HINTS):
                continue
            body = ast.unparse(node)
            route = deco.args[0].value if deco.args and isinstance(deco.args[0], ast.Constant) else "?"
            out.append((
                path.stem, deco.func.attr.upper(), route,
                "blocklist.enforce(" in body,
                any(marker in body for marker in _PATIENT_DATA),
            ))
    return out


PUBLIC_ROUTES = _public_routes()
NEEDS_THROTTLE = [
    (mod, method, route)
    for mod, method, route, throttled, touches in PUBLIC_ROUTES
    if touches and not throttled
]


def test_the_route_scan_found_the_public_surface():
    assert len(PUBLIC_ROUTES) >= 20, "public-route detection looks broken"
    assert any(m == "intake" for m, *_ in PUBLIC_ROUTES), "intake must stay in scope"


@pytest.mark.parametrize(
    "module,method,route", NEEDS_THROTTLE,
    ids=[f"{m}:{r}" for m, _, r in NEEDS_THROTTLE] or ["none"],
)
def test_public_routes_touching_patient_data_are_throttled(module, method, route):
    key = f"{module}:{route}"
    assert key in ALLOWED_UNTHROTTLED and ALLOWED_UNTHROTTLED[key].strip(), (
        f"{method} {route} in routers/{module}.py is public and touches patient "
        f"data but never calls blocklist.enforce(). Either add the abuse "
        f"controls, or add {key!r} to ALLOWED_UNTHROTTLED with the reason it is "
        f"safe without them."
    )


def test_exemptions_still_match_real_routes():
    live = {f"{m}:{r}" for m, _, r, _, _ in PUBLIC_ROUTES}
    stale = set(ALLOWED_UNTHROTTLED) - live
    assert not stale, f"ALLOWED_UNTHROTTLED names routes that do not exist: {sorted(stale)}"


def test_the_docstrings_do_not_claim_controls_that_are_absent():
    """The defect that started this file was a docstring promising throttling on
    a route that had none. A claim in a comment is what a reviewer reads when
    they are deciding not to look further."""
    offenders = []
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Route handlers only. A helper named _sim_identity can say it
            # exists "for simulator rate limiting" without performing any, which
            # is accurate and not the claim this is looking for.
            if not any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr in {"get", "post", "put", "patch", "delete"}
                for d in node.decorator_list
            ):
                continue
            doc = (ast.get_docstring(node) or "").lower()
            claims = any(w in doc for w in ("throttled", "rate limit", "rate-limited", "quota"))
            if claims and "quota.check" not in ast.unparse(node):
                offenders.append(f"{path.stem}:{node.name}")
    assert not offenders, (
        f"these handlers describe throttling they do not perform: {offenders}"
    )


# ── Driving the SMS route, which is where this started ───────────────────────

@pytest.fixture
def client():
    return TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"})


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound SMS instead of sending it."""
    outbox = []
    import routers.sms as sms_router

    monkeypatch.setattr(sms_router.sms, "send",
                        lambda to, body: (outbox.append((to, body)), {"success": True})[1])
    return outbox


@pytest.fixture
def victim():
    pid = f"pt-{uuid.uuid4().hex[:12]}"
    storage.put_patient({
        "patient_id": pid, "hospital_id": "demo", "name": "Jane Doe",
        "care_instructions": '["Rest and stay hydrated"]',
        "when_to_return": "if fever over 101",
        "phone": "+15125550100",
    })
    return pid


def test_care_instructions_are_rate_limited(client, sent, victim):
    """25 rapid requests all returned 200 and all sent. On a real deployment
    that is the clinic's Twilio account paying for each one."""
    statuses = [
        client.post("/api/demo/sms/care-instructions",
                    json={"patient_id": victim, "phone": "+15125550100"}).status_code
        for _ in range(25)
    ]
    assert 429 in statuses, f"no request was ever throttled: {sorted(set(statuses))}"


def test_care_instructions_only_go_to_the_number_on_file(client, sent, victim):
    """The plan is addressed to "Jane" and lists her medications. Sending it to
    whatever number the request names makes the endpoint a way to forward one
    patient's chart to any handset."""
    r = client.post("/api/demo/sms/care-instructions",
                    json={"patient_id": victim, "phone": "+15550009999"})
    assert r.status_code == 403
    assert sent == [], "PHI was sent to a number that is not on the patient record"


def test_care_instructions_still_reach_the_patient(client, sent, victim):
    """The fix must not break the feature it is protecting."""
    r = client.post("/api/demo/sms/care-instructions",
                    json={"patient_id": victim, "phone": "+15125550100"})
    assert r.status_code == 200
    assert len(sent) == 1
    assert sent[0][0] == "+15125550100"


def test_a_patient_with_no_number_on_file_can_supply_one(client, sent):
    """Not everyone gives a phone at intake. Those patients must still be able
    to get their own plan, and this is the case that makes the check a match
    rather than a lookup."""
    pid = f"pt-{uuid.uuid4().hex[:12]}"
    storage.put_patient({
        "patient_id": pid, "hospital_id": "demo", "name": "Sam Okafor",
        "care_instructions": '["Rest"]', "when_to_return": "if worse",
    })
    r = client.post("/api/demo/sms/care-instructions",
                    json={"patient_id": pid, "phone": "+15125557777"})
    assert r.status_code == 200
    assert sent[0][0] == "+15125557777"


def test_number_matching_ignores_formatting(client, sent, victim):
    """A patient typing their own number will not format it the way intake
    stored it. "(512) 555-0100" and "+15125550100" are the same phone, and
    refusing the patient their own care plan over punctuation would get this
    check removed within a week."""
    r = client.post("/api/demo/sms/care-instructions",
                    json={"patient_id": victim, "phone": "(512) 555-0100"})
    assert r.status_code == 200
    assert len(sent) == 1


def test_a_refused_send_is_audited(client, sent, victim, monkeypatch):
    recorded = []
    from lib import audit
    monkeypatch.setattr(audit, "record", lambda **kw: recorded.append(kw))

    client.post("/api/demo/sms/care-instructions",
                json={"patient_id": victim, "phone": "+15550009999"})
    assert any(r.get("status_code") == 403 for r in recorded), \
        "an attempt to send PHI elsewhere left no audit trail"
