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


# --- Segment labels ---------------------------------------------------------
# A segment is one of:
#   clinical              -> always kept (relevant to medical care)
#   small_talk            -> greetings, weather, weekend chatter — redact
#   side_conversation     -> talk with a third party / on the phone — redact
#   sensitive_nonclinical -> non-clinical but private (finances, immigration,
#                            relationship details unrelated to care) — redact
#                            so it never lands in the durable note
# Anything we cannot confidently bucket defaults to `clinical` (keep).
_OFF_RECORD_LABELS = {"small_talk", "side_conversation", "sensitive_nonclinical"}
_VALID_LABELS = {"clinical"} | _OFF_RECORD_LABELS


# Conservative regex fast-path. Each entry maps a pattern to an off-record
# label so the deterministic pass produces the same shape as the LLM pass.
# The LLM pass only refines segments the regex did not already decide.
_FASTPATH: list[tuple[str, str]] = [
    # --- small_talk ---------------------------------------------------------
    (r"^how (?:are|was|is) (?:you|your weekend|your day|your week|the kids|"
     r"the family|the dog|the drive|the holidays|everything)", "small_talk"),
    (r"^(?:so |well |um |uh |yeah |right |ok |okay )*(?:nice|good|great|lovely|"
     r"terrible|awful|cold|hot|rainy|beautiful) (?:weather|day|morning|out there)", "small_talk"),
    (r"^did you (?:see|catch|watch) (?:the game|the (?:show|movie|news|episode))", "small_talk"),
    (r"^(?:so |well )?how 'bout (?:them|those|that)", "small_talk"),
    (r"^(?:can|could) (?:i|you) get (?:you )?(?:some )?(?:water|coffee|tea|juice)", "small_talk"),
    (r"^(?:good|great) to (?:see|meet) you", "small_talk"),
    (r"^(?:happy|merry) (?:birthday|holidays|new year|thanksgiving)", "small_talk"),
    (r"^(?:thanks|thank you)(?: so much)?(?: for (?:coming|waiting|your patience))?\.?$", "small_talk"),
    (r"^(?:have a |you too|take care)\b.*\b(?:weekend|day|night|one)\b", "small_talk"),
    (r"^(?:sorry|apologies) (?:for|about) the wait", "small_talk"),
    (r"^did you (?:find|have) (?:any |much )?(?:trouble |problem )?(?:parking|finding (?:the|us))", "small_talk"),
    # --- side_conversation --------------------------------------------------
    (r"^(?:hey |hi )?(?:nurse|doctor|can someone|could someone)\b.*\b(?:next room|"
     r"down the hall|room \d|the front|reception)", "side_conversation"),
    (r"^(?:excuse me|hold on|one (?:sec|second|moment)|just a (?:sec|second|moment))\b.*"
     r"(?:phone|call|page|text|message)", "side_conversation"),
    (r"^(?:let me|i('ll| will)) (?:just )?(?:take|grab|answer) this (?:call|page)", "side_conversation"),
    (r"\b(?:talking|speaking) to (?:my|the) (?:colleague|assistant|the front desk)\b", "side_conversation"),
]
_FASTPATH_RX: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), label) for p, label in _FASTPATH
]


def _fastpath_label(text: str) -> str | None:
    """Return an off-record label if the regex fast-path is confident, else None."""
    t = (text or "").strip()
    if not t:
        return None
    for rx, label in _FASTPATH_RX:
        if rx.search(t):
            return label
    return None


# Backward-compatible helper retained for callers that only need a boolean.
def _is_obvious_chitchat(text: str) -> bool:
    return _fastpath_label(text) is not None


_LLM_SYSTEM = """You label conversation segments from a doctor-patient encounter.

For each segment assign exactly one label:
  - "clinical": relevant to medical care — symptoms, history, exam, plan,
    medications, results, scheduling of care, anything a clinician would
    want in the chart.
  - "small_talk": greetings, weather, weekend/holiday chatter, pleasantries.
  - "side_conversation": the speaker is talking to a third party, on a phone
    call, or to staff about something unrelated to this patient's care.
  - "sensitive_nonclinical": private but NOT medically relevant — finances,
    immigration status, legal matters, relationship gossip unrelated to care.

Be conservative: if a segment is ambiguous, or if redacting it could remove
clinical context, label it "clinical". Keeping a borderline segment is always
safer than dropping clinical information.

Return JSON ONLY: {"labels": [{"id": int, "label": "clinical|small_talk|side_conversation|sensitive_nonclinical"}, ...]}
"""


def redact_segments(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify scribe segments and split kept (clinical) from redacted (off-record).

    Returns:
      {
        "kept_segments": [...],          # label == "clinical"
        "redacted_segments": [...],      # each has an added "redaction_label"
        "kept_count": int,
        "redacted_count": int,
        "labels": {seg_id: label},       # full label map for every segment
        "label_source": {seg_id: "regex"|"llm"|"default"},
      }
    """
    labels: dict[int, str] = {}
    source: dict[int, str] = {}

    # 1. Deterministic regex fast-path.
    for s in segments:
        sid = int(s["id"])
        hit = _fastpath_label(s.get("content", ""))
        if hit:
            labels[sid] = hit
            source[sid] = "regex"

    # 2. LLM classifier on segments the regex did not decide.
    if settings.anthropic_api_key:
        candidates = [
            s for s in segments
            if int(s["id"]) not in labels and len(s.get("content", "")) < 400
        ]
        if candidates:
            user = json.dumps([
                {"id": s["id"], "speaker": s.get("speaker"), "content": s["content"]}
                for s in candidates
            ])
            try:
                resp = claude.messages_create(
                    model=_MODEL,
                    max_tokens=900,
                    system=_LLM_SYSTEM,
                    messages=[{"role": "user", "content": user[:9000]}],
                    purpose="redaction",
                )
                text = "".join(getattr(b, "text", "") for b in resp.content).strip()
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                out = json.loads(text)
                for item in out.get("labels", []) or []:
                    try:
                        sid = int(item["id"])
                        lbl = str(item["label"]).strip().lower()
                    except (KeyError, TypeError, ValueError):
                        continue
                    # Keep-when-in-doubt: an unrecognized label becomes clinical.
                    if lbl not in _VALID_LABELS:
                        lbl = "clinical"
                    labels[sid] = lbl
                    source[sid] = "llm"
            except Exception as e:
                log.warning("redaction LLM pass failed: %s", e)

    # 3. Conservative default — anything still unlabeled is kept as clinical.
    for s in segments:
        sid = int(s["id"])
        if sid not in labels:
            labels[sid] = "clinical"
            source[sid] = "default"

    kept = [s for s in segments if labels[int(s["id"])] == "clinical"]
    redacted = [
        {**s, "redaction_label": labels[int(s["id"])]}
        for s in segments
        if labels[int(s["id"])] in _OFF_RECORD_LABELS
    ]
    return {
        "kept_segments": kept,
        "redacted_segments": redacted,
        "kept_count": len(kept),
        "redacted_count": len(redacted),
        "labels": {sid: lbl for sid, lbl in labels.items()},
        "label_source": {sid: src for sid, src in source.items()},
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
