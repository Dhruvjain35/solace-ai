"""I-PASS / SBAR handoff generator.

I-PASS (Illness severity, Patient summary, Action list, Situation awareness,
Synthesis by receiver) is the gold-standard handoff structure shown in NEJM
(Starmer 2014) to cut handoff errors 30%. SBAR (Situation, Background,
Assessment, Recommendation) is the verbal counterpart used for one-shot
consults / curbside calls.

Both shapes are auto-generated from the chart context. Output is structured
JSON + a human-readable string ready to be pasted into a sign-out tool.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


_IPASS_SYSTEM = """You are generating an I-PASS handoff sign-out from a chart context.

Return JSON ONLY:
{
  "illness_severity": "stable | watcher | unstable",
  "patient_summary": "1-3 short sentences: age, sex, hospital day, principal dx, key relevant comorbidities",
  "action_list": [
    {"action": "short imperative sentence", "by_when": "shift / 6h / 24h / etc.", "responsible": "covering team / day team / night team"}
  ],
  "situation_awareness": "1-2 sentences on what could go wrong overnight or in the next handoff window, with any contingency plans",
  "synthesis_prompt": "1 sentence directing the receiver to read back the most critical action item"
}

Rules:
- Use clinical shorthand.
- Action items are imperative ("repeat lactate at 02:00", "reassess if BP <90").
- 'illness_severity' is your best inference from the chart; default to 'watcher' if unclear.
"""


_SBAR_SYSTEM = """You are generating an SBAR consult / curbside summary from a chart context.

Return JSON ONLY:
{
  "situation": "1 sentence on the immediate concern and the ask",
  "background": "2-4 sentences of relevant history, dx, prior workup, current meds",
  "assessment": "1-2 sentences with the working impression and any pertinent differential",
  "recommendation": "1-2 sentences with what you are asking the consultant to do or recommend"
}

Rules:
- Lead with the ask (situation includes 'I'm calling because...').
- Background is filtered to what the consultant needs.
- Recommendation is concrete (admit, see today, image, advise).
"""


def ipass(chart_context: dict[str, Any]) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"available": False, "reason": "anthropic_key_missing"}
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_IPASS_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(chart_context)[:6000]}],
            purpose="ipass_handoff",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
    except Exception as e:
        log.warning("ipass failed: %s", e)
        return {"available": False, "error": str(e)}
    data["available"] = True
    data["rendered_text"] = _render_ipass(data)
    return data


def _render_ipass(d: dict[str, Any]) -> str:
    lines = [
        f"Illness severity: {d.get('illness_severity', '')}",
        f"Patient summary: {d.get('patient_summary', '')}",
        "Action list:",
    ]
    for a in d.get("action_list") or []:
        lines.append(f"  - {a.get('action', '')} [{a.get('by_when','')}, {a.get('responsible','')}]")
    lines.append(f"Situation awareness: {d.get('situation_awareness', '')}")
    lines.append(f"Synthesis: {d.get('synthesis_prompt', '')}")
    return "\n".join(lines)


def sbar(chart_context: dict[str, Any], *, consult_specialty: str = "cardiology", reason: str = "") -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"available": False, "reason": "anthropic_key_missing"}
    payload = {"chart": chart_context, "consult_specialty": consult_specialty, "reason": reason}
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=700,
            system=_SBAR_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)[:6000]}],
            purpose="sbar_consult",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
    except Exception as e:
        log.warning("sbar failed: %s", e)
        return {"available": False, "error": str(e)}
    data["available"] = True
    data["rendered_text"] = (
        f"Situation: {data.get('situation','')}\n"
        f"Background: {data.get('background','')}\n"
        f"Assessment: {data.get('assessment','')}\n"
        f"Recommendation: {data.get('recommendation','')}"
    )
    return data
