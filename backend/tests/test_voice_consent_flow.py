"""The voice path, driven through the real routes.

``tests/services/test_consent_gate.py`` proves the gate exists by reading the
source. That is worth having and is not the same as proving it works: SEC-002
also had correct-looking code at the cited lines and leaked anyway. So this file
makes actual requests and asserts on what a caller would hear and on whether a
transcription provider is ever reached.

The specific thing being guarded: ``routers/voice.py`` used to answer with
"Hi, this is Solace at {hospital}. How can I help?" and then transcribe whatever
the caller said. Nobody was told it was a recording, nobody was told it was AI,
and nothing checked. A caller could describe their symptoms to a third-party
model believing they were talking to the front desk.
"""
from __future__ import annotations

import os
import uuid

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib.config import settings  # noqa: E402

settings.solace_mode = "local"

from main import app  # noqa: E402
from services.voice_agent import prompts, session  # noqa: E402


@pytest.fixture
def client():
    """Unique User-Agent per test: the abuse counters key on an IP+UA hash, and
    a shared identity makes tests accumulate against each other's quota."""
    return TestClient(app, headers={"User-Agent": f"pytest-{uuid.uuid4().hex}"})


@pytest.fixture
def spoken(monkeypatch):
    """Capture the text that becomes audio.

    The TwiML says ``<Play>https://.../abc.mp3</Play>`` — the words the caller
    hears are not in the response body, they are inside a cached MP3. Asserting
    against the XML would therefore pass whatever the wording was, including no
    wording at all. So this intercepts the layer that turns text into audio,
    which is the last place the actual sentence exists.
    """
    said: list[str] = []
    from services.voice_agent import tts_cache

    def capture(text, language="en", **kwargs):
        said.append(text)
        return f"https://audio.test/{len(said)}.mp3"

    monkeypatch.setattr(tts_cache, "get_or_generate", capture)
    return said


@pytest.fixture
def no_provider(monkeypatch):
    """Fail loudly if anything reaches a transcription provider.

    Asserting "the response was a hangup" is weaker than asserting the audio was
    never sent, because a route could transcribe first and refuse afterwards.
    The provider call is the thing SEC-004 is actually about.
    """
    calls = []

    def explode(*args, **kwargs):
        calls.append(kwargs)
        raise AssertionError("a transcription provider was called")

    from services import transcription
    monkeypatch.setattr(transcription, "transcribe", explode)
    return calls


# ── What the caller hears ────────────────────────────────────────────────────

def test_the_first_thing_a_caller_hears_is_the_disclosure(client, spoken):
    r = client.post("/api/voice/incoming", data={
        "CallSid": f"CA{uuid.uuid4().hex}", "From": "+15125550100", "To": "+15125550199",
    })
    assert r.status_code == 200
    assert len(spoken) == 1, "the opening was not spoken exactly once"
    opening = spoken[0]
    assert "automated assistant" in opening
    assert "recorded and transcribed" in opening
    # And it comes before the greeting, not after.
    assert opening.index("automated assistant") < opening.index("How can I help")


def test_the_disclosure_is_recorded_on_the_session(client):
    call_sid = f"CA{uuid.uuid4().hex}"
    client.post("/api/voice/incoming", data={
        "CallSid": call_sid, "From": "+15125550100", "To": "+15125550199",
    })
    rec = session.get(call_sid)
    assert rec["disclosure_played_at"].endswith("Z")
    assert rec["disclosure_version"] == prompts.DISCLOSURE_VERSION
    assert rec["consent_mode"] in {"disclosure", "explicit"}


def test_the_caller_is_told_how_to_reach_a_person(client, spoken):
    """A disclosure that offers no way out is a notice, not a choice."""
    client.post("/api/voice/incoming", data={
        "CallSid": f"CA{uuid.uuid4().hex}", "From": "+1", "To": "+2",
    })
    assert "agent" in spoken[0].lower()


# ── The gate on the transcription step ───────────────────────────────────────

def test_a_call_with_no_disclosure_never_reaches_a_provider(client, no_provider):
    """The migration case. Sessions started before this shipped carry no
    disclosure, and their callers were never told anything."""
    call_id = f"CA{uuid.uuid4().hex}"
    session.start(hospital_id="demo", caller_phone="+15125550100",
                  language="en", channel="twilio", twilio_call_sid=call_id)
    # Deliberately not calling /incoming: this session predates the disclosure.

    r = client.post(f"/api/voice/turn/{call_id}", data={
        "RecordingUrl": "https://api.twilio.com/recordings/RE123",
    })

    assert r.status_code == 200
    assert "<Hangup/>" in r.text
    assert no_provider == [], "audio was sent despite no disclosure"


def test_a_refused_call_is_ended_rather_than_left_open(client, no_provider):
    call_id = f"CA{uuid.uuid4().hex}"
    session.start(hospital_id="demo", caller_phone="+1", language="en",
                  channel="twilio", twilio_call_sid=call_id)
    client.post(f"/api/voice/turn/{call_id}", data={"RecordingUrl": "https://x/RE1"})
    assert session.get(call_id)["status"] != "active"


def test_a_refused_caller_is_pointed_at_a_human(client, no_provider, spoken):
    """The caller does not need our compliance problem, they need the clinic."""
    call_id = f"CA{uuid.uuid4().hex}"
    session.start(hospital_id="demo", caller_phone="+1", language="en",
                  channel="twilio", twilio_call_sid=call_id)
    client.post(f"/api/voice/turn/{call_id}", data={"RecordingUrl": "https://x/RE1"})
    assert "front desk" in spoken[0]


def test_a_disclosed_call_does_reach_the_provider(client, monkeypatch):
    """The gate has to let the legitimate call through. A gate that blocks
    everything passes every refusal test above and ships a dead phone line.

    Patched at ``_whisper_from_twilio_url`` rather than at ``transcribe``,
    because that helper downloads from Twilio first. Patching the deeper symbol
    leaves the download in the path, where it fails with no network and lands in
    the "caller said nothing" branch — a 200, and a test that passes without the
    gate ever being crossed.
    """
    reached = []
    monkeypatch.setattr("routers.voice._whisper_from_twilio_url",
                        lambda url: reached.append(url) or "I need an appointment")

    call_sid = f"CA{uuid.uuid4().hex}"
    client.post("/api/voice/incoming", data={
        "CallSid": call_sid, "From": "+15125550100", "To": "+15125550199",
    })
    r = client.post(f"/api/voice/turn/{call_sid}", data={
        "RecordingUrl": "https://api.twilio.com/recordings/RE123",
    })
    assert r.status_code == 200
    assert reached == ["https://api.twilio.com/recordings/RE123"], \
        "the disclosed call never reached the transcription step"


# ── The simulator, which is equally public ───────────────────────────────────

def test_the_simulator_also_discloses(client):
    r = client.post("/api/voice/simulator/start", data=None,
                    json={"hospital_id": "demo", "language": "en"})
    assert r.status_code == 200
    assert "automated assistant" in r.json()["say"]


def test_the_simulator_discloses_in_the_callers_language(client):
    r = client.post("/api/voice/simulator/start",
                    json={"hospital_id": "demo", "language": "es"})
    assert r.status_code == 200
    assert prompts.DISCLOSURES["es"] in r.json()["say"]


def test_a_simulator_session_without_a_disclosure_is_refused(client):
    rec = session.start(hospital_id="demo", caller_phone=None,
                        language="en", channel="simulator")
    r = client.post("/api/voice/simulator/turn",
                    json={"call_id": rec["call_id"], "text": "I have chest pain"})
    assert r.status_code == 403


def test_a_disclosed_simulator_session_proceeds(client):
    start = client.post("/api/voice/simulator/start",
                        json={"hospital_id": "demo", "language": "en"})
    call_id = start.json()["call_id"]
    r = client.post("/api/voice/simulator/turn",
                    json={"call_id": call_id, "text": "I need to book an appointment"})
    assert r.status_code != 403
