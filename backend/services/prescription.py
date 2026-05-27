"""Claude-powered prescription suggestions. Clearly AI — every one is shown to the physician
with cautions from the patient's known allergies + medications. The physician writes the final Rx.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings
from lib.medical_format import format_medical_info
from services import drug_interactions

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_SYSTEM = """You are an ER prescribing reference. Given a patient's symptoms, ESI, and history,
suggest 1-3 standard ER prescriptions a physician might consider.

Rules:
- NEVER present these as definitive. They are AI suggestions the physician will verify.
- Respect the patient's allergies — if a standard suggestion is contraindicated, SKIP it or substitute.
- Flag interactions with the patient's existing medications in the "cautions" field.
- Use generic drug names (ibuprofen, not Advil).
- Keep each suggestion to a standard ER dose + course. No exotic/off-label.
- If the complaint is clearly non-pharmacologic (sprain, minor cut, refill of unrelated med), return [].

Return JSON ONLY, no preamble, no markdown fence:
[
  {
    "drug": "generic name",
    "dose": "e.g. 600 mg",
    "route": "PO | IV | IM | SL | PR",
    "frequency": "e.g. q6h PRN",
    "duration": "e.g. 5 days",
    "indication": "one-line rationale",
    "cautions": "interaction or allergy note specific to this patient, else empty string"
  }
]"""


def suggest(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
) -> list[dict]:
    if not settings.anthropic_api_key:
        return []
    try:
        from services.followups import format_qa_for_prompts

        parts = [f'Transcript:\n"""\n{transcript.strip()}\n"""', f"ESI: {esi_level}"]
        if medical_info:
            parts.append(f"Medical info: {format_medical_info(medical_info)}")
        if followup_qa:
            qa = format_qa_for_prompts(followup_qa)
            if qa:
                parts.append(f"Follow-up Q&A:\n{qa}")
        if photo_analysis and photo_analysis.get("description"):
            parts.append(f"Photo: {photo_analysis['description']}")
        parts.append("Return the JSON array now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="prescription",
        )
        raw = "".join(b.text for b in resp.content)
        suggestions = _parse(raw)
        return _apply_interaction_checks(suggestions, medical_info, transcript)
    except Exception as e:
        log.exception("Prescription suggestion failed: %s", e)
        return []


def _patient_meds(medical_info: dict[str, Any] | None) -> list[str]:
    if not medical_info:
        return []
    meds = medical_info.get("medications") or []
    return [str(m).strip() for m in meds if m and str(m).strip()]


def _patient_allergies(medical_info: dict[str, Any] | None) -> list[str]:
    if not medical_info:
        return []
    allergies = medical_info.get("allergies") or []
    return [str(a).strip() for a in allergies if a and str(a).strip()]


def _format_alert(alert: dict[str, Any]) -> str:
    """Render one drug_interactions alert as a short physician-facing line."""
    sev = (alert.get("severity") or "").lower()
    prefix = sev.upper() if sev else "ALERT"
    reason = alert.get("reason") or alert.get("guidance") or ""
    if "a" in alert and "b" in alert:          # drug-drug
        return f"[{prefix}] {alert['a']} + {alert['b']}: {reason}"
    if "child_pugh" in alert:                  # hepatic
        return f"[{prefix}] hepatic ({alert['med']}): {reason}"
    if "threshold" in alert or "crcl" in alert:  # renal
        return f"[{prefix}] renal ({alert['med']}): {reason}"
    if "med" in alert:                         # drug-allergy
        return f"[{prefix}] allergy ({alert['med']}): {reason}"
    if "drug_class" in alert:                  # duplicate therapy
        return f"[{prefix}] duplicate {alert['drug_class']}: {reason}"
    return f"[{prefix}] {reason}".strip()


def _apply_interaction_checks(
    suggestions: list[dict],
    medical_info: dict[str, Any] | None,
    transcript: str,
) -> list[dict]:
    """Run each Claude-suggested drug through drug_interactions.check() against
    the patient's known meds + allergies, and merge any surfaced alerts into
    that suggestion's `cautions` field.

    The drug under evaluation is added to the patient's current med list so
    drug-drug, drug-allergy, renal, hepatic and duplicate-therapy checks all
    fire for the proposed prescription. Gating is delegated to check() via the
    chief complaint, so trivial-visit noise is suppressed automatically.
    """
    if not suggestions:
        return suggestions

    patient_meds = _patient_meds(medical_info)
    allergies = _patient_allergies(medical_info)
    egfr = None
    child_pugh = None
    if medical_info:
        egfr = medical_info.get("egfr") or medical_info.get("crcl")
        child_pugh = medical_info.get("child_pugh")

    for s in suggestions:
        drug = s.get("drug", "")
        if not drug:
            continue
        try:
            result = drug_interactions.check(
                patient_meds + [drug],
                allergies=allergies,
                egfr=egfr,
                child_pugh=child_pugh,
                complaint=transcript,
            )
        except Exception as e:  # never let a check failure drop a suggestion
            log.exception("Interaction check failed for %s: %s", drug, e)
            continue

        drug_canon = drug_interactions._canon(drug)
        lines: list[str] = []
        for alert in result.get("drug_drug", []):
            if drug_canon in (alert.get("a"), alert.get("b")):
                lines.append(_format_alert(alert))
        for category in ("drug_allergy", "renal", "hepatic"):
            for alert in result.get(category, []):
                if alert.get("med") == drug_canon:
                    lines.append(_format_alert(alert))
        for alert in result.get("duplicate_therapy", []):
            if drug_canon in (alert.get("members") or []):
                lines.append(_format_alert(alert))

        if lines:
            existing = s.get("cautions", "").strip()
            merged = "; ".join(lines)
            s["cautions"] = f"{existing}; {merged}" if existing else merged

    return suggestions




def _parse(raw: str) -> list[dict]:
    raw = raw.strip()
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        arr = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    cleaned: list[dict] = []
    for item in arr if isinstance(arr, list) else []:
        if not isinstance(item, dict):
            continue
        drug = str(item.get("drug", "")).strip()
        if not drug:
            continue
        cleaned.append(
            {
                "drug": drug,
                "dose": str(item.get("dose", "")).strip(),
                "route": str(item.get("route", "")).strip(),
                "frequency": str(item.get("frequency", "")).strip(),
                "duration": str(item.get("duration", "")).strip(),
                "indication": str(item.get("indication", "")).strip(),
                "cautions": str(item.get("cautions", "")).strip(),
            }
        )
        if len(cleaned) >= 3:
            break
    return cleaned
