"""Artifact validation + hydration.

In Pass 2 the model emits an artifact tree (prose + interactive blocks) where
data is bound BY REFERENCE — never inlined. This module:

  1. validates the tree against an allowlisted component palette (no raw HTML/JS,
     so no injection channel and no free-text place to smuggle PHI), and
  2. hydrates it deterministically: ``*_ref`` paths resolve against the executor
     results, ``{"$slot": id}`` markers and ``{Sx}`` text tokens resolve against
     the slot map. An invented ref/slot renders empty or ``[unavailable]`` — it
     can never fabricate a value.

The hydrated tree is what the frontend renders. The model only ever chose the
component types and which refs to bind.
"""
from __future__ import annotations

import re
from typing import Any

# Allowlisted interactive components. Anything else is dropped.
COMPONENTS = {
    "callout": {"text", "tone"},          # tone in {info, warning, success, critical}
    "stat": {"label", "value_ref", "unit"},
    "risk_gauge": {"title", "value_ref", "conformal_ref"},
    "table": {"title", "rows_ref", "columns"},
    "timeline": {"title", "events_ref"},
    "differential": {"title", "ranked_ref"},
    "card": {"title", "text"},
}

_SLOT_TOKEN = re.compile(r"\{(S\d+)\}")


def hydrate(tree: Any, results: list[dict[str, Any]], slots: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Validate + fill an artifact tree. Returns a clean list of rendered blocks."""
    by_id = {r["id"]: r.get("data") or {} for r in results}
    blocks = (tree or {}).get("blocks") if isinstance(tree, dict) else None
    if not isinstance(blocks, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in blocks:
        if not isinstance(raw, dict):
            continue
        btype = raw.get("type")
        allowed = COMPONENTS.get(btype)
        if allowed is None:
            continue  # unknown component — drop
        block: dict[str, Any] = {"type": btype}
        for field in allowed:
            if field not in raw:
                continue
            if field.endswith("_ref"):
                block[field.replace("_ref", "")] = _fill(_resolve(raw[field], by_id), slots)
            elif field == "columns":
                block["columns"] = [str(c) for c in raw["columns"]][:6] if isinstance(raw["columns"], list) else []
            else:  # plain text — fill slot tokens
                block[field] = _fill_text(str(raw[field]), slots)
        out.append(block)
    return out


def _resolve(path: Any, by_id: dict[str, Any]) -> Any:
    """Resolve a dotted ref like 's2.items' against the executor results."""
    if not isinstance(path, str):
        return None
    node: Any = by_id
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _fill(node: Any, slots: dict[str, dict[str, str]]) -> Any:
    """Replace ``{"$slot": id}`` markers with their real display value."""
    if isinstance(node, dict):
        if "$slot" in node:
            entry = slots.get(node["$slot"])
            return entry["value"] if entry else "[unavailable]"
        return {k: _fill(v, slots) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, slots) for v in node]
    return node


def _fill_text(text: str, slots: dict[str, dict[str, str]]) -> str:
    def sub(m: re.Match) -> str:
        entry = slots.get(m.group(1))
        return entry["value"] if entry else "[unavailable]"
    return _SLOT_TOKEN.sub(sub, text)


def plain_text(blocks: list[dict[str, Any]]) -> str:
    """Flatten callouts/cards to a text answer for the legacy `answer` field."""
    parts: list[str] = []
    for b in blocks:
        if b.get("type") in ("callout", "card") and b.get("text"):
            parts.append(b["text"])
    return "\n\n".join(parts)
