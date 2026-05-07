"""Auto-redaction of off-record conversation segments + closed-loop result tracking.

**Auto-redaction**: small talk, side conversations, and clearly non-clinical
content are stripped from the scribe transcript before a note is generated. The
redaction is conservative — when in doubt we keep the segment. The clinician
can always view the unredacted transcript.

**Closed-loop result tracking**: every abnormal lab/imaging result generated
through Solace gets a tracking record. If the clinician hasn't acted on it
within a configurable window (default 7 days), the patient and the result are
surfaced on a daily "loop closure" worklist. This addresses the 7-15% of
abnormal results never followed up — a top malpractice driver per Singh et al.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


# Conservative regex-only fast-path. LLM pass refines.
_CHITCHAT = [
    r"^how (?:are|was) (?:you|your weekend|the kids|the family|the dog|the drive|your day)",
    r"^(?:so |well |um |uh |yeah |right )?(?:nice|good|great|terrible|awful) weather",
    r"^did you (?:see|catch|watch) (?:the game|the (?:show|movie))",
    r"^(?:so |well )?how 'bout them",
    r"^(?:can|could) (?:i|you) get (?:you )?some (?:water|coffee)",
]


def _is_obvious_chitchat(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(re.match(p, t) for p in _CHITCHAT)


_LLM_SYSTEM = """You classify conversation segments from a doctor-patient encounter as either \
'clinical' (relevant to medical care) or 'off_record' (small talk, side conversation, non-clinical). \
Be conservative — when uncertain, classify as 'clinical'.

Return JSON ONLY: {"redacted_segment_ids": [int...]}
"""


def redact_segments(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns {kept, redacted, kept_segments, redacted_segments}."""
    redacted_ids: set[int] = set()

    # Fast-path regex
    for s in segments:
        if _is_obvious_chitchat(s.get("content", "")):
            redacted_ids.add(int(s["id"]))

    # LLM pass on remaining ambiguous-looking segments
    if settings.anthropic_api_key:
        candidates = [s for s in segments if int(s["id"]) not in redacted_ids and len(s.get("content", "")) < 200]
        if candidates:
            user = json.dumps([{"id": s["id"], "speaker": s.get("speaker"), "content": s["content"]} for s in candidates])
            try:
                resp = claude.messages_create(
                    model=_MODEL,
                    max_tokens=600,
                    system=_LLM_SYSTEM,
                    messages=[{"role": "user", "content": user[:8000]}],
                    purpose="redaction",
                )
                text = "".join(getattr(b, "text", "") for b in resp.content).strip()
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                out = json.loads(text)
                for i in out.get("redacted_segment_ids", []) or []:
                    redacted_ids.add(int(i))
            except Exception as e:
                log.warning("redaction LLM pass failed: %s", e)

    kept = [s for s in segments if int(s["id"]) not in redacted_ids]
    redacted = [s for s in segments if int(s["id"]) in redacted_ids]
    return {
        "kept_segments": kept,
        "redacted_segments": redacted,
        "kept_count": len(kept),
        "redacted_count": len(redacted),
    }


# ---- Closed-loop result tracking -------------------------------------------------
# Simple in-memory store keyed by tracking_id. DDB-backed in production.
_TRACKED: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds").replace("+00:00", "Z")


def open_loop(
    *,
    patient_id: str,
    clinician_id: str,
    hospital_id: str,
    test_name: str,
    value: str,
    severity: str,                 # "abnormal" | "critical"
    sla_days: int = 7,
) -> dict[str, Any]:
    tid = str(uuid.uuid4())
    entry = {
        "tracking_id": tid,
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "test_name": test_name,
        "value": value,
        "severity": severity,
        "opened_at": _now_iso(),
        "sla_days": sla_days,
        "closed_at": None,
        "closed_by": None,
        "close_action": None,
    }
    _TRACKED[tid] = entry
    return entry


def close_loop(tracking_id: str, *, closed_by: str, action: str) -> dict[str, Any] | None:
    e = _TRACKED.get(tracking_id)
    if not e:
        return None
    e["closed_at"] = _now_iso()
    e["closed_by"] = closed_by
    e["close_action"] = action
    return e


def open_loops(hospital_id: str | None = None) -> list[dict[str, Any]]:
    items = list(_TRACKED.values())
    if hospital_id:
        items = [i for i in items if i["hospital_id"] == hospital_id]
    return [i for i in items if i["closed_at"] is None]


def overdue_worklist(hospital_id: str | None = None) -> list[dict[str, Any]]:
    out = []
    now = _now()
    for e in open_loops(hospital_id):
        opened = datetime.fromisoformat(e["opened_at"].replace("Z", "+00:00"))
        sla = timedelta(days=int(e["sla_days"]))
        # Critical results trigger after 1 day regardless of SLA
        urgent_after = timedelta(days=1) if e["severity"] == "critical" else sla
        if now - opened > urgent_after:
            days_overdue = max(0, (now - opened - urgent_after).days)
            out.append({**e, "days_overdue": days_overdue})
    out.sort(key=lambda x: x["days_overdue"], reverse=True)
    return out
