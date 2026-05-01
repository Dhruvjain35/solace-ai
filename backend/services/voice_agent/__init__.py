"""Voice agent — Claude-driven phone receptionist for hospitals.

Same AI stack as the patient-side intake (Whisper + Claude + ElevenLabs), wired
through Twilio Voice via <Record>-style turn taking so the whole loop runs on
the existing Lambda with zero WebSocket / Fargate cost.

See docs/voice_agent_framework.md for the architecture.
"""
