"""Per-clinician note-style learning — data-collection pipeline.

Captures (AI draft, clinician final) pairs for every published note. The pairs
are the training corpus for a per-clinician LoRA fine-tune (Llama 3.3 8B or
Meditron 8B). We don't fine-tune in real time; we collect the pairs, surface
edit-pattern analytics so the clinician sees what their AI is learning, and
when ≥300 pairs accumulate per clinician we flag the corpus as ready to
train.

Edit-pattern analytics:
  - Average edit distance per draft
  - Most-edited section
  - Most-added clinical phrases (n-gram delta)
  - Most-removed clinical phrases
  - Per-section accept rate

This data is a moat — every visit makes the next visit's draft better in the
clinician's own voice.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

log = logging.getLogger(__name__)


# In-memory store; production swap to DDB / S3 NDJSON.
_PAIRS: list[dict[str, Any]] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ngrams(text: str, n: int) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z\-/0-9]{1,}", (text or "").lower())
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _diff_chars(a: str, b: str) -> int:
    sm = SequenceMatcher(a=a or "", b=b or "")
    return int((1 - sm.ratio()) * max(len(a or ""), len(b or "")))


def record_pair(*, clinician_id: str, hospital_id: str, ai_draft: str, final: str, section: str = "full_note") -> dict[str, Any]:
    entry = {
        "id": str(uuid.uuid4()),
        "ts": _now_iso(),
        "clinician_id": clinician_id,
        "hospital_id": hospital_id,
        "section": section,
        "ai_draft": ai_draft,
        "final": final,
        "diff_chars": _diff_chars(ai_draft, final),
        "draft_len": len(ai_draft or ""),
        "final_len": len(final or ""),
    }
    _PAIRS.append(entry)
    return {"id": entry["id"], "diff_chars": entry["diff_chars"]}


def clinician_pairs(clinician_id: str) -> list[dict[str, Any]]:
    return [p for p in _PAIRS if p["clinician_id"] == clinician_id]


def style_profile(clinician_id: str) -> dict[str, Any]:
    pairs = clinician_pairs(clinician_id)
    if not pairs:
        return {"clinician_id": clinician_id, "pair_count": 0, "ready_to_train": False}

    total_added: Counter[str] = Counter()
    total_removed: Counter[str] = Counter()
    section_counts: Counter[str] = Counter()
    section_edits: dict[str, list[int]] = {}

    for p in pairs:
        section_counts[p["section"]] += 1
        section_edits.setdefault(p["section"], []).append(p["diff_chars"])
        ai = set(_ngrams(p["ai_draft"], 2))
        final = set(_ngrams(p["final"], 2))
        for added in final - ai:
            total_added[added] += 1
        for removed in ai - final:
            total_removed[removed] += 1

    section_edit_avg = {s: round(sum(v) / max(1, len(v)), 1) for s, v in section_edits.items()}
    return {
        "clinician_id": clinician_id,
        "pair_count": len(pairs),
        "avg_diff_chars": round(sum(p["diff_chars"] for p in pairs) / len(pairs), 1),
        "section_counts": dict(section_counts),
        "section_edit_avg_chars": section_edit_avg,
        "top_added_phrases": total_added.most_common(15),
        "top_removed_phrases": total_removed.most_common(15),
        "ready_to_train": len(pairs) >= 300,
    }


def export_training_jsonl(clinician_id: str) -> str:
    pairs = clinician_pairs(clinician_id)
    lines = []
    for p in pairs:
        lines.append(
            '{"messages": [{"role": "user", "content": ' + repr(p["ai_draft"])
            + '}, {"role": "assistant", "content": ' + repr(p["final"]) + '}]}'
        )
    return "\n".join(lines)
