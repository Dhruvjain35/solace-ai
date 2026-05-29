"""Turn-taking helpers — barge-in detection and turn finalization.

The voice agent runs on Twilio `<Record>`-style half-duplex turns (see
docs/voice_agent_framework.md §10): the caller speaks, Twilio posts a recording,
we reply, repeat. That model has two rough edges this module smooths:

  1. *Barge-in*: the caller starts talking while the agent's prompt is still
     playing. Twilio's `<Record>` ends the playback when speech is detected, but
     the recording then contains a fragment ("—no wait, the OTHER ear"). We
     decide whether that fragment is a real interruption worth honoring or just
     a backchannel ("uh-huh", "mm") we should ignore and keep going.

  2. *Turn finalization*: deciding when the caller has actually *finished* a
     turn versus merely paused. Twilio's `timeout` ends a turn on silence, but a
     trailing filler ("so, um, yeah...") or a mid-sentence cut produces a
     half-utterance we should re-prompt on instead of feeding to Claude.

Everything here is pure, deterministic, side-effect free, and stateless except
for the small dicts passed in/out — easy to unit test and cheap to call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Backchannels — short acknowledgement noises that are NOT a real interruption.
# If a "barge-in" recording is only this, the agent should keep its turn.
_BACKCHANNELS: frozenset[str] = frozenset({
    "uh", "uh huh", "uh-huh", "mhm", "mm", "mmm", "mm hmm", "yeah", "yep",
    "ok", "okay", "right", "sure", "hm", "huh", "yup", "i see", "got it",
    "ah", "oh", "hmm", "alright",
})

# Explicit stop / interrupt phrases — a hard barge-in we always honor, even mid
# agent sentence. The caller is actively trying to cut us off.
_INTERRUPT_PHRASES: tuple[str, ...] = (
    "stop", "wait", "hold on", "hang on", "no no", "listen", "let me",
    "excuse me", "actually", "but", "that's not", "thats not", "i didn't",
    "i didnt", "you're wrong", "youre wrong", "no wait",
)

# Trailing fillers that mark an *unfinished* utterance — if the recording ends on
# one of these, the caller was probably cut off by the silence timeout.
_TRAILING_FILLERS: tuple[str, ...] = (
    "and", "but", "so", "because", "the", "a", "an", "my", "i", "it's",
    "its", "um", "uh", "like", "to", "with", "for", "or", "if", "when",
)

# Minimum word count for a recording to be treated as a complete, actionable
# turn. Below this we re-prompt rather than route a fragment to the agent.
_MIN_TURN_WORDS = 1

# A recording shorter (in characters) than this is almost certainly noise / a
# half-second of breath that tripped VAD.
_MIN_TURN_CHARS = 2


@dataclass
class TurnDecision:
    """Outcome of evaluating one caller recording.

    - action:    "process"  -> hand text to the agent/state machine
                 "reprompt" -> caller said too little; ask again
                 "ignore"   -> backchannel during agent speech; keep agent turn
    - text:      the (possibly trimmed) caller text to use downstream
    - barge_in:  True if this recording interrupted the agent mid-prompt
    - reason:    short human-readable explanation, handy for call analytics
    """

    action: str
    text: str
    barge_in: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "text": self.text,
            "barge_in": self.barge_in,
            "reason": self.reason,
        }


def _normalize(text: str) -> str:
    """Lowercase, strip, collapse whitespace, drop edge punctuation."""
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t.strip(" .,!?;:-—–")


def is_backchannel(text: str) -> bool:
    """True if the utterance is only an acknowledgement noise (no real content)."""
    norm = _normalize(text)
    if not norm:
        return True
    # Strip a leading/trailing backchannel token then see if anything remains.
    words = norm.split()
    if len(words) > 3:
        return False
    return norm in _BACKCHANNELS or all(w in _BACKCHANNELS for w in words)


def is_interrupt(text: str) -> bool:
    """True if the utterance opens with an explicit stop/interrupt phrase."""
    norm = _normalize(text)
    if not norm:
        return False
    for phrase in _INTERRUPT_PHRASES:
        if norm == phrase or norm.startswith(phrase + " "):
            return True
    return False


def looks_unfinished(text: str) -> bool:
    """Heuristic: did the caller get cut off mid-sentence?

    True when the recording ends on a dangling filler/conjunction/article — a
    strong sign the silence timeout fired before the caller actually finished.
    """
    norm = _normalize(text)
    if not norm:
        return False
    words = norm.split()
    if not words:
        return False
    return words[-1] in _TRAILING_FILLERS and len(words) >= 2


def finalize_turn(text: str, *, agent_speaking: bool = False) -> TurnDecision:
    """Decide what to do with one caller recording.

    Args:
      text:           Whisper transcript of the caller's recording.
      agent_speaking: True if this recording arrived *while the agent's prompt
                      was still playing* (i.e. a candidate barge-in). The caller
                      router knows this from Twilio `<Record>` timing.

    Returns a TurnDecision. The caller (voice router / intents) acts on
    `.action` and may surface `.barge_in` in call analytics.
    """
    raw = text or ""
    norm = _normalize(raw)

    # Empty / sub-noise recording -> always re-prompt.
    if len(norm) < _MIN_TURN_CHARS or len(norm.split()) < _MIN_TURN_WORDS:
        return TurnDecision(
            action="reprompt", text="", barge_in=False,
            reason="empty_or_noise",
        )

    if agent_speaking:
        # Caller made noise while the agent was talking. Two cases:
        if is_backchannel(raw):
            # Just "mm-hmm" — not a real interruption, let the agent finish.
            return TurnDecision(
                action="ignore", text="", barge_in=False,
                reason="backchannel_during_agent_speech",
            )
        # Anything substantive (or an explicit "stop") IS a barge-in: the caller
        # wants the floor. Honor it — process their text, flag the barge-in.
        return TurnDecision(
            action="process", text=raw.strip(), barge_in=True,
            reason="interrupt_phrase" if is_interrupt(raw) else "barge_in_content",
        )

    # Agent was NOT speaking — this is a normal in-turn caller utterance.
    if is_backchannel(raw):
        # A standalone backchannel when it was the caller's turn means they did
        # not really answer — nudge them.
        return TurnDecision(
            action="reprompt", text="", barge_in=False,
            reason="backchannel_only",
        )
    if looks_unfinished(raw):
        # Caller trailed off / got clipped — re-prompt rather than feed a
        # fragment to the agent (but keep the partial text for context).
        return TurnDecision(
            action="reprompt", text=raw.strip(), barge_in=False,
            reason="unfinished_utterance",
        )
    return TurnDecision(
        action="process", text=raw.strip(), barge_in=False,
        reason="complete_turn",
    )


def merge_barge_in(prior_partial: str, barge_in_text: str) -> str:
    """When a barge-in happens, the prior agent turn is abandoned but the caller
    may have a partial utterance from just before the cut. Stitch the partial and
    the barge-in text into one coherent caller utterance, de-duplicating any
    overlap (Whisper sometimes repeats the boundary word).
    """
    a = (prior_partial or "").strip()
    b = (barge_in_text or "").strip()
    if not a:
        return b
    if not b:
        return a
    a_words = a.split()
    b_words = b.split()
    # Drop the largest suffix of `a` that is also a prefix of `b`.
    max_overlap = min(len(a_words), len(b_words), 4)
    for k in range(max_overlap, 0, -1):
        if [w.lower() for w in a_words[-k:]] == [w.lower() for w in b_words[:k]]:
            return " ".join(a_words + b_words[k:])
    return f"{a} {b}"
