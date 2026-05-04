"""ESI → next-step recommendation.

Closest competitor: Clearstep's Smart Care Routing. After triage, the patient
gets a one-shot recommendation with rationale + a CTA the result page renders
as the primary button.

Recommendations are pulled from the existing ESI level (so they stay coherent
with the conformal-prediction set + SHAP), augmented by transcript-keyword
red flags. Pure deterministic — runs in microseconds, no Claude call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

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


def recommend(esi_level: int, transcript: str = "", patient_age: int | None = None) -> CareRecommendation:
    """Single-shot recommendation. Always returns; never None."""
    text = (transcript or "").lower()

    # Hard stop on ED-NOW phrases regardless of computed ESI — these belong in
    # the resus bay, not a waiting room kiosk.
    if _RED_FLAGS.search(text):
        return CareRecommendation(
            destination="ed_now",
            label=DESTINATION_LABELS["ed_now"],
            rationale=(
                "What you described needs a clinician right away. Please walk to the "
                "front desk now or, if you can't, dial 911."
            ),
            action_cta="I'm walking to the front desk",
            severity="critical",
        )

    if esi_level == 1:
        return CareRecommendation(
            destination="ed_now",
            label=DESTINATION_LABELS["ed_now"],
            rationale="High acuity — a clinician needs to see you immediately.",
            action_cta="Go to front desk",
            severity="critical",
        )
    if esi_level == 2:
        return CareRecommendation(
            destination="ed",
            label=DESTINATION_LABELS["ed"],
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
            return CareRecommendation(
                destination="ed",
                label=DESTINATION_LABELS["ed"],
                rationale="Given your age, staying for in-person evaluation is safer.",
                action_cta="Got it, I'll wait",
                severity="high",
            )
        return CareRecommendation(
            destination="urgent",
            label=DESTINATION_LABELS["urgent"],
            rationale=(
                "This is something we should look at today. You're already here, so "
                "stay — but a virtual visit would also work if you'd rather come back."
            ),
            action_cta="Stay here",
            severity="moderate",
        )
    if esi_level == 4:
        return CareRecommendation(
            destination="telehealth",
            label=DESTINATION_LABELS["telehealth"],
            rationale=(
                "Likely manageable without an ER bed. A virtual visit today or a "
                "same-day appointment is a faster path."
            ),
            action_cta="Book a virtual visit",
            severity="low",
        )
    # ESI 5 (or any unexpected value) → self-care + optional follow-up
    return CareRecommendation(
        destination="self_care",
        label=DESTINATION_LABELS["self_care"],
        rationale=(
            "You can take care of this from home. We'll text instructions if you'd like, "
            "and you can book a follow-up if it doesn't get better in 2-3 days."
        ),
        action_cta="See home-care steps",
        severity="low",
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
    }
