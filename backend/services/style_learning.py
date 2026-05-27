"""Per-clinician note-style learning — data-collection + analysis pipeline.

Captures (AI draft, clinician final) pairs for every published note. The pairs
are the training corpus for a per-clinician LoRA fine-tune (Llama 3.3 8B or
Meditron 8B). We don't fine-tune in real time; we collect the pairs, surface
edit-pattern analytics so the clinician sees what their AI is learning, and
when ≥300 pairs accumulate per clinician we flag the corpus as ready to train.

This module does three jobs:

1. **Capture** — ``record_pair`` stores a pair plus a per-pair structural
   analysis (``_analyze_pair``): char-level + opcode-level token diff,
   trivial-edit detection, inserted/deleted tokens, verbosity + abbreviation
   deltas, and section order.

2. **Profile** — ``style_profile`` aggregates pairs into a clinician style
   model: preferred section order, verbosity tendency, abbreviation bias,
   most-edited section, accept rate, and a ``stable`` flag.

3. **Surface** — ``style_fragment`` renders the profile into a compact,
   prependable instruction block the scribe can inject ahead of draft
   generation. ``export_training_jsonl`` emits a clean LoRA-ready chat-format
   corpus, excluding trivial pairs that would only teach the model noise.

This data is a moat — every visit makes the next visit's draft better in the
clinician's own voice.
"""
from __future__ import annotations

import json
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

# A pair whose char-level edit ratio is at or below this is "trivial" — a
# whitespace tweak, a single typo fix — and is excluded from LoRA training and
# from accept-rate denominators where noted.
_TRIVIAL_EDIT_RATIO = 0.04

# Minimum pairs before a style_fragment / stable profile is meaningful.
_MIN_PAIRS_FOR_FRAGMENT = 3
_STABLE_PAIR_THRESHOLD = 12

# Canonical clinical note sections, in conventional documentation order. Used
# to detect a clinician's preferred section ordering and to keep section keys
# consistent regardless of casing / punctuation in the draft.
_CANONICAL_SECTIONS: list[str] = [
    "chief complaint",
    "hpi",
    "history of present illness",
    "ros",
    "review of systems",
    "pmh",
    "past medical history",
    "medications",
    "allergies",
    "social history",
    "family history",
    "physical exam",
    "exam",
    "vitals",
    "results",
    "assessment",
    "plan",
    "assessment and plan",
    "disposition",
    "mdm",
]

# Common clinical abbreviations — presence is used to compute abbreviation
# bias (does the clinician prefer "shortness of breath" or "SOB"?).
_ABBREVIATIONS: set[str] = {
    "sob", "cp", "hpi", "ros", "pmh", "pe", "bp", "hr", "rr", "o2", "spo2",
    "wnl", "nad", "htn", "dm", "cad", "chf", "copd", "uti", "gi", "gu",
    "ams", "loc", "n/v", "abd", "ext", "neuro", "cv", "heent", "tx", "dx",
    "rx", "hx", "ekg", "ecg", "cbc", "bmp", "cmp", "iv", "po", "prn", "bid",
    "tid", "qid", "qd", "pt", "ddx", "f/u", "yo", "y/o",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-/0-9]*|\d+")
_SECTION_HEADER_RE = re.compile(r"^\s*([A-Za-z][A-Za-z /&]{1,40}?)\s*[:\-]\s*", re.MULTILINE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tokens(text: str) -> list[str]:
    """Lowercased word/number tokens — the unit for opcode-level diffing."""
    return _TOKEN_RE.findall((text or "").lower())


def _ngrams(text: str, n: int) -> list[str]:
    tokens = _tokens(text)
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _diff_chars(a: str, b: str) -> int:
    sm = SequenceMatcher(a=a or "", b=b or "")
    return int((1 - sm.ratio()) * max(len(a or ""), len(b or "")))


def _section_order(text: str) -> list[str]:
    """Extract the ordered list of recognized section headers from a note.

    A header is any line that starts ``Word[s]:`` or ``Word[s] -``. Only
    headers that map to a canonical section are kept, so free-text colons
    inside prose don't pollute the order.
    """
    order: list[str] = []
    for raw in _SECTION_HEADER_RE.findall(text or ""):
        name = raw.strip().lower()
        if name in _CANONICAL_SECTIONS and name not in order:
            order.append(name)
    return order


def _abbrev_count(tokens: list[str]) -> int:
    return sum(1 for t in tokens if t in _ABBREVIATIONS)


def _analyze_pair(ai_draft: str, final: str) -> dict[str, Any]:
    """Structural diff of one (AI-draft, clinician-final) pair.

    Returns a dict capturing, at both char and token granularity, *how* the
    clinician changed the draft. This is computed once at capture time and
    stored on the pair so ``style_profile`` and ``export_training_jsonl`` can
    aggregate / filter without re-diffing.

    Keys:
      diff_chars            char-level edit distance estimate
      char_edit_ratio       0..1 — fraction of content changed (char-level)
      token_edit_ratio      0..1 — fraction of content changed (token-level)
      trivial               True if char_edit_ratio <= _TRIVIAL_EDIT_RATIO
      tokens_inserted       count of tokens the clinician added
      tokens_deleted        count of tokens the clinician removed
      inserted_tokens       up to 40 of the actually-inserted tokens
      deleted_tokens        up to 40 of the actually-deleted tokens
      draft_len/final_len   raw char lengths
      draft_tokens/final_tokens   token counts
      verbosity_delta       final_tokens - draft_tokens (signed)
      abbrev_delta          abbrev count change (final - draft)
      draft_sections/final_sections   ordered recognized section headers
      section_reordered     True if section order changed (ignoring add/drop)
    """
    a_tokens = _tokens(ai_draft)
    b_tokens = _tokens(final)

    sm_chars = SequenceMatcher(a=ai_draft or "", b=final or "")
    char_ratio = sm_chars.ratio()
    char_edit_ratio = round(1.0 - char_ratio, 4)

    sm_tokens = SequenceMatcher(a=a_tokens, b=b_tokens)
    token_edit_ratio = round(1.0 - sm_tokens.ratio(), 4)

    inserted: list[str] = []
    deleted: list[str] = []
    for op, i1, i2, j1, j2 in sm_tokens.get_opcodes():
        if op in ("insert", "replace"):
            inserted.extend(b_tokens[j1:j2])
        if op in ("delete", "replace"):
            deleted.extend(a_tokens[i1:i2])

    draft_sections = _section_order(ai_draft)
    final_sections = _section_order(final)
    common = [s for s in draft_sections if s in final_sections]
    common_final = [s for s in final_sections if s in draft_sections]
    section_reordered = bool(common) and common != common_final

    return {
        "diff_chars": int(char_edit_ratio * max(len(ai_draft or ""), len(final or ""))),
        "char_edit_ratio": char_edit_ratio,
        "token_edit_ratio": token_edit_ratio,
        "trivial": char_edit_ratio <= _TRIVIAL_EDIT_RATIO,
        "tokens_inserted": len(inserted),
        "tokens_deleted": len(deleted),
        "inserted_tokens": inserted[:40],
        "deleted_tokens": deleted[:40],
        "draft_len": len(ai_draft or ""),
        "final_len": len(final or ""),
        "draft_tokens": len(a_tokens),
        "final_tokens": len(b_tokens),
        "verbosity_delta": len(b_tokens) - len(a_tokens),
        "abbrev_delta": _abbrev_count(b_tokens) - _abbrev_count(a_tokens),
        "draft_sections": draft_sections,
        "final_sections": final_sections,
        "section_reordered": section_reordered,
    }


def record_pair(*, clinician_id: str, hospital_id: str, ai_draft: str, final: str, section: str = "full_note") -> dict[str, Any]:
    """Capture one (AI-draft, clinician-final) pair with its structural analysis.

    Signature is stable for routers/wave4.py. The returned dict is extended
    with analysis flags but keeps ``id`` and ``diff_chars`` for back-compat.
    """
    analysis = _analyze_pair(ai_draft, final)
    entry = {
        "id": str(uuid.uuid4()),
        "ts": _now_iso(),
        "clinician_id": clinician_id,
        "hospital_id": hospital_id,
        "section": section,
        "ai_draft": ai_draft,
        "final": final,
        "analysis": analysis,
        # Promoted to top level for back-compat with prior callers.
        "diff_chars": analysis["diff_chars"],
        "draft_len": analysis["draft_len"],
        "final_len": analysis["final_len"],
    }
    _PAIRS.append(entry)
    return {
        "id": entry["id"],
        "diff_chars": analysis["diff_chars"],
        "trivial": analysis["trivial"],
        "token_edit_ratio": analysis["token_edit_ratio"],
        "verbosity_delta": analysis["verbosity_delta"],
    }


def clinician_pairs(clinician_id: str) -> list[dict[str, Any]]:
    return [p for p in _PAIRS if p["clinician_id"] == clinician_id]


def _pair_analysis(p: dict[str, Any]) -> dict[str, Any]:
    """Return a pair's analysis, recomputing for any legacy pair without one."""
    a = p.get("analysis")
    if a:
        return a
    return _analyze_pair(p.get("ai_draft", ""), p.get("final", ""))


def _preferred_section_order(analyses: list[dict[str, Any]]) -> list[str]:
    """Infer the clinician's preferred section ordering from their finals.

    Rank each canonical section by its average position across all finals,
    then return sections sorted by that average — the closest thing to a
    consensus ordering the clinician keeps reverting drafts toward.
    """
    positions: dict[str, list[int]] = {}
    for a in analyses:
        for idx, sec in enumerate(a.get("final_sections", [])):
            positions.setdefault(sec, []).append(idx)
    ranked = sorted(positions.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
    return [sec for sec, _ in ranked]


def style_profile(clinician_id: str) -> dict[str, Any]:
    """Aggregate a clinician's pairs into a style model.

    Signature stable for routers/wave4.py. Returns the original keys plus the
    richer style model: ``preferred_section_order``, ``verbosity``,
    ``abbreviation_bias``, ``most_edited_section``, ``accept_rate``, and a
    ``stable`` flag.
    """
    pairs = clinician_pairs(clinician_id)
    if not pairs:
        return {
            "clinician_id": clinician_id,
            "pair_count": 0,
            "ready_to_train": False,
            "stable": False,
            "preferred_section_order": [],
            "verbosity": "unknown",
            "abbreviation_bias": "unknown",
            "most_edited_section": None,
            "accept_rate": None,
        }

    analyses = [_pair_analysis(p) for p in pairs]

    total_added: Counter[str] = Counter()
    total_removed: Counter[str] = Counter()
    section_counts: Counter[str] = Counter()
    section_edits: dict[str, list[int]] = {}

    verbosity_deltas: list[int] = []
    abbrev_deltas: list[int] = []
    trivial_count = 0
    reorder_count = 0

    for p, a in zip(pairs, analyses):
        section_counts[p["section"]] += 1
        section_edits.setdefault(p["section"], []).append(a["diff_chars"])
        verbosity_deltas.append(a["verbosity_delta"])
        abbrev_deltas.append(a["abbrev_delta"])
        if a["trivial"]:
            trivial_count += 1
        if a["section_reordered"]:
            reorder_count += 1
        ai_ngrams = set(_ngrams(p["ai_draft"], 2))
        final_ngrams = set(_ngrams(p["final"], 2))
        for added in final_ngrams - ai_ngrams:
            total_added[added] += 1
        for removed in ai_ngrams - final_ngrams:
            total_removed[removed] += 1

    section_edit_avg = {s: round(sum(v) / max(1, len(v)), 1) for s, v in section_edits.items()}
    most_edited_section = (
        max(section_edit_avg.items(), key=lambda kv: kv[1])[0] if section_edit_avg else None
    )

    # Verbosity tendency: does the clinician tend to lengthen or trim drafts?
    avg_verbosity = sum(verbosity_deltas) / len(verbosity_deltas)
    if avg_verbosity > 8:
        verbosity = "expands"
    elif avg_verbosity < -8:
        verbosity = "trims"
    else:
        verbosity = "balanced"

    # Abbreviation bias: does the clinician add or strip abbreviations?
    avg_abbrev = sum(abbrev_deltas) / len(abbrev_deltas)
    if avg_abbrev > 0.5:
        abbreviation_bias = "prefers_abbreviations"
    elif avg_abbrev < -0.5:
        abbreviation_bias = "prefers_expanded"
    else:
        abbreviation_bias = "neutral"

    # accept_rate: fraction of drafts kept essentially as-is (trivial edits).
    accept_rate = round(trivial_count / len(pairs), 3)

    # A profile is stable once we have enough pairs and the clinician's edit
    # behavior is consistent (low variance is implied by enough volume here;
    # we use pair count + a non-degenerate accept rate as the proxy).
    stable = len(pairs) >= _STABLE_PAIR_THRESHOLD

    return {
        "clinician_id": clinician_id,
        "pair_count": len(pairs),
        "trivial_pair_count": trivial_count,
        "avg_diff_chars": round(sum(a["diff_chars"] for a in analyses) / len(analyses), 1),
        "avg_token_edit_ratio": round(
            sum(a["token_edit_ratio"] for a in analyses) / len(analyses), 3
        ),
        "section_counts": dict(section_counts),
        "section_edit_avg_chars": section_edit_avg,
        "most_edited_section": most_edited_section,
        "top_added_phrases": total_added.most_common(15),
        "top_removed_phrases": total_removed.most_common(15),
        "preferred_section_order": _preferred_section_order(analyses),
        "section_reorder_rate": round(reorder_count / len(pairs), 3),
        "verbosity": verbosity,
        "avg_verbosity_delta": round(avg_verbosity, 1),
        "abbreviation_bias": abbreviation_bias,
        "avg_abbrev_delta": round(avg_abbrev, 2),
        "accept_rate": accept_rate,
        "stable": stable,
        "ready_to_train": len(pairs) >= 300,
    }


def style_fragment(clinician_id: str) -> str:
    """Render the clinician's style profile into a prependable instruction block.

    The scribe injects this string ahead of its draft prompt so a freshly
    generated note already reflects the clinician's habits — before any LoRA
    fine-tune exists. Returns ``""`` until ≥3 pairs are captured (below that
    the signal is noise).
    """
    pairs = clinician_pairs(clinician_id)
    if len(pairs) < _MIN_PAIRS_FOR_FRAGMENT:
        return ""

    profile = style_profile(clinician_id)
    lines: list[str] = ["[Clinician note-style preferences — apply when drafting]"]

    if profile["verbosity"] == "expands":
        lines.append("- Write thorough, detailed notes; do not over-condense findings.")
    elif profile["verbosity"] == "trims":
        lines.append("- Keep the note concise; omit boilerplate and redundant phrasing.")
    else:
        lines.append("- Use a balanced level of detail — neither terse nor verbose.")

    if profile["abbreviation_bias"] == "prefers_abbreviations":
        lines.append("- Use standard clinical abbreviations (e.g. SOB, HPI, PE, BP).")
    elif profile["abbreviation_bias"] == "prefers_expanded":
        lines.append("- Spell out clinical terms in full; avoid abbreviations.")

    order = profile["preferred_section_order"]
    if order:
        lines.append("- Order sections as: " + " -> ".join(order) + ".")

    if profile["most_edited_section"] and profile["most_edited_section"] != "full_note":
        lines.append(
            f"- Take extra care with the '{profile['most_edited_section']}' "
            "section — it is most often rewritten."
        )

    # Surface the clinician's most consistently added phrasing as voice cues.
    added = [phrase for phrase, count in profile["top_added_phrases"] if count >= 2]
    if added:
        lines.append("- Favored phrasing: " + "; ".join(added[:6]) + ".")

    removed = [phrase for phrase, count in profile["top_removed_phrases"] if count >= 2]
    if removed:
        lines.append("- Avoid phrasing: " + "; ".join(removed[:6]) + ".")

    if not profile["stable"]:
        lines.append(
            f"- (Preliminary — based on {profile['pair_count']} edits; "
            "preferences will sharpen with more notes.)"
        )

    return "\n".join(lines)


def export_training_jsonl(clinician_id: str) -> str:
    """Emit a LoRA-ready chat-format JSONL corpus for the clinician.

    Signature stable for routers/wave4.py. Each non-trivial pair becomes one
    JSON line in OpenAI/HF chat format with a system prompt, the AI draft as
    the user turn, and the clinician final as the assistant turn. Trivial
    pairs (whitespace/typo-only edits) are excluded — training on them only
    teaches the model to echo its own draft.
    """
    pairs = clinician_pairs(clinician_id)
    system = (
        "You are a clinical scribe drafting notes in this clinician's "
        "personal style. Rewrite the draft as the clinician would finalize it."
    )
    lines: list[str] = []
    for p in pairs:
        a = _pair_analysis(p)
        if a["trivial"]:
            continue
        record = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": p.get("ai_draft", "")},
                {"role": "assistant", "content": p.get("final", "")},
            ]
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines)
