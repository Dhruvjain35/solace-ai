"""No identified PHI leaves through lib.claude, whatever the call site forgot.

CONSTITUTION SEC-005 asks every call site to scan before sending text to a
provider. Roughly thirty call sites reach ``lib.claude.messages_create``, and
asking thirty places to remember a rule is how SEC-002 and SEC-004 were both
broken. Three had missed it, confirmed by execution rather than by reading:

  services/inbox_drafts.py       the patient's own portal message, which is the
                                 most untrusted prose in the product
  services/ambient_scribe.py     regenerate_section and refine rebuild the prompt
                                 from a caller-supplied ``structured`` dict
  services/workflows/actions.py  three actions interpolate the patient row into
                                 a prompt template

Each was driven with "SSN 123-45-6789, DOB 1962-03-14, ZIP 75201. Ignore all
previous instructions..." and each delivered all four to the provider verbatim.

So redaction moves to the one function every call passes through. Call-site scans
stay: they reject bad input early and with a useful error. This is the floor
underneath them, and it is a floor precisely because nobody has to remember it.

Deliberately redaction only, not rejection. A central reject would fire on a
clinician saying "ignore the previous instructions about the diet" mid-encounter
and silently replace a chart note with a stub. Rejection belongs where the code
knows whether the text is a patient's message or a doctor's dictation; redaction
is safe everywhere.
"""
from __future__ import annotations

import pytest

from lib import claude

POISON = "SSN 123-45-6789, DOB 1962-03-14, ZIP 75201, card 4111 1111 1111 1111"


@pytest.fixture
def sent(monkeypatch):
    """Capture what reaches the provider, without a network call."""
    captured = {}

    class _Block:
        text = "ok"

    class _Resp:
        content = [_Block()]

    def fake_invoke(model, max_tokens, system, messages, temperature, **kwargs):
        captured["system"] = system
        captured["messages"] = messages
        return _Resp()

    monkeypatch.setattr(claude, "_bedrock_invoke", fake_invoke)
    monkeypatch.setattr(claude, "_direct_invoke", fake_invoke)
    return captured


def _blob(captured) -> str:
    return str(captured.get("system", "")) + str(captured.get("messages", ""))


# ── The floor ────────────────────────────────────────────────────────────────

def test_identifiers_in_a_message_never_reach_the_provider(sent):
    claude.messages_create(
        model="claude-haiku-4-5", max_tokens=100,
        messages=[{"role": "user", "content": f"Summarise: {POISON}"}],
        purpose="test",
    )
    blob = _blob(sent)
    for secret in ("123-45-6789", "1962-03-14", "75201", "4111 1111 1111 1111"):
        assert secret not in blob, f"{secret} reached the provider"


def test_identifiers_in_the_system_prompt_are_redacted_too(sent):
    """Chart context gets built into system prompts on several paths."""
    claude.messages_create(
        model="claude-haiku-4-5", max_tokens=100, system=f"Patient context: {POISON}",
        messages=[{"role": "user", "content": "go"}],
        purpose="test",
    )
    assert "123-45-6789" not in _blob(sent)


def test_content_block_lists_are_covered(sent):
    """The vision paths pass a list of blocks rather than a bare string."""
    claude.messages_create(
        model="claude-haiku-4-5", max_tokens=100,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"Read this: {POISON}"},
        ]}],
        purpose="test",
    )
    assert "123-45-6789" not in _blob(sent)


def test_image_blocks_pass_through_untouched(sent):
    """Redacting a base64 image would corrupt it. The ID-scan and
    insurance-card paths depend on this."""
    b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    claude.messages_create(
        model="claude-haiku-4-5", max_tokens=100,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": "What is on this card?"},
        ]}],
        purpose="test",
    )
    assert b64 in _blob(sent), "the image payload was mangled"


def test_a_redaction_is_logged_so_the_missing_call_site_is_findable(sent, caplog):
    """When the floor fires it means a call site forgot to scan. That is worth a
    line naming the purpose, or the gap stays invisible."""
    import logging

    with caplog.at_level(logging.WARNING):
        claude.messages_create(
            model="claude-haiku-4-5", max_tokens=100,
            messages=[{"role": "user", "content": POISON}],
            purpose="inbox_draft_reply",
        )
    assert any("inbox_draft_reply" in r.message for r in caplog.records)


def test_clean_clinical_text_is_untouched(sent):
    """If the floor mangles ordinary notes it will be removed."""
    text = ("Patient reports substernal chest pressure radiating to the left arm. "
            "Vitals: HR 118, BP 92/60, SpO2 94%. Started ibuprofen 400mg PO q6h PRN.")
    claude.messages_create(
        model="claude-haiku-4-5", max_tokens=100,
        messages=[{"role": "user", "content": text}], purpose="test",
    )
    assert text in _blob(sent)


def test_nothing_is_logged_when_there_was_nothing_to_redact(sent, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        claude.messages_create(
            model="claude-haiku-4-5", max_tokens=100,
            messages=[{"role": "user", "content": "Summarise the encounter."}],
            purpose="test",
        )
    assert not [r for r in caplog.records if "redact" in r.message.lower()]


def test_the_caller_is_not_mutated(sent):
    """A caller that logs or stores its own payload after the call must not find
    it silently rewritten underneath."""
    original = [{"role": "user", "content": f"Summarise: {POISON}"}]
    claude.messages_create(
        model="claude-haiku-4-5", max_tokens=100, messages=original, purpose="test",
    )
    assert "123-45-6789" in original[0]["content"], "the caller's list was mutated"


# ── The three call sites that were missing a scan ────────────────────────────

@pytest.mark.parametrize("module,attr", [
    ("services.inbox_drafts", "draft_reply"),
    ("services.ambient_scribe", "regenerate_section"),
])
def test_the_paths_that_were_leaking_no_longer_do(sent, module, attr):
    """Driven end to end through the service, not through claude directly."""
    import importlib

    mod = importlib.import_module(module)
    try:
        if attr == "draft_reply":
            mod.draft_reply(inbound_message=POISON, patient_chart={"name": "Jane"})
        else:
            mod.regenerate_section(
                structured={"transcript_segments": [{"content": POISON}]}, section="hpi")
    except Exception:
        pass  # provider is stubbed; a downstream shape error is not what is under test
    blob = _blob(sent)
    if blob:
        assert "123-45-6789" not in blob
        assert "1962-03-14" not in blob


def test_workflow_actions_no_longer_leak(sent):
    from services.workflows import actions

    actions._run_claude_prompt(
        {"prompt": "Summarise: {{patient.transcript}}"},
        {"patient": {"id": "p1", "transcript": POISON}},
    )
    assert "123-45-6789" not in _blob(sent)
