"""Claude generates 2-3 short follow-up questions based on the patient's transcript.

Returned to the patient as quick-tap chips or short text inputs. The answers feed
back into the pre-brief + triage.

This module also owns the **abnormal-result loop closure** machinery: a
forward-only state machine that tracks every abnormal lab/imaging result from
the moment it is detected until the patient has acknowledged the clinician's
message. Closures never silently fall through the cracks — they sit in
`outstanding` until a human acts.
"""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from lib import claude, json_extract
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = settings.model_utility


_SYSTEM = """You are a triage nurse asking brief follow-up questions. \
Given a patient's self-description, generate 2-3 short clarifying questions that a triage nurse would ask. \
Each question must be answerable in <10 seconds.

Return JSON ONLY, no preamble or markdown fence, in this exact shape:
[
  {{"id": "q1", "question": "...", "type": "boolean"}},
  {{"id": "q2", "question": "...", "type": "choice", "options": ["option1", "option2", "option3"]}},
  {{"id": "q3", "question": "...", "type": "text"}}
]

Rules:
- Use "boolean" for yes/no questions.
- Use "choice" when there are clear categorical answers (2-5 options max, very short).
- Use "text" only for quantities/qualities that need a phrase (e.g. "how many hours?").
- Max 3 questions. Prefer 2 if fewer are clearly useful.
- Focus on: duration, severity escalation, associated symptoms, prior history, triggers.
- Questions must be plain-language, no clinical jargon ("shortness of breath" OK, "dyspnea" not OK).
- Do NOT repeat what the patient already said in the transcript.
- If the transcript already contains a duration, severity, and key associated symptoms, return [].
- Write the "question" and any "options" in language code: {language}. Keep "id" and "type" in English."""


_FALLBACK: list[dict] = [
    {
        "id": "duration",
        "question": "How long has this been going on?",
        "type": "choice",
        "options": ["< 1 hour", "1-6 hours", "6-24 hours", "> 1 day"],
    },
    {
        "id": "worsening",
        "question": "Is it getting worse?",
        "type": "boolean",
    },
]


def generate_questions(
    transcript: str,
    medical_info: dict[str, Any] | None = None,
    language: str = "en",
) -> list[dict]:
    """Return 0-3 follow-up questions in the patient's language. Falls back on failure."""
    if not claude.available():
        return _FALLBACK
    try:
        info_blob = _summarize_medical_info(medical_info) if medical_info else "not provided"
        user = f"""Patient transcript:
\"\"\"
{transcript.strip()}
\"\"\"

Known medical info: {info_blob}

Return the JSON array now."""
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=500,
            system=_SYSTEM.format(language=(language or "en")[:2]),
            messages=[{"role": "user", "content": user}],
            purpose="followups",
        )
        raw = "".join(b.text for b in resp.content)
        return _parse(raw) or []
    except Exception as e:
        log.exception("Follow-up generation failed: %s", e)
        return _FALLBACK


def _parse(raw: str) -> list[dict]:
    arr = json_extract.extract_array(raw)
    if not arr:
        return []
    cleaned: list[dict] = []
    for idx, item in enumerate(arr if isinstance(arr, list) else []):
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        t = str(item.get("type", "text")).strip().lower()
        if not q or t not in ("boolean", "choice", "text"):
            continue
        entry: dict = {"id": item.get("id") or f"q{idx+1}", "question": q, "type": t}
        if t == "choice":
            opts = item.get("options") or []
            entry["options"] = [str(o) for o in opts if str(o).strip()][:5]
            if not entry["options"]:
                continue
        cleaned.append(entry)
        if len(cleaned) >= 3:
            break
    return cleaned


def _summarize_medical_info(info: dict[str, Any]) -> str:
    """Compact text summary for prompt context."""
    parts = []
    if info.get("age"):
        parts.append(f"{info['age']}yo")
    if info.get("sex"):
        parts.append(str(info["sex"]))
    if info.get("pregnant"):
        parts.append("pregnant")
    for key in ("allergies", "medications", "conditions"):
        arr = info.get(key) or []
        if arr and not (len(arr) == 1 and str(arr[0]).lower() == "none"):
            parts.append(f"{key}: {', '.join(str(x) for x in arr)}")
    return "; ".join(parts) if parts else "none reported"


def format_qa_for_prompts(followup_qa: list[dict]) -> str:
    """Format Q/A pairs for inclusion in downstream Claude prompts."""
    if not followup_qa:
        return ""
    lines = []
    for qa in followup_qa:
        q = str(qa.get("question", "")).strip()
        a = str(qa.get("answer", "")).strip()
        if q and a:
            lines.append(f"- {q} → {a}")
    return "\n".join(lines)


# ===========================================================================
# Abnormal-result loop closure
# ===========================================================================
#
# Closure state model
# -------------------
# A closure is the lifecycle of one abnormal result. It is a *forward-only*
# state machine — once a result advances it can never regress, which guarantees
# that "we already told the patient" can never be undone by a stale write.
#
#   outstanding   -> result detected, nobody has acted yet (the work queue)
#        |
#   communicated  -> clinician sent the patient a plain-language message
#        |
#   acknowledged  -> patient confirmed they received/understood it (TERMINAL)
#
# An orthogonal terminal state exists for results that need no patient contact:
#
#   dismissed     -> clinician judged the result clinically insignificant
#                    (e.g. expected, already known); reachable from any
#                    non-terminal state (TERMINAL)
#
# Each closure is an immutable dict. Transitions return a NEW closure dict with
# an appended `history` entry; the caller persists the returned value. There is
# no in-place mutation, so concurrent readers always see a consistent snapshot.

CLOSURE_STATES = ("outstanding", "communicated", "acknowledged", "dismissed")
_TERMINAL_STATES = frozenset({"acknowledged", "dismissed"})

# Allowed forward transitions. Key = current state, value = states reachable.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "outstanding": frozenset({"communicated", "dismissed"}),
    "communicated": frozenset({"acknowledged", "dismissed"}),
    "acknowledged": frozenset(),
    "dismissed": frozenset(),
}


class ClosureTransitionError(ValueError):
    """Raised when an illegal closure state transition is attempted."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def new_closure(
    *,
    patient_id: str,
    result: dict[str, Any],
    detected_by: str = "system",
) -> dict[str, Any]:
    """Create a fresh closure in the `outstanding` state for one abnormal result.

    `result` is an abnormal-result dict as produced by detect_abnormal_results().
    Returns an immutable closure snapshot — the caller persists it.
    """
    ts = _now_ms()
    closure_id = "clo_" + uuid.uuid4().hex[:16]
    return {
        "closure_id": closure_id,
        "patient_id": str(patient_id),
        "state": "outstanding",
        "result": dict(result),
        "created_at": ts,
        "updated_at": ts,
        "patient_message": None,   # filled when state -> communicated
        "history": [
            {"state": "outstanding", "at": ts, "actor": str(detected_by), "note": "result detected"}
        ],
    }


def advance_closure(
    closure: dict[str, Any],
    *,
    to_state: str,
    actor: str = "clinician",
    note: str = "",
    patient_message: str | None = None,
) -> dict[str, Any]:
    """Return a NEW closure advanced to `to_state`. Forward-only.

    Raises ClosureTransitionError if the transition is not legal from the
    closure's current state. The input dict is never mutated.
    """
    current = closure.get("state", "outstanding")
    if to_state not in CLOSURE_STATES:
        raise ClosureTransitionError(f"unknown closure state: {to_state!r}")
    if current in _TERMINAL_STATES:
        raise ClosureTransitionError(f"closure already terminal ({current}) — cannot advance")
    if to_state not in _TRANSITIONS.get(current, frozenset()):
        raise ClosureTransitionError(f"illegal transition {current} -> {to_state}")

    ts = _now_ms()
    advanced = dict(closure)
    advanced["state"] = to_state
    advanced["updated_at"] = ts
    if to_state == "communicated" and patient_message is not None:
        advanced["patient_message"] = str(patient_message)
    advanced["history"] = list(closure.get("history") or []) + [
        {"state": to_state, "at": ts, "actor": str(actor), "note": str(note)}
    ]
    return advanced


# --- Abnormal-result detection (deterministic, no AI) ----------------------

# Critical analytes — any result outside these hard bounds is flagged "critical"
# regardless of the lab's own reference range. Keys are matched case-insensitive
# against a substring of the result name.
_CRITICAL_BOUNDS: dict[str, tuple[float, float]] = {
    "potassium": (2.5, 6.5),
    "sodium": (120.0, 160.0),
    "glucose": (40.0, 500.0),
    "hemoglobin": (7.0, 20.0),
    "platelet": (20.0, 1000.0),
    "troponin": (0.0, 0.04),
    "creatinine": (0.0, 4.0),
    "inr": (0.0, 5.0),
    "wbc": (1.0, 30.0),
    "calcium": (6.0, 13.0),
    "lactate": (0.0, 4.0),
}

_ABNORMAL_FLAGS = frozenset({"h", "l", "hh", "ll", "a", "aa", "high", "low", "critical", "abnormal", "panic"})
_CRITICAL_FLAGS = frozenset({"hh", "ll", "aa", "critical", "panic"})


def _to_float(v: Any) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def detect_abnormal_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministically pick the abnormal results out of a lab/imaging panel.

    NO AI. A result is abnormal when either:
      - it carries an abnormal flag ("H", "L", "HH", "critical", ...), OR
      - its numeric value falls outside the supplied reference range
        (ref_low / ref_high), OR
      - it breaches a hard critical bound for a known critical analyte.

    Each input result dict may carry: name, value, unit, flag, ref_low,
    ref_high, ref_range (free text), category ("lab"|"imaging").

    Returns a list of abnormal-result dicts, each annotated with:
      severity: "critical" | "abnormal"
      reason:   short human-readable why-flagged string
    """
    abnormal: list[dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", "")).strip()
        if not name:
            continue
        flag = str(r.get("flag", "")).strip().lower()
        value = _to_float(r.get("value"))
        ref_low = _to_float(r.get("ref_low"))
        ref_high = _to_float(r.get("ref_high"))

        is_abnormal = False
        is_critical = False
        reasons: list[str] = []

        if flag in _ABNORMAL_FLAGS:
            is_abnormal = True
            reasons.append(f"flagged {flag.upper()}")
            if flag in _CRITICAL_FLAGS:
                is_critical = True

        if value is not None:
            if ref_low is not None and value < ref_low:
                is_abnormal = True
                reasons.append(f"{value} below reference low {ref_low}")
            if ref_high is not None and value > ref_high:
                is_abnormal = True
                reasons.append(f"{value} above reference high {ref_high}")
            lname = name.lower()
            for analyte, (cmin, cmax) in _CRITICAL_BOUNDS.items():
                if analyte in lname and not (cmin <= value <= cmax):
                    is_abnormal = True
                    is_critical = True
                    reasons.append(f"{value} outside critical bound [{cmin}, {cmax}]")
                    break

        # Imaging / qualitative results: flag text alone drives it.
        if not is_abnormal and str(r.get("category", "")).lower() == "imaging" and flag in _ABNORMAL_FLAGS:
            is_abnormal = True
            reasons.append("imaging flagged abnormal")

        if is_abnormal:
            entry = dict(r)
            entry["name"] = name
            entry["severity"] = "critical" if is_critical else "abnormal"
            entry["reason"] = "; ".join(reasons) if reasons else "outside expected range"
            abnormal.append(entry)
    return abnormal


# --- Plain-language patient messaging --------------------------------------

# Reading-level bands. The clinician picks one; it tunes the prompt.
READING_LEVELS = {
    "simple": "3rd-grade reading level. Very short sentences. Only the most common words.",
    "standard": "6th-grade reading level. Short sentences. Plain everyday words.",
    "detailed": "8th-grade reading level. May name the test and give one extra sentence of context.",
}

_RESULT_MSG_SYSTEM = """You write a short, calm message from a clinic to a patient about ONE of their test results.

{reading_band}

Return JSON ONLY, no preamble or markdown fence:
{{"message": "...", "tone": "reassuring|neutral|urgent"}}

Rules:
- Address the patient directly ("Your blood test ...").
- Say what the result is in plain words, what it may mean, and the ONE next step.
- Never give a diagnosis or a number the clinician did not authorize.
- If the result is critical/urgent, tell them to expect a call and what to watch for.
- Do NOT alarm the patient beyond what the result warrants.
- No medical jargon. No abbreviations.
- Write the message in language code: {language}. Keep the JSON keys in English."""


def _draft_one_message(
    result: dict[str, Any],
    reading_level: str,
    language: str,
) -> dict[str, Any]:
    """Draft a single plain-language patient message for one abnormal result."""
    band = READING_LEVELS.get(reading_level, READING_LEVELS["standard"])
    name = str(result.get("name", "your test"))
    fallback = {
        "result_name": name,
        "severity": result.get("severity", "abnormal"),
        "message": f"One of your recent test results ({name}) needs a quick follow-up. "
                   "Our office will be in touch about the next step.",
        "tone": "neutral",
        "reading_level": reading_level if reading_level in READING_LEVELS else "standard",
        "ai_generated": False,
    }
    if not claude.available():
        return fallback
    try:
        ctx_bits = [f"Test: {name}"]
        if result.get("value") is not None:
            ctx_bits.append(f"Value: {result.get('value')} {result.get('unit', '')}".strip())
        if result.get("ref_range"):
            ctx_bits.append(f"Normal range: {result.get('ref_range')}")
        ctx_bits.append(f"Severity: {result.get('severity', 'abnormal')}")
        ctx_bits.append(f"Why flagged: {result.get('reason', 'outside expected range')}")
        user = "\n".join(ctx_bits) + "\n\nReturn the JSON object now."
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=400,
            system=_RESULT_MSG_SYSTEM.format(
                reading_band=band, language=(language or "en")[:2]
            ),
            messages=[{"role": "user", "content": user}],
            purpose="result_message",
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        obj = json_extract.extract_obj(raw)
        if not obj:
            return fallback
        msg = str(obj.get("message", "")).strip()
        if not msg:
            return fallback
        tone = str(obj.get("tone", "neutral")).strip().lower()
        return {
            "result_name": name,
            "severity": result.get("severity", "abnormal"),
            "message": msg,
            "tone": tone if tone in ("reassuring", "neutral", "urgent") else "neutral",
            "reading_level": reading_level if reading_level in READING_LEVELS else "standard",
            "ai_generated": True,
        }
    except Exception as e:
        log.exception("Result message draft failed for %s: %s", name, e)
        return fallback


def review_results(
    abnormal_results: list[dict[str, Any]],
    *,
    reading_level: str = "standard",
    language: str = "en",
) -> dict[str, Any]:
    """Draft plain-language patient messages for a batch of abnormal results.

    Claude calls run in PARALLEL — one per result. The output is a one-click-send
    review panel: the clinician sees each draft, edits if needed, and sends.

    Returns:
      {
        "reading_level": "...",
        "language": "...",
        "count": N,
        "drafts": [
          {"result_name", "severity", "message", "tone",
           "reading_level", "ai_generated"}, ...
        ]
      }
    """
    results = [r for r in (abnormal_results or []) if isinstance(r, dict)]
    if not results:
        return {"reading_level": reading_level, "language": language, "count": 0, "drafts": []}

    drafts: list[dict[str, Any] | None] = [None] * len(results)
    with ThreadPoolExecutor(max_workers=min(5, len(results))) as pool:
        fut_to_idx = {
            pool.submit(_draft_one_message, r, reading_level, language): i
            for i, r in enumerate(results)
        }
        for fut in as_completed(fut_to_idx):
            idx = fut_to_idx[fut]
            try:
                drafts[idx] = fut.result()
            except Exception as e:  # defensive — _draft_one_message already guards
                log.exception("Result draft worker crashed: %s", e)
                drafts[idx] = {
                    "result_name": str(results[idx].get("name", "your test")),
                    "severity": results[idx].get("severity", "abnormal"),
                    "message": "One of your recent test results needs a quick follow-up.",
                    "tone": "neutral",
                    "reading_level": "standard",
                    "ai_generated": False,
                }
    ordered = [d for d in drafts if d is not None]
    return {
        "reading_level": reading_level if reading_level in READING_LEVELS else "standard",
        "language": language or "en",
        "count": len(ordered),
        "drafts": ordered,
    }


def closure_summary(closures: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll a list of closures into dashboard counts + the work queue.

    Returns:
      {
        "total": N,
        "by_state": {"outstanding": n, "communicated": n,
                     "acknowledged": n, "dismissed": n},
        "open": n,                  # outstanding + communicated
        "closed": n,                # acknowledged + dismissed
        "critical_open": n,         # open closures whose result is critical
        "oldest_open_age_ms": int | None,
        "queue": [ {closure_id, patient_id, state, result_name,
                    severity, age_ms}, ... ]   # open closures, critical first
      }
    """
    by_state = {s: 0 for s in CLOSURE_STATES}
    queue: list[dict[str, Any]] = []
    now = _now_ms()
    critical_open = 0
    oldest: int | None = None

    for c in closures or []:
        if not isinstance(c, dict):
            continue
        state = c.get("state", "outstanding")
        if state in by_state:
            by_state[state] += 1
        if state not in _TERMINAL_STATES:
            result = c.get("result") or {}
            severity = str(result.get("severity", "abnormal"))
            age = now - int(c.get("created_at", now))
            if severity == "critical":
                critical_open += 1
            oldest = age if oldest is None else max(oldest, age)
            queue.append({
                "closure_id": c.get("closure_id"),
                "patient_id": c.get("patient_id"),
                "state": state,
                "result_name": str(result.get("name", "result")),
                "severity": severity,
                "age_ms": age,
            })

    # Critical first, then oldest first.
    queue.sort(key=lambda q: (q["severity"] != "critical", -q["age_ms"]))
    open_n = by_state["outstanding"] + by_state["communicated"]
    closed_n = by_state["acknowledged"] + by_state["dismissed"]
    return {
        "total": sum(by_state.values()),
        "by_state": by_state,
        "open": open_n,
        "closed": closed_n,
        "critical_open": critical_open,
        "oldest_open_age_ms": oldest,
        "queue": queue,
    }
