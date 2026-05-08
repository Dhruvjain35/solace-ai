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


def list_protocols() -> list[str]:
    return sorted(PROTOCOLS.keys())


def evaluate(protocol_key: str, answers: dict[str, Any]) -> dict[str, Any]:
    fn = PROTOCOLS.get(protocol_key)
    if not fn:
        return {"error": f"unknown protocol '{protocol_key}'"}
    return {"protocol": protocol_key, **fn(answers)}
