"""I-PASS / SBAR handoff generator.

I-PASS (Illness severity, Patient summary, Action list, Situation awareness,
Synthesis by receiver) is the gold-standard handoff structure shown in NEJM
(Starmer 2014) to cut handoff errors 30%. SBAR (Situation, Background,
Assessment, Recommendation) is the verbal counterpart used for one-shot
consults / curbside calls.

Both shapes are auto-generated from the chart context. Output is structured
JSON + a human-readable string ready to be pasted into a sign-out tool.

Depth added here:
  - Each action item is graded by priority and tagged with a contingency
    ("if X then Y") so the covering team knows the failure mode.
  - The chart context is checked for completeness; missing high-value fields
    are surfaced under 'context_gaps' so the clinician knows what the model
    could not see.
  - Rendered text is structured for direct paste into Epic/Cerner sign-out.

Public interface (consumed by routers/clinical_ai.py):
  - ``ipass(chart_context)``                              -> dict
  - ``sbar(chart_context, consult_specialty=, reason=)``  -> dict
"""
from __future__ import annotations

import json
import logging
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

# High-value chart fields. If absent, the handoff is generated but the gap is
# surfaced so the clinician knows what the model was working without.
_IPASS_EXPECTED_FIELDS = ("age", "sex", "principal_dx", "hospital_day", "vitals", "medications")
_SBAR_EXPECTED_FIELDS = ("age", "sex", "principal_dx", "medications", "workup")


def _context_gaps(chart_context: dict[str, Any], expected: tuple[str, ...]) -> list[str]:
    """Return expected fields that are missing or empty in the chart context."""
    gaps: list[str] = []
    for field in expected:
        value = chart_context.get(field) if isinstance(chart_context, dict) else None
        if value in (None, "", [], {}):
            gaps.append(field)
    return gaps


_IPASS_SYSTEM = """You are generating an I-PASS handoff sign-out from a chart context.

Return JSON ONLY:
{
  "illness_severity": "stable | watcher | unstable",
  "severity_rationale": "1 short clause explaining the severity call",
  "patient_summary": "1-3 short sentences: age, sex, hospital day, principal dx, key relevant comorbidities",
  "action_list": [
    {
      "action": "short imperative sentence",
      "priority": "critical | routine | if-needed",
      "by_when": "shift / 6h / 24h / etc.",
      "responsible": "covering team / day team / night team",
      "contingency": "if X then Y — the failure mode and what to do; empty string if none"
    }
  ],
  "situation_awareness": "1-2 sentences on what could go wrong overnight or in the next handoff window, with any contingency plans",
  "anticipated_problems": ["short bullets — concrete things likely to come up overnight"],
  "synthesis_prompt": "1 sentence directing the receiver to read back the most critical action item"
}

Rules:
- Use clinical shorthand.
- Action items are imperative ("repeat lactate at 02:00", "reassess if BP <90").
- Order action_list with 'critical' items first.
- Every 'critical' action should carry a non-empty contingency.
- 'illness_severity' is your best inference from the chart; default to 'watcher' if unclear.
"""


_SBAR_SYSTEM = """You are generating an SBAR consult / curbside summary from a chart context.

Return JSON ONLY:
{
  "situation": "1 sentence on the immediate concern and the ask (include 'I'm calling because...')",
  "background": "2-4 sentences of relevant history, dx, prior workup, current meds",
  "assessment": "1-2 sentences with the working impression and any pertinent differential",
  "recommendation": "1-2 sentences with what you are asking the consultant to do or recommend",
  "urgency": "emergent | urgent | routine",
  "specific_questions": ["concrete questions for the consultant — what you need answered"]
}

Rules:
- Lead with the ask (situation includes 'I'm calling because...').
- Background is filtered to what the consultant needs.
- Recommendation is concrete (admit, see today, image, advise).
- 'urgency' reflects how fast the consultant must respond.
"""


def ipass(chart_context: dict[str, Any]) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"available": False, "reason": "anthropic_key_missing"}
    gaps = _context_gaps(chart_context, _IPASS_EXPECTED_FIELDS)
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1100,
            system=_IPASS_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(chart_context)[:6000]}],
            purpose="ipass_handoff",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
    except Exception as e:
        log.warning("ipass failed: %s", e)
        return {"available": False, "error": str(e), "context_gaps": gaps}
    data["available"] = True
    data["context_gaps"] = gaps
    data["critical_action_count"] = sum(
        1 for a in (data.get("action_list") or []) if a.get("priority") == "critical"
    )
    data["rendered_text"] = _render_ipass(data)
    return data


def _render_ipass(d: dict[str, Any]) -> str:
    severity = d.get("illness_severity", "")
    rationale = d.get("severity_rationale", "")
    lines = [
        f"Illness severity: {severity}" + (f" ({rationale})" if rationale else ""),
        f"Patient summary: {d.get('patient_summary', '')}",
        "Action list:",
    ]
    for a in d.get("action_list") or []:
        prio = (a.get("priority") or "routine").upper()
        line = f"  [{prio}] {a.get('action', '')} [{a.get('by_when', '')}, {a.get('responsible', '')}]"
        contingency = a.get("contingency")
        if contingency:
            line += f"\n      contingency: {contingency}"
        lines.append(line)
    anticipated = d.get("anticipated_problems") or []
    if anticipated:
        lines.append("Anticipated problems:")
        lines.extend(f"  - {p}" for p in anticipated)
    lines.append(f"Situation awareness: {d.get('situation_awareness', '')}")
    lines.append(f"Synthesis: {d.get('synthesis_prompt', '')}")
    return "\n".join(lines)


def sbar(chart_context: dict[str, Any], *, consult_specialty: str = "cardiology", reason: str = "") -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"available": False, "reason": "anthropic_key_missing"}
    gaps = _context_gaps(chart_context, _SBAR_EXPECTED_FIELDS)
    payload = {"chart": chart_context, "consult_specialty": consult_specialty, "reason": reason}
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_SBAR_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)[:6000]}],
            purpose="sbar_consult",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
    except Exception as e:
        log.warning("sbar failed: %s", e)
        return {"available": False, "error": str(e), "context_gaps": gaps}
    data["available"] = True
    data["context_gaps"] = gaps
    data["consult_specialty"] = consult_specialty
    data["rendered_text"] = _render_sbar(data, consult_specialty)
    return data


def _render_sbar(d: dict[str, Any], consult_specialty: str) -> str:
    urgency = d.get("urgency", "")
    header = f"SBAR consult to {consult_specialty}" + (f" [{urgency}]" if urgency else "")
    lines = [
        header,
        f"Situation: {d.get('situation', '')}",
        f"Background: {d.get('background', '')}",
        f"Assessment: {d.get('assessment', '')}",
        f"Recommendation: {d.get('recommendation', '')}",
    ]
    questions = d.get("specific_questions") or []
    if questions:
        lines.append("Specific questions:")
        lines.extend(f"  - {q}" for q in questions)
    return "\n".join(lines)
