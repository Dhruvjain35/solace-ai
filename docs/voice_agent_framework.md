# Solace Voice Agent — Framework Spec (groundwork only)

**Status:** Spec only. No implementation yet. This document captures the architecture
and decisions so the next session can start writing code from a known plan.

**Goal:** Hospitals route their main inbound number through Solace. Patients
calling for nurse-line questions, appointment scheduling, after-hours triage, or
general FAQ get a Claude-powered voice agent that handles 70-80% of calls
end-to-end and warm-transfers the rest to a human. The agent reuses the existing
Solace Whisper / ElevenLabs / Claude / triage stack — no parallel AI vendor list.

---

## 1. Telephony layer

**Choice: Twilio Voice + Twilio Media Streams.**

Why Twilio over Vonage / Bandwidth:
- Mature Media Streams API for bidirectional audio over WebSocket (μ-law 8kHz frames).
- BAA available for HIPAA workloads (matches Solace's existing compliance posture).
- Drop-in SIP-trunk support for hospitals that want to keep their existing PBX and
  forward only specific extensions to Solace.

**Phone-number model:** one Twilio number per hospital, configured in DynamoDB
(`solace-hospitals`). Adds a `voice_agent_config` JSON field per hospital row:

```json
{
  "twilio_phone_number": "+1...",
  "greeting_text":      "St. David's Medical Center, this is Solace.",
  "after_hours_start":  "21:00",
  "after_hours_end":    "07:00",
  "escalation_phone":   "+1...",
  "languages":          ["en", "es", "vi"],
  "default_language":   "en"
}
```

**Inbound webhook flow:**
1. Twilio POSTs to `POST /api/voice/incoming` (no hospital_id in path — we look it
   up by the `To` number).
2. We respond with TwiML:
   - `<Say>` the localized greeting (or `<Play>` a pre-rendered ElevenLabs MP3).
   - `<Connect><Stream url="wss://api.../voice/stream/{call_sid}" /></Connect>` to
     hand the audio to our WebSocket.
3. Solace holds the WebSocket; Twilio pumps μ-law frames in, we pump frames back.

**Call recording:** opt-in per hospital. If enabled, Twilio's native recording
goes to a dedicated S3 bucket (`solace-call-recordings-{account}`, CMK-encrypted,
TLS-only, 90-day lifecycle). A consent prompt plays before recording starts.

---

## 2. Real-time STT/TTS plumbing

The hard part of voice agents is latency under 800ms first-token.

**STT (caller → text):**
- Whisper isn't streaming-native — wrap it with a 600ms-window VAD-driven chunker
  (`webrtcvad` or equivalent). Each chunk is `whisper-1` sync. Acceptable for
  hackathon-grade demos; production should swap in **AssemblyAI Realtime** or
  **Deepgram Nova-2** for true streaming partials.
- Module: `backend/services/voice_agent/streaming_stt.py`.
- Falls back gracefully to text-only if STT exceeds 2s tail latency.

**TTS (text → caller):**
- ElevenLabs WebSocket streaming endpoint (`/v1/text-to-speech/{voice_id}/stream-input`)
  emits MP3 chunks as Claude tokens arrive — first audible byte ~250ms after Claude
  starts streaming.
- Module: `backend/services/voice_agent/streaming_tts.py`.
- Re-uses `eleven_multilingual_v2` so the existing 20-language patient-side
  language list works on the phone too.

**Audio codec bridge:**
- Twilio sends `audio/x-mulaw;rate=8000`. Whisper wants 16kHz PCM. Use
  `pydub`/`ffmpeg` for resample on the way in, μ-law encode on the way out.

---

## 3. Agent orchestration (Claude tool use)

A single Claude `messages.create` call with `tools=[...]` per turn. The agent has
a small toolbox; orchestration logic lives entirely in the system prompt + tool
schemas, not in our Python control flow.

**Module:** `backend/services/voice_agent/intents.py`.

**Tools the agent gets:**

| Tool                     | Purpose                                                                          | Returns to Claude                       |
|--------------------------|----------------------------------------------------------------------------------|------------------------------------------|
| `triage_symptoms`        | Run the existing `services.triage` pipeline against a transcript fragment        | ESI level + recommendation               |
| `book_appointment`       | Create an appointment row in a new `solace-appointments` DDB table               | Confirmation number + datetime           |
| `cancel_appointment`     | Mark existing appointment cancelled                                              | Success / not-found                      |
| `lookup_patient`         | EHR lookup by phone-number → existing `solace-ehr` matching                      | Patient summary or "not found"           |
| `answer_faq`             | RAG over a hospital-specific FAQ knowledge base (S3 + Bedrock embeddings later)  | Cited paragraph                          |
| `transfer_to_human`      | Issue a `<Dial>` instruction to escalation_phone                                 | Closes the agent loop                    |
| `schedule_callback`      | Queue a callback for the next available nurse                                    | Confirmation                             |
| `escalate_911`           | Hard-coded — speaks the 911 prompt and stays on the line                         | Closes the agent loop                    |

**Hard-coded triggers (bypass Claude):**
- Caller says any of: "chest pain", "can't breathe", "stroke", "bleeding heavily",
  "unconscious" → immediately call `escalate_911`.
- Multiple repeat-customer calls within 1h → auto-transfer (Claude is bad at
  recognizing distressed callers spiraling).

---

## 4. Call session state machine

**Module:** `backend/services/voice_agent/session.py`.

States:

```
GREETING ─→ IDENTIFY ─→ CLASSIFY ─→ {TRIAGE | BOOK | FAQ | TRANSFER} ─→ CLOSING ─→ HANGUP
                ↓
           NO_MATCH ─→ TRANSFER
```

- **GREETING:** play hospital-specific greeting + language selection (caller speaks
  language name → match against `voice_agent_config.languages`).
- **IDENTIFY:** ask DOB + last 4 of phone if EHR lookup is needed; skip for FAQ
  calls. Three retries before falling back to anonymous mode.
- **CLASSIFY:** Claude picks one of TRIAGE / BOOK / FAQ / TRANSFER from the
  caller's first sentence (≤ 1 turn).
- Branch states each have their own sub-conversation managed by Claude tool use.
- **CLOSING:** confirm what was done, give confirmation number, ask "anything else?".
- **HANGUP:** end TwiML, persist `solace-calls` row.

---

## 5. Persistence

**New DynamoDB table: `solace-calls`** (PAY_PER_REQUEST, CMK-encrypted, 90-day TTL):

| Attribute               | Type   | Notes                                           |
|-------------------------|--------|-------------------------------------------------|
| `call_id` (PK)          | S      | Twilio CallSid                                  |
| `hospital_id` (GSI PK)  | S      |                                                 |
| `started_at` (GSI SK)   | S      | ISO8601                                         |
| `caller_phone`          | S      | redacted in logs (last 4 only)                  |
| `language`              | S      | ISO 639-1                                       |
| `intent`                | S      | TRIAGE / BOOK / FAQ / TRANSFER / ESCALATED      |
| `disposition`           | S      | resolved_by_agent / transferred / hung_up       |
| `transcript`            | S      | JSON array of {role, text, ts}                  |
| `tools_called`          | S      | JSON array of tool invocations                  |
| `recording_s3_key`      | S      | empty if not recorded                           |
| `consent_recorded`      | BOOL   | mirrors the consent gate                        |
| `duration_seconds`      | N      |                                                 |
| `escalated_to`          | S      | empty unless transferred                        |
| `pii_redaction_applied` | BOOL   | true after the redactor runs (see §7)           |

**New table: `solace-appointments`** for `book_appointment`:

| `appointment_id`, `hospital_id+date` (GSI), `patient_name`, `patient_phone`,
`reason_short`, `time_slot`, `status` (booked / cancelled / completed),
`confirmation_code`, `created_via` ("voice" / "web") |

---

## 6. New backend module layout

```
backend/services/voice_agent/
├── __init__.py
├── session.py            # state machine, per-call context object
├── streaming_stt.py      # Whisper-via-VAD wrapper + AssemblyAI adapter (future)
├── streaming_tts.py      # ElevenLabs WS streaming wrapper
├── codec.py              # μ-law ↔ PCM resampling
├── intents.py            # Claude tool definitions + tool dispatcher
├── escalation.py         # transfer_to_human / 911 / callback queue
├── faq_rag.py            # FAQ retrieval (S3 + embeddings; stub for now)
├── prompts.py            # hospital-aware system prompts per state
└── redaction.py          # post-call PII scrubbing before persistence

backend/routers/voice.py
├── POST /api/voice/incoming    # Twilio webhook, returns TwiML
├── WS   /api/voice/stream/{call_sid}  # bidirectional audio
├── POST /api/voice/status      # Twilio status callback (call ended, etc.)
└── POST /api/voice/recording-callback  # recording finalized

scripts/
├── setup_voice_agent.py        # provisions Twilio number, sets webhook URL,
│                               # creates solace-calls + solace-appointments tables
└── seed_voice_demo.py          # populates a demo FAQ + appointment slots
```

---

## 7. Compliance + security

This is the riskiest piece — voice = PHI on the wire.

- **BAA:** required with Twilio (existing Solace BAA umbrella covers OpenAI /
  Anthropic / ElevenLabs already; Twilio gets added).
- **Consent:** every call opens with "This call may be processed by an AI
  assistant. To continue, say yes." If they decline → immediate transfer.
- **Recording consent:** separate yes/no, on top of AI consent.
- **PII redaction:** post-call, run `redaction.py` over the transcript before it
  hits `solace-calls`. Strip SSN, full DOB, full credit-card numbers using regex
  + Claude double-check pass.
- **Audit trail:** every tool call logged to existing `solace-audit-log` with
  `clinician_id=null, action="voice.tool.{name}", source_ip=null,
  extra={call_id, hospital_id}`.
- **Rate limits:** per-caller-phone hourly cap (e.g. 5 calls / 30 min) to prevent
  abuse loops. Identity-bound on `(hospital_id, caller_phone_hash)`.
- **Geo restrictions:** Twilio number pool restricted to US (no international
  inbound for v1).
- **Loss-of-quorum:** if Claude or Whisper or ElevenLabs is down for >5s during
  a live call, immediate fallback transfer to escalation_phone with a "I'm
  having trouble — connecting you to a person" message.

---

## 8. Latency budget

User experience target: < 1.5s from end-of-utterance to first audible response.

| Stage                                | Budget   |
|--------------------------------------|----------|
| VAD end-of-utterance detection       | 200ms    |
| Whisper sync transcribe (≤6s chunk)  | 400ms    |
| Claude w/ tool use (streamed)        | 600ms    |
| ElevenLabs first audio chunk         | 300ms    |
| **Total (first audible byte)**       | **1500ms** |

Streaming Claude + streaming TTS overlap, so practical TTFB is closer to 800ms.

---

## 9. Out of scope for v1

- **Outbound calling** (appointment reminders, follow-ups). Punt to v2.
- **SMS fallback** when caller can't hear well. Punt to v2.
- **Multi-party / conference** ("hold while I get the nurse"). v2.
- **Voice cloning** (hospital wants its own real receptionist's voice). v3.
- **Real-time interruption handling** (caller cuts off the agent). Treat all
  interruptions as "end of agent turn" for v1; v2 adds barge-in.

---

## 10. Demo path (for the next build session)

Order of work that'll produce a runnable demo fastest:

1. Stub `services/voice_agent/session.py` — synchronous Whisper + Claude + TTS
   loop, no Twilio, hits via `pytest`.
2. `routers/voice.py` `POST /incoming` returning hard-coded TwiML
   (`<Say>Hi.</Say><Hangup/>`) to verify webhook plumbing.
3. WebSocket `/voice/stream/{call_sid}` echoing the caller back to themselves.
4. Wire Whisper VAD chunker.
5. Wire Claude tool use with just `transfer_to_human` and `answer_faq`.
6. Add `solace-calls` persistence.
7. Add hospital config UI in the clinician dashboard sidebar.

Each step is shippable on its own — no big-bang integration.
