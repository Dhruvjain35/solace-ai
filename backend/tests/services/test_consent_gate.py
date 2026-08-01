"""CONSTITUTION SEC-004, enforced by a test instead of by convention.

SEC-004 (L1): no AI provider sees patient data before consent is verified.

The rule was kept by three routers copy-pasting the same six lines, and broken
by the ones written afterwards. That is the predictable outcome of a rule that
lives only in a document: it holds exactly as long as the next author remembers
it. So the rule is checked here, structurally, against the source tree.

**How a router is judged to reach AI.** By import closure, not by grep. Three
modules actually construct a provider client: ``services.transcription``,
``services.tts`` and ``lib.claude``. Everything that transitively imports one of
them can reach a provider. Substring matching was tried first and was useless in
both directions: it flagged ``routers/admin.py`` for the word "Whisper" in a
comment and ``routers/wave4.py`` for a local variable named ``differential``,
while missing nine routers that genuinely reach a provider through a service.

**What the rule requires.** Not every AI call needs a patient's signature, and
pretending otherwise would produce a gate everyone learns to bypass:

  * A route a *patient* hits (unauthenticated, or authenticated as the patient)
    that sends what they supply to a provider needs their authorization under
    HIPAA §164.508. That is what ``lib.consent.require`` enforces.

  * A route a *clinician* hits, acting on a chart they are already treating
    from, runs under treatment and operations. §164.508 does not apply. Those
    are recognised by their auth dependency, automatically, with no list to
    maintain.

So the test only demands a gate where the route is unauthenticated. That keeps
the requirement narrow enough to be true, which is the only way it survives.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import HTTPException

from lib import consent

BACKEND = pathlib.Path(__file__).resolve().parents[2]

# The only three modules that construct an AI provider client. Verified by
# unparsing each module with docstrings stripped, so prose about AI cannot
# masquerade as a call to it.
PROVIDER_LEAVES = {
    "services.transcription", "services.tts", "lib.claude",
    "services.voice_agent.tts_cache",
}

# Modules that enforce SEC-004 themselves, so a path to a provider through one
# of them is already gated and does not oblige the caller to gate again.
#
# ``services.workflows.actions`` is the one that matters. Fifteen routers can
# trigger a workflow, and three workflow actions interpolate the patient row
# into a Claude prompt. Gating in ``actions.run`` covers all fifteen at once.
# Requiring a consent form field on "cancel my appointment" instead would be
# theatre, and gates that are theatre are the ones people learn to bypass.
#
# An entry here is a claim that must be proved: ``test_each_gated_boundary_
# actually_gates`` calls into each one and asserts it refuses.
GATED_BOUNDARIES = {"services.workflows.actions"}

_AUTH_HINTS = (
    "require_clinician", "current_clinician", "require_auth", "clinician",
    "require_admin", "verify_token", "get_current",
)

# Unauthenticated routes on AI-reaching routers that are exempt, with the reason.
# Keyed "module:path" so exempting one route never silently exempts its
# neighbours. Anything not listed and not gated fails.
ALLOWED_UNGATED: dict[str, str] = {
    "cds_hooks_router:/cds-services": (
        "Static service discovery. Returns our own capability list and no "
        "patient data, and calls no provider."
    ),
    "cds_hooks_router:/cds-services/solace-patient-view": (
        "CDS Hooks. Invoked server-to-server by the EHR on behalf of a "
        "clinician who has the chart open, on data the EHR already holds. "
        "Treatment and operations. Caller identity is the EHR's signed JWT, "
        "which is an authentication concern, not a §164.508 one."
    ),
    "cds_hooks_router:/cds-services/solace-order-select": "As patient-view above.",
    "cds_hooks_router:/cds-services/solace-order-sign": "As patient-view above.",
    "cds_hooks_router:/cds-services/solace-encounter-discharge": "As patient-view above.",
    # The two openers do not gate — they are what creates the thing to gate on.
    # Their obligation is the opposite one, and it is checked by
    # test_the_call_opener_plays_the_disclosure below rather than waived here.
    "voice:/incoming": (
        "Plays the disclosure and records it on the session. Sends no caller "
        "data to a provider: the only thing synthesised is our own greeting. "
        "The caller has not spoken yet at this point in the call."
    ),
    "voice:/simulator/start": "As /incoming above, for the browser simulator.",
    "voice:/status": (
        "Twilio call-status callback. Marks the session ended. Reads no caller "
        "content and calls no provider."
    ),
    "voice:/simulator/end": "Ends a simulator session. Calls no provider.",
    "identity:/identity/lookup": (
        "Sends nothing to a provider. Matches name and date of birth against "
        "the connected EHR and returns what the EHR already holds. It is in an "
        "AI-reaching module only because /scan-id next door is. Its real "
        "exposure is PHI enumeration, which is SEC-003's job and is handled: "
        "blocklist and per-identity quota run before the query."
    ),
}


# ── Static analysis of the tree ──────────────────────────────────────────────

def _module_name(path: pathlib.Path) -> str:
    return str(path.relative_to(BACKEND).with_suffix("")).replace("/", ".").removesuffix(".__init__")


def _source_modules() -> dict[str, pathlib.Path]:
    skip = {"tests", ".venv", "node_modules", "__pycache__", "scripts"}
    return {
        _module_name(p): p
        for p in BACKEND.glob("**/*.py")
        if not skip & set(p.relative_to(BACKEND).parts)
    }


def _import_edges(modules: dict[str, pathlib.Path]) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for name, path in modules.items():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a broken file fails its own tests
            continue
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                deps.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                deps.add(node.module)
                deps.update(f"{node.module}.{a.name}" for a in node.names)
        edges[name] = deps
    return edges


def _reaches_provider() -> set[str]:
    """Every module that can reach a provider on a path that is not already
    gated for it.

    A gated boundary is absorbing: it is in the set itself, since it does reach
    a provider, but it does not pass the obligation up to its importers, because
    it discharges that obligation on their behalf.
    """
    edges = _import_edges(_source_modules())
    reached = set(PROVIDER_LEAVES)
    changed = True
    while changed:
        changed = False
        for name, deps in edges.items():
            if name in reached:
                continue
            if deps & (reached - GATED_BOUNDARIES):
                reached.add(name)
                changed = True
    return reached | GATED_BOUNDARIES


def _routes(path: pathlib.Path):
    """(method, route, is_authenticated, gates_consent) for each route."""
    out = []
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
        route = deco.args[0].value if deco.args and isinstance(deco.args[0], ast.Constant) else "?"
        signature = ast.unparse(node.args) + ast.unparse(node.decorator_list)
        # The gate is looked for in *this handler*, not anywhere in the module.
        # A module-wide check would mean gating one route silently vouches for
        # its neighbours, which is the same "looks covered, isn't" failure that
        # SEC-002 had.
        body = ast.unparse(node)
        # Two shapes of gate, because there are two shapes of consent. A form
        # post carries a field, so require() reads it. A phone call carries
        # nothing, so for_call() reads back the disclosure the caller heard.
        gated = "consent.require(" in body or "consent.for_call(" in body
        out.append((
            deco.func.attr.upper(), route,
            any(h in signature for h in _AUTH_HINTS),
            gated,
        ))
    return out


AI_ROUTERS = sorted(n for n in _reaches_provider() if n.startswith("routers."))
UNGATED_ROUTES = [
    (name, method, route)
    for name in AI_ROUTERS
    for method, route, authed, gated in _routes(BACKEND / f"{name.replace('.', '/')}.py")
    if not authed and not gated
]


# ── The structural rule ──────────────────────────────────────────────────────

def test_the_analysis_finds_something():
    """A structural test that matches nothing passes for free and proves
    nothing. These floors are well under the real counts, so they catch the
    analysis silently breaking without becoming a maintenance chore."""
    assert len(AI_ROUTERS) >= 8, f"import closure looks broken: {AI_ROUTERS}"
    assert any(r == "routers.voice" for r in AI_ROUTERS), "voice must stay in scope"
    assert any(not a for _, _, a, _ in _routes(BACKEND / "routers/voice.py")), \
        "route auth classification looks broken"


def test_provider_leaves_are_still_the_only_leaves():
    """If someone adds a fourth module that calls a provider directly, the
    closure above silently stops covering it. This is the tripwire."""
    calls = ("anthropic.", "openai.", "OpenAI(", "Anthropic(", "AsyncAnthropic(",
             'client("bedrock', "client('bedrock", "bedrock-runtime", "polly")
    found = set()
    for name, path in _source_modules().items():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):  # blank out docstrings so prose cannot match
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                node.value.value = ""
        if any(c in ast.unparse(tree) for c in calls):
            found.add(name)
    new = found - PROVIDER_LEAVES
    assert not new, (
        f"these modules call an AI provider directly and are not in "
        f"PROVIDER_LEAVES: {sorted(new)}. Add them, then re-run: the consent "
        f"closure does not currently cover anything that only reaches AI "
        f"through them."
    )


@pytest.mark.parametrize(
    "module,method,route",
    UNGATED_ROUTES,
    ids=[f"{m.split('.')[-1]}:{r}" for m, _, r in UNGATED_ROUTES],
)
def test_unauthenticated_ai_routes_gate_consent(module: str, method: str, route: str):
    """The rule. An unauthenticated route on a module that can reach an AI
    provider is a patient-facing surface, and needs the patient's §164.508
    authorization before anything they supply goes to a provider."""
    key = f"{module.split('.')[-1]}:{route}"
    assert key in ALLOWED_UNGATED and ALLOWED_UNGATED[key].strip(), (
        f"{method} {route} in {module} is unauthenticated and can reach an AI "
        f"provider, but does not call lib.consent.require(). Either gate it, or "
        f"add {key!r} to ALLOWED_UNGATED with the basis that makes it lawful "
        f"without the patient's authorization."
    )


def test_exemptions_still_correspond_to_real_routes():
    """An exemption for a route that no longer exists is dead weight that makes
    the list look scarier than it is. Delete it when the route goes."""
    live = {f"{m.split('.')[-1]}:{r}" for m, _, r in UNGATED_ROUTES}
    stale = set(ALLOWED_UNGATED) - live
    assert not stale, f"ALLOWED_UNGATED exempts routes that no longer exist: {sorted(stale)}"


def test_no_router_reimplements_the_gate():
    """Three routers each had their own copy of the check. Three copies is how
    a fourth file gets written without one, and how a fix to the parsing has to
    be applied in three places and gets applied in two."""
    offenders = []
    for module in AI_ROUTERS:
        source = (BACKEND / f"{module.replace('.', '/')}.py").read_text()
        if "consent_granted" in source and "consent.require(" not in source:
            offenders.append(module)
    assert not offenders, (
        f"these routers check consent with their own inline copy: {offenders}. "
        f"Call lib.consent.require() so there is one implementation to audit."
    )


# ── The phone path ───────────────────────────────────────────────────────────

def test_the_call_opener_plays_the_disclosure():
    """/incoming and /simulator/start are exempt from the gate because they are
    what makes the gate satisfiable. That exemption is only honest while they
    actually play the disclosure and record it, so that is asserted here rather
    than assumed."""
    source = (BACKEND / "routers/voice.py").read_text()
    for handler in ("twilio_incoming", "simulator_start"):
        body = next(
            ast.unparse(n) for n in ast.walk(ast.parse(source))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == handler
        )
        assert "opening_for" in body, f"{handler} no longer plays the disclosure"
        assert "record_disclosure" in body, f"{handler} does not record what it played"


def test_the_greeting_alone_is_never_what_the_caller_hears():
    """The bare greeting says "Hi, this is Solace at X. How can I help?" and
    discloses nothing. If a handler goes back to using GREETINGS directly, the
    caller stops being told the call is recorded."""
    source = (BACKEND / "routers/voice.py").read_text()
    assert "prompts.GREETINGS" not in source, (
        "routers/voice.py reads GREETINGS directly. Use prompts.opening_for(), "
        "which prefixes the disclosure."
    )


def test_every_greeting_language_has_a_disclosure():
    """A caller routed to Spanish must not silently fall back to an English
    disclosure, or to none."""
    from services.voice_agent import prompts

    missing = set(prompts.GREETINGS) - set(prompts.DISCLOSURES)
    assert not missing, f"languages with a greeting but no disclosure: {sorted(missing)}"


@pytest.mark.parametrize("lang", ["en", "es", "zh", "vi", "ar", "fr", "pt", "ko", "hi", "ru"])
def test_the_opening_leads_with_the_disclosure(lang):
    """Disclosure before greeting, not after. Someone who hangs up on hearing
    "recorded" should hear it before they have said anything worth recording."""
    from services.voice_agent import prompts

    opening = prompts.opening_for(lang, "Baylor McKinney")
    assert opening.startswith(prompts.DISCLOSURES[lang])
    assert "Baylor McKinney" in opening


def test_an_unknown_language_still_gets_a_disclosure():
    from services.voice_agent import prompts

    opening = prompts.opening_for("xx", "Baylor McKinney")
    assert prompts.DISCLOSURES["en"] in opening


def test_a_session_without_a_disclosure_cannot_reach_a_provider():
    """The case that matters most: sessions that already exist. Every call
    started before this shipped has no disclosure field, and those callers
    genuinely were never told."""
    assert consent.for_call({"call_id": "sim-old", "status": "active"}) is False
    assert consent.for_call({}) is False
    assert consent.for_call(None) is False


def test_a_session_with_a_disclosure_may_proceed():
    from services.voice_agent import prompts

    rec = {"call_id": "sim-1", **consent.record_disclosure(prompts.DISCLOSURE_VERSION)}
    assert consent.for_call(rec) is True
    assert rec["disclosure_version"] == prompts.DISCLOSURE_VERSION
    assert rec["disclosure_played_at"].endswith("Z")


def test_explicit_mode_needs_more_than_a_disclosure(monkeypatch):
    """Whether continuing to speak is consent is a decision for the deploying
    hospital's counsel. In explicit mode a disclosure alone is not enough."""
    from lib.config import settings
    from services.voice_agent import prompts

    monkeypatch.setattr(settings, "voice_consent_mode", "explicit", raising=False)
    rec = {"call_id": "sim-2", **consent.record_disclosure(prompts.DISCLOSURE_VERSION)}
    assert consent.for_call(rec) is False

    rec["consent_affirmed"] = "yes"
    assert consent.for_call(rec) is True


def test_an_unrecognised_consent_mode_falls_back_to_disclosure(monkeypatch):
    """A typo in an env var must not silently disable the phone service, nor
    silently drop to a weaker basis than either named mode."""
    from lib.config import settings
    from services.voice_agent import prompts

    monkeypatch.setattr(settings, "voice_consent_mode", "Explicitt", raising=False)
    rec = {"call_id": "sim-3", **consent.record_disclosure(prompts.DISCLOSURE_VERSION)}
    assert consent.for_call(rec) is True


# ── The workflow choke point ─────────────────────────────────────────────────

def test_every_ai_action_is_declared():
    """AI_ACTIONS is what actions.run gates on. An AI action missing from it
    fails open, so this asserts the list matches the handlers that actually
    reach lib.claude."""
    from services.workflows import actions

    src = (BACKEND / "services/workflows/actions.py").read_text()
    tree = ast.parse(src)
    reaching = {
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and "claude.messages_create" in ast.unparse(n)
    }
    declared = {
        a.handler.__name__ for a in actions.ACTIONS if a.type in actions.AI_ACTIONS
    }
    assert reaching == declared, (
        f"handlers reaching Claude: {sorted(reaching)}; declared in AI_ACTIONS: "
        f"{sorted(declared)}. Any difference means an AI action runs ungated."
    )


@pytest.mark.parametrize("action_type", ["run_claude_prompt", "draft_message", "generate_letter"])
def test_a_workflow_ai_action_is_blocked_without_recorded_consent(action_type):
    """The indirect path. Fifteen routers can trigger a workflow, and a prompt
    can interpolate {{patient.*}}, so this is a live route from an appointment
    booking to a patient's chart landing in a Claude prompt."""
    from services.workflows import actions

    result = actions.run(
        action_type,
        {"prompt": "Summarise {{patient.symptoms}}", "output_key": "summary"},
        {"patient": {"id": "p-1", "symptoms": "chest pain since Tuesday"}},
    )
    assert result["success"] is False
    assert result["reason"] == "blocked_no_consent"


def test_a_workflow_ai_action_is_blocked_when_there_is_no_patient_at_all():
    """No patient in context means no consent record to check, which is a no."""
    from services.workflows import actions

    result = actions.run("run_claude_prompt", {"prompt": "hello"}, {})
    assert result == {"success": False, "reason": "blocked_no_consent"}


def test_non_ai_workflow_actions_are_not_gated():
    """Sending an SMS or writing an audit line does not put anything in front of
    a model, and gating it would train people to grant consent for everything."""
    from services.workflows import actions

    result = actions.run("audit_log", {"message": "workflow ran"}, {"patient": {"id": "p-1"}})
    assert result.get("reason") != "blocked_no_consent"


def test_a_blocked_workflow_action_is_audited(monkeypatch):
    recorded = {}
    from lib import audit
    from services.workflows import actions

    monkeypatch.setattr(audit, "record", lambda **kw: recorded.update(kw))
    actions.run("run_claude_prompt", {"prompt": "x"}, {"patient": {"id": "p-9"}})
    assert recorded.get("action") == "workflow.run_claude_prompt_no_consent"
    assert recorded.get("status_code") == 403


def test_a_workflow_ai_action_runs_when_consent_is_on_the_record(monkeypatch):
    """The gate has to let the legitimate case through, or the product does
    nothing and someone removes the gate."""
    from services.workflows import actions

    called = {}

    class _Block:
        text = "summary text"

    class _Resp:
        content = [_Block()]

    def fake_create(**kwargs):
        called.update(kwargs)
        return _Resp()

    import lib.claude as claude_mod
    monkeypatch.setattr(claude_mod, "messages_create", fake_create)
    monkeypatch.setattr(actions.storage, "get_patient", lambda pid: {"id": pid})
    monkeypatch.setattr(actions.storage, "update_patient", lambda pid, patch: None)

    result = actions.run(
        "run_claude_prompt",
        {"prompt": "Summarise {{patient.symptoms}}", "output_key": "summary"},
        {"patient": {"id": "p-2", "symptoms": "cough",
                     "consent_granted_at": "2026-07-01T10:00:00Z"}},
    )
    assert result["success"] is True
    assert called, "Claude was never called on the consented path"


# ── The gate itself ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES", " true "])
def test_affirmative_values_pass(value):
    assert consent.granted(value) is True
    consent.require(value, action="test.ok")  # must not raise


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "false", "0", "no", "maybe", "tru", "null", "undefined", "[]", "on"],
)
def test_everything_else_is_a_refusal(value):
    """Consent is the one field where an ambiguous parse must never resolve in
    our favour. ``"undefined"`` is what a JavaScript client sends when the
    variable was never set, and ``"on"`` is what an HTML checkbox posts, which
    looks affirmative and is not evidence anyone read anything."""
    assert consent.granted(value) is False
    with pytest.raises(HTTPException) as exc:
        consent.require(value, action="test.refused")
    assert exc.value.status_code == 403


def test_non_string_input_does_not_crash_the_gate():
    """A JSON body can deliver a bool, a number or a list where a form would
    deliver a string. None of those may raise on the way to a decision."""
    for value in (True, False, 1, 0, [], {}, 1.0):
        assert isinstance(consent.granted(value), bool)


def test_python_true_is_accepted_but_truthiness_is_not():
    """A JSON ``true`` is a real affirmative. A non-empty list is not: bare
    truthiness would let ``["maybe"]`` through."""
    assert consent.granted(True) is True
    assert consent.granted(["yes"]) is False


def test_refusal_is_audited(monkeypatch):
    recorded = {}
    from lib import audit
    monkeypatch.setattr(audit, "record", lambda **kw: recorded.update(kw))

    with pytest.raises(HTTPException):
        consent.require(None, action="abuse.transcribe_no_consent",
                        identity="ident-1", source_ip="203.0.113.7")

    assert recorded["action"] == "abuse.transcribe_no_consent"
    assert recorded["status_code"] == 403
    assert recorded["source_ip"] == "203.0.113.7"


def test_a_grant_is_not_audited_as_abuse(monkeypatch):
    """Only refusals belong in the abuse log. Writing a line per successful
    intake would bury the real signal."""
    calls = []
    from lib import audit
    monkeypatch.setattr(audit, "record", lambda **kw: calls.append(kw))
    consent.require("true", action="test.granted")
    assert calls == []


def test_an_audit_failure_still_refuses(monkeypatch):
    """If the audit backend is down the answer is still no. A logging problem
    must never widen access."""
    from lib import audit

    def boom(**kwargs):
        raise RuntimeError("audit backend unavailable")

    monkeypatch.setattr(audit, "record", boom)
    with pytest.raises(HTTPException) as exc:
        consent.require("false", action="test.audit_down")
    assert exc.value.status_code == 403


# ── The consent record §164.508 requires ─────────────────────────────────────

def test_a_grant_produces_a_record_of_what_was_agreed_to():
    """"They consented" is not defensible on its own. §164.508 asks what they
    were shown, so the version of the authorization text is part of the record
    and defaults rather than going missing."""
    rec = consent.record_of("true", version=None)
    assert rec["granted"] is True
    assert rec["version"] == consent.CURRENT_VERSION
    assert rec["granted_at"].endswith("Z")


def test_the_recorded_version_is_the_one_the_patient_saw():
    rec = consent.record_of("true", version="2025-03")
    assert rec["version"] == "2025-03"


def test_a_refusal_records_no_timestamp():
    rec = consent.record_of("no", version="2025-03")
    assert rec["granted"] is False
    assert rec["granted_at"] is None
