"""Nurse-triage protocols (Schmitt-Thompson alternative).

A small, openly-derived chief-complaint protocol library that recommends a
disposition (911, ED now, ED, urgent care, telehealth, self-care) based on a
short symptom interview. Designed for call-center / patient-portal triage and
to serve the Solace voice agent.

Each protocol is a deterministic decision tree with red-flag escalations.
Output mirrors the existing care-routing service shape so downstream code
treats it uniformly.

Implemented protocols (10 chief complaints — covers ~70% of triage volume):
  - chest_pain
  - shortness_of_breath
  - abdominal_pain
  - headache
  - back_pain
  - fever
  - cough
  - peds_fever (under 3 months special path)
  - laceration
  - mental_health_crisis
"""
from __future__ import annotations

from typing import Any


def _result(disposition: str, reason: str, *, sla: str = "", instructions: str = "") -> dict[str, Any]:
    return {"disposition": disposition, "reason": reason, "sla": sla, "instructions": instructions}


def chest_pain(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("severe_or_crushing"):
        return _result("911", "Severe / crushing chest pain — call 911", sla="now", instructions="Stay still. Chew an aspirin if not allergic and if instructed by 911.")
    if answers.get("with_dyspnea") or answers.get("with_diaphoresis") or answers.get("radiating_to_arm_jaw"):
        return _result("ed_now", "Chest pain with concerning features — go to the nearest ED now", sla="now")
    if answers.get("age_over_50") or answers.get("known_cad") or answers.get("diabetes"):
        return _result("ed_now", "Risk factors plus chest pain — be evaluated today in an ED", sla="now")
    if answers.get("pleuritic") or answers.get("trauma"):
        return _result("ed", "Pleuritic / post-traumatic chest pain — ED evaluation", sla="today")
    return _result("urgent", "Atypical chest pain — same-day evaluation in urgent care", sla="today")


def shortness_of_breath(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("severe_at_rest") or answers.get("blue_lips"):
        return _result("911", "Severe dyspnea or cyanosis — call 911", sla="now")
    if answers.get("known_asthma_failed_inhaler"):
        return _result("ed_now", "Asthma not responding to rescue inhaler — ED now", sla="now")
    if answers.get("with_chest_pain") or answers.get("post_long_travel_or_surgery"):
        return _result("ed_now", "Concerning for PE / cardiac cause — ED", sla="now")
    if answers.get("fever") or answers.get("productive_cough"):
        return _result("ed", "Possible pneumonia — ED evaluation today", sla="today")
    return _result("urgent", "Mild dyspnea — same-day urgent care evaluation", sla="today")


def abdominal_pain(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("severe_sudden") or answers.get("with_syncope"):
        return _result("911", "Severe sudden abdominal pain or syncope", sla="now")
    if answers.get("rigid_abdomen") or answers.get("vomiting_blood") or answers.get("black_tarry_stool"):
        return _result("ed_now", "Acute abdomen / GI bleed signs — ED now", sla="now")
    if answers.get("rlq_pain_with_fever"):
        return _result("ed", "Possible appendicitis — ED today", sla="today")
    if answers.get("pregnancy_possible_with_pain") or answers.get("missed_period_with_pain"):
        return _result("ed_now", "Possible ectopic pregnancy — ED now", sla="now")
    return _result("urgent", "Stable abdominal pain — urgent care today", sla="today")


def headache(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("worst_ever") or answers.get("thunderclap"):
        return _result("911", "Worst-ever / thunderclap headache — call 911", sla="now")
    if answers.get("with_neuro_deficit") or answers.get("with_fever_stiff_neck"):
        return _result("ed_now", "Headache with neuro deficit or meningismus — ED now", sla="now")
    if answers.get("immunocompromised") or answers.get("on_anticoagulation"):
        return _result("ed", "Immunocompromised / anticoagulated with headache — ED today", sla="today")
    return _result("self_care", "Routine headache — hydration, rest, analgesic per usual; ED if worsening or new neuro symptoms", sla="today")


def back_pain(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("saddle_anesthesia") or answers.get("urinary_retention") or answers.get("bowel_incontinence"):
        return _result("ed_now", "Cauda equina red flag — ED now", sla="now")
    if answers.get("with_fever") or answers.get("iv_drug_use") or answers.get("immunocompromised"):
        return _result("ed", "Concern for spinal infection — ED today", sla="today")
    if answers.get("recent_trauma") and answers.get("age_over_50_or_osteoporosis"):
        return _result("ed", "Trauma + osteoporosis risk — ED imaging today", sla="today")
    return _result("urgent", "Mechanical back pain — urgent or PCP this week", sla="this week")


def fever(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("temp_over_103_with_lethargy") or answers.get("rash_with_fever"):
        return _result("ed", "High fever with lethargy / rash — ED today", sla="today")
    if answers.get("immunocompromised") or answers.get("recent_chemo"):
        return _result("ed_now", "Immunocompromised + fever — ED now", sla="now")
    if answers.get("fever_5_days_or_more"):
        return _result("urgent", "Prolonged fever — clinic / urgent care today", sla="today")
    return _result("self_care", "Routine viral illness — hydration, antipyretics, ED if worsening", sla="2-3 days")


def cough(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("hemoptysis"):
        return _result("ed", "Hemoptysis — ED today", sla="today")
    if answers.get("with_fever_and_dyspnea"):
        return _result("ed", "Cough with fever and dyspnea — ED evaluation", sla="today")
    if answers.get("over_3_weeks"):
        return _result("urgent", "Chronic cough — clinic this week with possible CXR", sla="this week")
    return _result("self_care", "URI care; recheck if worsening or new red flags", sla="few days")


def peds_fever(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("under_3_months"):
        return _result("ed_now", "Any fever under 3 months requires ED workup now", sla="now")
    if answers.get("under_3_yr_temp_over_104"):
        return _result("ed", "High fever in young child — ED", sla="today")
    if answers.get("rash") or answers.get("lethargy") or answers.get("vomiting"):
        return _result("ed", "Concerning peds fever features — ED", sla="today")
    return _result("urgent", "Routine peds fever — clinic same/next day, antipyretics, hydration", sla="24h")


def laceration(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("uncontrolled_bleeding") or answers.get("arterial_spurting"):
        return _result("911", "Uncontrolled bleeding — 911", sla="now")
    if answers.get("over_30_min_old_with_dirt") or answers.get("animal_bite") or answers.get("on_face_or_hand"):
        return _result("urgent", "Wound needs cleaning + likely closure within 6h", sla="now")
    return _result("self_care", "Clean, pressure, simple bandage; reassess if worsening", sla="hours")


def mental_health_crisis(answers: dict[str, Any]) -> dict[str, Any]:
    if answers.get("active_plan_or_means") or answers.get("homicidal_ideation"):
        return _result("911", "Active plan or means — call 988 or 911 now", sla="now")
    if answers.get("ideation_no_plan_unsafe_at_home"):
        return _result("ed_now", "Suicidal ideation, unsafe at home — ED now", sla="now")
    if answers.get("ideation_no_plan_safe_at_home"):
        return _result("urgent", "Same-day or next-day behavioral health appointment", sla="today")
    return _result("urgent", "Behavioral health follow-up this week", sla="this week")


PROTOCOLS = {
    "chest_pain": chest_pain,
    "shortness_of_breath": shortness_of_breath,
    "abdominal_pain": abdominal_pain,
    "headache": headache,
    "back_pain": back_pain,
    "fever": fever,
    "cough": cough,
    "peds_fever": peds_fever,
    "laceration": laceration,
    "mental_health_crisis": mental_health_crisis,
}


# ---- Structured red-flag interview metadata --------------------------------
# Each protocol's decision tree consumes a fixed set of boolean `answers`.
# The metadata below names every question, gives a patient-facing prompt, and
# tags the disposition a positive answer drives. A caller (voice agent, portal
# triage form, call-center script) walks `interview()` to collect answers and
# then passes them to `evaluate()`. `tier` lets a UI ask the highest-acuity
# red flags first and stop early on a "911" hit.
#
# Question dict shape:
#   {
#     "key": str,              # matches the key chest_pain() et al. read
#     "prompt": str,           # patient-facing yes/no question
#     "red_flag_for": str,     # disposition a True answer pushes toward
#     "tier": "emergent" | "urgent" | "routine",
#   }

def _q(key: str, prompt: str, red_flag_for: str, tier: str = "urgent") -> dict[str, Any]:
    return {"key": key, "prompt": prompt, "red_flag_for": red_flag_for, "tier": tier}


_INTERVIEWS: dict[str, dict[str, Any]] = {
    "chest_pain": {
        "chief_complaint": "Chest pain",
        "questions": [
            _q("severe_or_crushing", "Is the pain severe, crushing, or like a heavy weight?", "911", "emergent"),
            _q("with_dyspnea", "Are you also short of breath?", "ed_now", "emergent"),
            _q("with_diaphoresis", "Are you sweating or clammy?", "ed_now", "emergent"),
            _q("radiating_to_arm_jaw", "Does the pain spread to your arm, neck, or jaw?", "ed_now", "emergent"),
            _q("age_over_50", "Are you over 50 years old?", "ed_now", "urgent"),
            _q("known_cad", "Do you have known heart disease?", "ed_now", "urgent"),
            _q("diabetes", "Do you have diabetes?", "ed_now", "urgent"),
            _q("pleuritic", "Is the pain worse when you breathe in?", "ed", "urgent"),
            _q("trauma", "Did the pain follow an injury to the chest?", "ed", "urgent"),
        ],
    },
    "shortness_of_breath": {
        "chief_complaint": "Shortness of breath",
        "questions": [
            _q("severe_at_rest", "Are you severely short of breath even while sitting still?", "911", "emergent"),
            _q("blue_lips", "Are your lips or fingertips turning blue or gray?", "911", "emergent"),
            _q("known_asthma_failed_inhaler", "Do you have asthma that is not responding to your rescue inhaler?", "ed_now", "emergent"),
            _q("with_chest_pain", "Do you also have chest pain?", "ed_now", "emergent"),
            _q("post_long_travel_or_surgery", "Have you had recent long travel or surgery?", "ed_now", "urgent"),
            _q("fever", "Do you have a fever?", "ed", "urgent"),
            _q("productive_cough", "Are you coughing up mucus or phlegm?", "ed", "urgent"),
        ],
    },
    "abdominal_pain": {
        "chief_complaint": "Abdominal pain",
        "questions": [
            _q("severe_sudden", "Did severe pain come on very suddenly?", "911", "emergent"),
            _q("with_syncope", "Have you fainted or felt close to fainting?", "911", "emergent"),
            _q("rigid_abdomen", "Is your abdomen hard, rigid, or extremely tender?", "ed_now", "emergent"),
            _q("vomiting_blood", "Are you vomiting blood?", "ed_now", "emergent"),
            _q("black_tarry_stool", "Have you had black, tarry, or bloody stools?", "ed_now", "emergent"),
            _q("pregnancy_possible_with_pain", "Is pregnancy possible, with this pain?", "ed_now", "emergent"),
            _q("missed_period_with_pain", "Have you missed a period, with this pain?", "ed_now", "emergent"),
            _q("rlq_pain_with_fever", "Is the pain in the lower right side with a fever?", "ed", "urgent"),
        ],
    },
    "headache": {
        "chief_complaint": "Headache",
        "questions": [
            _q("worst_ever", "Is this the worst headache of your life?", "911", "emergent"),
            _q("thunderclap", "Did it reach maximum intensity within seconds?", "911", "emergent"),
            _q("with_neuro_deficit", "Do you have weakness, numbness, vision changes, or trouble speaking?", "ed_now", "emergent"),
            _q("with_fever_stiff_neck", "Do you have a fever with a stiff neck?", "ed_now", "emergent"),
            _q("immunocompromised", "Is your immune system weakened?", "ed", "urgent"),
            _q("on_anticoagulation", "Are you taking a blood thinner?", "ed", "urgent"),
        ],
    },
    "back_pain": {
        "chief_complaint": "Back pain",
        "questions": [
            _q("saddle_anesthesia", "Do you have numbness in the groin or inner thighs?", "ed_now", "emergent"),
            _q("urinary_retention", "Are you unable to urinate?", "ed_now", "emergent"),
            _q("bowel_incontinence", "Have you lost control of your bowels?", "ed_now", "emergent"),
            _q("with_fever", "Do you have a fever with the back pain?", "ed", "urgent"),
            _q("iv_drug_use", "Do you use intravenous drugs?", "ed", "urgent"),
            _q("immunocompromised", "Is your immune system weakened?", "ed", "urgent"),
            _q("recent_trauma", "Did the pain follow a recent injury or fall?", "ed", "urgent"),
            _q("age_over_50_or_osteoporosis", "Are you over 50 or do you have osteoporosis?", "ed", "urgent"),
        ],
    },
    "fever": {
        "chief_complaint": "Fever",
        "questions": [
            _q("immunocompromised", "Is your immune system weakened?", "ed_now", "emergent"),
            _q("recent_chemo", "Have you had chemotherapy recently?", "ed_now", "emergent"),
            _q("temp_over_103_with_lethargy", "Is your temperature over 103F with unusual drowsiness?", "ed", "urgent"),
            _q("rash_with_fever", "Do you have a new rash with the fever?", "ed", "urgent"),
            _q("fever_5_days_or_more", "Has the fever lasted 5 days or longer?", "urgent", "routine"),
        ],
    },
    "cough": {
        "chief_complaint": "Cough",
        "questions": [
            _q("hemoptysis", "Are you coughing up blood?", "ed", "emergent"),
            _q("with_fever_and_dyspnea", "Do you have a fever and shortness of breath with the cough?", "ed", "urgent"),
            _q("over_3_weeks", "Has the cough lasted more than 3 weeks?", "urgent", "routine"),
        ],
    },
    "peds_fever": {
        "chief_complaint": "Pediatric fever",
        "questions": [
            _q("under_3_months", "Is the child under 3 months old?", "ed_now", "emergent"),
            _q("under_3_yr_temp_over_104", "Is the child under 3 years with a temperature over 104F?", "ed", "emergent"),
            _q("rash", "Does the child have a new rash?", "ed", "urgent"),
            _q("lethargy", "Is the child unusually drowsy or hard to wake?", "ed", "urgent"),
            _q("vomiting", "Is the child repeatedly vomiting?", "ed", "urgent"),
        ],
    },
    "laceration": {
        "chief_complaint": "Cut or laceration",
        "questions": [
            _q("uncontrolled_bleeding", "Is the bleeding not stopping with firm pressure?", "911", "emergent"),
            _q("arterial_spurting", "Is blood spurting from the wound?", "911", "emergent"),
            _q("over_30_min_old_with_dirt", "Is the wound over 30 minutes old and dirty?", "urgent", "urgent"),
            _q("animal_bite", "Was the wound caused by an animal bite?", "urgent", "urgent"),
            _q("on_face_or_hand", "Is the cut on the face or hand?", "urgent", "urgent"),
        ],
    },
    "mental_health_crisis": {
        "chief_complaint": "Mental health crisis",
        "questions": [
            _q("active_plan_or_means", "Do you have a specific plan or the means to harm yourself?", "911", "emergent"),
            _q("homicidal_ideation", "Do you have thoughts of harming someone else?", "911", "emergent"),
            _q("ideation_no_plan_unsafe_at_home", "Do you have thoughts of self-harm and feel unsafe at home?", "ed_now", "emergent"),
            _q("ideation_no_plan_safe_at_home", "Do you have thoughts of self-harm but currently feel safe at home?", "urgent", "urgent"),
        ],
    },
}

# Tier ordering so a caller can ask emergent red flags first.
_TIER_RANK = {"emergent": 0, "urgent": 1, "routine": 2}


def list_protocols() -> list[str]:
    return sorted(PROTOCOLS.keys())


def interview(protocol_key: str) -> dict[str, Any]:
    """Return the structured red-flag interview metadata for a protocol.

    Returns:
      {
        "protocol": str,
        "chief_complaint": str,
        "questions": [{key, prompt, red_flag_for, tier}, ...],  # tier-ordered
        "answer_keys": [str, ...],   # every key evaluate() will read
      }
    Or {"error": ...} for an unknown protocol.
    """
    meta = _INTERVIEWS.get(protocol_key)
    if not meta:
        return {"error": f"unknown protocol '{protocol_key}'"}
    questions = sorted(
        meta["questions"],
        key=lambda q: _TIER_RANK.get(q["tier"], 9),
    )
    return {
        "protocol": protocol_key,
        "chief_complaint": meta["chief_complaint"],
        "questions": questions,
        "answer_keys": [q["key"] for q in questions],
    }


def evaluate(protocol_key: str, answers: dict[str, Any]) -> dict[str, Any]:
    fn = PROTOCOLS.get(protocol_key)
    if not fn:
        return {"error": f"unknown protocol '{protocol_key}'"}
    result = {"protocol": protocol_key, **fn(answers)}

    # Attach the structured red-flag trail: which interview questions the
    # patient answered positively, so the disposition is auditable.
    meta = _INTERVIEWS.get(protocol_key)
    if meta:
        triggered = [
            {"key": q["key"], "prompt": q["prompt"], "red_flag_for": q["red_flag_for"]}
            for q in meta["questions"]
            if answers.get(q["key"])
        ]
        result["red_flags_triggered"] = triggered
        result["red_flag_count"] = len(triggered)
    return result
