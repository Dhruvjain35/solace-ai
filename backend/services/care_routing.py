"""ESI → next-step recommendation.

Closest competitor: Clearstep's Smart Care Routing. After triage, the patient
gets a one-shot recommendation with rationale + a CTA the result page renders
as the primary button.

Recommendations are pulled from the existing ESI level (so they stay coherent
with the conformal-prediction set + SHAP), augmented by transcript-keyword
red flags. Pure deterministic — runs in microseconds, no Claude call.

The recommendation is then refined for department capacity and patient age,
and carries a structured `next_steps` list the UI can render as a checklist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Map deliberately conservative — when in doubt, escalate. The ESI engine + the
# triage_rules shortcut already classify; this layer just translates the level
# into a patient-facing action.

DESTINATION_LABELS: dict[str, str] = {
    "ed_now":     "Stay here — go to the front desk now",
    "ed":         "Stay here for emergency care",
    "urgent":     "Urgent care or ED today",
    "telehealth": "Virtual visit today",
    "self_care":  "Care at home with our guidance",
    "schedule":   "Schedule a regular visit",
}


@dataclass(frozen=True)
class CareRecommendation:
    destination: str          # one of the keys above
    label: str                # human-facing title
    rationale: str            # 1-line explanation, patient-tone
    action_cta: str           # text for the primary button
    severity: str             # "critical" | "high" | "moderate" | "low"
    next_steps: tuple[str, ...] = field(default=())  # ordered patient checklist
    capacity_note: str = ""   # optional surge/wait advisory


# Structured next-step checklists, one per destination. The UI renders these
# as an ordered list under the primary CTA.
_NEXT_STEPS: dict[str, tuple[str, ...]] = {
    "ed_now": (
        "Walk to the front desk now and say you were told to come immediately.",
        "If you cannot walk or feel worse, dial 911.",
        "Do not eat or drink until a clinician sees you.",
    ),
    "ed": (
        "Stay seated in the waiting area — your spot is held.",
        "Tell staff right away if your symptoms get worse.",
        "Keep your phone nearby; we may text your queue updates.",
    ),
    "urgent": (
        "Check in here, or ask the front desk about a same-day virtual visit.",
        "Bring a list of your current medications.",
        "Watch for the warning signs on this page — return sooner if they appear.",
    ),
    "telehealth": (
        "Tap the button to book a virtual visit for today.",
        "Find a quiet, well-lit spot for the video call.",
        "Have your medications and pharmacy details ready.",
    ),
    "self_care": (
        "Follow the home-care steps we provide.",
        "Rest, fluids, and over-the-counter relief as directed.",
        "Book a follow-up if it is not improving in 2-3 days.",
    ),
    "schedule": (
        "Book a routine appointment with your regular clinician.",
        "Note any changes in your symptoms before the visit.",
    ),
}


def recommend(
    esi_level: int,
    transcript: str = "",
    patient_age: int | None = None,
    *,
    department_load: float | None = None,
    waiting_count: int | None = None,
) -> CareRecommendation:
    """Single-shot recommendation. Always returns; never None.

    `department_load`: optional 0.0-1.0 occupancy ratio for the ED.
    `waiting_count`: optional integer of patients currently waiting.
    When supplied, low-acuity patients are nudged toward off-site care during
    surge, and a `capacity_note` is attached. High-acuity routing is never
    softened by capacity.
    """
    text = (transcript or "").lower()

    # Hard stop on ED-NOW phrases regardless of computed ESI — these belong in
    # the resus bay, not a waiting room kiosk.
    if _RED_FLAGS.search(text):
        return _build(
            "ed_now",
            rationale=(
                "What you described needs a clinician right away. Please walk to the "
                "front desk now or, if you can't, dial 911."
            ),
            action_cta="I'm walking to the front desk",
            severity="critical",
        )

    if esi_level == 1:
        return _build(
            "ed_now",
            rationale="High acuity — a clinician needs to see you immediately.",
            action_cta="Go to front desk",
            severity="critical",
        )
    if esi_level == 2:
        return _build(
            "ed",
            rationale=(
                "You're in the right place. Stay seated — your spot is held and a "
                "clinician will see you soon."
            ),
            action_cta="Got it, I'll wait",
            severity="high",
        )
    if esi_level == 3:
        # Younger adult with typical ESI 3 may be a good telehealth candidate;
        # older or pregnant patients should stay.
        if patient_age is not None and patient_age >= 65:
            return _build(
                "ed",
                rationale="Given your age, staying for in-person evaluation is safer.",
                action_cta="Got it, I'll wait",
                severity="high",
            )
        return _build(
            "urgent",
            rationale=(
                "This is something we should look at today. You're already here, so "
                "stay — but a virtual visit would also work if you'd rather come back."
            ),
            action_cta="Stay here",
            severity="moderate",
            department_load=department_load,
            waiting_count=waiting_count,
        )
    if esi_level == 4:
        return _build(
            "telehealth",
            rationale=(
                "Likely manageable without an ER bed. A virtual visit today or a "
                "same-day appointment is a faster path."
            ),
            action_cta="Book a virtual visit",
            severity="low",
            department_load=department_load,
            waiting_count=waiting_count,
        )
    # ESI 5 (or any unexpected value) → self-care + optional follow-up
    return _build(
        "self_care",
        rationale=(
            "You can take care of this from home. We'll text instructions if you'd like, "
            "and you can book a follow-up if it doesn't get better in 2-3 days."
        ),
        action_cta="See home-care steps",
        severity="low",
        department_load=department_load,
        waiting_count=waiting_count,
    )


def _build(
    destination: str,
    *,
    rationale: str,
    action_cta: str,
    severity: str,
    department_load: float | None = None,
    waiting_count: int | None = None,
) -> CareRecommendation:
    """Assemble a recommendation, applying capacity-aware refinement.

    Only low/moderate-severity recommendations are capacity-refined; critical
    and high routing is never softened.
    """
    capacity_note = ""
    if severity in ("low", "moderate") and department_load is not None:
        if department_load >= 0.9:
            capacity_note = (
                "The emergency department is very busy right now. If you're "
                "comfortable, an off-site option may be seen faster."
            )
            # Nudge a moderate ESI-3 toward telehealth during heavy surge.
            if destination == "urgent":
                destination = "telehealth"
                action_cta = "Book a virtual visit instead"
        elif department_load >= 0.75:
            capacity_note = "The emergency department is busy; expect a longer wait."
    elif severity in ("low", "moderate") and waiting_count is not None and waiting_count >= 15:
        capacity_note = "A large number of patients are waiting; expect a longer wait."

    return CareRecommendation(
        destination=destination,
        label=DESTINATION_LABELS[destination],
        rationale=rationale,
        action_cta=action_cta,
        severity=severity,
        next_steps=_NEXT_STEPS.get(destination, ()),
        capacity_note=capacity_note,
    )


# Phrases that bypass any computed ESI and dump straight to the resus bay.
_RED_FLAGS = re.compile(
    r"\b("
    r"chest pain|crushing chest|left arm.*pain|right side.*weak|"
    r"can(?:'?t| not) breathe|gasping|blue lips|"
    r"slurred speech|face droop|sudden weakness|stroke symptoms?|"
    r"unconscious|passed out|fainted and|not waking|"
    r"bleeding (?:badly|heavily|won'?t stop)|"
    r"overdose(?:d)?|took (?:too many|all my) pills|"
    r"suicidal|kill myself|end my life"
    r")\b"
)


def serialize(rec: CareRecommendation) -> dict:
    return {
        "destination": rec.destination,
        "label": rec.label,
        "rationale": rec.rationale,
        "action_cta": rec.action_cta,
        "severity": rec.severity,
        "next_steps": list(rec.next_steps),
        "capacity_note": rec.capacity_note,
    }
