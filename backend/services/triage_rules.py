"""Deterministic ESI shortcuts — checked before any LLM call.

The triage_engine already has clinical-simulation logic, but for genuinely
unambiguous cases (med refill, paperwork, prior-auth fax pickup, suicidal
ideation, active CPR-eligible emergency) we can skip the whole Claude pipeline
and return a hard-coded ESI in microseconds. Saves ~$0.04-0.08 per such case
and shaves whole seconds off intake latency.

If no rule matches, returns None and the regular triage path runs unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ShortcutResult:
    esi_level: int                  # 1-5
    reason: str                     # short rule name for audit log
    recommendation: str             # 1-line clinician-facing recommendation
    skip_claude_pipeline: bool = True  # if True, intake skips prebrief / Ddx / etc


# Order matters — first match wins. High-acuity rules first so an ambiguous
# message ("med refill but I'm having chest pain") triages as the higher acuity.
# Each pattern is matched against the lowercased transcript with re.search.
RULES: list[tuple[re.Pattern[str], ShortcutResult]] = [
    # ESI 1 — life-threatening, immediate intervention
    (
        re.compile(
            r"\b(not breathing|isn'?t breathing|stopped breathing|apnea|apneic|"
            r"cpr|cardiac arrest|cardiopulmonary arrest|code blue|"
            r"drowning|drowned|choking|hanging|hanged|"
            r"unrespons\w*|unconscious|not waking up|no pulse|pulseless)\b"
        ),
        ShortcutResult(
            esi_level=1,
            reason="rule.esi1.life_threatening_keywords",
            recommendation="ESI 1 — immediate resuscitation. Direct to trauma bay; clinician sees first.",
        ),
    ),
    # ESI 1 — catastrophic trauma: traumatic amputation, dismemberment,
    # uncontrolled/arterial hemorrhage, penetrating torso/head trauma.
    (
        re.compile(
            r"\b(amputat\w*|dismember\w*|severed|degloving|chainsaw|"
            r"chopped (off|through)|cut off|sliced off|sawed off|ripped off|"
            r"exsanguinat\w*|hemorrhagic shock|spurting blood|"
            r"(massive|uncontroll\w*|profuse|arterial) (bleed\w*|hemorrhag\w*)|"
            r"gunshot|gsw|impale\w*|stab\w* (wound )?(to (the )?(chest|abdomen|neck|back)))\b"
        ),
        ShortcutResult(
            esi_level=1,
            reason="rule.esi1.catastrophic_trauma",
            recommendation="ESI 1 — catastrophic trauma / hemorrhage. Trauma team activation; hemorrhage control, airway, shock protocol.",
        ),
    ),
    # ESI 2 — high-risk presentations that must not wait (chest pain, severe
    # dyspnea, sepsis, open fracture, anaphylaxis, worst-headache).
    (
        re.compile(
            r"\b(chest pain|chest pressure|chest tightness|"
            r"difficulty breathing|trouble breathing|shortness of breath|dyspnea|"
            r"anaphyla\w*|allergic reaction|throat swelling|"
            r"sepsis|septic|"
            r"open fracture|compound fracture|"
            r"worst headache|thunderclap|"
            r"severe bleed\w*|hemorrhag\w*)\b"
        ),
        ShortcutResult(
            esi_level=2,
            reason="rule.esi2.high_risk_presentation",
            recommendation="ESI 2 — high-risk; do not let wait. Expedite to acute bed; vitals + clinician promptly.",
        ),
    ),
    # Suicidal ideation / overdose — ESI 2 by default, but flag for crisis intervention
    (
        re.compile(r"\b(suicid\w*|kill myself|kill my self|homicidal|self.?harm|overdos\w*|took (too many|all my))\b"),
        ShortcutResult(
            esi_level=2,
            reason="rule.esi2.crisis",
            recommendation="ESI 2 — psychiatric emergency. Continuous observation; psych consult.",
        ),
    ),
    # Active stroke symptoms — ESI 1
    (
        re.compile(r"\b(face droop|slurred speech|sudden weakness|numb on one side|stroke)\b"),
        ShortcutResult(
            esi_level=1,
            reason="rule.esi1.stroke_symptoms",
            recommendation="ESI 1 — possible stroke. Activate stroke alert; CT head STAT.",
        ),
    ),
    # Pure administrative — no clinical evaluation needed (skip whole AI pipeline)
    (
        re.compile(
            r"^(?=.{0,200}$)"  # short message
            r"(?:.*\b(refill|prescription pickup|prior auth|prior authorization|paperwork|"
            r"fax|records request|fmla|disability form|work note|school note|medical clearance|"
            r"vaccine record|immunization record)\b)"
        ),
        ShortcutResult(
            esi_level=5,
            reason="rule.esi5.administrative",
            recommendation="ESI 5 — non-clinical / administrative. Direct to front desk; no medical workup.",
        ),
    ),
]


def evaluate(transcript: str) -> ShortcutResult | None:
    """Return a shortcut result if any rule matches, else None.

    Patterns are pre-compiled module-level so this is O(N rules) with N small.
    Cost: microseconds per call; safe to run on every intake.
    """
    if not transcript:
        return None
    text = transcript.lower()
    for pattern, result in RULES:
        if pattern.search(text):
            return result
    return None
