"""Deterministic intake dialogue state machine for the voice agent.

Why deterministic? A Claude-only conversation loop is great at *phrasing* but
unreliable at *bookkeeping* — it forgets which slot it already asked, re-asks
filled slots, or skips the red-flag screen. This module owns the bookkeeping:
which slot we are on, what is already filled, how many times we have re-prompted,
and whether any red flag has surfaced. Claude (in intents.py) still does the
natural-language understanding; this state machine decides *what to ask next*.

State graph (linear, with an unconditional red-flag override):

    CHIEF_COMPLAINT -> ONSET -> SEVERITY -> HISTORY -> RED_FLAG_SCREEN -> READY -> DONE

At any point, if a continuous red-flag scan trips, the machine jumps straight to
READY with `emergency=True` so the caller is routed to 911/transfer immediately.

The whole IntakeState is a plain dict-serializable object so it round-trips
through `session.py` -> DynamoDB and back across Lambda cold starts.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from services.voice_agent.prompts import (
    INTAKE_QUESTIONS,
    NO_WORDS,
    RED_FLAG_PATTERNS,
    SLOT_CONFIRMATIONS,
    YES_WORDS,
)

# --- State constants -----------------------------------------------------------------

# Ordered intake stages. The machine walks these top to bottom; `RED_FLAG_SCREEN`
# is an explicit ask even though red flags are *also* scanned continuously, so a
# caller who never volunteered a danger sign still gets asked once directly.
CHIEF_COMPLAINT = "CHIEF_COMPLAINT"
ONSET = "ONSET"
SEVERITY = "SEVERITY"
HISTORY = "HISTORY"
RED_FLAG_SCREEN = "RED_FLAG_SCREEN"
READY = "READY"
DONE = "DONE"

# The slot-collecting stages, in order. READY/DONE are terminal and collect nothing.
SLOT_ORDER: tuple[str, ...] = (
    CHIEF_COMPLAINT,
    ONSET,
    SEVERITY,
    HISTORY,
    RED_FLAG_SCREEN,
)

# Per-stage the slot key it fills in `IntakeState.slots`.
_STAGE_SLOT: dict[str, str] = {
    CHIEF_COMPLAINT: "chief_complaint",
    ONSET: "onset",
    SEVERITY: "severity",
    HISTORY: "history",
    RED_FLAG_SCREEN: "red_flag_answer",
}

# How many times we will re-ask a single slot before giving up on it and moving
# on (a stuck slot should not trap the caller forever — we degrade gracefully).
MAX_REPROMPTS = 2

# Severity: spoken numbers + words mapped to a 0-10 scale.
_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_SEVERITY_BANDS: list[tuple[str, int]] = [
    ("unbearable", 10), ("worst", 10), ("excruciating", 10), ("severe", 9),
    ("really bad", 8), ("very bad", 8), ("bad", 7), ("intense", 8),
    ("strong", 7), ("moderate", 5), ("medium", 5), ("manageable", 4),
    ("mild", 3), ("slight", 2), ("a little", 2), ("barely", 1),
]


# --- Multilingual yes/no parsing -----------------------------------------------------


def parse_yes_no(text: str, language: str = "en") -> bool | None:
    """Return True for an affirmative, False for a negative, None if ambiguous.

    Checks the caller's language first, then falls back to English (callers
    code-switch on the phone constantly — "no, gracias" is common).
    """
    if not text:
        return None
    t = f" {text.strip().lower()} "
    lang = (language or "en")[:2]

    yes_sets = [YES_WORDS.get(lang, ()), YES_WORDS.get("en", ())]
    no_sets = [NO_WORDS.get(lang, ()), NO_WORDS.get("en", ())]

    # Negation wins over affirmation when both appear ("no, I'm fine, yeah").
    # Real callers lead with the operative word, so check negatives first.
    for words in no_sets:
        for w in words:
            if f" {w} " in t or t.strip() == w:
                return False
    for words in yes_sets:
        for w in words:
            if f" {w} " in t or t.strip() == w:
                return True
    return None


# --- Red-flag scanning ---------------------------------------------------------------


def scan_red_flags(text: str, language: str = "en") -> list[str]:
    """Continuous red-flag scan. Returns the list of red-flag category names that
    matched anywhere in `text`. Runs every turn, regardless of dialogue stage —
    a caller can blurt "and my chest hurts" while answering an onset question.
    """
    if not text:
        return []
    t = text.strip().lower()
    lang = (language or "en")[:2]
    hits: list[str] = []
    # Scan both the caller's language patterns and English (code-switching).
    pattern_sources = {**RED_FLAG_PATTERNS.get("en", {})}
    pattern_sources.update(RED_FLAG_PATTERNS.get(lang, {}))
    for category, patterns in pattern_sources.items():
        for pat in patterns:
            if pat in t:
                if category not in hits:
                    hits.append(category)
                break
    return hits


# --- Slot extraction helpers ---------------------------------------------------------


def extract_severity(text: str) -> int | None:
    """Pull a 0-10 pain/severity score from free speech.

    Handles "it's a seven", "7 out of 10", "about an eight", and word bands
    like "really bad" -> 8. Returns None if nothing scoreable is present.
    """
    if not text:
        return None
    t = text.strip().lower()

    # Explicit digit "N out of 10" / "N/10" — capture the score, not the scale.
    m = re.search(r"\b(\d{1,2})\s*(?:out of|/|over)\s*10\b", t)
    if m:
        return min(10, max(0, int(m.group(1))))

    # Spoken-word "eight out of ten" — the score is a word before the anchor.
    m = re.search(
        r"\b(" + "|".join(_NUMBER_WORDS) + r")\b\s*(?:out of|over)\s*ten\b", t)
    if m:
        return _NUMBER_WORDS[m.group(1)]

    # Strip a trailing "out of 10 / out of ten" scale anchor so the bare-number
    # and word scans below don't latch onto the "10" of the scale.
    t_scan = re.sub(r"\b(?:out of|over)\s*(?:10|ten)\b", " ", t)

    # Bare number 0-10 anywhere.
    for m in re.finditer(r"\b(\d{1,2})\b", t_scan):
        n = int(m.group(1))
        if 0 <= n <= 10:
            return n

    # Spoken number words.
    for word, n in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", t_scan):
            return n

    # Descriptive bands — longest phrase first so "really bad" beats "bad".
    for phrase, score in sorted(_SEVERITY_BANDS, key=lambda p: -len(p[0])):
        if phrase in t:
            return score
    return None


# --- The state object ----------------------------------------------------------------


@dataclass
class IntakeState:
    """Serializable intake-conversation state for one voice call.

    Persisted inside the session record under the `intake` key. Every field is
    a JSON-native type so `to_dict()` round-trips cleanly through DynamoDB.
    """

    stage: str = CHIEF_COMPLAINT
    # Filled slot values, keyed by the slot names in `_STAGE_SLOT`.
    slots: dict[str, Any] = field(default_factory=dict)
    # Per-stage re-prompt counter — how many times we re-asked an unanswered slot.
    reprompts: dict[str, int] = field(default_factory=dict)
    # Distinct red-flag categories seen across the whole call (continuous scan).
    red_flags: list[str] = field(default_factory=list)
    # True once a red flag trips — the call should route to emergency handling.
    emergency: bool = False
    # Caller language (ISO 639-1) — drives question wording + yes/no parsing.
    language: str = "en"
    # Monotonic turn counter, useful for analytics + loop-guarding.
    turns: int = 0

    # -- serialization --

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form for session persistence."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "IntakeState":
        """Rehydrate from a persisted dict. Tolerates missing/extra keys so an
        older session row never crashes a newer deploy."""
        if not data:
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        state = cls(**clean)
        # Defensive normalization after a round-trip.
        if state.stage not in (*SLOT_ORDER, READY, DONE):
            state.stage = CHIEF_COMPLAINT
        state.slots = dict(state.slots or {})
        state.reprompts = {k: int(v) for k, v in (state.reprompts or {}).items()}
        state.red_flags = list(state.red_flags or [])
        return state

    # -- queries --

    def is_complete(self) -> bool:
        return self.stage in (READY, DONE)

    def filled_slots(self) -> dict[str, Any]:
        return {k: v for k, v in self.slots.items() if v not in (None, "", [])}

    def current_slot(self) -> str | None:
        """The slot key the current stage is trying to fill, or None if terminal."""
        return _STAGE_SLOT.get(self.stage)

    def reprompt_count(self, stage: str | None = None) -> int:
        return self.reprompts.get(stage or self.stage, 0)

    def summary(self) -> dict[str, Any]:
        """Compact view for handoff to triage / clinician dashboard."""
        return {
            "chief_complaint": self.slots.get("chief_complaint", ""),
            "onset": self.slots.get("onset", ""),
            "severity": self.slots.get("severity"),
            "history": self.slots.get("history", ""),
            "red_flags": list(self.red_flags),
            "emergency": self.emergency,
            "complete": self.is_complete(),
        }


# --- The state machine ---------------------------------------------------------------


def next_prompt(state: IntakeState) -> str:
    """The question to speak for the *current* stage, in the caller's language.

    Falls back through the same language's English question, then a generic
    English line, so a missing translation never yields an empty prompt.
    """
    lang = (state.language or "en")[:2]
    stage = state.stage
    if stage in (READY, DONE):
        return ""
    by_lang = INTAKE_QUESTIONS.get(lang) or INTAKE_QUESTIONS.get("en", {})
    en = INTAKE_QUESTIONS.get("en", {})
    return by_lang.get(stage) or en.get(stage) or "Could you tell me more?"


def reprompt_text(state: IntakeState) -> str:
    """A gentler re-ask for the current stage when the caller's last answer did
    not fill the slot. After MAX_REPROMPTS the caller should be moved on instead.
    """
    lang = (state.language or "en")[:2]
    by_lang = INTAKE_QUESTIONS.get(lang) or INTAKE_QUESTIONS.get("en", {})
    en = INTAKE_QUESTIONS.get("en", {})
    key = f"{state.stage}_REPROMPT"
    return by_lang.get(key) or en.get(key) or next_prompt(state)


def _advance_stage(state: IntakeState) -> None:
    """Move `state.stage` to the next stage that still needs a slot, or READY."""
    try:
        idx = SLOT_ORDER.index(state.stage)
    except ValueError:
        state.stage = READY
        return
    for nxt in SLOT_ORDER[idx + 1:]:
        slot = _STAGE_SLOT[nxt]
        if state.slots.get(slot) in (None, "", []):
            state.stage = nxt
            return
    state.stage = READY


def _opportunistic_fill(state: IntakeState, text: str) -> list[str]:
    """Multi-slot fill — a caller often answers more than one slot in a breath
    ("My chest has hurt since this morning, it's a bad eight"). We harvest every
    slot we can from a single utterance, not just the one we asked for.

    Returns the list of slot keys that got newly filled.
    """
    filled: list[str] = []
    stripped = text.strip()

    # Chief complaint: first substantive utterance fills it if still empty.
    if not state.slots.get("chief_complaint") and len(stripped) >= 3:
        state.slots["chief_complaint"] = stripped[:300]
        filled.append("chief_complaint")

    # Onset: look for time-reference language anywhere in the utterance.
    if not state.slots.get("onset"):
        if re.search(
            r"\b(yesterday|today|this morning|last night|ago|since|hour|hours|"
            r"day|days|week|weeks|month|minute|minutes|just now|recently)\b",
            stripped.lower(),
        ):
            state.slots["onset"] = stripped[:200]
            filled.append("onset")

    # Severity: any scoreable score, anytime.
    if state.slots.get("severity") in (None, ""):
        sev = extract_severity(stripped)
        if sev is not None:
            state.slots["severity"] = sev
            filled.append("severity")

    return filled


def ingest(state: IntakeState, user_text: str) -> dict[str, Any]:
    """Feed one caller utterance into the machine and advance it.

    This is the single entry point intents.py calls per turn. It:
      1. runs the continuous red-flag scan (every turn, every stage),
      2. opportunistically fills any slot the utterance answers,
      3. fills the *current* stage's slot if not already covered,
      4. advances the stage (or re-prompts / gives up after MAX_REPROMPTS),
      5. returns a directive dict telling intents.py what to do next.

    Returned dict keys:
      - say:        suggested line to speak (the next question / re-prompt /
                    completion line), or "" when the machine has nothing to add.
      - stage:      the stage *after* this turn.
      - emergency:  True if a red flag has tripped this call.
      - red_flags:  full list of red-flag categories seen so far.
      - filled:     slot keys newly filled this turn.
      - complete:   True once the intake reached READY/DONE.
      - advanced:   True if the stage changed this turn.
    """
    state.turns += 1
    text = (user_text or "").strip()
    prev_stage = state.stage

    # 1. Continuous red-flag scan — runs no matter the stage.
    new_flags = scan_red_flags(text, state.language)
    for f in new_flags:
        if f not in state.red_flags:
            state.red_flags.append(f)
    if new_flags and not state.emergency:
        state.emergency = True
        # Jump straight to READY — the caller needs routing now, not more intake.
        state.stage = READY
        return {
            "say": "",  # intents.py / red-flag handler owns the emergency line
            "stage": state.stage,
            "emergency": True,
            "red_flags": list(state.red_flags),
            "filled": [],
            "complete": True,
            "advanced": prev_stage != state.stage,
        }

    if state.is_complete():
        return {
            "say": "",
            "stage": state.stage,
            "emergency": state.emergency,
            "red_flags": list(state.red_flags),
            "filled": [],
            "complete": True,
            "advanced": False,
        }

    # 2. Opportunistic multi-slot fill from the raw utterance.
    filled = _opportunistic_fill(state, text)

    # 3. Stage-specific slot fill for whatever the current stage still needs.
    slot = state.current_slot()
    answered_current = bool(slot and state.slots.get(slot) not in (None, "", []))

    if slot and not answered_current:
        if state.stage == RED_FLAG_SCREEN:
            yn = parse_yes_no(text, state.language)
            if yn is True:
                # Caller affirms a danger sign on the direct screen — treat as a flag.
                state.slots["red_flag_answer"] = "yes"
                if "screen_positive" not in state.red_flags:
                    state.red_flags.append("screen_positive")
                state.emergency = True
                answered_current = True
            elif yn is False:
                state.slots["red_flag_answer"] = "no"
                answered_current = True
            # yn is None -> unanswered, fall through to re-prompt logic
        elif state.stage == HISTORY:
            # History is free-text; any non-trivial reply counts. A bare "no"
            # ("no past conditions") is a valid, complete answer.
            if len(text) >= 2:
                state.slots["history"] = text[:300]
                answered_current = True
        elif state.stage == SEVERITY:
            if state.slots.get("severity") not in (None, ""):
                answered_current = True
        else:
            # CHIEF_COMPLAINT / ONSET were handled opportunistically; if still
            # empty after a >=3-char reply, accept it verbatim.
            if state.slots.get(slot) in (None, "", []) and len(text) >= 3:
                state.slots[slot] = text[:300]
                answered_current = True
            else:
                answered_current = bool(state.slots.get(slot))

    # 4. Advance, re-prompt, or give up.
    if answered_current or (slot and slot in filled):
        if state.emergency:
            state.stage = READY
        else:
            _advance_stage(state)
        advanced = state.stage != prev_stage
        if state.is_complete():
            return {
                "say": _completion_line(state),
                "stage": state.stage,
                "emergency": state.emergency,
                "red_flags": list(state.red_flags),
                "filled": filled,
                "complete": True,
                "advanced": advanced,
            }
        return {
            "say": next_prompt(state),
            "stage": state.stage,
            "emergency": state.emergency,
            "red_flags": list(state.red_flags),
            "filled": filled,
            "complete": False,
            "advanced": advanced,
        }

    # Slot still unanswered — count a re-prompt.
    count = state.reprompts.get(state.stage, 0) + 1
    state.reprompts[state.stage] = count
    if count > MAX_REPROMPTS:
        # Give up on this slot, mark it skipped, and move on so we never trap
        # a caller who genuinely cannot answer (bad line, language gap).
        if slot and state.slots.get(slot) in (None, "", []):
            state.slots[slot] = "(not provided)"
        _advance_stage(state)
        if state.is_complete():
            return {
                "say": _completion_line(state),
                "stage": state.stage,
                "emergency": state.emergency,
                "red_flags": list(state.red_flags),
                "filled": filled,
                "complete": True,
                "advanced": True,
            }
        return {
            "say": next_prompt(state),
            "stage": state.stage,
            "emergency": state.emergency,
            "red_flags": list(state.red_flags),
            "filled": filled,
            "complete": False,
            "advanced": True,
        }

    return {
        "say": reprompt_text(state),
        "stage": state.stage,
        "emergency": state.emergency,
        "red_flags": list(state.red_flags),
        "filled": filled,
        "complete": False,
        "advanced": False,
    }


def _completion_line(state: IntakeState) -> str:
    """The line to speak once intake reaches READY — a brief read-back so the
    caller hears we captured their story, then a handoff cue."""
    lang = (state.language or "en")[:2]
    by_lang = SLOT_CONFIRMATIONS.get(lang) or SLOT_CONFIRMATIONS.get("en", {})
    template = by_lang.get("READY") or SLOT_CONFIRMATIONS["en"]["READY"]
    cc = state.slots.get("chief_complaint") or "your concern"
    return template.format(chief_complaint=cc)
